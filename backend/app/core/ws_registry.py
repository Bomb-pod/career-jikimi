"""`core/ws_registry` — 연결된 사용자의 WebSocket을 프로세스 메모리에 보관한다.

공개 표면 (`inception/application-design/components.md` § core/ws_registry):

    register(user_id, ws)          — 등록. 기존 연결은 교체한다 (BR-5.4)
    unregister(user_id, ws=None)   — 해제. 없어도 조용히 통과한다
    push_to_users(user_ids, load)  — 연결된 사용자에게만 밀어낸다 (BR-5.7)

**표면을 좁게 유지하는 것이 이 모듈의 설계다.** 이 딕셔너리가 확장의 병목이자
유일한 교체 지점이다 — Redis pub/sub으로 바꾸면 멀티 워커가 가능해진다. 함수가
셋뿐이면 그 교체가 이 파일 안에서 끝난다.

**이것이 CON-1(단일 프로세스)의 원인이다.** 워커를 늘리면 각 워커가 자기 레지스트리를
갖고, 다른 워커에 붙은 사용자에게 보낼 수 없다. `docker-entrypoint.sh`가
`--workers 1`로 고정하는 이유가 여기 있다 (FR-9.4).

**잠금이 없는 이유** — 단일 프로세스 + asyncio 단일 스레드다. 아래 함수들은 `await`
사이에서 딕셔너리를 읽고 쓰지만, 그 사이에 다른 코루틴이 끼어들어도 각 연산
자체(`dict.get`·`dict.__setitem__`·`dict.pop`)는 원자적이다. 끼어듦이 실제로 의미를
갖는 지점은 `unregister()`의 **소유권 확인** 하나이며, 그것을 아래에서 명시적으로
다룬다.

대응: FR-5.1, BR-5.4, BR-5.7, BR-5.8, CON-1.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket, status

logger = logging.getLogger(__name__)

#: `user_id -> 소켓`. **프로세스 메모리에만 있다.**
#:
#: 수명은 프로세스 수명이다 — 재시작하면 전부 사라지고 클라이언트가 재연결해
#: 복구한다. 그 사이 메시지는 다음 입장 시 히스토리로 받으므로 유실이 아니다.
#:
#: **사용자당 1개다** (FR-5.1). 두 번째 연결이 오면 첫 번째를 교체한다.
_connections: dict[int, WebSocket] = {}

#: 밀려난 연결에 보내는 프레임의 `type`. 클라이언트는 이 프레임을 받으면
#: 재연결하지 않는다 (BR-5.5).
SESSION_REPLACED_FRAME: dict[str, str] = {"type": "session_replaced"}


async def register(user_id: int, ws: WebSocket) -> None:
    """사용자의 연결을 등록한다. 기존 연결이 있으면 교체한다 (BR-5.4, FR-5.1).

    Args:
        user_id: `verify_token()`이 해석한 사용자 id. **인증 후에만 부른다.**
        ws: 이미 `accept()`된 소켓.

    **`session_replaced` 프레임을 보낸 뒤에 닫는 순서가 이 함수의 핵심이다.**
    그냥 닫으면 밀려난 탭이 네트워크 오류로 오인해 재연결을 시도하고, 두 탭이 서로를
    밀어내는 순환이 생긴다. 프레임이 그 순환을 끊는 신호다.

    **프레임 전송과 닫기가 실패해도 교체는 진행한다.** 기존 소켓이 이미 죽어 있는
    경우가 그렇다 — 그때 예외를 올리면 새 연결이 등록되지 못하고, 사용자는 죽은
    소켓 때문에 영영 붙지 못한다. 실패는 로그로만 남긴다(조용히 삼키지 않는다).
    """
    existing = _connections.get(user_id)

    # 먼저 새 연결을 등록한다. 아래 `close()`가 밀려난 쪽 핸들러의 `finally`를
    # 깨우는데, 그 핸들러가 `unregister()`를 부르기 전에 새 소켓이 자리에 있어야
    # 소유권 확인(아래 `unregister` 참조)이 올바르게 동작한다.
    _connections[user_id] = ws

    if existing is None or existing is ws:
        return

    logger.info("기존 WebSocket 연결을 교체합니다 (user_id=%s)", user_id)
    try:
        await existing.send_json(SESSION_REPLACED_FRAME)
    except Exception:
        # 이미 죽은 소켓이다. 알릴 대상이 없을 뿐이므로 교체를 막지 않는다.
        logger.info("밀려난 연결에 session_replaced를 보내지 못했습니다 (user_id=%s)", user_id)

    try:
        await existing.close(code=status.WS_1000_NORMAL_CLOSURE)
    except Exception:
        # 상대가 먼저 끊었거나 이미 닫혀 있다. 레지스트리에서는 이미 빠졌다.
        logger.info("밀려난 연결을 닫지 못했습니다 (user_id=%s)", user_id)


async def unregister(user_id: int, ws: WebSocket | None = None) -> None:
    """연결을 해제한다. 없으면 조용히 통과한다.

    Args:
        user_id: 해제할 사용자.
        ws: 해제를 요청하는 소켓. **주면 그 소켓이 현재 등록된 것일 때만 지운다.**

    `ws`가 왜 있는가 — `component-methods.md`의 서명은 `unregister(user_id)`이고
    그 호출은 지금도 유효하다. 선택 인자를 더한 것은 **밀려난 연결의 정리가 새
    연결을 지우는 사고**를 막기 위해서다:

        탭 A 연결 → register(1, A)
        탭 B 연결 → register(1, B)  → A에 session_replaced 후 닫음
        A의 핸들러가 깨어나 finally → unregister(1)  ← 여기서 B가 지워진다

    id만 보고 지우면 방금 붙은 B가 사라지고, B는 자기가 등록되어 있다고 믿은 채
    아무 메시지도 받지 못한다. 소켓 동일성을 확인하면 A의 정리는 아무 일도 하지
    않는다. WebSocket 핸들러는 **반드시 자기 소켓을 함께 넘긴다.**
    """
    current = _connections.get(user_id)
    if current is None:
        return
    if ws is not None and current is not ws:
        # 이미 다른 연결로 교체되었다 — 밀려난 쪽의 뒤늦은 정리다. 지우지 않는다.
        logger.debug("교체된 연결의 정리 요청을 무시합니다 (user_id=%s)", user_id)
        return
    del _connections[user_id]
    logger.info("WebSocket 연결을 해제했습니다 (user_id=%s)", user_id)


async def push_to_users(user_ids: list[int], payload: dict[str, Any]) -> None:
    """연결된 사용자에게만 프레임을 밀어낸다 (BR-5.7).

    Args:
        user_ids: 대상 사용자 id 목록. **발신자를 포함한다** (BR-5.8) — 다른 탭·기기의
            세션도 갱신되어야 한다. 중복은 클라이언트가 메시지 ID로 제거한다.
        payload: 그대로 JSON 직렬화되는 프레임. 봉투 모양은 `services.md`가 정한다.

    **연결이 없는 사용자는 조용히 건너뛴다 — 오류가 아니다.** 오프라인일 뿐이며 그
    사용자는 다음 입장 시 히스토리로 받는다. 미전송 큐를 만들지 않는다.

    **`try`가 루프 안에 있다.** 밖에 두면 소켓 하나의 실패가 나머지 참여자의 수신을
    막는다 — 그것이 이 함수에서 가장 틀리기 쉬운 지점이다. 전송 중 죽은 소켓은
    레지스트리에서 빼고 **나머지에게 계속 보낸다.**

    예외를 넓게 잡는 이유 — 끊긴 소켓에서 나오는 예외 종류가 상황마다 다르다
    (`WebSocketDisconnect`, ASGI 상태 위반의 `RuntimeError`, 드라이버 수준의
    `ConnectionError`). 종류를 열거하면 목록에 없는 하나가 루프를 통째로 죽인다.
    """
    # 같은 사용자가 두 번 들어오면 프레임도 두 번 간다 — 중복 제거는 발신 쪽의 몫이다.
    # `dict.fromkeys`는 순서를 보존한다(참여자 순서대로 도착하게 한다).
    for user_id in dict.fromkeys(user_ids):
        ws = _connections.get(user_id)
        if ws is None:
            continue
        try:
            await ws.send_json(payload)
        except Exception:
            logger.info("전송 중 소켓이 죽어 연결을 해제합니다 (user_id=%s)", user_id)
            await unregister(user_id, ws)


def is_connected(user_id: int) -> bool:
    """그 사용자의 연결이 등록되어 있는지. 진단과 테스트용 읽기 전용 조회다."""
    return user_id in _connections


def connection_count() -> int:
    """등록된 연결 수. 진단과 테스트용."""
    return len(_connections)


def clear() -> None:
    """레지스트리를 비운다. **소켓을 닫지 않는다.**

    테스트 격리용이다. 프로세스 종료 시에는 uvicorn이 열린 소켓을 닫고 각 핸들러의
    `finally`가 자기 항목을 지우므로 이 함수를 부를 필요가 없다.
    """
    _connections.clear()


__all__ = [
    "SESSION_REPLACED_FRAME",
    "clear",
    "connection_count",
    "is_connected",
    "push_to_users",
    "register",
    "unregister",
]

"""`core/ws_registry` — 연결된 사용자의 WebSocket을 프로세스 메모리에 보관한다.

공개 표면 (`inception/application-design/components.md` § core/ws_registry):

    register(user_id, ws)          — 등록. **기존 연결과 나란히 둔다**
    unregister(user_id, ws=None)   — 해제. 없어도 조용히 통과한다
    push_to_users(user_ids, load)  — 연결된 사용자의 **모든** 소켓에 밀어낸다 (BR-5.7)

**표면을 좁게 유지하는 것이 이 모듈의 설계다.** 이 딕셔너리가 확장의 병목이자
유일한 교체 지점이다 — Redis pub/sub으로 바꾸면 멀티 워커가 가능해진다. 함수가
셋뿐이면 그 교체가 이 파일 안에서 끝난다.

## 사용자당 여러 연결 (2026-07-31 변경, 이전 BR-5.4를 대체)

원래는 **사용자당 1개**였다. 두 번째 연결이 오면 첫 번째에 `session_replaced`를
보내고 닫았다 — 한 사람이 여러 탭을 열면 앞 탭이 조용히 죽는 것을 막기 위한
장치였고, 그때는 화면이 하나뿐이라 그 가정이 맞았다.

지금은 방을 **새 창으로 연다.** 목록 창과 대화 창이 동시에 살아 있어야 하고,
방 여러 개를 나란히 띄우는 것도 정상 사용이다. 연결을 하나로 묶으면 창을 열
때마다 앞 창이 죽어 그 사용법 자체가 성립하지 않는다.

그래서 값을 `set[WebSocket]`으로 바꿨다. 바뀐 것과 바뀌지 않은 것:

| | 이전 | 지금 |
|---|---|---|
| 두 번째 연결 | 첫 번째를 닫음 | 나란히 유지 |
| `session_replaced` | 보냄 | **보내지 않는다** |
| 브로드캐스트 | 소켓 1개 | 그 사용자의 **전 소켓** |
| 죽은 소켓 | 전송 중 감지해 제거 | 같음 |

**중복 수신은 문제가 아니다.** 같은 메시지가 창 두 개에 각각 도착하며, 각 창은
자기 목록에 대해 메시지 ID로 중복을 접는다(BR-5.8이 이미 발신자 본인에게도
푸시하기로 정해 둔 것과 같은 이유다).

**`session_replaced` 프레임은 더 이상 나가지 않는다.** 클라이언트(`wsClient.ts`)는
그 프레임을 여전히 처리할 줄 알지만 받을 일이 없다 — 서버를 되돌리는 날 그쪽을
함께 고치지 않아도 되도록 남겨 둔다.

**이것이 CON-1(단일 프로세스)의 원인이다.** 워커를 늘리면 각 워커가 자기 레지스트리를
갖고, 다른 워커에 붙은 사용자에게 보낼 수 없다. `docker-entrypoint.sh`가
`--workers 1`로 고정하는 이유가 여기 있다 (FR-9.4).

**잠금이 없는 이유** — 단일 프로세스 + asyncio 단일 스레드다. 아래 함수들은 `await`
사이에서 자료구조를 읽고 쓰지만, 각 연산 자체(`set.add`·`set.discard`)는 원자적이다.
`push_to_users()`가 **집합의 사본을 순회하는 것**이 유일한 주의 지점이며, 그것을
아래에서 명시적으로 다룬다.

대응: FR-5.1, BR-5.7, BR-5.8, CON-1.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

#: `user_id -> 그 사용자의 소켓들`. **프로세스 메모리에만 있다.**
#:
#: 수명은 프로세스 수명이다 — 재시작하면 전부 사라지고 클라이언트가 재연결해
#: 복구한다. 그 사이 메시지는 다음 입장 시 히스토리로 받으므로 유실이 아니다.
#:
#: **빈 집합을 남기지 않는다.** 마지막 소켓이 빠지면 키까지 지운다 — 남겨두면
#: `is_connected()`가 아무도 없는 사용자에게 참을 준다.
_connections: dict[int, set[WebSocket]] = {}

#: 밀려난 연결에 보내던 프레임. **이제 서버는 보내지 않는다** (위 § 참조).
#: 클라이언트가 아직 이 타입을 처리하므로 규약의 기록으로 남긴다.
SESSION_REPLACED_FRAME: dict[str, str] = {"type": "session_replaced"}


async def register(user_id: int, ws: WebSocket) -> None:
    """사용자의 연결을 등록한다 (FR-5.1).

    Args:
        user_id: `verify_token()`이 해석한 사용자 id. **인증 후에만 부른다.**
        ws: 이미 `accept()`된 소켓.

    **기존 연결을 닫지 않는다.** 같은 사용자의 창이 여럿 살아 있는 것이 정상이며,
    그것이 방을 새 창으로 여는 사용법의 전제다. 같은 소켓을 두 번 등록해도
    집합이라 한 번만 들어간다.
    """
    sockets = _connections.setdefault(user_id, set())
    sockets.add(ws)
    logger.info(
        "WebSocket 연결을 등록했습니다 (user_id=%s, 이 사용자의 연결 %d개)",
        user_id,
        len(sockets),
    )


async def unregister(user_id: int, ws: WebSocket | None = None) -> None:
    """연결을 해제한다. 없으면 조용히 통과한다.

    Args:
        user_id: 해제할 사용자.
        ws: 해제를 요청하는 소켓. **주면 그 소켓 하나만 뺀다.** 생략하면 그
            사용자의 연결을 전부 뺀다(진단·정리용이며 핸들러는 쓰지 않는다).

    **WebSocket 핸들러는 반드시 자기 소켓을 함께 넘긴다.** id만 보고 전부 지우면
    한 창을 닫았을 때 다른 창의 연결까지 레지스트리에서 사라지고, 그 창은 자기가
    등록되어 있다고 믿은 채 아무 메시지도 받지 못한다. 사용자당 소켓이 하나였을
    때는 "밀려난 연결의 뒤늦은 정리"가 이 사고의 경로였고, 여러 개인 지금은 창을
    닫는 평범한 동작이 그 경로다 — 이 인자가 그때보다 더 중요해졌다.
    """
    sockets = _connections.get(user_id)
    if sockets is None:
        return

    if ws is None:
        del _connections[user_id]
        logger.info("WebSocket 연결을 전부 해제했습니다 (user_id=%s)", user_id)
        return

    sockets.discard(ws)
    if not sockets:
        # 빈 집합을 남기지 않는다 — `is_connected()`가 참을 주게 된다.
        del _connections[user_id]
    logger.info(
        "WebSocket 연결을 해제했습니다 (user_id=%s, 남은 연결 %d개)",
        user_id,
        len(sockets),
    )


async def push_to_users(user_ids: list[int], payload: dict[str, Any]) -> None:
    """연결된 사용자의 **모든** 소켓에 프레임을 밀어낸다 (BR-5.7).

    Args:
        user_ids: 대상 사용자 id 목록. **발신자를 포함한다** (BR-5.8) — 다른 창·기기의
            세션도 갱신되어야 한다. 중복은 클라이언트가 메시지 ID로 제거한다.
        payload: 그대로 JSON 직렬화되는 프레임. 봉투 모양은 `services.md`가 정한다.

    **연결이 없는 사용자는 조용히 건너뛴다 — 오류가 아니다.** 오프라인일 뿐이며 그
    사용자는 다음 입장 시 히스토리로 받는다. 미전송 큐를 만들지 않는다.

    **`try`가 안쪽 루프 안에 있다.** 밖에 두면 소켓 하나의 실패가 나머지 참여자의,
    나아가 같은 사용자의 다른 창의 수신까지 막는다 — 그것이 이 함수에서 가장 틀리기
    쉬운 지점이다. 전송 중 죽은 소켓은 레지스트리에서 빼고 **나머지에게 계속 보낸다.**

    **집합의 사본(`list(...)`)을 순회한다.** 아래 `unregister()`가 순회 중인 그
    집합에서 원소를 지우므로, 원본을 그대로 돌면 `RuntimeError: Set changed size
    during iteration`이 난다 — 소켓이 죽은 순간에만 나타나는 실패라 평시 테스트로는
    드러나지 않는다.

    예외를 넓게 잡는 이유 — 끊긴 소켓에서 나오는 예외 종류가 상황마다 다르다
    (`WebSocketDisconnect`, ASGI 상태 위반의 `RuntimeError`, 드라이버 수준의
    `ConnectionError`). 종류를 열거하면 목록에 없는 하나가 루프를 통째로 죽인다.
    """
    # 같은 사용자가 두 번 들어오면 프레임도 두 번 간다 — 중복 제거는 발신 쪽의 몫이다.
    # `dict.fromkeys`는 순서를 보존한다(참여자 순서대로 도착하게 한다).
    for user_id in dict.fromkeys(user_ids):
        sockets = _connections.get(user_id)
        if not sockets:
            continue
        for ws in list(sockets):
            try:
                await ws.send_json(payload)
            except Exception:
                logger.info("전송 중 소켓이 죽어 연결을 해제합니다 (user_id=%s)", user_id)
                await unregister(user_id, ws)


def is_connected(user_id: int) -> bool:
    """그 사용자의 연결이 하나라도 등록되어 있는지. 진단과 테스트용 읽기 전용 조회다."""
    return bool(_connections.get(user_id))


def connection_count() -> int:
    """등록된 **소켓** 총 개수. 사용자 수가 아니다. 진단과 테스트용."""
    return sum(len(sockets) for sockets in _connections.values())


def connection_count_for(user_id: int) -> int:
    """그 사용자의 소켓 개수. 여러 창이 나란히 붙어 있는지 확인하는 데 쓴다."""
    return len(_connections.get(user_id, ()))


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
    "connection_count_for",
    "is_connected",
    "push_to_users",
    "register",
    "unregister",
]

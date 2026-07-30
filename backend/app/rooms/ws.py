"""`GET /ws` — WebSocket 수명주기와 첫 프레임 인증 (W5).

**클라이언트가 보내는 것은 인증 프레임 하나뿐이다** (ADR-001). 전송이 HTTP이므로
인증 이후의 수신 루프는 사실상 비어 있고, 그 루프의 유일한 목적은 **연결 종료 감지**다.

**왜 헤더가 아니라 첫 프레임인가** — 브라우저는 WebSocket 연결에 커스텀 헤더를 붙일 수
없다(CON-4). 토큰을 쿼리스트링에 넣는 대안은 URL이 액세스 로그·프록시 로그·브라우저
히스토리에 남아 더 나쁘다. 그래서 FR-1.3이 첫 프레임 인증을 요구한다.

대응: FR-1.3, FR-5.1, BR-5.4, BR-5.6.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Final

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from app.auth.exceptions import InvalidToken
from app.auth.security import verify_token
from app.core.ws_registry import register, unregister

logger = logging.getLogger(__name__)

router = APIRouter()

#: 첫 프레임을 기다리는 시간 (BR-5.6, ASM-5).
#:
#: 정상 클라이언트는 `onopen`에서 즉시 보내므로 5초는 충분하고, 방치된 연결을 오래
#: 붙들지 않는 값이다. 인증 없는 연결이 쌓이면 그 자체가 자원 소모다.
#:
#: 모듈 전역인 이유 — 테스트가 이 값을 줄여 타임아웃 경로를 5초 기다리지 않고
#: 검증한다. 핸들러가 호출 시점에 이 이름을 읽으므로 교체가 즉시 반영된다.
WS_AUTH_TIMEOUT_SECONDS: float = 5.0

#: 인증 실패의 이유. **클라이언트에게 세부를 알리지 않는다** — "만료됨"과 "위조됨"을
#: 구분해 주면 토큰을 탐색할 여지가 생긴다. 로그에도 토큰 원문은 남기지 않는다.
_REASON_TIMEOUT: Final[str] = "auth_timeout"
_REASON_EXPECTED_AUTH: Final[str] = "expected_auth_frame"
# S105를 끄는 이유 — 이름에 TOKEN이 들어가 ruff가 비밀 리터럴로 오인한다. 이 값은
# 비밀이 아니라 **클라이언트에게 보내는 실패 사유 문자열**이며, `services.md`의
# 프레임 봉투가 `{"type": "auth_error", "reason": "invalid_token"}`으로 정한 값이다.
_REASON_INVALID_TOKEN: Final[str] = "invalid_token"  # noqa: S105


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """연결을 받아 인증하고, 끊길 때까지 유지한다 — W5.

    흐름은 `business-logic-model.md` W5 그대로다:

        accept → 5초 안에 첫 프레임 → type == 'auth' → verify_token()
               → register()(기존 연결 교체) → auth_ok → 수신 루프 → unregister

    **`unregister()`가 모든 종료 경로에서 돈다.** `finally`에 두는 것이 그 장치다 —
    예외로 빠져나가는 경로에서 빠뜨리면 죽은 소켓이 레지스트리에 남고, 그 사용자는
    다음 브로드캐스트에서 "연결된 것으로 보이지만 받지 못하는" 상태가 된다.

    **자기 소켓을 함께 넘긴다.** 밀려난 연결이 뒤늦게 정리될 때 새 연결을 지우는
    사고를 막는다(`ws_registry.unregister()` 참조).
    """
    await websocket.accept()

    user_id: int | None = None
    try:
        user_id = await _authenticate(websocket)
        if user_id is None:
            # 실패 응답과 종료는 `_authenticate()`가 이미 처리했다.
            return

        # 기존 연결이 있으면 여기서 교체된다 — session_replaced를 보낸 뒤 닫는다
        # (BR-5.4). 등록이 auth_ok보다 먼저인 이유는, 클라이언트가 auth_ok를 보고
        # 화면을 열었는데 아직 등록되지 않아 그 사이 메시지를 놓치는 창을 없애기
        # 위해서다.
        await register(user_id, websocket)
        await websocket.send_json({"type": "auth_ok"})
        logger.info("WebSocket 인증에 성공했습니다 (user_id=%s)", user_id)

        await _wait_until_disconnect(websocket)
    except WebSocketDisconnect:
        # 정상적인 종료 경로다. 사용자가 탭을 닫거나 새로고침하면 여기로 온다.
        logger.debug("WebSocket 연결이 끊겼습니다 (user_id=%s)", user_id)
    finally:
        if user_id is not None:
            await unregister(user_id, websocket)


async def _authenticate(websocket: WebSocket) -> int | None:
    """첫 프레임으로 인증한다. 성공하면 `user_id`, 실패하면 `None`.

    실패 시 `auth_error`를 보내고 연결을 닫는다 — 호출자는 그냥 반환하면 된다.

    **인증 전에 도착한 다른 프레임은 처리하지 않는다** (FR-1.3, BR-5.6). 무시하고
    다음 프레임을 기다리는 것도 아니다 — 그러면 인증 없는 연결이 프레임을 계속
    보내며 5초를 버틸 수 있다. 첫 프레임이 `auth`가 아니면 그 자리에서 끊는다.
    """
    try:
        message = await asyncio.wait_for(websocket.receive(), timeout=WS_AUTH_TIMEOUT_SECONDS)
    except TimeoutError:
        # 5초 안에 아무것도 오지 않았다 (BR-5.6). 이유를 알려주고 끊는다 —
        # 조용히 끊으면 클라이언트가 네트워크 문제로 오인해 재연결을 반복한다.
        logger.info("WebSocket 인증 타임아웃 (%.1f초)", WS_AUTH_TIMEOUT_SECONDS)
        await _reject(websocket, _REASON_TIMEOUT)
        return None

    if message["type"] == "websocket.disconnect":
        # 인증 전에 클라이언트가 끊었다. 보낼 곳이 없으므로 아무것도 하지 않는다.
        return None

    raw = _frame_text(message)
    if raw is None:
        await _reject(websocket, _REASON_EXPECTED_AUTH)
        return None

    try:
        frame: Any = json.loads(raw)
    except json.JSONDecodeError:
        # JSON이 아닌 첫 프레임. 형식 오류와 인증 실패를 구분해 알려줄 이유가 없다.
        await _reject(websocket, _REASON_EXPECTED_AUTH)
        return None

    if not isinstance(frame, dict) or frame.get("type") != "auth":
        await _reject(websocket, _REASON_EXPECTED_AUTH)
        return None

    token = frame.get("token")
    if not isinstance(token, str) or not token:
        await _reject(websocket, _REASON_INVALID_TOKEN)
        return None

    try:
        # **HTTP 경로와 같은 함수다** (BR-1.5). 검증 로직이 두 벌이 되면 반드시
        # 어긋난다 — U3이 이 함수를 FastAPI 의존성이 아닌 순수 함수로 노출한
        # 이유가 그것이다.
        return verify_token(token)
    except InvalidToken:
        logger.info("WebSocket 인증 실패 — 유효하지 않은 토큰")
        await _reject(websocket, _REASON_INVALID_TOKEN)
        return None


def _frame_text(message: dict[str, Any]) -> str | None:
    """ASGI 수신 메시지에서 텍스트를 꺼낸다. 텍스트 프레임이 아니면 `None`.

    `receive_text()`를 쓰지 않는 이유 — 클라이언트가 바이너리 프레임을 보내면 그
    헬퍼는 `KeyError`로 죽는다. 첫 프레임의 형태를 우리가 통제할 수 없으므로 원시
    메시지를 직접 다룬다.
    """
    text = message.get("text")
    if isinstance(text, str):
        return text
    payload = message.get("bytes")
    if isinstance(payload, bytes):
        # 브라우저가 문자열을 바이너리로 보내는 구현도 있다. UTF-8로 읽어본다.
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return None
    return None


async def _reject(websocket: WebSocket, reason: str) -> None:
    """`auth_error`를 보내고 연결을 닫는다 (BR-5.6).

    **프레임을 먼저 보내고 닫는다.** 그냥 닫으면 클라이언트가 네트워크 오류로 오인해
    재연결을 반복한다 — `session_replaced`가 같은 이유로 같은 순서를 쓴다(BR-5.4).

    전송·종료 실패를 삼키는 이유 — 이 경로는 이미 실패 처리 중이며, 여기서 예외가
    올라가면 호출자의 `finally`가 도는 것 말고는 할 수 있는 일이 없다.
    """
    try:
        await websocket.send_json({"type": "auth_error", "reason": reason})
    except Exception:
        logger.info("auth_error 프레임을 보내지 못했습니다 (reason=%s)", reason)
    try:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
    except Exception:
        logger.info("인증 실패 연결을 닫지 못했습니다 (reason=%s)", reason)


async def _wait_until_disconnect(websocket: WebSocket) -> None:
    """연결이 끊길 때까지 대기한다. **받은 것은 버린다.**

    인증 이후 클라이언트는 아무것도 보내지 않는다(ADR-001). 그래도 루프가 필요한
    이유는 ASGI에서 **연결 종료가 수신 이벤트로 온다**는 데 있다 — 여기서 기다리지
    않으면 핸들러가 곧장 반환하고, 반환하면 uvicorn이 연결을 닫는다.

    받은 프레임을 처리하지 않고 버리는 것이 의도다. 서버가 해석하는 클라이언트 →
    서버 프레임은 인증 하나뿐이며(`services.md`), 그 외를 처리하기 시작하면 HTTP로
    옮겨둔 요청-응답이 WebSocket 위로 되돌아온다.
    """
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


__all__ = ["WS_AUTH_TIMEOUT_SECONDS", "router"]

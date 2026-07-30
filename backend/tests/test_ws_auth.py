"""`/ws` 첫 프레임 인증과 수명주기 — FR-1.3·FR-5.1의 수용 기준.

**실제 WebSocket으로 돈다.** `test_ws_registry.py`가 가짜 소켓으로 레지스트리의
분기를 보는 데 반해, 여기서는 핸드셰이크·프레임 왕복·종료 감지처럼 **실제 소켓이
있어야만 확인되는 것**을 본다.

**`app.main.app`이 아니라 라우터만 담은 작은 앱을 쓰는 이유** — `TestClient`를
컨텍스트 매니저로 열면 lifespan이 돌고, 그 lifespan은 실제 DB 연결을 최대 30초
기다린다(FR-9.2). 컨텍스트 매니저로 열지 않으면 세션마다 별도의 이벤트 루프가
생겨 **두 연결이 서로를 밀어내는 경로(BR-5.4)를 재현할 수 없다.** 라우터만 담은
앱은 lifespan이 없어 둘 다 피한다. 이 엔드포인트는 DB를 쓰지 않는다 —
`verify_token()`이 동기 순수 함수이기 때문이다(그것이 U3이 그렇게 만든 이유다).

`app.main.app`에 실제로 등록되어 있는지는 아래 마지막 테스트가 따로 확인한다.

대응: FR-1.3, FR-5.1, BR-5.4, BR-5.6.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.security import create_token
from app.core import ws_registry
from app.rooms import ws as ws_module

#: 타임아웃 경로를 5초 기다리지 않기 위한 값. 실제 값은 `WS_AUTH_TIMEOUT_SECONDS`(5초)이며
#: 그 결정 근거는 ASM-5에 있다. 여기서 재는 것은 "값이 5초인가"가 아니라
#: **"시간이 지나면 끊는가"** 이므로 짧게 줄여도 검증 대상이 그대로다.
FAST_TIMEOUT = 0.15


@pytest.fixture
def ws_client() -> Iterator[TestClient]:
    """`/ws`만 담은 앱의 `TestClient`. 레지스트리는 앞뒤로 비운다."""
    app = FastAPI()
    app.include_router(ws_module.router)
    ws_registry.clear()
    with TestClient(app) as client:
        yield client
    ws_registry.clear()


def _auth_frame(token: str) -> str:
    return json.dumps({"type": "auth", "token": token})


def _wait_until_disconnected(user_id: int, timeout: float = 2.0) -> bool:
    """레지스트리에서 그 사용자가 사라질 때까지 기다린다. 시간이 다하면 `False`.

    **연결 종료 정리가 비동기이기 때문에 필요하다.** 클라이언트 쪽 `with` 블록을
    빠져나온 시점에 서버 핸들러의 `finally`가 아직 돌지 않았을 수 있다 — 그 둘은
    다른 스레드에서 진행한다. 여기서 곧바로 단정하면 구현이 맞아도 간헐적으로
    붉어진다(그런 테스트는 결국 무시된다).

    고정 `sleep`을 쓰지 않는 이유 — 짧으면 흔들리고 길면 매번 그 시간을 낸다.
    조건이 충족되면 즉시 반환한다.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not ws_registry.is_connected(user_id):
            return True
        time.sleep(0.01)
    return not ws_registry.is_connected(user_id)


# --------------------------------------------------------------------------
# 성공 경로
# --------------------------------------------------------------------------
def test_valid_first_frame_authenticates_and_registers(ws_client: TestClient) -> None:
    """FR-1.3 — 첫 프레임이 `{type:'auth', token}`이면 `auth_ok`가 오고 등록된다."""
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(_auth_frame(create_token(42)))

        assert socket.receive_json() == {"type": "auth_ok"}
        assert ws_registry.is_connected(42)


def test_the_registry_is_cleaned_up_when_the_client_disconnects(ws_client: TestClient) -> None:
    """종료 시 `unregister()`가 돈다.

    남으면 그 사용자는 "연결된 것으로 보이지만 받지 못하는" 상태가 되고,
    브로드캐스트마다 죽은 소켓에 대고 보내게 된다.
    """
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(_auth_frame(create_token(7)))
        assert socket.receive_json() == {"type": "auth_ok"}
        assert ws_registry.is_connected(7)

    assert _wait_until_disconnected(7)


def test_the_server_pushes_frames_over_the_authenticated_connection(ws_client: TestClient) -> None:
    """등록된 연결로 서버가 밀어낸다 — FR-5.1의 멀티플렉싱 경로.

    `push_to_users()`가 레지스트리의 소켓을 실제로 쓸 수 있는지 확인한다. 가짜
    소켓 테스트는 그것을 보여주지 못한다.
    """
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(_auth_frame(create_token(11)))
        assert socket.receive_json() == {"type": "auth_ok"}

        pushed = {"type": "message", "room_id": 3, "message": {"id": 99}}
        ws_client.portal.call(ws_registry.push_to_users, [11], pushed)  # type: ignore[union-attr]

        assert socket.receive_json() == pushed


# --------------------------------------------------------------------------
# 사용자당 1개 (BR-5.4)
# --------------------------------------------------------------------------
def test_a_second_connection_replaces_the_first_with_a_frame(ws_client: TestClient) -> None:
    """**BR-5.4** — 두 번째 연결이 첫 번째에 `session_replaced`를 보낸 뒤 닫는다.

    프레임 없이 닫으면 밀려난 탭이 네트워크 오류로 오인해 재연결하고, 두 탭이 서로를
    밀어내는 순환이 생긴다. 클라이언트의 `replaced` 플래그가 그 순환을 끊는 나머지
    절반이다 (BR-5.5, `wsClient.test.ts`).
    """
    token = create_token(5)
    with ws_client.websocket_connect("/ws") as first:
        first.send_text(_auth_frame(token))
        assert first.receive_json() == {"type": "auth_ok"}

        with ws_client.websocket_connect("/ws") as second:
            second.send_text(_auth_frame(token))
            assert second.receive_json() == {"type": "auth_ok"}

            # 밀려난 쪽이 받는 것은 **프레임이 먼저**다.
            assert first.receive_json() == {"type": "session_replaced"}
            # 그리고 서버가 닫는다.
            assert first.receive()["type"] == "websocket.close"

            # 새 연결이 자리를 지킨다 — 밀려난 쪽의 정리가 이것을 지우면 안 된다.
            assert ws_registry.is_connected(5)
            pushed = {"type": "message", "room_id": 1}
            ws_client.portal.call(ws_registry.push_to_users, [5], pushed)  # type: ignore[union-attr]
            assert second.receive_json() == pushed


# --------------------------------------------------------------------------
# 실패 경로 (BR-5.6)
# --------------------------------------------------------------------------
def test_a_frame_that_is_not_auth_is_rejected(ws_client: TestClient) -> None:
    """인증 전 다른 프레임은 **처리하지 않는다** (FR-1.3).

    무시하고 다음 프레임을 기다리지도 않는다 — 그러면 인증 없는 연결이 프레임을
    계속 보내며 타임아웃을 우회할 수 있다.
    """
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "message", "body": "안녕"}))

        frame = socket.receive_json()
        assert frame["type"] == "auth_error"
        assert frame["reason"] == "expected_auth_frame"
        assert socket.receive()["type"] == "websocket.close"
    assert ws_registry.connection_count() == 0


def test_a_malformed_first_frame_is_rejected(ws_client: TestClient) -> None:
    """JSON이 아닌 첫 프레임도 같은 경로로 끊는다 (경계 사례).

    여기서 파싱 예외가 올라가면 500 대신 조용한 연결 끊김이 되고, 클라이언트는
    이유를 알 수 없다.
    """
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text("이건 JSON이 아니다")

        assert socket.receive_json()["type"] == "auth_error"
        assert socket.receive()["type"] == "websocket.close"


def test_an_invalid_token_is_rejected(ws_client: TestClient) -> None:
    """서명이 맞지 않는 토큰은 `auth_error` 후 종료다 (BR-5.6).

    "만료됨"과 "위조됨"을 구분해 알려주지 않는다 — 구분하면 토큰을 탐색할 여지가
    생긴다.
    """
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(_auth_frame("이건.유효한.토큰이아니다"))

        frame = socket.receive_json()
        assert frame["type"] == "auth_error"
        assert frame["reason"] == "invalid_token"
        assert socket.receive()["type"] == "websocket.close"
    assert ws_registry.connection_count() == 0


def test_an_auth_frame_without_a_token_is_rejected(ws_client: TestClient) -> None:
    """`token`이 없는 `auth` 프레임도 거절된다 (경계 사례).

    `None`이 `verify_token()`까지 흘러가면 그 안에서 타입 오류가 나고 500이 된다.
    """
    with ws_client.websocket_connect("/ws") as socket:
        socket.send_text(json.dumps({"type": "auth"}))

        assert socket.receive_json()["type"] == "auth_error"
        assert socket.receive()["type"] == "websocket.close"


def test_a_silent_client_is_disconnected_after_the_timeout(
    ws_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**BR-5.6** — 제한 시간 안에 인증 프레임이 없으면 끊는다.

    실제 값은 5초다. 테스트에서 5초를 기다리지 않으려고 상수를 줄인다 — 재는 것은
    값이 아니라 **시간이 지나면 끊는다**는 동작이다.

    끊기 전에 이유를 보내는 이유 — 조용히 끊으면 클라이언트가 네트워크 문제로
    오인해 재연결을 반복한다.
    """
    monkeypatch.setattr(ws_module, "WS_AUTH_TIMEOUT_SECONDS", FAST_TIMEOUT)

    with ws_client.websocket_connect("/ws") as socket:
        frame = socket.receive_json()

        assert frame["type"] == "auth_error"
        assert frame["reason"] == "auth_timeout"
        assert socket.receive()["type"] == "websocket.close"
    assert ws_registry.connection_count() == 0


# --------------------------------------------------------------------------
# 등록 위치
# --------------------------------------------------------------------------
def test_the_ws_route_is_registered_on_the_real_app() -> None:
    """`/ws`가 실제 앱에 있고 **SPA 폴백보다 먼저** 등록되어 있다.

    위 테스트들이 작은 앱을 쓰므로, 실제 앱에 붙었는지는 여기서 확인한다. 폴백보다
    뒤에 등록하면 catch-all에 가려진다.
    """
    from app.main import app

    paths = [getattr(route, "path", None) for route in app.routes]
    assert "/ws" in paths

    spa_index = paths.index("/{spa_path:path}") if "/{spa_path:path}" in paths else len(paths)
    assert paths.index("/ws") < spa_index


def test_the_room_routes_are_registered_before_the_spa_fallback() -> None:
    """방 라우터도 같은 규칙을 따른다.

    SPA 폴백이 `/{spa_path:path}` catch-all이라 뒤에 등록된 GET 경로는 전부 가려진다.
    개발 구성에서는 `static/`이 없어 폴백 자체가 없으므로, 있을 때만 순서를 본다.
    """
    from app.main import app

    paths: list[Any] = [getattr(route, "path", None) for route in app.routes]
    assert "/rooms" in paths
    assert "/rooms/{room_id}" in paths

    if "/{spa_path:path}" in paths:
        assert paths.index("/rooms/{room_id}") < paths.index("/{spa_path:path}")

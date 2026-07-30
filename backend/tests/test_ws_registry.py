"""`core/ws_registry` — 사용자당 1개 연결과 브로드캐스트의 실패 격리.

**가짜 소켓으로 검증한다.** 실제 WebSocket이 필요 없는 이유 — 이 모듈이 소켓에게
요구하는 것은 `send_json()`과 `close()` 둘뿐이고, 검증 대상은 **호출 순서**(프레임을
보낸 뒤에 닫는가)와 **실패 격리**(한 소켓이 죽어도 나머지가 받는가)다. 실제 소켓을
쓰면 그 두 가지가 이벤트 루프와 전송 타이밍 뒤에 가려진다.

핸드셰이크와 인증은 실제 소켓으로 `test_ws_auth.py`가 검증한다.

대응: FR-5.1, BR-5.4, BR-5.7, BR-5.8.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core import ws_registry


class FakeSocket:
    """`send_json`과 `close`만 기록하는 가짜 소켓.

    `dead=True`면 `send_json()`이 던진다 — 전송 중 죽은 소켓을 흉내낸다.
    `closed_after`에 닫힌 시점의 전송 개수를 남겨, **프레임을 보낸 뒤에 닫혔는지**를
    사후에 판정할 수 있게 한다 (BR-5.4).
    """

    def __init__(self, *, dead: bool = False) -> None:
        self.sent: list[dict[str, Any]] = []
        self.closed = False
        self.close_code: int | None = None
        self.closed_after: int | None = None
        self.dead = dead

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self.dead:
            raise RuntimeError("소켓이 이미 끊겼습니다")
        self.sent.append(payload)

    async def close(self, code: int = 1000) -> None:
        self.closed = True
        self.close_code = code
        self.closed_after = len(self.sent)


@pytest.fixture(autouse=True)
def clean_registry() -> Any:
    """테스트마다 레지스트리를 비운다. 프로세스 전역 상태라 새지 않게 앞뒤로 지운다."""
    ws_registry.clear()
    yield
    ws_registry.clear()


def _as_socket(fake: FakeSocket) -> Any:
    """`FakeSocket`을 `WebSocket` 자리에 넣는다.

    타입 무시를 한곳에 모으는 헬퍼다 — 테스트마다 `# type: ignore`를 흩뿌리면
    나중에 진짜 타입 오류가 섞여도 눈에 띄지 않는다.
    """
    return fake


# --------------------------------------------------------------------------
# 등록·해제
# --------------------------------------------------------------------------
async def test_register_then_unregister() -> None:
    """등록하면 연결된 상태가 되고, 해제하면 사라진다."""
    socket = FakeSocket()

    await ws_registry.register(1, _as_socket(socket))
    assert ws_registry.is_connected(1)

    await ws_registry.unregister(1, _as_socket(socket))
    assert not ws_registry.is_connected(1)


async def test_unregister_of_an_unknown_user_is_silent() -> None:
    """등록된 적 없는 사용자를 해제해도 조용히 통과한다.

    예외를 던지면 WebSocket 핸들러의 `finally`가 인증 실패 경로에서도 터진다.
    """
    await ws_registry.unregister(999)

    assert ws_registry.connection_count() == 0


# --------------------------------------------------------------------------
# 사용자당 1개 (BR-5.4)
# --------------------------------------------------------------------------
async def test_second_connection_sends_session_replaced_before_closing() -> None:
    """**BR-5.4의 핵심** — 밀려난 연결에 프레임을 보낸 **뒤** 닫는다.

    그냥 닫으면 밀려난 탭이 네트워크 오류로 오인해 재연결하고, 두 탭이 서로를
    밀어내는 순환이 생긴다. `closed_after`가 전송 개수를 기억하므로 순서를
    사후에 판정할 수 있다.
    """
    first = FakeSocket()
    second = FakeSocket()

    await ws_registry.register(1, _as_socket(first))
    await ws_registry.register(1, _as_socket(second))

    assert first.sent == [{"type": "session_replaced"}]
    assert first.closed
    # 닫힌 시점에 이미 1개를 보낸 상태였다 = 프레임이 먼저다.
    assert first.closed_after == 1
    # 새 연결은 닫히지 않고 자리를 차지한다.
    assert not second.closed
    assert ws_registry.connection_count() == 1


async def test_replaced_socket_cleanup_does_not_evict_the_new_connection() -> None:
    """밀려난 연결의 뒤늦은 정리가 **새 연결을 지우지 않는다.**

    실제 순서가 그렇다 — B가 붙어 A를 닫으면, A의 핸들러가 그제서야 깨어나
    `finally`에서 `unregister()`를 부른다. id만 보고 지우면 방금 붙은 B가 사라지고
    B는 자기가 등록된 줄 알면서 아무 메시지도 받지 못한다.
    """
    first = FakeSocket()
    second = FakeSocket()
    await ws_registry.register(1, _as_socket(first))
    await ws_registry.register(1, _as_socket(second))

    # 밀려난 A의 핸들러가 뒤늦게 정리한다.
    await ws_registry.unregister(1, _as_socket(first))

    assert ws_registry.is_connected(1)
    await ws_registry.push_to_users([1], {"type": "message"})
    assert second.sent == [{"type": "message"}]


async def test_replacement_proceeds_even_if_the_old_socket_is_already_dead() -> None:
    """기존 소켓이 이미 죽어 있어도 새 연결은 등록된다.

    여기서 예외가 올라가면 사용자는 죽은 소켓 때문에 영영 붙지 못한다.
    """
    dead = FakeSocket(dead=True)
    fresh = FakeSocket()

    await ws_registry.register(1, _as_socket(dead))
    await ws_registry.register(1, _as_socket(fresh))

    assert ws_registry.connection_count() == 1
    await ws_registry.push_to_users([1], {"type": "message"})
    assert fresh.sent == [{"type": "message"}]


async def test_registering_the_same_socket_twice_does_not_close_it() -> None:
    """같은 소켓을 두 번 등록해도 자기 자신을 밀어내지 않는다.

    경계 사례다. 동일성 확인이 없으면 재등록이 곧 자기 연결을 끊는 일이 된다.
    """
    socket = FakeSocket()

    await ws_registry.register(1, _as_socket(socket))
    await ws_registry.register(1, _as_socket(socket))

    assert socket.sent == []
    assert not socket.closed
    assert ws_registry.connection_count() == 1


# --------------------------------------------------------------------------
# 브로드캐스트 (BR-5.7, BR-5.8)
# --------------------------------------------------------------------------
async def test_offline_users_are_skipped_silently() -> None:
    """연결이 없는 사용자는 건너뛴다 — **오류가 아니다** (BR-5.7).

    오프라인 사용자는 다음 입장 시 히스토리로 받는다. 미전송 큐를 만들지 않는다.
    """
    online = FakeSocket()
    await ws_registry.register(1, _as_socket(online))

    await ws_registry.push_to_users([1, 2, 3], {"type": "message", "room_id": 7})

    assert online.sent == [{"type": "message", "room_id": 7}]


async def test_one_dead_socket_does_not_block_the_others() -> None:
    """**BR-5.7의 핵심** — 소켓 하나가 죽어도 나머지 참여자가 받는다.

    `try`를 루프 밖에 두면 이 테스트가 붉어진다. 죽은 소켓이 목록 **중간**에 있는
    것이 의도다 — 마지막에 두면 루프 전체를 감싼 구현도 통과해버린다.
    """
    first = FakeSocket()
    dead = FakeSocket(dead=True)
    last = FakeSocket()
    await ws_registry.register(1, _as_socket(first))
    await ws_registry.register(2, _as_socket(dead))
    await ws_registry.register(3, _as_socket(last))

    await ws_registry.push_to_users([1, 2, 3], {"type": "message"})

    assert first.sent == [{"type": "message"}]
    assert last.sent == [{"type": "message"}]


async def test_a_socket_that_dies_mid_send_is_unregistered() -> None:
    """전송 중 죽은 소켓은 레지스트리에서 빠진다.

    남겨두면 그 사용자는 "연결된 것으로 보이지만 받지 못하는" 상태가 되고,
    브로드캐스트마다 같은 예외를 다시 겪는다.
    """
    dead = FakeSocket(dead=True)
    await ws_registry.register(2, _as_socket(dead))

    await ws_registry.push_to_users([2], {"type": "message"})

    assert not ws_registry.is_connected(2)


async def test_broadcast_includes_the_sender() -> None:
    """발신자도 받는다 (BR-5.8) — 다른 탭·기기의 세션이 갱신되어야 한다.

    이 함수는 발신자를 거르지 않는다. 중복 제거는 클라이언트가 메시지 ID로 한다.
    """
    sender = FakeSocket()
    other = FakeSocket()
    await ws_registry.register(1, _as_socket(sender))
    await ws_registry.register(2, _as_socket(other))

    await ws_registry.push_to_users([1, 2], {"type": "message", "message": {"id": 5}})

    assert sender.sent == other.sent == [{"type": "message", "message": {"id": 5}}]


async def test_duplicate_target_ids_send_only_once() -> None:
    """대상 목록에 같은 id가 두 번 있어도 프레임은 한 번만 간다.

    경계 사례다. 두 번 가면 클라이언트의 중복 제거가 그것까지 흡수해야 하고,
    무엇보다 참여자 목록에 중복이 생겼다는 사실이 화면에서 보이지 않게 된다.
    """
    socket = FakeSocket()
    await ws_registry.register(1, _as_socket(socket))

    await ws_registry.push_to_users([1, 1], {"type": "message"})

    assert len(socket.sent) == 1


async def test_push_to_nobody_is_a_no_op() -> None:
    """빈 대상 목록은 아무 일도 하지 않는다 (경계 사례)."""
    await ws_registry.push_to_users([], {"type": "message"})

    assert ws_registry.connection_count() == 0

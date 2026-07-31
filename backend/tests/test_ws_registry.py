"""`core/ws_registry` — 사용자당 1개 연결과 브로드캐스트의 실패 격리.

**가짜 소켓으로 검증한다.** 실제 WebSocket이 필요 없는 이유 — 이 모듈이 소켓에게
요구하는 것은 `send_json()`과 `close()` 둘뿐이고, 검증 대상은 **호출 순서**(프레임을
보낸 뒤에 닫는가)와 **실패 격리**(한 소켓이 죽어도 나머지가 받는가)다. 실제 소켓을
쓰면 그 두 가지가 이벤트 루프와 전송 타이밍 뒤에 가려진다.

핸드셰이크와 인증은 실제 소켓으로 `test_ws_auth.py`가 검증한다.

대응: FR-5.1, BR-5.4, BR-5.7, BR-5.8.
"""

from __future__ import annotations

import asyncio
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
# 사용자당 여러 연결 (2026-07-31, 이전 BR-5.4를 대체)
#
# 방을 새 창으로 열면 목록 창과 대화 창이 동시에 살아 있어야 한다. 이전 규칙은
# 두 번째 연결이 첫 번째를 닫았고, 그러면 창을 열 때마다 앞 창이 죽어 그 사용법
# 자체가 성립하지 않는다.
# --------------------------------------------------------------------------
async def test_second_connection_does_not_close_the_first() -> None:
    """**이 파일에서 가장 중요한 한 줄** — 두 번째 연결이 첫 번째를 닫지 않는다.

    이전에는 여기서 `session_replaced`를 보내고 닫았다. 그 동작이 남아 있으면
    사용자가 방을 새 창으로 여는 순간 목록 창이 죽는다.
    """
    first = FakeSocket()
    second = FakeSocket()

    await ws_registry.register(1, _as_socket(first))
    await ws_registry.register(1, _as_socket(second))

    assert not first.closed
    assert not second.closed
    # **프레임을 보내지 않는다.** 밀려난 연결이라는 개념 자체가 없어졌다.
    assert first.sent == []
    assert ws_registry.connection_count() == 2
    assert ws_registry.connection_count_for(1) == 2


async def test_broadcast_reaches_every_window_of_the_same_user() -> None:
    """한 사용자의 **모든** 소켓이 같은 프레임을 받는다.

    목록 창은 배지를, 대화 창은 말풍선을 그려야 한다 — 둘 중 하나만 받으면 어느
    한쪽이 갱신되지 않는다. 중복은 각 창이 메시지 ID로 접는다(BR-5.8과 같은 이유).
    """
    list_window = FakeSocket()
    chat_window = FakeSocket()
    await ws_registry.register(1, _as_socket(list_window))
    await ws_registry.register(1, _as_socket(chat_window))

    await ws_registry.push_to_users([1], {"type": "message", "room_id": 7})

    assert list_window.sent == [{"type": "message", "room_id": 7}]
    assert chat_window.sent == [{"type": "message", "room_id": 7}]


async def test_closing_one_window_keeps_the_others_connected() -> None:
    """창 하나를 닫아도 나머지 창은 계속 받는다.

    `unregister()`가 소켓을 보지 않고 user_id만 보면 여기서 전부 지워지고, 남은
    창들은 자기가 등록된 줄 알면서 아무 메시지도 받지 못한다. 사용자당 소켓이
    하나였을 때는 드문 경합이었지만 지금은 **창을 닫는 평범한 동작**이 이 경로다.
    """
    closing = FakeSocket()
    staying = FakeSocket()
    await ws_registry.register(1, _as_socket(closing))
    await ws_registry.register(1, _as_socket(staying))

    await ws_registry.unregister(1, _as_socket(closing))

    assert ws_registry.is_connected(1)
    assert ws_registry.connection_count_for(1) == 1
    await ws_registry.push_to_users([1], {"type": "message"})
    assert staying.sent == [{"type": "message"}]
    assert closing.sent == []


async def test_last_window_closing_leaves_no_phantom_connection() -> None:
    """마지막 소켓이 빠지면 그 사용자는 **연결 없음**이 된다.

    빈 집합을 남겨두면 `is_connected()`가 아무도 없는 사용자에게 참을 주고,
    브로드캐스트가 매번 빈 집합을 훑는다.
    """
    only = FakeSocket()
    await ws_registry.register(1, _as_socket(only))

    await ws_registry.unregister(1, _as_socket(only))

    assert not ws_registry.is_connected(1)
    assert ws_registry.connection_count() == 0
    assert ws_registry.connection_count_for(1) == 0


async def test_a_dead_socket_does_not_block_a_new_one() -> None:
    """이미 죽은 소켓이 있어도 새 연결은 등록되고 정상 소켓은 받는다.

    죽은 쪽은 전송 시점에 감지되어 빠진다.
    """
    dead = FakeSocket(dead=True)
    fresh = FakeSocket()

    await ws_registry.register(1, _as_socket(dead))
    await ws_registry.register(1, _as_socket(fresh))
    assert ws_registry.connection_count_for(1) == 2

    await ws_registry.push_to_users([1], {"type": "message"})

    assert fresh.sent == [{"type": "message"}]
    # 죽은 소켓은 전송 실패로 드러나 레지스트리에서 빠진다.
    assert ws_registry.connection_count_for(1) == 1


async def test_registering_the_same_socket_twice_counts_once() -> None:
    """같은 소켓을 두 번 등록해도 하나다 — 집합이라 중복이 접힌다.

    접히지 않으면 그 소켓에 프레임이 두 번 가고, 클라이언트가 ID로 접긴 하지만
    전송 비용이 창 수가 아니라 재등록 횟수에 비례하게 된다.
    """
    socket = FakeSocket()

    await ws_registry.register(1, _as_socket(socket))
    await ws_registry.register(1, _as_socket(socket))

    assert not socket.closed
    assert ws_registry.connection_count() == 1

    await ws_registry.push_to_users([1], {"type": "message"})
    assert socket.sent == [{"type": "message"}]


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


class HangingCloseSocket(FakeSocket):
    """`close()`가 영영 끝나지 않는 소켓.

    close 핸드셰이크에 응답하지 않는 실제 클라이언트(멈춘 탭, 끊긴 네트워크)를
    흉내낸다. `send_json`은 정상 동작한다 — 프레임은 나가고 응답만 없는 상황이다.
    """

    async def close(self, code: int = 1000) -> None:
        await asyncio.sleep(3600)


async def test_an_unresponsive_socket_never_delays_a_new_connection() -> None:
    """기존 연결이 close에 응답하지 않아도 새 연결이 즉시 붙는다.

    **build-and-test에서 라이브 스택으로 실측해 찾은 결함의 회귀 테스트다.**
    당시 `register()`는 기존 연결을 닫았고, `await existing.close()`가 uvicorn의
    close 핸드셰이크 상한인 10초를 그대로 기다렸다 — 그동안 새 탭의 `auth_ok`가
    나가지 못했다. 정상 브라우저는 즉시 응답해(실측 0.0초) 평소에는 드러나지
    않지만, 멈춘 탭 하나가 새 탭 접속을 10초 막았다.

    **지금은 아예 닫지 않으므로 그 경로가 사라졌다.** 그래도 이 테스트를 남기는
    이유는 불변식이 그대로이기 때문이다 — "기존 소켓의 상태가 새 연결을 붙잡지
    못한다". 누군가 교체 동작을 되살리면 여기서 먼저 붉어진다.

    2초로 재는 이유 — 수정 전 동작(10초)보다는 훨씬 짧고 정상 등록보다는 넉넉하다.
    상한 값 자체를 박으면 값을 바꿀 때 테스트도 함께 고치게 되어 불변식이 사라진다.
    """
    stuck = HangingCloseSocket()
    await ws_registry.register(1, _as_socket(stuck))

    fresh = FakeSocket()
    started = asyncio.get_running_loop().time()
    await asyncio.wait_for(ws_registry.register(1, _as_socket(fresh)), timeout=5.0)
    elapsed = asyncio.get_running_loop().time() - started

    assert elapsed < 2.0, f"등록이 {elapsed:.1f}초 걸렸다 — 기존 소켓이 붙잡고 있다"
    # **닫지도, 알리지도 않는다.** 멈춘 창도 그대로 연결된 채 남는다.
    assert not stuck.closed
    assert stuck.sent == []
    await ws_registry.push_to_users([1], {"type": "message"})
    assert fresh.sent == [{"type": "message"}]

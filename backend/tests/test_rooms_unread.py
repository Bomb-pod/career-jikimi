"""안 읽은 개수와 읽음 처리 — FR-5.2의 수용 기준과 N+1 회귀.

여기서 가장 중요한 두 가지는 **한 번의 쿼리로 전부 센다**(BR-5.1)와 **역행 요청이
배지를 되살리지 않는다**(BR-5.3)이다. 둘 다 눈으로는 확인할 수 없어 `capture_sql()`로
실제 SQL을 본다.

메시지는 U5가 만들지만 이 단위가 **읽는다**(안 읽은 개수). U5가 아직 없으므로
테스트가 `messages` 행을 직접 심는다 — 소유권이 아니라 준비 데이터다.

대응: FR-5.2, BR-5.1, BR-5.3, BR-3.3.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.models import Friendship, Message, RoomMember
from app.rooms import service
from app.rooms.exceptions import RoomForbidden
from tests.conftest import capture_sql, make_room, make_user, selects


async def _room_with_two_members(session: Any, suffix: str = "") -> tuple[Any, Any, Any]:
    """`alice`·`bob`과 그 둘이 참여한 방 하나를 심는다.

    서비스가 아니라 모델로 직접 심는 이유 — 이 파일이 검증하는 것은 집계와 갱신이지
    생성 경로가 아니다. `test_rooms_api.py`가 생성을 맡는다.
    """
    alice = await make_user(session, f"alice{suffix}")
    bob = await make_user(session, f"bob{suffix}")
    session.add(Friendship(owner_id=alice.id, friend_id=bob.id, alias="밥"))
    room = await make_room(session, created_by=alice.id)
    session.add_all(
        [
            RoomMember(room_id=room.id, user_id=alice.id, ai_check_enabled=True, last_read_seq=0),
            RoomMember(room_id=room.id, user_id=bob.id, ai_check_enabled=True, last_read_seq=0),
        ]
    )
    await session.flush()
    return alice, bob, room


async def _add_messages(
    session: Any, room: Any, sender: Any, count: int, *, start: int = 1
) -> None:
    """`seq`가 `start`부터 이어지는 메시지를 심는다.

    `rooms.last_seq`도 함께 올린다 — 실제로는 U5가 한 트랜잭션에서 하는 일이며(ADR-003),
    여기서 맞춰두지 않으면 방의 상태가 실제로 존재할 수 없는 모양이 된다.
    """
    session.add_all(
        [
            Message(
                room_id=room.id,
                sender_id=sender.id,
                seq=start + offset,
                body=f"메시지 {start + offset}",
                verification_status="ok",
            )
            for offset in range(count)
        ]
    )
    room.last_seq = start + count - 1
    await session.flush()


# --------------------------------------------------------------------------
# 배지 계산 (BR-5.1)
# --------------------------------------------------------------------------
async def test_unread_counts_messages_past_last_read_seq(db_session: Any) -> None:
    """FR-5.2의 첫 기준 — `last_read_seq`가 10이고 seq 11·12가 오면 배지가 2다."""
    alice, bob, room = await _room_with_two_members(db_session)
    await _add_messages(db_session, room, bob, count=12)
    await service.mark_read(db_session, alice.id, room.id, 10)

    rooms = await service.list_rooms(db_session, alice.id)

    assert [item.unread_count for item in rooms] == [2]
    assert rooms[0].last_read_seq == 10


async def test_a_room_without_messages_reports_zero(db_session: Any) -> None:
    """메시지가 없는 방은 0이다 — 목록에서 사라지지 않는다.

    `LEFT JOIN`이 아니라 INNER JOIN이면 방금 만든 방이 목록에서 통째로 빠진다.
    """
    alice, _bob, _room = await _room_with_two_members(db_session)

    rooms = await service.list_rooms(db_session, alice.id)

    assert len(rooms) == 1
    assert rooms[0].unread_count == 0


async def test_each_member_has_their_own_unread_count(db_session: Any) -> None:
    """배지는 사람마다 다르다 — `last_read_seq`가 참여자별 값이기 때문이다."""
    alice, bob, room = await _room_with_two_members(db_session)
    await _add_messages(db_session, room, bob, count=5)
    await service.mark_read(db_session, alice.id, room.id, 5)

    alice_rooms = await service.list_rooms(db_session, alice.id)
    bob_rooms = await service.list_rooms(db_session, bob.id)

    assert alice_rooms[0].unread_count == 0
    assert bob_rooms[0].unread_count == 5


async def test_unread_counts_for_all_rooms_in_one_query(db_session: Any) -> None:
    """**N+1 회귀** — 방이 3개여도 조회 횟수가 1개일 때와 같다 (BR-5.1).

    U3의 `resolve_display_names()`가 같은 방식으로 자기 회귀를 막고 있다. 여기서
    방마다 반복하면 그 함수가 방 개수만큼 호출되어 그쪽 보증이 무의미해진다.

    개수를 상수로 못 박지 않고 **두 경우를 비교**하는 이유 — 구현이 조회를 하나
    합치거나 나눌 수 있고, 그것은 이 테스트가 지켜야 할 것이 아니다. 지켜야 할 것은
    **방 개수에 비례하지 않는다**는 성질이다.
    """
    alice, bob, first = await _room_with_two_members(db_session)
    await _add_messages(db_session, first, bob, count=3)
    with capture_sql() as one_room:
        await service.list_rooms(db_session, alice.id)

    for index in range(2):
        extra = await make_room(db_session, created_by=alice.id)
        db_session.add_all(
            [
                RoomMember(room_id=extra.id, user_id=alice.id),
                RoomMember(room_id=extra.id, user_id=bob.id),
            ]
        )
        await db_session.flush()
        await _add_messages(db_session, extra, bob, count=index + 1)

    with capture_sql() as three_rooms:
        rooms = await service.list_rooms(db_session, alice.id)

    assert len(rooms) == 3
    assert len(selects(one_room)) == len(selects(three_rooms)), selects(three_rooms)


# --------------------------------------------------------------------------
# 읽음 처리 (BR-5.3)
# --------------------------------------------------------------------------
async def test_mark_read_advances_and_clears_the_badge(db_session: Any) -> None:
    """FR-5.2의 둘째 기준 — 입장하면 `last_read_seq`가 갱신되고 배지가 사라진다."""
    alice, bob, room = await _room_with_two_members(db_session)
    await _add_messages(db_session, room, bob, count=2)

    result = await service.mark_read(db_session, alice.id, room.id, 2)

    assert result == 2
    rooms = await service.list_rooms(db_session, alice.id)
    assert rooms[0].unread_count == 0


async def test_a_backwards_request_is_ignored_but_still_succeeds(db_session: Any) -> None:
    """**BR-5.3** — 뒤로 가는 요청은 무시되고, 그래도 오류가 아니다.

    사용자가 방을 빠르게 오갈 때 순서가 뒤바뀐 요청이 실제로 들어온다. 조건절이
    없으면 늦게 도착한 옛 요청이 `last_read_seq`를 되돌려 **배지가 되살아난다.**
    """
    alice, bob, room = await _room_with_two_members(db_session)
    await _add_messages(db_session, room, bob, count=30)
    await service.mark_read(db_session, alice.id, room.id, 30)

    # 늦게 도착한 옛 요청.
    result = await service.mark_read(db_session, alice.id, room.id, 12)

    # 오류가 아니라 현재 값을 그대로 돌려준다.
    assert result == 30
    rooms = await service.list_rooms(db_session, alice.id)
    assert rooms[0].unread_count == 0


async def test_an_equal_request_is_also_a_no_op(db_session: Any) -> None:
    """같은 값으로 다시 요청해도 무시된다 (경계 사례).

    `<`가 아니라 `<=`로 쓰면 매번 UPDATE가 나가고, 같은 값을 쓰는 무의미한 쓰기가
    사용자가 방을 볼 때마다 발생한다.
    """
    alice, bob, room = await _room_with_two_members(db_session)
    await _add_messages(db_session, room, bob, count=5)
    await service.mark_read(db_session, alice.id, room.id, 5)

    assert await service.mark_read(db_session, alice.id, room.id, 5) == 5


async def test_the_guard_clause_is_actually_in_the_sql(db_session: Any) -> None:
    """조건절이 **실제 SQL에 있다.**

    앞의 두 테스트는 파이썬 쪽에서 값을 비교해 UPDATE를 건너뛰는 구현으로도 통과한다.
    그 구현은 두 요청이 겹칠 때 경쟁 조건이 생긴다 — 판정은 DB가 해야 한다.
    """
    alice, bob, room = await _room_with_two_members(db_session)
    await _add_messages(db_session, room, bob, count=3)

    with capture_sql() as statements:
        await service.mark_read(db_session, alice.id, room.id, 3)

    updates = [item for item in statements if item.lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 1, statements
    assert "last_read_seq <" in updates[0], updates[0]


async def test_mark_read_is_forbidden_for_a_non_member(db_session: Any) -> None:
    """참여자가 아니면 403이다 (BR-3.3) — 남의 방 읽음 위치를 건드릴 수 없다."""
    _alice, _bob, room = await _room_with_two_members(db_session)
    stranger = await make_user(db_session, "stranger")

    with pytest.raises(RoomForbidden):
        await service.mark_read(db_session, stranger.id, room.id, 1)


async def test_mark_read_via_the_api_returns_200_even_when_it_cannot_advance(
    api_client: Any, db_session: Any
) -> None:
    """전진하지 못해도 **HTTP 200**이다 (BR-5.3).

    앞의 서비스 테스트가 반환값을 확인했다면 이것은 **상태 코드**를 확인한다.
    400이나 409를 주면 클라이언트가 정상 동작을 실패로 다루고 사용자에게 오류를
    보여준다.
    """
    from tests.conftest import bearer, signup_via_api

    alice = await signup_via_api(api_client, "alice")
    bob = await signup_via_api(api_client, "bob")
    await api_client.post(
        "/friends", json={"username": "bob", "alias": "밥"}, headers=bearer(alice["token"])
    )
    created = await api_client.post(
        "/rooms", json={"friend_user_ids": [bob["user"]["id"]]}, headers=bearer(alice["token"])
    )
    room_id = created.json()["id"]

    ahead = await api_client.post(
        f"/rooms/{room_id}/read", json={"up_to_seq": 9}, headers=bearer(alice["token"])
    )
    behind = await api_client.post(
        f"/rooms/{room_id}/read", json={"up_to_seq": 3}, headers=bearer(alice["token"])
    )

    assert ahead.status_code == 200
    assert ahead.json() == {"last_read_seq": 9}
    assert behind.status_code == 200
    assert behind.json() == {"last_read_seq": 9}

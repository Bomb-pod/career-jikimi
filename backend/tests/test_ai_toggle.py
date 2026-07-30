"""개인별 AI 검증 토글 — FR-6.1의 수용 기준.

**이 파일이 지키는 것은 "남의 설정이 변하지 않는다" 하나다** (BR-6.1). 방장 개념이
없다는 결정이 코드로 지켜지는지 확인한다 — `rooms.created_by`는 기록이지 권한이
아니다.

대응: FR-6.1, BR-6.1, BR-6.2, BR-3.3.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.rooms import service
from app.rooms.exceptions import RoomForbidden
from tests.conftest import bearer, make_user, signup_via_api


async def _room_of_two(client: Any) -> tuple[dict[str, Any], dict[str, Any], int]:
    """`alice`가 만든 방에 `bob`이 함께 있는 상태를 만든다."""
    alice = await signup_via_api(client, "alice")
    bob = await signup_via_api(client, "bob")
    await client.post(
        "/friends", json={"username": "bob", "alias": "밥"}, headers=bearer(alice["token"])
    )
    created = await client.post(
        "/rooms", json={"friend_user_ids": [bob["user"]["id"]]}, headers=bearer(alice["token"])
    )
    assert created.status_code == 201, created.text
    return alice, bob, created.json()["id"]


async def test_new_rooms_default_to_enabled_for_everyone(api_client: Any) -> None:
    """BR-6.2 — 신규 방의 모든 참여자가 켜짐으로 시작한다.

    기본이 켜짐인 이유 — 이 앱의 존재 이유가 그 기능이다. 꺼진 채로 시작하면 아무도
    켜지 않는다.
    """
    alice, bob, room_id = await _room_of_two(api_client)

    for actor in (alice, bob):
        detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(actor["token"]))
        assert detail.status_code == 200, detail.text
        assert detail.json()["ai_check_enabled"] is True


async def test_toggling_changes_only_the_callers_row(api_client: Any) -> None:
    """**FR-6.1의 수용 기준** — 한 사람이 꺼도 다른 참여자의 설정은 그대로다.

    방장 개념이 없다. `alice`가 방을 만들었지만 그 사실이 `bob`의 설정에 대한
    권한을 주지 않으며, 반대로 `bob`이 끈다고 `alice`의 전송이 달라지지 않는다.
    """
    alice, bob, room_id = await _room_of_two(api_client)

    response = await api_client.patch(
        f"/rooms/{room_id}/ai-check", json={"enabled": False}, headers=bearer(bob["token"])
    )

    assert response.status_code == 200
    assert response.json() == {"ai_check_enabled": False}

    bob_detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(bob["token"]))
    alice_detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(alice["token"]))
    assert bob_detail.json()["ai_check_enabled"] is False
    # ← 이 줄이 BR-6.1이다. `WHERE user_id = 호출자`를 빼면 여기서 False가 된다.
    assert alice_detail.json()["ai_check_enabled"] is True


async def test_the_room_list_carries_each_callers_own_value(api_client: Any) -> None:
    """목록에도 **호출자 본인의** 값이 실린다 (FR-6.1).

    화면이 방마다 상세를 다시 부르지 않고 자기 토글을 그릴 수 있어야 한다. 목록
    쿼리가 이미 호출자의 `room_members` 행과 조인하므로 공짜로 따라온다 — 남의
    값이 실릴 경로는 없다.
    """
    alice, bob, room_id = await _room_of_two(api_client)
    await api_client.patch(
        f"/rooms/{room_id}/ai-check", json={"enabled": False}, headers=bearer(bob["token"])
    )

    alice_list = await api_client.get("/rooms", headers=bearer(alice["token"]))
    bob_list = await api_client.get("/rooms", headers=bearer(bob["token"]))

    assert alice_list.json()["rooms"][0]["ai_check_enabled"] is True
    assert bob_list.json()["rooms"][0]["ai_check_enabled"] is False


async def test_the_toggle_can_be_turned_back_on(api_client: Any) -> None:
    """껐다 켤 수 있다 — 한 방향으로만 동작하면 사용자가 되돌릴 수 없다."""
    _alice, bob, room_id = await _room_of_two(api_client)
    await api_client.patch(
        f"/rooms/{room_id}/ai-check", json={"enabled": False}, headers=bearer(bob["token"])
    )

    response = await api_client.patch(
        f"/rooms/{room_id}/ai-check", json={"enabled": True}, headers=bearer(bob["token"])
    )

    assert response.status_code == 200
    detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(bob["token"]))
    assert detail.json()["ai_check_enabled"] is True


async def test_a_non_member_cannot_change_the_toggle(api_client: Any) -> None:
    """참여자가 아니면 403이다 (BR-3.3). 존재하지 않는 방도 같다."""
    alice, _bob, room_id = await _room_of_two(api_client)
    carol = await signup_via_api(api_client, "carol")

    other_room = await api_client.patch(
        f"/rooms/{room_id}/ai-check", json={"enabled": False}, headers=bearer(carol["token"])
    )
    missing_room = await api_client.patch(
        "/rooms/999999/ai-check", json={"enabled": False}, headers=bearer(carol["token"])
    )

    assert other_room.status_code == 403
    assert other_room.json()["error"]["code"] == "FORBIDDEN"
    assert missing_room.status_code == 403

    # 아무것도 바뀌지 않았다.
    detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(alice["token"]))
    assert detail.json()["ai_check_enabled"] is True


async def test_the_toggle_is_visible_to_u5_through_get_membership(db_session: Any) -> None:
    """U5가 쓰는 계약 — `get_membership()`이 자격과 토글을 **함께** 준다.

    U5의 `send_message()` 1단계가 그 둘을 한 번의 조회로 확인한다. 나눠 두면 같은
    행을 두 번 읽게 되고, 그 사이에 토글이 바뀌면 두 값이 서로 다른 시점을 가리킨다.
    """
    from app.models import RoomMember
    from tests.conftest import make_room

    alice = await make_user(db_session, "alice")
    room = await make_room(db_session, created_by=alice.id)
    db_session.add(RoomMember(room_id=room.id, user_id=alice.id))
    await db_session.flush()

    await service.set_ai_check(db_session, alice.id, room.id, enabled=False)
    membership = await service.get_membership(db_session, alice.id, room.id)

    assert membership is not None
    assert membership.ai_check_enabled is False
    assert membership.last_read_seq == 0


async def test_set_ai_check_raises_for_a_non_member_at_the_service_level(db_session: Any) -> None:
    """서비스 계층에서도 같은 규칙이다 — 라우터를 거치지 않는 호출도 막힌다."""
    stranger = await make_user(db_session, "stranger")

    with pytest.raises(RoomForbidden):
        await service.set_ai_check(db_session, stranger.id, 999999, enabled=True)

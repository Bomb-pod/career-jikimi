"""`/rooms/{id}/members` 추가·나가기 — FR-10.1, FR-10.2의 수용 기준.

**실제 MariaDB에서 돈다.** `TEST_DATABASE_URL`이 없으면 전부 skip된다. 복합 PK
`(room_id, user_id)`가 있어야 중복 참여 방지가 실제로 확인된다.

FR-10은 **Should**이며 2026-07-30에 일정 때문에 절단되었다가 2026-07-31에 복원됐다
(`code-generation-plan.md` Step 7). 그 사이 `AlreadyMember` 예외와 응답 코드 규약은
자리를 지키고 있었다.

대응: FR-10.1, FR-10.2, BR-3.2, BR-3.3, BR-10.1, BR-10.2, BR-6.2.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.models import Message, RoomMember
from app.rooms.service import member_user_ids
from tests.conftest import bearer, signup_via_api

ALIAS_BOB = "회사 김대리"
ALIAS_CAROL = "동아리 후배"
ALIAS_DAVE = "학교 선배"


async def _room_of_two(client: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], int]:
    """`alice`가 `bob`과 둘이 있는 방을 만든다. `carol`은 alice의 친구지만 방 밖이다.

    가입·친구·방 생성을 전부 API로 하는 이유 — 서비스 함수로 심으면 라우터·스키마
    경로가 빠져 "실제로 그 응답으로 만들어진 데이터"가 아니게 된다.
    """
    alice = await signup_via_api(client, "alice")
    bob = await signup_via_api(client, "bob")
    carol = await signup_via_api(client, "carol")
    for username, alias in (("bob", ALIAS_BOB), ("carol", ALIAS_CAROL)):
        created = await client.post(
            "/friends", json={"username": username, "alias": alias}, headers=bearer(alice["token"])
        )
        assert created.status_code == 201, created.text

    room = await client.post(
        "/rooms",
        json={"friend_user_ids": [bob["user"]["id"]], "name": "점심 약속"},
        headers=bearer(alice["token"]),
    )
    assert room.status_code == 201, room.text
    return alice, bob, carol, room.json()["id"]


# --------------------------------------------------------------------------
# 추가 (FR-10.1, BR-10.1, BR-3.2)
# --------------------------------------------------------------------------
async def test_adding_a_friend_makes_the_room_three(api_client: Any) -> None:
    """FR-10.1의 첫 기준 — 2명인 방에 친구를 더하면 **3명**이 된다."""
    alice, bob, carol, room_id = await _room_of_two(api_client)

    response = await api_client.post(
        f"/rooms/{room_id}/members",
        json={"friend_user_id": carol["user"]["id"]},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 201, response.text
    assert {member["user_id"] for member in response.json()["members"]} == {
        alice["user"]["id"],
        bob["user"]["id"],
        carol["user"]["id"],
    }


async def test_the_added_member_sees_the_room_in_their_list(api_client: Any) -> None:
    """FR-10.1의 첫 기준 나머지 절반 — **추가된 사람의 방 목록에 그 방이 나타난다.**

    추가한 쪽 응답만 보면 절반만 확인한 것이다. 참여 행이 실제로 들어갔는지는
    받는 쪽 화면에서 드러난다.
    """
    alice, _bob, carol, room_id = await _room_of_two(api_client)
    before = await api_client.get("/rooms", headers=bearer(carol["token"]))
    assert before.json()["rooms"] == []

    added = await api_client.post(
        f"/rooms/{room_id}/members",
        json={"friend_user_id": carol["user"]["id"]},
        headers=bearer(alice["token"]),
    )
    assert added.status_code == 201, added.text

    listed = await api_client.get("/rooms", headers=bearer(carol["token"]))
    assert [room["id"] for room in listed.json()["rooms"]] == [room_id]


async def test_the_added_member_starts_with_ai_check_on(api_client: Any) -> None:
    """추가된 사람의 검증 토글은 **켜짐**, 읽음 위치는 0이다 (BR-6.2).

    방 생성과 같은 기본값이어야 한다 — `_insert_members()`를 재사용하는 것이 그
    보장이며, 여기서 따로 초기화했다면 두 경로가 갈린다.
    """
    alice, _bob, carol, room_id = await _room_of_two(api_client)
    await api_client.post(
        f"/rooms/{room_id}/members",
        json={"friend_user_id": carol["user"]["id"]},
        headers=bearer(alice["token"]),
    )

    detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(carol["token"]))

    assert detail.status_code == 200, detail.text
    assert detail.json()["ai_check_enabled"] is True
    assert detail.json()["last_read_seq"] == 0


async def test_adding_an_existing_member_is_rejected(api_client: Any) -> None:
    """FR-10.1의 둘째 기준 — 이미 있는 사람을 더하면 **400**이고 인원은 그대로다 (BR-10.1)."""
    alice, bob, _carol, room_id = await _room_of_two(api_client)

    response = await api_client.post(
        f"/rooms/{room_id}/members",
        json={"friend_user_id": bob["user"]["id"]},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALREADY_MEMBER"

    detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(alice["token"]))
    assert len(detail.json()["members"]) == 2


async def test_adding_myself_reports_already_member(api_client: Any) -> None:
    """자기 자신을 더하면 `ALREADY_MEMBER`다 — `NOT_A_FRIEND`가 아니다.

    경계 사례이지만 문구가 사용자에게 보이므로 어느 쪽이 나가는지가 중요하다.
    "자기 자신은 자기 친구가 아니다"는 사실은 맞지만(U3 BR-2.5), 사용자가 읽으면
    원인을 잘못 짚는다. 판정 순서(403 → ALREADY_MEMBER → NOT_A_FRIEND)가 이것을
    결정한다.
    """
    alice, _bob, _carol, room_id = await _room_of_two(api_client)

    response = await api_client.post(
        f"/rooms/{room_id}/members",
        json={"friend_user_id": alice["user"]["id"]},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALREADY_MEMBER"


async def test_adding_a_stranger_is_rejected(api_client: Any) -> None:
    """친구가 아닌 사람은 초대할 수 없다 (BR-3.2, 400).

    **호출자 기준이다** — `dave`는 존재하지만 `alice`의 친구가 아니다.
    """
    alice, _bob, _carol, room_id = await _room_of_two(api_client)
    dave = await signup_via_api(api_client, "dave")

    response = await api_client.post(
        f"/rooms/{room_id}/members",
        json={"friend_user_id": dave["user"]["id"]},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_A_FRIEND"
    # 어떤 id가 문제인지 알려주지 않는다 — 알려주면 친구 관계를 탐색할 수 있다.
    assert str(dave["user"]["id"]) not in response.json()["error"]["message"]


async def test_a_non_member_cannot_add_anyone(api_client: Any) -> None:
    """**403이 가장 먼저다** (BR-3.3).

    참여자가 아닌 사람에게 `ALREADY_MEMBER`를 주면 그 방에 누가 있는지 확인해주는
    셈이 된다. `carol`은 방 밖이므로 자기 친구를 넣으려 해도 403이다.
    """
    _alice, _bob, carol, room_id = await _room_of_two(api_client)
    dave = await signup_via_api(api_client, "dave")
    await api_client.post(
        "/friends", json={"username": "dave", "alias": ALIAS_DAVE}, headers=bearer(carol["token"])
    )

    response = await api_client.post(
        f"/rooms/{room_id}/members",
        json={"friend_user_id": dave["user"]["id"]},
        headers=bearer(carol["token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_adding_to_a_nonexistent_room_is_also_forbidden(api_client: Any) -> None:
    """**없는 방도 403이다** (BR-3.3) — 404를 주면 방 id의 존재 여부가 샌다."""
    alice, _bob, carol, _room_id = await _room_of_two(api_client)

    response = await api_client.post(
        "/rooms/999999",
        json={"friend_user_id": carol["user"]["id"]},
        headers=bearer(alice["token"]),
    )

    assert response.status_code in {403, 405}
    if response.status_code == 403:
        assert response.json()["error"]["code"] == "FORBIDDEN"

    on_members = await api_client.post(
        "/rooms/999999/members",
        json={"friend_user_id": carol["user"]["id"]},
        headers=bearer(alice["token"]),
    )
    assert on_members.status_code == 403
    assert on_members.json()["error"]["code"] == "FORBIDDEN"


async def test_adding_requires_authentication(api_client: Any) -> None:
    """토큰 없이 참여자를 더할 수 없다."""
    response = await api_client.post("/rooms/1/members", json={"friend_user_id": 2})

    assert response.status_code == 401


# --------------------------------------------------------------------------
# 나가기 (FR-10.2, BR-10.2)
# --------------------------------------------------------------------------
async def test_leaving_removes_the_room_from_my_list(api_client: Any) -> None:
    """FR-10.2의 첫 기준 — 나가면 **방 목록에서 사라진다.**"""
    _alice, bob, _carol, room_id = await _room_of_two(api_client)

    response = await api_client.delete(f"/rooms/{room_id}/members/me", headers=bearer(bob["token"]))

    assert response.status_code == 204, response.text
    listed = await api_client.get("/rooms", headers=bearer(bob["token"]))
    assert listed.json()["rooms"] == []


async def test_leaving_stops_new_messages(db_session: Any, api_client: Any) -> None:
    """FR-10.2의 둘째 기준 — 나간 뒤에는 **새 메시지를 받지 않는다** (BR-10.2).

    브로드캐스트 대상은 `member_user_ids()`가 매 전송마다 조회하므로, 참여 행이
    지워지면 그 목록에서 자동으로 빠진다. 캐시가 있었다면 여기서 무효화를 함께
    해야 했고, 빠뜨리는 날 나간 사람에게 계속 전송되는 조용한 정보 유출이 된다.

    실제 WebSocket 대신 그 함수를 직접 확인하는 이유 — 전송 경로(U5)와 레지스트리는
    각자의 테스트가 이미 덮고 있고, 여기서 지켜야 할 것은 **대상 목록이 참여 행을
    따라간다**는 사실 하나다.
    """
    _alice, bob, _carol, room_id = await _room_of_two(api_client)
    before = await member_user_ids(db_session, room_id)
    assert bob["user"]["id"] in before

    gone = await api_client.delete(f"/rooms/{room_id}/members/me", headers=bearer(bob["token"]))
    assert gone.status_code == 204, gone.text

    after = await member_user_ids(db_session, room_id)
    assert bob["user"]["id"] not in after
    assert len(after) == len(before) - 1


async def test_leaving_leaves_the_others_alone(api_client: Any) -> None:
    """나가는 것은 **자기 행만** 지운다 — 남은 사람은 그대로 방을 본다.

    `WHERE user_id = 호출자`가 빠지면 한 사람이 나갈 때 방이 통째로 비워진다.
    """
    alice, bob, _carol, room_id = await _room_of_two(api_client)

    await api_client.delete(f"/rooms/{room_id}/members/me", headers=bearer(bob["token"]))

    detail = await api_client.get(f"/rooms/{room_id}", headers=bearer(alice["token"]))
    assert detail.status_code == 200, detail.text
    assert [member["user_id"] for member in detail.json()["members"]] == [alice["user"]["id"]]


async def test_leaving_twice_is_forbidden(api_client: Any) -> None:
    """이미 나간 방에서 또 나갈 수 없다 — 참여자가 아니므로 403이다 (BR-3.3)."""
    _alice, bob, _carol, room_id = await _room_of_two(api_client)
    first = await api_client.delete(f"/rooms/{room_id}/members/me", headers=bearer(bob["token"]))
    assert first.status_code == 204

    second = await api_client.delete(f"/rooms/{room_id}/members/me", headers=bearer(bob["token"]))

    assert second.status_code == 403
    assert second.json()["error"]["code"] == "FORBIDDEN"


async def test_the_last_member_can_leave_and_messages_survive(
    db_session: Any, api_client: Any
) -> None:
    """**마지막 참여자가 나가도 방과 메시지는 남는다.**

    `create_room()`이 경계하는 "유령 방"과 겉모습이 같지만 성격이 다르다 — 그쪽은
    메시지가 없는 방이 트랜잭션 분리로 생기는 결함이고, 이쪽은 메시지와 판정 로그가
    이미 쌓인 방이 정상 경로로 비는 것이다.

    지우려면 `messages`와 `judgment_logs`를 함께 지워야 하는데, 그것이 이 프로젝트가
    모으려는 실험 데이터 자체다 (FR-7의 지표와 오프라인 재판정이 그 행들을 읽는다).
    """
    alice, bob, _carol, room_id = await _room_of_two(api_client)
    db_session.add(
        Message(
            room_id=room_id,
            sender_id=alice["user"]["id"],
            seq=1,
            body="남아 있어야 한다",
            verification_status="disabled",
        )
    )
    await db_session.commit()

    for who in (alice, bob):
        left = await api_client.delete(f"/rooms/{room_id}/members/me", headers=bearer(who["token"]))
        assert left.status_code == 204, left.text

    remaining_members = await db_session.scalar(
        sa.select(sa.func.count()).select_from(RoomMember).where(RoomMember.room_id == room_id)
    )
    remaining_messages = await db_session.scalar(
        sa.select(sa.func.count()).select_from(Message).where(Message.room_id == room_id)
    )
    assert remaining_members == 0
    assert remaining_messages == 1


async def test_leaving_requires_authentication(api_client: Any) -> None:
    """토큰 없이 방을 나갈 수 없다."""
    response = await api_client.delete("/rooms/1/members/me")

    assert response.status_code == 401

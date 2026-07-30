"""`/rooms` 생성·목록·상세 — FR-3.1~FR-3.3의 수용 기준.

**실제 MariaDB에서 돈다.** `TEST_DATABASE_URL`이 없으면 전부 skip된다. 복합 PK
`(room_id, user_id)`와 FK가 있어야 "한 트랜잭션"과 중복 참여 방지가 실제로 확인된다.

대응: FR-3.1, FR-3.2, FR-3.3, BR-3.1~BR-3.4, BR-6.2.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from app.models import Friendship, Room
from app.rooms import service
from tests.conftest import bearer, make_user, signup_via_api

ALIAS_BOB = "회사 김대리"
ALIAS_CAROL = "동아리 후배"


async def _friends(client: Any) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """`alice`가 `bob`·`carol`을 친구로 등록한 상태를 만든다.

    가입과 친구 등록을 API로 하는 이유 — 서비스 함수로 심으면 라우터·스키마 경로가
    빠져 "실제로 그 응답으로 만들어진 데이터"가 아니게 된다.
    """
    alice = await signup_via_api(client, "alice")
    bob = await signup_via_api(client, "bob")
    carol = await signup_via_api(client, "carol")
    for username, alias in (("bob", ALIAS_BOB), ("carol", ALIAS_CAROL)):
        created = await client.post(
            "/friends", json={"username": username, "alias": alias}, headers=bearer(alice["token"])
        )
        assert created.status_code == 201, created.text
    return alice, bob, carol


# --------------------------------------------------------------------------
# 생성 (FR-3.1, BR-3.1, BR-3.2, BR-6.2)
# --------------------------------------------------------------------------
async def test_creating_a_room_with_one_friend_yields_two_members(api_client: Any) -> None:
    """FR-3.1의 첫 기준 — 친구 1명을 고르면 **본인 포함 2명**인 방이 생긴다."""
    alice, bob, _carol = await _friends(api_client)

    response = await api_client.post(
        "/rooms",
        json={"friend_user_ids": [bob["user"]["id"]], "name": "점심 약속"},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "점심 약속"
    assert {member["user_id"] for member in body["members"]} == {
        alice["user"]["id"],
        bob["user"]["id"],
    }
    # BR-6.2 — 신규 방의 기본값은 켜짐이고 읽음 위치는 0이다.
    assert body["ai_check_enabled"] is True
    assert body["last_read_seq"] == 0
    assert body["last_seq"] == 0


async def test_room_members_are_shown_with_resolved_display_names(api_client: Any) -> None:
    """참여자는 `resolve_display_names()`가 해석한 이름으로 나온다 (FR-2.4, BR-2.8).

    `bob`의 계정 표시명은 `"bob"`이고 `alice`가 붙인 별칭은 `"회사 김대리"`다.
    별칭이 이겨야 하며, 본명은 응답 어디에도 없어야 한다 — 규칙을 이 모듈이 복제하지
    않고 U3의 단일 출처를 부르는지가 여기서 드러난다.
    """
    alice, bob, _carol = await _friends(api_client)

    response = await api_client.post(
        "/rooms", json={"friend_user_ids": [bob["user"]["id"]]}, headers=bearer(alice["token"])
    )

    assert response.status_code == 201, response.text
    names = {member["user_id"]: member["display_name"] for member in response.json()["members"]}
    assert names[bob["user"]["id"]] == ALIAS_BOB
    assert "bob" not in response.text
    # 자기 자신은 자기 친구가 아니므로 계정 표시명으로 떨어진다.
    assert names[alice["user"]["id"]] == "alice"


async def test_creating_a_room_without_a_name_is_allowed(api_client: Any) -> None:
    """방 이름은 선택이다 — 없으면 `null`이고 화면이 참여자 표시명으로 조립한다."""
    alice, bob, _carol = await _friends(api_client)

    response = await api_client.post(
        "/rooms", json={"friend_user_ids": [bob["user"]["id"]]}, headers=bearer(alice["token"])
    )

    assert response.status_code == 201, response.text
    assert response.json()["name"] is None


async def test_empty_participant_list_is_rejected(api_client: Any) -> None:
    """FR-3.1의 둘째 기준 — 아무도 고르지 않으면 **400**이고 방은 생기지 않는다.

    **422가 아니라 400 `EMPTY_ROOM`이다** (BR-3.1). pydantic의 `min_length`로 막으면
    이 코드가 사라지고 프론트엔드가 분기할 수 없다.
    """
    alice, _bob, _carol = await _friends(api_client)

    response = await api_client.post(
        "/rooms", json={"friend_user_ids": []}, headers=bearer(alice["token"])
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "EMPTY_ROOM"

    listed = await api_client.get("/rooms", headers=bearer(alice["token"]))
    assert listed.json()["rooms"] == []


async def test_a_stranger_in_the_participant_list_is_rejected(api_client: Any) -> None:
    """FR-3.1의 셋째 기준 — 친구가 아닌 id가 섞이면 **400**이고 방은 생기지 않는다 (BR-3.2).

    `dave`는 존재하지만 `alice`의 친구가 아니다. 한 명이라도 아니면 전부 거절이다 —
    친구인 사람만 넣고 만드는 부분 성공은 사용자가 고른 것과 다른 방이다.
    """
    alice, bob, _carol = await _friends(api_client)
    dave = await signup_via_api(api_client, "dave")

    response = await api_client.post(
        "/rooms",
        json={"friend_user_ids": [bob["user"]["id"], dave["user"]["id"]]},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_A_FRIEND"
    # 어떤 id가 문제인지 알려주지 않는다 — 알려주면 친구 관계를 탐색할 수 있다.
    assert str(dave["user"]["id"]) not in response.json()["error"]["message"]

    listed = await api_client.get("/rooms", headers=bearer(alice["token"]))
    assert listed.json()["rooms"] == []


async def test_friendship_is_directional_so_the_other_side_cannot_invite_back(
    api_client: Any,
) -> None:
    """친구 등록은 단방향이다 (BR-2.3) — `bob`은 `alice`를 초대할 수 없다.

    `alice`가 `bob`을 등록해도 `bob`의 목록은 비어 있다. 판정이 **호출자 기준**임을
    확인하는 경계 사례다.
    """
    alice, bob, _carol = await _friends(api_client)

    response = await api_client.post(
        "/rooms", json={"friend_user_ids": [alice["user"]["id"]]}, headers=bearer(bob["token"])
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NOT_A_FRIEND"


async def test_duplicate_participant_ids_are_folded(api_client: Any) -> None:
    """같은 친구를 두 번 고르면 조용히 한 명으로 접는다.

    복합 PK 위반으로 500이 나면 안 된다. 사용자 입력의 잡음이지 규칙 위반이 아니다.
    """
    alice, bob, _carol = await _friends(api_client)

    response = await api_client.post(
        "/rooms",
        json={"friend_user_ids": [bob["user"]["id"], bob["user"]["id"]]},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 201, response.text
    assert len(response.json()["members"]) == 2


async def test_room_creation_requires_authentication(api_client: Any) -> None:
    """토큰 없이 방을 만들 수 없다."""
    response = await api_client.post("/rooms", json={"friend_user_ids": [1]})

    assert response.status_code == 401


async def test_room_creation_is_a_single_transaction(db_session: Any, monkeypatch: Any) -> None:
    """**참여자 INSERT가 실패하면 방도 남지 않는다.**

    나뉘어 커밋되면 참여자가 없는 방, 즉 **아무도 접근할 수 없는 유령 방**이 남는다 —
    방 목록은 `room_members`로 조회하므로 그 방은 어떤 화면에도 나타나지 않고 삭제
    수단도 없다.

    참여자 INSERT만 실패시키기 위해 `_insert_members()`를 갈아끼운다. FK 위반으로
    같은 상황을 만들 수는 없다 — 그 앞의 친구 검사(BR-3.2)가 존재하지 않는 사용자를
    먼저 걸러내기 때문이다.
    """
    alice = await make_user(db_session, "alice")
    bob = await make_user(db_session, "bob")
    db_session.add(Friendship(owner_id=alice.id, friend_id=bob.id, alias=ALIAS_BOB))
    await db_session.flush()
    owner_id = alice.id

    async def _fail(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("참여자 INSERT 실패")

    monkeypatch.setattr(service, "_insert_members", _fail)

    with pytest.raises(RuntimeError):
        await service.create_room(db_session, owner_id, [bob.id], None)

    # 라우터 경로에서는 `get_session()`이 이 롤백을 한다.
    await db_session.rollback()

    remaining = await db_session.execute(
        sa.select(sa.func.count()).select_from(Room).where(Room.created_by == owner_id)
    )
    assert remaining.scalar_one() == 0


# --------------------------------------------------------------------------
# 목록 (FR-3.2, BR-3.4)
# --------------------------------------------------------------------------
async def test_list_returns_only_my_rooms(api_client: Any) -> None:
    """FR-3.2의 첫 기준 — 속한 방만 나오고 속하지 않은 방은 나오지 않는다."""
    alice, bob, carol = await _friends(api_client)
    mine = await api_client.post(
        "/rooms",
        json={"friend_user_ids": [bob["user"]["id"]], "name": "내 방"},
        headers=bearer(alice["token"]),
    )
    assert mine.status_code == 201, mine.text
    # carol이 bob과 만든 방 — alice는 참여자가 아니다.
    await api_client.post(
        "/friends", json={"username": "bob", "alias": "밥"}, headers=bearer(carol["token"])
    )
    theirs = await api_client.post(
        "/rooms",
        json={"friend_user_ids": [bob["user"]["id"]], "name": "남의 방"},
        headers=bearer(carol["token"]),
    )
    assert theirs.status_code == 201, theirs.text

    response = await api_client.get("/rooms", headers=bearer(alice["token"]))

    assert response.status_code == 200
    assert [room["name"] for room in response.json()["rooms"]] == ["내 방"]


async def test_list_is_empty_but_successful_for_a_user_without_rooms(api_client: Any) -> None:
    """FR-3.2의 둘째 기준 — 빈 목록은 **200**이고 오류가 아니다 (BR-3.4)."""
    alice = await signup_via_api(api_client, "alice")

    response = await api_client.get("/rooms", headers=bearer(alice["token"]))

    assert response.status_code == 200
    assert response.json() == {"rooms": []}


async def test_list_requires_authentication(api_client: Any) -> None:
    """토큰 없이 남의 방 목록을 물을 수 없다."""
    response = await api_client.get("/rooms")

    assert response.status_code == 401


# --------------------------------------------------------------------------
# 상세 (BR-3.3)
# --------------------------------------------------------------------------
async def test_detail_is_forbidden_for_a_non_member(api_client: Any) -> None:
    """참여자가 아니면 **403**이다 (BR-3.3)."""
    alice, bob, carol = await _friends(api_client)
    created = await api_client.post(
        "/rooms", json={"friend_user_ids": [bob["user"]["id"]]}, headers=bearer(alice["token"])
    )
    room_id = created.json()["id"]

    response = await api_client.get(f"/rooms/{room_id}", headers=bearer(carol["token"]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_detail_of_a_nonexistent_room_is_also_forbidden(api_client: Any) -> None:
    """**존재하지 않는 방도 403이다** (BR-3.3).

    404를 주면 방 id의 존재 여부가 새어나간다 — 없는 id를 훑어 어떤 id가 실재하는지
    알아낼 수 있다. U3의 BR-2.7이 같은 판단을 먼저 했다.
    """
    alice = await signup_via_api(api_client, "alice")

    response = await api_client.get("/rooms/999999", headers=bearer(alice["token"]))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_detail_never_exposes_another_members_toggle(api_client: Any) -> None:
    """**FR-6.1** — 응답의 `ai_check_enabled`는 호출자 본인의 값 하나뿐이다.

    `bob`이 자기 토글을 껐어도 `alice`의 상세 응답은 그 사실을 담지 않는다. 개인
    설정이며 남이 알 필요가 없다.
    """
    alice, bob, _carol = await _friends(api_client)
    created = await api_client.post(
        "/rooms", json={"friend_user_ids": [bob["user"]["id"]]}, headers=bearer(alice["token"])
    )
    room_id = created.json()["id"]
    turned_off = await api_client.patch(
        f"/rooms/{room_id}/ai-check", json={"enabled": False}, headers=bearer(bob["token"])
    )
    assert turned_off.status_code == 200, turned_off.text

    response = await api_client.get(f"/rooms/{room_id}", headers=bearer(alice["token"]))

    assert response.status_code == 200
    body = response.json()
    assert body["ai_check_enabled"] is True
    # 참여자 항목에는 토글 필드 자체가 없다 — 스키마가 구조적으로 막는다.
    assert all("ai_check_enabled" not in member for member in body["members"])


async def test_detail_requires_authentication(api_client: Any) -> None:
    """토큰 없이 방 상세를 볼 수 없다."""
    response = await api_client.get("/rooms/1")

    assert response.status_code == 401

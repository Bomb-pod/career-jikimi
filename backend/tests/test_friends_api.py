"""`/users/search`와 `/friends/*` — FR-2.1~FR-2.4의 수용 기준.

**실제 MariaDB에서 돈다.** `TEST_DATABASE_URL`이 없으면 전부 skip된다.
`UNIQUE (owner_id, friend_id)`의 409 변환과 `utf8mb4` 별칭 저장은 실제 제약과
콜레이션이 있어야 확인된다.

대응: FR-2.1, FR-2.2, FR-2.3, FR-2.4, BR-2.1~BR-2.7.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import bearer, signup_via_api

ALIAS = "회사 김대리"


async def _two_users(client: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    """`alice`와 `bob`을 만든다. `bob`의 표시명은 `"bob"`이다 (username 복사).

    FR-2.4의 수용 기준이 "B의 계정 표시명이 bob"을 전제하므로 그대로 맞춘다.
    """
    alice = await signup_via_api(client, "alice")
    bob = await signup_via_api(client, "bob")
    return alice, bob


# --------------------------------------------------------------------------
# 검색 (FR-2.1, BR-2.1)
# --------------------------------------------------------------------------
async def test_exact_match_finds_one_user(api_client: Any) -> None:
    """FR-2.1의 첫 기준 — `"alice"`로 검색하면 그 한 명이 나온다."""
    alice, _bob = await _two_users(api_client)

    response = await api_client.get(
        "/users/search", params={"username": "bob"}, headers=bearer(alice["token"])
    )

    assert response.status_code == 200
    assert response.json()["user"]["username"] == "bob"


async def test_partial_match_returns_an_empty_result_with_200(api_client: Any) -> None:
    """FR-2.1의 둘째 기준 — `"ali"`로 검색하면 결과가 비어 있다.

    **404가 아니라 200 + `null`이다** (BR-2.1). 검색은 성공했고 결과가 없을 뿐이다.
    등록(BR-2.6)이 404를 주는 것과 의도적으로 다르며, 이 둘을 합치지 않는다.
    """
    alice, _bob = await _two_users(api_client)

    response = await api_client.get(
        "/users/search", params={"username": "ali"}, headers=bearer(alice["token"])
    )

    assert response.status_code == 200
    assert response.json() == {"user": None}


async def test_search_requires_authentication(api_client: Any) -> None:
    """검색도 보호 경로다 — 토큰 없이 남의 아이디 존재 여부를 물을 수 없다."""
    response = await api_client.get("/users/search", params={"username": "alice"})

    assert response.status_code == 401


# --------------------------------------------------------------------------
# 등록 (FR-2.2, BR-2.2~BR-2.6)
# --------------------------------------------------------------------------
async def test_add_friend_appears_immediately_with_the_alias(api_client: Any) -> None:
    """FR-2.2의 첫 기준 — 승인 대기 없이 즉시 목록에 나타나고 별칭이 저장된다."""
    alice, bob = await _two_users(api_client)

    created = await api_client.post(
        "/friends",
        json={"username": "bob", "alias": ALIAS},
        headers=bearer(alice["token"]),
    )

    assert created.status_code == 201
    assert created.json()["alias"] == ALIAS
    assert created.json()["friend_user_id"] == bob["user"]["id"]

    listed = await api_client.get("/friends", headers=bearer(alice["token"]))
    assert listed.status_code == 200
    assert [item["alias"] for item in listed.json()["friends"]] == [ALIAS]


async def test_friend_list_never_exposes_the_other_persons_display_name(
    api_client: Any,
) -> None:
    """**FR-2.4의 수용 기준** — `"bob"`이 목록 응답의 어디에도 없다.

    별칭만 보여야 한다. 응답 본문 전체를 문자열로 훑는 이유 — 필드를 하나 추가하면서
    상대의 이름이 실리는 것이 이 요구사항이 깨지는 가장 흔한 방식이고, 특정 키만
    확인하는 테스트는 그것을 놓친다.
    """
    alice, _bob = await _two_users(api_client)
    await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS}, headers=bearer(alice["token"])
    )

    listed = await api_client.get("/friends", headers=bearer(alice["token"]))

    assert ALIAS in listed.text
    assert "bob" not in listed.text


async def test_empty_alias_is_rejected(api_client: Any) -> None:
    """FR-2.2의 둘째 기준 — 빈 별칭은 400이고 친구는 등록되지 않는다 (BR-2.2)."""
    alice, _bob = await _two_users(api_client)

    response = await api_client.post(
        "/friends", json={"username": "bob", "alias": ""}, headers=bearer(alice["token"])
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALIAS_REQUIRED"

    listed = await api_client.get("/friends", headers=bearer(alice["token"]))
    assert listed.json()["friends"] == []


async def test_whitespace_only_alias_is_rejected(api_client: Any) -> None:
    """**트림 후 빈 값도 400이다** — BR-2.2의 핵심.

    `friendships.alias`의 NOT NULL은 `"   "`를 막지 못한다. DB가 볼 때 그것은 값이
    있는 문자열이다. 이 검사가 빠지면 공백만 있는 별칭이 저장되고, 목록에 빈 줄이
    나타난다.
    """
    alice, _bob = await _two_users(api_client)

    response = await api_client.post(
        "/friends", json={"username": "bob", "alias": "   "}, headers=bearer(alice["token"])
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALIAS_REQUIRED"


async def test_alias_is_stored_trimmed(api_client: Any) -> None:
    """앞뒤 공백은 저장 전에 제거된다 (BR-2.2).

    남기면 목록 항목이 들쭉날쭉하게 보이고, 같은 이름을 붙였는데 다르게 보인다.
    """
    alice, _bob = await _two_users(api_client)

    created = await api_client.post(
        "/friends",
        json={"username": "bob", "alias": f"  {ALIAS}  "},
        headers=bearer(alice["token"]),
    )

    assert created.status_code == 201
    assert created.json()["alias"] == ALIAS


async def test_friendship_is_one_directional(api_client: Any) -> None:
    """FR-2.2의 셋째 기준 — A가 B를 등록해도 **B의 목록에 A는 없다** (BR-2.3)."""
    alice, bob = await _two_users(api_client)
    await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS}, headers=bearer(alice["token"])
    )

    bobs_list = await api_client.get("/friends", headers=bearer(bob["token"]))

    assert bobs_list.status_code == 200
    assert bobs_list.json()["friends"] == []


async def test_adding_the_same_friend_twice_is_a_conflict(api_client: Any) -> None:
    """중복 등록은 409 `ALREADY_FRIEND`다 — BR-2.4.

    사전 조회가 아니라 `UNIQUE (owner_id, friend_id)` 위반을 변환한 결과다.
    """
    alice, _bob = await _two_users(api_client)
    first = await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS}, headers=bearer(alice["token"])
    )
    assert first.status_code == 201

    second = await api_client.post(
        "/friends", json={"username": "bob", "alias": "다른 별칭"}, headers=bearer(alice["token"])
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ALREADY_FRIEND"
    # 첫 등록의 별칭이 그대로 남아 있다 — 실패한 요청이 기존 값을 건드리지 않았다.
    listed = await api_client.get("/friends", headers=bearer(alice["token"]))
    assert [item["alias"] for item in listed.json()["friends"]] == [ALIAS]


async def test_adding_yourself_is_rejected(api_client: Any) -> None:
    """자기 자신은 등록할 수 없다 — BR-2.5, 400 `CANNOT_FRIEND_SELF`."""
    alice, _bob = await _two_users(api_client)

    response = await api_client.post(
        "/friends", json={"username": "alice", "alias": "나"}, headers=bearer(alice["token"])
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CANNOT_FRIEND_SELF"


async def test_adding_a_missing_user_is_not_found(api_client: Any) -> None:
    """없는 아이디로 등록하면 **404**다 — BR-2.6.

    같은 아이디로 **검색**하면 200 + `null`이 나온다(위 테스트). 두 응답이 다른 것이
    설계의 의도다 — 검색은 "찾아봤다"이고 등록은 "이 대상에 대해 작업하라"이기
    때문이다. 이 두 테스트가 함께 있어야 그 구분이 회귀로부터 지켜진다.
    """
    alice, _bob = await _two_users(api_client)

    response = await api_client.post(
        "/friends",
        json={"username": "nobody-here", "alias": ALIAS},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_alias_check_comes_before_the_target_lookup(api_client: Any) -> None:
    """규칙 우선순위 — 별칭이 비고 대상도 없으면 **별칭 오류만** 응답한다.

    `business-rules.md` § 규칙 간 우선순위가 "싼 검사부터"와 "첫 번째 위반만
    응답한다"를 정했다. 순서가 뒤집히면 사용자는 아이디를 고친 다음에야 별칭이
    필요하다는 것을 알게 된다.
    """
    alice, _bob = await _two_users(api_client)

    response = await api_client.post(
        "/friends",
        json={"username": "nobody-here", "alias": "  "},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALIAS_REQUIRED"


# --------------------------------------------------------------------------
# 별칭 수정 (FR-2.3, BR-2.2, BR-2.7)
# --------------------------------------------------------------------------
async def test_alias_can_be_updated(api_client: Any) -> None:
    """FR-2.3의 첫 기준 — 수정한 별칭이 목록에 반영된다."""
    alice, _bob = await _two_users(api_client)
    created = await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS}, headers=bearer(alice["token"])
    )
    friendship_id = created.json()["id"]

    updated = await api_client.patch(
        f"/friends/{friendship_id}",
        json={"alias": "김철수 팀장"},
        headers=bearer(alice["token"]),
    )

    assert updated.status_code == 200
    assert updated.json()["alias"] == "김철수 팀장"

    listed = await api_client.get("/friends", headers=bearer(alice["token"]))
    assert [item["alias"] for item in listed.json()["friends"]] == ["김철수 팀장"]


async def test_updating_to_an_empty_alias_keeps_the_existing_value(api_client: Any) -> None:
    """FR-2.3의 둘째 기준 — 빈 값으로 수정하면 400이고 **기존 별칭이 유지된다**.

    유지 여부를 확인하는 이유 — 400을 주면서 이미 컬럼을 비운 구현도 상태 코드만
    보면 통과한다.
    """
    alice, _bob = await _two_users(api_client)
    created = await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS}, headers=bearer(alice["token"])
    )
    friendship_id = created.json()["id"]

    response = await api_client.patch(
        f"/friends/{friendship_id}", json={"alias": "   "}, headers=bearer(alice["token"])
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "ALIAS_REQUIRED"

    listed = await api_client.get("/friends", headers=bearer(alice["token"]))
    assert [item["alias"] for item in listed.json()["friends"]] == [ALIAS]


async def test_updating_someone_elses_friendship_is_forbidden(api_client: Any) -> None:
    """남의 friendship은 403 `FORBIDDEN`이다 — BR-2.7."""
    alice, bob = await _two_users(api_client)
    created = await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS}, headers=bearer(alice["token"])
    )
    alices_friendship_id = created.json()["id"]

    response = await api_client.patch(
        f"/friends/{alices_friendship_id}",
        json={"alias": "가로채기"},
        headers=bearer(bob["token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    # alice의 별칭이 그대로다.
    listed = await api_client.get("/friends", headers=bearer(alice["token"]))
    assert [item["alias"] for item in listed.json()["friends"]] == [ALIAS]


async def test_updating_a_nonexistent_friendship_is_also_forbidden(api_client: Any) -> None:
    """**없는 id도 403이다 — 404가 아니다** (BR-2.7).

    404를 주면 "그 id는 있지만 네 것이 아니다"(403)와 "그 id는 없다"(404)가 구분되어,
    남의 friendship id 존재 여부를 훑어낼 수 있다. 이 테스트가 그 누출을 막는다.
    """
    alice, _bob = await _two_users(api_client)

    response = await api_client.patch(
        "/friends/999999", json={"alias": "아무거나"}, headers=bearer(alice["token"])
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_missing_and_foreign_friendship_ids_respond_identically(api_client: Any) -> None:
    """없는 id와 남의 id의 응답이 **완전히 같다** — BR-2.7의 비구분.

    상태 코드만 같고 본문이 다르면 여전히 새어나간다. 본문 전체를 비교한다.
    """
    alice, bob = await _two_users(api_client)
    created = await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS}, headers=bearer(alice["token"])
    )

    foreign = await api_client.patch(
        f"/friends/{created.json()['id']}", json={"alias": "x"}, headers=bearer(bob["token"])
    )
    missing = await api_client.patch(
        "/friends/999999", json={"alias": "x"}, headers=bearer(bob["token"])
    )

    assert foreign.status_code == missing.status_code == 403
    assert foreign.json() == missing.json()


async def test_alias_update_requires_authentication(api_client: Any) -> None:
    """토큰 없이 수정할 수 없다 — 인증이 없으면 소유자를 알 수 없다."""
    response = await api_client.patch("/friends/1", json={"alias": "x"})

    assert response.status_code == 401

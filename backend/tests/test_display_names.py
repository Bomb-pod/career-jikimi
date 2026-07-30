"""`resolve_display_names()` — BR-2.8과 그 성능 계약.

이 함수는 **U4·U5가 호출하는 계약**이다(`unit-of-work-dependency.md`). 그래서 결과
정확성만 보지 않고 **나가는 쿼리 수**까지 확인한다 — 반복문 안 조회로 바뀌면 U4의
방 상세와 U5의 히스토리가 참여자 수만큼 느려지고, 그 회귀는 기능 테스트로는 절대
드러나지 않는다.

라우터를 거치지 않고 서비스 함수를 직접 부른다 — 이 함수는 HTTP 표면이 없다.

**실제 MariaDB에서 돈다.** `TEST_DATABASE_URL`이 없으면 전부 skip된다.
"""

from __future__ import annotations

from typing import Any

from app.friends.service import resolve_display_names
from app.models import Friendship, User
from tests.conftest import capture_sql, selects


async def _make_user(session: Any, username: str, display_name: str | None = None) -> User:
    """사용자 하나를 만든다. `display_name`을 주지 않으면 `username`을 복사한다.

    회원가입(W1)의 초기값 규칙과 같게 둔다 — 여기서만 다르게 만들면 테스트가
    실제 데이터 모양과 어긋난다.
    """
    user = User(
        username=username,
        display_name=display_name if display_name is not None else username,
        # 이 테스트는 해싱을 검증하지 않는다. 자리 채우기 값이다.
        password_hash="$argon2id$placeholder",
    )
    session.add(user)
    await session.flush()
    return user


async def _befriend(session: Any, owner: User, friend: User, alias: str) -> Friendship:
    friendship = Friendship(owner_id=owner.id, friend_id=friend.id, alias=alias)
    session.add(friendship)
    await session.flush()
    return friendship


# --------------------------------------------------------------------------
# 정확성 (BR-2.8)
# --------------------------------------------------------------------------
async def test_alias_wins_over_the_account_display_name(db_session: Any) -> None:
    """친구로 등록한 상대는 **별칭**으로 해석된다 — FR-2.4.

    `display_name`이 `"bob"`인데도 결과가 `"회사 김대리"`여야 한다.
    """
    alice = await _make_user(db_session, "alice")
    bob = await _make_user(db_session, "bob")
    await _befriend(db_session, alice, bob, "회사 김대리")

    resolved = await resolve_display_names(db_session, alice.id, [bob.id])

    assert resolved == {bob.id: "회사 김대리"}


async def test_non_friend_falls_back_to_the_display_name(db_session: Any) -> None:
    """친구가 아닌 참여자는 그 사용자의 `display_name`으로 떨어진다.

    **폴백이 발생하는 조건은 하나뿐이다** — 방에 내가 친구로 등록하지 않은 참여자가
    있을 때(다른 사람이 초대, FR-10.1). 친구 목록에서는 절대 일어나지 않는다.
    """
    alice = await _make_user(db_session, "alice")
    carol = await _make_user(db_session, "carol", display_name="캐롤")

    resolved = await resolve_display_names(db_session, alice.id, [carol.id])

    assert resolved == {carol.id: "캐롤"}


async def test_mixed_input_resolves_each_by_its_own_rule(db_session: Any) -> None:
    """별칭이 있는 id와 없는 id가 섞여도 각각 자기 규칙으로 해석된다.

    `business-logic-model.md` § 표시명 해석의 예시(`[3, 7, 12]`)와 같은 모양이다.
    """
    alice = await _make_user(db_session, "alice")
    bob = await _make_user(db_session, "bob")
    dave = await _make_user(db_session, "dave")
    carol = await _make_user(db_session, "carol", display_name="캐롤")
    await _befriend(db_session, alice, bob, "회사 김대리")
    await _befriend(db_session, alice, dave, "동생")

    resolved = await resolve_display_names(db_session, alice.id, [bob.id, dave.id, carol.id])

    assert resolved == {bob.id: "회사 김대리", dave.id: "동생", carol.id: "캐롤"}


async def test_someone_elses_alias_is_not_used(db_session: Any) -> None:
    """다른 사람이 붙인 별칭은 내 해석에 쓰이지 않는다 — 별칭은 `owner_id`의 것이다.

    이 검사가 없으면 `owner_id` 조건이 빠진 구현도 통과하고, 그러면 남이 붙인 이름이
    내 화면에 나타난다.
    """
    alice = await _make_user(db_session, "alice")
    bob = await _make_user(db_session, "bob")
    carol = await _make_user(db_session, "carol", display_name="캐롤")
    # carol이 bob에게 붙인 별칭 — alice와는 무관하다.
    await _befriend(db_session, carol, bob, "캐롤의 별칭")

    resolved = await resolve_display_names(db_session, alice.id, [bob.id])

    assert resolved == {bob.id: "bob"}


async def test_own_id_resolves_to_own_display_name(db_session: Any) -> None:
    """`owner_id` 자신이 목록에 있어도 된다 — 자기 `display_name`이 나온다.

    방 참여자 목록에는 자신이 포함된다. 자기 자신은 자기 친구가 아니므로 폴백 경로로
    떨어지는 것이 맞다.
    """
    alice = await _make_user(db_session, "alice", display_name="앨리스")

    resolved = await resolve_display_names(db_session, alice.id, [alice.id])

    assert resolved == {alice.id: "앨리스"}


async def test_unknown_user_id_is_absent_from_the_result(db_session: Any) -> None:
    """`users`에 없는 id는 **키가 아예 없다** — 가짜 이름을 만들지 않는다.

    호출자가 `dict.get()`으로 다뤄야 한다는 계약을 여기서 고정한다. 빈 문자열이나
    `"알 수 없음"`을 채워주면 호출자가 없는 사용자를 화면에 그린다.
    """
    alice = await _make_user(db_session, "alice")

    resolved = await resolve_display_names(db_session, alice.id, [999_999_999])

    assert resolved == {}


async def test_duplicate_ids_are_folded(db_session: Any) -> None:
    """같은 id가 여러 번 들어와도 결과는 한 번이다 — 입력 정리를 호출자에게 떠넘기지 않는다."""
    alice = await _make_user(db_session, "alice")
    bob = await _make_user(db_session, "bob")
    await _befriend(db_session, alice, bob, "회사 김대리")

    resolved = await resolve_display_names(db_session, alice.id, [bob.id, bob.id, bob.id])

    assert resolved == {bob.id: "회사 김대리"}


# --------------------------------------------------------------------------
# 쿼리 수 (BR-2.8의 성능 계약)
# --------------------------------------------------------------------------
async def test_empty_input_sends_no_query_at_all(db_session: Any) -> None:
    """빈 입력은 쿼리를 **아예 보내지 않는다**.

    `IN ()`은 MariaDB에서 구문 오류이고, SQLAlchemy가 대신 만들어주는 항상-거짓
    표현식도 왕복 한 번을 쓴다. 참여자가 없는 방을 그릴 때 그 왕복은 순수 낭비다.
    """
    alice = await _make_user(db_session, "alice")

    with capture_sql() as statements:
        resolved = await resolve_display_names(db_session, alice.id, [])

    assert resolved == {}
    assert selects(statements) == []


async def test_all_friends_needs_exactly_one_query(db_session: Any) -> None:
    """전원이 친구면 **쿼리 1회**로 끝난다 — 두 번째 조회는 필요할 때만 돈다.

    친구 목록 조회가 이 경우다. 두 번째 조회를 무조건 돌리는 구현이면 여기가 2가 된다.
    """
    alice = await _make_user(db_session, "alice")
    friends = [await _make_user(db_session, f"friend-{index}") for index in range(3)]
    for index, friend in enumerate(friends):
        await _befriend(db_session, alice, friend, f"별칭{index}")

    with capture_sql() as statements:
        resolved = await resolve_display_names(db_session, alice.id, [f.id for f in friends])

    assert len(resolved) == 3
    assert len(selects(statements)) == 1, selects(statements)


async def test_fallback_needs_exactly_two_queries(db_session: Any) -> None:
    """폴백이 있으면 쿼리 **2회**다. 대상이 몇 명이든 2회다."""
    alice = await _make_user(db_session, "alice")
    friend = await _make_user(db_session, "friend")
    await _befriend(db_session, alice, friend, "친구")
    strangers = [await _make_user(db_session, f"stranger-{index}") for index in range(5)]

    with capture_sql() as statements:
        resolved = await resolve_display_names(
            db_session, alice.id, [friend.id, *[s.id for s in strangers]]
        )

    assert len(resolved) == 6
    assert len(selects(statements)) == 2, selects(statements)


async def test_query_count_does_not_grow_with_the_number_of_targets(db_session: Any) -> None:
    """**N+1 회귀 방지** — 대상이 3명일 때와 30명일 때의 쿼리 수가 같다.

    이것이 이 파일에서 가장 중요한 테스트다. 반복문 안 조회로 바뀌면 결과는 여전히
    정확해서 다른 모든 테스트가 통과하고, 느려진 것만 나중에 사람이 눈치챈다.
    `component-dependency.md`가 이 위험을 열린 항목으로 남겼고 여기서 닫는다.
    """
    alice = await _make_user(db_session, "alice")
    friends = [await _make_user(db_session, f"many-{index}") for index in range(30)]
    for index, friend in enumerate(friends):
        await _befriend(db_session, alice, friend, f"별칭{index}")
    ids = [friend.id for friend in friends]

    with capture_sql() as few_statements:
        few = await resolve_display_names(db_session, alice.id, ids[:3])
    with capture_sql() as many_statements:
        many = await resolve_display_names(db_session, alice.id, ids)

    assert len(few) == 3
    assert len(many) == 30
    assert len(selects(few_statements)) == len(selects(many_statements)) == 1

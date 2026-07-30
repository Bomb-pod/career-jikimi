"""히스토리 — W2의 커서 페이지네이션 (FR-3.3, FR-4.4, BR-4.4, BR-3.3).

**`before`가 경계를 포함하지 않는다**는 것과 **표시명 해석이 한 번**이라는 것이
이 파일의 두 축이다. 전자는 페이지 경계마다 한 건씩 중복되는 버그이고, 후자는
메시지 수에 비례해 조회가 늘어나는 N+1이다 — 둘 다 눈으로는 잘 보이지 않는다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.messages import history
from app.messages.constants import HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT
from app.messages.exceptions import MessageForbidden
from tests.conftest import bearer, capture_sql, make_room, make_user, selects, signup_via_api
from tests.messaging_support import seed_membership, seed_messages

ALIAS_BOB = "회사 김대리"


async def _room_with(session: Any, username: str, count: int) -> tuple[Any, Any]:
    user = await make_user(session, username)
    room = await make_room(session, user.id, f"{username}의 방")
    await seed_membership(session, room.id, [user.id])
    if count:
        await seed_messages(session, room.id, user.id, count)
    return user, room


# --------------------------------------------------------------------------
# 기본 페이지 (BR-4.4)
# --------------------------------------------------------------------------
async def test_history_returns_the_latest_page_in_descending_seq(db_session: Any) -> None:
    """기본은 **최신 50개**를 `seq` 내림차순으로 준다.

    내림차순인 이유 — 채팅은 최신부터 거슬러 읽는다. 오름차순이면 첫 페이지에
    방을 만든 날의 인사말이 온다.
    """
    alice, room = await _room_with(db_session, "hist_alice", 120)

    page = await history.list_messages(db_session, alice.id, room.id)

    assert len(page) == HISTORY_DEFAULT_LIMIT
    seqs = [item.seq for item in page]
    assert seqs == sorted(seqs, reverse=True)
    assert seqs[0] == 120
    assert seqs[-1] == 120 - HISTORY_DEFAULT_LIMIT + 1


async def test_before_excludes_the_cursor_row(db_session: Any) -> None:
    """**`before`는 경계를 포함하지 않는다** (`<`, BR-4.4).

    포함하면 페이지 경계에서 한 건이 매번 중복된다 — 클라이언트가 ID로 접어 화면에는
    안 보이므로 **발견이 늦다**. 그러다 페이지를 넘길수록 한 건씩 덜 받아 마지막
    페이지에서 메시지가 사라진다.
    """
    alice, room = await _room_with(db_session, "hist_before", 30)

    page = await history.list_messages(db_session, alice.id, room.id, before=20, limit=5)

    seqs = [item.seq for item in page]
    assert 20 not in seqs
    assert seqs == [19, 18, 17, 16, 15]


async def test_paging_with_the_cursor_covers_every_row_exactly_once(db_session: Any) -> None:
    """커서를 이어 붙이면 전체가 **중복도 누락도 없이** 나온다.

    앞 테스트의 결과다. 경계 하나를 잘못 쓰면 여기서 개수가 어긋난다.
    """
    alice, room = await _room_with(db_session, "hist_page", 25)

    collected: list[int] = []
    cursor: int | None = None
    while True:
        page = await history.list_messages(db_session, alice.id, room.id, before=cursor, limit=7)
        if not page:
            break
        collected.extend(item.seq for item in page)
        cursor = page[-1].seq

    assert collected == list(range(25, 0, -1))


async def test_limit_is_clamped_to_the_maximum(db_session: Any) -> None:
    """`limit` 상한은 100이고, 넘는 값은 **거부하지 않고 자른다** (BR-4.4).

    400을 주면 클라이언트가 상한을 알아야만 조회할 수 있다. 페이지 크기는 도메인
    규칙이 아니라 서버가 정하는 자원 한도다.
    """
    alice, room = await _room_with(db_session, "hist_limit", 150)

    page = await history.list_messages(db_session, alice.id, room.id, limit=1_000)

    assert len(page) == HISTORY_MAX_LIMIT


async def test_an_empty_room_returns_an_empty_page(db_session: Any) -> None:
    """빈 방도 오류가 아니다 — 빈 배열이다."""
    alice, room = await _room_with(db_session, "hist_empty", 0)

    assert await history.list_messages(db_session, alice.id, room.id) == []


async def test_a_cursor_past_the_beginning_returns_an_empty_page(db_session: Any) -> None:
    """끝까지 거슬러 올라가면 빈 배열이다 — 그것이 "더 없음"의 신호다."""
    alice, room = await _room_with(db_session, "hist_end", 5)

    assert await history.list_messages(db_session, alice.id, room.id, before=1) == []


# --------------------------------------------------------------------------
# 참여 자격 (BR-3.3)
# --------------------------------------------------------------------------
async def test_a_non_member_cannot_read_history(db_session: Any) -> None:
    """참여자가 아니면 403이다 — 없는 방도 마찬가지다."""
    _alice, room = await _room_with(db_session, "hist_owner", 3)
    stranger = await make_user(db_session, "hist_stranger")

    with pytest.raises(MessageForbidden):
        await history.list_messages(db_session, stranger.id, room.id)

    with pytest.raises(MessageForbidden):
        await history.list_messages(db_session, stranger.id, 99_999_999)


# --------------------------------------------------------------------------
# 표시명 (FR-2.4, BR-2.8) — N+1 회귀
# --------------------------------------------------------------------------
async def test_display_names_are_resolved_in_a_fixed_number_of_queries(db_session: Any) -> None:
    """**메시지 수와 무관하게 조회 횟수가 같다** — N+1 회귀 방지.

    발신자를 반복문 안에서 해석하면 50개 페이지에 50번 조회가 붙는다. U3의
    `resolve_display_names()`에는 쿼리 횟수 회귀 테스트가 있지만, 그것을 방마다·
    메시지마다 부르면 붉어지는 것은 그 테스트가 아니라 이 경로다.

    절대 횟수를 못 박지 않고 **두 크기를 비교**하는 이유 — 절대 횟수는 U3의 내부
    구현이 바뀌면 흔들리지만, "메시지가 늘어도 늘지 않는다"는 이 경로의 성질이다.
    """
    alice = await make_user(db_session, "hist_names")
    room = await make_room(db_session, alice.id, "표시명")
    senders = [alice]
    for index in range(3):
        senders.append(await make_user(db_session, f"hist_sender{index}"))
    await seed_membership(db_session, room.id, [user.id for user in senders])
    seq = 1
    for _round in range(10):
        for sender in senders:
            await seed_messages(db_session, room.id, sender.id, 1, start_seq=seq)
            seq += 1
    await db_session.commit()

    with capture_sql() as small:
        await history.list_messages(db_session, alice.id, room.id, limit=4)
    with capture_sql() as large:
        await history.list_messages(db_session, alice.id, room.id, limit=40)

    assert len(selects(large)) == len(
        selects(small)
    ), f"메시지가 늘자 조회가 늘었다 (4개={len(selects(small))}, 40개={len(selects(large))})"


async def test_history_uses_the_callers_alias_for_the_sender(
    api_client: Any, db_session: Any
) -> None:
    """발신자 표시명은 **호출자가 붙인 별칭**이다 (FR-2.4).

    상대의 계정 표시명이 응답에 새면 안 된다 — 규칙을 이 모듈이 복제하지 않고 U3의
    단일 출처를 부르는지가 여기서 드러난다.
    """
    alice = await signup_via_api(api_client, "alice")
    bob = await signup_via_api(api_client, "bob")
    added = await api_client.post(
        "/friends", json={"username": "bob", "alias": ALIAS_BOB}, headers=bearer(alice["token"])
    )
    assert added.status_code == 201, added.text

    room = await make_room(db_session, alice["user"]["id"], "별칭 확인")
    await seed_membership(db_session, room.id, [alice["user"]["id"], bob["user"]["id"]])
    await seed_messages(db_session, room.id, bob["user"]["id"], 1)
    await db_session.commit()

    response = await api_client.get(f"/rooms/{room.id}/messages", headers=bearer(alice["token"]))

    assert response.status_code == 200, response.text
    messages = response.json()["messages"]
    assert messages[0]["sender_display_name"] == ALIAS_BOB
    assert "bob" not in response.text


# --------------------------------------------------------------------------
# HTTP 표면
# --------------------------------------------------------------------------
async def test_api_history_carries_the_verification_status_and_report_flag(
    api_client: Any, db_session: Any
) -> None:
    """응답에 `verification_status`와 `misdirect_reported_at`이 있다.

    전자는 미검증 배지의 근거이고(BR-8.6), 후자는 신고 표시의 근거다(FR-11.3).
    **스크롤해서 다시 봐도 배지가 남아야 하므로**(FR-8.6) 히스토리에 실려야 한다 —
    실시간 알림으로만 주면 새로고침에 사라진다.
    """
    alice = await signup_via_api(api_client, "hist_api")
    room = await make_room(db_session, alice["user"]["id"], "상태 노출")
    await seed_membership(db_session, room.id, [alice["user"]["id"]])
    await seed_messages(db_session, room.id, alice["user"]["id"], 1, status="skipped_no_context")
    await db_session.commit()

    response = await api_client.get(f"/rooms/{room.id}/messages", headers=bearer(alice["token"]))

    assert response.status_code == 200, response.text
    message = response.json()["messages"][0]
    assert message["verification_status"] == "skipped_no_context"
    assert message["misdirect_reported_at"] is None


async def test_api_history_rejects_a_non_member_with_403(api_client: Any, db_session: Any) -> None:
    """비참여자는 403이다 (BR-3.3)."""
    alice = await signup_via_api(api_client, "hist_api_owner")
    stranger = await signup_via_api(api_client, "hist_api_stranger")
    room = await make_room(db_session, alice["user"]["id"], "남의 방")
    await seed_membership(db_session, room.id, [alice["user"]["id"]])
    await db_session.commit()

    response = await api_client.get(f"/rooms/{room.id}/messages", headers=bearer(stranger["token"]))

    assert response.status_code == 403, response.text

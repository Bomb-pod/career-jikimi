"""오발송 신고 — W3 (FR-11.1~FR-11.3, BR-11.1~BR-11.3).

**`verification_status`를 보지 않는다**는 것이 이 파일의 핵심이다 (BR-11.2). 6값 어느
상태든 신고할 수 있으며, 그것이 이 기능의 존재 이유다 — `flagged_sent`를 제외한
다섯 상태가 사용자 판단에 대한 신호를 남기지 않는 사각지대이고, 신고가 그것을 메운다.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.messages import report as report_service
from app.messages.exceptions import MessageForbidden
from app.models import VERIFICATION_STATUS_VALUES
from tests.conftest import bearer, make_room, make_user, signup_via_api
from tests.messaging_support import seed_membership, seed_messages


async def _one_message(session: Any, username: str, status: str = "ok") -> tuple[Any, Any]:
    """사용자 하나와 그가 보낸 메시지 하나. `(user, message)`."""
    user = await make_user(session, username)
    room = await make_room(session, user.id, f"{username}의 방")
    await seed_membership(session, room.id, [user.id])
    messages = await seed_messages(session, room.id, user.id, 1, status=status)
    return user, messages[0]


# --------------------------------------------------------------------------
# 신고와 취소 (FR-11.1, BR-11.3)
# --------------------------------------------------------------------------
async def test_reporting_my_own_message_records_the_time(db_session: Any) -> None:
    """내 메시지를 신고하면 `misdirect_reported_at`이 기록된다."""
    alice, message = await _one_message(db_session, "rep_alice")

    reported_at = await report_service.report(db_session, alice.id, message.id)

    await db_session.refresh(message)
    assert message.misdirect_reported_at is not None
    assert message.misdirect_reported_at == reported_at


async def test_unreporting_clears_the_time(db_session: Any) -> None:
    """취소하면 NULL로 돌아간다 — **이력은 남지 않는다** (BR-11.3).

    별도 신고 테이블을 두지 않은 대가다. 신고→취소→신고를 반복해도 마지막 상태만
    알 수 있으며, 데모 범위에서 수용한다.
    """
    alice, message = await _one_message(db_session, "rep_undo")
    await report_service.report(db_session, alice.id, message.id)

    await report_service.unreport(db_session, alice.id, message.id)

    await db_session.refresh(message)
    assert message.misdirect_reported_at is None


async def test_reporting_twice_is_not_an_error(db_session: Any) -> None:
    """이미 신고된 메시지를 다시 신고해도 200이다 — 시각만 갱신된다.

    멱등한 동작을 409로 막으면 더블클릭이 사용자에게 오류로 보인다. 이력이 남지 않는
    설계이므로 덮어써도 잃는 정보가 없다.
    """
    alice, message = await _one_message(db_session, "rep_twice")

    first = await report_service.report(db_session, alice.id, message.id)
    second = await report_service.report(db_session, alice.id, message.id)

    assert first is not None
    assert second is not None


async def test_unreporting_an_unreported_message_is_not_an_error(db_session: Any) -> None:
    """신고되지 않은 메시지를 취소해도 200이다 — 결과 상태가 같다."""
    alice, message = await _one_message(db_session, "rep_noop")

    await report_service.unreport(db_session, alice.id, message.id)

    await db_session.refresh(message)
    assert message.misdirect_reported_at is None


# --------------------------------------------------------------------------
# 발신자 본인만 (BR-11.1)
# --------------------------------------------------------------------------
async def test_another_users_message_cannot_be_reported(db_session: Any) -> None:
    """남의 메시지는 신고할 수 없다 — 403.

    이것은 "내가 잘못 보냈다"는 **자기 신고**이지 타인 신고 기능이 아니다. 열어 두면
    수집되는 신호의 의미가 통째로 달라진다 (FR-11.1).
    """
    _alice, message = await _one_message(db_session, "rep_owner")
    intruder = await make_user(db_session, "rep_intruder")
    await seed_membership(db_session, message.room_id, [intruder.id])

    with pytest.raises(MessageForbidden):
        await report_service.report(db_session, intruder.id, message.id)

    await db_session.refresh(message)
    assert message.misdirect_reported_at is None


async def test_a_nonexistent_message_is_also_403(db_session: Any) -> None:
    """**없는 메시지도 403이다** — 404를 주면 메시지 id의 존재 여부가 새어나간다."""
    alice = await make_user(db_session, "rep_ghost")

    with pytest.raises(MessageForbidden):
        await report_service.report(db_session, alice.id, 99_999_999)

    with pytest.raises(MessageForbidden):
        await report_service.unreport(db_session, alice.id, 99_999_999)


# --------------------------------------------------------------------------
# 검증 상태와 무관 (BR-11.2)
# --------------------------------------------------------------------------
@pytest.mark.parametrize("status", VERIFICATION_STATUS_VALUES)
async def test_every_verification_status_is_reportable(db_session: Any, status: str) -> None:
    """**6값 전부** 신고 가능하다 (BR-11.2).

    상태별로 하나씩 도는 이유 — "어느 상태든"을 대표값 하나로 확인하면, 나중에 누가
    `verification_status`를 조건절에 넣어도 그 하나만 통과하며 나머지가 조용히 막힌다.
    `flagged_sent`를 제외한 다섯이 지금 신호가 없는 사각지대이고, `flagged_sent`까지
    포함하는 것이 "무관"의 뜻이다.
    """
    alice, message = await _one_message(db_session, f"rep_{status}", status=status)

    reported_at = await report_service.report(db_session, alice.id, message.id)

    assert reported_at is not None


# --------------------------------------------------------------------------
# HTTP 표면
# --------------------------------------------------------------------------
async def test_api_report_and_unreport_round_trip(api_client: Any, db_session: Any) -> None:
    """`POST`는 시각을, `DELETE`는 `null`을 돌려준다 — 화면이 그 값으로 표시를 그린다."""
    alice = await signup_via_api(api_client, "rep_api")
    room = await make_room(db_session, alice["user"]["id"], "API 신고")
    await seed_membership(db_session, room.id, [alice["user"]["id"]])
    messages = await seed_messages(db_session, room.id, alice["user"]["id"], 1, status="disabled")
    await db_session.commit()
    headers = bearer(alice["token"])

    reported = await api_client.post(f"/messages/{messages[0].id}/report", headers=headers)
    cleared = await api_client.delete(f"/messages/{messages[0].id}/report", headers=headers)

    assert reported.status_code == 200, reported.text
    assert reported.json()["misdirect_reported_at"] is not None
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["misdirect_reported_at"] is None


async def test_api_rejects_reporting_another_users_message(
    api_client: Any, db_session: Any
) -> None:
    """남의 메시지는 403이다 (BR-11.1)."""
    alice = await signup_via_api(api_client, "rep_api_owner")
    intruder = await signup_via_api(api_client, "rep_api_intruder")
    room = await make_room(db_session, alice["user"]["id"], "남의 메시지")
    await seed_membership(db_session, room.id, [alice["user"]["id"], intruder["user"]["id"]])
    messages = await seed_messages(db_session, room.id, alice["user"]["id"], 1)
    await db_session.commit()

    response = await api_client.post(
        f"/messages/{messages[0].id}/report", headers=bearer(intruder["token"])
    )

    assert response.status_code == 403, response.text

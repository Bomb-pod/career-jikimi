"""`force_log_id` 검증과 `user_action` 기록 — BR-6.9, BR-7.1, FR-8.3.

이 파일의 두 축:

1. **BR-6.9의 여섯 검사가 전부 살아 있는가.** 특히 텍스트 일치 검사는
   `application-design`에서 이월된 구멍의 해소라 회귀 테스트가 필요하다 —
   없으면 유효한 토큰에 다른 문장을 실어 판정 없이 `flagged_sent`로 통과한다.
2. **`set_user_action()`이 진짜 원자적 조건부 갱신인가.** 결과만 보면
   SELECT 후 UPDATE로 짜도 테스트가 통과하므로, `capture_sql()`로 **SQL에 조건절이
   실제로 있는지**까지 본다. 그것이 없으면 더블클릭에 메시지가 두 개 저장된다.

**실제 MariaDB에서 돈다.** OpenAI를 부르지 않는다 — 로그 행을 직접 만든다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
import sqlalchemy as sa

from app.judgment.exceptions import AlreadyResolved, ForceTokenForbidden, InvalidForceToken
from app.judgment.service import get_log_for_force, link_message, set_user_action
from app.models import JudgmentLog, Message
from tests.conftest import capture_sql, make_room, make_user

TEXT = "오늘 저녁에 치킨 어때?"


async def _log(
    session: Any,
    user_id: int,
    room_id: int,
    *,
    candidate_text: str = TEXT,
    verdict: str | None = "inappropriate",
    user_action: str | None = None,
) -> JudgmentLog:
    """판정 로그 하나를 직접 심는다. `judge()`를 거치지 않아 모델 호출이 없다."""
    log = JudgmentLog(
        user_id=user_id,
        room_id=room_id,
        context_from_seq=11,
        context_to_seq=13,
        candidate_text=candidate_text,
        score=Decimal("0.850") if verdict is not None else None,
        verdict=verdict,
        threshold=Decimal("0.700"),
        latency_ms=1234,
        prompt_tokens=312 if verdict is not None else None,
        completion_tokens=8 if verdict is not None else None,
        user_action=user_action,
    )
    session.add(log)
    await session.flush()
    return log


async def _actors(session: Any, username: str = "force-owner") -> tuple[int, int]:
    user = await make_user(session, username)
    room = await make_room(session, created_by=user.id)
    return user.id, room.id


# --------------------------------------------------------------------------
# BR-6.9 — 여섯 검사
# --------------------------------------------------------------------------
async def test_valid_token_passes(db_session: Any) -> None:
    """여섯 검사를 모두 통과하면 로그를 돌려준다. 호출자가 `verdict`로 상태를 파생한다."""
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id)

    found = await get_log_for_force(db_session, user_id, room_id, log.id, TEXT)

    assert found.id == log.id
    assert found.verdict == "inappropriate"  # 호출자가 flagged_sent로 파생한다


async def test_missing_log_is_rejected(db_session: Any) -> None:
    """없는 `force_log_id` — 400."""
    user_id, room_id = await _actors(db_session)

    with pytest.raises(InvalidForceToken):
        await get_log_for_force(db_session, user_id, room_id, 9_999_999, TEXT)


async def test_another_users_log_is_the_only_403(db_session: Any) -> None:
    """**소유자 불일치만 403이다** (BR-6.9). 나머지 다섯은 전부 400.

    남의 판정 로그로 강행 전송하는 것을 막는다. 400으로 덮으면 서버가 남의 자원에
    대한 접근을 입력 오류로 보고하는 셈이 되어, 로그에서 공격 시도를 구분할 수 없다.
    """
    owner_id, room_id = await _actors(db_session, "force-owner")
    other = await make_user(db_session, "force-intruder")
    log = await _log(db_session, owner_id, room_id)

    with pytest.raises(ForceTokenForbidden):
        await get_log_for_force(db_session, other.id, room_id, log.id, TEXT)


async def test_a_log_from_another_room_is_rejected(db_session: Any) -> None:
    """A방의 판정으로 B방에 강행 전송할 수 없다 — 400."""
    user_id, room_id = await _actors(db_session)
    other_room = await make_room(db_session, created_by=user_id, name="다른 방")
    log = await _log(db_session, user_id, room_id)

    with pytest.raises(InvalidForceToken):
        await get_log_for_force(db_session, user_id, other_room.id, log.id, TEXT)


async def test_a_consumed_token_is_rejected(db_session: Any) -> None:
    """`user_action`이 이미 있으면 소진된 토큰이다 — 400.

    이 검사가 1회성의 절반이고, 나머지 절반은 `set_user_action()`의 조건부
    UPDATE다 (BR-7.1). 검사만 있으면 동시 요청 둘이 모두 통과한다.
    """
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id, user_action="sent")

    with pytest.raises(InvalidForceToken):
        await get_log_for_force(db_session, user_id, room_id, log.id, TEXT)


async def test_mismatched_text_is_rejected(db_session: Any) -> None:
    """**텍스트가 다르면 거부한다** — 이월된 구멍의 회귀 테스트 (BR-6.9).

    이 검사가 없으면 소유자·방·미소진을 만족하는 토큰에 *다른 문장*을 실어 판정
    없이 `flagged_sent`로 통과시킬 수 있다. UI로는 도달할 수 없지만 API 직접
    호출로는 가능하다.
    """
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id, candidate_text="원래 판정받은 문장")

    with pytest.raises(InvalidForceToken):
        await get_log_for_force(db_session, user_id, room_id, log.id, "슬쩍 바꾼 문장")


async def test_text_comparison_trims_but_does_not_normalize(db_session: Any) -> None:
    """비교는 **트림 후 정확 일치**다. 공백 축약·유니코드 정규화를 하지 않는다.

    트림까지만 하는 이유 — 입력창의 앞뒤 공백은 사용자가 화면에서 볼 수 없어
    거기서 막으면 정상 재전송이 실패한다. 그 이상 정규화하면 "같다"의 범위가
    넓어지고, 넓어진 만큼 우회 여지가 생긴다.
    """
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id, candidate_text=f"  {TEXT}  ")

    # 트림 후 같으므로 통과한다.
    assert (await get_log_for_force(db_session, user_id, room_id, log.id, TEXT)).id == log.id

    # 가운데 공백을 접은 것은 **다른 문장이다.**
    inner_space = await _log(db_session, user_id, room_id, candidate_text="치킨  먹자")
    with pytest.raises(InvalidForceToken):
        await get_log_for_force(db_session, user_id, room_id, inner_space.id, "치킨 먹자")


async def test_appropriate_verdict_is_rejected(db_session: Any) -> None:
    """`verdict='appropriate'`인 로그는 강행 대상이 아니다 — 400.

    적절 판정은 이미 자동 전송되었다. 막지 않으면 그 경로로 판정을 건너뛸 수 있다.
    """
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id, verdict="appropriate")

    with pytest.raises(InvalidForceToken):
        await get_log_for_force(db_session, user_id, room_id, log.id, TEXT)


async def test_null_verdict_passes(db_session: Any) -> None:
    """`verdict`가 NULL(호출 실패)이면 **통과한다** — 이것이 FR-8.3의 장치다.

    판정 실패를 사용자가 수락했을 때 그 메시지는 `failed`여야 하는데(시도는
    했으므로), `degraded` 플래그만 세워 재요청하면 우선순위 규칙에 걸려
    `degraded`로 저장된다. `force_log_id`가 "이 시도는 이미 있었다"를 전달한다.
    """
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id, verdict=None)

    found = await get_log_for_force(db_session, user_id, room_id, log.id, TEXT)

    assert found.verdict is None  # 호출자가 failed로 파생한다


# --------------------------------------------------------------------------
# BR-7.1 — user_action은 한 번만
# --------------------------------------------------------------------------
async def test_second_set_user_action_raises_already_resolved(db_session: Any) -> None:
    """두 번째 호출은 409다 — 라벨이 덮어써지면 집계가 왜곡된다 (FR-7.3)."""
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id)

    await set_user_action(db_session, log.id, "cancelled")

    with pytest.raises(AlreadyResolved):
        await set_user_action(db_session, log.id, "sent")

    await db_session.refresh(log)
    assert log.user_action == "cancelled"  # 첫 값이 이긴다


async def test_set_user_action_emits_the_null_guard_in_sql(db_session: Any) -> None:
    """**조건절이 SQL에 실제로 있다** — `WHERE ... AND user_action IS NULL`.

    결과만 보면 SELECT 후 UPDATE로 짜도 위 테스트는 통과한다. 그 구현은 동시
    요청 둘이 모두 NULL을 보고 모두 갱신하는 경로를 남기며, **그것이 더블클릭에
    메시지 두 개가 저장되는 경로다** (BR-7.1). 그래서 SQL 자체를 본다.
    """
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id)

    with capture_sql() as statements:
        await set_user_action(db_session, log.id, "sent")

    updates = [item for item in statements if item.lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 1
    normalized = " ".join(updates[0].split()).lower()
    assert "user_action is null" in normalized
    # 검사와 갱신이 한 문장이어야 한다 — SELECT로 먼저 확인하고 UPDATE하면 안 된다.
    assert normalized.startswith("update judgment_logs set user_action")


async def test_set_user_action_on_a_missing_log_raises(db_session: Any) -> None:
    """없는 로그도 409다. 라우터가 호출 전에 소유권과 존재를 이미 확인한다."""
    with pytest.raises(AlreadyResolved):
        await set_user_action(db_session, 9_999_999, "sent")


async def test_consuming_the_token_makes_it_unusable(db_session: Any) -> None:
    """`user_action`을 채우는 것이 곧 토큰 소진이다 — 같은 토큰으로 두 번 못 보낸다.

    두 규칙(BR-6.9의 미소진 검사 + BR-7.1의 조건부 갱신)이 맞물려 1회성을
    만든다는 것을 한 흐름으로 확인한다.
    """
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id)

    await get_log_for_force(db_session, user_id, room_id, log.id, TEXT)
    await set_user_action(db_session, log.id, "sent")

    with pytest.raises(InvalidForceToken):
        await get_log_for_force(db_session, user_id, room_id, log.id, TEXT)


# --------------------------------------------------------------------------
# link_message
# --------------------------------------------------------------------------
async def test_link_message_attaches_the_message(db_session: Any) -> None:
    """전송이 확정된 뒤 로그를 메시지에 연결한다."""
    user_id, room_id = await _actors(db_session)
    log = await _log(db_session, user_id, room_id)
    message = Message(
        room_id=room_id,
        sender_id=user_id,
        seq=1,
        body=TEXT,
        verification_status="flagged_sent",
    )
    db_session.add(message)
    await db_session.flush()

    await link_message(db_session, log.id, message.id)

    await db_session.refresh(log)
    assert log.message_id == message.id


async def test_link_message_on_a_missing_log_raises(db_session: Any) -> None:
    """없는 로그에 연결하려 하면 조용히 넘기지 않는다.

    호출자는 방금 `judge()`에서 받은 id를 넘기므로 이 경우는 데이터 손상이다.
    삼키면 그 메시지는 영원히 판정과 연결되지 않고 원인도 남지 않는다.
    """
    user_id, room_id = await _actors(db_session)
    message = Message(
        room_id=room_id, sender_id=user_id, seq=1, body=TEXT, verification_status="ok"
    )
    db_session.add(message)
    await db_session.flush()

    with pytest.raises(ValueError, match="판정 로그"):
        await link_message(db_session, 9_999_999, message.id)


# --------------------------------------------------------------------------
# HTTP 표면
# --------------------------------------------------------------------------
async def test_patch_records_the_action_and_rejects_the_second_call(
    api_client: Any, db_session: Any
) -> None:
    """`PATCH /judgments/{id}` — 204, 두 번째는 409 (BR-7.1)."""
    from tests.conftest import bearer, signup_via_api

    signed_up = await signup_via_api(api_client, "patch-owner")
    user_id = signed_up["user"]["id"]
    room = await make_room(db_session, created_by=user_id)
    log = await _log(db_session, user_id, room.id)
    await db_session.commit()

    headers = bearer(signed_up["token"])
    first = await api_client.patch(
        f"/judgments/{log.id}", json={"user_action": "cancelled"}, headers=headers
    )
    second = await api_client.patch(
        f"/judgments/{log.id}", json={"user_action": "sent"}, headers=headers
    )

    assert first.status_code == 204, first.text
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "ALREADY_RESOLVED"


async def test_patch_on_another_users_log_is_403(api_client: Any, db_session: Any) -> None:
    """남의 판정 로그에는 라벨을 쓸 수 없다 — 403.

    막지 않으면 아무나 남의 로그에 `cancelled`를 써서 precision을 조작할 수 있고,
    그 로그의 `force_log_id`를 소진시켜 상대의 전송을 방해할 수도 있다.
    """
    from tests.conftest import bearer, signup_via_api

    owner = await signup_via_api(api_client, "patch-owner2")
    intruder = await signup_via_api(api_client, "patch-intruder")
    room = await make_room(db_session, created_by=owner["user"]["id"])
    log = await _log(db_session, owner["user"]["id"], room.id)
    await db_session.commit()

    response = await api_client.patch(
        f"/judgments/{log.id}",
        json={"user_action": "cancelled"},
        headers=bearer(intruder["token"]),
    )

    assert response.status_code == 403, response.text


async def test_patch_rejects_auto_sent_from_a_client(api_client: Any, db_session: Any) -> None:
    """클라이언트는 `auto_sent`를 주장할 수 없다 — 422.

    그것은 "적절 판정이라 묻지 않고 보냈다"는 서버가 붙이는 라벨이다 (FR-7.2).
    클라이언트가 그 값을 쓰게 두면 "물어봤는데 안 물어본 것으로 기록된" 로그가
    생겨 FR-7.3의 라벨 의미가 무너진다.
    """
    from tests.conftest import bearer, signup_via_api

    signed_up = await signup_via_api(api_client, "patch-auto")
    room = await make_room(db_session, created_by=signed_up["user"]["id"])
    log = await _log(db_session, signed_up["user"]["id"], room.id)
    await db_session.commit()

    response = await api_client.patch(
        f"/judgments/{log.id}",
        json={"user_action": "auto_sent"},
        headers=bearer(signed_up["token"]),
    )

    assert response.status_code == 422, response.text
    assert (
        await db_session.scalar(sa.select(JudgmentLog.user_action).where(JudgmentLog.id == log.id))
        is None
    )

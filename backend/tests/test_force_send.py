"""강행 전송 — BR-6.4와 **FR-8.3을 성립시키는 장치**.

부적절 판정의 "보내기"와 판정 실패의 "수락"이 **같은 재요청 경로**를 쓴다. 서버는 그
로그의 `verdict`를 보고 상태를 정한다:

| 로그의 `verdict` | 결과 상태 |
|---|---|
| `inappropriate` | `flagged_sent` — 경고를 보고도 보냈다 |
| NULL (호출 실패) | `failed` — 시도했으나 못 받고 보냈다 |

**NULL → `failed`가 이 파일에서 가장 중요한 한 줄이다.** `degraded` 플래그만 세워
재요청하면 BR-6.1의 2번 규칙에 걸려 `degraded`로 저장되고, "판정을 시도했다"는
사실이 사라진다 — `failed`와 `degraded`를 나눠 둔 이유(FR-7.1) 자체가 무너진다.

검증은 전부 U2의 `get_log_for_force()`가 한다 (BR-6.9). 여기서는 그 결과가 상태로
어떻게 이어지는지와, 우회 경로가 열리지 않는지를 본다.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from app.core.config import settings
from app.judgment.exceptions import ForceTokenForbidden, InvalidForceToken
from app.messages import service
from app.models import JudgmentLog, Message
from tests.conftest import bearer, make_room, make_user, signup_via_api
from tests.messaging_support import make_log, seed_membership, seed_messages

TEXT = "그래도 보낼게요"


class NeverJudge:
    """강행 전송 경로에서는 판정을 **부르지 않는다.** 불리면 그 자리에서 실패한다."""

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("강행 전송이 judge()를 호출했다 — 판정을 두 번 하고 있다")


@pytest.fixture(autouse=True)
def _no_real_judgement(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일의 모든 테스트에 판정 금지를 건다.

    autouse인 이유 — 강행 전송은 정의상 판정을 건너뛰는 경로다. 한 테스트라도 실제
    `judge()`에 닿으면 그것은 검증이 아니라 실제 OpenAI 호출이다.
    """
    monkeypatch.setattr(service, "judge", NeverJudge())


async def _ready(session: Any, username: str) -> tuple[Any, Any]:
    """사용자 + 방 + 참여 + 문맥 `N`개."""
    user = await make_user(session, username)
    room = await make_room(session, user.id, f"{username}의 방")
    await seed_membership(session, room.id, [user.id])
    await seed_messages(session, room.id, user.id, settings.AI_CONTEXT_N)
    return user, room


# --------------------------------------------------------------------------
# 두 갈래의 결과 상태 (BR-6.4)
# --------------------------------------------------------------------------
async def test_forcing_an_inappropriate_log_stores_flagged_sent(db_session: Any) -> None:
    """부적절 판정을 강행하면 `flagged_sent`다 — 경고를 보고도 보냈다.

    이 상태에는 "검증 안 됨" 배지가 붙지 않는다 (BR-8.6). 검증을 받았고 경고까지 봤다.
    """
    alice, room = await _ready(db_session, "force_bad")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="inappropriate", score=0.91)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT, force_log_id=log.id)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "flagged_sent"


async def test_forcing_a_null_verdict_log_stores_failed(db_session: Any) -> None:
    """**FR-8.3을 성립시키는 장치** — `verdict=NULL` 로그를 강행하면 `failed`다.

    `degraded`가 아니다. 호출을 **실제로 시도했기 때문**이며, 그 구분이
    `failed`/`degraded`를 나눠 둔 이유다 (FR-7.1). `degraded`로 저장되면 API 실패
    빈도를 셀 때 그 건이 사라진다.
    """
    alice, room = await _ready(db_session, "force_null")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict=None)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT, force_log_id=log.id)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "failed"


async def test_forcing_bypasses_the_degraded_rule_even_when_the_flag_is_set(
    db_session: Any,
) -> None:
    """`force_log_id`가 있으면 `degraded=True`여도 BR-6.1의 2번 규칙을 타지 않는다.

    **이것이 원래의 버그였다** (functional-design 리뷰어의 blocking finding). 수락 시
    클라이언트가 `enterDegraded()`를 먼저 부르고 재요청하면 그 메시지가 `degraded`로
    저장되어 시도한 사실이 사라졌다. 서버 쪽 방어가 이 분기다 — 2번 경로를
    **아예 거치지 않는다.**
    """
    alice, room = await _ready(db_session, "force_deg")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict=None)

    outcome = await service.send_message(
        db_session, alice.id, room.id, TEXT, force_log_id=log.id, degraded=True
    )

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "failed"


async def test_forcing_works_even_when_the_toggle_is_off(db_session: Any) -> None:
    """토글이 꺼져 있어도 강행 전송의 상태는 로그에서 나온다 — `disabled`가 아니다.

    경계 사례다. 판정을 받고 팝업을 본 뒤 사용자가 다른 탭에서 토글을 껐을 수 있다.
    그때 `disabled`로 저장하면 "경고를 보고 보냈다"는 사실이 사라진다.
    """
    alice = await make_user(db_session, "force_off")
    room = await make_room(db_session, alice.id, "토글 꺼짐")
    await seed_membership(db_session, room.id, [alice.id], ai_check_enabled=False)
    await seed_messages(db_session, room.id, alice.id, settings.AI_CONTEXT_N)
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="inappropriate", score=0.8)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT, force_log_id=log.id)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "flagged_sent"


# --------------------------------------------------------------------------
# 라벨과 연결 (BR-6.4, FR-7.2)
# --------------------------------------------------------------------------
async def test_forcing_labels_the_log_sent_and_links_the_message(db_session: Any) -> None:
    """`user_action='sent'`가 **두 갈래 모두**에 붙고, 로그가 그 메시지를 가리킨다.

    `sent`는 "경고 또는 미검증을 알고도 보냈다"는 뜻이며, `verdict='inappropriate'`인
    로그에서는 FP(오탐)의 근거가 된다 (BR-7.3).
    """
    alice, room = await _ready(db_session, "force_label")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="inappropriate", score=0.88)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT, force_log_id=log.id)

    assert isinstance(outcome, service.Sent)
    stored = await db_session.get(JudgmentLog, log.id)
    await db_session.refresh(stored)
    assert stored.user_action == "sent"
    assert stored.message_id == outcome.message.id


# --------------------------------------------------------------------------
# 우회 방어 (BR-6.9 — 검증은 U2가 하고 여기서는 결과만 본다)
# --------------------------------------------------------------------------
async def test_a_different_text_is_rejected(db_session: Any) -> None:
    """텍스트가 다르면 거부한다 — **판정 우회 경로를 막는 검사다.**

    없으면 소유자·방·미소진을 만족하는 토큰에 *다른 문장*을 실어 판정 없이
    `flagged_sent`로 통과시킬 수 있다. UI로는 도달할 수 없지만 API 직접 호출로는
    가능하다.
    """
    alice, room = await _ready(db_session, "force_text")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="inappropriate", score=0.9)
    before = await db_session.scalar(
        sa.select(sa.func.count(Message.id)).where(Message.room_id == room.id)
    )

    with pytest.raises(InvalidForceToken):
        await service.send_message(
            db_session, alice.id, room.id, "전혀 다른 문장", force_log_id=log.id
        )

    after = await db_session.scalar(
        sa.select(sa.func.count(Message.id)).where(Message.room_id == room.id)
    )
    assert after == before


async def test_a_consumed_log_is_rejected(db_session: Any) -> None:
    """이미 소진된 토큰은 거부한다 — 1회성 (BR-7.1).

    같은 `force_log_id`로 두 번 보낼 수 없다. 더블클릭이 메시지를 두 개 만들지 않는다.
    """
    alice, room = await _ready(db_session, "force_used")
    log = await make_log(
        db_session, alice.id, room.id, TEXT, verdict="inappropriate", score=0.9, user_action="sent"
    )

    with pytest.raises(InvalidForceToken):
        await service.send_message(db_session, alice.id, room.id, TEXT, force_log_id=log.id)


async def test_another_users_log_is_403(db_session: Any) -> None:
    """남의 판정 로그로는 강행할 수 없다 — **여섯 검사 중 유일한 403이다** (BR-6.9).

    400으로 덮으면 서버가 남의 자원에 대한 접근을 입력 오류로 보고하는 셈이 되어,
    로그에서 공격 시도를 구분할 수 없게 된다.
    """
    alice, room = await _ready(db_session, "force_owner")
    intruder = await make_user(db_session, "force_intruder")
    await seed_membership(db_session, room.id, [intruder.id])
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="inappropriate", score=0.9)

    with pytest.raises(ForceTokenForbidden):
        await service.send_message(db_session, intruder.id, room.id, TEXT, force_log_id=log.id)


async def test_an_appropriate_log_cannot_be_forced(db_session: Any) -> None:
    """적절 판정 로그는 강행 대상이 아니다 (BR-6.9).

    막지 않으면 그 경로로 판정을 건너뛸 수 있다 — 적절 판정은 이미 자동 전송되었다.
    """
    alice, room = await _ready(db_session, "force_good")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="appropriate", score=0.1)

    with pytest.raises(InvalidForceToken):
        await service.send_message(db_session, alice.id, room.id, TEXT, force_log_id=log.id)


async def test_a_log_from_another_room_is_rejected(db_session: Any) -> None:
    """다른 방의 판정 로그는 거부한다 (BR-6.9).

    방마다 문맥이 다르므로 A방에서 부적절이던 문장이 B방에서도 그렇다는 보장이 없다.
    """
    alice, room = await _ready(db_session, "force_room")
    other = await make_room(db_session, alice.id, "다른 방")
    log = await make_log(db_session, alice.id, other.id, TEXT, verdict="inappropriate", score=0.9)

    with pytest.raises(InvalidForceToken):
        await service.send_message(db_session, alice.id, room.id, TEXT, force_log_id=log.id)


# --------------------------------------------------------------------------
# HTTP 표면 — 소진된 토큰이 두 경로 어디서든 같은 의미를 갖는가
# --------------------------------------------------------------------------
async def test_the_token_is_consumed_across_both_surfaces(api_client: Any, db_session: Any) -> None:
    """강행 전송이 토큰을 소진하면 `PATCH /judgments/{id}`도 **409 `ALREADY_RESOLVED`** 다.

    같은 1회성이 두 표면에 걸쳐 성립해야 한다 (BR-7.1). 한쪽만 막으면 사용자가
    "보내기" 뒤에 "취소"를 눌러 라벨을 덮어쓸 수 있고, 그러면 FP가 TP로 둔갑해
    precision이 왜곡된다 (FR-7.3).
    """
    alice = await signup_via_api(api_client, "force_api")
    user_id = alice["user"]["id"]
    room = await make_room(db_session, user_id, "API 강행")
    await seed_membership(db_session, room.id, [user_id])
    await seed_messages(db_session, room.id, user_id, settings.AI_CONTEXT_N)
    log = await make_log(db_session, user_id, room.id, TEXT, verdict="inappropriate", score=0.9)
    await db_session.commit()

    sent = await api_client.post(
        f"/rooms/{room.id}/messages",
        json={"text": TEXT, "force_log_id": log.id},
        headers=bearer(alice["token"]),
    )
    patched = await api_client.patch(
        f"/judgments/{log.id}",
        json={"user_action": "cancelled"},
        headers=bearer(alice["token"]),
    )
    again = await api_client.post(
        f"/rooms/{room.id}/messages",
        json={"text": TEXT, "force_log_id": log.id},
        headers=bearer(alice["token"]),
    )

    assert sent.status_code == 201, sent.text
    assert sent.json()["verification_status"] == "flagged_sent"
    assert patched.status_code == 409, patched.text
    assert patched.json()["error"]["code"] == "ALREADY_RESOLVED"
    # 두 번째 강행은 400이다 — 소진 검사가 `get_log_for_force()`에서 먼저 걸린다.
    assert again.status_code == 400, again.text
    assert again.json()["error"]["code"] == "INVALID_FORCE_TOKEN"

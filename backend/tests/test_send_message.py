"""전송 경로 — W1의 9단계와 BR-6.1의 상태 결정 순서.

**실제 OpenAI 호출은 하나도 없다.** 판정은 전부 `FakeJudge`로 갈아끼운다 — 판정의
내부는 U2가 이미 검증했고, 여기서 볼 것은 **세 갈래를 어떻게 분기하는가**뿐이다.

대응: FR-4.1~FR-4.3, FR-6.4~FR-6.6, FR-7.1, FR-8.2·8.3·8.5, NFR-3,
BR-3.3·BR-4.1~BR-4.3·BR-6.1~BR-6.3·BR-8.1·BR-8.2·BR-8.5.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa

from app.core.config import settings
from app.judgment.exceptions import AlreadyResolved
from app.messages import service
from app.messages.constants import MESSAGE_MAX_LENGTH
from app.messages.exceptions import MessageForbidden, MessageTooLong
from app.models import JudgmentLog, Message
from tests.conftest import bearer, make_room, make_user, signup_via_api
from tests.messaging_support import (
    FakeJudge,
    appropriate,
    count_logs,
    failed,
    inappropriate,
    make_log,
    seed_membership,
    seed_messages,
)

TEXT = "이 방에 맞는 말인지 봐 주세요"


class NeverJudge:
    """불리면 그 자리에서 실패하는 판정 대역.

    "호출하지 않는다"는 규칙(BR-6.1의 1~3번)을 검증할 때 쓴다. 호출 횟수를 나중에
    세는 것보다 낫다 — 실패 지점이 규칙을 어긴 그 줄이 된다.
    """

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("판정을 호출하면 안 되는 경로에서 judge()가 불렸다")


async def _room_with_context(
    session: Any,
    username: str,
    *,
    ai_check_enabled: bool = True,
    message_count: int | None = None,
) -> tuple[Any, Any]:
    """사용자 + 방 + 참여 + 문맥 메시지를 심는다. `(user, room)`.

    `message_count`의 기본값이 `AI_CONTEXT_N`인 이유 — 콜드스타트(BR-6.2)를 넘겨야
    판정 분기에 도달한다. 그 준비가 이 파일 대부분의 첫 줄이다.
    """
    count = settings.AI_CONTEXT_N if message_count is None else message_count
    user = await make_user(session, username)
    room = await make_room(session, user.id, f"{username}의 방")
    await seed_membership(session, room.id, [user.id], ai_check_enabled=ai_check_enabled)
    if count > 0:
        await seed_messages(session, room.id, user.id, count)
    return user, room


async def _stored(session: Any, room_id: int) -> list[Message]:
    rows = await session.execute(
        sa.select(Message).where(Message.room_id == room_id).order_by(Message.seq)
    )
    return list(rows.scalars().all())


# --------------------------------------------------------------------------
# 1. 참여 자격과 본문 길이 (BR-3.3, 400 MESSAGE_TOO_LONG)
# --------------------------------------------------------------------------
async def test_a_non_member_cannot_send(db_session: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """BR-3.3 — 참여자가 아니면 403이고 **아무것도 저장되지 않는다.**"""
    monkeypatch.setattr(service, "judge", NeverJudge())
    owner, room = await _room_with_context(db_session, "send_owner")
    stranger = await make_user(db_session, "send_stranger")

    with pytest.raises(MessageForbidden):
        await service.send_message(db_session, stranger.id, room.id, TEXT)

    assert len(await _stored(db_session, room.id)) == settings.AI_CONTEXT_N
    assert owner.id != stranger.id


async def test_a_nonexistent_room_is_also_403(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """없는 방도 404가 아니라 403이다 — 방 id의 존재 여부를 새게 하지 않는다."""
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice = await make_user(db_session, "send_ghost")

    with pytest.raises(MessageForbidden):
        await service.send_message(db_session, alice.id, 99_999_999, TEXT)


async def test_a_body_over_the_limit_is_rejected(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한 초과는 400이고 **판정도 저장도 하지 않는다.**

    가장 싼 검사가 가장 앞에 있는지를 본다 — 판정 뒤에 있으면 상한을 넘은 본문이
    외부 API로 나가고 `judgment_logs.candidate_text`에도 남는다.
    """
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(db_session, "send_long")

    with pytest.raises(MessageTooLong):
        await service.send_message(db_session, alice.id, room.id, "가" * (MESSAGE_MAX_LENGTH + 1))

    assert len(await _stored(db_session, room.id)) == settings.AI_CONTEXT_N


async def test_a_body_exactly_at_the_limit_is_accepted(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """경계값 — 정확히 `MESSAGE_MAX_LENGTH`자는 통과한다.

    `>`와 `>=`를 잘못 쓰면 사용자가 상한을 정확히 채웠을 때만 실패한다. 그 버그는
    거의 드러나지 않다가 하필 데모에서 나온다.
    """
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(db_session, "send_edge", ai_check_enabled=False)

    outcome = await service.send_message(db_session, alice.id, room.id, "가" * MESSAGE_MAX_LENGTH)

    assert isinstance(outcome, service.Sent)
    assert len(outcome.message.body) == MESSAGE_MAX_LENGTH


# --------------------------------------------------------------------------
# 3. 호출하지 않는 세 값 (BR-6.1의 1~3번, FR-7.1)
# --------------------------------------------------------------------------
async def test_toggle_off_stores_disabled_without_a_log(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """토글이 꺼져 있으면 `disabled`이고 **판정 로그도 남지 않는다** (FR-6.1, FR-7.1)."""
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(db_session, "send_off", ai_check_enabled=False)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "disabled"
    assert await count_logs(db_session, alice.id) == 0


async def test_cold_start_stores_skipped_without_a_log(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-6.2 — 방 메시지가 `N`개 미만이면 `skipped_no_context`, 로그 없음 (FR-6.4).

    문맥이 없으면 판단이 불가능하다. 억지로 판정하면 노이즈만 쌓인다.
    """
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(
        db_session, "send_cold", message_count=settings.AI_CONTEXT_N - 1
    )

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "skipped_no_context"
    assert await count_logs(db_session, alice.id) == 0


async def test_exactly_n_messages_is_enough_to_judge(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """경계값 — 정확히 `N`개면 콜드스타트가 아니다 (`<`이지 `<=`가 아니다).

    반대로 짜면 방이 영원히 한 개 모자란 상태로 남아 판정이 한 번도 안 돈다.
    """
    alice, room = await _room_with_context(
        db_session, "send_exact", message_count=settings.AI_CONTEXT_N
    )
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="appropriate", score=0.1)
    fake = FakeJudge(appropriate(log.id))
    monkeypatch.setattr(service, "judge", fake)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "ok"
    assert len(fake.calls) == 1


async def test_degraded_stores_degraded_without_a_log(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """degraded 구간에서는 호출하지 않고 `degraded`로 저장한다 (BR-8.5, FR-7.1)."""
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(db_session, "send_degraded")

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT, degraded=True)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "degraded"
    assert await count_logs(db_session, alice.id) == 0


# --------------------------------------------------------------------------
# 상태 결정 **순서** (BR-6.1)
# --------------------------------------------------------------------------
async def test_toggle_off_wins_over_cold_start(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1번이 3번보다 앞이다 — 토글이 꺼져 있으면 문맥이 부족해도 `disabled`다.

    순서가 뒤집히면 토글을 끈 사용자의 메시지가 `skipped_no_context`로 기록되고,
    "사용자가 스스로 껐다"와 "문맥이 없었다"가 집계에서 섞인다 (FR-7.1).
    """
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(
        db_session, "send_order1", ai_check_enabled=False, message_count=0
    )

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "disabled"


async def test_toggle_off_wins_over_degraded(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1번이 2번보다 앞이다 — 토글이 꺼져 있으면 degraded여도 `disabled`다."""
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(db_session, "send_order2", ai_check_enabled=False)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT, degraded=True)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "disabled"


async def test_degraded_wins_over_cold_start_and_skips_the_context_query(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2번이 3번보다 앞이다 — **그리고 그 순서가 조회를 실제로 아낀다.**

    `business-rules.md`가 "degraded면 문맥 개수 조회(DB 접근 1회)를 아낀다"를 순서의
    근거로 들었다. 산문으로만 두면 순서를 바꿔도 아무도 모른다: 문맥이 없는 방에서
    degraded로 보내면 `skipped_no_context`가 아니라 `degraded`여야 한다.
    """
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice, room = await _room_with_context(db_session, "send_order3", message_count=0)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT, degraded=True)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "degraded"


# --------------------------------------------------------------------------
# 4~5. 판정 분기 (BR-6.3, BR-8.2, BR-8.5)
# --------------------------------------------------------------------------
async def test_appropriate_stores_ok_and_labels_auto_sent(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """적절 판정 → `ok` + `user_action='auto_sent'` (FR-7.2).

    `auto_sent`는 "물어보지 않고 보냈다"는 서버의 라벨이다. 없으면 그 로그가
    "아직 답하지 않은 건"으로 집계되어 FR-7.4의 미응답 수가 부풀려진다.
    """
    alice, room = await _room_with_context(db_session, "send_ok")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="appropriate", score=0.12)
    monkeypatch.setattr(service, "judge", FakeJudge(appropriate(log.id, 0.12)))

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "ok"
    stored = await db_session.get(JudgmentLog, log.id)
    await db_session.refresh(stored)
    assert stored.user_action == "auto_sent"
    # 7번 — 로그가 그 메시지를 가리킨다.
    assert stored.message_id == outcome.message.id


async def test_inappropriate_returns_409_and_stores_nothing(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-6.3 — 부적절 판정은 **저장하지 않고** 409 `inappropriate`를 준다.

    저장해 버리면 사용자가 취소해도 메시지가 남는다 — FR-7.2가 "취소된 메시지는
    `messages`에 없다"를 이 설계의 성질로 두었다.
    """
    alice, room = await _room_with_context(db_session, "send_bad")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="inappropriate", score=0.93)
    monkeypatch.setattr(service, "judge", FakeJudge(inappropriate(log.id, 0.93)))
    before = len(await _stored(db_session, room.id))

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Blocked)
    assert outcome.reason == "inappropriate"
    assert outcome.log_id == log.id
    assert outcome.score == pytest.approx(0.93)
    assert len(await _stored(db_session, room.id)) == before


async def test_judge_failure_outside_degraded_returns_409_judge_failed(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-8.2 — 세션 첫 실패는 **저장하지 않고** 409 `judge_failed`를 준다.

    **점수가 없다** — 실패에 점수를 만들어 주면 클라이언트가 그것을 판정으로 착각한다.

    조용히 보내지 않는 것이 BR-8.1의 전부다. 사용자는 검증받았다고 믿고 있다.
    """
    alice, room = await _room_with_context(db_session, "send_fail")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict=None)
    monkeypatch.setattr(service, "judge", FakeJudge(failed(log.id)))
    before = len(await _stored(db_session, room.id))

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Blocked)
    assert outcome.reason == "judge_failed"
    assert outcome.log_id == log.id
    assert outcome.score is None
    assert len(await _stored(db_session, room.id)) == before


async def test_probe_failure_saves_as_failed_without_asking(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-8.5 — 프로브 실패는 **팝업 없이** 저장하고 201을 준다. 상태는 `failed`.

    사용자는 이미 degraded를 수락해 두었으므로 다시 묻지 않는다. 여기서 409를 주면
    degraded 구간 내내 5번째마다 팝업이 뜬다.

    `degraded`가 아니라 `failed`인 것 — **호출을 실제로 시도했기 때문이다** (FR-7.1).
    """
    alice, room = await _room_with_context(db_session, "send_probe")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict=None)
    fake = FakeJudge(failed(log.id))
    monkeypatch.setattr(service, "judge", fake)

    outcome = await service.send_message(
        db_session, alice.id, room.id, TEXT, degraded=True, probe=True
    )

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "failed"
    # 프로브는 degraded 중에도 **실제로 호출한다** — 그것이 회복 감지의 전부다.
    assert len(fake.calls) == 1


async def test_probe_success_stores_the_judged_status(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """프로브가 성공하면 상태는 **판정 결과대로**다 (BR-8.5).

    `degraded`로 덮어쓰면 회복된 판정의 결과가 버려진다.
    """
    alice, room = await _room_with_context(db_session, "send_probe_ok")
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="appropriate", score=0.2)
    monkeypatch.setattr(service, "judge", FakeJudge(appropriate(log.id, 0.2)))

    outcome = await service.send_message(
        db_session, alice.id, room.id, TEXT, degraded=True, probe=True
    )

    assert isinstance(outcome, service.Sent)
    assert outcome.message.verification_status == "ok"


# --------------------------------------------------------------------------
# 4. 문맥 (BR-6.1 — seq 오름차순)
# --------------------------------------------------------------------------
async def test_context_is_the_latest_n_in_ascending_seq(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """문맥은 **최근 N개**를 **오래된 것부터** 넘긴다 (judgment-core BR-6.1).

    뒤집으면 `context_from_seq`와 `context_to_seq`가 뒤바뀌어 로그의 범위가 거꾸로
    남고, 프롬프트의 대화도 역순으로 읽힌다. `ContextMessage`는 **세 필드**다.
    """
    alice, room = await _room_with_context(
        db_session, "send_ctx", message_count=settings.AI_CONTEXT_N + 5
    )
    log = await make_log(db_session, alice.id, room.id, TEXT, verdict="appropriate", score=0.1)
    fake = FakeJudge(appropriate(log.id))
    monkeypatch.setattr(service, "judge", fake)

    await service.send_message(db_session, alice.id, room.id, TEXT)

    context = fake.calls[0]["context"]
    seqs = [item.seq for item in context]
    assert len(seqs) == settings.AI_CONTEXT_N
    assert seqs == sorted(seqs), "문맥이 seq 오름차순이 아니다"
    # 최근 N개다 — 가장 오래된 5개는 빠진다.
    assert seqs[-1] == settings.AI_CONTEXT_N + 5
    assert all(item.sender_id == alice.id and item.text for item in context)
    assert fake.calls[0]["candidate_text"] == TEXT


# --------------------------------------------------------------------------
# 8. 브로드캐스트가 커밋 뒤인가 (BR-4.1, NFR-3)
# --------------------------------------------------------------------------
async def test_broadcast_happens_after_the_commit(
    live_sessionmaker: Any, migrated_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-3 — 브로드캐스트 시점에 그 메시지가 **다른 커넥션에서 보인다.**

    "커밋 뒤"를 이보다 약하게 검증할 방법이 없다. 같은 세션에서 조회하면 커밋 전에도
    보이므로 아무것도 증명하지 못한다 — 별도 커넥션에서 보인다는 것이 곧
    "커밋되었다"는 뜻이다.

    반대로 트랜잭션 안에서 밀어내면 롤백 시 화면에만 존재하는 유령 메시지가 남는다.
    그것이 FR-4.1이 막으려는 상황이다.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    async with live_sessionmaker() as setup:
        alice = await make_user(setup, "bc_alice")
        room = await make_room(setup, alice.id, "브로드캐스트")
        await seed_membership(setup, room.id, [alice.id], ai_check_enabled=False)
        await setup.commit()
        alice_id, room_id = alice.id, room.id

    seen: list[int] = []

    async def spy_push(user_ids: list[int], payload: dict[str, Any]) -> None:
        # **완전히 독립된 커넥션**으로 확인한다. 세션도 엔진도 공유하지 않는다.
        probe_engine = create_async_engine(migrated_database)
        try:
            async with probe_engine.connect() as connection:
                rows = await connection.execute(
                    sa.text("SELECT id FROM messages WHERE room_id = :room_id"),
                    {"room_id": room_id},
                )
                seen.extend(row[0] for row in rows)
        finally:
            await probe_engine.dispose()
        assert user_ids == [alice_id]
        assert payload["type"] == "message"

    monkeypatch.setattr(service, "push_to_users", spy_push)

    async with live_sessionmaker() as session:
        outcome = await service.send_message(session, alice_id, room_id, "커밋 뒤에 나간다")

    assert isinstance(outcome, service.Sent)
    assert seen == [outcome.message.id], "브로드캐스트 시점에 메시지가 커밋되어 있지 않았다"


async def test_broadcast_failure_does_not_fail_the_send(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """푸시가 터져도 전송은 성공이다 — 메시지는 이미 커밋되었다.

    여기서 예외를 올리면 사용자만 500을 보고, 되돌릴 것도 없다. 연결이 없는
    사용자는 다음 입장 시 히스토리로 받으므로 유실이 아니다.
    """

    async def exploding_push(user_ids: list[int], payload: dict[str, Any]) -> None:
        raise RuntimeError("소켓이 전부 죽었다")

    monkeypatch.setattr(service, "judge", NeverJudge())
    monkeypatch.setattr(service, "push_to_users", exploding_push)
    alice, room = await _room_with_context(db_session, "bc_fail", ai_check_enabled=False)

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Sent)


async def test_broadcast_includes_the_sender(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-5.8 — 발신자도 대상에 포함된다. 프레임 모양은 HTTP 응답과 같다.

    다른 탭·기기의 세션도 갱신되어야 하고, 중복은 클라이언트가 메시지 ID로 제거한다.
    """
    captured: list[tuple[list[int], dict[str, Any]]] = []

    async def spy_push(user_ids: list[int], payload: dict[str, Any]) -> None:
        captured.append((user_ids, payload))

    monkeypatch.setattr(service, "judge", NeverJudge())
    monkeypatch.setattr(service, "push_to_users", spy_push)
    alice, room = await _room_with_context(db_session, "bc_self", ai_check_enabled=False)
    bob = await make_user(db_session, "bc_bob")
    await seed_membership(db_session, room.id, [bob.id])

    outcome = await service.send_message(db_session, alice.id, room.id, TEXT)

    assert isinstance(outcome, service.Sent)
    user_ids, payload = captured[0]
    assert set(user_ids) == {alice.id, bob.id}
    assert payload["room_id"] == room.id
    frame = payload["message"]
    assert frame["id"] == outcome.message.id
    assert frame["seq"] == outcome.message.seq
    assert frame["verification_status"] == "disabled"
    assert frame["misdirect_reported_at"] is None
    # 표시명은 보는 사람마다 다르다 — 하나의 프레임에 담을 수 없다 (FR-2.4).
    assert "sender_display_name" not in frame


# --------------------------------------------------------------------------
# HTTP 표면
# --------------------------------------------------------------------------
async def test_api_returns_201_with_the_stored_message(
    api_client: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """정상 전송은 201이고 본문이 저장된 메시지 그대로다."""
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice = await signup_via_api(api_client, "api_send_alice")
    room = await make_room(db_session, alice["user"]["id"], "API 전송")
    await seed_membership(db_session, room.id, [alice["user"]["id"]], ai_check_enabled=False)
    await db_session.commit()

    response = await api_client.post(
        f"/rooms/{room.id}/messages",
        json={"text": "안녕하세요"},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["body"] == "안녕하세요"
    assert body["seq"] == 1
    assert body["verification_status"] == "disabled"
    assert body["misdirect_reported_at"] is None


async def test_api_returns_409_with_reason_for_both_blocked_kinds(
    api_client: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """두 갈래 모두 **409**이고 `reason`으로 갈린다 — 503을 쓰지 않는다.

    상태 코드를 나누면 클라이언트가 네트워크 오류와 헷갈린다. 실패한 것은 판정이지
    요청이 아니다.
    """
    alice = await signup_via_api(api_client, "api_block_alice")
    user_id = alice["user"]["id"]
    room = await make_room(db_session, user_id, "409 두 종")
    await seed_membership(db_session, room.id, [user_id])
    await seed_messages(db_session, room.id, user_id, settings.AI_CONTEXT_N)
    bad = await make_log(db_session, user_id, room.id, "부적절", verdict="inappropriate", score=0.9)
    broken = await make_log(db_session, user_id, room.id, "실패", verdict=None)
    await db_session.commit()

    monkeypatch.setattr(service, "judge", FakeJudge(inappropriate(bad.id, 0.9)))
    first = await api_client.post(
        f"/rooms/{room.id}/messages", json={"text": "부적절"}, headers=bearer(alice["token"])
    )

    monkeypatch.setattr(service, "judge", FakeJudge(failed(broken.id)))
    second = await api_client.post(
        f"/rooms/{room.id}/messages", json={"text": "실패"}, headers=bearer(alice["token"])
    )

    assert first.status_code == 409, first.text
    assert first.json() == {"log_id": bad.id, "reason": "inappropriate", "score": 0.9}
    assert second.status_code == 409, second.text
    assert second.json() == {"log_id": broken.id, "reason": "judge_failed", "score": None}


async def test_api_rejects_a_too_long_body_with_400(
    api_client: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """상한 초과는 **422가 아니라 400 `MESSAGE_TOO_LONG`** 이다.

    pydantic의 `max_length`로 막으면 이 코드가 사라지고 프론트엔드가 분기할 수 없다.
    """
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice = await signup_via_api(api_client, "api_long_alice")
    room = await make_room(db_session, alice["user"]["id"], "길이 상한")
    await seed_membership(db_session, room.id, [alice["user"]["id"]], ai_check_enabled=False)
    await db_session.commit()

    response = await api_client.post(
        f"/rooms/{room.id}/messages",
        json={"text": "가" * (MESSAGE_MAX_LENGTH + 1)},
        headers=bearer(alice["token"]),
    )

    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "MESSAGE_TOO_LONG"


async def test_api_rejects_a_non_member_with_403(
    api_client: Any, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """비참여자는 403이다 (BR-3.3)."""
    monkeypatch.setattr(service, "judge", NeverJudge())
    alice = await signup_via_api(api_client, "api_403_alice")
    stranger = await signup_via_api(api_client, "api_403_stranger")
    room = await make_room(db_session, alice["user"]["id"], "남의 방")
    await seed_membership(db_session, room.id, [alice["user"]["id"]], ai_check_enabled=False)
    await db_session.commit()

    response = await api_client.post(
        f"/rooms/{room.id}/messages",
        json={"text": "들어가도 되나요"},
        headers=bearer(stranger["token"]),
    )

    assert response.status_code == 403, response.text


# --------------------------------------------------------------------------
# 판정 로그의 1회성이 저장과 원자적인가 (BR-7.1)
# --------------------------------------------------------------------------
async def test_a_consumed_log_rolls_the_message_back(
    live_sessionmaker: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이미 라벨이 쓰인 로그를 자동 전송에 다시 쓰면 `AlreadyResolved`이고
    **그 메시지도 저장되지 않는다.**

    `set_user_action()`이 저장 트랜잭션 **안**에 있어야 성립한다. 밖에 있으면 라벨만
    실패하고 메시지는 남거나, 반대로 라벨만 소진되고 메시지는 없는 행이 생긴다.

    **진짜 롤백이 필요해 `live_sessionmaker`를 쓴다.** savepoint 픽스처에서는 롤백
    범위가 savepoint 경계라 "저장 트랜잭션만 되돌아갔는가"를 물을 수 없다.
    """
    async with live_sessionmaker() as setup:
        alice = await make_user(setup, "send_atomic")
        room = await make_room(setup, alice.id, "원자성")
        await seed_membership(setup, room.id, [alice.id])
        await seed_messages(setup, room.id, alice.id, settings.AI_CONTEXT_N)
        log = await make_log(
            setup, alice.id, room.id, TEXT, verdict="appropriate", score=0.1, user_action="sent"
        )
        await setup.commit()
        alice_id, room_id, log_id = alice.id, room.id, log.id

    monkeypatch.setattr(service, "judge", FakeJudge(appropriate(log_id)))

    async with live_sessionmaker() as session:
        with pytest.raises(AlreadyResolved):
            await service.send_message(session, alice_id, room_id, TEXT)
        await session.rollback()

    async with live_sessionmaker() as check:
        stored = await check.scalar(
            sa.select(sa.func.count(Message.id)).where(Message.room_id == room_id)
        )
    assert stored == settings.AI_CONTEXT_N

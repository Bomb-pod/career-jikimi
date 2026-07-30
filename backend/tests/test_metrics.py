"""지표 산출과 리포트 — FR-7.3~FR-7.5, BR-7.2~BR-7.6, ASM-1.

**집계 축이 `judgment_logs`인지 확인하는 것이 이 파일의 주제다** (BR-7.2).
요구사항 단계에서 한 번 잡힌 결함이라 회귀를 막아야 한다 —
`messages.verification_status`로 거르면 **취소된 건은 `messages` 행이 없어서**
영원히 안 잡히고, 그러면 TP가 항상 0이 되어 precision이 계산 불가가 된다.

리포트 렌더링도 여기서 본다. 문구 두 개가 규칙이기 때문이다:
`recall`의 산출 불가 문자열(BR-7.5)과 precision의 `※ 근사`(ASM-1).

**실제 MariaDB에서 돈다.** OpenAI를 부르지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.judgment.constants import (
    PRECISION_APPROXIMATE_MARK,
    PRECISION_UNAVAILABLE,
    RECALL_UNAVAILABLE,
)
from app.judgment.metrics import compute_metrics
from app.judgment.report import render_report
from app.judgment.types import MetricsReport
from app.models import JudgmentLog, Message
from tests.conftest import make_room, make_user


async def _actors(session: Any) -> tuple[int, int]:
    user = await make_user(session, "metrics-user")
    room = await make_room(session, created_by=user.id)
    return user.id, room.id


def _log(
    user_id: int,
    room_id: int,
    *,
    verdict: str | None,
    user_action: str | None = None,
    latency_ms: int = 1000,
    prompt_tokens: int | None = 300,
    completion_tokens: int | None = 8,
    created_at: datetime | None = None,
) -> JudgmentLog:
    return JudgmentLog(
        user_id=user_id,
        room_id=room_id,
        context_from_seq=1,
        context_to_seq=10,
        candidate_text="후보 문장",
        score=Decimal("0.850") if verdict is not None else None,
        verdict=verdict,
        threshold=Decimal("0.700"),
        latency_ms=latency_ms,
        prompt_tokens=prompt_tokens if verdict is not None else None,
        completion_tokens=completion_tokens if verdict is not None else None,
        user_action=user_action,
        **({} if created_at is None else {"created_at": created_at}),
    )


def _message(
    room_id: int,
    sender_id: int,
    seq: int,
    *,
    status: str,
    reported: bool = False,
) -> Message:
    return Message(
        room_id=room_id,
        sender_id=sender_id,
        seq=seq,
        body="본문",
        verification_status=status,
        misdirect_reported_at=datetime(2026, 7, 29, 12, 0) if reported else None,
    )


# --------------------------------------------------------------------------
# precision (BR-7.3)
# --------------------------------------------------------------------------
async def test_precision_counts_cancelled_over_cancelled_plus_sent(db_session: Any) -> None:
    """7 cancelled / 3 sent → 0.7 — FR-7.4의 수용 기준 그대로."""
    user_id, room_id = await _actors(db_session)
    db_session.add_all(
        [_log(user_id, room_id, verdict="inappropriate", user_action="cancelled") for _ in range(7)]
        + [_log(user_id, room_id, verdict="inappropriate", user_action="sent") for _ in range(3)]
    )
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert report.true_positives == 7
    assert report.false_positives == 3
    assert report.precision == pytest.approx(0.7)


async def test_precision_is_none_not_zero_when_there_is_no_sample(db_session: Any) -> None:
    """**분모가 0이면 `None`이다. 0.0이 아니다** (BR-7.3).

    0.0으로 두면 "표본이 없다"가 "성능이 0이다"로 읽힌다. 그 오해는 precision에서
    특히 비싸다 — 이 프로젝트의 1순위 지표이기 때문이다.
    """
    user_id, room_id = await _actors(db_session)
    # 판정은 있으나 부적절 판정이 없다.
    db_session.add(_log(user_id, room_id, verdict="appropriate", user_action="auto_sent"))
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert report.precision is None
    assert report.judged_count == 1


async def test_unanswered_is_excluded_from_precision_but_counted(db_session: Any) -> None:
    """미응답은 precision에서 빼되 **별도 수치로 보고한다** (BR-7.4).

    "경고를 받고 아무것도 하지 않았다"는 오류가 아니라 관찰값이다. TP도 FP도
    아니므로 분모에 넣으면 precision이 실제보다 낮게 나온다. 이 수치가 크면
    팝업이 무시당하고 있다는 신호다.
    """
    user_id, room_id = await _actors(db_session)
    db_session.add_all(
        [
            _log(user_id, room_id, verdict="inappropriate", user_action="cancelled"),
            _log(user_id, room_id, verdict="inappropriate", user_action="sent"),
            _log(user_id, room_id, verdict="inappropriate", user_action=None),
            _log(user_id, room_id, verdict="inappropriate", user_action=None),
        ]
    )
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert report.unanswered_count == 2
    # 분모는 2다 — 미응답 2건이 들어갔다면 0.25가 나온다.
    assert report.precision == pytest.approx(0.5)


# --------------------------------------------------------------------------
# 집계 축과 분모 (BR-7.2)
# --------------------------------------------------------------------------
async def test_failed_rows_leave_precision_alone_but_drive_the_failure_rate(
    db_session: Any,
) -> None:
    """`verdict IS NULL`인 행은 precision에서 빠지고 **API 실패율에는 들어간다.**

    **API 실패율만 분모가 다르다** — 다른 지표는 거른 뒤 계산하지만 실패율은
    실패를 세는 것이므로 거르기 전의 전체 행을 쓴다. 걸러진 분모를 쓰면 실패율이
    항상 0이 된다.
    """
    user_id, room_id = await _actors(db_session)
    db_session.add_all(
        [_log(user_id, room_id, verdict="inappropriate", user_action="cancelled") for _ in range(3)]
        + [_log(user_id, room_id, verdict=None) for _ in range(2)]
    )
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert report.attempted_count == 5  # 거르기 전
    assert report.judged_count == 3  # 거른 뒤
    assert report.failed_count == 2
    assert report.api_failure_rate == pytest.approx(2 / 5)
    assert report.precision == pytest.approx(1.0)  # 실패 건이 precision을 오염시키지 않는다
    assert report.flag_rate == pytest.approx(1.0)  # 판정된 3건 모두 부적절


async def test_messages_without_a_log_row_never_enter_the_aggregation(db_session: Any) -> None:
    """`disabled` 메시지 100건은 집계에 없다 — FR-7.4의 수용 기준.

    호출하지 않은 건은 판정 로그에 행이 없으므로(FR-7.2) 어떤 필터도 필요 없다.
    **집계 축이 `judgment_logs`라서 자동으로 그렇게 된다** — 축이
    `messages`였다면 이 100건을 매번 걸러내야 하고, 대신 취소된 건이 사라진다.
    """
    user_id, room_id = await _actors(db_session)
    db_session.add_all(
        [
            _message(room_id, user_id, seq, status="disabled")
            for seq in range(1, 101)  # 100건
        ]
    )
    db_session.add(_log(user_id, room_id, verdict="inappropriate", user_action="cancelled"))
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert report.attempted_count == 1
    assert report.judged_count == 1
    assert report.precision == pytest.approx(1.0)
    # 메시지는 신고 지표에만 쓰인다 (BR-7.6).
    assert report.messages_total == 100


async def test_cancelled_judgments_are_counted_even_though_no_message_exists(
    db_session: Any,
) -> None:
    """**취소된 건에는 `messages` 행이 없다.** 그래도 TP로 잡힌다 (BR-7.2).

    이것이 집계 축을 옮긴 이유 그 자체다. `messages.verification_status`로
    걸렀다면 이 건은 영원히 안 잡히고 TP가 0이 되어 precision이 계산 불가가 된다.
    """
    user_id, room_id = await _actors(db_session)
    log = _log(user_id, room_id, verdict="inappropriate", user_action="cancelled")
    db_session.add(log)
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert log.message_id is None  # 메시지가 없다
    assert report.true_positives == 1
    assert report.messages_total == 0


# --------------------------------------------------------------------------
# 지연·토큰·신고 (FR-7.5, BR-7.6)
# --------------------------------------------------------------------------
async def test_latency_and_tokens_come_from_judged_rows(db_session: Any) -> None:
    """지연 분포와 토큰 합계는 판정된 행에서 나온다.

    실패 건의 `latency_ms`(타임아웃 값)를 섞으면 분포가 그쪽으로 끌려간다. 그
    사실은 API 실패율이 따로 보고하므로 여기서 겹쳐 세지 않는다.
    """
    user_id, room_id = await _actors(db_session)
    db_session.add_all(
        [
            _log(user_id, room_id, verdict="appropriate", user_action="auto_sent", latency_ms=1000),
            _log(user_id, room_id, verdict="appropriate", user_action="auto_sent", latency_ms=2000),
            _log(user_id, room_id, verdict="appropriate", user_action="auto_sent", latency_ms=3000),
            # 실패 건: 타임아웃까지 8초를 기다렸다.
            _log(user_id, room_id, verdict=None, latency_ms=8000),
        ]
    )
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert report.latency_max_ms == 3000  # 8000이 아니다
    assert report.latency_p50_ms == 2000
    assert report.latency_p95_ms == 3000
    assert report.prompt_tokens_total == 900
    assert report.completion_tokens_total == 24
    assert report.tokens_total == 924


async def test_report_rate_and_undetected_candidates_read_messages(db_session: Any) -> None:
    """신고율과 미검출 후보만 `messages`를 읽는다 (BR-7.6).

    미검출 후보는 **비율이 아니라 건수**다 — 신고된 것 중 모델이 `ok`라 했던
    사례를 표본으로 확보하는 것이지, 놓친 비율을 재는 것이 아니다 (ASM-6).
    """
    user_id, room_id = await _actors(db_session)
    db_session.add_all(
        [
            # 모델이 ok라 했는데 사용자가 신고 = 미검출 후보
            _message(room_id, user_id, 1, status="ok", reported=True),
            # 경고를 보고 보낸 뒤 신고 = 미검출이 아니다
            _message(room_id, user_id, 2, status="flagged_sent", reported=True),
            _message(room_id, user_id, 3, status="ok"),
            _message(room_id, user_id, 4, status="ok"),
        ]
    )
    await db_session.flush()

    report = await compute_metrics(db_session)

    assert report.messages_total == 4
    assert report.reported_count == 2
    assert report.report_rate == pytest.approx(0.5)
    assert report.undetected_candidates == 1


async def test_since_filters_both_tables(db_session: Any) -> None:
    """`--since`는 판정 로그와 메시지 양쪽에 적용된다."""
    user_id, room_id = await _actors(db_session)
    cutoff = datetime(2026, 7, 29, 0, 0)
    db_session.add_all(
        [
            _log(
                user_id,
                room_id,
                verdict="inappropriate",
                user_action="cancelled",
                created_at=cutoff - timedelta(days=2),
            ),
            _log(
                user_id,
                room_id,
                verdict="inappropriate",
                user_action="sent",
                created_at=cutoff + timedelta(days=1),
            ),
        ]
    )
    await db_session.flush()

    report = await compute_metrics(db_session, since=cutoff)

    assert report.attempted_count == 1
    assert report.true_positives == 0
    assert report.false_positives == 1


# --------------------------------------------------------------------------
# recall (BR-7.5)
# --------------------------------------------------------------------------
async def test_recall_is_the_unavailable_string(db_session: Any) -> None:
    """**recall은 수치가 아니라 문자열이다** (BR-7.5).

    계산해서 0을 넣거나 항목을 빼면 안 된다. 빼면 왜 없는지 모르고, 0을 넣으면
    성능이 나쁜 것으로 오해된다. 산출 불가라는 사실 자체를 보고한다.
    """
    await _actors(db_session)

    report = await compute_metrics(db_session)

    assert report.recall == RECALL_UNAVAILABLE
    assert report.recall == "산출 불가 — 라벨 데이터셋 필요"
    assert not isinstance(report.recall, float)


# --------------------------------------------------------------------------
# 리포트 렌더링 (ADR-008, ASM-1)
# --------------------------------------------------------------------------
def _empty_report(precision: float | None) -> MetricsReport:
    return MetricsReport(
        since=None,
        period_from=datetime(2026, 7, 29),
        period_to=datetime(2026, 8, 4),
        attempted_count=145,
        judged_count=142,
        inappropriate_count=26,
        flag_rate=26 / 142,
        true_positives=20,
        false_positives=6,
        precision=precision,
        unanswered_count=3,
        latency_p50_ms=1200,
        latency_p95_ms=3400,
        latency_max_ms=4900,
        prompt_tokens_total=35_120,
        completion_tokens_total=3_290,
        failed_count=3,
        api_failure_rate=3 / 145,
        messages_total=143,
        reported_count=2,
        report_rate=2 / 143,
        undetected_candidates=1,
    )


def test_report_prints_recall_as_the_unavailable_string() -> None:
    """리포트의 recall 줄에 산출 불가 사유가 그대로 나온다 (BR-7.5)."""
    output = render_report(_empty_report(20 / 26))

    assert RECALL_UNAVAILABLE in output


def test_report_always_marks_precision_as_approximate() -> None:
    """**precision 옆에 항상 근사 표시가 붙는다** (ASM-1).

    숫자만 보면 정확한 측정값으로 읽힌다. 이 값은 취소가 "판정에 동의해서"인지
    "귀찮아서"인지 구별하지 못한다.
    """
    output = render_report(_empty_report(20 / 26))

    assert PRECISION_APPROXIMATE_MARK in output
    assert "0.769" in output
    # 하단 각주가 그 표시의 내용을 설명한다.
    assert "user_action을 정답 라벨로 삼은 근사치" in output


def test_report_uses_a_different_message_when_precision_has_no_sample() -> None:
    """precision의 산출 불가 문구는 recall과 **다르다** — 원인이 다르기 때문이다.

    recall은 원리적으로 산출할 수 없고(라벨 모수가 없다), precision은 이번 기간에
    표본이 없을 뿐이다. 같은 문구를 쓰면 "데이터가 쌓이면 나오는 값"과 "영원히
    안 나오는 값"이 구별되지 않는다. 0.0으로 표시하지도 않는다.
    """
    output = render_report(_empty_report(None))

    assert PRECISION_UNAVAILABLE in output
    assert PRECISION_UNAVAILABLE != RECALL_UNAVAILABLE
    assert "0.000" not in output
    # 값이 없어도 근사 표시는 유지된다 — 줄 모양이 흔들리지 않는다.
    assert PRECISION_APPROXIMATE_MARK in output

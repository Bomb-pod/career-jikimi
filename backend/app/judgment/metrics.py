"""지표 산출 — FR-7.5의 표를 그대로 계산한다 (W4).

**집계 축이 `judgment_logs`다** (BR-7.2). `messages.verification_status`를 필터로
쓰지 않는다 — **취소된 건은 `messages` 행이 없어서** 그 필터로는 영원히 잡히지
않고, 그러면 TP가 항상 0이 되어 precision이 계산 불가가 된다. 이것이 요구사항
단계에서 한 번 잡힌 결함이라 여기서 다시 깨뜨리지 않는다.

**분모가 두 종류다.** 대부분은 `verdict IS NOT NULL`로 거른 뒤 세지만, API
실패율만 거르기 전의 전체 행을 쓴다 — 실패를 세는 지표이므로 실패를 걸러내면
항상 0이 된다.

**신고 관련 두 지표만 `messages`를 읽는다** (BR-7.6). 이 단위가 다른 테이블을
읽는 유일한 지점이며, 그래서 `compute_metrics()`는 `judge()`와 달리 앱 전체가
있어야 의미가 있다.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.judgment.service import VERDICT_INAPPROPRIATE
from app.judgment.types import MetricsReport
from app.models import JudgmentLog, Message

logger = logging.getLogger(__name__)

#: `messages.verification_status` 중 "모델이 적절하다고 한" 값. 미검출 후보를
#: 세는 기준이다 (FR-7.5, BR-7.6).
_STATUS_OK: Final[str] = "ok"

#: 사용자가 팝업에 응답한 두 값. precision의 모집단이다 (BR-7.3).
_ACTION_SENT: Final[str] = "sent"
_ACTION_CANCELLED: Final[str] = "cancelled"


def _count_if(condition: sa.ColumnElement[bool]) -> sa.ColumnElement[int]:
    """조건을 만족하는 행 수. `SUM(CASE WHEN ... THEN 1 ELSE 0 END)`.

    `COUNT`를 여러 번 쓰는 대신 조건부 합계를 한 SELECT에 모은다 — 지표마다
    쿼리를 보내면 왕복이 열 번을 넘고, 그 사이에 행이 늘면 지표끼리 어긋난다.
    """
    return sa.func.coalesce(sa.func.sum(sa.case((condition, 1), else_=0)), 0)


def _ratio(numerator: int, denominator: int) -> float | None:
    """비율. **분모가 0이면 `None`** — 0.0으로 표시하지 않는다 (BR-7.3).

    0.0으로 두면 "표본이 없다"가 "성능이 0이다"로 읽힌다. 그 오해는 precision에서
    특히 비싸다.
    """
    if denominator == 0:
        return None
    return numerator / denominator


def _percentile(sorted_values: list[int], fraction: float) -> int | None:
    """정렬된 값에서 백분위수를 고른다 (nearest-rank). 비어 있으면 `None`.

    보간하지 않는 이유 — `latency_ms`는 정수 밀리초이고, 실제로 관측된 값 하나를
    돌려주는 편이 "p95가 3412.5ms"보다 해석하기 쉽다. 표본이 적을 때 보간값은
    존재하지 않는 지연을 만들어내기도 한다.
    """
    if not sorted_values:
        return None
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


async def compute_metrics(
    session: AsyncSession,
    since: datetime | None = None,
) -> MetricsReport:
    """FR-7.5의 지표를 산출한다 — W4.

    Args:
        session: 세션. 읽기만 한다.
        since: 이 시각 이후에 만들어진 행만 집계한다. `None`이면 전 기간.

    Returns:
        `MetricsReport`. **`recall`은 수치가 아니라 문자열이다** (BR-7.5).

    쿼리는 셋이다:

        1. `judgment_logs` 조건부 합계 — 건수·라벨·토큰·기간
        2. `judgment_logs`의 `latency_ms` 목록 — 백분위수는 파이썬에서 계산한다
        3. `messages` 조건부 합계 — 신고 관련 두 지표뿐 (BR-7.6)
    """
    log_window = [] if since is None else [JudgmentLog.created_at >= since]
    judged = JudgmentLog.verdict.is_not(None)
    inappropriate = JudgmentLog.verdict == VERDICT_INAPPROPRIATE

    # 1. 로그 집계. `attempted`만 거르기 전의 전체 행이다.
    totals = (
        await session.execute(
            sa.select(
                sa.func.count().label("attempted"),
                _count_if(judged).label("judged"),
                _count_if(inappropriate).label("inappropriate"),
                _count_if(
                    sa.and_(inappropriate, JudgmentLog.user_action == _ACTION_CANCELLED)
                ).label("true_positives"),
                _count_if(sa.and_(inappropriate, JudgmentLog.user_action == _ACTION_SENT)).label(
                    "false_positives"
                ),
                _count_if(sa.and_(inappropriate, JudgmentLog.user_action.is_(None))).label(
                    "unanswered"
                ),
                sa.func.coalesce(
                    sa.func.sum(sa.case((judged, JudgmentLog.prompt_tokens), else_=0)), 0
                ).label("prompt_tokens"),
                sa.func.coalesce(
                    sa.func.sum(sa.case((judged, JudgmentLog.completion_tokens), else_=0)), 0
                ).label("completion_tokens"),
                sa.func.min(JudgmentLog.created_at).label("period_from"),
                sa.func.max(JudgmentLog.created_at).label("period_to"),
            ).where(*log_window)
        )
    ).one()

    # 2. 지연 분포. **판정된 행만** — 타임아웃 건을 섞으면 분포가 타임아웃 값으로
    #    끌려가고, 그 사실은 API 실패율이 따로 보고한다.
    latencies = list(
        (
            await session.execute(
                sa.select(JudgmentLog.latency_ms)
                .where(judged, *log_window)
                .order_by(JudgmentLog.latency_ms)
            )
        )
        .scalars()
        .all()
    )

    # 3. 신고 지표 (BR-7.6). 이 단위가 `messages`를 읽는 유일한 지점이다.
    message_window = [] if since is None else [Message.created_at >= since]
    reported = Message.misdirect_reported_at.is_not(None)
    message_totals = (
        await session.execute(
            sa.select(
                sa.func.count().label("messages_total"),
                _count_if(reported).label("reported"),
                _count_if(sa.and_(reported, Message.verification_status == _STATUS_OK)).label(
                    "undetected"
                ),
            ).where(*message_window)
        )
    ).one()

    attempted = int(totals.attempted)
    judged_count = int(totals.judged)
    inappropriate_count = int(totals.inappropriate)
    true_positives = int(totals.true_positives)
    false_positives = int(totals.false_positives)
    failed_count = attempted - judged_count
    messages_total = int(message_totals.messages_total)
    reported_count = int(message_totals.reported)

    return MetricsReport(
        since=since,
        period_from=totals.period_from,
        period_to=totals.period_to,
        attempted_count=attempted,
        judged_count=judged_count,
        inappropriate_count=inappropriate_count,
        flag_rate=_ratio(inappropriate_count, judged_count),
        true_positives=true_positives,
        false_positives=false_positives,
        # 미응답은 분모에 넣지 않는다 (BR-7.4) — TP도 FP도 아니다.
        precision=_ratio(true_positives, true_positives + false_positives),
        unanswered_count=int(totals.unanswered),
        latency_p50_ms=_percentile(latencies, 0.50),
        latency_p95_ms=_percentile(latencies, 0.95),
        latency_max_ms=latencies[-1] if latencies else None,
        prompt_tokens_total=int(totals.prompt_tokens),
        completion_tokens_total=int(totals.completion_tokens),
        failed_count=failed_count,
        # **여기만 분모가 전체 행이다.**
        api_failure_rate=_ratio(failed_count, attempted),
        messages_total=messages_total,
        reported_count=reported_count,
        report_rate=_ratio(reported_count, messages_total),
        undetected_candidates=int(message_totals.undetected),
    )


__all__ = ["compute_metrics"]

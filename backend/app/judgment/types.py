"""판정이 주고받는 값 객체 — 호출자가 분기하는 유일한 표면.

**`JudgeResult`는 세 갈래뿐이다.** U5는 이 셋만 분기하고 판정의 내부를 모른다:

    match await judge(session, user_id, room_id, context, text):
        case Appropriate(score, log_id):    ...  # verification_status = ok
        case Inappropriate(score, log_id):  ...  # 409 Blocked, 저장하지 않는다
        case Failed(log_id):                ...  # verification_status = failed

**`Failed`는 예외가 아니라 반환값이다** (BR-6.7). 실패는 "일어나면 안 되는 일"이
아니라 FR-8이 정의한 흐름의 일부다. 예외로 만들면 호출자가 정상 분기를
`try/except`로 쓰게 되고, 그러면 진짜 오류와 섞인다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.judgment.constants import RECALL_UNAVAILABLE


@dataclass(frozen=True, slots=True)
class ContextMessage:
    """판정 문맥에 들어가는 메시지 하나. **이 단위가 소유하는 값 객체다.**

    U5의 ORM 모델(`app.models.Message`)을 받지 않는다 — 받으면 이 단위가 DB와
    U5에 묶여 `try` CLI가 채팅 앱 없이 돌 수 없게 된다. 그것이 이 단위를 DAG에서
    앞으로 당긴 값어치다.

    Attributes:
        sender_id: 발신자. **모델 입력에 들어가지 않는다** — 익명 라벨(A, B, C…)로
            바뀐 뒤에야 프롬프트에 실린다 (BR-6.2). 여기서 필요한 이유는 "누가
            말했는가"가 아니라 "화자가 바뀌었는가"를 계산하기 위해서다.
        text: 메시지 본문.
        seq: 방 안의 메시지 순번. **`judgment_logs.context_from_seq`~
            `context_to_seq`에 남기려면 필요하다** (BR-6.1) — 두 컬럼이 NOT NULL이고,
            `judge()`의 시그니처는 U5와의 계약이라 seq를 별도 인자로 받을 수 없다.
            `try` CLI처럼 DB에 남기지 않는 경로는 1부터 붙여 쓴다.
    """

    sender_id: int
    text: str
    seq: int


@dataclass(frozen=True, slots=True)
class Appropriate:
    """점수가 임계값 **미만**이다 (BR-6.5). U5는 그대로 전송하고 `ok`로 기록한다."""

    score: float
    log_id: int


@dataclass(frozen=True, slots=True)
class Inappropriate:
    """점수가 임계값 **이상**이다 — 같으면 부적절이다 (BR-6.5).

    U5는 저장하지 않고 `Blocked(log_id, score)`로 409를 낸다. 사용자가 강행하면
    `log_id`가 `force_log_id`로 돌아온다.
    """

    score: float
    log_id: int


@dataclass(frozen=True, slots=True)
class Failed:
    """호출이 실패했다 — 타임아웃·연결 오류·5xx·429 재시도 소진 (BR-6.7).

    **점수가 없다.** `score` 필드를 두지 않은 것이 의도다 — 실패에 점수를 만들어
    주면 호출자가 그것을 판정으로 착각할 수 있다. 로그 행은 남아 있고
    (`score`·`verdict`가 NULL), U5는 `failed`로 전송한다 (FR-8.3).
    """

    log_id: int


#: `judge()`의 반환 타입. **이 셋이 전부다.**
JudgeResult = Appropriate | Inappropriate | Failed


@dataclass(frozen=True, slots=True)
class MetricsReport:
    """`compute_metrics()`가 돌려주는 지표 묶음 — FR-7.5의 표 그대로.

    **분모가 두 종류다.** 대부분의 지표는 `verdict IS NOT NULL`로 거른 뒤
    계산하지만(BR-7.2), `api_failure_rate`만 거르기 전의 전체 행을 쓴다 —
    실패를 세는 지표이므로 실패를 걸러내면 항상 0이 된다.

    비율 필드가 `float | None`인 이유는 분모 0을 0.0으로 표시하지 않기
    위해서다 (BR-7.3). `None`은 "0%"가 아니라 "산출할 표본이 없음"이다.
    """

    #: 집계 기간의 시작 필터. `None`이면 전 기간.
    since: datetime | None
    #: 실제로 집계에 들어간 로그의 첫·마지막 `created_at`. 행이 없으면 둘 다 `None`.
    period_from: datetime | None
    period_to: datetime | None

    #: **거르기 전의 전체 행** — 호출을 시도한 모든 건 (BR-6.8). 실패율의 분모.
    attempted_count: int
    #: `verdict IS NOT NULL` — 나머지 지표 전부의 모집단 (BR-7.2).
    judged_count: int
    #: 그중 `verdict = 'inappropriate'`.
    inappropriate_count: int
    #: `inappropriate_count / judged_count`. 판정 건이 없으면 `None`.
    #:
    #: **이 값이 높으면 precision과 무관하게 기능을 못 쓴다** (FR-7.5).
    flag_rate: float | None

    #: TP — 부적절 판정 후 사용자가 취소 (BR-7.3).
    true_positives: int
    #: FP — 부적절 판정 후 사용자가 그대로 전송 (BR-7.3).
    false_positives: int
    #: `TP / (TP + FP)`. **분모가 0이면 `None`** — 0.0이 아니다 (BR-7.3).
    precision: float | None
    #: 부적절 판정인데 `user_action`이 NULL인 건 (BR-7.4). precision에서 제외하되
    #: 별도로 보고한다 — 크면 팝업이 무시당하고 있다는 신호다.
    unanswered_count: int

    #: `latency_ms`의 분포. 판정된 행(`verdict IS NOT NULL`)만 본다 — 타임아웃 건을
    #: 섞으면 분포가 타임아웃 값으로 끌려가고, 그 사실은 `api_failure_rate`가
    #: 따로 보고한다. 행이 없으면 셋 다 `None`.
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    latency_max_ms: int | None

    prompt_tokens_total: int
    completion_tokens_total: int

    #: `verdict IS NULL` — 호출을 시도했으나 못 받은 건.
    failed_count: int
    #: `failed_count / attempted_count`. **분모가 전체 행이다** (BR-7.2 예외).
    api_failure_rate: float | None

    #: 신고 관련 두 지표만 `messages`를 읽는다 (BR-7.6). 이 단위가 다른 테이블을
    #: 읽는 유일한 지점이다.
    messages_total: int
    reported_count: int
    #: 전송된 메시지 대비 신고 비율. **신고 행위의 빈도이지 오발송의 빈도가
    #: 아니다** (ASM-6).
    report_rate: float | None
    #: 신고된 것 중 `verification_status='ok'`였던 **건수**. 비율이 아니라 표본이다.
    undetected_candidates: int

    #: **문자열이다.** 수치를 넣거나 항목을 빼지 않는다 (BR-7.5).
    recall: str = RECALL_UNAVAILABLE

    @property
    def tokens_total(self) -> int:
        """프롬프트 + 응답 토큰 합계."""
        return self.prompt_tokens_total + self.completion_tokens_total


__all__ = [
    "Appropriate",
    "ContextMessage",
    "Failed",
    "Inappropriate",
    "JudgeResult",
    "MetricsReport",
]

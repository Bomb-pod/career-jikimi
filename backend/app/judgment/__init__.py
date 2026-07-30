"""`judgment` 모듈 — LLM 호출·점수 판정·판정 로그·지표 산출 (U2 judgment-core).

`unit-of-work-dependency.md`가 기록한 **U2가 U5에 제공하는 계약**을 여기서
재노출한다. **이 시그니처를 바꾸면 U5가 깨진다:**

    from app.judgment import judge, get_log_for_force, set_user_action, link_message
    from app.judgment import Appropriate, Inappropriate, Failed, ContextMessage

    match await judge(session, user_id, room_id, context, text):
        case Appropriate(score, log_id):    ...   # verification_status = ok
        case Inappropriate(score, log_id):  ...   # 409 Blocked, 저장하지 않는다
        case Failed(log_id):                ...   # verification_status = failed

**`Failed`는 예외가 아니라 반환값이다** (BR-6.7) — 실패는 FR-8이 정의한 흐름의
일부이지 오류가 아니다.

**이 단위는 채팅 앱 없이 단독으로 돈다.** 문맥과 후보 문장을 인자로 받으므로
CLI(`python -m app.judgment.try`)나 테스트에서 바로 호출할 수 있다. 그것이 이
단위를 DAG에서 앞으로 당긴 이유다.

`router`를 여기서 import하지 않는다 — `main.py`만 `app.judgment.router`를 본다.
CLI 두 개(`report`, `try`)도 마찬가지로 각자 모듈로만 실행한다.
"""

from app.judgment.exceptions import (
    AlreadyResolved,
    ForceTokenForbidden,
    InvalidForceToken,
)
from app.judgment.metrics import compute_metrics
from app.judgment.service import (
    get_log_for_force,
    judge,
    link_message,
    set_user_action,
)
from app.judgment.types import (
    Appropriate,
    ContextMessage,
    Failed,
    Inappropriate,
    JudgeResult,
    MetricsReport,
)

__all__ = [
    "AlreadyResolved",
    "Appropriate",
    "ContextMessage",
    "Failed",
    "ForceTokenForbidden",
    "Inappropriate",
    "InvalidForceToken",
    "JudgeResult",
    "MetricsReport",
    "compute_metrics",
    "get_log_for_force",
    "judge",
    "link_message",
    "set_user_action",
]

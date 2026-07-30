"""판정에서 코드가 정하는 상수 — 환경변수로 빼지 않은 값들.

**환경변수와 상수의 경계**: 운영 중에 조정할 값(`AI_VERDICT_THRESHOLD`,
`AI_CONTEXT_N`, `AI_TIMEOUT_SECONDS`, `OPENAI_MODEL`)은 `app.core.config`의
`settings`에 있다. 여기 있는 것은 **바뀌면 규칙의 의미가 깨지는 값**이다.

프롬프트 문안은 여기가 아니라 `prompt.py`에 있다 — 문안과 스키마가 한 곳에
모여 있어야 `try` CLI와 운영 경로가 같은 것을 쓴다.
"""

from __future__ import annotations

import sys
from typing import Final

# --------------------------------------------------------------------------
# 호출 예산 (BR-6.7, NFR-1)
# --------------------------------------------------------------------------

#: 최초 호출 + 재시도 1회의 **총 대기 상한**(초).
#:
#: NFR-1이 "재시도를 포함한 최악의 경우 10초 이내"를, BR-6.7이 "총 상한 10초를
#: 넘지 않는다"를 요구한다. `AI_TIMEOUT_SECONDS`가 잘못 설정돼도(예: 8초) 이
#: 예산이 두 번째 시도의 타임아웃을 깎아 상한을 지킨다 — 설정 실수 하나가
#: 사용자 대기 시간을 20초로 만들지 않게 하는 마지막 방어선이다.
TOTAL_BUDGET_SECONDS: Final[float] = 10.0

#: 최초 1회 + 재시도 1회. **정확히 2다** (BR-6.7).
#:
#: 2회 재시도면 사용자가 최대 15초를 기다리고, 그 시점에는 이미 앱이 멈춘
#: 것으로 읽힌다. 늘리려면 BR-6.7을 먼저 바꿔야 한다.
MAX_ATTEMPTS: Final[int] = 2

# --------------------------------------------------------------------------
# 모델 파라미터
# --------------------------------------------------------------------------

#: **0으로 고정한다.** 환경변수로 빼지 않는다.
#:
#: BR-6.5의 임계값 조정이 의미를 가지려면 같은 입력에 같은 점수가 나와야 한다.
#: 튜닝 대상은 프롬프트와 임계값이고, 재현성은 고정값이어야 지켜진다.
TEMPERATURE: Final[float] = 0.0

# --------------------------------------------------------------------------
# 점수 (BR-6.6)
# --------------------------------------------------------------------------

#: JSON 스키마의 `number`는 범위를 강제하지 않는다. 모델이 1.2를 줄 수 있으므로
#: 이 범위로 클램프한다 — **실패로 처리하지 않는다** (BR-6.6).
SCORE_MIN: Final[float] = 0.0
SCORE_MAX: Final[float] = 1.0

#: `judgment_logs.score`·`threshold`가 `DECIMAL(4,3)`이다. 그 자릿수에 맞춰
#: 반올림해 저장한다 — 드라이버가 조용히 자르게 두지 않는다.
SCORE_DECIMAL_PLACES: Final[int] = 3

# --------------------------------------------------------------------------
# 지표 문구 (BR-7.3, BR-7.5, ASM-1)
# --------------------------------------------------------------------------

#: **recall은 수치가 아니라 이 문자열이다** (BR-7.5).
#:
#: 계산해서 0을 넣거나 항목을 빼면 안 된다. 빼면 왜 없는지 모르고, 0을 넣으면
#: 성능이 나쁜 것으로 오해된다. 산출 불가라는 사실 자체가 보고 대상이다.
RECALL_UNAVAILABLE: Final[str] = "산출 불가 — 라벨 데이터셋 필요"

#: precision의 분모가 0일 때의 표시 문구 (BR-7.3).
#:
#: **recall과 문구가 다른 것이 의도다.** 원인이 다르다 — recall은 원리적으로
#: 산출할 수 없고(라벨 모수가 없다), precision은 이번 기간에 표본이 없을 뿐이다.
#: 같은 문구를 쓰면 "데이터가 쌓이면 나오는 값"과 "영원히 안 나오는 값"이
#: 구별되지 않는다. 0.0으로 표시하지 않는다.
PRECISION_UNAVAILABLE: Final[str] = "산출 불가 — 부적절 판정 건이 없음"

#: precision 값 옆에 **항상** 붙는 표시 (ASM-1). 숫자만 보면 정확한 측정값으로
#: 읽힌다.
PRECISION_APPROXIMATE_MARK: Final[str] = "※ 근사 — ASM-1 참조"

#: 리포트 하단 각주 (ASM-1). `PRECISION_APPROXIMATE_MARK`가 가리키는 내용이다.
PRECISION_FOOTNOTE: Final[str] = (
    "※ precision은 user_action을 정답 라벨로 삼은 근사치입니다.\n"
    "  취소가 판정 동의인지 단순 회피인지 구별하지 못합니다."
)

# --------------------------------------------------------------------------
# CLI 출력
# --------------------------------------------------------------------------


def use_utf8_console() -> None:
    """표준 출력·오류를 UTF-8로 돌린다. **두 CLI가 시작하자마자 부른다.**

    **왜 필요한가** — 위 문구들의 `—`(U+2014 em dash)가 cp949에 없다. 한국어
    Windows 콘솔의 기본 코드페이지가 cp949라서, 그대로 출력하면 리포트가
    `UnicodeEncodeError`로 죽는다. 문구는 규칙이 정한 것이라 바꿀 수 없고
    (BR-7.5의 recall 문자열), 바꿀 수 있는 것은 출력 인코딩이다.

    `errors="replace"`를 함께 주는 이유 — 어떤 이유로 UTF-8 전환이 안 되는
    환경이어도 **지표 리포트가 예외로 죽지는 않게** 한다. 글자 하나가 `?`로
    나오는 것이 리포트 전체를 못 보는 것보다 낫다.

    이 함수가 상수 모듈에 있는 이유는 두 CLI(`report`, `try`)가 공유하는 유일한
    모듈이 여기이기 때문이다. `try`는 DB를 import하지 않아야 하므로
    (`business-logic-model.md` § 단독 검증 경로) `report`에서 가져올 수 없다.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


__all__ = [
    "MAX_ATTEMPTS",
    "PRECISION_APPROXIMATE_MARK",
    "PRECISION_FOOTNOTE",
    "PRECISION_UNAVAILABLE",
    "RECALL_UNAVAILABLE",
    "SCORE_DECIMAL_PLACES",
    "SCORE_MAX",
    "SCORE_MIN",
    "TEMPERATURE",
    "TOTAL_BUDGET_SECONDS",
    "use_utf8_console",
]

"""프롬프트 문안과 응답 스키마 — **운영 경로와 `try` CLI의 단일 출처.**

문안이 두 벌이 되면 CLI로 튜닝한 결과가 운영에 반영되지 않고, 그러면 튜닝 자체가
무의미해진다. `service.judge()`와 `app.judgment.try`가 모두 여기의
`build_messages()`를 부른다.

문안은 `functional-design/business-logic-model.md` § 프롬프트 설계에서 확정한
것을 **그대로** 옮겼다. 임의로 다듬지 않는다 — 각 문장이 왜 거기 있는지는 그
문서가 설명한다. 특히 다음 셋을 빼면 안 된다:

1. **"판단하지 않는 것" 3항목** — 없으면 모델이 알아서 욕설을 잡는다. 그러면
   측정 대상이 둘로 늘어 precision 해석이 흐려진다 (BR-6.3, FR-6.7).
2. **"화제가 바뀌었다는 사실만으로 부적합하다고 보지 마십시오"** — 빼면 모델이
   화제 전환을 전부 부적합으로 잡아 flag rate가 치솟고 기능이 죽는다.
3. **점수 구간 4개의 언어적 설명** — 숫자만 요구하면 분포가 0.5 근처로 몰린다.

프롬프트가 한국어인 것은 **검증되지 않은 가정이다.** 판정 대상이 한국어 대화라
언어를 맞추는 편이 자연스러울 것으로 보지만 확인되지 않았다 — `try` CLI가 이것을
실험하는 도구다.
"""

from __future__ import annotations

from typing import Any, Final

from app.judgment.anonymize import label_speakers
from app.judgment.types import ContextMessage

#: 채팅 completions API에 넘기는 메시지 한 건의 모양.
ChatMessage = dict[str, str]

#: system 프롬프트. `business-logic-model.md` § 프롬프트 설계 § system 그대로.
SYSTEM_PROMPT: Final[str] = """당신은 채팅 메시지가 그 대화방의 문맥에 맞는지 판단합니다.

사용자는 여러 채팅방을 오가며, 가끔 방을 착각해 엉뚱한 방에 메시지를
보냅니다. 당신의 일은 그것을 보내기 전에 알아채는 것입니다.

## 판단 기준

주어진 대화의 흐름·주제·어조에 비추어, 보내려는 메시지가 이 방에서
나올 법한 말인지 판단하십시오.

## 판단하지 않는 것

- 메시지 내용 자체의 적절성(욕설·비방·민감정보 여부)은 판단하지 마십시오.
- 맞춤법·문장의 완성도는 판단하지 마십시오.
- 화제가 바뀌었다는 사실만으로 부적합하다고 보지 마십시오. 대화는
  자연스럽게 화제를 바꿉니다.

## 점수

0.0에서 1.0 사이의 부적합 점수를 매기십시오. 높을수록 이 방에
어울리지 않는다는 뜻입니다.

- 0.0 ~ 0.2  이 대화의 자연스러운 연장
- 0.3 ~ 0.5  화제는 바뀌었으나 같은 관계·상황에서 나올 수 있는 말
- 0.6 ~ 0.8  이 방의 성격과 어긋남
- 0.9 ~ 1.0  명백히 다른 방에 갈 메시지

## 표기

화자는 A, B, C로 익명 표기됩니다. 이 라벨은 이번 판단에만 쓰이는
순번이며 특정 인물을 뜻하지 않습니다."""

#: user 메시지의 두 절 제목. 문안과 함께 고정한다.
CONTEXT_HEADING: Final[str] = "## 최근 대화"
CANDIDATE_HEADING: Final[str] = "## 보내려는 메시지"

#: Structured Outputs 응답 형식 (ADR-005).
#:
#: **`strict: true`가 파싱 실패라는 실패 유형을 없앤다** (BR-6.4). 그래서 파싱
#: 오류를 FR-8.1의 실패 경로(타임아웃·재시도)로 흘려보내지 않는다 — 그 경로는
#: 네트워크·API 장애용이다.
#:
#: **스키마가 `score` 하나뿐인 것도 결정이다.** 근거 문장을 받으면 디버깅에
#: 좋지만 토큰과 지연이 늘고, 지금 필요한 것은 점수다 (FR-6.3). 나중에 늘리는
#: 비용은 작다.
#:
#: `additionalProperties: false`와 `required`에 모든 키를 넣는 것은 OpenAI의
#: strict 모드 요구사항이다 — 빼면 API가 400으로 거절한다.
#:
#: 확인 완료: `gpt-4o-mini`가 `strict: true`를 지원한다 (ADR-005의 이월 항목).
RESPONSE_FORMAT: Final[dict[str, Any]] = {
    "type": "json_schema",
    "json_schema": {
        "name": "verdict",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
            },
            "required": ["score"],
            "additionalProperties": False,
        },
    },
}

#: 응답 JSON에서 꺼내는 키. 스키마와 파싱이 어긋나지 않게 한 곳에 둔다.
SCORE_KEY: Final[str] = "score"


def build_user_message(
    labelled: list[tuple[str, str]],
    candidate_label: str,
    candidate_text: str,
) -> str:
    """익명화된 문맥과 후보 문장을 user 메시지로 조립한다.

    `business-logic-model.md` § 프롬프트 설계 § user의 형식 그대로다:

        ## 최근 대화

        A: 내일 회의 몇 시죠?
        B: 10시입니다

        ## 보내려는 메시지

        B: 오늘 저녁에 치킨 어때?

    **본문을 가공하지 않는다.** 여러 줄 메시지는 여러 줄 그대로 실린다 —
    판정 대상은 사용자가 실제로 쓴 문장이고, 줄바꿈을 접거나 공백을 정리하면
    모델이 보는 것과 사용자가 보낸 것이 달라진다. 그 대가로 본문에 `##`로
    시작하는 줄을 넣어 절 제목을 흉내내는 것이 이론상 가능하지만, 그것으로
    조작할 수 있는 것은 **자기 자신의 메시지에 대한 판정뿐**이고, 그 사용자는
    경고를 받은 뒤 강행 전송(`force_log_id`)이라는 정식 경로로 같은 결과에
    도달할 수 있다. 얻는 것이 없는 우회다.
    """
    lines = [f"{label}: {text}" for label, text in labelled]
    context_block = "\n".join(lines) if lines else "(이전 대화 없음)"
    return (
        f"{CONTEXT_HEADING}\n\n"
        f"{context_block}\n\n"
        f"{CANDIDATE_HEADING}\n\n"
        f"{candidate_label}: {candidate_text}"
    )


def build_messages(
    context: list[ContextMessage],
    candidate_sender_id: int,
    candidate_text: str,
) -> list[ChatMessage]:
    """익명화부터 메시지 조립까지 — 판정 입력을 한 번에 만든다.

    Args:
        context: 오래된 것부터 정렬된 최근 `AI_CONTEXT_N`개 (BR-6.1).
        candidate_sender_id: 보내려는 사람. 익명 라벨을 붙이는 데만 쓰이고
            **프롬프트에는 들어가지 않는다** (BR-6.2).
        candidate_text: 판정 대상 문장.

    Returns:
        `[{"role": "system", ...}, {"role": "user", ...}]`.

    이 함수가 `service.judge()`와 `app.judgment.try`의 **공통 진입점이다.**
    한쪽만 익명화를 거치는 일이 생기지 않게 조립을 여기 하나로 묶었다.
    """
    labelled, candidate_label = label_speakers(context, candidate_sender_id)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(labelled, candidate_label, candidate_text)},
    ]


__all__ = [
    "CANDIDATE_HEADING",
    "CONTEXT_HEADING",
    "RESPONSE_FORMAT",
    "SCORE_KEY",
    "SYSTEM_PROMPT",
    "ChatMessage",
    "build_messages",
    "build_user_message",
]

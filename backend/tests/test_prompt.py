"""프롬프트 문안과 응답 스키마 — FR-6.3, FR-6.7, BR-6.3, BR-6.4, ADR-005.

**문안의 세 부분을 회귀 테스트로 고정한다.** 프롬프트는 튜닝 대상이라 자주
바뀌는데, 그때 실수로 빠지면 조용히 다른 것을 측정하게 되는 문장들이 있다:

1. "판단하지 않는 것" 3항목 — 빠지면 모델이 욕설도 잡아 측정 대상이 둘이 된다
2. 점수 구간 4개 — 빠지면 분포가 0.5로 몰린다
3. `strict: true` / `additionalProperties: false` — 빠지면 형식 보장이 사라진다

문구 전체를 바이트 단위로 고정하지는 않는다 — 그러면 표현을 다듬을 때마다
테스트를 고쳐야 해서 튜닝을 방해한다. **의미가 살아 있는지**만 본다.
"""

from __future__ import annotations

from app.judgment.prompt import (
    CANDIDATE_HEADING,
    CONTEXT_HEADING,
    RESPONSE_FORMAT,
    SYSTEM_PROMPT,
    build_messages,
)
from app.judgment.types import ContextMessage


def test_system_prompt_keeps_the_three_out_of_scope_clauses() -> None:
    """ "판단하지 않는 것" 3항목이 살아 있다 — BR-6.3, FR-6.7.

    이것을 안 적으면 모델이 알아서 욕설을 잡는다. 그러면 측정 대상이 둘로 늘어
    precision 해석이 흐려진다 — "부적절 판정"이 문맥 이탈인지 욕설인지 구별되지
    않는다.
    """
    assert "판단하지 않는 것" in SYSTEM_PROMPT
    # 1. 내용 자체의 적절성
    assert "욕설" in SYSTEM_PROMPT
    assert "민감정보" in SYSTEM_PROMPT
    # 2. 맞춤법
    assert "맞춤법" in SYSTEM_PROMPT
    # 3. 화제 전환만으로 부적합이 아니다 — 빼면 flag rate가 치솟아 기능이 죽는다
    assert "화제가 바뀌었다는 사실만으로 부적합하다고 보지 마십시오" in SYSTEM_PROMPT


def test_system_prompt_keeps_all_four_score_bands() -> None:
    """점수 구간 4개의 언어적 설명이 살아 있다.

    숫자만 요구하면 모델이 0.5 근처로 몰린다. 구간마다 무엇을 뜻하는지 주어야
    분포가 벌어지고, 그래야 임계값 조정에 의미가 생긴다 (BR-6.5).
    """
    for band in ("0.0 ~ 0.2", "0.3 ~ 0.5", "0.6 ~ 0.8", "0.9 ~ 1.0"):
        assert band in SYSTEM_PROMPT

    # 구간 설명이 숫자만 있는 것이 아니라 말로 붙어 있어야 한다.
    assert "자연스러운 연장" in SYSTEM_PROMPT
    assert "명백히 다른 방에 갈 메시지" in SYSTEM_PROMPT


def test_system_prompt_explains_the_anonymous_labels() -> None:
    """라벨이 순번일 뿐 특정 인물이 아니라고 알려준다 (BR-6.2).

    없으면 모델이 A와 B를 고정된 인물로 취급해, 윈도우마다 라벨이 바뀌는 것을
    화자 교체로 읽을 수 있다.
    """
    assert "익명 표기" in SYSTEM_PROMPT
    assert "특정 인물을 뜻하지 않습니다" in SYSTEM_PROMPT


def test_response_format_is_strict_with_a_single_score() -> None:
    """Structured Outputs가 `strict`이고 스키마가 `score` 하나다 — ADR-005, BR-6.4.

    `strict: true`가 형식을 보장하므로 **파싱 실패라는 실패 유형이 없다.**
    `additionalProperties: false`를 빼면 OpenAI가 strict 모드를 거절한다.
    """
    assert RESPONSE_FORMAT["type"] == "json_schema"

    json_schema = RESPONSE_FORMAT["json_schema"]
    assert json_schema["strict"] is True

    schema = json_schema["schema"]
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["score"]
    assert schema["required"] == ["score"]
    assert schema["properties"]["score"]["type"] == "number"


def test_user_message_carries_no_participant_identity() -> None:
    """user 메시지에 사용자 id·이름·별칭이 없다 — FR-6.2의 수용 기준.

    라벨과 본문만 실린다. 이 단언이 깨지면 참여자 정보가 모델 입력에 들어간
    것이다.
    """
    context = [
        ContextMessage(sender_id=70_001, text="내일 회의 몇 시죠?", seq=11),
        ContextMessage(sender_id=70_002, text="10시입니다", seq=12),
    ]

    messages = build_messages(context, candidate_sender_id=70_002, candidate_text="치킨 어때?")

    user_content = messages[1]["content"]
    assert "70001" not in user_content
    assert "70002" not in user_content
    assert "sender" not in user_content.lower()


def test_user_message_follows_the_designed_layout() -> None:
    """`## 최근 대화` + `## 보내려는 메시지` 두 절 — 설계 문서의 형식 그대로.

    문맥과 후보를 절로 나누지 않으면 모델이 후보 문장도 대화의 일부로 읽어,
    "이미 보낸 말"과 "보내려는 말"을 구별하지 못한다.
    """
    context = [
        ContextMessage(sender_id=7, text="내일 회의 몇 시죠?", seq=1),
        ContextMessage(sender_id=12, text="10시입니다", seq=2),
        ContextMessage(sender_id=7, text="자료는 제가 준비할게요", seq=3),
    ]

    candidate = "오늘 저녁에 치킨 어때?"

    messages = build_messages(context, candidate_sender_id=12, candidate_text=candidate)

    assert [item["role"] for item in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert messages[1]["content"] == (
        f"{CONTEXT_HEADING}\n\n"
        "A: 내일 회의 몇 시죠?\n"
        "B: 10시입니다\n"
        "A: 자료는 제가 준비할게요\n\n"
        f"{CANDIDATE_HEADING}\n\n"
        "B: 오늘 저녁에 치킨 어때?"
    )


def test_empty_context_still_produces_both_sections() -> None:
    """문맥이 비어도 두 절이 나온다 — `try` CLI의 빈 문맥 실험을 위해서다."""
    messages = build_messages([], candidate_sender_id=7, candidate_text="안녕")

    user_content = messages[1]["content"]
    assert CONTEXT_HEADING in user_content
    assert CANDIDATE_HEADING in user_content
    assert "A: 안녕" in user_content

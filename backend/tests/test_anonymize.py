"""문맥 익명화 — FR-6.2, BR-6.2.

**가장 중요한 테스트는 `test_output_never_contains_a_sender_id`다.** 나머지는
라벨이 맞는지 보지만 그것은 참여자 정보가 새지 않는지를 본다. FR-6.2의 수용
기준이 "참여자 이름·아이디·별칭은 포함되지 않는다"이고, 그 규칙은 코드가 조금
바뀌어도 계속 지켜져야 한다.

DB도 API 키도 쓰지 않는다 — 순수 함수다.
"""

from __future__ import annotations

from app.judgment.anonymize import label_speakers
from app.judgment.types import ContextMessage


def _context(*pairs: tuple[int, str]) -> list[ContextMessage]:
    """`(sender_id, text)` 쌍으로 문맥을 만든다. seq는 1부터 붙인다."""
    return [
        ContextMessage(sender_id=sender_id, text=text, seq=index + 1)
        for index, (sender_id, text) in enumerate(pairs)
    ]


def test_labels_follow_the_order_of_appearance() -> None:
    """등장 순서대로 A, B, C를 준다 — `business-logic-model.md`의 예시 그대로.

    같은 사람이 다시 말하면 **처음 받은 라벨을 다시 쓴다.** 그렇지 않으면 모델이
    세 사람의 대화로 읽는다.
    """
    context = _context(
        (7, "내일 회의 몇 시죠?"),
        (12, "10시입니다"),
        (7, "자료는 제가 준비할게요"),
    )

    labelled, candidate_label = label_speakers(context, candidate_sender_id=12)

    assert labelled == [
        ("A", "내일 회의 몇 시죠?"),
        ("B", "10시입니다"),
        ("A", "자료는 제가 준비할게요"),
    ]
    assert candidate_label == "B"


def test_candidate_absent_from_the_context_gets_a_fresh_label() -> None:
    """후보 발신자가 문맥에 없으면 **다음 라벨을 새로 준다** (BR-6.2).

    기존 라벨을 재사용하면 모델이 "이미 말하던 사람"으로 읽어, 처음 말하는 사람이
    끼어든 상황과 구별할 수 없게 된다.
    """
    context = _context((7, "안녕하세요"), (12, "네 안녕하세요"))

    _, candidate_label = label_speakers(context, candidate_sender_id=99)

    assert candidate_label == "C"


def test_single_speaker_context_gives_the_candidate_the_second_label() -> None:
    """화자가 한 명뿐인 문맥. 후보가 다른 사람이면 B다."""
    context = _context((7, "혼잣말1"), (7, "혼잣말2"))

    labelled, candidate_label = label_speakers(context, candidate_sender_id=8)

    assert labelled == [("A", "혼잣말1"), ("A", "혼잣말2")]
    assert candidate_label == "B"


def test_empty_context_labels_the_candidate_a() -> None:
    """빈 문맥도 받는다 — `try` CLI가 문맥 없이 돌려볼 수 있어야 한다.

    실제 판정 경로에서는 U5가 문맥 부족을 먼저 걸러낸다 (FR-6.4).
    """
    labelled, candidate_label = label_speakers([], candidate_sender_id=7)

    assert labelled == []
    assert candidate_label == "A"


def test_more_than_twenty_six_speakers_continue_with_two_letters() -> None:
    """26명을 넘으면 `AA`, `AB`로 이어간다.

    요구사항에 없는 방 크기지만, `LABEL_ALPHABET[index]`로 두면 27번째 화자에서
    `IndexError`가 판정 경로 한복판에서 터져 호출 실패로 오해된다.
    """
    context = _context(*[(sender_id, f"발언 {sender_id}") for sender_id in range(28)])

    labelled, candidate_label = label_speakers(context, candidate_sender_id=28)

    labels = [label for label, _ in labelled]
    assert labels[25] == "Z"
    assert labels[26] == "AA"
    assert labels[27] == "AB"
    # 28명이 이미 등장했으므로 후보는 29번째 라벨을 받는다.
    assert candidate_label == "AC"


def test_output_never_contains_a_sender_id() -> None:
    """**출력 어디에도 `sender_id`가 남지 않는다** — FR-6.2의 핵심 검사.

    라벨과 본문만 나가야 한다. 이 단언이 깨지면 사용자 식별자가 모델 입력으로
    흘러간다는 뜻이며, 그것은 익명화가 실패한 것이다.
    """
    sender_ids = [40_001, 40_002, 40_003]
    context = _context(
        (sender_ids[0], "첫 번째"),
        (sender_ids[1], "두 번째"),
        (sender_ids[2], "세 번째"),
    )

    labelled, candidate_label = label_speakers(context, candidate_sender_id=sender_ids[1])

    serialized = repr(labelled) + candidate_label
    for sender_id in sender_ids:
        assert str(sender_id) not in serialized


def test_labels_are_valid_only_inside_the_window() -> None:
    """**라벨은 윈도우 안에서만 유효한 순번이다** (BR-6.2).

    같은 사람(12)이 윈도우가 밀리면서 `B`에서 `A`로 바뀐다. 그것이 신원이 새지
    않는 이유이며, 동시에 판정 품질에 영향을 주는지 확인되지 않은 지점이다 —
    `try` CLI로 관찰할 항목으로 남아 있다.
    """
    first_window = _context((7, "먼저"), (12, "나중"))
    second_window = _context((12, "나중"), (7, "그 다음"))

    first_labels, _ = label_speakers(first_window, candidate_sender_id=7)
    second_labels, _ = label_speakers(second_window, candidate_sender_id=7)

    assert first_labels[1][0] == "B"  # 12번이 첫 윈도우에서는 B
    assert second_labels[0][0] == "A"  # 같은 12번이 다음 윈도우에서는 A

"""문맥 익명화 — 발신자를 윈도우 내 순번 라벨(A, B, C…)로 바꾼다 (FR-6.2, BR-6.2).

**모델 입력에 사용자 이름·아이디·별칭·`display_name`이 들어가지 않는다.** 이
모듈의 출력에 `sender_id`가 남으면 그 자체가 FR-6.2 위반이므로, 그 사실을 단위
테스트로 고정한다.

**그런데 왜 라벨은 넣는가** — 라벨이 없으면 모델이 대화를 한 사람의 독백으로
읽는다. 화자 전환은 문맥 판단의 핵심 신호다. 라벨은 신원이 아니라 대화 구조이며,
**이 윈도우 안에서만 유효한 순번**이라 같은 사람이 다음 판정에서 다른 라벨을 받아도
된다 (BR-6.2). 윈도우가 밀릴 때마다 라벨이 바뀌는 것이 판정 품질에 영향을 주는지는
확인되지 않았다 — `try` CLI로 관찰할 항목이다.
"""

from __future__ import annotations

from typing import Final

from app.judgment.types import ContextMessage

#: 라벨에 쓰는 글자. 26명을 넘으면 `AA`, `AB`로 이어간다.
LABEL_ALPHABET: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _label_for_index(index: int) -> str:
    """0-based 순번을 라벨로 바꾼다. 0→A, 25→Z, 26→AA, 27→AB.

    **26명 넘는 방은 요구사항에 없다.** 그래도 `LABEL_ALPHABET[index]`로 두면
    27번째 화자에서 `IndexError`가 나고, 그 예외는 판정 경로 한복판에서 터져
    호출 실패로 오해된다. 조용히 깨지지 않게 자릿수를 늘린다.

    엑셀 열 이름과 같은 bijective base-26이다 — `Z` 다음이 `AA`이며 `A0` 같은
    자리는 없다.
    """
    if index < 0:  # pragma: no cover - 호출자가 len()으로만 만든다
        raise ValueError(f"라벨 순번은 음수일 수 없습니다: {index}")

    label = ""
    remaining = index + 1
    while remaining > 0:
        remaining, position = divmod(remaining - 1, len(LABEL_ALPHABET))
        label = LABEL_ALPHABET[position] + label
    return label


def label_speakers(
    context: list[ContextMessage],
    candidate_sender_id: int,
) -> tuple[list[tuple[str, str]], str]:
    """문맥의 화자를 등장 순서대로 라벨에 대응시킨다.

    Args:
        context: 오래된 것부터 정렬된 문맥 메시지 (BR-6.1).
        candidate_sender_id: 지금 보내려는 메시지의 발신자.

    Returns:
        `(labelled, candidate_label)`.

        - `labelled`: `(라벨, 본문)` 순서쌍. **`sender_id`가 들어 있지 않다.**
        - `candidate_label`: 후보 발신자의 라벨. 문맥에 이미 등장했으면 그때 받은
          라벨을, 아니면 **다음 라벨을 새로 준다.**

    후보 발신자가 문맥에 없을 때 새 라벨을 주는 것이 중요하다. 기존 라벨 하나를
    재사용하면 모델이 "이 방에서 이미 말하던 사람"으로 읽어, 처음 말하는 사람이
    끼어든 상황과 구별할 수 없게 된다.

    빈 문맥도 받는다 — 그때 후보는 `A`다. 실제 판정 경로에서는 U5가 문맥 부족을
    먼저 걸러내지만(FR-6.4), `try` CLI는 빈 문맥을 넣어볼 수 있어야 한다.
    """
    labels: dict[int, str] = {}
    labelled: list[tuple[str, str]] = []

    for message in context:
        label = labels.get(message.sender_id)
        if label is None:
            label = _label_for_index(len(labels))
            labels[message.sender_id] = label
        labelled.append((label, message.text))

    candidate_label = labels.get(candidate_sender_id)
    if candidate_label is None:
        candidate_label = _label_for_index(len(labels))

    return labelled, candidate_label


__all__ = ["LABEL_ALPHABET", "label_speakers"]

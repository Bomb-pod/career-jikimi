"""라벨 데이터셋 평가기 — 키 없이 검증되는 부분.

**모델 호출은 여기서 테스트하지 않는다.** `call_model()`의 재시도·예산·실패 분류는
`test_client.py`가 이미 덮고, 이 파일이 검증하는 것은 그 앞뒤다 — CSV를 문맥으로
바꾸는 파싱, 표본 균형, 혼동행렬 산술.

**이 셋이 틀리면 지표가 조용히 거짓이 된다.** 호출이 실패하면 눈에 보이지만,
표본이 한쪽 라벨로 쏠리거나 혼동행렬의 축이 뒤바뀌면 그럴듯한 숫자가 나온다.

대응: FR-7.5 (라벨 데이터셋으로 recall 산출).
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.judgment.evaluate import (
    LABEL_APPROPRIATE,
    LABEL_INAPPROPRIATE,
    Confusion,
    Outcome,
    Sample,
    confusion_at,
    load_samples,
    parse_history,
)
from app.judgment.types import ContextMessage


# --------------------------------------------------------------------------
# 문맥 파싱
# --------------------------------------------------------------------------
def test_history_lines_become_context_in_order() -> None:
    """`화자: 텍스트` 줄이 순서대로 문맥이 된다. `seq`는 1부터 오름차순이다."""
    context, _ = parse_history("선임: 첫 줄\n나: 둘째 줄\n선임: 셋째 줄")

    assert [message.text for message in context] == ["첫 줄", "둘째 줄", "셋째 줄"]
    assert [message.seq for message in context] == [1, 2, 3]


def test_the_same_speaker_keeps_one_id() -> None:
    """같은 화자 이름은 같은 id를 받는다 — 익명화가 A/B/A로 라벨하려면 필요하다."""
    context, _ = parse_history("선임: 가\n나: 나\n선임: 다")

    assert context[0].sender_id == context[2].sender_id
    assert context[0].sender_id != context[1].sender_id


def test_the_self_speaker_becomes_the_candidate_sender() -> None:
    """ "나"가 후보 발신자다 — 데이터셋의 `response`가 그 사람이 보내려는 말이다."""
    context, sender = parse_history("선임: 가\n나: 나")

    assert sender == context[1].sender_id


def test_a_context_without_the_self_speaker_gets_a_fresh_id() -> None:
    """ "나"가 없으면 문맥에 없는 새 id를 준다.

    익명화가 그 id에 새 라벨(C 등)을 붙인다 — 기존 화자 중 하나로 접으면 후보가
    누군가의 발언인 것처럼 읽힌다.
    """
    context, sender = parse_history("A선배: 가\nB동료: 나")

    assert sender not in {message.sender_id for message in context}


def test_a_continuation_line_joins_the_previous_message() -> None:
    """`화자:` 구분자가 없는 줄은 앞 화자의 이어지는 말로 붙인다.

    버리면 문맥이 끊기고, 새 화자로 두면 화자 수가 부풀려져 익명화 라벨이 어긋난다.
    """
    context, _ = parse_history("나: 첫 줄\n이어지는 줄")

    assert len(context) == 1
    assert context[0].text == "첫 줄\n이어지는 줄"


def test_blank_lines_are_dropped() -> None:
    """빈 줄은 무시한다 — 턴 수를 부풀리면 콜드스타트 판정이 흐려진다."""
    context, _ = parse_history("나: 가\n\n\n선임: 나\n")

    assert len(context) == 2


def test_an_empty_history_yields_no_context() -> None:
    """빈 문맥은 판정 대상이 아니다 — 라이브에서도 `skipped_no_context`다."""
    context, _ = parse_history("")

    assert context == []


# --------------------------------------------------------------------------
# 표본 적재와 균형
# --------------------------------------------------------------------------
def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["no", "label", "history", "response"])
        writer.writeheader()
        writer.writerows(rows)


def _rows(inappropriate: int, appropriate: int) -> list[dict[str, str]]:
    """라벨별로 **뭉쳐서** 만든다 — 실제 데이터셋이 그렇게 정렬되어 있다."""
    rows: list[dict[str, str]] = []
    for index in range(inappropriate):
        rows.append(
            {
                "no": f"bad{index}",
                "label": LABEL_INAPPROPRIATE,
                "history": "선임: 가\n나: 나",
                "response": f"부적절 {index}",
            }
        )
    for index in range(appropriate):
        rows.append(
            {
                "no": f"good{index}",
                "label": LABEL_APPROPRIATE,
                "history": "선임: 가\n나: 나",
                "response": f"적절 {index}",
            }
        )
    return rows


def test_a_limited_sample_stays_balanced(tmp_path: Path) -> None:
    """**핵심 회귀 테스트다.** `--limit`이 한쪽 라벨만 뽑으면 안 된다.

    CSV가 라벨별로 뭉쳐 있어 단순히 앞에서 자르면 `--limit 3`이 한 라벨 3개를 준다.
    그러면 혼동행렬의 한 축이 비어 precision이나 recall이 산출 불가가 되고, 사용자는
    "지표가 안 나온다"만 보고 원인을 모른다.
    """
    csv_path = tmp_path / "d.csv"
    _write_csv(csv_path, _rows(inappropriate=20, appropriate=20))

    samples = load_samples(csv_path, limit=6)

    assert len(samples) == 6
    assert sum(1 for s in samples if s.is_inappropriate) == 3


def test_limit_zero_loads_everything(tmp_path: Path) -> None:
    csv_path = tmp_path / "d.csv"
    _write_csv(csv_path, _rows(inappropriate=7, appropriate=5))

    samples = load_samples(csv_path, limit=0)

    assert len(samples) == 12


def test_sampling_is_deterministic(tmp_path: Path) -> None:
    """같은 `--limit`은 매번 같은 표본을 준다.

    무작위 표집이면 프롬프트를 고친 전후를 비교할 수 없다 — 점수 차이가 프롬프트
    때문인지 표본 때문인지 가릴 수 없다.
    """
    csv_path = tmp_path / "d.csv"
    _write_csv(csv_path, _rows(inappropriate=20, appropriate=20))

    first = [s.no for s in load_samples(csv_path, limit=8)]
    second = [s.no for s in load_samples(csv_path, limit=8)]

    assert first == second


def test_an_uneven_label_split_still_fills_the_limit(tmp_path: Path) -> None:
    """한쪽 라벨이 부족하면 남은 쪽으로 채운다 — 경계 사례.

    번갈아 뽑다 한쪽이 소진되면 멈추는 구현이면 `--limit`보다 적게 나온다.
    """
    csv_path = tmp_path / "d.csv"
    _write_csv(csv_path, _rows(inappropriate=2, appropriate=10))

    samples = load_samples(csv_path, limit=8)

    assert len(samples) == 8
    assert sum(1 for s in samples if s.is_inappropriate) == 2


def test_rows_without_a_usable_label_are_skipped(tmp_path: Path) -> None:
    """라벨이 없거나 모르는 값인 행은 버린다."""
    csv_path = tmp_path / "d.csv"
    rows = _rows(inappropriate=1, appropriate=1)
    rows.append({"no": "x", "label": "", "history": "나: 가", "response": "무"})
    rows.append({"no": "y", "label": "애매", "history": "나: 가", "response": "무"})
    _write_csv(csv_path, rows)

    samples = load_samples(csv_path, limit=0)

    assert len(samples) == 2


def test_rows_without_a_response_or_history_are_skipped(tmp_path: Path) -> None:
    """판정할 문장이나 문맥이 없으면 표본이 아니다."""
    csv_path = tmp_path / "d.csv"
    _write_csv(
        csv_path,
        [
            {"no": "1", "label": LABEL_APPROPRIATE, "history": "나: 가", "response": ""},
            {"no": "2", "label": LABEL_APPROPRIATE, "history": "", "response": "있음"},
            {"no": "3", "label": LABEL_APPROPRIATE, "history": "나: 가", "response": "있음"},
        ],
    )

    samples = load_samples(csv_path, limit=0)

    assert [s.no for s in samples] == ["3"]


# --------------------------------------------------------------------------
# 혼동행렬 — 축이 뒤바뀌면 그럴듯한 거짓 숫자가 나온다
# --------------------------------------------------------------------------
def _outcome(label: str, score: float) -> Outcome:
    sample = Sample(
        no="n",
        label=label,
        context=[ContextMessage(sender_id=1, text="가", seq=1)],
        candidate_sender_id=1,
        candidate_text="나",
        difficulty="-",
    )
    return Outcome(sample, True, score, 100, 10, 1, None)


def test_inappropriate_is_the_positive_class() -> None:
    """부적절이 양성이다 — 모델이 잡아야 하는 쪽이다.

    축이 뒤바뀌면 precision과 recall이 서로 자리를 바꿔 계산되고, 숫자는 그럴듯하게
    나오면서 해석이 정반대가 된다.
    """
    scored = [
        _outcome(LABEL_INAPPROPRIATE, 0.9),  # 잡았다 → TP
        _outcome(LABEL_INAPPROPRIATE, 0.1),  # 놓쳤다 → FN
        _outcome(LABEL_APPROPRIATE, 0.9),  # 오탐 → FP
        _outcome(LABEL_APPROPRIATE, 0.1),  # 맞게 통과 → TN
    ]

    matrix = confusion_at(scored, 0.7)

    assert (matrix.tp, matrix.fn, matrix.fp, matrix.tn) == (1, 1, 1, 1)


def test_the_threshold_boundary_counts_as_inappropriate() -> None:
    """`score == threshold`는 부적절이다 — BR-6.5의 `>=`."""
    matrix = confusion_at([_outcome(LABEL_INAPPROPRIATE, 0.7)], 0.7)

    assert matrix.tp == 1


def test_metrics_are_computed_from_the_matrix() -> None:
    matrix = Confusion(tp=7, fp=3, fn=2, tn=8)

    assert matrix.precision == 0.7
    assert matrix.recall == 7 / 9
    assert matrix.accuracy == 0.75
    assert matrix.f1 is not None


def test_precision_with_no_positive_predictions_is_unavailable() -> None:
    """부적절이라 한 건이 없으면 precision은 **`None`이지 0.0이 아니다.**

    0.0으로 표시하면 "성능이 나쁘다"로 읽힌다. 라이브 지표가 같은 규칙을 쓴다 (BR-7.3).
    """
    matrix = Confusion(tp=0, fp=0, fn=5, tn=5)

    assert matrix.precision is None
    assert matrix.f1 is None


def test_recall_with_no_actual_positives_is_unavailable() -> None:
    """실제 부적절이 없으면 recall도 `None`이다 — 균형 표집이 막으려는 상태다."""
    matrix = Confusion(tp=0, fp=3, fn=0, tn=7)

    assert matrix.recall is None


def test_a_failed_call_does_not_enter_the_matrix() -> None:
    """점수가 없는 표본은 세지 않는다 — 호출 실패가 지표를 오염시키면 안 된다."""
    failed = Outcome(
        _outcome(LABEL_INAPPROPRIATE, 0.9).sample, False, None, 4000, None, None, "timeout"
    )

    matrix = confusion_at([_outcome(LABEL_INAPPROPRIATE, 0.9), failed], 0.7)

    assert (matrix.tp, matrix.fp, matrix.fn, matrix.tn) == (1, 0, 0, 0)

"""라벨 데이터셋으로 판정 품질을 오프라인 평가한다 — `python -m app.judgment.evaluate`.

**이 도구가 존재하는 이유** — `requirements.md` FR-7.5가 라이브 지표에서 recall을
"산출 불가"로 못박았다. 사용자 피드백은 모델이 부적절이라 판정한 건에서만 나오므로
(팝업이 뜨니까) **놓친 오발송의 모수를 알 수 없다.** 그 판단은 라이브 로그에 대해
지금도 옳다.

라벨 데이터셋은 그 제약을 우회한다. 정답이 미리 붙어 있으므로 **모수를 안다** —
recall·F1·혼동행렬이 전부 계산된다. FR-7.5가 "라벨 데이터셋(트랙 2)이 있어야
한다"고 적은 것이 정확히 이 경로다.

`compute_metrics()`(라이브)와 이 파일(오프라인)은 **다른 질문에 답한다:**

| | 무엇을 재는가 | recall |
|---|---|---|
| `report` | 실사용 중 사용자가 어떻게 반응했는가 | 산출 불가 |
| `evaluate` | 모델이 정답 라벨을 맞히는가 | **산출 가능** |

## 프롬프트를 두 벌로 만들지 않는다

`prompt.build_messages()`와 `client.call_model()`을 그대로 쓴다 — 판정 경로와
**같은 함수다.** 평가용 프롬프트를 따로 두면 평가 점수가 실제 동작을 대변하지
않는다.

**DB에 쓰지 않는다.** `judge()`를 쓰지 않는 이유가 그것이다 — 그 함수는
`judgment_logs`에 행을 남기고(BR-6.8) 세션을 요구한다. 평가는 실험이므로 실사용
지표를 오염시켜서는 안 된다.

## 임계값 스윕

`ASM-3`이 "임계값은 실사용 로그를 보고 조정할 값이지 이론적으로 도출할 값이
아니다"라고 적었다. 이 도구가 그 조정을 데이터로 한다 — 0.05 간격으로 훑어
F1이 가장 높은 지점을 찾고, 현재 설정값과 나란히 보여준다.

대응: FR-7.5, ASM-3, ASM-7, ADR-005.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.judgment.client import call_model
from app.judgment.constants import use_utf8_console
from app.judgment.prompt import build_messages
from app.judgment.types import ContextMessage

#: 데이터셋의 라벨 값. `부적절`이 양성(positive)이다 — 모델이 잡아야 하는 쪽이다.
LABEL_INAPPROPRIATE = "부적절"
LABEL_APPROPRIATE = "적절"

#: 문맥에서 "나"로 표기된 화자. 후보 문장의 발신자로 본다.
SELF_SPEAKER = "나"

#: 동시 호출 수. 올리면 빨라지지만 rate limit에 걸린다.
DEFAULT_CONCURRENCY = 4

#: 기본 표본 수. 0이면 전량. 첫 실행을 싸게 만들려고 전량이 아니다.
DEFAULT_LIMIT = 100

#: 임계값 스윕 간격.
SWEEP_STEP = 0.05

#: gpt-4o-mini 기준 100만 토큰당 달러. 비용 추정에만 쓰며 정확한 청구액이 아니다.
COST_PER_MTOK_INPUT = 0.15
COST_PER_MTOK_OUTPUT = 0.60

#: 기본 데이터셋. **`__file__` 기준으로 잡는다** — `backend/`에서 돌려야 `app`
#: 모듈이 해석되는데 데이터셋은 저장소 루트에 있어, cwd 기준 상대 경로로 두면
#: 한쪽에서만 동작한다. 컨테이너 안에서는 `dataset/`이 이미지에 없으므로
#: `--csv`로 명시하거나 호스트에서 돌린다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CSV = _REPO_ROOT / "dataset" / "dialogue_context_dataset_v25_combined.csv"


@dataclass(frozen=True)
class Sample:
    """평가 대상 한 줄."""

    no: str
    label: str
    context: list[ContextMessage]
    candidate_sender_id: int
    candidate_text: str
    difficulty: str

    @property
    def is_inappropriate(self) -> bool:
        return self.label == LABEL_INAPPROPRIATE


@dataclass
class Outcome:
    """한 표본의 판정 결과."""

    sample: Sample
    ok: bool
    score: float | None
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    error: str | None


def parse_history(raw: str) -> tuple[list[ContextMessage], int]:
    """`화자: 텍스트` 여러 줄을 `ContextMessage` 목록으로 바꾼다.

    Returns:
        `(context, self_sender_id)`. `self_sender_id`는 "나"로 표기된 화자의 id이며,
        문맥에 "나"가 없으면 **문맥에 없는 새 id**를 준다(익명화가 새 라벨을 붙인다).

    화자 이름은 **id로만 바뀌고 프롬프트에 들어가지 않는다** (BR-6.2). 등장 순서대로
    1부터 배정하므로 `label_speakers()`가 A, B, C를 그 순서로 붙인다.
    """
    ids: dict[str, int] = {}
    context: list[ContextMessage] = []
    for seq, line in enumerate((ln.strip() for ln in raw.splitlines()), start=1):
        if not line:
            continue
        speaker, _, text = line.partition(":")
        if not text.strip():
            # `화자:` 구분자가 없는 줄이다. 앞 화자의 이어지는 말로 본다 —
            # 버리면 문맥이 끊기고, 새 화자로 두면 화자 수가 부풀려진다.
            if context:
                previous = context[-1]
                context[-1] = ContextMessage(
                    sender_id=previous.sender_id,
                    text=f"{previous.text}\n{line}",
                    seq=previous.seq,
                )
            continue
        name = speaker.strip()
        ids.setdefault(name, len(ids) + 1)
        context.append(ContextMessage(sender_id=ids[name], text=text.strip(), seq=seq))

    self_id = ids.get(SELF_SPEAKER, len(ids) + 1)
    return context, self_id


def load_samples(path: Path, limit: int) -> list[Sample]:
    """CSV를 읽어 표본 목록을 만든다. `limit`가 0이면 전량."""
    # `utf-8-sig` — 이 CSV들이 BOM으로 시작한다. `utf-8`로 읽으면 첫 컬럼명이
    # `﻿no`가 되어 DictReader의 키가 어긋난다.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    samples: list[Sample] = []
    for row in rows:
        label = (row.get("label") or "").strip()
        if label not in {LABEL_APPROPRIATE, LABEL_INAPPROPRIATE}:
            continue
        response = (row.get("response") or "").strip()
        if not response:
            continue
        context, self_id = parse_history(row.get("history") or "")
        if not context:
            # 문맥이 없으면 판정할 것이 없다 — 라이브에서도 `skipped_no_context`다.
            continue
        samples.append(
            Sample(
                no=(row.get("no") or "").strip(),
                label=label,
                context=context,
                candidate_sender_id=self_id,
                candidate_text=response,
                difficulty=(row.get("difficulty") or "").strip() or "-",
            )
        )

    if limit <= 0:
        return samples

    # **앞에서 잘라내지 않는다.** CSV가 라벨별로 뭉쳐 있어 `samples[:limit]`은
    # 한쪽 라벨만 뽑는다 — 실제로 `--limit 3`이 적절 3개를 줬다. 그러면 혼동행렬의
    # 한 축이 비어 precision이나 recall이 산출 불가가 되고 평가가 무의미해진다.
    #
    # 두 라벨에서 번갈아 뽑아 원본 비율(정확히 50:50)을 표본에서도 유지한다.
    # 무작위 표집을 쓰지 않는 이유 — 같은 `--limit`이 매번 같은 표본을 줘야
    # 프롬프트를 고친 전후를 비교할 수 있다.
    inappropriate = [s for s in samples if s.is_inappropriate]
    appropriate = [s for s in samples if not s.is_inappropriate]
    balanced: list[Sample] = []
    for index in range(max(len(inappropriate), len(appropriate))):
        if len(balanced) >= limit:
            break
        if index < len(inappropriate):
            balanced.append(inappropriate[index])
        if len(balanced) < limit and index < len(appropriate):
            balanced.append(appropriate[index])
    return balanced


async def judge_one(sample: Sample, semaphore: asyncio.Semaphore) -> Outcome:
    """표본 하나를 판정한다. **예외를 밖으로 내보내지 않는다.**

    `call_model()`이 이미 실패를 반환값으로 다루므로(BR-6.7) 여기서 잡을 것은
    프롬프트 조립 단계의 오류뿐이다.
    """
    async with semaphore:
        try:
            messages = build_messages(
                sample.context, sample.candidate_sender_id, sample.candidate_text
            )
        except Exception as caught:  # noqa: BLE001 - 한 표본의 실패가 전체를 멈추면 안 된다
            return Outcome(sample, False, None, 0, None, None, f"prompt: {caught}")

        call = await call_model(messages)
        return Outcome(
            sample=sample,
            ok=call.ok,
            score=call.score,
            latency_ms=call.latency_ms,
            prompt_tokens=call.prompt_tokens,
            completion_tokens=call.completion_tokens,
            error=call.error,
        )


@dataclass(frozen=True)
class Confusion:
    """한 임계값에서의 혼동행렬. `부적절`이 양성이다."""

    tp: int
    fp: int
    fn: int
    tn: int

    @property
    def precision(self) -> float | None:
        denominator = self.tp + self.fp
        return None if denominator == 0 else self.tp / denominator

    @property
    def recall(self) -> float | None:
        denominator = self.tp + self.fn
        return None if denominator == 0 else self.tp / denominator

    @property
    def f1(self) -> float | None:
        precision, recall = self.precision, self.recall
        if precision is None or recall is None or precision + recall == 0:
            return None
        return 2 * precision * recall / (precision + recall)

    @property
    def accuracy(self) -> float | None:
        total = self.tp + self.fp + self.fn + self.tn
        return None if total == 0 else (self.tp + self.tn) / total


def confusion_at(scored: list[Outcome], threshold: float) -> Confusion:
    """임계값 하나에서 혼동행렬을 센다. `score >= threshold`가 부적절 (BR-6.5)."""
    tp = fp = fn = tn = 0
    for outcome in scored:
        if outcome.score is None:
            # 호출자가 `ok and score is not None`으로 걸러 넘기므로 여기 오지 않는다.
            # 그래도 건너뛴다 — assert로 죽이면 평가 전체가 한 표본 때문에 멈춘다.
            continue
        predicted_inappropriate = outcome.score >= threshold
        if outcome.sample.is_inappropriate:
            if predicted_inappropriate:
                tp += 1
            else:
                fn += 1
        elif predicted_inappropriate:
            fp += 1
        else:
            tn += 1
    return Confusion(tp, fp, fn, tn)


def _pct(value: float | None) -> str:
    return "산출 불가" if value is None else f"{value:.3f}"


def _write_rows(path: Path, outcomes: list[Outcome], threshold: float) -> None:
    """표본별 결과를 CSV로 남긴다 — 토큰을 다시 쓰지 않고 재분석하기 위해서다."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["no", "label", "difficulty", "score", "predicted", "correct", "latency_ms", "error"]
        )
        for outcome in outcomes:
            predicted = (
                ""
                if outcome.score is None
                else (LABEL_INAPPROPRIATE if outcome.score >= threshold else LABEL_APPROPRIATE)
            )
            writer.writerow(
                [
                    outcome.sample.no,
                    outcome.sample.label,
                    outcome.sample.difficulty,
                    "" if outcome.score is None else f"{outcome.score:.3f}",
                    predicted,
                    "" if not predicted else str(predicted == outcome.sample.label),
                    outcome.latency_ms,
                    outcome.error or "",
                ]
            )


def report(outcomes: list[Outcome], threshold: float, sweep: bool) -> None:
    """결과를 표로 출력한다."""
    line = "─" * 62
    scored = [o for o in outcomes if o.ok and o.score is not None]
    failed = [o for o in outcomes if not o.ok or o.score is None]

    print()
    print(f"표본 {len(outcomes)}개  |  판정 성공 {len(scored)}  |  호출 실패 {len(failed)}")
    print(f"모델 {settings.OPENAI_MODEL}  |  임계값 {threshold}")
    print(line)

    if not scored:
        print("판정된 표본이 없어 지표를 낼 수 없다.")
        if failed:
            print(f"\n첫 실패 사유: {failed[0].error}")
        print(line)
        return

    matrix = confusion_at(scored, threshold)
    print("혼동행렬 (부적절 = 양성)")
    print(f"  TP {matrix.tp:5}   FP {matrix.fp:5}")
    print(f"  FN {matrix.fn:5}   TN {matrix.tn:5}")
    print()
    print(f"precision   {_pct(matrix.precision)}   부적절이라 한 것 중 맞은 비율")
    print(f"recall      {_pct(matrix.recall)}   실제 부적절 중 잡은 비율")
    print(f"F1          {_pct(matrix.f1)}")
    print(f"accuracy    {_pct(matrix.accuracy)}")
    print()
    print("**recall이 여기서는 산출된다.** 라벨이 모수를 주기 때문이다 —")
    print("라이브 지표(`report`)에서 산출 불가인 것은 그 모수를 모르기 때문이다 (FR-7.5).")

    # 점수 분포 — 두 라벨이 갈리는지가 프롬프트 품질의 핵심 신호다.
    print(line)
    print("점수 분포")
    for label in (LABEL_APPROPRIATE, LABEL_INAPPROPRIATE):
        scores = [o.score for o in scored if o.sample.label == label if o.score is not None]
        if not scores:
            continue
        print(
            f"  {label:4}  n={len(scores):4}  "
            f"평균 {statistics.fmean(scores):.3f}  "
            f"중앙 {statistics.median(scores):.3f}  "
            f"최소 {min(scores):.3f}  최대 {max(scores):.3f}"
        )
    appropriate = [o.score for o in scored if not o.sample.is_inappropriate if o.score is not None]
    inappropriate = [o.score for o in scored if o.sample.is_inappropriate if o.score is not None]
    if appropriate and inappropriate:
        gap = statistics.fmean(inappropriate) - statistics.fmean(appropriate)
        print(f"  평균 간격 {gap:+.3f}  ← 클수록 프롬프트가 두 라벨을 잘 가른다")
        if gap < 0.1:
            print("  ⚠ 간격이 좁다 — 점수 구간 설명이 분포를 벌리지 못하고 있다 (ASM-3)")

    # 난이도 슬라이스 — v2.5가 hard/medium/easy를 붙여둔 값어치가 여기서 나온다.
    slices = {o.sample.difficulty for o in scored}
    if slices - {"-"}:
        print(line)
        print("난이도별 recall")
        for name in ("hard", "medium", "easy"):
            subset = [o for o in scored if o.sample.difficulty == name]
            if not subset:
                continue
            sub = confusion_at(subset, threshold)
            print(f"  {name:6} n={len(subset):4}  recall {_pct(sub.recall)}  F1 {_pct(sub.f1)}")

    if sweep:
        print(line)
        print("임계값 스윕 — ASM-3이 데이터로 정하라고 한 값")
        best: tuple[float, float] | None = None
        step = int(round(1 / SWEEP_STEP))
        for index in range(1, step):
            candidate = round(index * SWEEP_STEP, 2)
            sub = confusion_at(scored, candidate)
            f1 = sub.f1
            if f1 is None:
                continue
            marker = "  <- 현재 설정" if abs(candidate - threshold) < 1e-9 else ""
            print(
                f"  {candidate:.2f}  precision {_pct(sub.precision)}  "
                f"recall {_pct(sub.recall)}  F1 {_pct(f1)}{marker}"
            )
            if best is None or f1 > best[1]:
                best = (candidate, f1)
        if best is not None:
            print(f"\n  F1이 가장 높은 임계값: {best[0]:.2f} (F1 {best[1]:.3f})")
            print("  precision을 우선하려면(FR-7.3의 방침) 이보다 높게 잡는다.")

    print(line)
    latencies = sorted(o.latency_ms for o in outcomes)
    if latencies:
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        print(
            f"지연  p50 {statistics.median(latencies) / 1000:.2f}s  "
            f"p95 {p95 / 1000:.2f}s  max {max(latencies) / 1000:.2f}s"
        )
        over = sum(1 for value in latencies if value > 5000)
        print(f"      NFR-1(정상 5초) 초과 {over}건 / {len(latencies)}")

    prompt_tokens = sum(o.prompt_tokens or 0 for o in outcomes)
    completion_tokens = sum(o.completion_tokens or 0 for o in outcomes)
    cost = (
        prompt_tokens / 1_000_000 * COST_PER_MTOK_INPUT
        + completion_tokens / 1_000_000 * COST_PER_MTOK_OUTPUT
    )
    print(f"토큰  프롬프트 {prompt_tokens:,}  응답 {completion_tokens:,}  (추정 ${cost:.4f})")

    if failed:
        print(line)
        print(f"호출 실패 {len(failed)}건 — 첫 사유: {failed[0].error}")

    print(line)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.judgment.evaluate",
        description=(
            "라벨 데이터셋으로 판정 품질을 평가한다. "
            "라이브 지표와 달리 recall이 산출된다 (FR-7.5)."
        ),
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_CSV,
        help="라벨 데이터셋. 기본값은 저장소의 v2.5 통합본 (744행)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"표본 수. 0이면 전량 (기본 {DEFAULT_LIMIT} — 첫 실행을 싸게)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help=f"판정 임계값. 기본은 AI_VERDICT_THRESHOLD({settings.AI_VERDICT_THRESHOLD})",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"동시 호출 수 (기본 {DEFAULT_CONCURRENCY}). 올리면 rate limit에 걸린다",
    )
    parser.add_argument(
        "--no-sweep",
        action="store_true",
        help="임계값 스윕을 생략한다",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="표본별 결과를 CSV로 남긴다 — 토큰을 다시 쓰지 않고 재분석하려면 지정한다",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="모델을 부르지 않고 표본 구성만 확인한다 (API 키 없이 파싱을 검증할 때)",
    )
    return parser


async def run(argv: list[str] | None = None) -> int:
    use_utf8_console()
    args = build_parser().parse_args(argv)
    threshold = settings.AI_VERDICT_THRESHOLD if args.threshold is None else args.threshold

    if not args.csv.is_file():
        print(f"데이터셋을 찾을 수 없다: {args.csv}", file=sys.stderr)
        print("컨테이너 안에서 돌리는 경우 dataset/이 이미지에 없을 수 있다 —", file=sys.stderr)
        print("호스트에서 `--csv dataset/...`로 돌리거나 볼륨으로 붙인다.", file=sys.stderr)
        return 1

    samples = load_samples(args.csv, args.limit)
    if not samples:
        print("평가할 표본이 없다. label/response/history 컬럼을 확인한다.", file=sys.stderr)
        return 1

    positives = sum(1 for s in samples if s.is_inappropriate)
    print(f"표본 {len(samples)}개  (부적절 {positives} / 적절 {len(samples) - positives})")

    if args.dry_run:
        print("\n--dry-run — 모델을 부르지 않는다. 첫 표본의 구성:")
        first = samples[0]
        print(f"  라벨 {first.label}  난이도 {first.difficulty}")
        print(f"  문맥 {len(first.context)}턴, 화자 {len({m.sender_id for m in first.context})}명")
        print(f"  후보 발신자 id {first.candidate_sender_id}")
        for message in build_messages(
            first.context, first.candidate_sender_id, first.candidate_text
        ):
            print(f"\n--- {message['role']} ---")
            print(message["content"])
        return 0

    started = time.monotonic()
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    outcomes = await asyncio.gather(*(judge_one(sample, semaphore) for sample in samples))
    elapsed = time.monotonic() - started

    report(list(outcomes), threshold, sweep=not args.no_sweep)
    print(f"총 소요 {elapsed:.1f}s (동시 {args.concurrency})")

    if args.out is not None:
        _write_rows(args.out, list(outcomes), threshold)
        print(f"표본별 결과: {args.out}")

    return 0


def main() -> int:
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())

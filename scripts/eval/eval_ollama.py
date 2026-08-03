#!/usr/bin/env python3
"""Ollama 로컬 LLM(qwen3.5:4b 등)을 라벨 데이터셋으로 평가한다 — 독립 실행 스크립트.

`eval_testset.py`(인코더 계측용)의 LLM 버전이다. 같은 CSV, 같은 익명화 규칙,
같은 지표(정확도·precision·recall·F1·팝업률·지연)를 내므로 두 결과를 나란히
놓고 비교할 수 있다.

프롬프트는 운영 경로의 단일 출처(`backend/app/judgment/prompt.py`)를 **그대로
import** 한다. 문안을 복사해두면 두 벌이 되어 측정과 운영이 어긋난다.

사용 (프로젝트 루트에서, backend/.venv 의 python으로):

    # 1) Ollama 기동 + 모델 준비:  ollama pull qwen3.5:4b
    # 2) 실행
    backend/.venv/Scripts/python.exe scripts/eval/eval_ollama.py ^
        --csv dataset/test_dataset_100.csv --model qwen3.5:4b ^
        --out benchmark_out/ollama_qwen35_4b_test100.csv

입력 CSV 규격 (학습 데이터와 동일)
    history   여러 줄. 각 줄이 "화자: 내용"
    response  보내려는 메시지 한 줄
    label     "적절" | "부적절"

주의
    - LLM은 건당 수 초가 걸릴 수 있다. 100행 × 수 초 = 수 분~수십 분.
      먼저 `--limit 10`으로 소요 시간을 가늠할 것.
    - 순차 1건씩 호출한다 — 병렬로 던지면 Ollama가 큐잉해 건당 지연이
      실사용과 달라진다. 측정 목적이므로 순차가 맞다.
    - 첫 요청은 모델 로딩이 섞인다. 워밍업 1회를 지표에서 뺀다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path


# ── 프로젝트 모듈 부트스트랩 (check_local_llm.py와 같은 방식) ─────────────
def _bootstrap_path() -> str | None:
    here = Path(__file__).resolve().parent
    for base in [Path.cwd(), *Path.cwd().parents, here, *here.parents]:
        for cand in (base, base / "backend"):
            if (cand / "app" / "judgment" / "prompt.py").exists():
                if str(cand) not in sys.path:
                    sys.path.insert(0, str(cand))
                return str(cand)
    return None


_APP_ROOT = _bootstrap_path()

try:
    from app.judgment.constants import TEMPERATURE
    from app.judgment.prompt import (
        RESPONSE_FORMAT,
        SCORE_KEY,
        SYSTEM_PROMPT,
        build_user_message,
    )
except ImportError as exc:  # pragma: no cover
    print(f"[중단] 프로젝트 모듈을 못 찾았다: {exc}")
    print(f"       app 패키지 탐색 결과: {_APP_ROOT}")
    print("       프로젝트 루트나 backend/ 에서 실행할 것.")
    raise SystemExit(1)

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SPEAKER = re.compile(r"^([^:]{1,10}):\s*(.*)$")

#: json_object 폴백일 때 system 프롬프트 끝에 붙이는 한 줄.
#: strict 스키마가 없으므로 형태를 문장으로 못박는다 (check_local_llm.py [1-b]).
JSON_FALLBACK_SUFFIX = '\n\n## 출력 형식\n\n{"score": 0.0} 형태의 JSON으로만 답하십시오.'


# ── 입력 준비 ──────────────────────────────────────────────────────────
def anonymize_lines(history: str) -> list[tuple[str, str]]:
    """history를 (익명 라벨, 본문) 목록으로 바꾼다.

    규칙은 `eval_testset.anonymize` · 운영 `anonymize.label_speakers`와 같다:
    등장 순서대로 A, B, C…. 화자 접두어가 없는 줄은 직전 발화의 연속으로 본다.

    Returns:
        (labelled, seen) — seen은 원문 화자 → 라벨 맵 (후보 라벨 결정에 쓴다).
    """
    seen: dict[str, str] = {}
    out: list[tuple[str, str]] = []
    for line in str(history).replace("\r\n", "\n").split("\n"):
        mo = SPEAKER.match(line)
        if not mo:
            if out:
                out[-1] = (out[-1][0], out[-1][1] + "\n" + line)
            continue
        who, text = mo.group(1), mo.group(2)
        if who not in seen:
            seen[who] = ALPHABET[len(seen)] if len(seen) < 26 else f"S{len(seen)}"
        out.append((seen[who], text))
    anonymize_lines.last_seen = seen  # type: ignore[attr-defined]
    return out


def candidate_label_for(seen: dict[str, str]) -> str:
    """후보 문장(response)의 화자 라벨.

    이 데이터셋의 response는 "나"가 보내려는 메시지다. history에 "나"가
    등장했으면 그 라벨을 재사용하고(운영 규칙: 문맥에 이미 등장한 화자는 그때
    라벨), 없으면 다음 라벨을 새로 준다.
    """
    if "나" in seen:
        return seen["나"]
    return ALPHABET[len(seen)] if len(seen) < 26 else f"S{len(seen)}"


def load(csv_path: Path):
    import pandas as pd

    df = pd.read_csv(csv_path)
    missing = {"history", "response", "label"} - set(df.columns)
    if missing:
        sys.exit(f"[중단] 컬럼 누락: {sorted(missing)}")
    df = df.dropna(subset=["history", "response", "label"]).reset_index(drop=True)
    df["history"] = df["history"].astype(str)
    df["response"] = df["response"].astype(str)
    df["y"] = (df["label"].astype(str).str.strip() == "부적절").astype(int)
    return df


# ── Ollama 호출 ────────────────────────────────────────────────────────
def make_client(base_url: str, api_key: str):
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("[중단] openai 패키지가 없다. backend/.venv 의 python으로 실행할 것.")
    return OpenAI(base_url=base_url, api_key=api_key, max_retries=0)


def pick_format(client, model: str, messages, timeout: float) -> tuple[dict, bool]:
    """strict json_schema를 받아주는지 1회 시험하고, 안 되면 json_object 폴백.

    Returns:
        (response_format, fallback 여부)
    """
    try:
        r = client.chat.completions.create(
            model=model, messages=messages,
            response_format=RESPONSE_FORMAT, temperature=TEMPERATURE, timeout=timeout,
        )
        json.loads(r.choices[0].message.content or "")[SCORE_KEY]
        return RESPONSE_FORMAT, False
    except Exception as exc:  # noqa: BLE001
        print(f"[안내] strict json_schema 거절 ({type(exc).__name__}) → json_object 폴백")
        return {"type": "json_object"}, True


def judge_one(client, model: str, messages, fmt: dict, timeout: float,
              retries: int) -> tuple[float | None, float, str]:
    """한 건 판정. (score | None, 지연 ms, 오류 문자열) 반환. 재시도 1회는 운영과 동일."""
    last_err = ""
    for _ in range(retries + 1):
        t0 = time.perf_counter()
        try:
            r = client.chat.completions.create(
                model=model, messages=messages,
                response_format=fmt, temperature=TEMPERATURE, timeout=timeout,
            )
            ms = (time.perf_counter() - t0) * 1000
            raw = json.loads(r.choices[0].message.content or "")
            score = float(raw[SCORE_KEY])
            return max(0.0, min(1.0, score)), ms, ""
        except Exception as exc:  # noqa: BLE001
            ms = (time.perf_counter() - t0) * 1000
            last_err = f"{type(exc).__name__}: {str(exc)[:80]}"
    return None, ms, last_err


# ── 지표 (eval_testset.py와 동일 정의) ─────────────────────────────────
def confusion(y, p, thr: float) -> dict:
    import numpy as np

    y = np.asarray(y)
    p = np.asarray(p)
    pred = (p > thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "accuracy": (tp + tn) / len(y) if len(y) else None,
            "precision": prec, "recall": rec, "f1": f1,
            "flag_rate": float(pred.mean()) if len(y) else None}


def fmt_v(v) -> str:
    return "  —  " if v is None else f"{v:.3f}"


# ── 진입점 ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="Ollama LLM을 라벨 CSV로 평가한다")
    ap.add_argument("--csv", type=Path, default=Path("dataset/test_dataset_100.csv"))
    ap.add_argument("--model", default="qwen3.5:4b", help="Ollama 모델 태그")
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--api-key", default="ollama", help="Ollama는 무시하지만 SDK가 요구한다")
    ap.add_argument("--threshold", type=float, default=0.7,
                    help="판정 임계값. 백엔드별 분리 원칙에 따라 인코더 값과 별개다")
    ap.add_argument("--timeout", type=float, default=30.0,
                    help="건당 타임아웃(초). 계측용이라 운영값(4초)보다 넉넉히")
    ap.add_argument("--retries", type=int, default=1, help="실패 시 재시도 횟수 (운영과 동일: 1)")
    ap.add_argument("--limit", type=int, default=None, help="앞에서 N행만 (소요 시간 가늠용)")
    ap.add_argument("--out", type=Path, default=None, help="표본별 점수·지연을 CSV로 저장")
    a = ap.parse_args()

    import numpy as np

    if not a.csv.exists():
        sys.exit(f"[중단] CSV가 없습니다: {a.csv}")

    df = load(a.csv)
    if a.limit:
        df = df.head(a.limit).copy()

    client = make_client(a.base_url, a.api_key)

    # 메시지 사전 조립 (운영 프롬프트 단일 출처 사용)
    all_msgs = []
    for _, row in df.iterrows():
        labelled = anonymize_lines(row["history"])
        seen = getattr(anonymize_lines, "last_seen", {})
        cand = candidate_label_for(seen)
        user_msg = build_user_message(labelled, cand, row["response"])
        all_msgs.append(user_msg)

    print(f"CSV        {a.csv}  ({len(df)}행 · 부적절 {int(df['y'].sum())} / 적절 {int((1 - df['y']).sum())})")
    print(f"엔드포인트 {a.base_url}")
    print(f"모델       {a.model} · threshold {a.threshold:.2f} · timeout {a.timeout:.0f}s · 재시도 {a.retries}")

    def msgs_for(i: int, system: str):
        return [{"role": "system", "content": system},
                {"role": "user", "content": all_msgs[i]}]

    # 형식 결정 + 워밍업 (모델 로딩이 섞인 첫 요청은 지표에서 뺀다)
    print("\n[준비] 응답 형식 확인 + 워밍업 …")
    t0 = time.perf_counter()
    fmt, fallback = pick_format(client, a.model, msgs_for(0, SYSTEM_PROMPT), a.timeout)
    system = SYSTEM_PROMPT + (JSON_FALLBACK_SUFFIX if fallback else "")
    print(f"       형식 {'json_object(폴백)' if fallback else 'json_schema(strict)'} · "
          f"워밍업 {(time.perf_counter() - t0):.1f}s")

    # 본 측정 — 순차 1건씩
    scores: list[float | None] = []
    lats: list[float] = []
    errs: list[str] = []
    t_total = time.perf_counter()
    for i in range(len(df)):
        score, ms, err = judge_one(client, a.model, msgs_for(i, system), fmt, a.timeout, a.retries)
        scores.append(score)
        lats.append(ms)
        errs.append(err)
        if (i + 1) % 10 == 0 or i == len(df) - 1:
            done_lat = [m for s, m in zip(scores, lats) if s is not None]
            eta = (np.median(done_lat) / 1000 * (len(df) - i - 1)) if done_lat else 0
            print(f"  {i + 1:4d}/{len(df)}  중앙지연 {np.median(done_lat):6.0f}ms  남은 예상 {eta:5.0f}s")
    total_s = time.perf_counter() - t_total

    ok_mask = np.array([s is not None for s in scores])
    n_fail = int((~ok_mask).sum())
    y = df["y"].values[ok_mask]
    p = np.array([s for s in scores if s is not None])
    lat_ok = np.array(lats)[ok_mask]

    line = "=" * 68
    print(f"\n{line}\n{a.model} @ {a.csv.name} · threshold {a.threshold:.2f}"
          f" · 성공 {int(ok_mask.sum())} / 실패 {n_fail}\n{line}")

    if not len(p):
        sys.exit("[중단] 성공한 판정이 없다. Ollama 기동과 모델 태그를 확인할 것.")

    c = confusion(y, p, a.threshold)
    auc = None
    try:
        from sklearn.metrics import roc_auc_score
        if y.sum() and (1 - y).sum():
            auc = roc_auc_score(y, p)
    except ImportError:
        pass

    print(f"AUC        {fmt_v(auc)}")
    print(f"정확도     {fmt_v(c['accuracy'])}")
    print(f"precision  {fmt_v(c['precision'])}     ← 우선 지표")
    print(f"recall     {fmt_v(c['recall'])}")
    print(f"F1         {fmt_v(c['f1'])}")
    print(f"팝업률     {fmt_v(c['flag_rate'])}")
    print(f"\n혼동행렬        예측:적절  예측:부적절")
    print(f"  실제 적절     {c['tn']:8d} {c['fp']:11d}   <- false positive")
    print(f"  실제 부적절   {c['fn']:8d} {c['tp']:11d}")

    print(f"\n건당 응답속도 (워밍업 제외, 성공 {len(lat_ok)}건)")
    print(f"  p50 {np.percentile(lat_ok, 50):8.1f}ms | p95 {np.percentile(lat_ok, 95):8.1f}ms"
          f" | 평균 {lat_ok.mean():8.1f}ms | 최대 {lat_ok.max():8.1f}ms")
    print(f"  운영 타임아웃(4초) 초과: {int((lat_ok > 4000).sum())}건")
    print(f"\n총 응답속도")
    print(f"  전체 {total_s:.1f}s ({total_s / 60:.1f}분) · 처리율 {len(df) / total_s:.2f}건/s")

    # threshold 스윕 — LLM 점수 분포는 인코더와 다르므로 0.7이 최선이 아닐 수 있다
    print(f"\nthreshold 스윕")
    print(f"{'thr':>5} {'정확도':>8} {'precision':>10} {'recall':>8} {'F1':>7} {'팝업률':>8}")
    for t in np.arange(0.1, 1.0, 0.1):
        cc = confusion(y, p, t)
        print(f"{t:5.2f} {cc['accuracy']:8.3f} {fmt_v(cc['precision']):>10} "
              f"{fmt_v(cc['recall']):>8} {fmt_v(cc['f1']):>7} {cc['flag_rate']:8.3f}")

    if n_fail:
        print(f"\n[주의] 실패 {n_fail}건은 지표에서 제외했다. 첫 오류: "
              f"{next(e for e in errs if e)}")
    print(f"\n비교 상대(인코더)는 같은 CSV로: python scripts/eval/eval_testset.py --csv {a.csv}")
    print(line)

    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        res = df[["history", "response", "label", "y"]].copy()
        res["score"] = scores
        res["latency_ms"] = lats
        res["error"] = errs
        res["pred"] = [None if s is None else int(s > a.threshold) for s in scores]
        res["correct"] = [None if s is None else int(int(s > a.threshold) == yy)
                          for s, yy in zip(scores, df["y"])]
        res.to_csv(a.out, index=False, encoding="utf-8-sig")
        bad = sum(1 for v in res["correct"] if v == 0)
        print(f"저장: {a.out}  (오분류 {bad}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""파인튜닝 인코더를 라벨 데이터셋으로 평가한다 — 독립 실행 스크립트.

백엔드도 DB도 도커도 필요 없다. 모델 폴더와 CSV만 있으면 돈다.
Colab에서 학습 직후 바로 돌릴 수도 있고, 노트북에서는 아래처럼 부른다.

    !python eval_testset.py --csv test_dataset_100.csv --model context_checker

`app.judgment.evaluate`와의 차이 — 그쪽은 백엔드 설정·프롬프트 조립·판정 로그를
전부 거치는 운영 경로이고, 이쪽은 **모델만 떼어내 재는 계측용**이다. 대신
단일 요청 지연과 절제 실험, 기저율 보정을 함께 낸다.

입력 CSV 규격 (학습 데이터와 동일)
    history   여러 줄. 각 줄이 "화자: 내용"
    response  보내려는 메시지 한 줄
    label     "적절" | "부적절"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SPEAKER = re.compile(r"^([^:]{1,10}):\s*(.*)$")


# ── 입력 준비 ──────────────────────────────────────────────────────────
def anonymize(history: str) -> str:
    """화자 호칭을 등장 순서대로 A, B, C… 로 바꾼다.

    학습 파이프라인(노트북 §1)과 운영 경로(`app/judgment/anonymize.py`)가 쓰는
    규칙과 같다. **이걸 빼먹으면 학습 때와 입력 형식이 달라져 점수가 흔들린다.**
    """
    seen: dict[str, str] = {}
    out: list[str] = []
    for line in str(history).replace("\r\n", "\n").split("\n"):
        mo = SPEAKER.match(line)
        if not mo:
            out.append(line)
            continue
        who, text = mo.group(1), mo.group(2)
        if who not in seen:
            seen[who] = ALPHABET[len(seen)] if len(seen) < 26 else f"S{len(seen)}"
        out.append(f"{seen[who]}: {text}")
    return "\n".join(out)


def load(csv_path: Path, anon: bool) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    missing = {"history", "response", "label"} - set(df.columns)
    if missing:
        sys.exit(f"[중단] 컬럼 누락: {sorted(missing)}")
    df = df.dropna(subset=["history", "response", "label"]).reset_index(drop=True)
    df["history"] = df["history"].astype(str)
    df["response"] = df["response"].astype(str)
    if anon:
        df["history"] = df["history"].map(anonymize)
    df["y"] = (df["label"].astype(str).str.strip() == "부적절").astype(int)
    return df


# ── 모델 ───────────────────────────────────────────────────────────────
class Scorer:
    """부적절 확률을 낸다. 토큰화 규칙은 `local_encoder._infer`와 같아야 한다."""

    def __init__(self, model_dir: Path, max_len: int):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.max_len = max_len
        self.tok = AutoTokenizer.from_pretrained(str(model_dir))
        self.model = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model.to(self.device).eval()

    def score(self, hist: list[str], resp: list[str], batch: int = 32) -> np.ndarray:
        out = []
        for i in range(0, len(resp), batch):
            enc = self.tok(hist[i:i + batch], resp[i:i + batch],
                           truncation="only_first", max_length=self.max_len,
                           padding=True, return_tensors="pt").to(self.device)
            with self.torch.no_grad():
                lg = self.model(**enc).logits
            out.append(self.torch.softmax(lg.float(), -1)[:, 1].cpu().numpy())
        return np.concatenate(out)

    def score_one(self, hist: str, resp: str) -> float:
        return float(self.score([hist], [resp], batch=1)[0])


# ── 지표 ───────────────────────────────────────────────────────────────
def confusion(y: np.ndarray, p: np.ndarray, thr: float) -> dict:
    pred = (p > thr).astype(int)
    tp = int(((pred == 1) & (y == 1)).sum())
    fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum())
    tn = int(((pred == 0) & (y == 0)).sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = (2 * prec * rec / (prec + rec)) if prec and rec else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "accuracy": (tp + tn) / len(y), "precision": prec,
            "recall": rec, "f1": f1, "flag_rate": float(pred.mean())}


def fmt(v) -> str:
    return "  —  " if v is None else f"{v:.3f}"


def base_rate_precision(recall: float, fpr: float, base: float) -> float:
    """기저율이 base일 때의 precision. 50:50 평가셋 수치를 실사용으로 옮긴다."""
    tp = base * recall
    fp = (1 - base) * fpr
    return tp / (tp + fp) if tp + fp else 0.0


# ── 보고 ───────────────────────────────────────────────────────────────
def report(df: pd.DataFrame, p: np.ndarray, thr: float,
           abl: dict[str, np.ndarray], lat: list[float]) -> None:
    from sklearn.metrics import roc_auc_score

    y = df["y"].values
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    line = "=" * 68

    print(f"\n{line}\n표본  {len(df)}행 · 부적절 {n_pos} / 적절 {n_neg} · threshold {thr:.2f}\n{line}")

    c = confusion(y, p, thr)
    auc = roc_auc_score(y, p) if n_pos and n_neg else None
    print(f"AUC        {fmt(auc)}")
    print(f"정확도     {fmt(c['accuracy'])}")
    print(f"precision  {fmt(c['precision'])}     ← 우선 지표")
    print(f"recall     {fmt(c['recall'])}")
    print(f"F1         {fmt(c['f1'])}")
    print(f"팝업률     {fmt(c['flag_rate'])}")
    print(f"\n혼동행렬        예측:적절  예측:부적절")
    print(f"  실제 적절     {c['tn']:8d} {c['fp']:11d}   <- false positive")
    print(f"  실제 부적절   {c['fn']:8d} {c['tp']:11d}")

    # 점수 분포 — 두 집단이 갈라졌는지
    hi, lo = p[y == 1], p[y == 0]
    if len(hi) and len(lo):
        gap = hi.min() - lo.max()
        print(f"\n점수 분포")
        print(f"  부적절  중앙 {np.median(hi):.4f} | 최소 {hi.min():.4f} | 최대 {hi.max():.4f}")
        print(f"  적절    중앙 {np.median(lo):.4f} | 최소 {lo.min():.4f} | 최대 {lo.max():.4f}")
        if gap > 0:
            print(f"  두 집단 사이 빈 구간 {gap:.4f} — 이 폭 안이면 threshold를 어디에 둬도 같다")
        else:
            print(f"  두 집단이 {-gap:.4f}만큼 겹친다")

    # threshold 스윕
    print(f"\nthreshold 스윕")
    print(f"{'thr':>5} {'정확도':>8} {'precision':>10} {'recall':>8} {'F1':>7} {'팝업률':>8}")
    best_f1 = (None, -1.0)
    for t in np.arange(0.05, 1.00, 0.05):
        cc = confusion(y, p, t)
        if cc["f1"] and cc["f1"] > best_f1[1]:
            best_f1 = (t, cc["f1"])
        print(f"{t:5.2f} {cc['accuracy']:8.3f} {fmt(cc['precision']):>10} "
              f"{fmt(cc['recall']):>8} {fmt(cc['f1']):>7} {cc['flag_rate']:8.3f}")
    if best_f1[0] is not None:
        print(f"F1 최대: thr={best_f1[0]:.2f} (F1 {best_f1[1]:.3f})")

    # 절제 실험
    if abl:
        print(f"\n절제 실험 — 응답은 그대로 두고 문맥만 바꾼다")
        base_auc = auc
        for name, pa in abl.items():
            ca = confusion(y, pa, thr)
            aa = roc_auc_score(y, pa) if n_pos and n_neg else None
            d_auc = (aa - base_auc) if (aa is not None and base_auc is not None) else None
            print(f"  {name:9s} AUC {fmt(aa)} ({d_auc:+.3f})   정확도 {fmt(ca['accuracy'])} "
                  f"({ca['accuracy'] - c['accuracy']:+.3f})")
        drop = base_auc - roc_auc_score(y, abl["swapped"]) if "swapped" in abl else None
        if drop is not None:
            verdict = ("문맥 사용" if drop >= 0.20 else
                       "부분 사용" if drop >= 0.08 else "문맥 미사용")
            print(f"  → [{verdict}] swapped AUC 하락폭 {drop:+.3f}")

    # 지연
    if lat:
        a = np.array(lat)
        over = int((a > 4000).sum())
        print(f"\n단일 요청 지연 (한 건씩 순차 측정, 표본 {len(a)})")
        print(f"  p50 {np.percentile(a, 50):7.1f}ms | p95 {np.percentile(a, 95):7.1f}ms "
              f"| 최대 {a.max():7.1f}ms | 4초 초과 {over}건")

    # 기저율 보정 — 이 평가셋은 50:50이다
    if c["precision"] is not None and c["recall"]:
        fpr_point = c["fp"] / n_neg if n_neg else 0.0
        fpr_upper = fpr_point if c["fp"] else 3.0 / n_neg      # rule of three
        note = "" if c["fp"] else f" (FP 0건 → 95% 상한 3/{n_neg} 적용)"
        print(f"\n기저율 보정 — 이 평가셋은 50:50이다. 실사용 비율로 옮기면{note}")
        print(f"  가정 오탐률(FPR) {fpr_upper:.4f} · recall {c['recall']:.3f}")
        print(f"{'기저율':>8} {'precision':>11}")
        for b in (0.50, 0.10, 0.05, 0.01):
            print(f"{b:8.0%} {base_rate_precision(c['recall'], fpr_upper, b):11.3f}")
        print("  실사용 기저율은 judgment_logs.user_action이 쌓여야 확정된다.")
    print(line)


# ── 진입점 ─────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(description="파인튜닝 인코더를 라벨 CSV로 평가한다")
    ap.add_argument("--csv", type=Path, required=True, help="평가 데이터셋")
    ap.add_argument("--model", type=Path, default=Path("backend/models/context_checker"),
                    help="모델 디렉터리 (기본 backend/models/context_checker)")
    ap.add_argument("--threshold", type=float, default=None,
                    help="판정 임계값. 미지정 시 threshold.json → 없으면 0.7")
    ap.add_argument("--max-len", type=int, default=None,
                    help="토큰 최대 길이. 미지정 시 threshold.json → 없으면 384")
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--out", type=Path, default=None, help="표본별 점수를 CSV로 저장")
    ap.add_argument("--no-anonymize", action="store_true",
                    help="화자 익명화를 건너뛴다 (이미 A/B/C인 데이터)")
    ap.add_argument("--no-ablation", action="store_true", help="절제 실험 생략")
    ap.add_argument("--latency-samples", type=int, default=30,
                    help="단일 요청 지연을 몇 건 잴지 (0이면 생략)")
    a = ap.parse_args()

    if not a.csv.exists():
        sys.exit(f"[중단] CSV가 없습니다: {a.csv}")
    if not a.model.exists():
        sys.exit(f"[중단] 모델 디렉터리가 없습니다: {a.model}")

    # threshold.json이 있으면 학습 때 값을 그대로 따른다
    meta = {}
    tj = a.model / "threshold.json"
    if tj.exists():
        try:
            meta = json.loads(tj.read_text(encoding="utf-8"))
        except Exception as e:                                  # noqa: BLE001
            print(f"[주의] threshold.json을 읽지 못했습니다: {e}")
    thr = a.threshold if a.threshold is not None else float(meta.get("threshold", 0.7))
    max_len = a.max_len if a.max_len is not None else int(meta.get("max_len", 384))

    df = load(a.csv, anon=not a.no_anonymize)
    print(f"CSV      {a.csv}  ({len(df)}행)")
    print(f"모델     {a.model}")
    print(f"설정     threshold {thr:.2f} · max_len {max_len} · "
          f"익명화 {'off' if a.no_anonymize else 'on'}")

    sc = Scorer(a.model, max_len)
    print(f"장치     {sc.device}\n채점 중…")

    hist = df["history"].tolist()
    resp = df["response"].tolist()
    p = sc.score(hist, resp, a.batch)

    abl = {}
    if not a.no_ablation:
        print("절제 실험 채점 중…")
        abl["swapped"] = sc.score(list(np.roll(np.array(hist, dtype=object), 1)), resp, a.batch)
        abl["empty"] = sc.score([""] * len(resp), resp, a.batch)

    lat = []
    if a.latency_samples:
        n = min(a.latency_samples, len(df))
        print(f"단일 요청 지연 측정 중… ({n}건)")
        sc.score_one(hist[0], resp[0])                          # 워밍업
        for i in range(n):
            t0 = time.perf_counter()
            sc.score_one(hist[i], resp[i])
            lat.append((time.perf_counter() - t0) * 1000)

    report(df, p, thr, abl, lat)

    if a.out:
        res = df[["history", "response", "label", "y"]].copy()
        res["score"] = p
        res["pred"] = (p > thr).astype(int)
        res["correct"] = (res["pred"] == res["y"]).astype(int)
        for k, v in abl.items():
            res[f"score_{k}"] = v
        res.to_csv(a.out, index=False, encoding="utf-8-sig")
        print(f"저장: {a.out}  (오분류 {int((res['correct'] == 0).sum())}건)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

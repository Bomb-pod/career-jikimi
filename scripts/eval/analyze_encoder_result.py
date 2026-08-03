# -*- coding: utf-8 -*-
"""benchmark_out/encoder.csv 를 다시 읽어 threshold를 이 평가셋 기준으로 다시 고른다.

AUC가 1.000인데 정확도가 0.78이면 **모델이 아니라 threshold 문제다.**
완벽히 분리됐다는 뜻이므로 정확도 1.000을 주는 지점이 반드시 존재한다.

저장소 루트에서 실행한다 (기본 `--csv` 경로가 루트 기준이다).

    python scripts/eval/analyze_encoder_result.py --csv benchmark_out/encoder.csv
"""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="benchmark_out/encoder.csv")
    ap.add_argument("--current", type=float, default=None, help="현재 운영 threshold")
    args = ap.parse_args()

    d = pd.read_csv(args.csv)
    d = d[d["score"].notna()]
    y = d["y"].values if "y" in d else (d["label"].astype(str).str.strip() == "부적절").astype(int).values
    s = d["score"].values
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    print(f"{len(d)}행 | 부적절 {n_pos} / 적절 {n_neg}")

    print(f"\n점수 분포")
    for lab, name in [(1, "부적절"), (0, "적절  ")]:
        v = s[y == lab]
        print(f"  {name}  중앙 {np.median(v):.4f} | 최소 {v.min():.4f} | 최대 {v.max():.4f}")
    gap = s[y == 1].min() - s[y == 0].max()
    print(f"\n  두 집단 사이 간격: {gap:+.4f}"
          f"  {'← 완전히 분리됨. 이 사이 아무 값이나 threshold로 쓸 수 있다' if gap > 0 else '← 겹친다'}")

    print(f"\n{'thr':>6} {'정확도':>7} {'precision':>10} {'recall':>7} {'팝업률':>7} {'FP':>4} {'FN':>4}")
    rows = []
    grid = sorted(set(np.round(np.arange(0.01, 1.00, 0.01), 3)) | set(np.round(s, 4)))
    for t in grid:
        p = (s >= t).astype(int)
        tp = int(((p == 1) & (y == 1)).sum()); fp = int(((p == 1) & (y == 0)).sum())
        fn = int(((p == 0) & (y == 1)).sum())
        prec = tp / max(tp + fp, 1); rec = tp / max(n_pos, 1)
        rows.append({"thr": t, "acc": (p == y).mean(), "prec": prec, "rec": rec,
                     "flag": p.mean(), "fp": fp, "fn": fn})
    best_acc = max(rows, key=lambda r: r["acc"])
    for r in rows:
        if abs(r["thr"] * 100 - round(r["thr"] * 100)) < 1e-9 and round(r["thr"] * 100) % 5 == 0:
            print(f"{r['thr']:6.2f} {r['acc']:7.3f} {r['prec']:10.3f} {r['rec']:7.3f} "
                  f"{r['flag']:7.3f} {r['fp']:4d} {r['fn']:4d}")

    print(f"\n정확도 최대: thr={best_acc['thr']:.3f} → 정확도 {best_acc['acc']:.3f} "
          f"(precision {best_acc['prec']:.3f} / recall {best_acc['rec']:.3f} / FP {best_acc['fp']})")

    # precision 1.0을 지키면서 recall이 가장 높은 지점
    perfect = [r for r in rows if r["fp"] == 0]
    if perfect:
        b = max(perfect, key=lambda r: r["rec"])
        print(f"FP 0을 지키는 최대 recall: thr={b['thr']:.3f} → recall {b['rec']:.3f} "
              f"(정확도 {b['acc']:.3f} / 팝업률 {b['flag']:.3f})")

    if args.current is not None:
        cur = min(rows, key=lambda r: abs(r["thr"] - args.current))
        print(f"\n현재 threshold {args.current}: 정확도 {cur['acc']:.3f} / recall {cur['rec']:.3f} "
              f"→ 최적 대비 정확도 {best_acc['acc']-cur['acc']:+.3f}, recall {best_acc['rec']-cur['rec']:+.3f}")

    # FP=0 이라고 FPR이 0인 것은 아니다 (0/n 의 95% 상한 ≈ 3/n)
    cur_r = min(rows, key=lambda r: abs(r["thr"] - (args.current if args.current is not None else best_acc["thr"])))
    if cur_r["fp"] == 0:
        ub = 3.0 / n_neg
        print(f"\n[주의] 적절 {n_neg}건 중 FP가 0이지만 **FPR이 0인 것은 아니다.**")
        print(f"       0/{n_neg} 의 95% 상한은 약 {ub:.3f} 이다 (rule of three).")
        print(f"       실사용 기저율별 precision을 이 상한으로 다시 보면:")
        for base in (0.10, 0.05, 0.01):
            den = cur_r["rec"] * base + ub * (1 - base)
            print(f"         기저율 {int(base*100):>2}% : {cur_r['rec']*base/den:.3f}")
        print("       벤치마크가 찍은 prec@1% = 1.000 은 FPR=0 가정의 산물이라 믿으면 안 된다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""Ollama가 왜 느린지 가른다 — CPU 폴백인가, 추론 토큰인가.

저장소 루트에서 실행한다 (기본 `--csv` 경로가 루트 기준이다).

    python scripts/eval/diagnose_ollama.py --csv benchmark_out/main/ollama.csv
    python scripts/eval/diagnose_ollama.py --model qwen3.5:4b --live   # 직접 호출해서 재기
"""
from __future__ import annotations
import argparse, json, sys, time

def from_csv(path):
    import pandas as pd
    d = pd.read_csv(path)
    d = d[d["score"].notna()]
    if not len(d):
        print("성공한 행이 없다."); return
    ct = d["completion_tokens"].fillna(0)
    pt = d["prompt_tokens"].fillna(0)
    lat = d["latency_ms"].astype(float)
    print(f"{len(d)}건")
    print(f"  입력 토큰   중앙 {pt.median():.0f}")
    print(f"  출력 토큰   중앙 {ct.median():.0f} | 최대 {ct.max():.0f}")
    print(f"  지연        중앙 {lat.median():.0f}ms | p95 {lat.quantile(.95):.0f}ms")
    if ct.median() > 0:
        print(f"  토큰당      {lat.median()/max(ct.median(),1):.0f}ms")
    print()
    print("=" * 66)
    if ct.median() > 50:
        print("[추론 토큰] 출력이 50토큰을 넘는다. 필요한 건 {\"score\": 0.93} 뿐인데")
        print(f"            {ct.median():.0f}토큰을 쓰고 있다 — 생각 과정을 뱉는 중이다.")
        print("            → 아래 § 추론 끄기 참조. 지연이 몇 배 줄어든다.")
    elif lat.median() > 800:
        print("[느린 추론] 출력 토큰은 적은데 지연이 크다.")
        print("            → GPU에 안 올라갔을 가능성이 높다. `ollama ps` 로 확인할 것.")
    else:
        print("[정상] 출력 토큰도 지연도 예상 범위다.")
    print("=" * 66)


def live(model, base_url, n):
    from openai import OpenAI
    c = OpenAI(base_url=base_url, api_key="ollama", max_retries=0)
    msgs = [{"role": "system", "content": "숫자 하나만 JSON으로 답하십시오."},
            {"role": "user", "content": '{"score": 0.0} 형식으로 0.5를 답하십시오.'}]
    print(f"{model} — 짧은 요청 {n}회")
    for i in range(n):
        t0 = time.monotonic()
        r = c.chat.completions.create(model=model, messages=msgs, temperature=0, timeout=120)
        el = (time.monotonic() - t0) * 1000
        u = getattr(r, "usage", None)
        out = getattr(u, "completion_tokens", None)
        txt = (r.choices[0].message.content or "")[:60].replace("\n", " ")
        print(f"  {i+1}: {el:7.0f}ms | 출력 {out} 토큰 | {txt}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default=None)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--model", default="qwen3.5:4b")
    ap.add_argument("--base-url", default="http://localhost:11434/v1")
    ap.add_argument("--n", type=int, default=3)
    a = ap.parse_args()
    if a.csv:
        from_csv(a.csv)
    if a.live:
        live(a.model, a.base_url, a.n)
    if not a.csv and not a.live:
        ap.print_help()

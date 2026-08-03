# -*- coding: utf-8 -*-
"""세 가지 판정 방식을 같은 평가셋에 올려 비교한다.

    OpenAI API  /  Ollama 로컬 LLM  /  파인튜닝 인코더

**backend 디렉터리에서 실행한다** — 프롬프트를 `app.judgment.prompt`에서
가져오기 위해서다. 문안을 복사해두면 벤치마크와 운영이 갈라진다.

    cd backend
    .venv/Scripts/python.exe ../scripts/eval/benchmark_three.py --csv ../eval.csv --dry-run
    .venv/Scripts/python.exe ../scripts/eval/benchmark_three.py --csv ../eval.csv \
        --backends encoder,ollama,openai --limit 100

## 공정성을 위해 하는 것

1. **누출 검사** — 평가셋이 인코더 학습 데이터와 겹치면 인코더만 유리하다.
   `--train-csv`를 주면 겹치는 행을 세어 경고하고, `--exclude-overlap`으로 뺀다.
2. **같은 익명화** — 인코더는 학습 때 `A:/B:` 형식만 봤다. LLM도 운영에서
   같은 익명화를 거친다. 평가셋의 실제 호칭(`팀장:`)을 양쪽 모두에 대해
   같은 규칙으로 A/B/C로 바꾼다.
3. **같은 프롬프트** — 두 LLM 백엔드가 `prompt.build_messages()`를 공유한다.
4. **threshold 무관 지표 병기** — 세 방식의 점수 스케일이 다르므로 AUC를
   같이 본다. 정확도만 비교하면 threshold 운에 좌우된다.
5. **중간 저장** — 백엔드별 CSV로 남긴다. 한 백엔드가 죽어도 나머지는 산다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

def _bootstrap_path() -> str | None:
    """`app` 패키지가 있는 폴더를 sys.path에 넣는다.

    Python은 cwd가 아니라 **스크립트가 있는 폴더**를 sys.path[0]에 넣는다.
    그래서 `cd backend && python ../this.py` 로 실행하면 프로젝트 루트가 잡히고
    `app`(= backend/app)을 못 찾는다. cwd와 그 상위, 스크립트 폴더를 훑어
    `app/judgment/prompt.py`가 있는 곳을 찾아 넣는다.
    """
    import sys
    from pathlib import Path
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
    from app.judgment.prompt import RESPONSE_FORMAT, SCORE_KEY, build_messages
    from app.judgment.types import ContextMessage
except ImportError as exc:
    sys.exit(f"[중단] {exc}\n       app 패키지를 못 찾았다 (탐색 결과: {_APP_ROOT}).\n"
             "       backend/ 안에 app/judgment/prompt.py 가 있는지 확인할 것.")

LABEL_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
SPEAKER_RE = re.compile(r"^([^:]{1,12}):\s*(.*)$")


# ---------------------------------------------------------------- 데이터
def parse_history(text: str) -> list[tuple[str, str]]:
    """'팀장: 안녕\n나: 네' → [('팀장','안녕'), ('나','네')].

    화자 표기가 없는 줄은 직전 화자의 이어지는 줄로 붙인다 — 여러 줄 메시지다.
    """
    pairs: list[tuple[str, str]] = []
    for line in str(text).replace("\r\n", "\n").split("\n"):
        if not line.strip():
            continue
        m = SPEAKER_RE.match(line)
        if m:
            pairs.append([m.group(1).strip(), m.group(2)])
        elif pairs:
            pairs[-1][1] += "\n" + line
        else:
            pairs.append(["?", line])
    return [(a, b) for a, b in pairs]


def anonymized_history(pairs: list[tuple[str, str]]) -> str:
    """등장 순서대로 A,B,C… — `app.judgment.anonymize.label_speakers`와 같은 규칙."""
    seen: dict[str, str] = {}
    out = []
    for who, txt in pairs:
        if who not in seen:
            i = len(seen)
            seen[who] = LABEL_ALPHABET[i] if i < 26 else f"S{i}"
        out.append(f"{seen[who]}: {txt}")
    return "\n".join(out)


def to_context(pairs: list[tuple[str, str]]) -> tuple[list[ContextMessage], int]:
    """LLM 경로용. sender_id는 화자별 순번이고 프롬프트에는 안 실린다.

    후보 발신자는 '나'가 있으면 그 사람, 없으면 새 화자다 — 학습 데이터가
    '나:'를 응답자로 쓰는 관례를 따른다.
    """
    ids: dict[str, int] = {}
    ctx = []
    for i, (who, txt) in enumerate(pairs):
        ids.setdefault(who, len(ids))
        ctx.append(ContextMessage(sender_id=ids[who], text=txt, seq=i + 1))
    return ctx, ids.get("나", len(ids))


def load_eval(path: str, limit: int) -> pd.DataFrame:
    df = pd.read_csv(path)
    cols = {c.lower().strip(): c for c in df.columns}

    def pick(*names):
        for n in names:
            if n in cols:
                return cols[n]
        return None

    h, r, l = pick("history", "대화", "context"), pick("response", "응답", "candidate"), pick("label", "라벨", "정답")
    missing = [n for n, c in [("history", h), ("response", r), ("label", l)] if c is None]
    if missing:
        sys.exit(f"[중단] 컬럼을 못 찾았다: {missing}\n       있는 컬럼: {list(df.columns)}")

    out = pd.DataFrame({
        "history": df[h].astype(str),
        "response": df[r].astype(str),
        "label_raw": df[l].astype(str).str.strip(),
    })
    pid = pick("pair_id", "pair", "group")
    out["pair_id"] = df[pid].astype(str) if pid else [f"row{i}" for i in range(len(df))]
    for extra in ("reason", "difficulty", "scenario", "source", "source_type"):
        if extra in cols:
            out[extra] = df[cols[extra]].astype(str)

    vals = set(out["label_raw"])
    pos = {"부적절", "1", "inappropriate", "misdirected", "True"}
    if not (vals & pos):
        sys.exit(f"[중단] 라벨에서 '부적절'에 해당하는 값을 못 찾았다: {sorted(vals)[:8]}")
    out["y"] = out["label_raw"].isin(pos).astype(int)

    out = out.dropna(subset=["history", "response"]).reset_index(drop=True)
    if limit and limit < len(out):
        # 두 라벨에서 번갈아 뽑아 항상 균형을 맞춘다 — evaluate CLI와 같은 규칙이라
        # 같은 --limit이 매번 같은 표본을 준다.
        a = out[out.y == 1].index.tolist()
        b = out[out.y == 0].index.tolist()
        idx = [x for pair in zip(a, b) for x in pair][:limit]
        out = out.loc[sorted(idx)].reset_index(drop=True)
    return out


def check_overlap(ev: pd.DataFrame, train_csv: str | None) -> pd.Series:
    """평가셋이 인코더 학습 데이터와 겹치는지. 겹치면 인코더만 유리해진다."""
    if not train_csv or not Path(train_csv).exists():
        print("[주의] --train-csv 미지정 — 누출 검사를 건너뛴다.")
        print("       인코더 학습셋과 겹치면 인코더 점수만 부풀려진다.")
        return pd.Series(False, index=ev.index)

    tr = pd.read_csv(train_csv)
    tr_pair = set(zip(tr["history"].astype(str).str.strip(), tr["response"].astype(str).str.strip()))
    tr_resp = set(tr["response"].astype(str).str.strip())
    tr_hist = set(tr["history"].astype(str).str.strip())

    h = ev["history"].str.strip()
    r = ev["response"].str.strip()
    dup_pair = pd.Series(list(zip(h, r))).isin(tr_pair)
    print(f"\n=== 누출 검사 (vs {Path(train_csv).name}) ===")
    print(f"  (history, response) 완전 일치 : {dup_pair.sum():4d} / {len(ev)}")
    print(f"  response만 일치               : {r.isin(tr_resp).sum():4d} / {len(ev)}")
    print(f"  history만 일치                : {h.isin(tr_hist).sum():4d} / {len(ev)}")
    if dup_pair.sum():
        print("  [!] 겹치는 행이 있다. --exclude-overlap 으로 빼거나, 결과 해석 시 감안할 것.")
    return dup_pair


# ---------------------------------------------------------------- 백엔드
async def run_llm(ev, model, base_url, api_key, concurrency, timeout, extra_body=None):
    from openai import AsyncOpenAI

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=0)
    sem = asyncio.Semaphore(concurrency)
    res: list[dict] = [None] * len(ev)  # type: ignore

    async def one(i, row):
        ctx, sender = to_context(parse_history(row.history))
        messages = build_messages(context=ctx, candidate_sender_id=sender,
                                  candidate_text=row.response)
        async with sem:
            t0 = time.monotonic()
            try:
                kw = {}
                if extra_body:
                    # Ollama의 think/options 같은 비표준 필드를 그대로 얹는다.
                    # SDK가 모르는 키라도 본문에 실어 보낸다.
                    kw["extra_body"] = extra_body
                c = await client.chat.completions.create(
                    model=model, messages=messages, response_format=RESPONSE_FORMAT,
                    temperature=TEMPERATURE, timeout=timeout, **kw)
                score = float(json.loads(c.choices[0].message.content or "")[SCORE_KEY])
                u = getattr(c, "usage", None)
                res[i] = {"score": min(max(score, 0.0), 1.0),
                          "latency_ms": int((time.monotonic() - t0) * 1000),
                          "prompt_tokens": getattr(u, "prompt_tokens", None),
                          "completion_tokens": getattr(u, "completion_tokens", None),
                          "error": None}
            except Exception as exc:  # noqa: BLE001
                res[i] = {"score": None, "latency_ms": int((time.monotonic() - t0) * 1000),
                          "prompt_tokens": None, "completion_tokens": None,
                          "error": f"{type(exc).__name__}: {str(exc)[:90]}"}
        done = sum(x is not None for x in res)
        print(f"  {done}/{len(ev)}", end="\r")

    await asyncio.gather(*(one(i, row) for i, row in enumerate(ev.itertuples())))
    print()
    return res


def run_encoder(ev, model_dir, max_len):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(model_dir)
    mdl = AutoModelForSequenceClassification.from_pretrained(model_dir)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    mdl.to(dev).eval()
    print(f"  device={dev} | max_len={max_len}")

    # 인코더는 학습 때 익명화된 형식만 봤다. 평가셋도 같은 규칙으로 바꾼다.
    hists = [anonymized_history(parse_history(h)) for h in ev.history]
    res = []
    with torch.no_grad():
        for i in range(0, len(ev), 32):
            hb, rb = hists[i:i + 32], list(ev.response[i:i + 32])
            t0 = time.monotonic()
            e = tok(hb, rb, truncation="only_first", max_length=max_len,
                    padding=True, return_tensors="pt").to(dev)
            p = torch.softmax(mdl(**e).logits.float(), -1)[:, 1].cpu().numpy()
            per = int((time.monotonic() - t0) * 1000 / len(hb))
            n_tok = int(e["input_ids"].shape[1])
            res += [{"score": float(x), "latency_ms": per, "prompt_tokens": n_tok,
                     "completion_tokens": 0, "error": None} for x in p]
            print(f"  {len(res)}/{len(ev)}", end="\r")
    print()
    return res


# ---------------------------------------------------------------- 지표
def evaluate(name, ev, rows, threshold):
    from sklearn.metrics import (confusion_matrix, precision_score,
                                 recall_score, roc_auc_score)

    d = pd.DataFrame(rows)
    ok = d["score"].notna()
    n_fail = int((~ok).sum())
    y = ev.y.values[ok.values]
    s = d.loc[ok, "score"].values
    if len(y) == 0 or len(set(y)) < 2:
        print(f"[{name}] 유효 표본 부족 (성공 {len(y)} / 실패 {n_fail})")
        return None

    pred = (s >= threshold).astype(int)
    lat = d.loc[ok, "latency_ms"].astype(float).tolist()
    tp = int(((pred == 1) & (y == 1)).sum()); fp = int(((pred == 1) & (y == 0)).sum())
    fn = int(((pred == 0) & (y == 1)).sum()); tn = int(((pred == 0) & (y == 0)).sum())
    fpr = fp / max(tn + fp, 1)
    rec = recall_score(y, pred, zero_division=0)

    m = {
        "backend": name, "n": len(y), "실패": n_fail,
        "AUC": round(float(roc_auc_score(y, s)), 4),
        "threshold": threshold,
        "정확도": round(float((pred == y).mean()), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "recall": round(float(rec), 4),
        "팝업률": round(float(pred.mean()), 4),
        "FPR": round(float(fpr), 4),
        "p50_ms": int(statistics.median(lat)),
        "p95_ms": int(np.percentile(lat, 95)),
        "4초초과": int(sum(x > 4000 for x in lat)),
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "prompt_tokens": int(d.loc[ok, "prompt_tokens"].fillna(0).sum()),
    }
    # 기저율 보정 — 평가셋은 균형이지만 실사용은 아니다
    for base in (0.10, 0.05, 0.01):
        den = rec * base + fpr * (1 - base)
        m[f"prec@{int(base*100)}%"] = round(float(rec * base / den), 4) if den else 0.0
    return m



class _Tee:
    """콘솔에 그대로 찍으면서 동시에 버퍼에 쌓는다 — 리포트 파일용."""

    def __init__(self, stream, buf):
        self._s, self._b = stream, buf

    def write(self, text):
        self._s.write(text)
        # 진행 표시(\r로 덮어쓰는 줄)는 파일에 남기지 않는다
        if not text.endswith("\r"):
            self._b.append(text)

    def flush(self):
        self._s.flush()

    def isatty(self):
        return getattr(self._s, "isatty", lambda: False)()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True, help="평가 데이터셋")
    ap.add_argument("--backends", default="encoder,ollama,openai")
    ap.add_argument("--limit", type=int, default=0, help="0이면 전량")
    ap.add_argument("--train-csv", default="../dataset/training_dataset_v3_1000_simple.csv")
    ap.add_argument("--exclude-overlap", action="store_true", help="학습셋과 겹치는 행 제외")
    ap.add_argument("--model-dir", default="models/context_checker")
    ap.add_argument("--encoder-max-len", type=int, default=384)
    ap.add_argument("--encoder-threshold", type=float, default=None, help="기본: threshold.json")
    ap.add_argument("--openai-model", default="gpt-5.6-luna")
    ap.add_argument("--openai-key", default=None, help="기본: OPENAI_API_KEY 환경변수")
    ap.add_argument("--ollama-model", default="qwen3.5:4b")
    ap.add_argument("--ollama-url", default="http://localhost:11434/v1")
    ap.add_argument("--llm-threshold", type=float, default=0.7)
    ap.add_argument("--llm-extra-body", default=None,
                    help='요청 본문에 그대로 얹을 JSON. Ollama 예: '
                         '\'{"think": false, "options": {"num_ctx": 2048}}\'')
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--out", default="../benchmark_out")
    ap.add_argument("--dry-run", action="store_true", help="CSV만 검증하고 호출은 안 한다")
    ap.add_argument("--ablation", action="store_true",
                    help="history를 다른 행 것으로 바꿔 한 번 더 돌린다. LLM은 호출이 2배 든다")
    ap.add_argument("--slice-col", default=None,
                    help="이 컬럼 값별로 성능을 나눠 보고한다 (예: reason, difficulty)")
    args = ap.parse_args()
    extra_body = json.loads(args.llm_extra_body) if args.llm_extra_body else None

    import datetime, io
    buf: list[str] = []
    real_stdout = sys.stdout
    sys.stdout = _Tee(real_stdout, buf)  # type: ignore[assignment]
    started = datetime.datetime.now()
    print(f"benchmark_three  {started:%Y-%m-%d %H:%M:%S}")
    print(f"평가셋 {args.csv} | 백엔드 {args.backends} | limit {args.limit or '전량'}"
          f" | ablation {args.ablation}")

    ev = load_eval(args.csv, args.limit)
    print(f"평가셋 {len(ev)}행 | 부적절 {int(ev.y.sum())} / 적절 {int((1-ev.y).sum())}")

    dup = check_overlap(ev, args.train_csv)
    if args.exclude_overlap and dup.any():
        ev = ev[~dup.values].reset_index(drop=True)
        print(f"  → 겹치는 {int(dup.sum())}행 제외. 남은 {len(ev)}행")

    print("\n=== 파싱 확인 (첫 행) ===")
    pr = parse_history(ev.history.iloc[0])
    print(f"  화자 {len(pr)}턴: {[p[0] for p in pr]}")
    print(f"  익명화: {anonymized_history(pr)[:70]}...")
    print(f"  후보  : {ev.response.iloc[0][:50]}")
    if args.dry_run:
        print("\n--dry-run — 여기까지.")
        _write_report(Path(args.out), buf, None, args, started)
        sys.stdout = real_stdout
        return 0

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    metrics = []
    for be in [b.strip() for b in args.backends.split(",") if b.strip()]:
        print(f"\n=== {be} ===")
        t0 = time.time()
        try:
            if be == "encoder":
                thr = args.encoder_threshold
                if thr is None:
                    tj = Path(args.model_dir) / "threshold.json"
                    thr = json.loads(tj.read_text(encoding="utf-8"))["threshold"] if tj.exists() else 0.5
                    print(f"  threshold {thr} ({'threshold.json' if tj.exists() else '기본 0.5'})")
                rows = run_encoder(ev, args.model_dir, args.encoder_max_len)
            elif be == "ollama":
                thr = args.llm_threshold
                rows = asyncio.run(run_llm(ev, args.ollama_model, args.ollama_url,
                                           "ollama", args.concurrency, args.timeout, extra_body))
            elif be == "openai":
                import os
                key = args.openai_key or os.environ.get("OPENAI_API_KEY")
                if not key:
                    print("  건너뜀 — OPENAI_API_KEY 없음"); continue
                thr = args.llm_threshold
                rows = asyncio.run(run_llm(ev, args.openai_model, None, key,
                                           args.concurrency, args.timeout))
            else:
                print(f"  알 수 없는 백엔드: {be}"); continue
        except Exception as exc:  # noqa: BLE001
            print(f"  실패: {type(exc).__name__}: {exc}"); continue

        pd.concat([ev.reset_index(drop=True), pd.DataFrame(rows)], axis=1) \
          .to_csv(out / f"{be}.csv", index=False, encoding="utf-8-sig")
        m = evaluate(be, ev, rows, thr)
        if m:
            m["총소요_s"] = int(time.time() - t0)
            metrics.append(m)
            print(f"  AUC {m['AUC']:.3f} | precision {m['precision']:.3f} | "
                  f"recall {m['recall']:.3f} | p50 {m['p50_ms']}ms | 실패 {m['실패']}")
            _ct = pd.DataFrame(rows)["completion_tokens"].fillna(0)
            if len(_ct) and _ct.median() > 50:
                print(f"  [!] 출력 토큰 중앙값 {_ct.median():.0f} — 필요한 건 점수 하나뿐인데")
                print(f"      생각 과정을 뱉고 있다. --llm-extra-body '{{\"think\": false}}' 로 끌 것.")

        # 슬라이스별 — 평가셋에 reason/difficulty 같은 컬럼이 있을 때
        if args.slice_col and args.slice_col in ev.columns:
            print(f"\n  [{args.slice_col}별]")
            sc = pd.DataFrame(rows)["score"]
            for v, idx in ev.groupby(args.slice_col).groups.items():
                sub = ev.loc[idx]
                ss = sc.loc[idx]
                okm = ss.notna()
                if okm.sum() == 0:
                    continue
                p = (ss[okm] >= thr).astype(int).values
                yy = sub.y.values[okm.values]
                print(f"    {str(v):10s} n={okm.sum():3d}  정답률 {float((p==yy).mean()):.3f}"
                      f"  (실제 부적절 {int(yy.sum())})")

        # 절제 실험 — history를 한 칸 밀어 다른 행 문맥과 짝지운다.
        # 평가셋에 response-only 누출이 있으면 정확도만으로는 문맥 사용 여부를
        # 알 수 없다. 여기서 점수가 안 떨어지는 방식은 문맥을 안 보는 것이다.
        if args.ablation:
            print(f"\n  [절제] history 교체 후 재실행")
            ev_ab = ev.copy()
            ev_ab["history"] = np.roll(ev["history"].values, 1)
            try:
                if be == "encoder":
                    rows_ab = run_encoder(ev_ab, args.model_dir, args.encoder_max_len)
                elif be == "ollama":
                    rows_ab = asyncio.run(run_llm(ev_ab, args.ollama_model, args.ollama_url,
                                                  "ollama", args.concurrency, args.timeout, extra_body))
                else:
                    import os as _os
                    rows_ab = asyncio.run(run_llm(ev_ab, args.openai_model, None,
                                                  args.openai_key or _os.environ.get("OPENAI_API_KEY"),
                                                  args.concurrency, args.timeout))
                m_ab = evaluate(be + ":swapped", ev, rows_ab, thr)
                if m_ab and m:
                    # **판정은 AUC로 한다.** 정확도 하락폭은 threshold가 나쁘면
                    # 원래 정확도가 이미 깎여 있어 하락 여지가 줄고, 문맥 의존도를
                    # 실제보다 작게 보이게 한다. AUC는 threshold와 무관하다.
                    d_acc = m["정확도"] - m_ab["정확도"]
                    d_auc = m["AUC"] - m_ab["AUC"]
                    m["swapped_정확도"] = m_ab["정확도"]
                    m["swapped_AUC"] = m_ab["AUC"]
                    m["하락폭_정확도"] = round(float(d_acc), 4)
                    m["하락폭_AUC"] = round(float(d_auc), 4)
                    verdict = ("문맥 사용" if d_auc >= 0.25 else
                               "부분 사용" if d_auc >= 0.10 else "문맥 미사용")
                    print(f"    정확도 {m['정확도']:.3f} → {m_ab['정확도']:.3f} ({d_acc:+.3f})")
                    print(f"    AUC   {m['AUC']:.3f} → {m_ab['AUC']:.3f} ({d_auc:+.3f}) → [{verdict}]")
            except Exception as exc:  # noqa: BLE001
                print(f"    절제 실패: {type(exc).__name__}: {exc}")

    if not metrics:
        print("\n결과 없음.")
        _write_report(out, buf, None, args, started)
        sys.stdout = real_stdout
        return 1

    md = pd.DataFrame(metrics)
    print("\n" + "=" * 78)
    print(md[["backend", "n", "AUC", "정확도", "precision", "recall", "팝업률",
              "p50_ms", "p95_ms", "4초초과", "실패"]].to_string(index=False))
    if "하락폭_AUC" in md.columns:
        print("\n절제 실험 — history를 바꿔도 유지되면 문맥을 안 보는 것이다 (판정은 AUC 기준)")
        print(md[["backend", "AUC", "swapped_AUC", "하락폭_AUC",
                  "정확도", "swapped_정확도", "하락폭_정확도"]].to_string(index=False))
    print("\n실사용 기저율 보정 precision")
    print(md[["backend", "precision", "prec@10%", "prec@5%", "prec@1%"]].to_string(index=False))
    print("\n토큰 (누적 입력)")
    print(md[["backend", "prompt_tokens", "총소요_s"]].to_string(index=False))

    for _, r in md.iterrows():
        if r.get("FP", 1) == 0:
            n_neg = int(r["TN"]) + int(r["FP"])
            ub = 3.0 / max(n_neg, 1)
            print(f"\n[주의] {r['backend']}: 적절 {n_neg}건 중 FP가 0이라 FPR을 0으로 계산했다.")
            print(f"       0/{n_neg} 의 95% 상한은 약 {ub:.3f} (rule of three) —")
            print(f"       그 값으로 보면 prec@1% 는 "
                  f"{r['recall']*0.01/(r['recall']*0.01+ub*0.99):.3f} 까지 떨어진다.")
            print("       위 표의 prec@1% = 1.000 을 그대로 믿으면 안 된다.")

    md.to_csv(out / "comparison.csv", index=False, encoding="utf-8-sig")
    print(f"\n저장: {out}/  (백엔드별 행 단위 결과 + comparison.csv)")
    print("\n읽는 법")
    print("  · AUC가 threshold와 무관한 비교다. 정확도는 threshold 운이 섞인다.")
    print("  · precision이 우선 지표다 (README). 다만 평가셋이 균형이면 실사용보다 낙관적이다.")
    print("  · 4초초과 건수가 NFR-1 판단 근거다.")

    _write_report(out, buf, md, args, started)
    sys.stdout = real_stdout
    return 0



def _write_report(out, buf, md, args, started):
    """콘솔 전문(report.txt)과 요약(report.md)을 남긴다."""
    import datetime
    out.mkdir(parents=True, exist_ok=True)

    (out / "report.txt").write_text("".join(buf), encoding="utf-8")

    lines = [
        f"# 판정 성능 비교",
        "",
        f"- 실행: {started:%Y-%m-%d %H:%M}  (소요 {(datetime.datetime.now()-started).seconds}초)",
        f"- 평가셋: `{args.csv}`",
        f"- 백엔드: {args.backends}",
        f"- 절제 실험: {'실행' if args.ablation else '안 함'}",
        "",
    ]
    if md is not None and len(md):
        def tbl(cols, title):
            cs = [c for c in cols if c in md.columns]
            if not cs:
                return []
            o = [f"## {title}", "", "| " + " | ".join(cs) + " |",
                 "|" + "---|" * len(cs)]
            for _, r in md.iterrows():
                o.append("| " + " | ".join(str(r[c]) for c in cs) + " |")
            return o + [""]

        lines += tbl(["backend", "n", "AUC", "정확도", "precision", "recall",
                      "팝업률", "실패"], "판정 성능")
        lines += tbl(["backend", "p50_ms", "p95_ms", "4초초과", "총소요_s"],
                     "지연 (NFR-1: 정상 5초 / 타임아웃 4초)")
        lines += tbl(["backend", "AUC", "swapped_AUC", "하락폭_AUC",
                      "정확도", "swapped_정확도", "하락폭_정확도"],
                     "절제 실험 — history를 바꿔도 유지되면 문맥을 안 보는 것")
        lines += tbl(["backend", "precision", "prec@10%", "prec@5%", "prec@1%"],
                     "실사용 기저율 보정 precision")
        lines += tbl(["backend", "TP", "FP", "FN", "TN", "threshold"], "혼동행렬")

        lines += [
            "## 읽을 때 주의",
            "",
            "- **AUC가 threshold와 무관한 비교다.** 정확도는 threshold를 잘 골랐냐는 운이 섞인다.",
            "- 평가셋이 50:50이면 precision이 실사용보다 낙관적이다. 기저율 보정표를 같이 볼 것.",
            "- **FP가 0이어도 FPR이 0인 것은 아니다.** 0/n의 95% 상한은 약 3/n이고,",
            "  그 값으로 보면 낮은 기저율에서의 precision이 크게 떨어진다.",
            "- 지연은 배치 처리량이다. 실서비스는 한 건씩 오므로 단일 요청 지연을 따로 재야 한다.",
            "",
        ]
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n리포트: {out}/report.md  (요약)  ·  {out}/report.txt  (콘솔 전문)")

if __name__ == "__main__":
    sys.exit(main())

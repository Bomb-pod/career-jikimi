# =====================================================================
# §9. 배포용 최종 모델 — §6이 [문맥 사용] 또는 [부분 사용]일 때만 실행
# =====================================================================
# 지금까지의 학습은 전부 "평가용"이라 20%를 검증으로 빼고 돌렸고 매번 버렸다.
# 여기서는 전체 데이터로 한 번 학습해 저장한다.
import json, os, shutil
import numpy as np, torch
from torch.utils.data import TensorDataset, DataLoader
from transformers import get_linear_schedule_with_warmup
from sklearn.metrics import precision_score, recall_score

OUT = "context_checker"
TARGET_PRECISION = 0.95   # 프로젝트 우선 지표. false positive가 치명적이다.

# --- 1) threshold 는 OOF에서 뽑는다 ------------------------------------
# 최종 모델이 자기 학습 데이터에 매긴 점수로 정하면 낙관적으로 편향된다.
# §6의 p_mean은 fold 밖 예측이라 편향이 없다.
cands = []
for t in np.arange(0.05, 1.00, 0.01):
    pr = (p_mean > t).astype(int)
    if pr.sum() == 0:
        continue
    cands.append((t, precision_score(y, pr, zero_division=0),
                     recall_score(y, pr, zero_division=0), pr.mean()))

hit = [c for c in cands if c[1] >= TARGET_PRECISION]
if hit:
    thr, prec, rec, flag = hit[0]
    print(f"threshold {thr:.2f} — precision {prec:.3f} / recall {rec:.3f} / 팝업률 {flag:.3f}")
else:
    thr, prec, rec, flag = max(cands, key=lambda c: c[1])
    print(f"[주의] precision {TARGET_PRECISION} 를 만족하는 threshold가 없다.")
    print(f"       최대 precision {prec:.3f} 지점 {thr:.2f} 를 쓴다 (recall {rec:.3f}).")
    print("       운영에 올리기 전에 데이터를 더 봐야 한다.")

# --- 2) 전체 데이터로 1회 학습 -----------------------------------------
torch.manual_seed(42); np.random.seed(42)
model = load_model()
enc = encode(df["history"].values, df["response"].values)
dl = DataLoader(TensorDataset(enc["input_ids"], enc["attention_mask"],
                              torch.tensor(y, dtype=torch.long)),
                batch_size=BATCH, shuffle=True)
opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
total = len(dl) * EPOCHS
sch = get_linear_schedule_with_warmup(opt, max(1, int(total*0.1)), total)
amp = torch.bfloat16 if USE_BF16 else torch.float32

model.train()
for ep in range(EPOCHS):
    tot = 0.0
    for ids, mask, lab in dl:
        ids, mask, lab = ids.to(device), mask.to(device), lab.to(device)
        with torch.autocast("cuda", dtype=amp, enabled=USE_BF16):
            loss = model(input_ids=ids, attention_mask=mask, labels=lab).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sch.step(); opt.zero_grad()
        tot += loss.item()
    print(f"  epoch {ep+1}/{EPOCHS}  loss {tot/len(dl):.4f}")

# --- 3) 저장 -----------------------------------------------------------
if os.path.exists(OUT):
    shutil.rmtree(OUT)
model.save_pretrained(OUT)
tokenizer.save_pretrained(OUT)

with open(f"{OUT}/threshold.json", "w", encoding="utf-8") as f:
    json.dump({
        "threshold": round(float(thr), 4),
        "target_precision": TARGET_PRECISION,
        "oof_precision": round(float(prec), 4),
        "oof_recall": round(float(rec), 4),
        "oof_flag_rate": round(float(flag), 4),
        "max_len": MAX_LEN,          # 추론 때 반드시 같아야 한다
        "epochs": EPOCHS, "lr": LR, "batch": BATCH,
        "n_rows": int(len(df)), "csv": CSV_PATH,
        "base_model": MODEL_NAME,
        "label_positive": "부적절",   # index 1 이 부적절이다
    }, f, ensure_ascii=False, indent=2)

# --- 4) 저장한 것을 그대로 다시 불러 검산 -------------------------------
# save/load 경로가 실제로 도는지 여기서 확인한다. 로컬에 가져가서 깨지면
# 원인을 찾기 훨씬 어렵다.
from transformers import AutoModelForSequenceClassification, AutoTokenizer
tk = AutoTokenizer.from_pretrained(OUT)
md = AutoModelForSequenceClassification.from_pretrained(OUT).to(device).eval()
HIST = ("A: 내일 배포 리허설 몇 시로 할까요?\nB: 오전 10시면 될 것 같습니다\n"
        "C: 저는 10시 좋습니다. 스테이징 먼저 올릴게요\nA: 롤백 절차도 한 번 봐주세요")
for cand, expect in [("오늘 저녁에 치킨 어때? 양념 vs 후라이드", "부적절"),
                     ("롤백은 alembic downgrade 한 단계로 정리해뒀습니다", "적절")]:
    e = tk(HIST, cand, truncation="only_first", max_length=MAX_LEN, return_tensors="pt").to(device)
    with torch.no_grad():
        p = torch.softmax(md(**e).logits.float(), -1)[0, 1].item()
    got = "부적절" if p >= thr else "적절"
    print(f"  {'OK ' if got == expect else 'X  '} p={p:.3f} → {got} (기대 {expect}) | {cand[:26]}")

# --- 5) 내려받기 -------------------------------------------------------
!zip -qr {OUT}.zip {OUT}
print(f"\n{OUT}.zip  {os.path.getsize(OUT + '.zip')/1e6:.0f}MB")
from google.colab import files
files.download(f"{OUT}.zip")

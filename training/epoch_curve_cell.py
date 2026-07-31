# =====================================================================
# §4-b. epoch 곡선 — EPOCHS를 몇으로 할지 10~13분에 정한다
# =====================================================================
# 전체 CV를 4/8 두 번 돌리면 46분이다. 한 fold에서 epoch마다 검증해 보면
# 어디서 정점을 찍는지 한 번에 보인다.
#
# swapped도 함께 잰다. 더 학습시킬수록 문맥 의존이 강해지는지 약해지는지가
# 이 프로젝트에서는 정확도만큼 중요하다.
import time
import torch
from torch.utils.data import TensorDataset, DataLoader
from transformers import get_linear_schedule_with_warmup

PROBE_EPOCHS = 10

cvp = StratifiedGroupKFold(5, shuffle=True, random_state=SEEDS[0])
tr_p, va_p = next(iter(cvp.split(df, y, groups)))

torch.manual_seed(42); np.random.seed(42)
m = load_model()
enc = encode(df["history"].values[tr_p], df["response"].values[tr_p])
dl = DataLoader(TensorDataset(enc["input_ids"], enc["attention_mask"],
                              torch.tensor(y[tr_p], dtype=torch.long)),
                batch_size=BATCH, shuffle=True)
opt = torch.optim.AdamW(m.parameters(), lr=LR, weight_decay=0.01)
total = len(dl) * PROBE_EPOCHS
sch = get_linear_schedule_with_warmup(opt, max(1, int(total*0.1)), total)
amp = torch.bfloat16 if USE_BF16 else torch.float32

h_va, r_va = df["history"].values[va_p], df["response"].values[va_p]
h_sw = np.roll(h_va, 1)
smp = tr_p[:200]

@torch.no_grad()
def _pred(h, r):
    m.eval(); out = []
    for i in range(0, len(r), 64):
        e = encode(h[i:i+64], r[i:i+64])
        with torch.autocast("cuda", dtype=amp, enabled=USE_BF16):
            lg = m(input_ids=e["input_ids"].to(device),
                   attention_mask=e["attention_mask"].to(device)).logits
        out.append(torch.softmax(lg.float(), -1)[:,1].cpu().numpy())
    m.train()
    return np.concatenate(out)

print(f"{'ep':>3} {'loss':>7} {'학습셋':>7} {'검증':>7} {'swapped':>8} {'하락폭':>7}")
hist, t0 = [], time.time()
for ep in range(PROBE_EPOCHS):
    tot = 0.0
    m.train()
    for ids, mask, lab in dl:
        ids, mask, lab = ids.to(device), mask.to(device), lab.to(device)
        with torch.autocast("cuda", dtype=amp, enabled=USE_BF16):
            loss = m(input_ids=ids, attention_mask=mask, labels=lab).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
        opt.step(); sch.step(); opt.zero_grad()
        tot += loss.item()

    tr_a = (((_pred(df["history"].values[smp], df["response"].values[smp]) > 0.5).astype(int))
            == y[smp]).mean()
    va_a = (((_pred(h_va, r_va) > 0.5).astype(int)) == y[va_p]).mean()
    sw_a = (((_pred(h_sw, r_va) > 0.5).astype(int)) == y[va_p]).mean()
    hist.append((ep+1, tot/len(dl), tr_a, va_a, sw_a))
    print(f"{ep+1:3d} {tot/len(dl):7.4f} {tr_a:7.3f} {va_a:7.3f} {sw_a:8.3f} {va_a-sw_a:+7.3f}")

print(f"\n({time.time()-t0:.0f}초)")
best = max(hist, key=lambda r: r[3])
print(f"검증 정점: epoch {best[0]} (검증 {best[3]:.3f} / swapped {best[4]:.3f} / 하락폭 {best[3]-best[4]:+.3f})")

# 정점 이후 3 epoch 동안 개선이 없으면 그 앞이 실질 정점이다.
plateau = next((r[0] for i, r in enumerate(hist)
                if all(h[3] <= r[3] + 0.005 for h in hist[i+1:i+4]) and len(hist) - i > 3), best[0])
print(f"권장 EPOCHS: {best[0]}  (정체 시작 {plateau})")
print("\n읽는 법")
print("  · 검증이 계속 오르면 EPOCHS를 더 올릴 여지가 있다")
print("  · 검증이 꺾이는데 학습셋만 오르면 그 지점부터 과적합이다")
print("  · **하락폭이 줄어들면** 더 학습시킬수록 문맥을 덜 본다는 뜻 — 정확도가 올라도 그 지점은 피한다")

del m; torch.cuda.empty_cache()

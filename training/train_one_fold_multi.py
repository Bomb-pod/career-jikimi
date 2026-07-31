# =====================================================================
# train_one_fold — 다른 인코더도 받도록 수정한 버전 (§3 두 번째 셀을 교체)
# =====================================================================
# 바뀐 점: token_type_ids 를 모델에 넘긴다.
#
# A.X-Encoder(ModernBERT)는 token_type_ids 를 쓰지 않아서 없어도 됐다.
# 그런데 KoBERT·KoELECTRA(BERT/ELECTRA 계열)는 **그것으로 문맥과 후보를
# 구분한다.** 안 넘기면 두 덩어리가 한 문장으로 뭉개진 채 학습되고,
# 에러 없이 성능만 조용히 떨어진다.
from torch.utils.data import TensorDataset, DataLoader
from transformers import get_linear_schedule_with_warmup

_probe = tokenizer("문맥", "후보")
USE_TOKEN_TYPE = "token_type_ids" in _probe
print(f"{MODEL_NAME} → token_type_ids {'사용' if USE_TOKEN_TYPE else '없음(ModernBERT/RoBERTa 계열)'}")

def _tensors(enc):
    t = [enc["input_ids"], enc["attention_mask"]]
    if USE_TOKEN_TYPE:
        t.append(enc["token_type_ids"])
    return t

def _kwargs(batch):
    kw = {"input_ids": batch[0].to(device), "attention_mask": batch[1].to(device)}
    if USE_TOKEN_TYPE:
        kw["token_type_ids"] = batch[2].to(device)
    return kw

def train_one_fold(tr_idx, va_idx, seed, verbose=False):
    torch.manual_seed(seed); np.random.seed(seed)
    model = load_model()

    enc = encode(df["history"].values[tr_idx], df["response"].values[tr_idx])
    dl = DataLoader(TensorDataset(*_tensors(enc), torch.tensor(y[tr_idx], dtype=torch.long)),
                    batch_size=BATCH, shuffle=True)

    opt = torch.optim.AdamW(model.parameters(), lr=LR, weight_decay=0.01)
    total = len(dl) * EPOCHS
    sch = get_linear_schedule_with_warmup(opt, max(1, int(total*0.1)), total)
    amp = torch.bfloat16 if USE_BF16 else torch.float32

    losses = []
    model.train()
    for ep in range(EPOCHS):
        tot = 0.0
        for batch in dl:
            lab = batch[-1].to(device)
            with torch.autocast("cuda", dtype=amp, enabled=USE_BF16):
                loss = model(**_kwargs(batch), labels=lab).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sch.step(); opt.zero_grad()
            tot += loss.item()
        losses.append(tot/len(dl))
        if verbose:
            print(f"    epoch {ep+1}/{EPOCHS}  loss {losses[-1]:.4f}")

    @torch.no_grad()
    def predict(h, r):
        model.eval(); out = []
        for i in range(0, len(r), 64):
            e = encode(h[i:i+64], r[i:i+64])
            batch = _tensors(e)
            with torch.autocast("cuda", dtype=amp, enabled=USE_BF16):
                lg = model(**_kwargs(batch)).logits
            out.append(torch.softmax(lg.float(), -1)[:,1].cpu().numpy())
        return np.concatenate(out)

    smp = tr_idx[:200]
    train_acc = (((predict(df["history"].values[smp], df["response"].values[smp]) > 0.5).astype(int))
                 == y[smp]).mean()

    h_va, r_va = df["history"].values[va_idx], df["response"].values[va_idx]
    res = {"normal":  predict(h_va, r_va),
           "swapped": predict(np.roll(h_va, 1), r_va),
           "empty":   predict(np.array([""]*len(r_va)), r_va),
           "train_acc": train_acc, "losses": losses}
    del model; torch.cuda.empty_cache()
    return res

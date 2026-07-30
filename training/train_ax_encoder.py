# -*- coding: utf-8 -*-
"""
career-jikimi 문맥 적절성 분류기 파인튜닝
모델: skt/A.X-Encoder-base (0.1B, ModernBERT, ctx 16K, Apache-2.0)
태스크: [CLS] history [SEP] response → 부적절 확률 (cross-encoder 이진 분류)

사용법:
  python train_ax_encoder.py --csv dataset/training_dataset_v3_1000.csv          # 5-fold CV + 최종 모델
  python train_ax_encoder.py --csv ... --smoke                                    # 축소 동작 확인
  python train_ax_encoder.py --csv ... --skip-cv                                  # CV 생략, 최종 모델만

원칙 (데이터셋 문서와 일치):
  - 분할은 pair_id 그룹 단위 — 같은 response의 쌍둥이 행을 train/test에 가르지 않는다
  - 입력은 history + response 만 사용 (source/difficulty는 평가 분석 전용)
  - precision 우선 — OOF 예측으로 threshold 스윕, 목표 precision을 만족하는 지점 채택

출력 (--out 디렉터리):
  oof_predictions.csv   fold 밖 예측 (no, prob, label) — 슬라이스 분석용
  report.json           전체/슬라이스 지표 + threshold 스윕
  final_model/          전체 데이터로 학습한 배포용 모델 + tokenizer + threshold.json
"""
import argparse, json, os, random
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset, DataLoader
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                             f1_score, roc_auc_score)
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL_NAME = 'skt/A.X-Encoder-base'


def set_seed(s):
    random.seed(s); np.random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)


class PairDataset(Dataset):
    def __init__(self, df, tokenizer, max_len):
        self.h = df.history.tolist()
        self.r = df.response.tolist()
        self.y = (df.label == '부적절').astype(int).tolist()
        self.tok, self.max_len = tokenizer, max_len

    def __len__(self):
        return len(self.y)

    def __getitem__(self, i):
        enc = self.tok(self.h[i], self.r[i], truncation=True, max_length=self.max_len)
        enc['labels'] = self.y[i]
        return enc


def collate(batch, tok):
    labels = torch.tensor([b.pop('labels') for b in batch])
    out = tok.pad(batch, return_tensors='pt')
    out['labels'] = labels
    return out


def train_one(model, loader, val_loader, device, epochs, lr, use_amp):
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    total = len(loader) * epochs
    warmup = max(1, int(total * 0.1))
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: s / warmup if s < warmup else max(0.0, (total - s) / max(1, total - warmup)))
    scaler = torch.amp.GradScaler(enabled=use_amp)
    for ep in range(epochs):
        model.train(); tl = 0.0
        for batch in loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            opt.zero_grad()
            with torch.amp.autocast('cuda', enabled=use_amp):
                loss = model(**batch).loss
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt); scaler.update(); sched.step()
            tl += loss.item()
        msg = f'  epoch {ep + 1}/{epochs} train_loss={tl / len(loader):.4f}'
        if val_loader is not None:
            p, y = predict(model, val_loader, device, use_amp)
            msg += f' val_acc={accuracy_score(y, p > .5):.3f} val_auc={roc_auc_score(y, p):.3f}'
        print(msg, flush=True)


@torch.no_grad()
def predict(model, loader, device, use_amp):
    model.eval(); probs, ys = [], []
    for batch in loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        y = batch.pop('labels')
        with torch.amp.autocast('cuda', enabled=use_amp):
            logits = model(**batch).logits
        probs.append(torch.softmax(logits.float(), -1)[:, 1].cpu().numpy())
        ys.append(y.cpu().numpy())
    return np.concatenate(probs), np.concatenate(ys)


def metrics_at(y, p, thr):
    pred = (p >= thr).astype(int)
    return dict(threshold=round(float(thr), 3),
                accuracy=round(accuracy_score(y, pred), 4),
                precision=round(precision_score(y, pred, zero_division=0), 4),
                recall=round(recall_score(y, pred, zero_division=0), 4),
                f1=round(f1_score(y, pred, zero_division=0), 4),
                flag_rate=round(float(pred.mean()), 4))


def fresh_model(model_name, device, num_labels=2):
    """분류 헤드를 새로 붙인 모델 1개. 노트북과 스크립트가 같은 정의를 쓴다."""
    m = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=num_labels)
    # fp32 고정 — A.X-Encoder의 config는 dtype=bfloat16을 선언하고 transformers 5.x는
    # 체크포인트 dtype을 그대로 따른다(4.x는 무조건 fp32로 올렸다). bf16 파라미터는 bf16
    # 그래디언트를 만들고 GradScaler.unscale_에는 bf16 CUDA 커널이 없어 학습이 죽는다.
    # 이 스크립트의 전제는 'fp32 가중치 + autocast 혼합정밀도'이므로 로드 dtype과 무관하게 못박는다.
    return m.float().to(device)


def choose_threshold(y, p, target_precision, lo=0.30, hi=0.991, step=0.005):
    """목표 precision을 만족하는 가장 낮은 threshold. 못 만족하면 0.5."""
    for t in np.arange(lo, hi, step):
        if metrics_at(y, p, t)['precision'] >= target_precision:
            return round(float(t), 3)
    return 0.5


def slice_metrics(df, y, p, thr, cols=('source', 'source_type', 'difficulty'), min_n=10):
    """분석용 컬럼이 있을 때만 슬라이스 지표를 낸다 (simple CSV에는 없다).

    `n_pos`를 함께 낸다 — 이 데이터셋은 source_type이 라벨과 얽혀 있어
    `matched`/`matched_v25`/`smalltalk_casual`처럼 부적절 행이 0건인 슬라이스가 있다.
    그 경우 precision/recall은 정의되지 않고 zero_division=0 때문에 0.0으로 나오는데,
    성능이 0인 것과 구별되지 않는다. 표를 읽거나 만들 때 반드시 n_pos를 먼저 볼 것.
    """
    out = {}
    for col in cols:
        if col in df.columns:
            for val, g in df.groupby(df[col].fillna('-')):
                if len(g) >= min_n:
                    i = g.index
                    out[f'{col}={val}'] = dict(
                        n=len(g), n_pos=int(y[i].sum()),
                        **{k: v for k, v in metrics_at(y[i], p[i], thr).items()
                           if k != 'threshold'})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', default='dataset/training_dataset_v3_1000.csv')
    ap.add_argument('--out', default='train_out')
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--epochs', type=int, default=4)
    ap.add_argument('--lr', type=float, default=2e-5)
    ap.add_argument('--batch', type=int, default=16)
    ap.add_argument('--max-len', type=int, default=512)
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--target-precision', type=float, default=0.95)
    ap.add_argument('--smoke', action='store_true', help='96행/1에폭 축소 실행 (동작 확인용)')
    ap.add_argument('--skip-cv', action='store_true')
    ap.add_argument('--model', default=MODEL_NAME)
    args = ap.parse_args()

    set_seed(args.seed)
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    use_amp = device == 'cuda'
    print(f'device={device} amp={use_amp} model={args.model}')

    df = pd.read_csv(args.csv, encoding='utf-8-sig')
    assert {'pair_id', 'history', 'response', 'label'} <= set(df.columns)
    if args.smoke:
        keep = df.pair_id.drop_duplicates().sample(48, random_state=0)
        df = df[df.pair_id.isin(keep)].reset_index(drop=True)
        args.epochs, args.folds = 1, 2
        print(f'[smoke] {len(df)}행 / folds=2 / epochs=1')

    os.makedirs(args.out, exist_ok=True)
    tok = AutoTokenizer.from_pretrained(args.model)
    y_all = (df.label == '부적절').astype(int).values

    def make_loader(sub, shuffle):
        return DataLoader(PairDataset(sub, tok, args.max_len), batch_size=args.batch,
                          shuffle=shuffle, num_workers=0,
                          collate_fn=lambda b: collate(b, tok))

    report = {'model': args.model, 'rows': len(df), 'folds': args.folds,
              'epochs': args.epochs, 'lr': args.lr, 'max_len': args.max_len}

    # ---------------- 5-fold 그룹 CV → OOF 예측 ----------------
    if not args.skip_cv:
        oof = np.zeros(len(df))
        skf = StratifiedGroupKFold(args.folds, shuffle=True, random_state=args.seed)
        for k, (tr, va) in enumerate(skf.split(df, y_all, groups=df.pair_id)):
            print(f'--- fold {k + 1}/{args.folds} (train {len(tr)} / val {len(va)})')
            model = fresh_model(args.model, device)
            train_one(model, make_loader(df.iloc[tr], True), make_loader(df.iloc[va], False),
                      device, args.epochs, args.lr, use_amp)
            oof[va], _ = predict(model, make_loader(df.iloc[va], False), device, use_amp)
            del model
            if device == 'cuda':
                torch.cuda.empty_cache()

        pd.DataFrame({'no': df.no if 'no' in df else range(len(df)),
                      'pair_id': df.pair_id, 'label': df.label,
                      'prob_inappropriate': oof.round(4)}
                     ).to_csv(f'{args.out}/oof_predictions.csv', index=False, encoding='utf-8-sig')

        # 전체 지표 + threshold 스윕
        report['oof_auc'] = round(roc_auc_score(y_all, oof), 4)
        report['sweep'] = [metrics_at(y_all, oof, t) for t in np.arange(0.3, 0.96, 0.05)]
        # precision 우선: 목표 precision을 만족하는 가장 낮은 threshold
        chosen = choose_threshold(y_all, oof, args.target_precision)
        report['chosen_threshold'] = chosen
        report['at_chosen'] = metrics_at(y_all, oof, chosen)
        report['at_0.5'] = metrics_at(y_all, oof, 0.5)

        # 슬라이스 분석 (컬럼이 있을 때만)
        report['slices'] = slice_metrics(df, y_all, oof, chosen)
        print(json.dumps({k: report[k] for k in ('oof_auc', 'chosen_threshold', 'at_chosen', 'at_0.5')},
                         ensure_ascii=False, indent=1))

    # ---------------- 최종 모델: 전체 데이터로 학습 → 저장 ----------------
    print('--- final model (전체 데이터 학습)')
    model = fresh_model(args.model, device)
    train_one(model, make_loader(df, True), None, device, args.epochs, args.lr, use_amp)
    out_dir = f'{args.out}/final_model'
    model.save_pretrained(out_dir); tok.save_pretrained(out_dir)
    with open(f'{out_dir}/threshold.json', 'w', encoding='utf-8') as f:
        json.dump({'threshold': report.get('chosen_threshold', 0.5),
                   'target_precision': args.target_precision,
                   'label_map': {'0': '적절', '1': '부적절'}}, f, ensure_ascii=False, indent=2)
    with open(f'{args.out}/report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f'저장 완료: {out_dir}  (threshold={report.get("chosen_threshold", 0.5)})')


if __name__ == '__main__':
    main()

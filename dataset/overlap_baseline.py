# -*- coding: utf-8 -*-
"""
어휘 겹침 베이스라인 — 모델 없이 문자열 겹침만으로 label을 맞혀본다.
=====================================================================
사용법: python overlap_baseline.py <데이터셋.csv> [...]

이 값이 높으면 테스트셋이 '문맥 판단'이 아니라 '어휘 겹침'을 재고 있다는 뜻이다.
모델 AUC와 반드시 나란히 보고할 것. 모델 AUC가 이 값보다 유의하게 높지 않으면
모델이 기여한 게 없다.

기준: 겹침 AUC가 0.75를 넘으면 그 구간은 변별력이 의심스럽다.
"""
import sys, re
import pandas as pd
from sklearn.metrics import roc_auc_score

W = lambda s: set(w for w in re.sub(r'[^가-힣a-zA-Z0-9 ]', ' ', str(s)).split() if len(w) >= 2)
def C(s, n=2):
    t = re.sub(r'\s', '', re.sub(r'[^가-힣a-zA-Z0-9]', ' ', str(s)))
    return set(t[i:i+n] for i in range(len(t)-n+1))

def scores(d):
    j, o, c = [], [], []
    for _, r in d.iterrows():
        H, R = W(r.history), W(r.response)
        Hc, Rc = C(r.history), C(r.response)
        j.append(len(H & R) / max(1, len(H | R)))
        o.append(len(H & R) / max(1, len(R)))
        c.append(len(Hc & Rc) / max(1, len(Hc | Rc)))
    return pd.DataFrame({'어절 Jaccard': j, 'response 포함률': o, '글자 2-gram': c})

def report(path):
    d = pd.read_csv(path, encoding='utf-8-sig')
    y = (d.label == '부적절').astype(int)
    s = scores(d)
    print(f'\n=== {path}  (n={len(d)}) ===')
    groups = [('전체', d.index)]
    if 'difficulty' in d.columns:
        groups += [(g, d.index[d.difficulty == g]) for g in ['easy', 'medium', 'hard'] if (d.difficulty == g).any()]
    print(f"{'구간':8s} {'n':>4s} " + ' '.join(f'{c:>14s}' for c in s.columns) + '   판정')
    for name, idx in groups:
        aucs = [roc_auc_score(y[idx], -s[c][idx]) for c in s.columns]
        worst = max(aucs)
        flag = 'OK' if worst <= 0.75 else ('주의' if worst <= 0.85 else '변별력 낮음')
        print(f'{name:8s} {len(idx):>4d} ' + ' '.join(f'{a:>14.3f}' for a in aucs) + f'   {flag}')

for p in sys.argv[1:]:
    report(p)

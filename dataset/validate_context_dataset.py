# -*- coding: utf-8 -*-
"""
문맥 적절성 데이터셋 누출 진단 스크립트
========================================
사용법: python validate_context_dataset.py <데이터셋.csv>
필요 컬럼: history, response, label (label 값: 적절/부적절)

데이터셋을 수정할 때마다 반드시 다시 실행할 것.
결측치·중복·분포 균형보다 이 검증이 중요하다 — 이걸 통과하지 못하는
데이터셋은 '문맥'을 측정하지 않는다.

| 검사                | 통과 기준        | 실패의 의미                          |
|---------------------|------------------|--------------------------------------|
| response-only       | ≤ 0.55           | label이 response 안에 새어 있음      |
| history-only        | ≤ 0.55           | label이 history 안에 새어 있음       |
| history 셔플        | ≤ 0.60           | 짝이 아니라 각 텍스트의 표면 특징으로 맞힘 |
| 관계 특징(정합성)   | 위 세 값보다 높음 | 신호가 history-response '관계'에 존재  |
"""
import sys, re
import pandas as pd, numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import cross_val_score, StratifiedKFold, StratifiedGroupKFold

path = sys.argv[1] if len(sys.argv) > 1 else 'dialogue_context_dataset_v2.csv'
df = pd.read_csv(path, encoding='utf-8-sig')
y = (df.label == '부적절').astype(int).values

# 짝 구조 데이터셋은 같은 텍스트의 쌍둥이 행이 train/test에 갈라지면
# 암기 효과가 평가를 오염시킨다(과대/과소 모두 가능).
# → 각 검사에서 암기 가능한 텍스트 단위로 그룹 분할한다.
#   (실제 파인튜닝의 train/val/test 분할은 pair_id 단위로 지킬 것.)
def lr_acc(X, group_key):
    p = make_pipeline(TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4), min_df=2),
                      LogisticRegression(max_iter=2000))
    cv = StratifiedGroupKFold(5, shuffle=True, random_state=0)
    return cross_val_score(p, X, y, cv=cv, groups=pd.factorize(group_key)[0]).mean()

rng = np.random.default_rng(0)
perm = rng.permutation(len(df))

# 관계 특징: (a) history-response TF-IDF 코사인 유사도 (b) 격식(존댓말) 불일치
vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4), min_df=2)
M = vec.fit_transform(pd.concat([df.history, df.response]).tolist())
H, R = M[:len(df)], M[len(df):]
Hn = H.multiply(1 / (np.sqrt(H.multiply(H).sum(1)) + 1e-9))
Rn = R.multiply(1 / (np.sqrt(R.multiply(R).sum(1)) + 1e-9))
cos = np.asarray(Hn.multiply(Rn).sum(1)).ravel()

def formal_score(t):
    sents = [x for x in re.split(r'(?<=[.?!])\s+', str(t)) if x.strip()]
    return np.mean([bool(re.search(r'(요|습니다|습니까|시죠|세요)\s*[.?!]?$', s)) for s in sents]) if sents else 0.0

fh = df.history.map(formal_score).values
fr = df.response.map(formal_score).values
feats = np.c_[cos, np.abs(fh - fr), fh, fr]
rel = cross_val_score(LogisticRegression(max_iter=2000), feats, y,
                      cv=StratifiedKFold(5, shuffle=True, random_state=0)).mean()

pair_key = df.pair_id if 'pair_id' in df.columns else df.response
results = {
    'response-only':    lr_acc(df.response, df.response),
    'history-only':     lr_acc(df.history, df.history),
    'history 셔플+concat': lr_acc(pd.Series(df.history.values[perm]) + ' [SEP] ' + df.response.values, pair_key),
    'history+response concat': lr_acc(df.history + ' [SEP] ' + df.response, pair_key),
    '관계 특징(유사도+격식)': rel,
}

print(f'파일: {path}  ({len(df)}행, 부적절 {y.mean():.1%})\n')
crit = {'response-only': .55, 'history-only': .55, 'history 셔플+concat': .60}
fails = 0
for k, v in results.items():
    mark = ''
    if k in crit:
        ok = v <= crit[k]; fails += (not ok)
        mark = f'  [{"PASS" if ok else "FAIL"} 기준 ≤{crit[k]}]'
    print(f'  {k:24s} acc = {v:.3f}{mark}')

sig = results['관계 특징(유사도+격식)'] > max(results['response-only'], results['history-only'], .55)
print(f'\n  관계 신호 존재 여부: {"YES" if sig else "NO"} (관계 특징이 단독 텍스트 특징보다 높은가)')
print('\n판정:', '통과 — label은 history와 response의 관계에만 존재한다.' if fails == 0 and sig
      else '실패 — 이 데이터셋으로 파인튜닝하면 문맥이 아닌 다른 것을 학습한다.')
sys.exit(0 if fails == 0 and sig else 1)

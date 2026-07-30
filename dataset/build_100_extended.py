# -*- coding: utf-8 -*-
"""
dialogue_context_appropriateness_100 확장본 조립.
사용법: python build_100_extended.py <원본 100행 CSV>
산출: dialogue_context_appropriateness_extended.csv (원본 100 + 추가 156 = 256행)
컬럼·규약 유지: no, pair_id, turn_count, history, response, label / pair = 같은 history 2행
"""
import sys
import pandas as pd
from additions_100 import QUADS, FLIPS

src = sys.argv[1]
orig = pd.read_csv(src)
by_no = orig.set_index('no')

# --- 무결성 검사 ---
sm_nos = [f[0] for f in FLIPS]; an_nos = [f[1] for f in FLIPS]
assert len(set(sm_nos)) == 50 and sorted(sm_nos) == list(range(2, 101, 2)), '잡담 50개 전부 1회씩'
assert len(set(an_nos)) == 50, '적절 응답 50개 전부 1회씩'
assert all(by_no.loc[n, 'label'] == '부적절' for n in sm_nos)
assert all(by_no.loc[n, 'label'] == '적절' for n in an_nos)
for _, hA, rA, hB, rB in QUADS:
    for h in (hA, hB):
        assert h.split('\n')[-1].split(':')[0].strip() != '나', 'history가 나로 끝남'

rows, no, pid = [], 101, 51
def pair(hist, resp_ok, resp_bad):
    global no, pid
    tc = len([l for l in hist.split('\n') if l.strip()])
    rows.append(dict(no=no,   pair_id=f'P{pid:03d}', turn_count=tc, history=hist, response=resp_ok,  label='적절'))
    rows.append(dict(no=no+1, pair_id=f'P{pid:03d}', turn_count=tc, history=hist, response=resp_bad, label='부적절'))
    no += 2; pid += 1

for _, hA, rA, hB, rB in QUADS:      # 교차: A방(rA 적절/rB 부적절), B방(rB 적절/rA 부적절)
    pair(hA, rA, rB)
    pair(hB, rB, rA)
for sm_no, an_no, hist in FLIPS:     # 뒤집기: 새 방(잡담 적절 / 기존 적절응답 부적절)
    pair(hist, by_no.loc[sm_no, 'response'], by_no.loc[an_no, 'response'])

ext = pd.DataFrame(rows)
comb = pd.concat([orig, ext], ignore_index=True)
comb.to_csv('dialogue_context_appropriateness_extended.csv', index=False, encoding='utf-8-sig')

rb = comb.groupby('response').label.nunique()
hb = comb.groupby('history').label.value_counts().unstack(fill_value=0)
print(f'추가 {len(ext)}행 → 통합 {len(comb)}행  label={dict(comb.label.value_counts())}')
print(f'양쪽 label 등장 response: {(rb == 2).sum()}/{len(rb)} | history 균형 이탈: {(hb.min(axis=1) == 0).sum()}')
print(f'turn_count 분포: {dict(comb.turn_count.value_counts().sort_index())}')

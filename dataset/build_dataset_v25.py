# -*- coding: utf-8 -*-
"""
v2.5 확장 데이터 조립 + v2 통합.
사용법: python build_dataset_v25.py [v2 CSV 경로]

산출:
  dialogue_context_dataset_v25_extension.csv  — 확장분 (16방 × 7응답 × 2 = 224행)
  dialogue_context_dataset_v25_combined.csv   — v2(520) + 확장(224) = 744행 (학습용)

구조 보증 (v2와 동일):
  - 모든 response는 자기 방(적절) 1회 + 파트너 방(부적절) 1회 등장
  - 모든 방 history는 적절 7회 + 부적절 7회 등장 → history 측 누출 없음
"""
import sys
import pandas as pd
from rooms_v25 import ROOMS, SWAP_PAIRS

V2_PATH = sys.argv[1] if len(sys.argv) > 1 else 'dialogue_context_dataset_v2.csv'

# 무결성 검사: 방 7응답 고정, 잡담 앵커 규칙은 수작업 검수 전제
for rid, room in ROOMS.items():
    assert len(room['responses']) == 7, f'{rid}: 응답 7개 필요'
    last_speaker = room['history'][-1].split(':')[0].strip()
    assert last_speaker != '나', f'{rid}: history가 나의 발화로 끝남'
paired = {r for a, b, _ in SWAP_PAIRS for r in (a, b)}
assert paired == set(ROOMS), '모든 방이 교환 쌍에 정확히 1회 속해야 함'

rows = []
def add(label, room_id, origin_room, resp_idx, difficulty):
    room, origin = ROOMS[room_id], ROOMS[origin_room]
    hist = '\n'.join(room['history'])
    rows.append(dict(
        pair_id=f'v25_{origin_room}_{resp_idx}',
        source_type='matched_v25' if label == '적절' else 'misdirect_v25',
        label=label,
        room_id=room_id, origin_room=origin_room,
        difficulty='-' if label == '적절' else difficulty,
        party=room['party'], register=room['register'], style=room['style'],
        turn_count=len(room['history']),
        history=hist, response=origin['responses'][resp_idx],
    ))

for a, b, diff in SWAP_PAIRS:
    for i in range(7):
        add('적절', a, a, i, diff)      # A 응답 × A 방
        add('부적절', b, a, i, diff)    # A 응답 × B 방 (잘못 보냄)
        add('적절', b, b, i, diff)      # B 응답 × B 방
        add('부적절', a, b, i, diff)    # B 응답 × A 방

ext = pd.DataFrame(rows)
ext.insert(0, 'no', range(1, len(ext) + 1))
ext['source'] = 'v25'
ext.to_csv('dialogue_context_dataset_v25_extension.csv', index=False, encoding='utf-8-sig')

# ---- v2와 통합 ----
v2 = pd.read_csv(V2_PATH, encoding='utf-8-sig')
v2['source'] = 'v2'
common = ['pair_id', 'source_type', 'label', 'turn_count', 'history', 'response', 'source']
comb = pd.concat([
    v2[common + ['persona', 'scenario', 'orig_reason']],
    ext[common + ['room_id', 'origin_room', 'difficulty', 'party', 'register', 'style']],
], ignore_index=True)
comb.insert(0, 'no', range(1, len(comb) + 1))
comb.to_csv('dialogue_context_dataset_v25_combined.csv', index=False, encoding='utf-8-sig')

# ---- 요약 ----
rb = ext.groupby('response').label.nunique()
hb = ext.groupby('history').label.value_counts().unstack(fill_value=0)
print(f'확장분: {len(ext)}행  label={dict(ext.label.value_counts())}')
print(f'  난이도(부적절): {dict(ext[ext.label=="부적절"].difficulty.value_counts())}')
print(f'  단체방 비율: {(ext.party=="group").mean():.0%}, 평균 turn_count: {ext.turn_count.mean():.1f}')
print(f'  양쪽 label 등장 response: {(rb==2).sum()}/{len(rb)}, history 균형 이탈: {(hb.min(axis=1)==0).sum()}')
print(f'통합본: {len(comb)}행  label={dict(comb.label.value_counts())}')

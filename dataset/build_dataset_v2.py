# -*- coding: utf-8 -*-
"""
career-jikimi 데이터셋 v2 재조립 스크립트
=========================================
목적: '방 착각(문맥 불일치) 탐지' 태스크에 맞는 짝(counterfactual) 구조 데이터셋 생성.

핵심 원칙: 모든 response는 적절 1회 + 부적절 1회씩 등장한다.
  → response만 보고는 label을 맞힐 수 없다 (response-only 정확도 = 50%).
  → 모델이 label을 맞히려면 반드시 history와의 관계를 읽어야 한다.

구성 (v1 500행 → v2 520행):
  A. matched          : v1 적절(P1~P5) 원본 짝 250행 → 적절
  B. cross_scenario   : A의 response에 다른 시나리오 그룹의 history를 결합 230행 → 부적절
  C. work_to_casual   : 업무 대화 P response × 일상 잡담 history 20행 → 부적절 ("회사 메시지를 친구방에")
  D. smalltalk_casual : N1 잡담 response(첫 문장만, 중복 제거) × 일상 잡담 history 10행 → 적절
  E. smalltalk_serious: 같은 잡담 response × 예약된 진지한 P history 10행 → 부적절
     (N1 원본 history는 15/50이 일상 대화라 '잡담방에서 잡담=적절' 기준과 모순 → 미사용)

제외: N2·N4·N5(무례·공격·갈등)와 N3(질문 무시) 200행은 '내용/화용 문제'로,
      프로젝트의 닫힌 결정("내용 기준 필터링 배제")에 따라 본 태스크에서 분리.
      → pragmatic_quality_dataset_v2.csv 로 별도 보존 (향후 톤 경고 확장용).
"""
import pandas as pd, numpy as np, re, collections, itertools, sys

SRC = sys.argv[1] if len(sys.argv) > 1 else 'dialogue_appropriateness_dataset_500_final.csv'
SEED = 42
rng = np.random.default_rng(SEED)

df = pd.read_csv(SRC, encoding='utf-8-sig')

# ---------------------------------------------------------------- 유틸
def split_sents(s):
    return [x.strip() for x in re.split(r'(?<=[.!?])\s+', str(s).strip()) if x.strip()]

def is_formal(t):
    return any(re.search(r'(요|습니다|습니까|시죠|세요)\s*[.?!]?$', x) for x in split_sents(t))

SCEN_GROUP = {'갈등 상황': 'emotional', '고민·감정 상담': 'emotional',
              '업무 대화': 'task', '질문·요청': 'task', '정보 공유': 'task',
              '일상 대화': 'casual'}
FORMAL_PERSONA = {'선후배', '직장 관계(상사·동료)'}

# ---------------------------------------------------------------- 1) N1 잡담 추출: 첫 문장만 사용
# 이유: 뒷문장에 원본 문맥 참조("아무튼 발표 얘기는 나중에 하자")가 남아
#       잡담방(적절) 짝에 넣으면 라벨이 오염된다. 첫 문장이 순수 잡담이다.
n1 = df[df.reason == 'N1'].copy()
n1['stripped'] = n1.response.map(lambda s: split_sents(s)[0])
n1 = n1.drop_duplicates('stripped', keep='first')
n1 = n1[~n1.stripped.map(is_formal)]          # 반말 잡담 history와 격이 안 맞는 존댓말 잡담은 제외
n1 = n1.reset_index(drop=True)
U = len(n1)
print(f'N1: 고유 잡담 response {U}개 확보 (첫 문장 기준)')

# ---------------------------------------------------------------- 2) 일상 잡담 history (신규 작성 20종, 반말)
# 조건: (a) 마지막 화자가 상대방 (b) 답을 요구하는 직접 질문으로 끝나지 않음 (c) 고민/갈등 아님
CASUAL = [
    ('친구',      '친구: 어제 새로 생긴 분식집 가봤는데 떡볶이가 진짜 맛있더라'),
    ('친구',      '나: 주말에 뭐 해?\n친구: 아직 계획 없어. 집에서 쉬지 않을까 싶은데'),
    ('형제·자매', '나: 오늘 저녁 뭐 먹지?\n동생: 나는 아무거나 좋아. 시켜 먹어도 되고'),
    ('연인',      '연인: 오늘 하늘 봤어? 노을이 진짜 예쁘더라'),
    ('친구',      '나: 요즘 별일 없지?\n친구: 응, 그냥 똑같지 뭐. 회사 갔다 집 갔다 반복이야'),
    ('형제·자매', '동생: 냉장고에 있던 푸딩 언니가 먹었지?\n나: ㅋㅋ 미안, 하나만 남았길래\n동생: 아 진짜, 그거 아껴둔 건데 ㅋㅋ'),
    ('연인',      '나: 이번 주말에 날씨 좋으면 드라이브 갈까?\n연인: 좋아, 토요일이 낫겠다. 오랜만에 바람 좀 쐬자'),
    ('친구',      '친구: 어제 축구 봤어? 마지막 골 진짜 장난 아니더라'),
    ('형제·자매', '형: 요즘 운동 시작했는데 3일 만에 근육통 와서 죽겠다'),
    ('연인',      '연인: 아까 카페에서 마신 라떼 괜찮더라. 다음에 또 가자'),
    ('친구',      '친구: 나 어제 미용실 갔다가 머리 엄청 짧게 잘랐어 ㅋㅋ\n나: 진짜? 사진 보내봐\n친구: 잠깐만, 지금은 부끄러우니까 나중에 ㅋㅋ'),
    ('친구',      '친구: 요즘 뭐 재밌는 거 없나. 하루하루가 너무 심심해'),
    ('형제·자매', '동생: 오늘 길에서 완전 귀여운 강아지 봤어. 사진 찍어놨는데 나중에 보여줄게'),
    ('연인',      '연인: 오늘 점심에 뭐 먹었어?\n나: 회사 앞에서 김치찌개. 너는?\n연인: 나는 그냥 샌드위치로 때웠어'),
    ('친구',      '친구: 어제 늦게까지 게임 하다가 늦잠 자서 하루 종일 정신없었어'),
    ('형제·자매', '나: 요즘 드라마 뭐 봐?\n오빠: 볼 게 없어서 그냥 유튜브만 계속 보게 되더라'),
    ('연인',      '연인: 방금 산책 나왔는데 바람이 선선해서 걷기 딱 좋아'),
    ('친구',      '친구: 나 요즘 커피 줄이는 중인데 오후만 되면 너무 마시고 싶어'),
    ('형제·자매', '언니: 아까 마트 갔다가 네가 좋아하는 과자 있길래 사 왔어'),
    ('연인',      '연인: 오늘따라 시간이 진짜 안 가는 것 같아\n나: ㅋㅋ 왜, 무슨 일 있어?\n연인: 아니 그냥, 빨리 퇴근해서 쉬고 싶어서'),
]

rows = []
def add(source, label, hist, resp, persona, scenario, pair_id, extra=None):
    rows.append(dict(source_type=source, label=label, history=hist, response=resp,
                     persona=persona, scenario=scenario, pair_id=pair_id,
                     turn_count=len([l for l in hist.split('\n') if l.strip()]),
                     **(extra or {})))

# ---------------------------------------------------------------- 3) A. matched (적절 250)
P = df[df.label == '적절'].reset_index(drop=True)
for i, r in P.iterrows():
    add('matched', '적절', r.history, r.response, r.persona, r.scenario,
        f'p{i}', {'orig_no_history': r.no, 'orig_no_response': r.no, 'orig_reason': r.reason})

# ---------------------------------------------------------------- 4) E용 진지한 history 예약 (U개)
# smalltalk 부적절 짝에는 N1 원본 대신, 다른 곳에 미사용된 task 그룹 P history를 쓴다.
# 이 history들은 matched(적절) 1회 + E(부적절) 1회로 양쪽에 균형 있게 등장한다.
task_hist_pool = P.index[P.scenario.isin(['업무 대화', '질문·요청', '정보 공유'])].tolist()
reserved = list(rng.choice(task_hist_pool, size=U, replace=False))

# ---------------------------------------------------------------- 5) C. work_to_casual (부적절 20)
# 잡담 history 20종을 각 1회씩만 부적절에 사용해 history 측 라벨 균형을 지킨다.
work_all = P.index[P.scenario == '업무 대화'].tolist()
work_idx = list(rng.choice(work_all, size=len(CASUAL), replace=False))
order = rng.permutation(len(CASUAL))
for k, i in enumerate(work_idx):
    persona_c, hist_c = CASUAL[order[k]]
    r = P.loc[i]
    add('work_to_casual', '부적절', hist_c, r.response, persona_c, '일상 대화',
        f'p{i}', {'orig_no_history': -1, 'orig_no_response': r.no, 'orig_reason': 'X2'})

# ---------------------------------------------------------------- 6) B. cross_scenario derangement (부적절 230)
# work_to_casual에 쓰인 20개를 제외한 나머지 230개 P response에, 다른 '시나리오 그룹'의 P history를 1:1 결합.
# 제약: 시나리오 그룹 상이 + TF-IDF 유사도 < 0.25 + 가능하면 격식(존댓말/반말) 그룹 일치.
from sklearn.feature_extraction.text import TfidfVectorizer
vec = TfidfVectorizer(analyzer='char_wb', ngram_range=(2, 4), min_df=1)
M = vec.fit_transform(pd.concat([P.history, P.response]).tolist())
H, R = M[:len(P)], M[len(P):]
sim = (R @ H.T).toarray()                                        # sim[i,j] = response_i vs history_j

resp_idx = [i for i in P.index if i not in work_idx]
hist_pool = np.array([j for j in P.index if j not in reserved])   # E 예약분 제외
grp = P.scenario.map(SCEN_GROUP).values
formal = P.persona.isin(FORMAL_PERSONA).values
# 후보 풀이 가장 좁은 response(=task 그룹)부터 배정해 실패를 줄인다
resp_order = sorted(resp_idx, key=lambda i: (grp[i] != 'task', grp[i] != 'emotional'))
assign = {}
for attempt in range(50):
    used = np.zeros(len(P), bool); assign.clear(); ok = True
    for i in resp_order:
        m = (~used[hist_pool]) & (grp[hist_pool] != grp[i]) & (sim[i, hist_pool] < 0.25)
        if not m.any():
            m = (~used[hist_pool]) & (grp[hist_pool] != grp[i]) & (sim[i, hist_pool] < 0.32)
        if not m.any(): ok = False; break
        cands = hist_pool[m]
        same_reg = cands[formal[cands] == formal[i]]
        pool = same_reg if len(same_reg) else cands
        j = int(pool[rng.integers(len(pool))])
        used[j] = True; assign[i] = j
    if ok: break
assert ok, 'derangement 실패'
for i, j in assign.items():
    r, h = P.loc[i], P.loc[j]
    add('cross_scenario', '부적절', h.history, r.response, h.persona, h.scenario,
        f'p{i}', {'orig_no_history': h.no, 'orig_no_response': r.no, 'orig_reason': 'X1'})

# ---------------------------------------------------------------- 7) D/E. 잡담 짝 (적절 U + 부적절 U)
order2 = rng.permutation(len(CASUAL))
for k, r in n1.iterrows():
    persona_c, hist_c = CASUAL[order2[k % len(CASUAL)]]
    add('smalltalk_casual', '적절', hist_c, r.stripped, persona_c, '일상 대화',
        f'n{k}', {'orig_no_history': -1, 'orig_no_response': r.no, 'orig_reason': 'P6'})
    h = P.loc[reserved[k]]
    add('smalltalk_serious', '부적절', h.history, r.stripped, h.persona, h.scenario,
        f'n{k}', {'orig_no_history': h.no, 'orig_no_response': r.no, 'orig_reason': 'X1'})

# ---------------------------------------------------------------- 7) 저장
out = pd.DataFrame(rows)
out.insert(0, 'no', range(1, len(out) + 1))
out = out[['no', 'pair_id', 'source_type', 'label', 'persona', 'scenario',
           'turn_count', 'history', 'response', 'orig_no_history', 'orig_no_response', 'orig_reason']]
out.to_csv('dialogue_context_dataset_v2.csv', index=False, encoding='utf-8-sig')

aux = df[df.reason.isin(['N2', 'N3', 'N4', 'N5']) | (df.label == '적절')].copy()
aux['axis'] = np.where(aux.label == '적절', 'ok', 'pragmatic_issue')
aux.to_csv('pragmatic_quality_dataset_v2.csv', index=False, encoding='utf-8-sig')

print(f'\n메인: {len(out)}행  label={dict(out.label.value_counts())}')
print(f'source_type={dict(out.source_type.value_counts())}')
resp_bal = out.groupby('response').label.nunique()
print(f'양쪽 label에 모두 등장하는 response: {(resp_bal == 2).sum()} / 고유 {len(resp_bal)}')
print(f'보조(화용 품질): {len(aux)}행')

# -*- coding: utf-8 -*-
"""
테스트셋 v4 조립 — 난이도 3단계 100쌍 / 200행.
================================================
사용법:
    python build_testset_v4.py                       # CSV 생성
    python build_testset_v4.py --check <학습셋.csv>   # 학습셋과의 누수까지 검사

산출: test_dataset_v4_200.csv
컬럼: no, pair_id, turn_count, history, response, label, difficulty, tag, room
      (앞 6개는 기존 데이터셋과 동일한 필수 스키마. 뒤 3개는 분석용 추가 컬럼)

설계 근거 — 기존 test_dataset_100.csv의 문제:
    부적절 50건 중 48건이 history와 어절 겹침 0이었다. 즉 어휘가 통째로 다른
    도메인에서 온 응답이라, 글자 2-gram 겹침만으로 AUC 0.96이 나왔다.
    모델의 문맥 판단 능력을 변별하지 못한다.

v4의 대응:
    두 방을 얼마나 비슷하게 잡느냐로 난이도를 만든다. hard 구간은 같은 도메인
    안에서 요일·시간·수량·대상만 다르게 해서, 어휘 겹침으로는 풀 수 없게 했다.
    난이도별 점수를 따로 보면 모델이 어디서 무너지는지가 드러난다.

교차(swap) 구조의 부수 효과:
    모든 response가 적절/부적절 양쪽으로 정확히 한 번씩 등장하므로
    response-only / history-only 누수가 구조적으로 0이다.
"""
import sys
import pandas as pd

from rooms_v4 import QUADS

NO_START = 2001          # 학습셋(1~1000), 기존 테스트셋(1001~1100)과 겹치지 않게
OUT = 'test_dataset_v4_200.csv'
DIFF_CODE = {'easy': 'E', 'medium': 'M', 'hard': 'H'}


def build():
    rows = []
    no = NO_START
    seq = {'easy': 0, 'medium': 0, 'hard': 0}

    for q in QUADS:
        d = q['diff']
        seq[d] += 1
        base = f"V4{DIFF_CODE[d]}{seq[d]:02d}"

        # A방: rA가 적절, B방 응답인 rB가 잘못 들어오면 부적절
        # B방: rB가 적절, A방 응답인 rA가 잘못 들어오면 부적절
        for room, hist, ok, bad in (('A', q['hA'], q['rA'], q['rB']),
                                    ('B', q['hB'], q['rB'], q['rA'])):
            tc = len([l for l in hist.split('\n') if l.strip()])
            pid = f"{base}{room}"
            for resp, label in ((ok, '적절'), (bad, '부적절')):
                rows.append(dict(no=no, pair_id=pid, turn_count=tc,
                                 history=hist, response=resp, label=label,
                                 difficulty=d, tag=q['tag'], room=room))
                no += 1
    return pd.DataFrame(rows)


def integrity(df):
    """이 검사를 통과하지 못하면 CSV를 쓰지 않는다."""
    errs = []

    if len(df) != 200:
        errs.append(f"행 수가 200이 아님: {len(df)}")
    if df.pair_id.nunique() != 100:
        errs.append(f"쌍 수가 100이 아님: {df.pair_id.nunique()}")

    g = df.groupby('pair_id')
    if not (g.size() == 2).all():
        errs.append("2행이 아닌 쌍이 있음")
    if not g.history.nunique().eq(1).all():
        errs.append("한 쌍 안에서 history가 다름")
    if not g.label.apply(lambda s: set(s) == {'적절', '부적절'}).all():
        errs.append("한 쌍이 적절/부적절 한 쌍으로 구성되지 않음")

    # history가 '나:'로 끝나면 다음 화자가 '나'라는 전제가 깨진다
    bad = [h for h in df.history.unique()
           if h.strip().split('\n')[-1].split(':')[0].strip() == '나']
    if bad:
        errs.append(f"history가 '나:'로 끝나는 방 {len(bad)}개")

    # 교차 구조의 핵심: 모든 response가 양쪽 label로 등장해야 한다
    per_resp = df.groupby('response').label.nunique()
    if not (per_resp == 2).all():
        n = (per_resp != 2).sum()
        errs.append(f"한쪽 label로만 등장하는 response {n}개 (response-only 누수)")

    per_hist = df.groupby('history').label.nunique()
    if not (per_hist == 2).all():
        errs.append("한쪽 label로만 등장하는 history 있음 (history-only 누수)")

    if dict(df.label.value_counts()) != {'적절': 100, '부적절': 100}:
        errs.append(f"label 불균형: {dict(df.label.value_counts())}")

    want = {'easy': 60, 'medium': 80, 'hard': 60}   # 쌍 수 ×2행
    got = dict(df.difficulty.value_counts())
    if got != want:
        errs.append(f"난이도 분포가 목표와 다름: {got} (목표 {want})")

    if df.response.nunique() != 100:
        errs.append(f"고유 response가 100이 아님: {df.response.nunique()}")

    return errs


def leakage_check(df, train_path):
    """학습셋과의 중복 검사. 하나라도 걸리면 테스트셋으로 못 쓴다."""
    tr = pd.read_csv(train_path, encoding='utf-8-sig')
    norm = lambda s: s.astype(str).str.replace(r'\s+', ' ', regex=True).str.strip()
    th, tr_r = set(norm(tr.history)), set(norm(tr.response))
    h, r = norm(df.history), norm(df.response)
    pair = h + '||' + r
    tpair = set(norm(tr.history) + '||' + norm(tr.response))
    return {
        'history 중복': int(h.isin(th).sum()),
        'response 중복': int(r.isin(tr_r).sum()),
        '(history,response) 중복': int(pair.isin(tpair).sum()),
    }


def main():
    df = build()

    errs = integrity(df)
    if errs:
        print('무결성 검사 실패:')
        for e in errs:
            print('  -', e)
        sys.exit(1)

    if '--check' in sys.argv:
        train = sys.argv[sys.argv.index('--check') + 1]
        leak = leakage_check(df, train)
        print(f'학습셋 대조: {train}')
        for k, v in leak.items():
            print(f'  {k:24s} {v}')
        if any(leak.values()):
            print('  → 누수 발견. CSV를 쓰지 않고 중단합니다.')
            sys.exit(1)
        print()

    # 기존 데이터셋과 동일하게 history 줄바꿈은 CRLF, 인코딩은 utf-8-sig
    out = df.copy()
    out['history'] = out.history.str.replace('\n', '\r\n', regex=False)
    out.to_csv(OUT, index=False, encoding='utf-8-sig')

    print(f'{OUT} 생성 — {len(out)}행 / {out.pair_id.nunique()}쌍')
    print(f'  label      : {dict(out.label.value_counts())}')
    print(f'  난이도(행) : {dict(out.difficulty.value_counts())}')
    print(f'  turn_count : {dict(sorted(out.turn_count.value_counts().items()))}')
    print(f'  고유 방     : {out.history.nunique()}개 / 고유 response {out.response.nunique()}개')


if __name__ == '__main__':
    main()

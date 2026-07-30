# -*- coding: utf-8 -*-
"""학습된 모델과 데이터셋을 HuggingFace Hub에 올린다.

카드의 모든 수치는 train_out/report.json 과 slices_recovered.json 에서 생성한다 —
손으로 옮기면 재학습 후 카드가 조용히 거짓이 된다.

사용법:
  python training/hf_upload.py --owner agii0114                 # 기본: private, 모델+데이터셋
  python training/hf_upload.py --owner agii0114 --dry-run       # 카드만 출력하고 업로드 안 함
  python training/hf_upload.py --owner agii0114 --only model    # 모델만
  python training/hf_upload.py --owner agii0114 --public        # 공개로 (기본은 private)

토큰: 환경변수 HF_TOKEN, 없으면 프로젝트 루트 .env의 HF_TOKEN, 없으면 hf auth login 저장분.
"""
import argparse, json, os, pathlib, re, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_token():
    """환경변수 -> .env -> hf 저장 토큰 순. 값은 절대 출력하지 않는다."""
    tok = os.environ.get('HF_TOKEN') or os.environ.get('HUGGINGFACE_HUB_TOKEN')
    if tok:
        return tok.strip(), 'env'
    env = ROOT / '.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8').splitlines():
            m = re.match(r'^\s*HF_TOKEN\s*=\s*(.+)\s*$', line)
            if m and m.group(1).strip():
                return m.group(1).strip(), '.env'
    return None, 'hf auth login'   # HfApi가 저장 토큰을 자체적으로 찾는다


def pct(x):
    return f'{x * 100:.1f}%'


def metrics_table(m):
    return ('| threshold | accuracy | precision | recall | f1 | flag_rate |\n'
            '|---|---|---|---|---|---|\n'
            f"| {m['threshold']} | {m['accuracy']} | {m['precision']} | "
            f"{m['recall']} | {m['f1']} | {m['flag_rate']} |")


def base_rate_table(oof_csv, thr):
    """실전 기저율별 precision. 데이터셋 50/50 분포의 precision은 실전값이 아니다."""
    import csv
    rows = list(csv.DictReader(open(oof_csv, encoding='utf-8-sig')))
    y = [1 if r['label'] == '부적절' else 0 for r in rows]
    p = [float(r['prob_inappropriate']) for r in rows]
    pos = [pi for pi, yi in zip(p, y) if yi == 1]
    neg = [pi for pi, yi in zip(p, y) if yi == 0]
    tpr = sum(1 for x in pos if x >= thr) / len(pos)
    fpr = sum(1 for x in neg if x >= thr) / len(neg)
    out = ['| 실전 오발송 비율 | precision | 전체 메시지 중 팝업률 |', '|---|---|---|']
    for b in (0.50, 0.10, 0.05, 0.02, 0.01, 0.005):
        fr = b * tpr + (1 - b) * fpr
        out.append(f'| {pct(b)} | {pct(b * tpr / fr)} | {pct(fr)} |')
    return '\n'.join(out), tpr, fpr


def slices_table(slices, prefix):
    """부적절(양성) 0건인 슬라이스는 precision/recall이 정의되지 않는다 — 0.0으로 적으면
    '성능이 0'과 구별되지 않으므로 `—`로 두고 accuracy/flag_rate만 보여준다."""
    rows = [(k, v) for k, v in slices.items() if k.startswith(prefix)]
    if not rows:
        return '_(해당 슬라이스 없음)_'
    out = [f'| {prefix} | n | 부적절 | precision | recall | accuracy | flag_rate |',
           '|---|---|---|---|---|---|---|']
    any_undef = False
    for k, v in sorted(rows, key=lambda kv: -kv[1]['n']):
        undef = v.get('n_pos', 1) == 0
        any_undef |= undef
        prec = '—' if undef else v['precision']
        rec = '—' if undef else v['recall']
        out.append(f"| `{k.split('=', 1)[1]}` | {v['n']} | {v.get('n_pos', '?')} | "
                   f"{prec} | {rec} | {v['accuracy']} | {v['flag_rate']} |")
    if any_undef:
        out.append('')
        out.append('`—` 는 그 슬라이스에 부적절 행이 0건이어서 precision/recall이 정의되지 '
                   '않는다는 뜻이다(성능 0이 아니다). 그 슬라이스에서 읽어야 할 값은 '
                   '`flag_rate` — 전부 정상 메시지이므로 이것이 곧 오경보율이다.')
    return '\n'.join(out)


def false_alarm_note(sl):
    """정상 메시지만 있는 슬라이스끼리 flag_rate를 비교한다 — 그게 곧 오경보율이다.
    문장의 숫자를 손으로 적지 않기 위해 데이터에서 만든다."""
    neg_only = {k.split('=', 1)[1]: v for k, v in sl.items()
                if k.startswith('source_type') and v.get('n_pos') == 0}
    if len(neg_only) < 2:
        return ''
    worst = max(neg_only.items(), key=lambda kv: kv[1]['flag_rate'])
    others = ' / '.join(f"`{k}` {v['flag_rate']}" for k, v in
                        sorted(neg_only.items(), key=lambda kv: kv[1]['flag_rate'])
                        if k != worst[0])
    return (f"- **오경보가 특정 맥락에 몰릴 수 있다** — 정상 메시지만 있는 슬라이스의 "
            f"`flag_rate`(= 오경보율)를 비교하면 {others} 인데 "
            f"**`{worst[0]}` 은 {worst[1]['flag_rate']}** 다 "
            f"({worst[1]['n']}건 중 {round(worst[1]['flag_rate'] * worst[1]['n'])}건 오경보). "
            f"표본이 작아 단정할 수 없지만 확인이 필요한 신호.\n")


def build_model_card(rep, sl, base_tbl, tpr, fpr, ds_repo):
    at = rep['at_chosen']
    return f"""---
language: ko
license: apache-2.0
base_model: {rep['model']}
library_name: transformers
pipeline_tag: text-classification
tags:
- korean
- cross-encoder
- dialogue-context
- text-classification
---

# career-jikimi 문맥 적절성 분류기

대화 문맥을 보고 **채팅방을 착각해 잘못 보내려는 메시지**를 전송 전에 잡아내는 cross-encoder.

`[CLS] history [SEP] response` 를 입력받아 "부적절"(= 이 방에 맞지 않는 메시지) 확률을 낸다.
`{rep['model']}` ({rep['max_len']} 토큰까지 사용) 에 2-클래스 분류 헤드를 붙여 파인튜닝했다.

## ⚠️ 먼저 읽을 것 — 이 모델을 그대로 배포하지 말 것

아래 precision {at['precision']} 은 **평가 데이터가 부적절 50% 로 설계된 분포에서의 값**이다.
실서비스에서 오발송은 희귀하므로, 같은 모델·같은 threshold 라도 precision 은 아래처럼 떨어진다:

{base_tbl}

threshold {rep['chosen_threshold']} 에서 recall {tpr:.3f}, **FPR {fpr:.4f}** (정상 메시지를 막는 비율).
기저율이 낮아지면 이 FPR 이 precision 을 삼킨다.

threshold 를 올려도 잘 해결되지 않는다 — precision 0.95 를 되찾으려면 0.9999 까지 올려야 하고
그 지점의 recall 은 약 0.21 이다. 게다가 그 추정은 "정상 500건 중 오경보 0건" 관측에 기대고
있어(95% 상한 FPR 0.6%) 신뢰 구간이 매우 넓다. **500건 표본으로는 낮은 기저율의 운영점을
정할 수 없다.** 실사용 로그로 실제 오발송 빈도를 먼저 측정해야 한다.

## 사용법

```python
import json, torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL = '{{REPO_ID}}'
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL).eval()
threshold = 0.5   # 운영값은 threshold.json 참고 (아래)

history = '\\n'.join([
    '팀장: 내일 배포 일정 확인해주세요.',
    '나: 네, 오전 중으로 정리하겠습니다.',
    '팀장: 롤백 계획도 포함해주세요.',
])
candidate = '오늘 저녁 치킨 ㄱ? 양념 반 후라이드 반 어때 ㅋㅋ'

with torch.no_grad():
    enc = tok(history, candidate, truncation=True, max_length={rep['max_len']}, return_tensors='pt')
    prob = torch.softmax(model(**enc).logits.float(), -1)[0, 1].item()

print(('부적절' if prob >= threshold else '적절'), round(prob, 4))
```

운영 threshold 는 리포지토리의 `threshold.json` 에 들어 있다
(`{{"threshold": {rep['chosen_threshold']}, "target_precision": 0.95}}`).
**위 기저율 표를 보고 자기 서비스의 분포에 맞게 다시 정할 것** — 이 값을 그대로 쓰지 말 것.

## 학습 설정

| 항목 | 값 |
|---|---|
| base model | `{rep['model']}` (ModernBERT, 149M) |
| 데이터 | {rep['rows']}행 (부적절 50% / 적절 50%, 500 pair) |
| 분할 | StratifiedGroupKFold({rep['folds']}), 그룹 = `pair_id` |
| epochs / lr | {rep['epochs']} / {rep['lr']} |
| max_len | {rep['max_len']} |
| 정밀도 | fp32 가중치 + CUDA autocast 혼합정밀도 |

## 평가 — {rep['folds']}-fold out-of-fold 예측

**OOF ROC-AUC = {rep['oof_auc']}** (어휘 baseline 0.725, 관계특징 baseline 0.687 대비)

목표 precision 0.95 를 만족하는 최저 threshold = **{rep['chosen_threshold']}**

{metrics_table(at)}

threshold 0.5 기준:

{metrics_table(rep['at_0.5'])}

### 난이도별 — `difficulty=hard` 가 무너지는지가 핵심 진단

{slices_table(sl, 'difficulty')}

`hard` 는 "같은 회사 프로젝트방끼리", "같은 대학 반말 단체방" 처럼 어휘·격식만으로는 못 풀고
인명·일정 같은 개체 추적이 필요한 교차 쌍이다. 여기서 precision 이 유지된 것은 모델이 표면
특징이 아니라 문맥을 보고 있다는 신호다.

### source_type 별

{slices_table(sl, 'source_type')}

## 왜 이 점수를 신뢰할 수 있는가 (그리고 어디까지만)

**신뢰할 수 있는 부분 — 우회 학습이 구조적으로 막혀 있다.** 학습 데이터는 500 pair 전부
"적절 1 + 부적절 1" 짝이고, 그중 372 pair 는 **같은 response 에 history 만 다르다.**
즉 응답 문장만 보고 맞히는 것이 불가능하다. 데이터셋 문서의 검증값도 이를 뒷받침한다
(response-only 0.500, history-only 0.508, history 셔플 0.500).

**낙관적인 부분 — fold 간 문맥 누출.** 분할은 `pair_id` 단위인데, 데이터셋의 v2.5 확장분은
방 16개의 history 가 각 14회 반복된다. 그 결과 **검증 행의 63.2% 가 학습에서 이미 본 history** 다.
라벨 직접 누출은 아니지만(history-only = 0.500), 방 고유 내용(인명·날짜·화제)을 외울 수 있다.
실서비스에서는 모든 방이 처음 보는 방이므로 이 이점이 사라진다.
데이터셋 문서가 권한 `room_id` 단위 분할로 재평가하는 것이 다음 과제다.

## 한계

- **합성 데이터로만 학습했다.** 실사용 로그 검증이 없다.
- **history 다양성이 좁다** — v2.5 확장분은 방 16개뿐. 현재 최대 병목.
{false_alarm_note(sl)}- `turn_count` 1~15 범위로 학습했다. 훨씬 긴 문맥은 검증되지 않았다.
- 한국어 전용.
- `source_type` 은 라벨과 얽혀 있다(`matched*` 는 전부 적절, `cross_scenario`·`misdirect_v25` 는
  전부 부적절). 슬라이스 표를 읽을 때 `부적절` 열을 먼저 볼 것.

## 데이터셋

[`{ds_repo}`]({{DS_URL}})

## 라이선스

base model `{rep['model']}` 의 apache-2.0 을 따른다. 학습 데이터의 라이선스는 별도로
데이터셋 리포지토리를 참고할 것.
"""


def build_dataset_card(rep, sl, model_repo):
    return f"""---
language: ko
task_categories:
- text-classification
tags:
- korean
- dialogue
- context-appropriateness
- counterfactual-pairs
size_categories:
- 1K<n<10K
---

# career-jikimi 대화 문맥 적절성 데이터셋 (v3)

"이 대화방에서 이 메시지가 적절한가" 를 판정하는 이진 분류 데이터셋. 채팅방을 착각해
잘못 보낸 메시지를 감지하는 태스크를 위해 만들었다.

## 이 데이터셋의 핵심 — 반사실 짝 구조

**{rep['rows']}행 = 500 pair × 2행이고, 모든 pair 가 "적절 1 + 부적절 1" 이다.**

| 구성 | pair 수 |
|---|---|
| 같은 `response` + 다른 `history` | 372 |
| 같은 `history` + 다른 `response` | 128 |

그래서 **응답 문장만 보고, 또는 문맥만 보고 라벨을 맞히는 것이 구조적으로 불가능하다.**
이것이 표면 특징 학습을 막는 장치이며, 원 데이터셋 문서에 검증값이 기록되어 있다:

| baseline | 점수 | 기준 |
|---|---|---|
| response-only | 0.500 | ≤ 0.55 |
| history-only | 0.508 | ≤ 0.55 |
| history 셔플 | 0.500 | ≤ 0.60 |
| 관계 특징 (어휘 + 격식) | 0.687 | 표면 특징보다 높을 것 |

부적절 행은 방 A 의 응답을 방 B 로 옮겨 만든다 — 실제 오발송과 같은 형태다.
모든 응답에는 **방 고유 앵커**(인명·날짜·사물)가 최소 1개 들어 있다. "응 알겠어" 같은
일반 맞장구는 어느 방에서도 적절해서 부적절 라벨이 성립하지 않으므로 배제했다.

## 파일

| 파일 | 컬럼 |
|---|---|
| `training_dataset_v3_1000.csv` | `no`, `pair_id`, `source`, `source_type`, `difficulty`, `turn_count`, `history`, `response`, `label` |
| `training_dataset_v3_1000_simple.csv` | 위에서 `source`/`source_type`/`difficulty` 를 뺀 것 |

두 파일은 **공유 컬럼이 행 단위로 완전히 동일하다.** `_simple` 은 학습에만 쓸 때를 위한 것이고,
슬라이스 분석을 하려면 전체 파일을 써야 한다.

- `label` — `적절` / `부적절`
- `pair_id` — **분할 그룹 키.** 같은 pair 의 두 행을 train/test 로 가르면 평가가 무의미해진다
- `difficulty` — `hard`/`medium`/`easy` (v2.5 확장분 112행에만 있음), 평가 슬라이스 전용
- `history` — `화자: 내용` 을 줄바꿈으로 이은 문자열
- 모델 입력은 `history` + `response` 만. 나머지는 분석 전용

## 분포

| 항목 | 값 |
|---|---|
| 행 / pair | {rep['rows']} / 500 |
| 라벨 | 적절 500 / 부적절 500 |
| 서로 다른 `history` | 414 |
| `turn_count` | 1~15 (최다 3턴) |
| `response` 길이 | 평균 46자 (15~125) |
| `source` | v2 520 / v25 224 / ext100 256 |
| `difficulty` (라벨된 112행) | hard 56 / medium 42 / easy 14 |

## 사용법

```python
from datasets import load_dataset

ds = load_dataset('{{REPO_ID}}', data_files='training_dataset_v3_1000.csv')['train']
print(ds[0]['history'])
print(ds[0]['response'], '->', ds[0]['label'])
```

**분할은 반드시 `pair_id` 그룹 단위로 한다:**

```python
from sklearn.model_selection import StratifiedGroupKFold
import pandas as pd

df = pd.read_csv('training_dataset_v3_1000.csv', encoding='utf-8-sig')
y = (df.label == '부적절').astype(int)
skf = StratifiedGroupKFold(5, shuffle=True, random_state=42)
for tr, va in skf.split(df, y, groups=df.pair_id):   # groups 를 빠뜨리면 안 된다
    ...
```

## 벤치마크

이 데이터로 `{rep['model']}` 를 파인튜닝한 결과 (5-fold OOF):

| 지표 | 값 |
|---|---|
| ROC-AUC | {rep['oof_auc']} |
| precision @ threshold {rep['chosen_threshold']} | {rep['at_chosen']['precision']} |
| recall @ 같은 threshold | {rep['at_chosen']['recall']} |
| `difficulty=hard` precision | {(sl.get('difficulty=hard') or {}).get('precision', 'n/a')} |

모델: [`{model_repo}`]({{MODEL_URL}})

## 알려진 한계

- **합성 데이터다.** 방과 대화를 직접 작성해 만들었고 실제 채팅 로그가 아니다.
  카톡체·오타·축약은 모사이며 실제 사용자 분포와 다를 수 있다.
- **`history` 다양성이 좁다** — v2.5 확장분은 방 16개뿐이고 각 history 가 14행에 반복된다.
  그래서 `pair_id` 분할만으로는 **fold 간 문맥 누출이 63.2%** 다(같은 history 가 train/val 양쪽에).
  더 보수적으로 평가하려면 방 단위로 나눠야 하지만, 이 v3 파일에는 `room_id` 컬럼이 없다.
  **이 데이터로 낸 점수는 그만큼 낙관적으로 읽어야 한다.**
- **라벨 분포가 50/50 이다.** 실서비스의 오발송은 희귀하므로, 여기서 얻은 precision 은
  실전 precision 이 아니다. 모델 카드의 기저율 표를 볼 것.
- 한국어 전용.

## 라이선스

미정. 공개 전에 정할 것.
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--owner', required=True)
    ap.add_argument('--model-name', default='career-jikimi-context-guard')
    ap.add_argument('--dataset-name', default='career-jikimi-dialogue-context')
    ap.add_argument('--model-dir', default='train_out/final_model')
    ap.add_argument('--report', default='train_out/report.json')
    ap.add_argument('--slices', default='train_out/slices_recovered.json')
    ap.add_argument('--oof', default='train_out/oof_predictions.csv')
    ap.add_argument('--public', action='store_true', help='기본은 private')
    ap.add_argument('--only', choices=['model', 'dataset'], help='한쪽만')
    ap.add_argument('--dry-run', action='store_true', help='카드만 만들고 업로드 안 함')
    args = ap.parse_args()

    rep = json.loads((ROOT / args.report).read_text(encoding='utf-8'))
    sl = rep.get('slices') or {}
    if not sl:   # simple CSV 학습분은 slices 가 비어 있다 -> 복원 파일 사용
        sp = ROOT / args.slices
        if sp.exists():
            sl = json.loads(sp.read_text(encoding='utf-8'))['slices']
        else:
            print(f'경고: slices 가 비어 있고 {sp} 도 없다 — 카드의 슬라이스 표가 빠진다',
                  file=sys.stderr)

    model_repo = f'{args.owner}/{args.model_name}'
    ds_repo = f'{args.owner}/{args.dataset_name}'
    model_url = f'https://huggingface.co/{model_repo}'
    ds_url = f'https://huggingface.co/datasets/{ds_repo}'

    base_tbl, tpr, fpr = base_rate_table(ROOT / args.oof, rep['chosen_threshold'])

    mcard = (build_model_card(rep, sl, base_tbl, tpr, fpr, ds_repo)
             .replace('{REPO_ID}', model_repo).replace('{DS_URL}', ds_url))
    dcard = (build_dataset_card(rep, sl, model_repo)
             .replace('{REPO_ID}', ds_repo).replace('{MODEL_URL}', model_url))

    out = ROOT / 'train_out' / 'hf_cards'
    out.mkdir(parents=True, exist_ok=True)
    (out / 'model_README.md').write_text(mcard, encoding='utf-8')
    (out / 'dataset_README.md').write_text(dcard, encoding='utf-8')
    print(f'카드 생성: {out}/model_README.md ({len(mcard)}자), '
          f'{out}/dataset_README.md ({len(dcard)}자)')

    if args.dry_run:
        print('--dry-run: 업로드하지 않고 종료')
        return

    token, src = load_token()
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    who = api.whoami()
    print(f'인증: {who.get("name")} (토큰 출처 {src}, '
          f'권한 {(who.get("auth") or {}).get("accessToken", {}).get("role")})')

    private = not args.public
    print(f'공개 범위: {"private" if private else "PUBLIC"}')

    if args.only != 'dataset':
        api.create_repo(model_repo, repo_type='model', private=private, exist_ok=True)
        api.upload_folder(folder_path=str(ROOT / args.model_dir), repo_id=model_repo,
                          repo_type='model', commit_message='파인튜닝된 문맥 적절성 분류기')
        api.upload_file(path_or_fileobj=str(out / 'model_README.md'), path_in_repo='README.md',
                        repo_id=model_repo, repo_type='model',
                        commit_message='모델 카드 — 기저율 한계 포함')
        api.upload_file(path_or_fileobj=str(ROOT / args.report), path_in_repo='report.json',
                        repo_id=model_repo, repo_type='model',
                        commit_message='평가 리포트')
        print(f'모델 완료: {model_url}')

    if args.only != 'model':
        api.create_repo(ds_repo, repo_type='dataset', private=private, exist_ok=True)
        for name in ('training_dataset_v3_1000.csv', 'training_dataset_v3_1000_simple.csv'):
            api.upload_file(path_or_fileobj=str(ROOT / 'dataset' / name),
                            path_in_repo=name, repo_id=ds_repo, repo_type='dataset',
                            commit_message=f'{name} 추가')
        api.upload_file(path_or_fileobj=str(out / 'dataset_README.md'), path_in_repo='README.md',
                        repo_id=ds_repo, repo_type='dataset',
                        commit_message='데이터셋 카드 — 짝 구조와 누출 한계 포함')
        print(f'데이터셋 완료: {ds_url}')


if __name__ == '__main__':
    main()

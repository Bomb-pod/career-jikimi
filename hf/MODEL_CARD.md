---
language: ko
license: apache-2.0
base_model: skt/A.X-Encoder-base
pipeline_tag: text-classification
library_name: transformers
tags:
  - korean
  - context-appropriateness
  - misdirected-message
  - cross-encoder
metrics:
  - accuracy
  - precision
  - recall
  - roc_auc
---

# career-jikimi context guard

**채팅방을 착각해 잘못 보낸 메시지를 전송 전에 잡아내는 이진 분류기.**

`(최근 대화 문맥, 보내려는 메시지)`를 함께 받아 **부적합 확률**을 돌려준다.
`skt/A.X-Encoder-base`(ModernBERT, 0.1B)를 cross-encoder 분류기로 파인튜닝했다.

- 판정 대상: **방을 착각한 오발송**
- 판정 대상 아님: 욕설·비방, 맞춤법, 응답 품질, 지시 위반

## 사용

```python
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL = "agii0114/career-jikimi-context-guard"
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL).eval()

# 화자는 등장 순서대로 A, B, C… 로 익명화한다 (학습 형식과 반드시 같아야 한다)
history = "A: 내일 배포 리허설 몇 시로 할까요?\nB: 오전 10시면 될 것 같습니다\nA: 롤백 절차도 봐주세요"
candidate = "오늘 저녁에 치킨 어때?"

enc = tok(history, candidate, truncation="only_first", max_length=384, return_tensors="pt")
with torch.no_grad():
    prob = torch.softmax(model(**enc).logits.float(), -1)[0, 1].item()

print(prob, "부적절" if prob >= 0.7 else "적절")
```

**입력 형식을 지켜야 한다.**

| | |
|---|---|
| 화자 라벨 | 등장 순서대로 `A:` `B:` `C:` — 실제 이름·호칭을 넣으면 학습 분포와 어긋난다 |
| 후보 메시지 | **화자 라벨 없이** 본문만 |
| truncation | `only_first` — 잘릴 땐 문맥 앞부분부터. 판정 대상은 온전해야 한다 |
| `max_length` | 384 |
| 라벨 | index 1 = **부적절** |
| 임계값 | **0.7** (아래 § 임계값) |

## 학습

| 항목 | 값 |
|---|---|
| 기반 모델 | `skt/A.X-Encoder-base` (ModernBERT, 0.1B, 16K ctx) |
| 학습 데이터 | 1,000행 (적절 500 / 부적절 500) |
| MAX_LEN | 384 |
| BATCH | 8 |
| LR | 5e-5 |
| EPOCHS | 4 |
| Optimizer | AdamW (weight decay 0.01, linear warmup 10%) |
| Loss | CrossEntropyLoss (이진 분류) |
| 하드웨어 | Colab T4 |

## 평가

**독립 평가셋 100행.** 학습 데이터와 겹치지 않는다 — 아래 § 데이터 오염 참조.

| | 값 |
|---|---|
| AUC | **1.000** |
| accuracy | **1.000** |
| precision | **1.000** |
| recall | **1.000** |
| 지연 (CPU, batch 32) | p50 512ms |

부적절 점수 최소 0.8481 / 적절 점수 최대 0.1613 — **간격 0.687로 완전히 분리**됐다.

### 문맥을 실제로 읽는가 (절제 실험)

응답은 그대로 두고 `history`만 다른 행 것으로 바꿔 다시 판정했다.

| 조건 | AUC |
|---|---|
| 원래 문맥 | 1.000 |
| **문맥 교체** | **0.638** |
| 문맥 제거 | 0.480 |

문맥을 망가뜨리면 판별력이 무너진다. **응답 문체 암기가 아니라는 직접 증거다.**

## 데이터 오염 (data contamination)

**평가셋 100행은 학습 1,000행에 포함되어 있지 않다.** 세 기준으로 확인했다.

| 검사 | 결과 |
|---|---|
| `(history, response)` 완전 일치 | **0 / 100** |
| `response`만 일치 | **0 / 100** |
| `history`만 일치 | **0 / 100** |

학습 중 교차검증도 `pair_id` 그룹 단위로 분할해, 같은 응답을 공유하는 쌍둥이 행이
학습·검증에 갈라지지 않게 했다.

## 임계값

평가셋에서 두 집단이 `[0.1613, 0.8481]` 구간으로 완전히 갈려, **threshold를
0.20~0.80 어디에 두어도 정확도가 1.000**이다. **0.7**을 기본값으로 권장한다 —
적절 쪽 여유(0.539)가 부적절 쪽(0.148)보다 커서 false positive에 보수적이다.

## 한계

**1. 설계 범위 밖은 못 잡는다.** 별도의 hard 평가셋(지시 위반·요청 무시·정보
오해가 주된 100행)에서 AUC 0.728 / recall 0.020이다. 부적절 50건 중 46건이
"같은 방·같은 주제인데 응답 내용이 잘못된" 경우로, 이 모델의 판정 대상이 아니다.

다만 그 셋에서도 **오탐이 0**이다. 모르는 종류를 만나면 조용히 넘어간다.

**2. 같은 방 안의 사실 모순은 못 잡는다.** 날짜·대상·수량만 어긋난 경우
(예: "토요일 가능"이라는 문맥에 "금요일로 잡자")를 놓친다. 학습 데이터의
부적절 예시가 전부 **다른 방 문맥과 결합한 형태**라 배운 적이 없다.

**3. 실사용 precision은 미확인이다.** 평가셋이 50:50이라 낙관적이다. 오탐이
50건 중 0건이지만 FPR이 0이라는 뜻은 아니다 — 0/50의 95% 상한은 0.06이고,
그 값으로 보면 **실제 오발송 비율이 1%일 때 precision은 0.144**까지 떨어진다.
운영 임계값은 실사용 로그로 다시 정해야 한다.

**4. 수렴을 확인하지 않았다.** 4 epoch 고정으로 학습했고 epoch별 성능 곡선을
그리지 않았다. 더 학습하면 나아질 여지가 남아 있을 수 있다.

**5. 평가셋 난이도.** 이 평가셋은 응답만 보고도 84%가 맞는 구조라 난이도가 낮다.
AUC 1.000을 일반적인 성능으로 읽으면 안 된다.

## 학습 데이터에 대하여

응답 표면에 정답이 새지 않도록 **짝 구조**로 설계했다 — 고유 응답 500개가 각각
적절 1회 + 부적절 1회로 등장한다. 그 결과 응답만으로는 원리적으로 맞힐 수 없다
(TF-IDF 기준 0.400).

학습 시 화자 호칭(`팀장:` `선임:` 등 66종)을 **등장 순서대로 A/B/C로 익명화**했다.
서비스가 화자 정보를 모델에 넘기지 않기 때문이고, 부수적으로 검증 성능도
0.855 → 0.890으로 올랐다 — 호칭이 암기 손잡이로 쓰이고 있었다.

데이터셋: [agii0114/career-jikimi-context-dataset](https://huggingface.co/datasets/agii0114/career-jikimi-context-dataset)

## 라이선스

Apache-2.0. 기반 모델 `skt/A.X-Encoder-base`와 동일하다.

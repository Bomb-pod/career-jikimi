# Business Logic Model — judgment-core

`../../../inception/units-generation/unit-of-work.md`의 U2가 수행하는 흐름이다. 배정은 `../../../inception/units-generation/unit-of-work-story-map.md`, 요구사항은 `../../../inception/requirements-analysis/requirements.md`의 FR-6.2·FR-6.3·FR-6.7·FR-7.1~FR-7.5·FR-8.1, 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 서명은 `../../../inception/application-design/component-methods.md`, 프로세스·통신 형태는 `../../../inception/application-design/services.md`가 정한다.

규칙 번호(`BR-*`)는 같은 디렉터리의 `business-rules.md`를, 테이블 구조는 `domain-entities.md`를 가리킨다.

**이 단위는 채팅 앱 없이 단독으로 돈다.** 문맥과 후보 문장을 인자로 받으므로 CLI나 테스트에서 바로 호출할 수 있다. 그것이 이 단위를 DAG에서 앞으로 당긴 이유다.

## W1 · 판정

```
judge(user_id, room_id, context: list[Message], candidate_text) -> JudgeResult

[입력]
   |
   |-- 1. 익명화 — 화자를 윈도우 내 순번 라벨로            (BR-6.2)
   |
   |-- 2. 프롬프트 조립 — system + user                    (BR-6.3)
   |
   |-- 3. judgment_logs INSERT (score/verdict NULL)
   |
   |-- 4. OpenAI 호출  timeout=AI_TIMEOUT_SECONDS
   |        |
   |        +-- 실패 --> 재시도 1회                        (BR-6.7)
   |              |
   |              +-- 또 실패 --> 로그에 latency 기록
   |                              --> Failed(log_id) 반환
   |
   |-- 5. score 클램프 [0.0, 1.0]                          (BR-6.6)
   |
   |-- 6. verdict = score >= threshold ? 부적절 : 적절      (BR-6.5)
   |
   |-- 7. 로그 UPDATE (score, verdict, threshold, 토큰, latency)
   |
   +-- 8. Appropriate(score, log_id) 또는
          Inappropriate(score, log_id) 반환
```

<!-- Text fallback: judge는 문맥의 화자를 익명 라벨로 바꾸고, 프롬프트를 조립하고, 판정 로그 행을 먼저 만든 뒤 OpenAI를 호출한다. 실패하면 1회 재시도하고 그래도 실패하면 latency만 기록한 채 Failed를 반환한다. 성공하면 점수를 0에서 1 사이로 클램프하고 임계값과 비교해 판정한 뒤 로그를 갱신하고 결과를 반환한다. -->

**3번이 4번보다 먼저다.** 호출 중 프로세스가 죽어도 시도한 흔적이 남는다.

**예외를 던지지 않는다.** 실패는 `Failed`라는 반환값이다 (BR-6.7).

## 알고리즘: 문맥 익명화

```
입력: context = [
        Message(sender_id=7,  text="내일 회의 몇 시죠?"),
        Message(sender_id=12, text="10시입니다"),
        Message(sender_id=7,  text="자료는 제가 준비할게요"),
      ]
      candidate_sender_id = 12
      candidate_text = "오늘 저녁에 치킨 어때?"

1. 등장 순서로 라벨 할당
   7  -> "A"   (첫 등장)
   12 -> "B"   (두 번째 등장)

2. 후보 발신자가 문맥에 없으면 다음 라벨을 준다
   (여기서는 12가 이미 B)

3. 직렬화
   A: 내일 회의 몇 시죠?
   B: 10시입니다
   A: 자료는 제가 준비할게요

   [보내려는 메시지] B: 오늘 저녁에 치킨 어때?
```

<!-- Text fallback: 문맥 익명화는 발신자 id를 등장 순서대로 A, B, C 라벨에 대응시킨다. 후보 메시지의 발신자가 문맥에 없으면 다음 라벨을 새로 준다. 직렬화 결과는 라벨과 텍스트만 남고 실제 id나 이름은 전혀 포함하지 않는다. -->

**라벨은 이 윈도우 안에서만 유효하다** (BR-6.2). 같은 사람이 다음 판정에서 다른 라벨을 받을 수 있다. 신원이 새지 않으면서 대화 구조는 보존된다.

라벨이 없으면 모델이 위 예시를 한 사람의 독백으로 읽는다. 화자 전환은 문맥 판단의 핵심 신호다.

## 프롬프트 설계

`application-design`이 형식(ADR-005)만 정하고 문안을 이월했다. 여기서 확정한다.

### system

```
당신은 채팅 메시지가 그 대화방의 문맥에 맞는지 판단합니다.

사용자는 여러 채팅방을 오가며, 가끔 방을 착각해 엉뚱한 방에 메시지를
보냅니다. 당신의 일은 그것을 보내기 전에 알아채는 것입니다.

## 판단 기준

주어진 대화의 흐름·주제·어조에 비추어, 보내려는 메시지가 이 방에서
나올 법한 말인지 판단하십시오.

## 판단하지 않는 것

- 메시지 내용 자체의 적절성(욕설·비방·민감정보 여부)은 판단하지 마십시오.
- 맞춤법·문장의 완성도는 판단하지 마십시오.
- 화제가 바뀌었다는 사실만으로 부적합하다고 보지 마십시오. 대화는
  자연스럽게 화제를 바꿉니다.

## 점수

0.0에서 1.0 사이의 부적합 점수를 매기십시오. 높을수록 이 방에
어울리지 않는다는 뜻입니다.

- 0.0 ~ 0.2  이 대화의 자연스러운 연장
- 0.3 ~ 0.5  화제는 바뀌었으나 같은 관계·상황에서 나올 수 있는 말
- 0.6 ~ 0.8  이 방의 성격과 어긋남
- 0.9 ~ 1.0  명백히 다른 방에 갈 메시지

## 표기

화자는 A, B, C로 익명 표기됩니다. 이 라벨은 이번 판단에만 쓰이는
순번이며 특정 인물을 뜻하지 않습니다.
```

### user

```
## 최근 대화

A: 내일 회의 몇 시죠?
B: 10시입니다
A: 자료는 제가 준비할게요

## 보내려는 메시지

B: 오늘 저녁에 치킨 어때?
```

### 응답 스키마

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "verdict",
    "strict": true,
    "schema": {
      "type": "object",
      "properties": {
        "score": { "type": "number" }
      },
      "required": ["score"],
      "additionalProperties": false
    }
  }
}
```

### 설계 근거

**"판단하지 않는 것"을 명시한 것**이 이 프롬프트의 핵심이다. 없으면 모델이 알아서 욕설을 잡고, 그러면 측정 대상이 둘이 되어 precision 해석이 흐려진다 (BR-6.3, FR-6.7).

**"화제가 바뀌었다는 사실만으로 부적합하다고 보지 마십시오"**를 넣은 이유 — 이걸 빼면 모델이 화제 전환을 전부 부적합으로 잡는다. 대화는 원래 화제가 바뀌고, 그것까지 잡으면 flag rate가 치솟아 기능이 죽는다. precision 우선 방침의 실행이다.

**점수 구간에 언어적 설명을 붙인 것** — 숫자만 요구하면 모델이 0.5 근처로 몰린다. 구간마다 무엇을 뜻하는지 주면 분포가 벌어진다.

**근거 문장을 받지 않는 것** — 스키마를 `score` 하나로 좁혔다. 근거를 받으면 디버깅에 좋지만 토큰과 지연이 늘고, 지금 필요한 것은 점수다. 나중에 스키마를 늘리는 비용은 작다.

**temperature는 낮게 잡는다.** 같은 입력에 같은 점수가 나와야 임계값 조정이 의미를 갖는다.

## W2 · `force_log_id` 검증

```
get_log_for_force(user_id, room_id, log_id, candidate_text) -> JudgmentLog

SELECT * FROM judgment_logs WHERE id = ?
   |
   +-- 없음 ------------------------> InvalidForceToken
   +-- user_id 불일치 --------------> Forbidden
   +-- room_id 불일치 --------------> InvalidForceToken
   +-- user_action IS NOT NULL -----> InvalidForceToken  (소진됨)
   +-- verdict NOT IN (inappropriate, NULL) --> InvalidForceToken
   +-- candidate_text 불일치 -------> InvalidForceToken
   |
   +-- 통과 --> 로그 반환 (호출자가 verdict로 상태를 파생)
```

<!-- Text fallback: force_log_id 검증은 로그를 조회해 존재 여부, 소유자 일치, 방 일치, 미소진 여부, verdict가 inappropriate이거나 NULL인지, 텍스트 일치를 차례로 확인한다. 소유자 불일치만 403이고 나머지는 400이다. verdict가 inappropriate이면 호출자가 flagged_sent로, NULL이면 failed로 상태를 정한다. -->

**텍스트 일치 검사가 `application-design`에서 이월된 구멍의 해소다** (BR-6.9). 없으면 유효한 토큰에 다른 문장을 실어 판정을 건너뛸 수 있다.

비교는 트림 후 정확 일치다. 정규화까지 하면 우회 여지가 생긴다.

## W3 · `user_action` 기록

```
set_user_action(log_id, action)

UPDATE judgment_logs
   SET user_action = ?
 WHERE id = ? AND user_action IS NULL     ← 조건이 핵심
   |
   +-- 영향 행 0 --> AlreadyResolved 예외
   +-- 영향 행 1 --> 성공
```

<!-- Text fallback: user_action 기록은 조건부 UPDATE로 한다. user_action이 NULL인 경우에만 갱신하며, 영향받은 행이 0이면 이미 값이 있다는 뜻이므로 예외를 던진다. -->

**조건절이 1회성을 보장한다** (BR-7.1). SELECT 후 UPDATE로 짜면 동시 요청 둘이 모두 NULL을 보고 모두 갱신한다 — 그것이 더블클릭에 메시지 두 개가 저장되는 경로다.

## W4 · 지표 산출

`compute_metrics(since) -> MetricsReport`

```
집계 대상: judgment_logs WHERE verdict IS NOT NULL   (BR-7.2)
          + messages (신고 관련 지표만)
```

| 지표 | 계산 |
|---|---|
| 판정 건수 | `COUNT(*)` |
| flag rate | `COUNT(verdict='inappropriate') / COUNT(*)` |
| precision | `cancelled / (cancelled + sent)` — 부적절 판정 중 |
| 미응답 건수 | `COUNT(verdict='inappropriate' AND user_action IS NULL)` |
| 지연 분포 | `latency_ms`의 p50 / p95 / max |
| 토큰 합계 | `SUM(prompt_tokens + completion_tokens)` |
| API 실패율 | `COUNT(verdict IS NULL) / COUNT(전체 행)` ← **전체 행 기준** |
| 신고율 | `COUNT(messages.misdirect_reported_at IS NOT NULL) / COUNT(messages)` |
| 미검출 후보 | `COUNT(신고됨 AND verification_status='ok')` |
| **recall** | **`"산출 불가 — 라벨 데이터셋 필요"`** (BR-7.5) |

**API 실패율만 분모가 다르다.** 다른 지표는 `verdict IS NOT NULL`로 거른 뒤 계산하지만, 실패율은 실패를 세는 것이므로 거르기 전의 전체 행을 쓴다.

**precision의 분모가 0이면 `None`을 반환한다** (BR-7.3). 0.0으로 표시하면 성능이 나쁜 것으로 오해된다.

**신고 관련 두 지표만 `messages`를 읽는다.** 이 단위가 다른 테이블을 읽는 유일한 지점이며, 그래서 `compute_metrics()`는 `judge()`와 달리 앱 전체가 있어야 의미가 있다.

### 리포트 출력 (ADR-008 — CLI)

```
$ docker compose exec app python -m app.judgment.report

판정 기간: 2026-07-29 ~ 2026-08-04
─────────────────────────────────────────────
판정 건수          142
flag rate         18.3%  (26/142)
precision         0.769  (TP 20 / FP 6)     ※ 근사 — ASM-1 참조
미응답             3건   ← 팝업 무시 신호
지연              p50 1.2s  p95 3.4s  max 4.9s
토큰              38,410  (프롬프트 35,120 / 응답 3,290)
API 실패율         2.1%  (3/145)
신고율             1.4%  (2/143)
미검출 후보        1건   ← 모델이 ok라 했는데 사용자가 신고
recall            산출 불가 — 라벨 데이터셋 필요
─────────────────────────────────────────────
※ precision은 user_action을 정답 라벨로 삼은 근사치입니다.
  취소가 판정 동의인지 단순 회피인지 구별하지 못합니다.
```

**precision 옆에 항상 근사 표시를 붙인다** (ASM-1). 숫자만 보면 정확한 측정값으로 읽힌다.

## 단독 검증 경로

이 단위를 앞으로 당긴 값어치는 여기서 나온다.

```
$ python -m app.judgment.try \
    --context "내일 회의 몇 시죠?" "10시입니다" "자료는 제가 준비할게요" \
    --candidate "오늘 저녁에 치킨 어때?"

score: 0.82  → 부적절 (threshold 0.7)
latency: 1.4s   tokens: 312/8
```

채팅 UI도, 방도, 사용자도 필요 없다. **프롬프트를 고치고 바로 다시 돌릴 수 있다.**

이 CLI로 문맥 몇 벌을 손으로 만들어 돌려보는 것이 프롬프트 튜닝의 실질적 방법이다. 앱이 완성되기를 기다릴 필요가 없다.

## Assumptions & Open Questions

- **프롬프트 문안은 초안이다.** 위 CLI로 실제 대화를 넣어보며 조정해야 한다. 특히 점수 구간 설명이 실제로 분포를 벌리는지 확인되지 않았다.
- Structured Outputs를 지원하는 모델 ID를 확정하지 않았다. Code Generation에서 확인한다.
- `temperature`의 구체적 값을 정하지 않았다. 0에 가깝게 잡되 0이 최선인지는 실험해야 한다.
- 프롬프트가 한국어다. 영어로 쓰면 토큰이 줄지만 판정 대상이 한국어 대화라 언어를 맞추는 편이 자연스러울 것으로 보인다 — 검증되지 않았다.
- 문맥에 매우 긴 메시지가 섞이면 토큰이 급증한다. 메시지 길이 상한이 요구사항에 없다.
- `try` CLI는 요구사항에 없는 개발 도구다. 만들지 않아도 FR은 충족되나, 만들지 않으면 이 단위를 앞으로 당긴 의미가 절반 사라진다.

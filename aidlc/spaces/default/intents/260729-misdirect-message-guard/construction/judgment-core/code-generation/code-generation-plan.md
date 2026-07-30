# Code Generation Plan — judgment-core (U2)

**이 프로젝트가 증명하려는 것이 이 단위에 있다.**

`../functional-design/`의 세 문서가 권위다. `business-logic-model.md`가 워크플로 4개·익명화 알고리즘·**확정된 프롬프트 문안**을, `business-rules.md`가 규칙 16개를, `domain-entities.md`가 `judgment_logs`의 불변식을 정한다.

| 무엇 | 어디 |
|---|---|
| W1 판정, W2 `force_log_id` 검증, W3 `user_action`, W4 지표, 프롬프트 문안, `try` CLI | `../functional-design/business-logic-model.md` |
| BR-6.1~BR-6.9, BR-7.1~BR-7.6 | `../functional-design/business-rules.md` |
| `judgment_logs` 불변식과 생애주기 | `../functional-design/domain-entities.md` |
| 대응 요구사항 | `../../../inception/requirements-analysis/requirements.md` — FR-6.2·FR-6.3·FR-6.7·FR-7.1~FR-7.5·FR-8.1 |
| Structured Outputs 형식 | `../../../inception/application-design/decisions.md` ADR-005, CLI 노출은 ADR-008 |

**테이블은 이미 있다.** U1의 `0001_initial_schema`가 `judgment_logs`를 만들었다. 마이그레이션을 새로 만들지 않는다.

**이 단위는 `users`·`rooms`를 읽지 않고 조인하지 않는다.** 문맥은 U5가 조회해 인자로 넘긴다. 그래서 채팅 앱 없이 돈다 — 그것이 이 단위를 DAG에서 앞으로 당긴 값어치다. 예외는 `compute_metrics()`의 신고 관련 두 지표뿐이며, 그것만 `messages`를 읽는다.

**프론트엔드 몫이 없다.** UI가 없는 유일한 서비스 단위다. 백엔드 순서만 따른다.

---

## ADR-005의 확인 항목 — 닫았다

ADR-005가 "Structured Outputs를 지원하는 모델을 써야 한다. **Code Generation에서 모델 ID와 지원 여부를 확인한다**"로 이월한 항목이다.

**확인 결과: `gpt-4o-mini`는 지원한다.** `response_format: {type: "json_schema", json_schema: {..., strict: true}}`가 `gpt-4o-mini-2024-07-18` 이후와 `gpt-4o-2024-08-06` 이후에서 동작한다. `.env.example`의 기본값 `gpt-4o-mini`가 유효하다.

별칭(`gpt-4o-mini`)을 그대로 쓰고 날짜 스냅샷으로 고정하지 않는다 — 환경변수라 언제든 바꿀 수 있고, 별칭이 지원 스냅샷을 가리킨다. 다만 **모델이 `json_schema`를 거부하면 그것을 판정 실패로 조용히 삼키지 않는다** (아래 결정 표 참조).

---

## 이 계획이 닫는 열린 항목

| 열린 항목 | 결정 | 근거 |
|---|---|---|
| **`AI_TIMEOUT_SECONDS`의 기본값 3인지 5인지** | **4로 바꾼다.** `.env.example`과 `.env`의 현재 값 `5`는 **결함이다** | `business-rules.md` BR-6.7이 "총 상한 10초를 넘지 않는다"이고 그 문서 스스로 "10초를 지키려면 4 이하여야 한다"고 계산해두었다. 5면 재시도 포함 대기가 정확히 10초이고 연결 수립·직렬화 오버헤드가 그 위에 얹혀 **NFR-1의 최악 10초를 넘긴다.** 4면 8초 + 오버헤드로 여유가 남는다 |
| 429의 `Retry-After` 존중 여부 | **남은 예산 안에서만 존중한다.** `Retry-After`가 남은 예산을 넘으면 대기하지 않고 즉시 `Failed` | BR-6.7의 총 상한 10초와 NFR-1이 우선한다. 서버가 30초를 기다리라 해도 사용자를 30초 세울 수는 없다 |
| `temperature` 값 | **0** | BR-6.5의 임계값 조정이 의미를 가지려면 같은 입력에 같은 점수가 나와야 한다. 환경변수로 빼지 않는다 — 튜닝 대상은 프롬프트와 임계값이고, 재현성은 고정값이어야 지켜진다 |
| precision 분모가 0일 때 리포트 표시 | **`"산출 불가 — 부적절 판정 건이 없음"`** | BR-7.3이 `None` 반환을, BR-7.5가 recall의 문구를 정했으나 precision의 표시는 미정이었다. recall과 **다른 문구**를 쓴다 — 원인이 다르다(recall은 원리적 불가, precision은 표본 부재). 0.0으로 표시하지 않는다 |
| 프롬프트 언어 | **한국어 유지** | 판정 대상이 한국어 대화다. 토큰은 늘지만 언어를 맞추는 편이 자연스럽다. **검증되지 않은 가정**이며 `try` CLI가 이것을 실험하는 도구다 |
| `try` CLI를 만들지 | **만든다** | 요구사항에 없는 개발 도구지만, 없으면 이 단위를 앞으로 당긴 의미가 절반 사라진다. 채팅 UI 없이 프롬프트를 고치고 바로 돌려보는 것이 이 단위의 존재 이유다 |
| 익명 라벨의 윈도우 한정 | **그대로** (조치 없음) | BR-6.2가 이미 정했다. 품질 영향은 `try` CLI로 관찰할 항목이다 |

### 새로 추가되는 의존성

`backend/requirements.txt`에 한 줄. **ASCII 유지**(pip이 Windows에서 로케일 코드페이지로 읽는다).

| 패키지 | 왜 |
|---|---|
| `openai` | 공식 SDK. `strict: true` Structured Outputs와 per-request 타임아웃을 지원한다 |

---

## U1·U3이 남긴 계약

| 이름 | 어디서 | 주의 |
|---|---|---|
| `settings` | `app.core.config` | `OPENAI_API_KEY`가 **`SecretStr`** 이다. `.get_secret_value()` |
| `get_session()` | `app.core.db` | 핸들러 성공 시 자동 커밋 |
| `DomainError` 계열 | `app.core.errors` | 이 단위의 예외를 등록 |
| `current_user()` | `app.auth` | `PATCH /judgments/{id}` 라우터가 쓴다 |

`app/main.py`의 라우터 등록 지점은 **SPA catch-all보다 먼저**다.

---

## `JudgeResult` — 호출자가 분기하는 유일한 것

```python
@dataclass(frozen=True)
class Appropriate:   score: float; log_id: int
@dataclass(frozen=True)
class Inappropriate: score: float; log_id: int
@dataclass(frozen=True)
class Failed:        log_id: int

JudgeResult = Appropriate | Inappropriate | Failed
```

**세 갈래뿐이다.** U5는 이 셋만 분기하고 판정의 내부를 모른다. **`Failed`는 예외가 아니라 반환값이다** (BR-6.7) — 실패는 "일어나면 안 되는 일"이 아니라 FR-8이 정의한 흐름의 일부다.

## 다른 단위에 제공하는 것

`unit-of-work-dependency.md`가 기록한 계약이다. **시그니처를 바꾸면 U5가 깨진다.**

```python
async def judge(session, user_id, room_id, context: list[ContextMessage],
                candidate_text: str) -> JudgeResult
async def get_log_for_force(session, user_id, room_id, log_id,
                            candidate_text) -> JudgmentLog
async def set_user_action(session, log_id, action) -> None   # AlreadyResolved
async def link_message(session, log_id, message_id) -> None
async def compute_metrics(session, since=None) -> MetricsReport
```

`ContextMessage`는 `(sender_id, text)`만 담는 이 단위 소유의 값 객체다 — U5의 ORM 모델을 받지 않는다. 그래야 `try` CLI가 DB 없이 문맥을 조립할 수 있다.

---

## 실행 단계

### Step 1 — 모듈 골격과 의존성
- [x] `app/judgment/{__init__,constants,types,exceptions,anonymize,prompt,client,service,metrics,router,report,try}.py`
- [x] `requirements.txt`에 `openai` 추가 (ASCII 유지)
- [x] `.env.example`·`.env`의 `AI_TIMEOUT_SECONDS`를 **5 → 4**로 (위 결함 수정). 주석에 근거를 남긴다
- 대응: 구조, BR-6.7, NFR-1

### Step 2 — 값 타입과 예외
- [x] `types.py` — `ContextMessage(sender_id, text)`, `Appropriate`/`Inappropriate`/`Failed`, `JudgeResult` 별칭, `MetricsReport`
- [x] `exceptions.py` — `AlreadyResolved`(409), `InvalidForceToken`(400), `ForceTokenForbidden`(403). U1의 `DomainError` 상속
- [x] `Failed`가 예외 계층에 **들어가지 않는다** — 반환값이다
- 대응: BR-6.7, BR-6.9, BR-7.1

### Step 3 — 문맥 익명화
- [x] `anonymize.py` — `label_speakers(context, candidate_sender_id) -> (list[(label, text)], candidate_label)`
- [x] 등장 순서로 `A`, `B`, `C`… 할당. 후보 발신자가 문맥에 없으면 **다음 라벨을 새로 준다**
- [x] 라벨은 **이 윈도우 안에서만 유효**하다 (BR-6.2)
- [x] `Z` 이후는 `AA`, `AB`로 이어간다 — 26명 넘는 방은 요구사항에 없으나 조용히 깨지면 안 된다
- [x] **출력에 `sender_id`가 남지 않는지 단위 테스트로 고정**
- 대응: FR-6.2, BR-6.2

### Step 4 — 프롬프트 조립
- [x] `prompt.py` — `business-logic-model.md` § 프롬프트 설계의 system 문안을 **그 문서 그대로**. 임의로 다듬지 않는다
- [x] "판단하지 않는 것" 3항목(내용 자체의 적절성 / 맞춤법 / 화제 전환만으로 부적합 아님)이 빠지지 않게 — 이 셋이 측정 대상을 하나로 유지하는 장치다 (BR-6.3, FR-6.7)
- [x] 점수 구간 4개의 언어적 설명 포함 — 없으면 분포가 0.5로 몰린다
- [x] user 메시지 조립 — `## 최근 대화` + `## 보내려는 메시지`
- [x] `RESPONSE_FORMAT` 상수 — `strict: true`, `score` 하나, `additionalProperties: false`
- [x] 프롬프트 문안을 **상수 모듈에 모아** `try` CLI가 같은 문안을 쓰게 한다. 두 벌이 되면 튜닝이 무의미해진다
- 대응: FR-6.3, FR-6.7, BR-6.3, BR-6.4, ADR-005

### Step 5 — OpenAI 클라이언트
- [x] `client.py` — `call_model(messages) -> ModelCall` (`score`·`prompt_tokens`·`completion_tokens`·`latency_ms`·`ok`)
- [x] per-request 타임아웃 `settings.AI_TIMEOUT_SECONDS`, `temperature=0`
- [x] **재시도 정확히 1회** (BR-6.7). 대상: 타임아웃·연결 오류·5xx·429. **비대상: 429 외 4xx** — 요청 자체가 틀린 것이라 다시 보내도 같다
- [x] `Retry-After`는 **남은 예산 안에서만** 존중. 넘으면 대기하지 않고 실패
- [x] 총 대기 시간이 10초를 넘지 않는 예산 계산 (NFR-1)
- [x] `latency_ms`는 **실패해도** 실제 대기 시간을 기록 (BR-6.8)
- [x] SDK 자체 재시도를 **끈다**(`max_retries=0`) — 켜두면 재시도가 이중이 되어 1회 규칙이 깨진다
- [x] 모델이 `json_schema`를 거부하는 경우(4xx)는 재시도 없이 실패로 가되 **로그에 원문 오류를 남긴다** — 설정 오류를 API 장애로 오해하면 며칠 헤맨다
- 대응: FR-8.1, BR-6.7, BR-6.8, NFR-1

### Step 6 — `judge()`
- [x] `service.py` — `business-rules.md` § 규칙 판정 순서의 9단계 **그대로**
- [x] **로그 INSERT가 모델 호출보다 먼저** (BR-6.8). 호출 중 프로세스가 죽어도 시도 흔적이 남는다
- [x] `context_from_seq`/`context_to_seq`는 문맥의 첫·**마지막 메시지**의 seq. 후보는 아직 seq가 없다 (BR-6.1)
- [x] `candidate_text`와 `threshold`를 로그에 남긴다 — 재현에 필요하다
- [x] 점수 클램프 `[0.0, 1.0]` — 범위 밖을 실패로 처리하지 않는다 (BR-6.6)
- [x] `score >= threshold` → `inappropriate`. **같으면 부적절** (BR-6.5)
- [x] 실패 시 `score`·`verdict` NULL 유지 + `latency_ms` 기록 → `Failed(log_id)` **반환** (예외 아님)
- [x] **예외를 던지지 않는다.** OpenAI 예외를 이 함수 밖으로 내보내지 않는다
- 대응: FR-6.2·FR-6.3·FR-8.1, BR-6.1·BR-6.5·BR-6.6·BR-6.7·BR-6.8

### Step 7 — `force_log_id` 검증과 `user_action`
- [x] `get_log_for_force()` — BR-6.9의 6개 검사를 그 순서로. **`user_id` 불일치만 403, 나머지 전부 400**
- [x] `candidate_text` 비교는 **트림 후 정확 일치.** 정규화(공백 축약·유니코드 정규화)를 하지 않는다 — 우회 여지가 생긴다
- [x] `verdict`가 `inappropriate` **또는 NULL**이면 통과. `appropriate`는 거부 — 적절 판정은 이미 자동 전송되어 강행 대상이 아니다
- [x] `set_user_action()` — **원자적 조건부 갱신** `UPDATE ... SET user_action=? WHERE id=? AND user_action IS NULL`. 영향 행 0이면 `AlreadyResolved` (BR-7.1)
- [x] `link_message(log_id, message_id)`
- [x] `router.py` — `PATCH /judgments/{id}` (`user_action` 갱신). `current_user()`로 인증
- 대응: BR-6.9, BR-7.1, FR-8.3

### Step 8 — `compute_metrics()`
- [x] `metrics.py` — `business-logic-model.md` W4의 표 그대로
- [x] 집계 대상은 `judgment_logs` 중 **`verdict IS NOT NULL`**. `messages.verification_status`를 필터로 쓰지 않는다 (BR-7.2). **취소된 건은 `messages` 행이 없어 그 필터로는 영원히 안 잡힌다**
- [x] **API 실패율만 분모가 다르다** — 거르기 전의 전체 행 기준
- [x] precision = `cancelled / (cancelled + sent)`. **분모 0이면 `None`** (BR-7.3)
- [x] 미응답 건수 = `verdict='inappropriate' AND user_action IS NULL`. precision에서 제외하되 **별도 수치로** (BR-7.4)
- [x] recall은 **`"산출 불가 — 라벨 데이터셋 필요"` 문자열.** 수치를 넣거나 항목을 빼지 않는다 (BR-7.5)
- [x] 신고율·미검출 후보만 `messages`를 읽는다 — 이 단위가 다른 테이블을 읽는 유일한 지점
- 대응: FR-7.3~FR-7.5, BR-7.2~BR-7.6

### Step 9 — 리포트 CLI (ADR-008)
- [x] `report.py` — `python -m app.judgment.report`. `business-logic-model.md`의 출력 형식 그대로
- [x] **precision 옆에 항상 `※ 근사` 표시** + 하단에 ASM-1 각주. 숫자만 보면 정확한 측정값으로 읽힌다
- [x] recall 줄에 산출 불가 사유를 그대로 출력
- [x] `--since` 옵션
- [x] UI 화면을 만들지 않는다 (ADR-008)
- 대응: FR-7.5, ADR-008

### Step 10 — `try` CLI — 단독 검증 경로
- [x] `try.py` — `python -m app.judgment.try --context "..." "..." --candidate "..."`
- [x] **DB 없이 돈다.** 로그를 남기지 않고 점수·판정·지연·토큰만 출력
- [x] Step 4의 같은 프롬프트 상수를 쓴다 — 두 벌이면 튜닝이 무의미하다
- [x] `--sender` 옵션으로 후보 발신자를 문맥의 몇 번째 화자로 둘지 지정 (기본: 문맥에 없는 새 화자)
- [x] `--show-prompt`로 조립된 프롬프트를 그대로 출력 — 익명화가 맞는지 눈으로 본다
- [x] API 키가 없거나 모델이 거부하면 **원문 오류를 그대로** 보여준다. 판정 실패로 위장하지 않는다
- 대응: `business-logic-model.md` § 단독 검증 경로

### Step 11 — 테스트
Test Strategy **Standard**. **OpenAI 호출은 전부 목(mock)이다** — 테스트가 외부 API에 의존하면 키 없이 돌지 않고 비용이 든다.
- [x] `test_anonymize.py` — 등장 순서 라벨, 후보 발신자가 문맥에 있을 때/없을 때, 1명뿐인 문맥, 26명 초과, **출력에 `sender_id`가 없음**, 빈 문맥 (6~7개)
- [x] `test_prompt.py` — system에 "판단하지 않는 것" 3항목이 존재, 점수 구간 4개 존재, 참여자 이름·id가 user 메시지에 없음, `strict: true`·`additionalProperties: false` (5~6개)
- [x] `test_client.py` — 타임아웃 시 **정확히 1회** 재시도, 5xx·429 재시도, **400은 재시도 안 함**, 총 대기가 10초 예산 안, `Retry-After`가 예산 초과면 대기하지 않음, 실패도 `latency_ms` 기록, SDK 자체 재시도가 꺼짐 (7~8개)
- [x] `test_judge.py` — 로그 행이 **호출 전에** 생성됨, score 0.85/threshold 0.7 → `Inappropriate`, 0.65 → `Appropriate`, **경계 0.7 → `Inappropriate`**, 클램프(1.2→1.0, -0.3→0.0), 실패 시 `Failed` 반환이며 **예외를 던지지 않음**, 실패 로그의 `score`/`verdict` NULL, `context_from_seq`~`to_seq`가 실제 범위, `threshold`가 로그에 남음 (9~10개)
- [x] `test_force_log.py` — 6개 검사 각각의 실패, **소유자 불일치만 403**, **텍스트 불일치 거부**(이월된 구멍의 회귀 테스트), `verdict=appropriate` 거부, `verdict=NULL` 통과, `set_user_action` 2회 호출 시 두 번째가 `AlreadyResolved`, **조건절이 SQL에 실제로 있음** (9~10개)
- [x] `test_metrics.py` — precision 7 cancelled/3 sent → 0.7, **분모 0이면 `None`**(0.0이 아님), `verdict IS NULL` 행이 precision에서 제외되고 **API 실패율에는 포함**, 미응답 건수 별도 집계, **recall이 문자열**, `disabled` 메시지 100건이 집계에 안 들어옴(로그 행이 없으므로) (8~9개)
- [x] 실제 MariaDB 픽스처(U1·U3) 재사용. skip을 통과로 보고하지 않는다
- 대응: NFR-7 — FR-6.x·FR-7.x·FR-8.1의 수용 기준

---

## 요구사항 → 단계 추적

| FR/BR | 단계 |
|---|---|
| FR-6.2 문맥 N개 + 참여자 정보 배제 | 3, 4, 6 / 검증 11 |
| FR-6.3 모델은 점수만, 서버가 임계값 판정 | 4, 5, 6 / 검증 11 |
| FR-6.7 판정 대상은 문맥 적합성뿐 | 4 / 검증 11 |
| FR-7.1 `verification_status` 6값 중 판정 결과 3값 | 6 (U5가 나머지 3값) |
| FR-7.2 시도한 모든 건에 로그 | 6 / 검증 11 |
| FR-7.3 precision 라벨 | 7, 8 / 검증 11 |
| FR-7.4 집계 축은 판정 로그 | 8 / 검증 11 |
| FR-7.5 산출 가능·불가 지표 | 8, 9 / 검증 11 |
| FR-8.1 타임아웃 + 재시도 1회 | 5 / 검증 11 |
| NFR-1 정상 5초 / 최악 10초 | 1(기본값 4), 5 / 검증 11 |
| BR-6.9 텍스트 일치 검사 | 7 / 검증 11 |
| BR-7.1 원자적 조건부 갱신 | 7 / 검증 11 |
| ADR-008 지표를 CLI로 | 9 |

## 계획에서 뺀 것

- **마이그레이션** — `judgment_logs`는 U1이 이미 만들었다
- **프론트엔드 전체** — 이 단위에 UI가 없다. 판정 팝업(`JudgeConfirmDialog`)은 U5 소관이다
- **관리자 화면·`GET /metrics` 엔드포인트** — ADR-008이 CLI로 정하고 둘 다 기각했다
- **근거 문장 반환** — 스키마를 `score` 하나로 좁혔다. 나중에 늘리는 비용은 작다
- **욕설·비방·민감정보 판정** — FR-6.7이 명시적으로 배제. 프롬프트가 그것을 적극적으로 막는다
- **메시지 조회** — 문맥은 U5가 넘긴다. 이 단위는 `messages`를 판정 경로에서 읽지 않는다

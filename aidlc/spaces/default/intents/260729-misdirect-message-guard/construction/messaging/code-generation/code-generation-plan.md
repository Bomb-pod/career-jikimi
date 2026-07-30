# Code Generation Plan — messaging (U5)

**앞의 네 단위가 여기서 만난다.** 이 단위가 XL인 이유이며 `send_message()` 하나가 그 전부를 오케스트레이션한다.

| 무엇 | 어디 |
|---|---|
| W1 전송(9단계), seq 채번, W2 히스토리, W3 신고, 전송 상태 기계, degraded 관리, `ChatView`·팝업 2종 | `../functional-design/business-logic-model.md` |
| BR-4.1~BR-4.4, BR-6.1~BR-6.5, BR-8.1~BR-8.6, BR-11.1~BR-11.3, BR-3.3 | `../functional-design/business-rules.md` |
| `messages` 불변식, 클라이언트 측 상태 | `../functional-design/domain-entities.md` |
| 대응 요구사항 | `../../../inception/requirements-analysis/requirements.md` — FR-3.3·FR-4.1~FR-4.4·FR-6.4~FR-6.6·FR-7.1(판정 안 함 3값)·FR-8.2~FR-8.6·FR-11, NFR-2·NFR-3·NFR-5 |

**테이블은 이미 있다.** U1의 `0001_initial_schema`가 `messages`를 만들었다. 마이그레이션을 새로 만들지 않는다.

**`component-methods.md`의 백엔드 `send_message()` 산문은 낡았다** — "네 가지를 검증한 뒤 `flagged_sent`로 진행"이라 적혀 있고 `NULL` verdict → `failed` 분기가 없다. functional-design 리뷰어가 잔여 항목으로 기록했다. **충돌하면 `../functional-design/`가 권위다.**

---

## 앞선 단위가 남긴 계약 — 반드시 이대로 쓴다

| 이름 | 어디서 | **주의** |
|---|---|---|
| `judge(session, user_id, room_id, context, candidate_text)` | `app.judgment` | 아래 두 항목을 반드시 지킨다 |
| `ContextMessage` | `app.judgment` | **`(sender_id, text, seq)` 세 필드다.** 계획 문서상 2필드였으나 U2가 `context_from_seq`/`context_to_seq`(NOT NULL) 때문에 `seq`를 필수로 추가했다. `ContextMessage(sender_id=m.sender_id, text=m.body, seq=m.seq)` |
| — | — | **`judge()`는 내부에서 커밋한다.** 호출 시점에 세션에 커밋되지 않은 쓰기가 없어야 한다 |
| 문맥 순서 | judgment-core BR-6.1 | **`seq` 오름차순** — 오래된 것이 먼저 |
| `get_log_for_force`, `set_user_action`, `link_message` | `app.judgment` | `set_user_action`은 이미 값이 있으면 `AlreadyResolved` |
| `get_membership(session, user_id, room_id)` | `app.rooms` | 자격 + `ai_check_enabled`를 **한 번에** |
| `member_user_ids(session, room_id)` | `app.rooms` | 브로드캐스트 대상 |
| `push_to_users(user_ids, payload)` | `app.core.ws_registry` | 커밋 **뒤에** 호출 |
| `resolve_display_names(session, owner_id, user_ids)` | `app.friends` | **쿼리 횟수 회귀 테스트가 붙어 있다.** 히스토리 경로에서 N+1을 만들면 붉어진다 |
| `current_user()` | `app.auth` | |

프론트에서 이어받는 것:

| 이름 | 어디서 | 주의 |
|---|---|---|
| `chatStore` | `store/chatStore.ts` | U4가 rooms·unread·messages·toasts·wsStatus를 만들었다. **`degraded` 슬라이스를 여기서 더한다** |
| `enterRoom(roomId, loadHistory?)` | 같은 곳 | **기본 로더가 "히스토리 없음"이다. `GET /rooms/{id}/messages`로 교체한다** |
| `apiClient` | `lib/apiClient.ts` | 409를 예외로 던지지 않는다 — 정상 분기다 |

---

## 이 계획이 닫는 열린 항목

| 열린 항목 | 결정 | 근거 |
|---|---|---|
| **메시지 본문 길이 상한** (세 단위가 반복해서 제기했다) | **2000자.** 초과 시 400 `MESSAGE_TOO_LONG`. 프론트에 `maxLength` | 상한이 없으면 한 메시지가 판정 토큰 비용을 무제한으로 키우고 `judgment_logs.candidate_text`에 그대로 쌓인다. 2000자는 채팅 메시지로 넉넉하고(한글 기준 원고지 10장) 문맥 10개를 합쳐도 토큰이 통제된다. 상수 하나라 되돌림 비용이 없다 |
| 낙관적 렌더링 중 요청 실패 시 임시 메시지 처리 | **제거하고 입력창에 텍스트를 복원한다.** 201에서만 실제 메시지로 교체 | 규칙 하나로 세 경로(409 부적절 / 409 실패 / 네트워크 오류)를 모두 덮는다. 실패한 말풍선을 남기면 보낸 것처럼 보이는데 실제로는 DB에 없다 — NFR-3이 막으려는 착시와 같은 종류다. FR-6.6·FR-8.4가 이미 "입력창 텍스트 유지"를 요구한다 |
| "다시 시도" 버튼의 반복 횟수 제한 | **제한 없음.** 다만 요청 진행 중에는 비활성화 | 사용자가 의도적으로 누르는 동작이라 자동 폭주가 아니다. 제한을 두면 API가 늦게 복구됐을 때 사용자가 막힌다 |
| `shouldProbe()`의 `% 5 === 4` | **그대로** (조치 없음) | `business-logic-model.md`가 이미 근거와 함께 닫았다 |
| 프로브 카운터의 클라이언트 조작 가능성 | **수용** (조치 없음) | ADR-007이 이미 위협 모델 밖으로 정했다 |

### 새 의존성

**없다.**

---

## API 표면

| 메서드 | 경로 | 응답 |
|---|---|---|
| POST | `/rooms/{id}/messages` | 201 `{message}` / **409** `{log_id, score, reason:"inappropriate"}` / **409** `{log_id, reason:"judge_failed"}` / 400 `MESSAGE_TOO_LONG` / 403 |
| GET | `/rooms/{id}/messages?before=&limit=` | 200 / 403 |
| POST | `/messages/{id}/report` | 200 / 403 |
| DELETE | `/messages/{id}/report` | 200 / 403 |

**두 409가 같은 재요청 경로를 쓴다.** 상태 코드를 나누면(503 등) 클라이언트가 네트워크 오류와 헷갈린다 — 실패한 것은 판정이지 요청이 아니다.

---

## 실행 단계

### Step 1 — 모듈 골격과 상수
- [x] `app/messages/{__init__,constants,schemas,service,history,report,router,exceptions}.py`
- [x] `constants.py` — `MESSAGE_MAX_LENGTH = 2000`, `HISTORY_DEFAULT_LIMIT = 50`, `HISTORY_MAX_LIMIT = 100`
- [x] `exceptions.py` — `MessageTooLong`(400), `MessageForbidden`(403). 판정 관련 예외는 U2 것을 쓴다
- 대응: 구조

### Step 2 — `send_message()` 오케스트레이션
`business-rules.md` § 규칙 판정 순서의 7단계와 `business-logic-model.md` W1의 9단계를 **그대로**.
- [x] 1. `get_membership()` **1회** — 없으면 403. `ai_check_enabled` 확보 (BR-3.3)
- [x] 2. `force_log_id`가 있으면 `get_log_for_force(me, room_id, log_id, text)` → **상태를 로그의 `verdict`에서 파생**: `inappropriate`→`flagged_sent`, **NULL→`failed`**. 바로 6번으로 (BR-6.4)
- [x] 3. 없으면 상태 결정을 **이 순서로**, 첫 번째로 걸리는 것 적용 (BR-6.1): 토글 꺼짐→`disabled` / degraded이고 프로브 아님→`degraded` / 방 메시지 < `AI_CONTEXT_N`→`skipped_no_context` / 그 외 4번. **2번이 3번보다 앞인 것에 의미가 있다** — degraded면 문맥 개수 조회(DB 1회)를 아낀다
- [x] 4. 문맥 최근 N개를 **`seq` 오름차순**으로 조회 → `ContextMessage(sender_id, text, seq)` 리스트 → `judge()`. **트랜잭션 밖** (BR-4.3). 호출 전 세션에 커밋 안 된 쓰기가 없어야 한다
- [x] 5a. `Inappropriate` → **저장하지 않고** 409 `{log_id, score, reason:"inappropriate"}` (BR-6.3)
- [x] 5b. `Failed` → degraded(프로브)였으면 `failed`로 6번. 아니면 **저장하지 않고** 409 `{log_id, reason:"judge_failed"}` (BR-8.2)
- [x] `Appropriate` → `ok` + `set_user_action(auto_sent)`
- [x] 6. **트랜잭션**: `SELECT rooms.last_seq FOR UPDATE` → `INSERT messages(seq=last_seq+1)` → `UPDATE rooms.last_seq`. **외부 호출이 하나도 없다** (BR-4.2, ADR-003)
- [x] 7. 로그가 있으면 `link_message(log_id, message.id)`
- [x] 8. **커밋 뒤** `member_user_ids()` → `push_to_users()` (BR-4.1). 발신자 포함
- [x] 9. 201 `{message}`
- [x] 본문 2000자 초과는 1번 직후 400 (가장 싼 검사)
- 대응: FR-4.1~FR-4.3, FR-6.4~FR-6.6, FR-7.1(판정 안 함 3값), FR-8.2·8.3·8.5, NFR-3

### Step 3 — 히스토리
- [x] `list_messages(me, room_id, before, limit)` — `get_membership()` 없으면 403
- [x] `WHERE room_id=? AND (before IS NULL OR seq < ?)`, `ORDER BY seq DESC`, `LIMIT min(limit, 100)` (BR-4.4)
- [x] **`before`는 경계를 포함하지 않는다** (`<`). 포함하면 페이지 경계에서 한 건이 중복된다
- [x] `resolve_display_names()` **1회** — 발신자 id를 모아 한 번에. 반복문 안에 두지 않는다
- [x] 오프셋 페이지네이션을 쓰지 않는다 — 그 사이 메시지가 추가되면 경계가 밀린다
- 대응: FR-3.3, FR-4.4, BR-4.4

### Step 4 — 신고
- [x] `report(me, message_id)` / `unreport(me, message_id)` — `sender_id != me`거나 **없는 메시지도 403** (BR-11.1)
- [x] `verification_status`를 **보지 않는다** (BR-11.2). 어느 상태든 신고 가능하다 — 그것이 이 기능의 존재 이유다
- [x] `misdirect_reported_at`을 `NOW(6)` 또는 `NULL`로. 이력은 남지 않는다 (BR-11.3)
- 대응: FR-11.1~FR-11.3

### Step 5 — 라우터
- [x] `POST·GET /rooms/{id}/messages`, `POST·DELETE /messages/{id}/report`
- [x] 409 두 종을 `reason`으로 가르는 응답 스키마
- [x] `app/main.py`에 등록 — **SPA 폴백보다 먼저**
- 대응: API 표면

### Step 6 — 백엔드 테스트 ①: **동시 채번** (NFR-7 명시 의무)
`business-logic-model.md`가 이 단위의 테스트 의무로 지목한 둘 중 하나. **눈으로 검증할 수 없는 곳이다.**
- [x] 같은 방에 **실제로 동시** 전송 — seq가 중복 없이 연속 (asyncio.gather + 별도 커넥션)
- [x] **다른 방은 막히지 않는다** — 방 A의 잠금이 방 B의 전송을 지연시키지 않음
- [x] `SELECT ... FOR UPDATE`가 **발생한 SQL에 실제로 있다** (`capture_sql`)
- [x] `UNIQUE (room_id, seq)`가 최종 방어선으로 동작
- [x] 트랜잭션 안에 외부 호출이 없다
- (6~8개)
- 대응: **FR-4.2 — NFR-7의 명시 대상**

### Step 7 — 백엔드 테스트 ②: 전송 경로
- [x] `test_send_message.py` — 비참여자 403, 2000자 초과 400, 토글 꺼짐→`disabled`(로그 없음), 문맥 부족→`skipped_no_context`(로그 없음), degraded→`degraded`(로그 없음), 적절→`ok`+`auto_sent`, **부적절→저장 안 됨 + 409 inappropriate**, **실패(비degraded)→저장 안 됨 + 409 judge_failed**, **실패(프로브)→저장됨 + `failed`**, 상태 결정 **순서**(토글 꺼짐이 문맥 부족보다 우선), **판정이 트랜잭션 밖**, **브로드캐스트가 커밋 뒤** (12~14개)
- [x] `test_force_send.py` — `verdict=inappropriate`로 재요청→**`flagged_sent`**, **`verdict=NULL`로 재요청→`failed`**(FR-8.3을 성립시키는 장치), 텍스트 불일치 거부, 소진된 로그 거부, 남의 로그 403, 두 번 쓰면 `AlreadyResolved` (7~8개)
- [x] `test_history.py` — 최신 50개 내림차순, `before` **경계 미포함**, `limit` 상한 100, 비참여자 403, **표시명 해석 1회**(N+1 회귀) (6개)
- [x] `test_report.py` — 신고 200, 취소 200, **남의 메시지 403**, **없는 메시지도 403**, `ok` 상태 신고 가능, `disabled` 상태 신고 가능 (6~7개)
- 대응: NFR-7

### Step 8 — 프론트 `degraded` 슬라이스와 전송 상태 기계
- [x] `chatStore`에 `degraded`·`degradedSendCount` 추가 — **메모리에만.** `localStorage`·`sessionStorage` **금지** (FR-8.3)
- [x] `shouldProbe()` = `degraded && degradedSendCount % 5 === 4`. 카운터는 **사용자 전역** (BR-8.5). 방 단위면 방을 옮길 때마다 리셋되어 프로브가 거의 안 돈다
- [x] `enterDegraded()`/`exitDegraded()` — 후자는 "AI 검증이 다시 켜졌습니다" 토스트
- [x] `sendMessage()` 상태 기계 — 201/409 inappropriate/409 judge_failed/네트워크 오류 네 갈래
- [x] **수락 시 `enterDegraded()`가 재요청 *뒤에* 온다.** 먼저 부르면 재요청이 degraded 경로로 빠져 그 메시지가 `failed`가 아니라 `degraded`로 저장된다
- [x] 낙관적 렌더링 — 임시 ID로 즉시 표시, 201에서 실제 ID·seq로 교체, **그 외에는 제거 + 입력창 복원** (FR-4.3)
- [x] `enterRoom`의 기본 히스토리 로더를 `GET /rooms/{id}/messages`로 교체. **포인터 먼저, 히스토리 나중**은 U4가 이미 보장한다
- 대응: FR-4.3, FR-8.3, FR-8.5

### Step 9 — `ChatView`와 팝업 2종
- [x] `ChatView` — 헤더(방 이름 + **AI 토글** + 프라이버시 고지), 목록(메시지 + 발신자 표시명 + **미검증 배지** + 신고), 입력(textarea + 전송 + 조건부 "다시 시도")
- [x] **판정 대기 중 전송 버튼 비활성화 + "확인 중..."** (FR-6.5, NFR-2). 1~3초 무반응은 앱이 멈춘 것으로 읽힌다
- [x] 비어 있음: "첫 메시지를 보내보세요." + **콜드스타트 안내** — 방 메시지가 `N`개 미만이면 판정이 안 도는데 모르면 "왜 아무 일도 안 일어나지"가 된다
- [x] **프라이버시 고지** (NFR-5) — 토글 옆 상시 "검증 시 최근 대화가 외부 AI로 전송됩니다", 클릭 시 최근 `N`개 본문만 가고 참여자 정보는 안 간다는 설명. **토글이 꺼져 있어도 보인다**
- [x] 미검증 배지 — `failed`·`degraded`·`skipped_no_context`에만. `ok`·`flagged_sent`·`disabled`는 없음 (BR-8.6). **스크롤해서 다시 봐도 남는다** (FR-8.6)
- [x] `JudgeConfirmDialog` — "이 방에 맞지 않는 것 같습니다. 그래도 보낼까요?"
- [x] `DegradedDialog` — "검증 서버에 연결할 수 없습니다. 그래도 보내시겠습니까?" + 부제 "서버가 정상화될 때까지 검증 없이 전송합니다"
- [x] 두 팝업 공통 — `role="alertdialog"`, **기본 포커스 "취소"**, 포커스 트랩, Escape=취소(텍스트 유지), **배경 클릭으로 닫히지 않음**, 닫힐 때 입력창으로 포커스 복귀, 색만으로 표시하지 않음
- [x] **기본 포커스가 "취소"인 이유** — Enter를 반사적으로 누르는 사용자가 강행 전송하지 않게. precision 우선 방침과 같은 방향
- [x] `data-testid` 13개 — `chat-message-input`, `chat-send-button`, `chat-retry-button`, `chat-message-{id}`, `chat-unverified-badge-{id}`, `chat-report-{id}`, `judge-confirm-dialog`, `judge-confirm-send`, `judge-confirm-cancel`, `degraded-dialog`, `degraded-accept`, `degraded-reject`, `chat-privacy-notice`
- 대응: FR-6.5, FR-6.6, FR-8.2, FR-8.4, FR-8.6, FR-11.1, NFR-2, NFR-5

### Step 10 — 프론트 테스트: **degraded 상태 기계** (NFR-7 명시 의무)
둘 중 나머지 하나. **경로가 많아 손 테스트가 새는 곳이다.**
- [x] 첫 실패 → `DegradedDialog` 표시, **응답 전 전송 안 함**
- [x] 수락 → `force_log_id`로 재요청 → **그 메시지가 `failed`** → **그 다음** degraded 전환 (순서 검증)
- [x] 거절 → 전송 취소 + 입력 유지 + "다시 시도" 표시 + **degraded로 넘어가지 않음**
- [x] degraded 중 4번 전송 → 5번째가 **프로브**(`degraded=false`로 요청)
- [x] 프로브 성공 → degraded 해제 + 복귀 토스트
- [x] 프로브 실패 → **팝업 없이** degraded 유지, 그 메시지 `failed`
- [x] 카운터가 **방을 옮겨도 이어진다**
- [x] 새로고침 시뮬레이션(스토어 재생성) → degraded 초기화
- [x] `localStorage`·`sessionStorage`에 쓰지 않음
- (9~10개)
- 대응: **FR-8.3·FR-8.5 — NFR-7의 명시 대상**

### Step 11 — 프론트 테스트: `ChatView`와 팝업
- [x] 판정 대기 중 버튼 비활성화 + "확인 중...", 409 inappropriate 시 팝업, **기본 포커스가 취소**, Escape=취소+텍스트 유지, **배경 클릭으로 안 닫힘**, 미검증 배지 3값에만, 신고 버튼이 **내 메시지에만**, 프라이버시 고지가 **토글 꺼짐에도 보임**, 콜드스타트 안내, 낙관적 렌더링 교체와 실패 시 제거+복원 (10~12개)
- 대응: NFR-2, NFR-5, FR-6.5, FR-6.6, FR-8.6, FR-11.1

---

## 요구사항 → 단계 추적

| FR/NFR | 단계 |
|---|---|
| FR-3.3 히스토리 | 3, 8 / 검증 7 |
| FR-4.1 저장 후 브로드캐스트 | 2 / 검증 7 |
| FR-4.2 seq 채번 | 2 / **검증 6 (명시 의무)** |
| FR-4.3 낙관적 렌더링 | 8 / 검증 11 |
| FR-4.4 커서 페이지네이션 | 3 / 검증 7 |
| FR-6.4 콜드스타트 | 2, 9 / 검증 7 |
| FR-6.5 판정 대기 UI | 9 / 검증 11 |
| FR-6.6 확인 팝업 | 9 / 검증 11 |
| FR-7.1 판정 안 함 3값 | 2 / 검증 7 |
| FR-8.2 첫 실패 팝업 | 2, 9 / **검증 10** |
| FR-8.3 수락 시 failed + degraded | 2, 8 / **검증 10 (명시 의무)** |
| FR-8.4 거절 시 다시 시도 | 8, 9 / 검증 10 |
| FR-8.5 프로브 | 2, 8 / **검증 10 (명시 의무)** |
| FR-8.6 미검증 배지 | 9 / 검증 11 |
| FR-11 오발송 신고 | 4, 9 / 검증 7, 11 |
| NFR-2 응답성 | 9 / 검증 11 |
| NFR-3 데이터 무결성 | 2 / 검증 7 |
| NFR-5 프라이버시 고지 | 9 / 검증 11 |

## 계획에서 뺀 것

- **마이그레이션** — `messages`는 U1이 이미 만들었다
- **메시지 수정·삭제** — 요구사항에 없고 `seq` 정렬과 커서가 불변을 전제한다
- **미전송 큐** — 오프라인 사용자는 다음 입장 시 히스토리로 받는다
- **판정 내부** — U2 소유. 이 단위는 `JudgeResult` 세 갈래만 분기한다
- **방·연결 관리** — U4 소유
- **FR-10 참여자 관리** — U4에서 절단됨

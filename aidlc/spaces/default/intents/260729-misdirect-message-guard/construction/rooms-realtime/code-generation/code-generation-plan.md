# Code Generation Plan — rooms-realtime (U4)

`../functional-design/`의 세 문서가 권위다. `business-logic-model.md`가 워크플로 5개·브로드캐스트 알고리즘·프론트 명세를, `business-rules.md`가 규칙 16개를, `domain-entities.md`가 `rooms`·`room_members`와 **인메모리 연결 레지스트리**를 정한다.

| 무엇 | 어디 |
|---|---|
| W1 방 생성, W2 목록, W3 상세, W4 읽음, W5 WS 수명주기, 브로드캐스트, 프론트 | `../functional-design/business-logic-model.md` |
| BR-3.1~BR-3.5, BR-5.1~BR-5.10, BR-6.1~BR-6.2, BR-10.1~BR-10.2 | `../functional-design/business-rules.md` |
| `rooms`·`room_members` 불변식, 연결 레지스트리 | `../functional-design/domain-entities.md` |
| 대응 요구사항 | `../../../inception/requirements-analysis/requirements.md` — FR-1.3·FR-3.1~FR-3.3·FR-5.1~FR-5.4·FR-6.1·FR-10(Should) |

**테이블은 이미 있다.** U1의 `0001_initial_schema`가 `rooms`·`room_members`를 만들었다. 마이그레이션을 새로 만들지 않는다.

**두 번째 미지수가 여기 있다** — WebSocket 동시성. 첫 번째(LLM 판정)는 U2에서 끝났다.

**구현 순서는 백엔드 먼저, 그 위에 프론트다.** Step 1~7이 백엔드, Step 8~11이 프론트다.

---

## 앞선 단위가 남긴 계약 — 그대로 쓴다

| 이름 | 어디서 | 주의 |
|---|---|---|
| `verify_token(token) -> int` | `app.auth` | **동기 순수 함수.** WS 첫 프레임 인증이 이것을 쓴다. FastAPI 의존성이 아니다 |
| `current_user()` | `app.auth` | HTTP 라우터용 |
| `resolve_display_names(session, owner_id, user_ids)` | `app.friends` | **쿼리 횟수 회귀 테스트가 붙어 있다.** 방 참여자 경로에서 N+1을 만들면 그 테스트가 붉어진다 |
| `list_friends(owner_id)` | `app.friends` | BR-3.2의 친구 확인 |
| `get_session()`, `settings`, `Base`, `DomainError` | `app.core.*` | `get_session()`은 핸들러 성공 시 자동 커밋 |

`app/main.py`의 라우터 등록 지점은 **SPA catch-all보다 먼저**다. WebSocket 엔드포인트도 같다.

## 다른 단위에 제공하는 것 — U5가 쓴다

**시그니처를 바꾸면 U5가 깨진다.**

```python
async def get_membership(session, user_id, room_id) -> RoomMember | None   # ai_check_enabled 포함
async def member_user_ids(session, room_id) -> list[int]                   # 브로드캐스트 대상
async def push_to_users(user_ids: list[int], payload: dict) -> None        # 실제 전송
```

`get_membership()`은 **참여 자격과 `ai_check_enabled`를 한 번에** 준다 — U5의 `send_message()` 1단계가 그 둘을 함께 필요로 한다. `member_user_ids()`는 브로드캐스트 대상 조회 전용이다.

---

## 이 계획이 닫는 열린 항목

| 열린 항목 | 결정 | 근거 |
|---|---|---|
| WebSocket 재연결 백오프·최대 시도 | **지수 백오프 1→2→4→8→16초 상한, 시도 무제한.** `session_replaced`일 때만 재연결하지 않는다 | 데모 도중 끊기면 눈에 띈다. 시도를 유한하게 막으면 조용히 죽은 채로 남아 더 나쁘다 — 상한을 16초로 두면 재연결 트래픽은 억제되고 복구는 자동이다. 재연결 중임을 화면에 표시한다 |
| `rooms.name`이 NULL일 때 이름 조립 | **참여자 표시명 최대 3명 + `외 N명`.** 본인은 제외 | 3명이면 한 줄에 들어가고 방을 구별하기에 충분하다. 본인을 넣으면 모든 방 이름이 내 이름으로 시작해 구별에 기여하지 않는다 |
| 토스트 표시 시간·동시 상한 | **4초, 최대 3개.** 넘치면 가장 오래된 것부터 제거 | 4초는 읽고 클릭할 시간이고, 3개를 넘으면 화면을 가려 오히려 방해가 된다 |
| 마지막 참여자가 나간 방 | **그대로 남긴다** (조치 없음) | `business-rules.md`가 이미 "방과 메시지는 남는다"로 닫았다 |
| 밀려난 탭의 화면 갈림 | **수용한다** (조치 없음) | 밀려난 탭은 HTTP로 보낸 자기 메시지만 보고 남의 메시지를 못 받는다. 배너가 그 사실을 알린다 — 그 이상은 밀려난 탭을 살리는 일이고 FR-5.1의 "사용자당 1개"와 어긋난다 |

### `python-multipart` 등 새 의존성

**없다.** WebSocket은 FastAPI(Starlette)에 내장되어 있다.

---

## FR-10(Should)을 이번 단위에서 빼는 제안

`scope-document.md`의 위험 등록부와 `requirements.md` ASM-8이 **절단 순서를 미리 정해두었다**:

> 1순위 방 참여자 추가·나가기(FR-10) → 2순위 degraded 회복 프로브(FR-8.5) → 3순위 오발송 신고(FR-11)

지금 상황이 그 절단을 쓸 자리다:

- 오늘이 **07-30**, 중간 점검이 **07-31**, 최종이 **08-04**
- 남은 것은 U4(L)와 **U5(XL)** 다. U5는 다섯 단위 중 가장 크고 전송·순서·판정 통합·실패 처리가 한 요청 경로에 얽혀 있다
- 최상위 위험이 "07-31까지 Must 전량 완료"인데 Must가 아직 U5 전체만큼 남았다

FR-10은 **Should**이며, 빼도 데모 시나리오가 성립한다 — 방을 만들고 대화하고 판정을 받는 흐름에 참여자 추가·나가기가 필요하지 않다.

**따라서 이 계획은 Step 7을 조건부로 둔다.** 사람이 유지를 택하면 그 단계를 실행하고, 절단을 택하면 건너뛴다. 나중에 붙일 때 다른 단계를 건드리지 않도록 경계를 잡아두었다.

---

## API 표면

| 메서드 | 경로 | 워크플로 | 응답 |
|---|---|---|---|
| POST | `/rooms` | W1 | 201 / 400 `EMPTY_ROOM` / 400 `NOT_A_FRIEND` |
| GET | `/rooms` | W2 | 200 `{rooms: [...]}` (빈 배열도 200) |
| GET | `/rooms/{id}` | W3 | 200 / **403** `FORBIDDEN`(없는 방도 403) |
| POST | `/rooms/{id}/read` | W4 | 200 (전진 못 해도 200) |
| PATCH | `/rooms/{id}/ai-check` | — | 200 / 403 |
| WS | `/ws` | W5 | 첫 프레임 `auth` |
| POST | `/rooms/{id}/members` | (Step 7, 조건부) | 201 / 400 `ALREADY_MEMBER` / 400 `NOT_A_FRIEND` / 403 |
| DELETE | `/rooms/{id}/members/me` | (Step 7, 조건부) | 204 / 403 |

---

## 실행 단계

### Step 1 — 모듈 골격
- [x] `app/rooms/{__init__,schemas,service,router,ws,exceptions}.py`
- [x] `app/core/ws_registry.py` — **U1의 `core/`에 들어간다.** `components.md`가 이 컴포넌트를 `core` 소유로 두었다
- [x] `exceptions.py` — `EmptyRoom`(400), `NotAFriend`(400), `RoomForbidden`(403), `AlreadyMember`(400)
- 대응: 구조

### Step 2 — `core/ws_registry`
- [x] `_connections: dict[int, WebSocket]` — **프로세스 메모리.** 이것이 CON-1의 원인이다
- [x] `register(user_id, ws)` — 기존 연결이 있으면 **`session_replaced` 프레임을 보낸 뒤** 닫고 교체 (BR-5.4)
- [x] `unregister(user_id)` — 없어도 조용히 통과
- [x] `push_to_users(user_ids, payload)` — **try를 루프 안에.** 소켓 하나의 실패가 나머지 참여자의 수신을 막으면 안 된다 (BR-5.7). 연결 없는 사용자는 조용히 건너뛴다 — 오류가 아니다
- [x] 전송 중 소켓이 죽으면 그 사용자를 unregister하고 **나머지는 계속**
- [x] 표면을 이 세 함수로 좁게 유지한다 — Redis pub/sub 교체를 싸게 만드는 유일한 장치다
- 대응: FR-5.1, BR-5.4, BR-5.7, CON-1

### Step 3 — 방 생성·목록·상세
- [x] `create_room(me, friend_user_ids, name)` — W1 순서. **한 트랜잭션**에 `rooms` + `room_members` 전부. 나뉘면 아무도 접근 못 하는 유령 방이 남는다
- [x] 친구 확인은 **한 번의 조회**로 (BR-3.2). `friend_user_ids`를 순회하며 개별 확인하지 않는다
- [x] 모든 참여자 `ai_check_enabled=TRUE`, `last_read_seq=0` (BR-6.2)
- [x] `list_rooms(me)` — 안 읽은 개수를 `LEFT JOIN` + `GROUP BY`로 **한 번의 쿼리**, 표시명을 `resolve_display_names()` **한 번의 호출**로 (BR-5.1). 방마다 반복하면 N+1
- [x] `get_room_detail(me, room_id)` — 403 우선. 응답에 **호출자 본인의** `ai_check_enabled`만. 남의 토글 상태는 넣지 않는다
- [x] `get_membership(session, user_id, room_id)` — U5 계약. 자격과 `ai_check_enabled`를 함께
- [x] `member_user_ids(session, room_id)` — U5 계약. 브로드캐스트 대상 전용
- 대응: FR-3.1~FR-3.3, BR-3.1~BR-3.4

### Step 4 — 읽음 처리와 AI 토글
- [x] `mark_read()` — **조건부 UPDATE** `WHERE ... AND last_read_seq < ?`. 영향 행 0도 **200** (BR-5.3). 조건절이 없으면 순서 뒤바뀐 요청이 배지를 되살린다
- [x] `set_ai_check()` — **호출자 본인의 `room_members` 행만** (BR-6.1). 방장 개념이 없다. `rooms.created_by`는 기록이지 권한이 아니다
- 대응: FR-5.2, FR-6.1, BR-5.3, BR-6.1

### Step 5 — WebSocket 엔드포인트
- [x] `/ws` — 연결 수립 후 **5초 타이머** (BR-5.6)
- [x] 첫 프레임이 `{type:'auth', token}`이 아니면 `auth_error` 후 종료. 인증 전 다른 프레임은 **처리하지 않는다**
- [x] `verify_token()` 실패 시 `auth_error` 후 종료
- [x] 성공 시 `register()` → `auth_ok`
- [x] 수신 루프는 **사실상 비어 있다** — 전송이 HTTP라(ADR-001) 연결 종료 감지용이다
- [x] 종료 시 `unregister()`. **예외 경로에서도** 반드시 (try/finally)
- 대응: FR-1.3, FR-5.1, BR-5.6

### Step 6 — 백엔드 테스트
Test Strategy **Standard**.
- [x] `test_ws_registry.py` — 등록·해제, **두 번째 연결이 첫 번째에 `session_replaced`를 보낸 뒤 닫음**, 연결 없는 사용자를 조용히 건너뜀, **한 소켓이 죽어도 나머지가 받음**, 죽은 소켓이 unregister됨, 발신자 포함 (7~8개)
- [x] `test_rooms_api.py` — 생성 201, 빈 목록 400, 친구 아닌 id 400, **생성이 한 트랜잭션**(참여자 INSERT 실패 시 방도 없음), 목록이 내 방만, 빈 목록 200, 상세 403(참여자 아님), **없는 방도 403**, 상세에 남의 토글 없음 (9~10개)
- [x] `test_rooms_unread.py` — 배지 계산, 메시지 없는 방 0, **한 번의 쿼리로 전부**(N+1 회귀), `last_read_seq` 전진, **역행 요청 무시 + 200**, 조건절이 SQL에 실제로 있음 (6~7개)
- [x] `test_ai_toggle.py` — 본인 행만 바뀜, **다른 참여자 설정 불변**, 신규 방 기본 TRUE, 비참여자 403 (4~5개)
- [x] `test_ws_auth.py` — 5초 타임아웃 종료, 인증 전 프레임 거부, 잘못된 토큰 `auth_error`, 성공 시 `auth_ok` + 레지스트리 등록, 종료 시 unregister (5~6개)
- 대응: NFR-7 — FR-3.x·FR-5.x·FR-6.1의 수용 기준

### Step 7 — FR-10 참여자 관리 — **절단됨 (2026-07-30) → 복원됨 (2026-07-31)**

> 2026-07-30에 `scope-document.md`의 위험 등록부가 지정한 1순위 절단을 적용했다. U5(XL)에 시간을 돌려주기 위한 결정이었다.
>
> **2026-07-31에 되살렸다.** 절단 사유였던 U5 압박이 U5 완료로 사라졌고, 이 계획이 예고한 대로 **다른 단계를 하나도 건드리지 않고** 이 단계만 실행해 복원됐다. `AlreadyMember` 예외와 응답 코드 규약이 자리를 지키고 있었던 것이 그 값어치다 — 오류 규약을 다시 정하지 않았다.
- [x] `add_member()` — 친구 확인(BR-3.2), 중복 시 400 `ALREADY_MEMBER` (BR-10.1), `ai_check_enabled=TRUE` 초기화
- [x] `leave_room()` — `room_members` 행 삭제. `member_user_ids()`가 실시간 조회라 브로드캐스트에서 자동으로 빠진다 (BR-10.2)
- [x] 라우터 2개 (`POST /rooms/{id}/members` 201, `DELETE /rooms/{id}/members/me` 204) + `AddMemberRequest`
- [x] `test_rooms_members.py` — **15개.** 3명 되기, 추가된 사람의 목록에 나타남, 기본값 켜짐(BR-6.2), 중복 400, 자기 자신도 `ALREADY_MEMBER`, 친구 아님 400, 비참여자 403, 없는 방 403, 나간 뒤 목록에서 사라짐, `member_user_ids()`에서 빠짐, 남은 사람 불변, 두 번 나가기 403, **마지막 참여자가 나가도 메시지는 남음**, 인증 2개
- 대응: FR-10.1, FR-10.2 (**Should**)

**판정 순서를 403 → `ALREADY_MEMBER` → `NOT_A_FRIEND`로 정했다.** 403이 먼저인 것은 다른 검사가 방의 내용을 건드리기 때문이고(참여자가 아닌 사람에게 "이미 있다"를 주면 명단을 확인해주는 셈이다), `ALREADY_MEMBER`가 `NOT_A_FRIEND`보다 먼저인 것은 정확한 사유를 주기 위해서다 — 나중에 들어온 참여자는 내 친구가 아닐 수 있고(BR-3.2가 초대자 기준이다), 친구 검사를 먼저 두면 그 사람을 다시 추가할 때 원인을 잘못 읽는 문구가 나간다.

**마지막 참여자가 나가도 방을 지우지 않는다.** `create_room()`이 경계하는 "유령 방"과 겉모습이 같지만 성격이 다르다 — 그쪽은 메시지가 없는 방이 트랜잭션 분리로 생기는 결함이고, 이쪽은 메시지와 판정 로그가 이미 쌓인 방이 정상 경로로 비는 것이다. 지우려면 그 데이터를 함께 지워야 하는데(FK가 RESTRICT다) 그것이 이 프로젝트가 모으려는 실험 데이터 자체다. `Room` 모델의 생애주기 주석이 이미 같은 판단을 적어 두었다.

### Step 8 — `wsClient`
- [x] `src/lib/wsClient.ts` — `connect(token)`·`disconnect()`
- [x] `onopen`에서 즉시 `{type:'auth', token}` 전송
- [x] 프레임 라우팅 — `auth_ok`·`auth_error`·`session_replaced`·`message`
- [x] **`replaced` 플래그가 재연결을 막는다** (BR-5.5). 없으면 밀려난 탭이 다시 붙어 순환한다
- [x] 그 외 단절에는 지수 백오프 1→2→4→8→16초 재연결. 재연결 중임을 표시
- [x] `useChatStore.getState()`로 컴포넌트 밖에서 갱신 (ADR-004)
- 대응: FR-1.3, FR-5.1, BR-5.5

### Step 9 — `chatStore` rooms·unread·toasts 슬라이스
- [x] `receiveMessage(msg)` — 보고 있는 방이면 목록에 추가(**ID로 중복 제거**) + `markRead` 호출. 아니면 `unread += 1` + 토스트 (BR-5.9)
- [x] **중복 제거가 필수다** — 내 메시지는 HTTP 응답과 WS 푸시 양쪽으로 온다 (BR-5.8, FR-4.3)
- [x] `enterRoom(roomId)` — **포인터를 먼저 옮기고 그다음 히스토리** (BR-3.5). 반대면 그 사이 도착한 메시지가 유실된다
- [x] 토스트 큐 — 4초, 최대 3개
- 대응: FR-3.3, FR-4.3, FR-5.2, FR-5.3, BR-3.5

### Step 10 — `RoomListView`와 `ToastHost`
- [x] `RoomListView` — 목록(이름 없으면 표시명 3명 + `외 N명`), 배지(**0이면 표시 안 함**), 생성 폼(**친구 다중 선택** + 방 이름 선택)
- [x] 비어 있음: "채팅방이 없습니다. 친구를 초대해 만들어보세요."
- [x] `session_replaced` 배너 상단 고정 — "다른 탭에서 접속했습니다 — 이 탭에서 계속하려면 새로고침하세요"
- [x] `ToastHost` — `aria-live="polite"`. 클릭 시 그 방으로 이동 + 배지 소멸
- [x] 접근성 — 배지에 `aria-label="안 읽은 메시지 3개"`, 배너 `role="status"`, 목록은 `<ul>`/`<li>`, 토글은 **`<input type="checkbox">` + 보이는 라벨**(div로 만들지 않는다)
- [x] `data-testid` 8개 — `room-list`, `room-list-item-{id}`, `room-unread-badge-{id}`, `room-create-open`, `room-create-submit`, `room-ai-toggle`, `toast-{roomId}`, `session-replaced-banner`
- 대응: FR-3.1, FR-3.2, FR-5.2, FR-5.3, FR-6.1

### Step 11 — 프론트 테스트
- [x] `wsClient.test.ts` — 연결 후 auth 프레임 전송, `session_replaced` 후 **재연결 안 함**, 그 외 단절에는 재연결, 백오프 증가 (5~6개)
- [x] `chatStore.test.ts` — **`business-logic-model.md`가 지목한 이 단위의 테스트 의무**: 포인터 이동 후 히스토리 응답 전 도착한 메시지가 **유실되지 않음**, 히스토리와 스트림에 같은 메시지가 있어도 **한 번만 표시**, 다른 방 메시지는 배지+토스트, 보고 있는 방은 토스트 없음 (6~7개)
- [x] `RoomListView.test.tsx` — 목록 렌더, 배지 0이면 없음, 친구 다중 선택 후 생성, 빈 목록 문구, 배너 (6개)
- 대응: **NFR-7 — FR-3.3이 이 단위의 명시된 테스트 의무다**

---

## 요구사항 → 단계 추적

| FR/BR | 단계 |
|---|---|
| FR-1.3 WS 첫 프레임 인증 | 5 / 검증 6 |
| FR-3.1 친구 다중 선택 방 생성 | 3, 10 / 검증 6, 11 |
| FR-3.2 내 방 목록 | 3, 10 / 검증 6 |
| FR-3.3 구독 먼저, 히스토리 나중 | 9 / **검증 11 (명시된 의무)** |
| FR-5.1 사용자당 연결 1개 | 2, 5, 8 / 검증 6, 11 |
| FR-5.2 안 읽은 배지 | 3, 4, 9, 10 / 검증 6, 11 |
| FR-5.3 토스트 | 9, 10 / 검증 11 |
| FR-5.4 탭 열린 동안만 | 8 (설계상 자동) |
| FR-6.1 개인별 AI 토글 | 3, 4, 10 / 검증 6 |
| FR-10 참여자 관리 (Should) | **7 (조건부)** |

## 계획에서 뺀 것

- **마이그레이션** — `rooms`·`room_members`는 U1이 이미 만들었다
- **히스토리 조회 API** — U5 소관 (`GET /rooms/{id}/messages`)
- **메시지 전송·판정** — U5 소관
- **미전송 큐** — BR-5.7이 명시적으로 배제. 오프라인 사용자는 다음 입장 시 히스토리로 받는다
- **Service Worker + Web Push** — FR-5.4가 범위 밖으로 정했다
- **방 삭제·방장 권한** — 요구사항에 없다. `rooms.created_by`는 기록이지 권한이 아니다

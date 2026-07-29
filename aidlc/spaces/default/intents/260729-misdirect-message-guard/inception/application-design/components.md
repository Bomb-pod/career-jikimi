# Components — career-jikimi

## 개요

`../requirements-analysis/requirements.md`의 FR 11영역을 구현 가능한 컴포넌트로 나눈 것이다. 경계 기준은 **한 컴포넌트가 하나의 데이터 소유권과 하나의 나열 가능한 책임을 갖는가**이며, 백엔드는 Q4에서 확정한 기능별 모듈 구조를 따른다.

팀 관행(`team-practices`)은 `practices-discovery`를 건너뛰어 확립되지 않았다. `org.md`의 기본값(린터·포매터는 프로젝트 설정에 위임)이 적용되며, 구체적 도구 선택은 Code Generation에서 정한다.

## 시스템 경계

```
+----------------------------------------------------------+
|  브라우저 (React SPA)                                      |
|                                                            |
|  [AuthView] [FriendsView] [RoomListView] [ChatView]        |
|         \        |            |            /               |
|          +-------+------------+-----------+                |
|                        |                                   |
|                  [chatStore]  (Zustand)                    |
|                    |       |                               |
|            [apiClient]  [wsClient]                         |
+--------------------|-----------|---------------------------+
                     |           |
              HTTP (요청/응답)  WebSocket (서버→클라 푸시)
                     |           |
+--------------------v-----------v---------------------------+
|  FastAPI (단일 프로세스)                                    |
|                                                            |
|  auth/   friends/   rooms/   messages/   judgment/         |
|     \       |         |         |    \      /              |
|      +------+---------+---------+     +----+               |
|                   |                        |               |
|              core/db                  core/ws_registry     |
+-------------------|------------------------|---------------+
                    |                        |
              +-----v-----+          +-------v-------+
              |  MariaDB  |          | OpenAI API    |
              +-----------+          +---------------+
```

<!-- Text fallback: 브라우저의 React SPA는 네 개의 뷰(인증·친구·방목록·채팅)를 갖고, 모두 Zustand 스토어를 공유한다. 스토어 아래에 HTTP를 담당하는 apiClient와 WebSocket 수신을 담당하는 wsClient가 있다. 서버는 단일 프로세스 FastAPI이며 auth/friends/rooms/messages/judgment 다섯 기능 모듈과 공용 core(db, ws_registry)로 구성된다. messages와 judgment 모듈이 OpenAI API를 호출하고, 모든 모듈이 MariaDB를 쓴다. -->

**전송은 HTTP, 수신은 WebSocket이다.** 이 비대칭이 이 설계의 중심이며 근거는 `decisions.md`의 ADR-001에 있다.

## 백엔드 컴포넌트

### `core/config`

환경변수를 읽어 타입이 붙은 설정 객체로 노출한다. 다른 모든 컴포넌트가 여기서만 설정을 읽는다.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | 없음 (읽기 전용 설정) |
| 공개 표면 | `settings` 싱글턴 — `DATABASE_URL`, `JWT_SECRET`, `OPENAI_API_KEY`, `AI_CONTEXT_N`(기본 10), `AI_VERDICT_THRESHOLD`(기본 0.7), `AI_TIMEOUT_SECONDS`, `CORS_ORIGINS` |
| 경계 | 비밀은 여기를 통해서만 들어온다. 다른 모듈이 `os.environ`을 직접 읽지 않는다 (FR-1.4, NFR-6) |

### `core/db`

SQLAlchemy async 엔진과 세션 팩토리. 요청 단위 세션을 FastAPI 의존성으로 제공한다.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | 커넥션 풀 |
| 공개 표면 | `get_session()` 의존성, `Base` 선언적 기반 클래스 |
| 경계 | 트랜잭션 경계는 **요청 하나 = 트랜잭션 하나**가 기본이다. 예외는 `messages`의 seq 채번(FR-4.2)이며 그 안에서 명시적으로 잠금을 건다 |

### `core/ws_registry`

연결된 사용자의 WebSocket을 프로세스 메모리에 보관하고 방 참여자에게 밀어낸다.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | `dict[user_id, WebSocket]` — 프로세스 메모리 |
| 공개 표면 | `register(user_id, ws)`, `unregister(user_id)`, `push_to_users(user_ids, payload)` |
| 경계 | **이 컴포넌트가 CON-1(단일 프로세스)의 원인이다.** 레지스트리가 메모리에 있으므로 워커를 늘리면 갈라진다. 확장이 필요해지면 이 컴포넌트만 Redis pub/sub으로 교체하면 되도록 표면을 좁게 유지한다 |

### `auth`

회원가입·로그인·토큰 검증.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | `users` 테이블 |
| 공개 표면 | `POST /auth/signup`, `POST /auth/login`, `current_user()` 의존성, `verify_token(token) -> user_id` |
| 대응 요구사항 | FR-1.1~FR-1.4 |
| 경계 | 비밀번호 해시는 이 모듈 밖으로 나가지 않는다. `verify_token`은 WebSocket 인증(FR-1.3)에서도 쓰이므로 HTTP 의존성과 분리된 순수 함수로 노출한다 |

### `friends`

친구 검색·등록·별칭 관리.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | `friendships` 테이블 (`alias` NOT NULL) |
| 공개 표면 | `GET /friends`, `GET /users/search?username=`, `POST /friends`, `PATCH /friends/{id}` |
| 대응 요구사항 | FR-2.1~FR-2.4 |
| 경계 | 별칭 해석(누구를 어떻게 표시할지)은 이 모듈이 소유한다. `rooms`가 참여자를 표시할 때 이 모듈의 조회 함수를 쓴다 — 표시명 규칙이 두 곳에 흩어지지 않게 한다 |

### `rooms`

방 생성·목록·입장·안 읽은 개수.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | `rooms`(`last_seq` 포함), `room_members`(`ai_check_enabled`, `last_read_seq`) |
| 공개 표면 | `POST /rooms`, `GET /rooms`, `GET /rooms/{id}`(방 상세 — 참여자 표시명과 본인 `ai_check_enabled` 포함), `PATCH /rooms/{id}/ai-check`, `POST /rooms/{id}/read` |
| 대응 요구사항 | FR-3.1~FR-3.3, FR-5.2, FR-6.1, FR-10 (Should) |
| 경계 | `rooms.last_seq`를 소유하지만 **증가시키는 것은 `messages`다** — 채번이 메시지 저장 트랜잭션 안에 있어야 하기 때문이다(FR-4.2). 이 예외는 ADR-003에 기록한다 |

### `messages`

메시지 전송(판정 포함)·히스토리 조회·오발송 신고.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | `messages` 테이블 (`seq`, `verification_status`, `misdirect_reported_at`) |
| 공개 표면 | `POST /rooms/{id}/messages`, `GET /rooms/{id}/messages`, `POST /messages/{id}/report`, `DELETE /messages/{id}/report` |
| 대응 요구사항 | FR-4.1~FR-4.4, FR-11 |
| 경계 | 전송 경로 전체를 오케스트레이션한다 — 판정 호출(`judgment`에 위임), seq 채번, 저장, 브로드캐스트(`core/ws_registry`에 위임). **판정의 내용은 모르고 결과만 받는다** |

### `judgment`

LLM 호출·점수 판정·판정 로그.

| 항목 | 소유 |
|---|---|
| 소유 데이터 | `judgment_logs` 테이블 |
| 공개 표면 | `judge(room_id, context_messages, candidate_text) -> JudgeResult`, `PATCH /judgments/{id}` (user_action 갱신), 집계용 조회 함수 |
| 대응 요구사항 | FR-6.2~FR-6.4, FR-6.7, FR-7.1~FR-7.5, FR-8.1 |
| 경계 | **프로젝트가 공들이는 곳이다.** 프롬프트 구성, Structured Outputs 스키마, 타임아웃·재시도, 로그 적재를 모두 소유한다. `messages`는 이 모듈의 내부를 모른다 |

`JudgeResult`는 셋 중 하나다 — `Appropriate(score, log_id)`, `Inappropriate(score, log_id)`, `Failed(log_id)`. 호출자는 이 셋만 분기하면 된다.

## 프론트엔드 컴포넌트

### `apiClient`

HTTP 호출 래퍼. JWT 부착, 오류 정규화, 타임아웃.

| 항목 | 소유 |
|---|---|
| 공개 표면 | 각 엔드포인트별 함수. `sendMessage()`는 201/409를 구분해 판별 가능한 결과 타입으로 반환한다 |
| 경계 | 409(부적절 판정)를 예외로 던지지 않는다 — 정상 흐름의 한 갈래이기 때문이다. 예외는 네트워크·5xx에만 쓴다 |

### `wsClient`

WebSocket 연결·인증·재연결·수신 프레임 분배.

| 항목 | 소유 |
|---|---|
| 소유 상태 | 소켓 인스턴스, 연결 상태 |
| 공개 표면 | `connect(token)`, `disconnect()`, 수신 시 `chatStore` 갱신 |
| 대응 요구사항 | FR-1.3(첫 프레임 auth), FR-5.1 |
| 경계 | **보내는 것은 인증 프레임 하나뿐이다.** 그 외에는 받기만 한다 |

### `chatStore` (Zustand)

애플리케이션 상태의 단일 출처.

| 슬라이스 | 내용 | 대응 |
|---|---|---|
| `auth` | 토큰, 현재 사용자 | FR-1.2 |
| `friends` | 친구 목록(별칭 포함) | FR-2.4 |
| `rooms` | 방 목록, 방별 안 읽은 개수 | FR-5.2 |
| `messages` | 현재 방의 메시지, 낙관적 임시 메시지 | FR-4.3 |
| `degraded` | degraded 플래그, degraded 중 전송 횟수(프로브 카운터) | FR-8.3, FR-8.5 |
| `toasts` | 토스트 큐 | FR-5.3 |

`degraded`는 **메모리에만** 둔다 — `localStorage`·`sessionStorage`에 쓰지 않는다. 새로고침 시 초기화가 FR-8.3의 요구사항이다.

### 뷰 컴포넌트

| 컴포넌트 | 책임 | 대응 |
|---|---|---|
| `AuthView` | 회원가입·로그인 폼 | FR-1.1, FR-1.2 |
| `FriendsView` | 검색·등록(별칭 필수)·별칭 수정 | FR-2.1~FR-2.3 |
| `RoomListView` | 방 목록, 안 읽은 배지, 방 생성 | FR-3.1, FR-3.2, FR-5.2 |
| `ChatView` | 메시지 목록, 입력창, AI 토글, 검증 배지, 신고, **프라이버시 고지** | FR-3.3, FR-4.3, FR-6.1, FR-6.5, FR-8.6, FR-11.1, **NFR-5** |
| `JudgeConfirmDialog` | 부적절 판정 확인 팝업 | FR-6.6 |
| `DegradedDialog` | 첫 검증 실패 확인 팝업 | FR-8.2 |
| `ToastHost` | 토스트 렌더링 | FR-5.3, FR-8.5(복귀 알림) |

### UI 컴포넌트 명세 — 확인 팝업

`JudgeConfirmDialog`와 `DegradedDialog`는 같은 규칙을 따른다. 이 둘이 이 앱에서 사용자의 판단을 가로막는 유일한 지점이라 접근성 요구가 가장 높다.

| 요구 | 구현 |
|---|---|
| ARIA role | `role="alertdialog"` — 단순 dialog가 아니라 응답을 요구하는 상황이다 |
| 포커스 | 열릴 때 기본 버튼("취소")으로 이동, 닫힐 때 입력창으로 복귀 |
| 포커스 트랩 | 열려 있는 동안 Tab이 팝업 밖으로 나가지 않는다 |
| Escape | 취소와 동일하게 동작. 입력창 텍스트는 유지된다 (FR-6.6) |
| 배경 클릭 | **닫지 않는다.** 실수로 흘려보내면 안 되는 결정이다 |
| 라벨 | 버튼 문구는 "보내기" / "취소" — 동작을 그대로 쓴다. "확인"·"OK"는 쓰지 않는다 |
| 대비 | 텍스트 4.5:1, 버튼 3:1 이상 (WCAG AA) |
| 색 의존 금지 | 부적절 표시를 색만으로 하지 않는다. 아이콘 또는 텍스트를 함께 쓴다 |

토스트(`ToastHost`)는 `aria-live="polite"` 영역에 렌더링해 스크린리더가 새 메시지 도착을 읽도록 한다.

### 프라이버시 고지 (NFR-5)

`ChatView`가 소유한다. AI 검증 토글 옆에 상시 표시되는 짧은 문구와, 그것을 누르면 열리는 설명이다.

| 위치 | 내용 |
|---|---|
| 토글 옆 상시 표시 | "검증 시 최근 대화가 외부 AI로 전송됩니다" (작은 글씨, 아이콘 포함) |
| 클릭 시 | 최근 `N`개 메시지 본문만 전송되며 참여자 정보는 포함되지 않는다는 설명 (FR-6.2) |

토글이 켜져 있을 때만이 아니라 **항상** 보인다 — 켜기 전에 무슨 일이 일어나는지 알아야 결정할 수 있다.

### 다중 탭 처리

`ws_registry.register()`는 사용자당 연결 1개를 유지하므로(FR-5.1), 같은 사용자가 두 번째 탭을 열면 **첫 번째 탭의 연결이 닫힌다.** 그냥 두면 앞 탭은 조용히 죽어 실시간 수신·배지·토스트가 멈추고, 사용자는 그 사실을 모른다.

| 상황 | 처리 |
|---|---|
| 서버가 기존 연결을 교체할 때 | 닫기 전에 `{type:'session_replaced'}` 프레임을 보낸다 |
| 밀려난 탭이 그 프레임을 받으면 | 재연결을 시도하지 않는다. 화면 상단에 "다른 탭에서 접속했습니다 — 이 탭에서 계속하려면 새로고침하세요" 배너를 띄운다 |
| 밀려난 탭에서 전송을 시도하면 | HTTP는 여전히 동작한다(전송 경로는 WS와 무관하다, ADR-001). 다만 남의 메시지가 안 들어오므로 배너를 유지한다 |

**전송이 HTTP인 덕분에 밀려난 탭도 반쪽은 살아 있다.** 만약 전송까지 WS였다면 그 탭은 완전히 죽었을 것이다 — ADR-001의 부수 효과다.

### 화면 상태

각 뷰는 다섯 상태를 모두 갖는다. 특히 자주 빠지는 것을 명시한다.

| 뷰 | 비어 있음 | 로딩 | 오류 |
|---|---|---|---|
| `FriendsView` | "아직 친구가 없습니다. 아이디로 검색해 추가하세요." | 검색 중 스피너 | "그런 아이디가 없습니다" |
| `RoomListView` | "채팅방이 없습니다. 친구를 초대해 만들어보세요." | 스켈레톤 | 재시도 버튼 |
| `ChatView` | "첫 메시지를 보내보세요." + 콜드스타트 안내 | 히스토리 스켈레톤 | 재연결 표시 |

`ChatView`의 비어 있음 상태에는 **콜드스타트 안내를 함께 띄운다** — 방에 메시지가 `N`개 미만이면 판정이 돌지 않는데(FR-6.4), 그걸 모르면 "AI 검증이 켜져 있는데 왜 아무 일도 안 일어나지"가 된다.

## Assumptions & Open Questions

- 프롬프트의 구체적 문안은 이 단계에서 확정하지 않았다. 스키마와 호출 방식은 ADR-005가 정하고, 문안은 Functional Design 또는 Code Generation에서 다듬는다.
- `friends` 모듈이 표시명 해석을 소유한다는 결정은 `rooms`가 참여자 목록을 반환할 때 조인이 필요하다는 뜻이다. 성능은 데모 규모에서 문제되지 않으나 N+1 조회가 되지 않도록 주의한다.
- 프론트엔드 라우팅 라이브러리(React Router 등)를 쓸지, 단일 페이지 안에서 뷰 전환만 할지 정하지 않았다. 화면이 넷뿐이라 후자로도 충분하다.
- `wsClient`의 재연결 정책(백오프 간격, 최대 시도)이 정해지지 않았다. 요구사항에 없으나 데모 중 끊기면 눈에 띈다.

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

Second pass. I re-read all five artifacts fresh (not diffed against my memory of the prior version) and traced each of the five fixes against its original finding, plus the three specific questions raised in the fix summary. All five blocking findings are genuinely resolved — not just asserted-away. I found six residual items while attacking the fixes themselves; none of them rise to "a developer can't build this without asking the architect," which is the bar this review uses. They're recorded below as refinements, explicitly separated from the (zero) remaining contradictions/gaps that would block.

### The five blocking findings — verified closed

**1. `ai_check_enabled` reader.** `rooms.get_membership(user_id, room_id) -> RoomMember | None` (`component-methods.md`) now exists and returns exactly what `send_message` step 1 needs (`RoomMember | None` including `ai_check_enabled`, `last_read_seq`); `member_user_ids()` is now correctly scoped to broadcast-target lookup only, and the docstring says so explicitly. The data-flow diagram (`component-dependency.md`, line ~93) was updated to call `get_membership()` for "참여자 자격 + ai_check_enabled" and `member_user_ids()` separately for "브로드캐스트 대상" — matches. Closed.

**2. `force_log_id` validation.** Verified against the two questions posed:

- *Does the four-check validation close the double-submit bypass?* Yes, for the case it targets. The mechanism is a two-step pattern: `get_log_for_force()` does an optimistic pre-check (exists / owner / room / unconsumed), then `send_message` calls `set_user_action(log_id, 'sent')`, which is documented to throw `AlreadyResolved` if the label is already set. Tracing two concurrent double-click requests: both may pass `get_log_for_force()`'s read (that check alone is racy), but only one can win at `set_user_action()` if that write is atomic (`UPDATE ... WHERE user_action IS NULL` + affected-row check) — the second gets `AlreadyResolved` and never reaches the seq-allocation transaction, so no second message is created. **The gap**: the document states the *contract* ("이미 채워져 있으면 AlreadyResolved를 던진다") but never states that the underlying check-and-set must be atomic. A naive read-then-write implementation (fetch the ORM object, check in Python, write) would not actually be race-free under concurrent requests. Given the design already uses `SELECT ... FOR UPDATE` elsewhere (seq allocation) and demonstrates concurrency awareness, I judge this a **refinement** (state explicitly that `set_user_action`'s guard is an atomic conditional update), not a blocker — but it's the one place the "single-use" claim is asserted more strongly than the document actually proves.
- *Is there still a bypass path?* One narrow one: the four checks (exists / owner / room / unconsumed) never check that the retried `text` matches the `candidate_text` that was actually judged. A client could reuse a valid, unconsumed, same-room, self-owned `log_id` to push different text through as `flagged_sent`, decoupling the judgment log's recorded `score`/context from what was actually sent. Under the documented UI (`JudgeConfirmDialog` only offers 보내기/취소, no text-edit surface), this isn't reachable through normal use, and it's a self-directed bypass of the same shape ADR-007 already declared out of the demo's threat model. **Refinement**, not a blocker.

**3. Multi-tab eviction.** The new "다중 탭 처리" section (`components.md`) gives the displaced tab an explicit signal (`session_replaced` frame before close), a defined non-reconnect behavior, and a user-visible banner — this closes the original "silently blacks out" finding. **New gap introduced by the fix itself**: `session_replaced` was added to `components.md`'s narrative but not to the two other documents that enumerate the WS frame protocol — `component-methods.md`'s `wsClient` "수신 프레임" table still lists only `auth_ok` / `auth_error` / `message`, and `services.md`'s "WebSocket 프레임 봉투" example block still shows only the same three types. The behavior is unambiguous from `components.md` alone, so I judge this a documentation-sync **refinement**, not a blocker — but it's exactly the kind of cross-document drift this stage is supposed to prevent, worth a quick pass before Functional Design.

**4. `GET /rooms/{id}`.** `rooms.get_room_detail(user_id, room_id) -> RoomDetail` is now fully specified — participants with alias-resolved names via `friends.resolve_display_names()`, caller's `ai_check_enabled`, `last_read_seq`, `Forbidden`(403) for non-participants. This directly satisfies FR-2.4's room-participant-list acceptance test. Closed.

**5. NFR-5 privacy notice.** Owned by `ChatView`, with a concrete two-tier disclosure (always-visible line + expandable detail) and added to `ChatView`'s requirement mapping. Closed.

### Direct questions on the orphan-log and metrics fixes

**Does the orphan-log handling stay consistent with FR-7.4's `verdict IS NOT NULL` rule?** Yes. The new "미해소 로그" section correctly keeps unresolved rows (`verdict='inappropriate'`, `user_action IS NULL`) inside FR-7.4's aggregation base (they satisfy `verdict IS NOT NULL`) while explicitly excluding them from the precision numerator/denominator (neither TP nor FP) and surfacing them separately as "미응답 건수." This doesn't contradict FR-7.4's text or FR-7.4's own GWT example — it's a legitimate, non-strawmanned resolution of a case the requirement was silent on. One **minor, non-blocking traceability note**: "미응답 건수" is a new signal not present in FR-7.5's "이번 범위에서 산출하는 지표는 다음이 전부다" (declared-exhaustive) table in `requirements.md`. It's arguably a different category (popup-engagement signal, not a judgment-performance metric), but it wasn't flagged as a deviation anywhere. Worth a one-line note back to requirements at the next opportunity; doesn't affect buildability.

**Does ADR-008's CLI choice leave any FR-7.5 metric unreachable?** No. The CLI (`docker compose exec app python -m app.judgment.report`) runs inside the app container with the same DB access as the app itself, so it can join `judgment_logs` and `messages` freely — nothing about the CLI delivery mechanism restricts which tables a report script can query. Separately (pre-existing, not caused by ADR-008): `compute_metrics()`'s own docstring says "집계 대상은 judgment_logs이며 verdict IS NOT NULL인 행만 쓴다," which is imprecise for `신고율` and `미검출 후보` — both of those need `messages.misdirect_reported_at`, not `judgment_logs`. The capability clearly exists (a CLI script has full DB access); the docstring just undersells its own scope. Minor wording nit, not a reachability problem, and not something this round's changes introduced.

### Other residual refinement, found while attacking the fix

**`messages → friends` edge's application site is ambiguous.** The new edge is justified as "히스토리 응답에 발신자 표시명을 실으려면 별칭 해석이 필요하다" (`component-dependency.md`), but `component-methods.md`'s `list_messages()` entry was not updated to mention calling `friends.resolve_display_names()` or to note that returned `Message` objects now carry resolved names. It's also unstated whether the *live* WS-pushed `message` payload (from `send_message` → `ws_registry.push_to_users`) and the HTTP 201 response carry the same resolved names, or only the history-fetch path does — which matters for whether a message looks the same whether it arrived live or via scrollback. Likely resolved naturally by an implementer reusing one serialization function (consistent with the design's repeated "single source of truth" pattern elsewhere), so I'm not blocking on it, but it's worth a one-line clarification before Functional Design.

### Carried forward, unchanged from last round (explicitly deferred by the coordinator, not re-litigated)

- `shouldProbe()`'s counting scope (all sends while degraded vs. only sends to `ai_check`-on rooms) — still ambiguous, still non-blocking.
- FR-8.4's "다시 시도" retry action still has no named method/action in `component-methods.md`'s frontend section — still non-blocking (trivial re-invocation of `sendMessage`).

### Summary

Zero remaining contradictions or missing capabilities that would stop a developer from building this. All five original findings are substantively fixed with sound, non-strawmanned reasoning, verified by tracing the actual mechanism rather than taking the fix summary's word for it. Six items above are recorded as refinements for the approval gate, per this round's stated bar.

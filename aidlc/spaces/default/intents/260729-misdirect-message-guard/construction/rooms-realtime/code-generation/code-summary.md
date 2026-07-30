# Code Summary — rooms-realtime (U4)

`code-generation-plan.md`의 11단계 중 **10단계를 실행했다.** Step 7(FR-10 참여자 관리)은 Q1의 답에 따라 **절단**되었으며 체크박스가 미체크로 남아 복원 시 작업 목록이 된다.

**테이블은 새로 만들지 않았다.** U1의 `0001_initial_schema`가 만든 `rooms`·`room_members`에 쓰기만 한다.

**두 번째 미지수(WebSocket 동시성)가 이 단위에서 닫혔다.**

## 생성된 파일

### 백엔드

| 파일 | 내용 |
|---|---|
| `app/core/ws_registry.py` | `dict[user_id, WebSocket]` + `register`/`unregister`/`push_to_users` (+ 진단·테스트 격리용 `is_connected`/`connection_count`/`clear`). **`register()`가 `session_replaced`를 보낸 뒤 닫는다.** `push_to_users()`는 `try`를 루프 **안**에 둔다 |
| `app/rooms/exceptions.py` | `EmptyRoom`(400)·`NotAFriend`(400)·`RoomForbidden`(403)·`AlreadyMember`(400, 절단된 Step 7용으로 예약, 현재 raiser 없음을 docstring에 명시) |
| `app/rooms/schemas.py` | `MemberOut`에 **`ai_check_enabled` 필드가 없다** — 남의 토글은 구조적으로 나갈 수 없다 |
| `app/rooms/service.py` | `create_room`(한 트랜잭션), `list_rooms`(LEFT JOIN + GROUP BY, `resolve_display_names()` 1회), `get_room_detail`, `mark_read`(조건부 UPDATE), `set_ai_check`, U5 계약 `get_membership`/`member_user_ids` |
| `app/rooms/router.py` | `POST·GET /rooms`, `GET /rooms/{id}`, `POST /rooms/{id}/read`, `PATCH /rooms/{id}/ai-check` |
| `app/rooms/ws.py` | `/ws` — 5초 인증 타임아웃, 첫 프레임 `{type:'auth',token}`, 실패 시 `auth_error`+종료, 드레인 루프, **`finally`에서 `unregister()`** |
| `app/rooms/__init__.py` | U5 계약 둘만 재노출 (라우터는 import하지 않는다) |
| `app/main.py`(수정) | `rooms_router`·`ws_router`를 SPA 폴백보다 먼저 등록 |

### 프론트엔드

| 파일 | 내용 |
|---|---|
| `lib/wsClient.ts` | 연결·해제, `onopen` 즉시 auth, 프레임 라우팅, **`replaced` 플래그가 재연결을 막음**, 1→2→4→8→16초 백오프 |
| `lib/roomName.ts` | 이름 조립(표시명 ≤3 + `외 N명`, 본인 제외). 목록과 토스트가 **같은 함수**를 쓴다 |
| `lib/apiClient.ts`(수정) | `createRoom`/`listRooms`/`getRoom`/`markRead`/`setAiCheck` + 방·메시지 타입 |
| `lib/constants.ts`(수정) | 백오프, 토스트(4초/최대 3), 이름 나열 상한, 방 이름 길이 |
| `store/chatStore.ts`(수정) | rooms·unread·messages·toasts·wsStatus 슬라이스, `receiveMessage`, `enterRoom`, `leaveRoom`, `dismissToast` |
| `views/RoomListView.tsx`, `views/ToastHost.tsx`, `App.tsx`, `index.css` | 화면과 WS 수명주기 마운트 |

## 핵심 구현 결정

| 결정 | 근거 |
|---|---|
| **`unregister(user_id, ws=None)`에 소켓 인자 추가** | **실제 버그를 막은 것이다.** 신원 확인이 없으면 밀려난 탭의 `finally`가 방금 자기를 교체한 **새 연결을 지운다** — 새 탭이 조용히 아무것도 못 받는다. `unregister(user_id)` 형태도 여전히 동작하므로 `component-methods.md`의 시그니처는 유지된다. 전용 테스트가 붙어 있다 |
| `register()`가 **새 소켓을 먼저 넣고** 기존에 알린다 | 위 신원 확인이 밀려난 핸들러가 깨어날 때 이미 올바르려면 이 순서여야 한다. 프레임 먼저·닫기 나중(BR-5.4)은 그대로이며 `closed_after`로 검증한다 |
| `GET /rooms`에 **호출자 본인의** `ai_check_enabled` 추가 | 목록 쿼리가 이미 호출자의 `room_members` 행을 조인하므로 **공짜**이고, 상세를 한 번 더 부르지 않고 방마다 토글을 그릴 수 있다. `MemberOut`은 여전히 남의 값을 실을 수 없다 |
| `POST /rooms`가 **상세 형태**를 반환 | 클라이언트가 만든 방에 바로 입장할 수 있고 파싱 분기가 하나로 끝난다 |
| **`enterRoom(roomId, loadHistory?)`에 히스토리 로더를 주입** | 히스토리 API는 U5 것이지만 FR-3.3의 병합은 **이 단위의 명시된 테스트 의무**다. 주입이 있어야 포인터 이동과 히스토리 응답 **사이에** 메시지를 끼워 넣는 테스트를 쓸 수 있다 |
| `AlreadyMember`를 두되 아무도 던지지 않음 | Step 1이 목록에 넣었고 상태·코드가 이미 정해졌다. **유일한 raiser가 절단된 Step 7에 있다**는 사실을 docstring에 적어 미완성 FR-10으로 오해되지 않게 했다 |
| `friend_user_ids`의 자기 id는 **거부가 아니라 제거** | 그대로 두면 `NOT_A_FRIEND`("당신은 당신의 친구가 아닙니다")가 나오는데 사용자에게 설명할 수 없다. 호출자는 어차피 참여자로 들어간다 |
| 계획에 없던 `ToastHost.test.tsx` 추가 | 토스트 컴포넌트가 `aria-live`·클릭 이동·4초 타이머를 소유하는데 다른 어느 테스트도 그것을 건드리지 않는다 |

## 테스트 커버리지

Test Strategy **Standard**.

| 파일 | 개수 |
|---|---|
| `test_ws_registry.py` | 12 |
| `test_rooms_api.py` | 16 |
| `test_rooms_unread.py` | 10 |
| `test_ai_toggle.py` | 7 |
| `test_ws_auth.py` | 11 |
| `lib/wsClient.test.ts` | 12 |
| `store/chatStore.test.ts` | 17 |
| `views/RoomListView.test.tsx` | 15 |
| `views/ToastHost.test.tsx` | 4 |

**백엔드 243 passed / 0 skipped** (기존 187 + 56). **프론트 90 passed** (기존 42 + 48).

## 검증 결과 — 있는 그대로

| 명령 | 결과 |
|---|---|
| `ruff check .` / `ruff format --check .` | PASS (66 파일) |
| `pytest -q` | **243 passed, 0 failed, 0 skipped** (`-rs`로 skip 없음 확인) |
| `npm run typecheck` / `npm run build` | PASS (39 모듈) |
| `npx vitest run` | **90 passed, 0 failed, 0 skipped** (8 파일) |
| Step 7 절단 확인 | Step 1~6·8~11 전부 `[x]`, **Step 7 세 박스만 `[ ]`**, 제목 문구 그대로. `add_member`·`leave_room`·`POST /rooms/{id}/members`·`DELETE /rooms/{id}/members/me`가 `backend/app`·`frontend/src` 어디에도 없음 |
| `data-testid` 8개 | 전부 존재 (`RoomListView.tsx` 7 + `ToastHost.tsx` 1) |
| 라이브 스택 | 손대지 않았다 |

## 계획과의 차이

| 차이 | 이유 |
|---|---|
| **Step 7 미실행** | Q1의 답. 위험 등록부의 1순위 절단 |
| `unregister()`에 선택적 소켓 인자 | 위 결정 표 — 실제 버그 |
| `GET /rooms`에 `ai_check_enabled` | 위 결정 표 |
| `enterRoom`에 로더 주입 | 위 결정 표 |
| `ToastHost.test.tsx` 추가 | 위 결정 표 |
| `lib/roomName.ts` 분리 (계획은 `RoomListView` 안이라 암시) | 목록과 토스트가 같은 규칙을 쓰는데 두 벌이면 갈라진다 |

## 미해결 — 다음 단계가 알아야 할 것

1. **`test_ws_auth.py`가 `app.main.app`이 아니라 WS 라우터만 담은 작은 `FastAPI()`를 만든다.** `TestClient(app.main.app)`을 컨텍스트 매니저로 열면 lifespan이 돌아 실제 DB를 최대 30초 기다리고(FR-9.2), 매니저를 안 쓰면 소켓마다 이벤트 루프가 달라져 두 연결 교체 경로를 테스트할 수 없다. **보완으로 `/ws`와 방 라우트가 실제 앱에 SPA 폴백보다 앞서 등록되어 있는지 확인하는 테스트 2개를 따로 두었다**
2. 한 테스트가 **본질적으로 비동기인 정리를 기다린다** — 클라이언트 `with` 블록이 끝나도 서버 핸들러의 `finally`가 아직 안 돌았을 수 있다. 고정 sleep 대신 2초 데드라인 폴링(`_wait_until_disconnected()`)을 쓰며, `unregister()`가 영영 안 돌면 실패한다
3. `_require_targets()`가 중복 id를 조용히 접는다 — 그냥 두면 복합 PK에 걸려 500이 된다
4. **`enterRoom`이 캐시된 방 목록의 `last_seq`로 읽음 위치를 전진시킨다.** 히스토리는 U5 소유다. **U5가 들어오면 히스토리 응답이 `markRead`를 몰아야 정확해진다**
5. **`receiveMessage`가 내가 다른 탭에서 보낸 메시지를 특별 취급하지 않는다** — 보고 있지 않은 방이면 내 메시지에도 배지·토스트가 뜬다. 서버도 그것을 안 읽음으로 센다. 억제가 불안정한 이유는 새로고침 후 `auth.user`가 `null`이기 때문이다(`GET /auth/me`가 없다)
6. `messages` 슬라이스가 **현재 방만** 담는다. 방별 캐시를 둘지는 U5가 정한다
7. U5가 쓰는 세 이름 — `app.rooms.get_membership`, `app.rooms.member_user_ids`, `app.core.ws_registry.push_to_users`. `enterRoom`의 기본 히스토리 로더를 `GET /rooms/{id}/messages`로 교체하고 `apiClient.ts`의 `ChatMessage` 타입을 확장해야 한다

## 커밋 상태

커밋되지 않았다.

---

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

Adversarial pass against `backend/app/core/ws_registry.py`, `backend/app/rooms/*`, the modified `backend/app/main.py`, all five new backend test files, and the frontend `wsClient`/`chatStore`/`RoomListView`/`ToastHost` stack, cross-checked against `business-rules.md`, `business-logic-model.md`, `domain-entities.md`, and `application-design/component-methods.md`. All eleven attack vectors were run; every validation command in scope was executed rather than trusted.

### 1. Eviction interlock — held under construction

Traced the failure mode by hand: tab A registers (`_connections[1]=A`), tab B registers. In `register()` (`ws_registry.py:63-84`), the new socket is written to `_connections[user_id]` **synchronously, before any `await`** (line 68), then `session_replaced` is sent and the old socket closed. Because the dict write happens before the first await point, no other coroutine can observe the old mapping once B's `register()` resumes — so by the time A's `finally` runs `unregister(1, A)`, `_connections[1]` is already `B`. Without the `ws` identity parameter, `unregister(1)` would delete B's live entry (the exact scenario the docstring describes at `ws_registry.py:96-104`) — confirmed by reasoning through the trace and by `test_replaced_socket_cleanup_does_not_evict_the_new_connection` (`test_ws_registry.py:114-132`), which asserts `second.sent == [{"type": "message"}]` after the stale cleanup call. The insert-before-notify ordering is therefore load-bearing for the identity check's correctness, exactly as claimed — reversing it would reopen the race.

Signature check against `component-methods.md:28` (`async def unregister(user_id: int) -> None`): the shipped `unregister(user_id: int, ws: WebSocket | None = None) -> None` accepts the declared call shape unchanged (`ws` defaults to `None`), so U5 or any caller using the documented signature is unaffected. Verified via `test_unregister_of_an_unknown_user_is_silent`, which calls `unregister(999)` with no second argument.

Client-side mutual-eviction guard: `wsClient.ts`'s `route()` sets `replaced = true` synchronously on the `session_replaced` frame (line 124), and `onclose` gates `scheduleReconnect()` on that flag (line 77). Server-side, `existing.send_json(...)` is awaited before `existing.close(...)` (`ws_registry.py:75-84`), so the frame is written to the transport before the close handshake starts; WebSocket delivers data frames before the close frame in order, so `onmessage` fires before `onclose` in the browser. `wsClient.test.ts`'s `'session_replaced를 받으면 재연결하지 않는다'` test and — more convincingly — `test_ws_auth.py::test_a_second_connection_replaces_the_first_with_a_frame`, which drives two **real** WebSocket connections through `TestClient` end to end, both pass. This is the strongest evidence available short of a live two-tab browser session, and it's the one test in the suite actually built to catch the mutual-eviction loop if it existed.

### 2. `push_to_users()` fault isolation — confirmed

`try` is inside the `for` loop (`ws_registry.py:138-146`), not wrapping it. `test_one_dead_socket_does_not_block_the_others` deliberately places the dead socket in the **middle** of the target list (`test_ws_registry.py:181-197`) — a loop-wide `try` would still pass a "dead-last" test but fail this one, and it passes. Dead sockets are unregistered via the identity-checked `unregister(user_id, ws)` (line 146), connectionless users are skipped silently (`continue` at line 141, exercised by `test_offline_users_are_skipped_silently`), and sender inclusion is verified by `test_broadcast_includes_the_sender`. All confirmed by the passing suite (not just present in the code).

### 3. `unregister()` on every exit path

`ws.py`'s `finally` (line 86-88) is unconditional on `user_id is not None`, which structurally guarantees cleanup on any exception out of the `try` block (Python's `finally` semantics), not just the tested `WebSocketDisconnect` path. There is no dedicated test that forces an arbitrary non-`WebSocketDisconnect` exception mid-handler to prove the `finally` fires — the guarantee here rests on the language, not a synthetic test — but that is a reasonable place to stop for a `try/finally` this simple, not a coverage gap worth blocking on.

### 4. Conditional UPDATE in `mark_read()` — confirmed via `capture_sql()`

`test_the_guard_clause_is_actually_in_the_sql` (`test_rooms_unread.py:190-204`) inspects the emitted SQL text and asserts `"last_read_seq <"` appears, specifically to rule out a Python-side comparison masquerading as the guard (its own docstring calls this out: a Python-side check would pass the two black-box tests above it but introduces a race). `test_a_backwards_request_is_ignored_but_still_succeeds` and the API-level `test_mark_read_via_the_api_returns_200_even_when_it_cannot_advance` both confirm 0-rowcount is a 200, not an error, and that an out-of-order request cannot resurrect the badge.

### 5. N+1 regressions — none found

`list_rooms()` issues one `LEFT JOIN` + `GROUP BY` query, one batched participant-id query (`_members_by_room`), and one `resolve_display_names()` call (`service.py:202-281`). `test_unread_counts_for_all_rooms_in_one_query` compares SELECT counts between a 1-room and 3-room fixture and asserts equality — this is the right invariant (proportionality, not an absolute count) and it passes. `test_display_names.py` (U3's pre-existing regression test) is part of the 243 that ran green in this session's `pytest` invocation, confirming this unit didn't route around it.

### 6. Personal-settings isolation (BR-6.1, W3) — confirmed

`MemberOut` (`schemas.py:45-59`) declares only `user_id`/`display_name` — structurally incapable of carrying `ai_check_enabled`, verified both by reading the model and by `test_detail_never_exposes_another_members_toggle`'s explicit `assert all("ai_check_enabled" not in member for member in body["members"])`. `GET /rooms`'s addition of the caller's own `ai_check_enabled` rides the existing `RoomMember.user_id == user_id` join condition (`service.py:229-230,244`) — there is no code path that can substitute another participant's row. `set_ai_check()`'s UPDATE is scoped by `RoomMember.user_id == user_id` (`service.py:390-392`), confirmed by `test_toggling_changes_only_the_callers_row`.

### 7. 403-not-404 and one-transaction room creation — confirmed

`get_room_detail()` raises the same `RoomForbidden` whether the room is missing or the caller isn't a member (`service.py:298-308`), tested by both `test_detail_is_forbidden_for_a_non_member` and `test_detail_of_a_nonexistent_room_is_also_forbidden`. `create_room()` inserts `rooms` and `room_members` in one flush-then-continue sequence inside a single session, and `test_room_creation_is_a_single_transaction` monkeypatches `_insert_members` to fail and confirms the `rooms` row does not survive rollback.

### 8. FR-3.3 test — genuinely places the message in the window

Traced the microtask ordering in `chatStore.test.ts:96-110`: `enterRoom(2, load)` is an async function that runs synchronously up to its first `await` (`loadHistory(roomId)`, itself gated on an unresolved promise), so the pointer-move `set(...)` at the top of `enterRoom` completes before the test's next statement runs. `receiveMessage(...)` is then called synchronously, landing genuinely between the pointer move and history resolution — not just adjacent to it in source order. `release()` only then lets history resolve, and the assertion (`[1, 9]`, sorted by `seq`) confirms both survival and correct merge order. This is a real interleaving test, not a cosmetic one.

### 9. FR-10 cut — honest

`grep` across `backend/app` and `frontend/src` found zero occurrences of `add_member`/`leave_room` as callables (only docstring/comment references explaining the cut), and zero route registrations for `POST /rooms/{id}/members` or `DELETE /rooms/{id}/members/me`. `code-generation-plan.md`'s Step 7 checkboxes remain `[ ]` while Steps 1-6 and 8-11 are `[x]`. `AlreadyMember` is defined in `exceptions.py` with a docstring stating plainly that its only raiser lives in the cut Step 7 — this reads as a deliberately reserved contract slot, not an abandoned half-implementation.

### 10. Test honesty

- Reproduced counts exactly: backend `pytest -q -rs` → **243 passed, 0 skipped**; per-file counts for the five new files (`grep -c "^async def test_\|^def test_"`) sum to 12+16+10+7+11 = 56, matching the claimed delta from 187. Frontend `npx vitest run` → **90 passed**, with per-file counts (wsClient 12, chatStore 17, RoomListView 15, ToastHost 4 = 48 new) matching the claimed delta from 42.
- (a) `test_ws_auth.py`'s separate `FastAPI()` app: the two supplementary tests (`test_the_ws_route_is_registered_on_the_real_app`, `test_the_room_routes_are_registered_before_the_spa_fallback`) only check route **presence and ordering** on `app.main.app`, not runtime behavior on the real app. This is a real, correctly self-disclosed gap — the real app's `/ws` handler (with its full auth/registry/lifespan wiring) is never exercised end-to-end in a single test — but it's a narrow, honestly-scoped gap rather than an unstated one, and the isolated-app tests do exercise the actual logic (identity-checked unregister, real-socket close ordering) that the mock-socket tests in `test_ws_registry.py` cannot.
- (b) `_wait_until_disconnected()`'s 2-second poll: confirmed not vacuous — it asserts `is_connected(7) is True` immediately after auth (proving the setup state), then polls for the negative after the `with` block exits, returning `False` (causing the outer `assert` to fail) if the deadline is reached without cleanup. It cannot pass on a bug; it can only be flaky under extreme load, which the design already accepts as a tradeoff over a longer or shorter fixed `sleep`.

### 11. Does it run — reproduced in this session

- `ruff check .` → All checks passed. `ruff format --check .` → 66 files already formatted.
- `pytest -q -rs` in `backend/` → **243 passed in 16.70s, 0 skipped** (`-rs` printed no skip lines).
- `npm run typecheck` → clean. `npm run build` → 39 modules transformed, built in 707ms.
- `npx vitest run` → **8 files / 90 tests passed**, 0 skipped.
- Live stack (`mini_project-app-1`, `mini_project-db-1`, `cj-testdb`) was left untouched; no `docker compose` or `git commit` commands were run.

### Non-blocking findings

1. **`component-methods.md` is stale for two return types.** It declares `mark_read(...) -> None` (line 116) and `set_ai_check(...) -> None` (line 121); the implementation returns `int` (the resulting `last_read_seq`) and `bool` respectively, matching `business-logic-model.md`'s W4 spec and the response schemas. Neither function is in the U4→U5 locked-contract table in `domain-entities.md` (only `get_membership`, `member_user_ids`, `push_to_users` are), so this doesn't break U5 — but a future reader trusting `component-methods.md` literally would be misled about the return shape. Worth a one-line correction to that inception artifact.
2. **`services.md`'s WS envelope catalog omits `session_replaced`.** Only `auth`, `auth_ok`, `auth_error`, `message` are listed (`services.md:127-129`); `session_replaced` is specified in `business-rules.md` (BR-5.4/5.5) and correctly implemented, but a reader who only opens the inception-level `services.md` would not learn this frame type exists.
3. **`ToastHost`'s auto-dismiss timer restarts for all visible toasts whenever the toasts array reference changes** (`ToastHost.tsx:26-37`, effect keyed on `[toasts, dismissToast]`), not just the newly added/updated one. A toast already on screen for 3.9s gets a fresh 4-second window if a second, unrelated toast arrives in the meantime. This doesn't violate any numbered acceptance criterion (the plan's "4초" open item doesn't specify per-toast independence) and is a minor UX nuance, not a defect.

None of the above are blocking. The unit's stated second unknown — WebSocket concurrency — is closed: the eviction interlock, fault-isolated broadcast, and unregister-on-every-exit-path guarantees all held under adversarial tracing and reproduced test runs, and the one place the implementation deviates from the plan's declared contract (register-inserts-before-notify) is required for, not incidental to, the fix it enables.

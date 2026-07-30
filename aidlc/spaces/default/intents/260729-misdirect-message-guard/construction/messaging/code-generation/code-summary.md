# Code Summary — messaging (U5)

`code-generation-plan.md`의 11단계를 `aidlc-developer-agent`가 실행했다. 체크박스가 전부 `[x]`다. **마지막 단위이며 앞의 네 단위가 여기서 만난다.**

**테이블은 새로 만들지 않았다.** U1의 `0001_initial_schema`가 만든 `messages`에 쓰기만 한다.

## 생성된 파일

### 백엔드 — `app/messages/`

| 파일 | 내용 |
|---|---|
| `constants.py` | `MESSAGE_MAX_LENGTH=2000`(Q1의 답), `HISTORY_DEFAULT_LIMIT=50`, `HISTORY_MAX_LIMIT=100` |
| `exceptions.py` | `MessageTooLong`(400 `MESSAGE_TOO_LONG`), `MessageForbidden`(403). 판정 예외는 U2 것을 재사용 |
| `service.py` | `send_message()` — W1 9단계 오케스트레이션, `Sent`/`Blocked` 결과 유니온, `_resolve_forced`, `_decide`(BR-6.1 순서), `_recent_context`, `_persist`(seq 채번), `_broadcast` |
| `history.py` | `list_messages()` + `MessageView` — 커서 페이지네이션, `resolve_display_names()` **1회** |
| `report.py` | `report()`/`unreport()` — 발신자 전용, 상태 무관, `NOW(6)`/`NULL` |
| `schemas.py` | `SendMessageRequest`, `MessageOut`, `HistoryMessageOut`, `MessageListResponse`, `BlockedResponse`, `ReportResponse` |
| `router.py` | 엔드포인트 4개. 201·409를 명시적 `JSONResponse`로 만들어 **409 본문을 봉투 없이** 유지 |

`app/main.py`에 `messages_router`를 SPA 폴백보다 먼저 등록. `tests/conftest.py`에 `live_sessionmaker` 픽스처 추가(실제 커밋, 별도 커넥션, 테이블 정리).

### 프론트엔드

| 파일 | 내용 |
|---|---|
| `lib/apiClient.ts` | `ChatMessage`에 `verification_status`·`misdirect_reported_at`·`sender_display_name?` 추가, `VerificationStatus`, `SendOutcome`, `sendMessage`, `listMessages`, `judgmentAction`, `reportMisdirect`. `request()`를 `requestRaw()` 위로 분리 |
| `lib/constants.ts` | `MESSAGE_MAX_LENGTH`, `PROBE_EVERY`, `DEGRADED_RECOVERED_MESSAGE`, `AI_CONTEXT_N` |
| `store/chatStore.ts` | `degraded`·`pending` 슬라이스, `notice`, `shouldProbe`/`noteDegradedSend`/`enterDegraded`/`exitDegraded`, `applySentMessage`, `setReported`. **`enterRoom`의 기본 로더가 이제 `GET /rooms/{id}/messages`를 부른다** |
| `views/useSendMessage.ts` | 네 갈래 전송 상태 기계 |
| `views/ConfirmDialog.tsx`·`JudgeConfirmDialog.tsx`·`DegradedDialog.tsx` | 팝업 2종 + 공통 껍데기 |
| `views/ChatView.tsx`, `App.tsx` | 채팅 화면. 자리표시자 제거, `ToastHost`가 이제 채팅 화면을 연다 |

## 핵심 구현 결정

| 결정 | 근거 |
|---|---|
| **요청에 `probe: bool` 필드 추가** (계획 문구와 다름) | 계획 Step 10은 프로브를 "`degraded=false`로 보낸다"고 적었으나, 프로브 실패는 서버가 **팝업 없이 201 `failed`** 로 답해야 하고 BR-6.1 규칙 2가 문자 그대로 "degraded **이고 프로브 차례 아님**"이다. 둘 다 서버가 프로브와 비-degraded 첫 전송을 구별해야 하는데 불리언 하나로는 못 싣는다. 이제 `degraded`는 "클라이언트가 degraded 상태다"(프로브에서도 true), `probe`는 "그래도 판정하라"를 뜻한다. **와이어 모양만 다르고 모든 행동 규칙은 명세 그대로다** |
| **`_persist()`가 `await session.commit()`으로 시작한다** | **테스트가 잡은 실제 버그다.** MariaDB InnoDB는 트랜잭션의 read view가 잡힌 뒤 갱신된 행에 잠금 읽기가 닿으면 `1020 Record has changed since last read`를 낸다(MySQL은 최신 커밋본을 준다). 1~5단계가 read view를 잡아 **첫 번째 이후의 동시 전송이 전부 실패했다.** 읽기 단계를 닫으면 `SELECT ... FOR UPDATE`가 새 트랜잭션의 첫 문장이 되는데, 이것이 설계의 6단계 `BEGIN`이 원래 뜻하던 바이기도 하다 |
| `user_action`을 결정 시점이 아니라 **저장 트랜잭션 안에서** 쓴다 | 위 때문에 필요하고(이른 UPDATE가 read view를 다시 연다) 그 자체로 낫다 — 더블클릭 시 `AlreadyResolved`가 메시지까지 함께 롤백한다. 안 그러면 라벨 없는 로그를 가진 메시지나, 메시지 없이 소진된 토큰이 남는다 |
| `link_message()`를 **트랜잭션 안에서** | W1 다이어그램은 COMMIT 뒤 7단계로 그렸으나, 안에 두면 메시지↔로그 연결이 원자적이고 외부 호출이 늘지 않는다. 6→7→8 순서와 **브로드캐스트가 엄격히 커밋 뒤**인 것은 그대로다 |
| 복귀 알림을 `Toast`가 아니라 `notice` 문자열로 | 기존 토스트 큐는 방 키 기반(`id === roomId`, 클릭 시 그 방으로 이동)이다. 시스템 알림은 방이 없어 억지로 넣으면 `toast-{roomId}`와 클릭 동작이 둘 다 깨진다. `ChatView`에 `role="status"`로 렌더 |
| 콜드스타트 안내가 프론트의 `AI_CONTEXT_N = 10`을 쓴다 | **표시용일 뿐이다.** 실제 판정은 서버가 정하며, 불일치해도 안내 문구의 숫자만 달라지고 동작은 안 바뀐다 |
| `pending`을 `messages`와 분리 | 합치려면 가짜 `id`와 가짜 `seq`가 필요한데 그 둘이 정확히 중복 제거 키와 정렬 키다 |
| 판정 실패 팝업에서 **거절해도 `cancelled`를 쓰지 않는다** | `NULL` verdict 로그는 모든 지표 모집단 밖이고(BR-7.2), 라벨을 쓰면 토큰이 소진되어 사용자가 마음을 바꿀 수 없다. FR-8.4의 "다시 시도"가 그 경로를 덮는다 |
| 409 본문이 `{"error": ...}` 봉투 없이 **맨 `{log_id, reason, score}`** | 봉투를 쓰면 `log_id`가 `details` 안으로 밀려나고 정상 분기가 클라이언트의 오류 경로를 타게 된다 |

## 테스트 커버리지

Test Strategy **Standard**. **판정 호출은 전부 목이다.**

| 파일 | 개수 |
|---|---|
| `test_seq_allocation.py` | 9 — **NFR-7 명시 의무 ①** |
| `test_send_message.py` | 25 |
| `test_force_send.py` | 11 |
| `test_history.py` | 12 |
| `test_report.py` | 13 |
| `views/degradedFlow.test.tsx` | 13 — **NFR-7 명시 의무 ②** |
| `views/ChatView.test.tsx` | 27 |

**백엔드 313 passed / 0 skipped** (기존 243 + 70). **프론트 130 passed** (기존 90 + 40).

`chatStore.test.ts`와 `App.test.tsx`는 **추가가 아니라 수정**되었다 — `ChatMessage`에 필수 필드 둘이 생겼고 `view-placeholder`가 실제 채팅 화면으로 대체되었다.

## 검증 결과 — 있는 그대로

| 명령 | 결과 |
|---|---|
| `ruff check .` / `ruff format --check .` | PASS (79 파일) |
| `pytest -q` | **313 passed, 0 failed, 0 skipped** |
| `npm run typecheck` / `npm run build` | PASS (44 모듈, 719ms) |
| `npx vitest run` | **130 passed, 0 failed** |
| 라우트 등록 확인 | `POST·GET /rooms/{id}/messages`, `POST·DELETE /messages/{id}/report` 전부 SPA 폴백보다 앞서 해석됨 |
| 실제 OpenAI 호출 | **없음** — 모든 테스트가 `app.messages.service.judge` 또는 `apiClient.sendMessage`를 교체 |
| 라이브 스택 | 손대지 않았다 |

## 계획과의 차이

| 차이 | 이유 |
|---|---|
| **요청에 `probe` 필드** | 위 결정 표. **와이어 계약이 계획 문구와 다른 유일한 지점** |
| `_persist()`가 커밋으로 시작 | 위 결정 표 — MariaDB 1020 |
| `user_action`을 저장 트랜잭션 안에서 | 위 결정 표 |
| `link_message()`를 트랜잭션 안에서 | 위 결정 표 |
| `notice` 슬라이스 추가 | 위 결정 표 |
| `conftest.py`에 `live_sessionmaker` | 동시성 테스트가 실제 커밋과 별도 커넥션을 요구한다 |
| `chatStore.test.ts`·`App.test.tsx` 수정 | 위 참조 |

## 미해결 — 다음 단계가 알아야 할 것

1. **`probe` 필드가 계획 문구와의 문서화된 이탈이다.** `business-logic-model.md` W1의 요청 모양 `{ text, force_log_id?, degraded? }`와 `component-methods.md`의 `send_message()` 서명 둘 다 한 줄 동기화가 필요하다
2. **MariaDB 1020은 일회성이 아니라 버그의 한 부류다.** 한 트랜잭션에서 같은 행을 `FOR UPDATE` 잡기 **전에** 읽는 경로는 앞으로도 이것을 만난다. `_persist`의 docstring에 적어두었으나 린트 규칙이 강제하지 않는다 — `test_concurrent_sends_to_one_room_produce_contiguous_seq`만이 지킨다
3. **`component-methods.md`의 백엔드 `send_message()` 산문이 여전히 낡았다**(알려진 잔여). 이제 `probe` 인자와 `Blocked(reason=judge_failed)` 갈래까지 빠져 있다
4. **프로브 실패 로그의 `user_action`이 `NULL`로 남는다.** 사용자에게 묻지 않았으니 기록할 행동이 없다. `api_failure_rate` 외 모든 지표가 이미 `verdict IS NULL`을 제외하고 그 하나는 `user_action`을 보지 않는다. 설계가 명시하지 않은 판단이라 남긴다
5. **프로브가 409 `inappropriate`를 받으면 degraded가 해제되면서** 복귀 알림과 확인 팝업이 함께 뜬다. 호출은 분명히 성공했으므로 degraded를 유지하면 다음 네 메시지의 검증을 조용히 건너뛴다. UI가 약간 시끄럽다 — 설계가 이 조합을 다루지 않았다
6. `confirm()`의 409-on-force-retry 분기는 방어적일 뿐이다. `force_log_id`가 있으면 서버가 판정하지 않으므로 테스트로 덮이지 않는다

## 커밋 상태

커밋되지 않았다.

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

Adversarial pass on the merge unit. Ran every "does it run" command myself (not trusting the claimed numbers), then went further and empirically *reproduced* both claimed concurrency defects against the live test MariaDB (`cj-testdb` at `127.0.0.1:33061`) by monkeypatching a broken variant of `_persist()` in a standalone script — without touching any repository file — rather than taking the docstrings' word for it. Both reproductions are below. No blocking findings survived.

### Verified by direct reproduction, not just code-reading

**1. The `_persist()` leading `commit()` — confirmed real, confirmed caught by the test.** I copied `_persist()` with the leading `await session.commit()` (`backend/app/messages/service.py:403`) deleted, monkeypatched it onto `app.messages.service._persist`, and ran the exact `_seed_room`/concurrent-gather scenario `test_concurrent_sends_to_one_room_produce_contiguous_seq` uses (`ai_check_enabled=False`, 8-way `asyncio.gather`, separate connections via `live_sessionmaker`). Result: **1 success, 7 `OperationalError: (1020, "Record has changed since last read in table 'rooms'")`** — reproducing the developer's claimed MariaDB defect exactly, and exactly matching their own description ("첫 번째 이후의 동시 전송이 전부 실패했다"). Root cause confirmed: `get_membership()`'s SELECT opens a REPEATABLE-READ snapshot that nothing closes before the locking read, on every path that skips `judge()` (`disabled`/`degraded`/`skipped_no_context`/force-retry) — `judge()`'s own internal commits mask the bug on the `ok`/`Inappropriate`/`Failed`-probe paths, which is exactly why `test_seq_allocation.py`'s `_seed_room` deliberately uses `ai_check_enabled=False` to force the `disabled` path and hit the bug window. `messaging_support.FakeJudge` also deliberately calls `session.commit()` to mirror the real `judge()`'s transaction-boundary effect — the test author understood this precisely, not incidentally. Without `service._persist`'s fix, `asyncio.gather` (no `return_exceptions=True`) would propagate that `OperationalError` and the real test would error out. **The test is not vacuous; it genuinely catches this regression.**

**2. `FOR UPDATE` is load-bearing — confirmed the test would fail without it.** Separately, I patched `_persist()` to keep the commit fix but drop `.with_for_update()` from the `SELECT rooms.last_seq` and reran the same 8-way concurrent scenario: **only 2 of 8 sends succeeded** (`seqs=[1,2]`, not contiguous 1..8), the rest errored. `test_concurrent_sends_to_one_room_produce_contiguous_seq`'s exact-equality assertion (`seqs == list(range(1, CONCURRENT_SENDS + 1))`) would fail. Confirms item 6's "does it actually fail if `FOR UPDATE` is removed" — yes. The paired test `test_a_locked_room_does_not_block_another_room` / `test_a_locked_room_blocks_that_room_until_release` is also not vacuously true: the second test proves the same room *does* block (holds a lock via a separate connection and asserts the send stays unresolved for `BLOCKED_OBSERVE_SECONDS`), so "another room isn't blocked" is measured against a lock that is independently proven to exist.

**3. `AlreadyResolved` genuinely rolls back the message on a real race, not just sequentially.** Beyond the existing `test_a_consumed_log_rolls_the_message_back` (which pre-consumes a log then sends once), I fired two *concurrent* force-sends at the same not-yet-consumed `verdict=NULL` log via `live_sessionmaker` with two connections. Result: exactly 1 `Sent` + 1 `AlreadyResolved`, and post-race DB state shows `messages` count = 1, `rooms.last_seq` = 1, no orphaned row from the loser. This validates the code-summary's claim that `set_user_action()`'s conditional `WHERE user_action IS NULL` UPDATE inside the save transaction (not before it) is what makes the double-click 1-shot guarantee hold under real concurrency, and that `get_session()`'s catch-all rollback-on-exception (`app/core/db.py:151-157`) is what unwinds the loser's already-`flush()`-ed `INSERT`/`UPDATE rooms.last_seq`.

### Traced and confirmed, no reproduction needed

- **BR-4.3/BR-4.1 ordering**: `send_message()` calls `judge()` (via `_decide`) strictly before `_persist()`, and `_broadcast()` strictly after `_persist()` returns (which itself ends in `await session.commit()`); there is exactly one path into `_persist`/`_broadcast`, so no branch can broadcast a still-rollback-able write.
- **`link_message()`/`set_user_action()` moved inside the save transaction** (deviating from the W1 diagram's post-COMMIT step 7): both are DB-local `UPDATE`s with no external call, so the added lock-hold time under the `rooms` row lock is negligible — this does not reintroduce the BR-4.3/ADR-001 hazard (a 3-5s LLM call) the transaction boundary exists to prevent. It's also strictly safer than the diagram: it makes message-save and log-linkage atomic (no window where a message exists with a dangling/never-linked log, or vice versa).
- **The `probe` wire-field deviation is justified.** I re-derived it independently: under the plan's original single-boolean design (send a probe as `degraded=false`), a probe that hits `Failed` would fall into `_decide`'s "not degraded" branch and return `Blocked(reason=judge_failed)` — i.e., a popup would fire on a probe failure, directly violating BR-8.5 ("실패 -> 팝업 없이 degraded 유지"). One boolean cannot carry both "the client believes it's degraded" and "attempt real judgment anyway" simultaneously against BR-6.1 rule 2's literal wording. The two-field design is necessary, not just convenient, and `SendMessageRequest`/`sendMessage()`/`BlockedResponse` all agree on the wire shape.
- **`degraded=true, probe=true` sent dishonestly cannot bypass anything new.** Traced `_decide()`: `degraded and not probe` is `False` whenever `probe=True`, so this combination always falls through to the real context-check + `judge()` call — behaviorally identical to an honest `degraded=false` request. This is *stricter* than a bypass, not looser.
- **BR-6.1 order is real, not just enum-correct.** `test_toggle_off_wins_over_cold_start`/`test_toggle_off_wins_over_degraded` prove ordering directly. `test_degraded_wins_over_cold_start_and_skips_the_context_query` is non-vacuous by construction: it seeds **zero** context messages and asserts the result is `degraded`, not `skipped_no_context` — if the context-count check ran before the degraded check (or ran at all), `len(context)=0 < N` would force `skipped_no_context` instead, so the assertion itself only passes if the degraded branch short-circuits before the context query executes.
- **force_log_id/BR-6.4/BR-6.9**: text-mismatch, ownership, room, consumed-token, and appropriate-verdict are all independently tested in `test_force_send.py` and hold — a client cannot manufacture `flagged_sent` for unjudged text (six checks in `get_log_for_force`, all read-only, all tested), and a `NULL`-verdict log cannot be replayed (both via the sequential pre-consumed test and my concurrent-race reproduction above).
- **History/report**: `before` is exclusive (`seq <`, `history.py:91`), `limit` clamps to 100 without a 400, `resolve_display_names()` is called once per `list_messages()` call with a query-count regression test present and passing, report/unreport are sender-only with 403 (not 404) for both a stranger's message and a nonexistent one, and `verification_status` is never referenced in `report.py`.
- **Dialogs**: `role="alertdialog"`, default focus on 취소 (`ConfirmDialog.tsx:58-60`), Tab-trap between the two buttons, Escape routes to `onCancel` without touching input text, no `onClick` anywhere on `.dialog-backdrop`, focus returns via `returnFocusTo` on unmount — all independently asserted and passing in `ChatView.test.tsx`.
- **Unverified badge**: exactly `{failed, degraded, skipped_no_context}` (`ChatView.tsx:37-41`), matching BR-8.6.
- **Client-side FR-8.3**: grepped all of `frontend/src` — the only `localStorage`/`sessionStorage` writes are the auth token; `degraded`/`degradedSendCount`/`pending`/`notice` are plain Zustand state with no persistence middleware, and `degradedFlow.test.tsx` asserts zero storage writes plus a fresh-module-import reset.
- **Test honesty**: reran everything myself rather than trusting the table — `ruff check`/`ruff format --check`: pass; `pytest -q`: **313 passed, 0 skipped** (exact match); `npm run typecheck`/`build`: pass (44 modules, 711ms); `npx vitest run`: **130 passed** (exact match). No test file reaches a real judge call — `test_force_send.py` has an autouse `NeverJudge` fixture, every `test_send_message.py`/`test_seq_allocation.py` path either avoids `judge()` via `ai_check_enabled=False` or explicitly monkeypatches it, and both frontend suites `vi.mock('../lib/apiClient')` wholesale. `chatStore.test.ts`/`App.test.tsx` assertions are substantive (ordering checks, dedup checks, real DOM presence checks) — nothing weakened to a tautology.

### Non-blocking findings

1. **`probe=true` is honored without requiring `degraded=true`.** In `_decide()` (`service.py:310-317`), the silent-save-as-`failed` branch on judge failure triggers whenever `probe=True`, regardless of the `degraded` value — the code never checks `degraded and probe` together, only `probe` alone. The legitimate frontend never produces this combination (`chatStore.shouldProbe()` requires `state.degraded` to already be true), but the server doesn't defend against a crafted `{degraded: false, probe: true}` request, which would silently store a `failed` message on a real judge failure instead of surfacing BR-8.1's "always notify" 409. Untested in either direction. Low severity — the message still correctly carries the unverified badge, and it sits inside ADR-007's already-accepted "client fully owns degraded/probe truthfulness, self-directed bypass only, not in the demo's threat model" carve-out — but it's a narrower, unexamined instance of that same carve-out and worth a one-line defensive fix (`if probe and degraded:`) if this ever leaves the demo threat model.
2. **Two off-by-one counts in the "테스트 커버리지" table** (this file, above): `test_report.py` is listed as 13 but pytest collects 14 (the `@pytest.mark.parametrize` over 6 `VERIFICATION_STATUS_VALUES` on `test_every_verification_status_is_reportable` was undercounted by one); `test_history.py` is listed as 12 but collects 11. The pair's sum (25) and the verified aggregate totals (313 backend / 130 frontend) are both exactly correct, so this doesn't misrepresent overall coverage — but `project.md`'s own learned rule ("커버리지 표나 항목 수처럼 셀 수 있는 것은 눈으로 세지 않고 스크립트로 센다") flags exactly this class of mistake; worth a `pytest --collect-only -q | wc -l`-style pass next time.
3. **Comment/behavior mismatch in `useSendMessage.ts` (`send()`, around line 112-115).** The comment claims the probe-counter increment is placed after the round trip specifically so that network-dead ("네트워크에서 죽은") attempts aren't counted toward the probe cycle, but `if (degraded) useChatStore.getState().noteDegradedSend()` runs unconditionally after `roundTrip()` resolves — including the `{kind: 'transport'}` branch — so a network failure during degraded mode *does* advance the probe counter, contradicting what the comment says it avoids. Untested in either direction. Impact is minor (shifts probe timing by at most a couple of messages during network flakiness); worth reconciling the comment with the code or vice versa.
4. **Disclosed follow-up item 1 (above) is slightly incomplete**: it names `business-logic-model.md`'s W1 request shape and `component-methods.md`'s backend Python signature as needing a one-line `probe` sync, but doesn't also name `component-methods.md`'s frontend `opts?: {forceLogId?: number; degraded?: boolean}` type (same file, ~line 283) as needing the same sync. Cosmetic.
5. **Probe-succeeds-as-`inappropriate` double UI (already disclosed as open item 5, confirmed real, not re-flagged as new)**: traced `useSendMessage.send()` — when a probe hits `Inappropriate`, `exitDegraded()` fires and `JudgeConfirmDialog` opens in the same tick, so the recovery banner and the confirm dialog appear together. This is a defensible reading of BR-8.5 ("성공 시 상태는 판정 결과대로") since the call did succeed, and the design docs don't cover this combination — confirming the developer's own disclosure, not adding a new complaint.

None of the above blocks: every transaction/ordering invariant (BR-4.1, BR-4.2, BR-4.3), the `force_log_id` mechanism (BR-6.4/BR-6.9), the BR-6.1 decision order, both NFR-7-mandated test obligations, the dialog contract, history/report semantics, and the unverified-badge rule held up under adversarial, empirically-reproduced testing — including two real MariaDB failures I forced to occur and watched the fix (and its test) actually prevent.

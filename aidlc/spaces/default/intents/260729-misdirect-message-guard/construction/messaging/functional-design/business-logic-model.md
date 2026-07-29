# Business Logic Model — messaging

`../../../inception/units-generation/unit-of-work.md`의 U5가 수행하는 흐름이다. 배정은 `../../../inception/units-generation/unit-of-work-story-map.md`, 요구사항은 `../../../inception/requirements-analysis/requirements.md`의 FR-3.3·FR-4.1~FR-4.4·FR-6.4~FR-6.6·FR-7.1·FR-8.2~FR-8.6·FR-11, 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 서명은 `../../../inception/application-design/component-methods.md`, 트랜잭션·통신 형태는 `../../../inception/application-design/services.md`가 정한다.

규칙 번호(`BR-*`)는 같은 디렉터리의 `business-rules.md`를, 테이블은 `domain-entities.md`를 가리킨다.

**앞의 네 단위가 여기서 만난다.** 이 단위가 XL인 이유이며, `send_message()` 하나가 그 전부를 오케스트레이션한다.

## W1 · 메시지 전송 — 전체 흐름

```
POST /rooms/{id}/messages  { text, force_log_id?, degraded? }
   |
   |-- 1. rooms.get_membership(me, room_id)              [U4]
   |        +-- None --> 403 FORBIDDEN                    (BR-3.3)
   |        → ai_check_enabled 확보
   |
   |-- 2. force_log_id 가 있나?
   |     |
   |     +-- 예 --> judgment.get_log_for_force(           [U2]
   |     |            me, room_id, force_log_id, text)
   |     |            검증 — 소유자/방/미소진/텍스트일치/
   |     |                   verdict IN (inappropriate, NULL)
   |     |            실패 --> 400 또는 403                (BR-6.4)
   |     |          status = 로그의 verdict에서 파생:
   |     |            inappropriate --> flagged_sent
   |     |            NULL(실패)    --> failed
   |     |          log_id = force_log_id
   |     |          → 6번으로
   |     |
   |     +-- 아니오 --> 3번
   |
   |-- 3. 상태 결정                                        (BR-6.1)
   |     |
   |     +-- ai_check_enabled == false --> disabled,  log 없음 --> 6번
   |     +-- degraded && !프로브차례   --> degraded,  log 없음 --> 6번
   |     +-- 방 메시지 수 < N          --> skipped,   log 없음 --> 6번
   |     +-- 그 외 --> 4번
   |
   |-- 4. 문맥 조회 + 판정                                  (BR-4.3)
   |     최근 N개 SELECT
   |     judgment.judge(me, room_id, context, text)       [U2]
   |     ※ 트랜잭션 밖
   |     |
   |     +-- Failed        --> status = failed  --> 5b
   |     +-- Inappropriate --> 5a
   |     +-- Appropriate   --> status = ok,
   |                           set_user_action(auto_sent) --> 6번
   |
   |-- 5a. 부적절 --> 저장 안 함
   |        409 { log_id, score }                          (BR-6.3)
   |        [종료]
   |
   |-- 5b. 실패 --> degraded 상태였나?
   |        +-- 아니오 --> 저장 안 함
   |        |              409 { log_id, reason: judge_failed }  (BR-8.2)
   |        |              클라이언트가 수락하면 이 log_id를
   |        |              force_log_id로 재요청 --> 2번 경로
   |        |              --> status = failed                    (BR-8.3)
   |        +-- 예(프로브) --> status = failed --> 6번             (BR-8.5)
   |
   |-- 6. 트랜잭션                                          (BR-4.2)
   |     BEGIN
   |       SELECT last_seq FROM rooms WHERE id=? FOR UPDATE
   |       INSERT messages (seq = last_seq+1, status, ...)
   |       UPDATE rooms SET last_seq = last_seq+1
   |     COMMIT
   |
   |-- 7. judgment.link_message(log_id, message.id)  (로그가 있으면)
   |
   |-- 8. 커밋 후 브로드캐스트                              (BR-4.1)
   |     rooms.member_user_ids() → ws_registry.push_to_users()
   |
   +-- 9. 201 { message }
```

<!-- Text fallback: 전송은 참여자 자격과 토글을 한 번에 확인하고, force_log_id가 있으면 6중 검증 후 flagged_sent로 확정한다. 없으면 토글·degraded·콜드스타트 순으로 상태를 결정하고, 해당 없으면 트랜잭션 밖에서 문맥을 조회해 판정한다. 부적절이면 저장하지 않고 409를 반환한다. 그 외에는 트랜잭션 안에서 seq를 채번해 저장하고, 커밋 후 판정 로그를 메시지에 연결하고 브로드캐스트한 뒤 201을 반환한다. -->

**4번이 6번보다 앞이고 트랜잭션 밖인 것**이 이 흐름의 핵심이다. LLM 호출을 잠금 안에 넣으면 그 방의 모든 전송이 3~5초씩 막힌다.

**8번이 커밋 뒤인 것**이 FR-4.1의 전부다.

### 실패 응답 (5b)

판정 실패는 부적절 판정과 **다른 신호**여야 한다 — 클라이언트가 띄울 팝업이 다르기 때문이다.

| 상황 | 응답 | 클라이언트 |
|---|---|---|
| 부적절 판정 | `409` + `{ log_id, score, reason: "inappropriate" }` | `JudgeConfirmDialog` |
| 판정 실패 (degraded 아님) | `409` + `{ log_id, reason: "judge_failed" }` | `DegradedDialog` → 수락 시 그 `log_id`로 재요청 |
| 판정 실패 (프로브) | 저장 + `201` (status=`failed`) | 조용히 진행 |

**둘 다 409를 쓰되 `reason`으로 가른다.** 상태 코드를 나누면(예: 503) 클라이언트가 네트워크 오류와 헷갈린다 — 여기서 실패한 것은 판정이지 요청이 아니다.

프로브 실패는 팝업이 없으므로 그냥 저장하고 201을 준다 (BR-8.5).

**두 409가 같은 재요청 경로를 쓴다.** 부적절 판정이든 판정 실패든, 사용자가 "그래도 보내기"를 고르면 받은 `log_id`를 `force_log_id`로 실어 다시 보낸다. 서버는 그 로그의 `verdict`를 보고 상태를 정한다 — `inappropriate`면 `flagged_sent`, NULL(실패)이면 `failed`.

**이것이 FR-8.3의 "수락한 그 메시지는 `failed`"를 실제로 성립시키는 장치다.** `degraded` 플래그만 세워 재요청하면 BR-6.1의 우선순위에 걸려 `degraded`로 저장되어 버린다 — 시도한 사실이 사라진다. `force_log_id`가 "이 판정 시도는 이미 있었고 사용자가 결정했다"를 서버에 전달한다.

## 알고리즘: seq 채번

```sql
BEGIN;
  SELECT last_seq FROM rooms WHERE id = :room_id FOR UPDATE;
  -- 이 시점부터 그 방의 다른 전송은 대기한다. 다른 방은 영향 없음.

  INSERT INTO messages (room_id, sender_id, seq, body, verification_status)
  VALUES (:room_id, :me, :last_seq + 1, :body, :status);

  UPDATE rooms SET last_seq = last_seq + 1 WHERE id = :room_id;
COMMIT;
```

**`FOR UPDATE`가 행 잠금을 건다.** InnoDB의 행 잠금이라 같은 방만 직렬화되고 다른 방의 전송은 막지 않는다 — MariaDB를 고른 이유 중 하나다.

**`UNIQUE (room_id, seq)`가 최종 방어선이다.** 잠금이 어떤 이유로 안 걸려도 중복 seq가 들어가지 않는다.

트랜잭션 안에 **외부 호출이 하나도 없다.** 판정은 이미 끝났고, 브로드캐스트는 커밋 뒤다.

## W2 · 히스토리

```
GET /rooms/{id}/messages?before=<seq>&limit=50
   |
   |-- 1. get_membership() --> None이면 403                (BR-3.3)
   |
   |-- 2. SELECT * FROM messages
   |       WHERE room_id = ? AND (before IS NULL OR seq < ?)
   |       ORDER BY seq DESC
   |       LIMIT min(limit, 100)                           (BR-4.4)
   |
   |-- 3. friends.resolve_display_names(me, 발신자 id들)   [U3]
   |      → 한 번의 호출
   |
   +-- 4. 200 [ { message, sender_display_name } ]
```

<!-- Text fallback: 히스토리는 참여자 자격을 확인하고, before 커서보다 작은 seq를 내림차순으로 조회한 뒤, 발신자 표시명을 한 번의 호출로 해석해 반환한다. -->

**3번을 반복문 안에 두지 않는다.** 발신자 id를 모아 한 번에 해석한다.

`before`는 **경계를 포함하지 않는다** (`<`). 포함하면 페이지 경계에서 한 건이 중복된다.

## W3 · 신고

```
POST /messages/{id}/report      DELETE /messages/{id}/report
   |
   |-- SELECT messages WHERE id = ?
   |     +-- 없음 또는 sender_id != me --> 403             (BR-11.1)
   |
   |-- UPDATE messages
   |     SET misdirect_reported_at = NOW(6)  (또는 NULL)
   |
   +-- 200
```

<!-- Text fallback: 신고는 메시지를 조회해 발신자가 본인인지 확인하고, 아니면 403을 낸다. 통과하면 misdirect_reported_at을 현재 시각으로 설정하거나 NULL로 되돌린다. -->

**없는 메시지도 403이다** — 404를 주면 메시지 id의 존재 여부가 새어나간다.

`verification_status`를 보지 않는다 (BR-11.2). 어느 상태든 신고 가능하다.

## 프론트엔드

이 단위는 `ChatView`·`JudgeConfirmDialog`·`DegradedDialog`와 `chatStore`의 messages·degraded 슬라이스를 포함한다. `kind: service`라 `frontend-components.md`가 산출물에서 제외되어 여기에 적는다.

### 전송 상태 기계

```
[입력 중]
   |
   | Enter
   v
[전송 중] ── 전송 버튼 비활성화 + "확인 중..."           (FR-6.5)
   |
   +-- 201 --> [완료] 임시 메시지를 실제 ID·seq로 교체    (FR-4.3)
   |
   +-- 409 reason=inappropriate --> [확인 대기]
   |                                  |
   |                                  +-- 보내기 --> force_log_id로 재요청
   |                                  +-- 취소   --> PATCH judgments
   |                                                 입력창 텍스트 유지
   |
   +-- 409 reason=judge_failed --> [실패 확인 대기]
   |                                  |
   |                                  +-- 수락 --> force_log_id로 재요청
   |                                  |            → status=failed 로 저장
   |                                  |            그 다음 enterDegraded()
   |                                  |            (이후 전송부터 degraded)
   |                                  |
   |                                  +-- 거절 --> 입력 유지
   |                                               "다시 시도" 표시
   |
   +-- 네트워크 오류 --> [오류] 재시도 버튼
```

<!-- Text fallback: 전송은 입력 중에서 Enter로 전송 중이 되고 버튼이 비활성화되며 확인 중 표시가 뜬다. 201이면 완료되어 임시 메시지가 실제 것으로 교체된다. 409 inappropriate면 확인 팝업이 뜨고, 보내기는 force_log_id로 재요청하며 취소는 판정 로그만 갱신하고 입력창을 유지한다. 409 judge_failed면 실패 확인 팝업이 뜨고, 수락하면 같은 force_log_id로 재요청해 failed 상태로 저장한 뒤 degraded로 전환하며, 거절하면 입력을 유지하고 다시 시도 버튼을 보여준다. -->

**수락 시 `enterDegraded()`가 재요청 *뒤에* 온다.** 먼저 호출하면 재요청이 degraded 경로로 빠져 그 메시지가 `failed`가 아니라 `degraded`로 저장된다.

**"확인 중..." 표시가 필수다** (FR-6.5, NFR-2). 1~3초 무반응은 앱이 멈춘 것으로 읽힌다.

### degraded 상태 관리

```js
// chatStore — 메모리에만. localStorage/sessionStorage 금지 (FR-8.3)
degraded: false,
degradedSendCount: 0,          // 사용자 전역 카운터   (BR-8.5)

shouldProbe() {
  return this.degraded && this.degradedSendCount % 5 === 4
}

onSendWhileDegraded() {
  this.degradedSendCount += 1
}

enterDegraded() { this.degraded = true;  this.degradedSendCount = 0 }
exitDegraded()  { this.degraded = false; this.degradedSendCount = 0
                  toast("AI 검증이 다시 켜졌습니다") }
```

**카운터가 방 단위가 아니라 사용자 전역이다** (BR-8.5). degraded 자체가 모든 방에 적용되므로 카운터도 같은 범위여야 한다. 방 단위면 방을 옮길 때마다 리셋되어 프로브가 거의 안 돈다.

`% 5 === 4`는 0-index 기준 5번째다 — 0,1,2,3 전송 후 4번째 인덱스에서 프로브.

**새로고침하면 전부 사라진다.** 그것이 FR-8.3의 요구사항이다.

### `ChatView`

| 영역 | 내용 |
|---|---|
| 헤더 | 방 이름 + **AI 검증 토글** + 프라이버시 고지 (NFR-5) |
| 목록 | 메시지 + 발신자 표시명 + 미검증 배지 + 신고 표시 |
| 입력 | textarea + 전송 버튼 (+ "다시 시도" 조건부) |
| 비어 있음 | "첫 메시지를 보내보세요." + **콜드스타트 안내** |

**콜드스타트 안내가 중요하다** — 방에 메시지가 `N`개 미만이면 판정이 안 도는데(BR-6.2), 그걸 모르면 "AI 검증이 켜져 있는데 왜 아무 일도 안 일어나지"가 된다.

**프라이버시 고지** (NFR-5): 토글 옆에 "검증 시 최근 대화가 외부 AI로 전송됩니다"를 상시 표시하고, 누르면 최근 `N`개 본문만 전송되며 참여자 정보는 포함되지 않는다는 설명을 연다. **토글이 꺼져 있어도 보인다** — 켜기 전에 무슨 일이 일어나는지 알아야 결정할 수 있다.

### 확인 팝업 두 종

| 항목 | `JudgeConfirmDialog` | `DegradedDialog` |
|---|---|---|
| 문구 | "이 방에 맞지 않는 것 같습니다. 그래도 보낼까요?" | "검증 서버에 연결할 수 없습니다. 그래도 보내시겠습니까?" |
| 부제 | — | "서버가 정상화될 때까지 검증 없이 전송합니다" |
| 버튼 | 보내기 / 취소 | 보내기 / 취소 |
| 기본 포커스 | **취소** | **취소** |

두 팝업 모두:

| 요구 | 구현 |
|---|---|
| role | `alertdialog` — 응답을 요구하는 상황 |
| 포커스 트랩 | 열려 있는 동안 Tab이 밖으로 안 나간다 |
| Escape | 취소와 동일. 입력창 텍스트 유지 |
| 배경 클릭 | **닫지 않는다** — 실수로 흘려보내면 안 되는 결정 |
| 닫힐 때 | 포커스를 입력창으로 복귀 |
| 색 의존 금지 | 아이콘 또는 텍스트를 함께 |

**기본 포커스가 "취소"인 이유** — Enter를 반사적으로 누르는 사용자가 강행 전송하지 않게 한다. precision 우선 방침과 같은 방향이다.

### 미검증 배지

```
failed / degraded / skipped_no_context  →  "검증 안 됨" 배지
ok / flagged_sent / disabled            →  배지 없음
```

**스크롤해서 다시 봐도 남아 있어야 한다** (FR-8.6) — 메시지에 붙은 속성이지 일시적 알림이 아니다.

### 자동화 훅

`data-testid` — `chat-message-input`, `chat-send-button`, `chat-retry-button`, `chat-message-{id}`, `chat-unverified-badge-{id}`, `chat-report-{id}`, `judge-confirm-dialog`, `judge-confirm-send`, `judge-confirm-cancel`, `degraded-dialog`, `degraded-accept`, `degraded-reject`, `chat-privacy-notice`.

## 테스트 대상 (NFR-7)

이 단위가 지는 테스트 의무는 둘이다.

| 대상 | 무엇을 검증 |
|---|---|
| 동시 채번 (FR-4.2) | 같은 방에 동시 전송 시 seq가 중복 없이 연속하는가. 다른 방이 막히지 않는가 |
| degraded 상태 기계 (FR-8.3·8.5) | 첫 실패 팝업 → 수락 시 `failed` + degraded 전환 → 5번째 프로브 → 성공 시 복귀 |

**둘 다 산문으로 남으면 구현이 흔들리는 곳이다.** 동시 채번은 눈으로 검증할 수 없고, 상태 기계는 경로가 많아 손 테스트가 새다.

## Assumptions & Open Questions

- 실패 응답에 409 + `reason`을 쓰기로 한 것은 이 단계에서 정했다. `requirements.md`는 응답 형식을 규정하지 않았다.
- `shouldProbe()`의 `% 5 === 4` 구현은 "5번째마다"의 한 해석이다. degraded 진입 후 첫 메시지를 프로브로 볼지(`% 5 === 0`) 다섯 번째로 볼지 요구사항이 명시하지 않는다. 후자를 택했다 — 방금 실패한 API를 곧바로 다시 부르는 것은 의미가 적다.
- "다시 시도" 버튼의 반복 횟수 제한이 없다.
- 메시지 본문 길이 상한이 없다.
- 낙관적 렌더링 중 요청이 실패하면 임시 메시지를 어떻게 표시할지(빨간 표시 후 유지 / 제거) 정하지 않았다.

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

Confirmation pass, scoped to the changed sections: `judgment-core/business-rules.md` BR-6.9 and W4's neighborhood, `judgment-core/business-logic-model.md` W2, `messaging/business-rules.md` BR-6.4/BR-8.3, `messaging/business-logic-model.md` W1 step 2/5b + the failure-response table + the client state machine, `rooms-realtime/business-logic-model.md`'s new NFR-7 section, and `inception/application-design/component-methods.md`'s `SendOutcome` type. Traced the fix mechanically rather than trusting the changelog; it holds.

### Blocking finding — verified fixed

The original bug: on accept, `enterDegraded()` set `degraded=true` before the retry, and a retry sent as `{degraded: true}` re-entered `send_message()` at BR-6.1 step 3, where rule 2 ("degraded 이고 프로브 차례 아님 → degraded, 호출 안 함") silently reclassified the message as `degraded` instead of the `failed` FR-8.3 requires — and did so without ever consulting the log from the attempt that had actually failed.

The fix routes the accept path through step 2 instead of step 3. `judgment-core/business-rules.md` BR-6.9 now accepts `verdict IN ('inappropriate', NULL)` (still rejecting `'appropriate'`), and derives the resulting status from the log rather than from the client's `degraded` flag: `inappropriate → flagged_sent`, `NULL → failed`. `judgment-core/business-logic-model.md` W2's check list and text fallback match this exactly. `messaging/business-logic-model.md` W1 step 2 now shows `get_log_for_force(me, room_id, force_log_id, text)` deriving `status` from the log's verdict and routing straight to step 6 (the save transaction) — it never touches BR-6.1's degraded-skip branch at all. `messaging/business-rules.md` BR-8.3 states the mechanism and the reason explicitly ("`degraded` 플래그만 세워 재요청하면 BR-6.1 우선순위에 걸려 `degraded`로 저장되어 시도한 사실이 사라진다") and the client state machine now shows `enterDegraded()` firing *after* the force-retry completes, with the ordering hazard called out by name ("먼저 호출하면 재요청이 degraded 경로로 빠져 그 메시지가 `failed`가 아니라 `degraded`로 저장된다").

This closes the self-contradiction I flagged last round: `business-logic-model.md`'s own "테스트 대상 (NFR-7)" table commits to testing "첫 실패 팝업 → 수락 시 `failed` + degraded 전환" — that outcome is now actually reachable through the mechanism the same document describes, not just asserted by it.

### The two specific risks — checked, neither materializes

**Does reusing a `NULL`-verdict log via `force_log_id` bypass a judgment that would have succeeded on retry?** No. By the time the client ever sees `reason: judge_failed`, `judgment-core`'s BR-6.7 has already spent the call's full retry budget (1 internal retry, both attempts failed) — there is no unexercised "would have succeeded" attempt being skipped; that attempt already happened and already failed before the 409 was returned. `force_log_id` only ever replays the *exact* attempt that exhausted its budget, and only for that exact text (BR-6.9's `candidate_text` match still applies unconditionally to both verdict branches, and the single-use `user_action` guard is unchanged) — it can't be reused for a different message or reused twice. The path that performs a genuinely new, independent judgment attempt is unchanged and still exists: BR-8.4's reject → "다시 시도" → fresh `send_message()` call with `degraded=false`, which does re-enter BR-6.1 step 4 and call `judge()` again for real. Accept and reject remain correctly distinct: accept commits the exhausted attempt, reject asks for a new one.

**Does `user_action='sent'` on a failed log distort BR-7.3's precision calculation?** No. BR-7.3's population is `verdict = 'inappropriate' AND user_action IN ('sent','cancelled')` — a `NULL`-verdict log fails the `verdict='inappropriate'` predicate regardless of what `user_action` holds, so it structurally can't enter the TP/FP count. Checked this isn't a one-off exclusion: BR-7.2's aggregation base (`verdict IS NOT NULL`) already excludes every failed log from `judgment-core`'s entire metrics surface except one deliberately-carved-out exception — API 실패율, which explicitly uses "거르기 전의 전체 행" specifically to count failures, and counts on `verdict IS NULL` (unaffected by `user_action`). Nothing in the fix mutates `score` or `verdict`; it only ever sets `user_action` on a row that already has `verdict=NULL`, which every metric definition already treats as out-of-population by construction. No distortion anywhere in W4.

### Should-fix items — both verified closed

1. **`SendOutcome`.** `component-methods.md` now declares the three-arm union shown above (`sent` / `blocked+inappropriate+score` / `blocked+judge_failed`, no `score` on the latter), with prose stating `reason` is the discriminant and both blocked arms retry via the same `forceLogId`. Matches the wire shapes in `messaging/business-logic-model.md`'s failure-response table exactly.
2. **`rooms-realtime` NFR-7 gap.** `rooms-realtime/business-logic-model.md` now has a "## 테스트 대상 (NFR-7)" section naming the subscribe/fetch-ordering + dedup test and explicitly noting the history API itself belongs to U5 — symmetric with `messaging`'s existing section.

### One residual, not blocking

`component-methods.md`'s **backend** `send_message()` prose (the Python-signature section, separate from the `SendOutcome` type just fixed) still describes the pre-fix behavior — "네 가지를 검증한 뒤에만... `flagged_sent`로 진행," no mention of the `NULL`-verdict/`failed` branch. Nobody building from the functional-design artifacts under review would be misled by this, since `judgment-core` and `messaging`'s own docs are the correct and complete source now — but it's worth a one-line sync in `component-methods.md` at some point so that file doesn't read as contradicting its own sibling `SendOutcome` type. Not a Code Generation blocker.

### Not addressed this round — carried forward as recorded refinements, unchanged from last pass

BR-ID collisions across sibling units' `business-rules.md` files (`BR-3.3`, `BR-6.1`, `BR-6.2` each defined independently in both `rooms-realtime` and `messaging`, directory-scoped by convention so not a broken reference); unstated context-ordering direction into `judge()` in `messaging` W1 step 4 vs. `judgment-core` BR-6.1's seq-ascending requirement; the `shouldProbe()` → `degraded` call-site wiring never spelled out as an explicit line; the stale `last_seq`-read justification in `rooms-realtime/domain-entities.md` (its own W2 query never actually reads `rooms.last_seq`); and the check-order mismatch between `judgment-core`'s two `force_log_id` listings (behaviorally inert — both branches return the same error code). None of these misdirect an implementer badly enough to block on.

### Summary

The blocking bug is genuinely fixed, not just asserted-fixed — traced the mechanism end to end and it produces `failed` exactly where FR-8.3 requires it, via a route that never touches the branch that caused the original bug. Both should-fix items are closed and consistent with the artifacts that drove them. The two adversarial questions this round posed both check out: no new bypass, no metric distortion. Ready for Code Generation.

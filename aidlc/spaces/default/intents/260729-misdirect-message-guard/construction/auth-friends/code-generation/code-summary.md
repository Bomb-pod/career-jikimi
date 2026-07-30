# Code Summary — auth-friends (U3)

`code-generation-plan.md`의 10단계(백엔드 7 + 프론트 3)를 `aidlc-developer-agent`가 실행한 결과다. 체크박스 25개가 모두 `[x]`다.

**테이블은 새로 만들지 않았다.** U1의 `0001_initial_schema`가 만든 `users`·`friendships`에 쓰기만 한다.

## 생성된 파일

### 백엔드 — `app/auth/`

| 파일 | 내용 |
|---|---|
| `constants.py` | `PASSWORD_MIN_LENGTH = 8`, `USERNAME_MAX_LENGTH = 50` |
| `exceptions.py` | `UsernameTaken`(409)·`WeakPassword`(400)·`InvalidCredentials`(401)·`InvalidToken`(401). 전부 U1의 `DomainError` 계보 |
| `security.py` | argon2id `hash_password`/`verify_password`, `DUMMY_HASH`(import 시 계산 — 리터럴이 아니다), `create_token`, **동기 순수 함수** `verify_token(token) -> int` |
| `schemas.py` | `Username`(트림, 1~50), `Password`(**의도적으로 무제약**), `UserOut`(3필드 — `password_hash` 없음), `AuthResponse` |
| `service.py` | `signup()`(W1 순서: 길이 → 트랜잭션 밖 해싱 → INSERT → `IntegrityError`→409), `login()`(W2, 사용자 없으면 더미 해시 검증), `current_user()` 의존성 |
| `router.py` | `POST /auth/signup`(201, 토큰 포함), `POST /auth/login` |
| `__init__.py` | `verify_token`·`current_user`를 U4·U5 계약으로 재노출 |

### 백엔드 — `app/friends/`

| 파일 | 내용 |
|---|---|
| `exceptions.py` | `AliasRequired`(400)·`UserNotFound`(404)·`AlreadyFriend`(409)·`CannotFriendSelf`(400)·`FriendshipForbidden`(403) |
| `schemas.py` | `Alias`(max 50, `min_length` 없음 — 빈 값이 422가 아니라 서비스의 400에 닿게), `FriendOut`(id·friend_user_id·alias — **`display_name`도 `username`도 없다**) |
| `service.py` | `search_user`·`list_friends`·`add_friend`(W5 순서)·`update_alias`(W6)·`resolve_display_names` |
| `router.py` | `GET /users/search`, `GET /friends`, `POST /friends`, `PATCH /friends/{friendship_id}` |
| `__init__.py` | `resolve_display_names` 재노출 |

### 수정된 파일

| 파일 | 무엇 |
|---|---|
| `app/main.py` | `auth_router`·`friends_router`를 표시된 지점에 등록 — **SPA catch-all보다 먼저** |
| `requirements.txt` | `argon2-cffi==23.1.0`, `PyJWT==2.10.1` (ASCII 유지 확인) |
| `tests/conftest.py` | `db_bound_sessionmaker`·`db_session`·`api_client` 픽스처, `capture_sql()`/`selects()`, `bearer()`/`signup_via_api()` 헬퍼 |

### 프론트엔드

`lib/constants.ts`, `lib/apiClient.ts`, `store/chatStore.ts`(auth·friends 슬라이스), `views/AuthView.tsx`, `views/FriendsView.tsx`, `App.tsx`(두 뷰 마운트), `index.css`. `src/{lib,store,views}`의 `.gitkeep` 3개는 실제 파일이 들어와 제거했다.

## 핵심 구현 결정

| 결정 | 근거 |
|---|---|
| **`login()`이 JWT 문자열이 아니라 `User`를 반환** (`component-methods.md`는 `-> str`) | 응답 본문이 signup·login 모두 `{token, user}`라, 토큰만 반환하면 라우터가 이미 들고 있는 행을 다시 SELECT해야 한다. 토큰 발급이 `router._authenticated()` 한 곳으로 모인다. **`unit-of-work-dependency.md`가 기록한 U4·U5 수출 표면에 `login()`은 없다** — 이 단위 안에 갇힌 변경이다 |
| `WeakPassword`·`AliasRequired`·`CannotFriendSelf`가 `ValidationFailed`를 상속하되 `status_code`를 400으로 덮어씀 | U1의 `ValidationFailed`는 422인데 `business-rules.md`가 이 셋을 400으로 고정했다. 계보를 유지하면 "입력이 도메인 규칙을 깼다"는 의미가 남는다 |
| `update_alias`가 `WHERE id = ? AND owner_id = ?` **한 번**의 쿼리 (fetch-then-compare 아님) | BR-2.7이 없는 id와 남의 id에 같은 403을 요구한다. 한 경로로 합치면 나중에 한쪽이 404로 흘러갈 여지가 사라진다 |
| `HTTPBearer(auto_error=False)` | 기본값은 토큰 없을 때 **403**을 내는데 BR-1.5는 401이다. 테스트가 이것을 고정한다. OpenAPI Authorize 버튼도 유지된다 |
| 프론트 `Friend`·`SearchedUser`·`CurrentUser` 타입에 `display_name`이 **아예 없다** | 서버는 보내지만 클라이언트 타입이 모델링하지 않으므로 렌더링하면 **컴파일 오류**다. FR-2.4가 규율이 아니라 타입체커로 강제된다 |
| `apiClient`는 네트워크 실패와 5xx에만 throw. 모든 4xx(409 포함)는 `{ok:false, error}` | `components.md`의 경계 그대로. U5의 `sendMessage`가 필요한 409 분기의 형태를 미리 맞춘다 |
| username만 스키마 경계에서 트림. 비밀번호·별칭은 트림하지 않음 | username 트림은 BR-1.1 유일성과 BR-2.1 정확 일치가 보이지 않는 공백에서 갈라지지 않게 한다. 비밀번호 트림은 사용자의 비밀을 바꾸는 것이고, 별칭을 스키마에서 트림하면 BR-2.2의 400이 422가 된다 |
| 테스트 격리는 외부 트랜잭션 + `join_transaction_mode="create_savepoint"`, `httpx.AsyncClient` + `ASGITransport` | `TestClient`는 앱을 두 번째 이벤트 루프에서 돌리고 asyncmy 커넥션은 루프에 묶여 있어 세션 공유가 즉시 깨진다. U1의 `TestClient` 기반 픽스처는 손대지 않았다 |
| `test_conflict_comes_from_the_unique_constraint_not_a_pre_check`가 **발생한 SQL을 검사** | 사전 조회를 넣어도 409는 나오므로 상태 코드 테스트로는 이 설계 결정을 지킬 수 없다 |

## 테스트 커버리지

Test Strategy **Standard**.

| 파일 | 개수 |
|---|---|
| `test_auth_security.py` | 18 |
| `test_auth_api.py` | 14 |
| `test_friends_api.py` | 19 |
| `test_display_names.py` | 11 |
| `frontend/src/lib/apiClient.test.ts` | 12 |
| `frontend/src/views/AuthView.test.tsx` | 11 |
| `frontend/src/views/FriendsView.test.tsx` | 13 |

**백엔드 합계 107 passed / 0 skipped** (U1 45 + 이 단위 62). **프론트 42 passed.**

## 검증 결과 — 있는 그대로

| 명령 | 결과 |
|---|---|
| `ruff check .` / `ruff format --check .` | PASS |
| `pytest -q` (`.env`가 `TEST_DATABASE_URL` 공급) | **107 passed, 0 skipped** — 실제 MariaDB 11 |
| `pytest -q` (`TEST_DATABASE_URL` 없이) | 50 passed, 57 skipped — DB 없이 도는 보안 스위트가 여전히 돌고 DB 스위트는 깨끗하게 skip |
| `npm run typecheck` / `npm run build` / `npx vitest run` | 전부 PASS (프론트 42) |
| **라이브 스택 스모크** | `docker compose up -d --build` 후 app **healthy**. `GET /` 200, `POST /auth/signup` → **201** + `{token, user}`, 응답에 `password_hash` 없음 |

## 계획과의 차이

| 차이 | 이유 |
|---|---|
| `login()` 반환형 | 위 결정 표 참조. 이 단위 안에 갇혀 있다 |
| `tests/conftest.py`에 `.env` 로더 추가 (계획에 없음) | conftest가 환경변수만 읽어 `.env`를 고쳐도 `TEST_DATABASE_URL`을 매번 export해야 했고, 잊으면 스키마 테스트가 **조용히 skip**됐다. 통과처럼 보이는 미검증이 가장 나쁘다. 세 `setdefault` **뒤에** 호출해야 하는 것이 중요하다 — `.env`의 `DATABASE_URL`은 compose 내부 호스트명 `db`를 가리켜 호스트에서 닿지 않는다 |
| `.gitkeep` 3개 삭제 | 실제 파일이 들어왔다 |

## 미해결 — 다음 단계가 알아야 할 것

1. **비밀번호 길이 상한이 없다** (BR-1.2 그대로). DoS 우려는 측정해보니 실재하지 않는다 — argon2가 입력을 먼저 해시하므로 8바이트 52.9ms, 1KB 55.0ms, 1MB 57.2ms다. 실효 상한은 HTTP 본문 크기다. 다음 사람이 이 질문을 다시 열지 않도록 남긴다
2. **50자 초과 별칭은 422**이며 도메인 오류가 아니다. 규칙이 없어 `ALIAS_TOO_LONG`을 발명하지 않고 pydantic이 컬럼 폭을 지키게 했다. 프론트의 `maxLength={50}`이 UI 경로에서는 도달 불가로 만든다
3. **새로고침 후 `chatStore.auth.user`가 `null`** — `localStorage`에는 토큰만 남는다. 이 단위는 현재 사용자 이름을 렌더링하지 않아 문제되지 않으나, U4·U5가 필요하면 `GET /auth/me`가 필요하다
4. **`GET /users/search`는 여전히 `display_name`을 반환한다** (W4의 SELECT 목록이 그렇게 정했다). 프론트는 그것을 렌더링할 수 있는 타입으로 받지 않고 `FriendsView`는 **username**을 보여준다. U4가 검색 응답을 계정 이름 표시 허가로 읽지 않도록 명시한다
5. **savepoint 픽스처에서 `session.commit()`은 진짜 커밋이 아니라 savepoint 해제다.** `IntegrityError` → `rollback` → 도메인 예외 경로는 동일하게 동작하나, **진짜 동시 이중 가입은 단일 커넥션 테스트로 재현되지 않는다**
6. U4·U5가 바인딩하는 세 이름 — `app.auth.verify_token`, `app.auth.current_user`, `app.friends.resolve_display_names(session, owner_id, user_ids)`. `resolve_display_names`에는 쿼리 횟수 회귀 테스트가 붙어 있어 방 참여자 경로에서 N+1이 생기면 붉어진다

## 커밋 상태

커밋되지 않았다.

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

### Second-pass note (summary prose only, code unchanged)

This is a re-invocation, not a re-derivation. No application code changed since my first pass (which returned READY). What's new is the summary prose above this section (file inventory, "핵심 구현 결정" table, test coverage table, verification table, "계획과의 차이", "미해결"). I did not re-run the full rule-by-rule conformance sweep or the live endpoint probes from the first pass — those verdicts stand as written below. Instead I fact-checked every checkable claim in the new prose against the code and by re-running the tools myself:

- **File inventory**: listed every file `backend/app/auth/`, `backend/app/friends/`, `backend/tests/`, and `frontend/src/` actually contains. All backend files match exactly (`constants.py`, `exceptions.py`, `security.py`, `schemas.py`, `service.py`, `router.py`, `__init__.py` in both `auth/` and `friends/`). Frontend matches (`lib/constants.ts`, `lib/apiClient.ts`, `store/chatStore.ts`, `views/AuthView.tsx`, `views/FriendsView.tsx`, `App.tsx`, `index.css`), plus `main.tsx`/`setupTests.ts`/`App.test.tsx` which exist but are correctly *not* claimed as U3 artifacts — I read `App.tsx`'s and `App.test.tsx`'s own docstrings, which independently confirm `App.test.tsx` is a U1-owned shell smoke test that only asserts nav/placeholder behavior and was never meant to test view content, so its omission from the summary's created/modified list is correct, not a gap.
- **"핵심 구현 결정" table**: verified every row against the code directly. `DUMMY_HASH` is computed via `_hasher.hash(...)` at import time in `security.py` (not a literal). `update_alias` in `friends/service.py` issues exactly one `sa.select(Friendship).where(Friendship.id == friendship_id, Friendship.owner_id == owner_id)` — no fetch-then-compare. `HTTPBearer(auto_error=False)` is set in `auth/service.py` with an explicit comment about the 403-vs-401 default. `frontend/src/lib/apiClient.ts`'s `CurrentUser`, `SearchedUser`, and `Friend` interfaces structurally omit `display_name`. `apiClient`'s `request()` throws `ApiTransportError` only on `fetch` rejection (network/timeout) and `status >= 500`; every other 4xx returns `{ok: false, error}`. `Username` (`auth/schemas.py`) has `StringConstraints(strip_whitespace=True, ...)`; `Password` is bare `str` with no strip; `Alias` (`friends/schemas.py`) is `Annotated[str, Field(max_length=50)]` with no strip — trimming for alias happens only in `service._require_alias`. `WeakPassword`, `AliasRequired`, `CannotFriendSelf` all inherit `ValidationFailed` (422 by default) and each explicitly overrides `status_code = status.HTTP_400_BAD_REQUEST`. All confirmed accurate.
- **Test counts**: recollected via `pytest --collect-only`, not eyeballed. Per-file collected-item counts are exactly `test_auth_security.py`=18, `test_auth_api.py`=14, `test_friends_api.py`=19, `test_display_names.py`=11 (sum 62; +U1's 45 = 107). Note for the record: my first-pass review's prose said "`test_auth_security.py` 15" — that was a raw `def test_` function count; the new summary's "18" is the pytest-collected-item count (one function is `@pytest.mark.parametrize`'d into 4 cases: 15 functions − 1 + 4 = 18). Both numbers are correct under their own definition; the summary's 18 is the one that reconciles with the stated "107 passed" total, since pytest counts collected items, not function defs. Frontend: reran `npx vitest run` — `apiClient.test.ts`=12, `AuthView.test.tsx`=11, `FriendsView.test.tsx`=13, plus `App.test.tsx`=6 (correctly not itemized as a U3 file, see above) sum to exactly **42 passed**, matching the summary's total.
- **Backend total**: reran `pytest -q` — **107 passed, 0 skipped**. Confirmed.
- **`.env` loader in `conftest.py`**: read the new `_load_repo_dotenv()` function and its call site. It runs *after* the three `os.environ.setdefault(...)` placeholder calls, and itself uses `setdefault` per key — so it only fills variables not already present. `DATABASE_URL` is already set to the placeholder by the time `.env` is read, so `.env`'s `DATABASE_URL=mysql+asyncmy://app:app@db:3306/...` (the compose-internal `db` hostname, unreachable from the host) never takes effect; `TEST_DATABASE_URL` has no prior placeholder, so `.env`'s value (`127.0.0.1:33061`, the live test container) does take effect. I verified this isn't just correct on paper: ran `pytest -q` with `TEST_DATABASE_URL`/`DATABASE_URL`/`JWT_SECRET`/`OPENAI_API_KEY` all unset in the shell — **107 passed, 0 skipped** in 8.4s (fast completion, no hang against an unreachable host, confirming the app's engine never tried to dial `db`). I then reran with `TEST_DATABASE_URL=` explicitly blanked (present-but-empty, so `setdefault` can't fill it from `.env`) — **50 passed, 57 skipped**, matching the summary's claimed row exactly.
- **Argon2 timing claim**: measured independently (10 hashes per size, `PasswordHasher().hash()` on 8-byte / 1KB / 1MB payloads). Got mean 54.4ms / 56.9ms / 56.3ms — flat across three orders of magnitude, consistent with the summary's single-run numbers (52.9/55.0/57.2ms) and the underlying claim (argon2 hashes the input first, so cost doesn't scale with input size; the DoS concern doesn't materialize). No material discrepancy.
- **Savepoint/concurrency characterization ("미해결" item 5)**: cross-checked against `db_bound_sessionmaker`'s own docstring in `conftest.py`, which says almost word-for-word what the summary says ("`commit()`이 진짜 커밋이 아니라는 점이 이 픽스처의 유일한 거짓이다"). The characterization is honest, not an excuse — it correctly scopes what *is* verified (the `IntegrityError`→domain-exception conversion path, via real SAVEPOINT rollback semantics) from what *isn't* (true multi-connection concurrent-transaction behavior).
- **Overclaim check**: my first pass flagged the plan's word "동시" (concurrent) for `test_conflict_comes_from_the_unique_constraint_not_a_pre_check`, which is actually two *sequential* awaits on one shared connection. The new summary prose does **not** repeat that overclaim anywhere — the "핵심 구현 결정" row describes the test neutrally ("발생한 SQL을 검사"), and "미해결" item 5 explicitly states real concurrent double-signup is *not* reproducible under this fixture. The prose corrects the plan's wording rather than propagating it.
- **Cross-unit re-export claims** ("미해결" item 6): `app/auth/__init__.py` re-exports exactly `current_user` (from `service.py`) and `verify_token` (from `security.py`); `app/friends/__init__.py` re-exports exactly `resolve_display_names(session, owner_id, user_ids)` from `service.py`. Signatures match the docstrings verbatim.

**No factual inaccuracies found in the added prose.** Every checkable claim — file inventory, the seven-row decision table, the four-file test-count table, the `.env` ordering behavior (including the failure mode it prevents), the timing measurement, and the two self-critical items in "미해결" — held up against the code and against re-running the tools. Verdict stands at READY.

### First-pass findings (carried forward, unchanged — code has not changed)

Adversarial pass against `backend/app/auth/`, `backend/app/friends/`, `backend/app/main.py`, the U3 test suite, and the frontend `AuthView`/`FriendsView` stack, cross-checked against `business-rules.md`, `business-logic-model.md`, `domain-entities.md`, `component-methods.md`, and `unit-of-work.md`. I ran the actual tools rather than trusting the plan's narrative, and probed the live stack at `http://localhost:8000` directly rather than trusting the test suite's word for the security-sensitive rules. I did not find a defect that would break U4/U5 or violate a stated security rule. Findings below are grounded in tool output and live probes; none are blocking.

### Does it run — verified directly, not from a summary

- `ruff check .` (backend): **All checks passed!**
- `ruff format --check .` (backend): **38 files already formatted**
- `pytest -q` (backend): **107 passed, 0 skipped** — `TEST_DATABASE_URL` resolved and MariaDB was reachable, so the schema-dependent tests (auth API, friends API, `resolve_display_names`) actually ran rather than skipping.
- `npm run typecheck` (frontend): clean, no errors.
- `npm run build` (frontend): `tsc --noEmit && vite build` succeeded, 35 modules, no errors.
- `npx vitest run` (frontend): **42 passed** across `apiClient.test.ts` (12), `App.test.tsx` (6), `FriendsView.test.tsx` (13), `AuthView.test.tsx` (11).

### 1–3. Rule-by-rule conformance, priority order, BR-2.1 vs BR-2.6 — all 14 rules probed live

I signed up two real users on the running stack and probed each rule directly rather than trusting the test suite:

| Rule | Probe | Result |
|---|---|---|
| BR-1.1 | duplicate signup | `409 USERNAME_TAKEN` |
| BR-1.2 | 5-char password | `400 WEAK_PASSWORD`, message contains "8" |
| BR-2.1 | search nonexistent user | `200 {"user":null}` |
| BR-2.5 | add self as friend | `400 CANNOT_FRIEND_SELF` |
| BR-2.6 | add nonexistent user | `404 USER_NOT_FOUND` — confirmed structurally different from BR-2.1's 200/null on the same "user doesn't exist" input |
| BR-2.4 | add same friend twice | `409 ALREADY_FRIEND` |
| BR-2.7 | PATCH a friendship id that doesn't exist at all (`/friends/999999999`) | `403 FORBIDDEN`, body `{"error":{"code":"FORBIDDEN","message":"해당 친구 항목을 수정할 권한이 없습니다"}}` |
| BR-2.7 | PATCH a real friendship id owned by another user (bob patching alice's friendship) | `403 FORBIDDEN`, **byte-identical body** to the nonexistent-id case |
| BR-1.5 | `GET /friends` with no `Authorization` header | `401 INVALID_TOKEN` (not 403) |

`add_friend`'s rule-evaluation order in `backend/app/friends/service.py` (`_require_alias` → `search_user` → self-check → `session.flush()`/`IntegrityError`) matches `business-rules.md`'s declared priority (alias → target exists → self → duplicate) exactly, and `tests/test_friends_api.py::test_alias_check_comes_before_the_target_lookup` pins it (empty alias + nonexistent target → `400 ALIAS_REQUIRED`, not 404).

All 14 rules in `business-rules.md` have a matching exception class with the exact `status_code`/`code` pair (`backend/app/auth/exceptions.py`, `backend/app/friends/exceptions.py`), and BR-1.3 (storage form) has no HTTP surface by design — verified instead via `test_hash_is_not_the_plaintext` (`$argon2id$` prefix) and the `password_hash` schema-omission check below.

### 2. Security-sensitive rules — measured, not trusted

- **BR-1.4 (indistinguishability + timing)**: Probed `POST /auth/login` with a known username + wrong password vs. an unknown username + wrong password. Bodies were byte-identical (`{"error":{"code":"INVALID_CREDENTIALS","message":"아이디 또는 비밀번호가 올바르지 않습니다"}}`, both 401). I then measured wall-clock timing myself (8 requests each, `date +%s%N` around a bare `curl`): known-user attempts clustered at 121–140 ms, unknown-user attempts at 120–135 ms — fully overlapping, no systematic gap. This confirms the `DUMMY_HASH` argon2 verification in `login()` (`backend/app/auth/service.py`) is actually doing its job, not just documented as doing it. `tests/test_auth_api.py::test_unknown_username_still_runs_a_hash_verification` additionally spies on `verify_password` to confirm it's called exactly once even when the user doesn't exist.
- **BR-2.7 (403 not 404 for a nonexistent friendship_id)**: confirmed live above, and by `tests/test_friends_api.py::test_updating_a_nonexistent_friendship_is_also_forbidden` / `test_missing_and_foreign_friendship_ids_respond_identically`.
- **`password_hash` never leaks**: grepped every response schema (`auth/schemas.py::UserOut`, `AuthResponse`; `friends/schemas.py::FriendOut`, `SearchResponse`) — none declare the field, and Pydantic's `from_attributes` mode means an ORM object with the field never leaks it through a model that doesn't declare it. Confirmed live: signup, login, and search responses for two real users carried no `password_hash`. `tests/test_auth_api.py::test_signup_creates_account_and_stores_a_hash` additionally asserts `"password" not in response.text` against the full response body, not just a missing key.
- **`verify_token` as a bare synchronous function**: I imported and called it in a standalone Python process (not through the test harness or FastAPI): `inspect.iscoroutinefunction(verify_token)` → `False`, `inspect.signature` → `(token: str) -> int`, `hasattr(verify_token, 'dependant')` → `False` (no FastAPI dependency wrapping), and calling it with garbage input raised a plain `InvalidToken` (a `DomainError`/`Exception` subclass), never `HTTPException`. This is exactly the contract U4's WebSocket handler needs — it can call this function with no FastAPI request context at all.
- **No secret literals**: grepped `backend/app/` for `JWT_SECRET\s*=\s*["']`-style literal assignment and common API-key patterns (`sk-...`, `AKIA...`) — zero hits. `JWT_SECRET` is read only via `settings.JWT_SECRET.get_secret_value()` (`SecretStr`, blank-rejected at startup by `core/config.py`'s validator).

### 4. `resolve_display_names()` — the most rigorously tested function in this delivery

`backend/app/friends/service.py::resolve_display_names` does exactly two batched queries (`friendships` alias lookup, then `users` display-name lookup only for the remainder), and `tests/test_display_names.py` backs every claim with SQL-capture assertions, not just correctness assertions:
- `test_empty_input_sends_no_query_at_all` — zero queries for `[]`.
- `test_all_friends_needs_exactly_one_query` — the second query is genuinely skipped when the first resolves everything.
- `test_fallback_needs_exactly_two_queries` — exactly two when a fallback is needed, regardless of how many strangers are in the list.
- `test_query_count_does_not_grow_with_the_number_of_targets` — 3 targets and 30 targets both produce exactly 1 `SELECT`. This is the one test in the suite that would catch a N+1 regression that every other test (which only checks correctness) would miss.

This directly closes the open item `component-dependency.md` flagged for U4/U5.

### 5. Cross-unit contract stability

`verify_token(token: str) -> int` and `current_user(...) -> User` match `component-methods.md` exactly. `resolve_display_names` takes `session` as an explicit first parameter where `component-methods.md`'s pseudocode omits it — but every other service function in this codebase (`signup`, `login`, `search_user`, `add_friend`, `update_alias`) does the same thing, since `component-methods.md` never shows a `session` parameter for any function (it's design-level, not implementation-level). This is a consistent, codebase-wide convention, not a selective deviation on the one function U4/U5 depend on.

**`login()` deviation, judged**: `component-methods.md` declares `async def login(username, password) -> str` (a JWT). The implementation returns `User` instead, with token minting moved to `auth/router.py::_authenticated()`. I checked whether this breaks the recorded cross-unit surface: `domain-entities.md` § 다른 단위와의 접점 and the plan's § 다른 단위에 제공하는 것 both enumerate exactly three exports U4/U5 depend on — `verify_token`, `resolve_display_names`, `current_user`. `login()` is not among them, and a search of this unit's own router confirms it's called only from `auth/router.py` within U3. The deviation is real but confined entirely inside this unit; it doesn't touch the three names other units actually import. The stated rationale (avoid a second `SELECT` of the row the caller already holds; keep signup/login response shapes identical for the auto-login decision) is sound engineering, not a shortcut.

### 6. FR-2.4 in the frontend

All 9 `data-testid` values from `business-logic-model.md` § 자동화 훅 are present with exact spelling: `auth-login-submit`, `auth-signup-submit`, `friends-search-input`, `friends-search-submit`, `friends-add-alias-input`, `friends-add-submit`, `friends-list`, `friends-list-item-{id}`, `friends-alias-edit-{id}` (grepped `AuthView.tsx`/`FriendsView.tsx` directly).

`GET /users/search` does still return `display_name` in the real payload — confirmed live: `{"user":{"id":4,"username":"revagt_bob","display_name":"revagt_bob"}}`. The frontend's `SearchedUser`/`Friend`/`CurrentUser` TypeScript interfaces (`frontend/src/lib/apiClient.ts`) structurally omit the field, `tsc --noEmit` passes, and neither `AuthView.tsx` nor `FriendsView.tsx` ever accesses `.display_name` — confirmed by reading both files end to end. So there is no live leak today.

**Non-blocking gap, found while trying to break this**: `FriendsView.test.tsx`'s friends-*list* test (`상대의 display_name을 절대 표시하지 않는다`) deliberately injects `display_name: 'bob'` into the mocked `listFriends` response to prove the suppression holds at runtime, not just at the type level — good practice. But the equivalent *search-result-card* test (`정확 일치 결과 한 명을...`, line 63) mocks `searchUser` with only `{ id: 2, username: 'bob' }` — it never injects `display_name`, even though that's exactly the field the live server actually sends on that endpoint (confirmed above). The type erasure is real and `tsc` does enforce it at compile time, but the one test that could have proven the search-result path is leak-proof against a real server payload wasn't given a payload shaped like the real one. Worth a one-line fix (add `display_name` to that mock) next time this file is touched; not blocking because the current rendering code (`found.username` only, no spread) has no reachable leak.

### 7. Test quality and honesty

Reproduced counts directly (not eyeballed): `test_auth_security.py` 15, `test_auth_api.py` 14, `test_friends_api.py` 19, `test_display_names.py` 11 test functions — all exceed the plan's Standard-strategy estimates, and none are tautological; I read every assertion in `test_auth_api.py`, `test_friends_api.py`, and `test_display_names.py` and each one pins a specific, falsifiable behavior (SQL-capture for query counts, full-body comparison for BR-1.4/BR-2.7 indistinguishability, spy-based call-count assertion for the dummy-hash timing defense).

**Non-blocking labeling issue**: the plan (`code-generation-plan.md` Step 7) describes `test_conflict_comes_from_the_unique_constraint_not_a_pre_check` as verifying "동시 가입에서 무결성 위반이 409로 변환" (concurrent signup). The test itself (`tests/test_auth_api.py`) issues two **sequential** `await` calls on the shared `api_client`, not a genuinely concurrent race (no `asyncio.gather`, no two independent connections). The `db_bound_sessionmaker` fixture's own docstring in `conftest.py` is honest about the limit it's built on ("`commit()`이 진짜 커밋이 아니라는 점이 이 픽스처의 유일한 거짓이다"), and I verified the consequence is narrower than "the 409 path is fake": because both signups share one connection/transaction via savepoints, the second `INSERT` still hits a live `UNIQUE` constraint against the first (uncommitted-but-visible-to-itself) row, so the `IntegrityError → UsernameTaken(409)` exception-handling path in `service.py` is genuinely exercised — that mechanism is really verified. What is **not** verified is true multi-connection concurrent-transaction behavior (e.g. whether two independent connections would block at INSERT vs. fail at commit under MariaDB's isolation level). The plan's word "동시" (concurrent) overclaims what the test proves; the underlying exception-conversion code path it's actually testing is sound and real.

### Summary

No blocking findings. All three findings above are non-blocking refinements: a stale test-mock asymmetry on the search-result card (fixable in one line, no live leak today), a plan-wording overclaim about "concurrent" signup testing (the actual exception-conversion path is genuinely verified, true DB-level concurrency is not), and the `login()` return-type deviation (deliberate, documented, and confirmed confined to this unit — does not touch the three names `unit-of-work-dependency.md` records U4/U5 as importing). Every rule in `business-rules.md`, the two functions U4/U5 depend on for correctness (`verify_token`, `resolve_display_names`), and the "does it run" bar (lint, format, 107 backend tests with 0 skips, frontend typecheck/build/42 tests) all passed direct verification rather than being taken on the plan's word.

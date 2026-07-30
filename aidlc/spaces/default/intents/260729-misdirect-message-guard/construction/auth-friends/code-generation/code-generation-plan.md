# Code Generation Plan — auth-friends (U3)

`../functional-design/`의 세 문서가 이 계획의 권위다. `business-logic-model.md`가 워크플로 6개와 표시명 해석 알고리즘을, `business-rules.md`가 규칙 14개와 각 규칙의 응답 코드를, `domain-entities.md`가 `users`·`friendships`의 불변식을 정한다.

| 무엇 | 어디 |
|---|---|
| 워크플로 W1~W6, 표시명 해석, 프론트 명세 | `../functional-design/business-logic-model.md` |
| 규칙 BR-1.1~BR-1.6, BR-2.1~BR-2.8, 우선순위 | `../functional-design/business-rules.md` |
| `users`·`friendships` 불변식 | `../functional-design/domain-entities.md` |
| 대응 요구사항 | `../../../inception/requirements-analysis/requirements.md` — FR-1.1~FR-1.3, FR-2.1~FR-2.4 |
| 단위 경계 | `../../../inception/units-generation/unit-of-work.md` § U3 |
| 메서드 서명 | `../../../inception/application-design/component-methods.md` |

**테이블은 이미 있다.** U1의 `0001_initial_schema`가 `users`·`friendships`를 만들었고 모델도 `backend/app/models/`에 있다. 이 단위는 **쓰기만** 한다 — 마이그레이션을 새로 만들지 않는다.

**구현 순서는 백엔드 먼저, 그 위에 프론트다** (`code-generation-questions.md` Q1의 답). Step 1~7이 백엔드, Step 8~10이 프론트다.

---

## U1이 남긴 계약 — 그대로 쓴다

| 이름 | 어디서 | 주의 |
|---|---|---|
| `settings` | `app.core.config` | `JWT_SECRET`이 **`SecretStr`** 이다. `.get_secret_value()`를 써야 한다 |
| `get_session()` | `app.core.db` | 핸들러 성공 시 **자동 커밋**한다. 이 단위는 명시적 커밋이 필요 없다 |
| `Base` | `app.core.db` | 모델이 이미 이것을 쓴다 |
| `DomainError` 계열 + `register_error_handlers()` | `app.core.errors` | 이 단위의 도메인 예외를 여기에 등록한다 |

`app/main.py`에 U2~U5 라우터 등록 지점이 주석으로 표시되어 있고, **정적 SPA 폴백이 catch-all이라 라우터는 그보다 먼저 등록해야 한다.**

---

## 이 계획이 닫는 열린 항목

`functional-design`의 세 문서가 Code Generation으로 넘긴 것 전부다.

| 열린 항목 | 결정 | 근거 |
|---|---|---|
| **비밀번호 해시 라이브러리 — bcrypt의 72바이트 절단을 둘지 argon2로 피할지** | **argon2id (`argon2-cffi`)** | `business-rules.md` BR-1.2가 "상한은 두지 않는다"고 정했다. bcrypt를 쓰면 72바이트 초과가 **조용히 잘려** 그 규칙과 모순된다 — 긴 비밀번호를 넣은 사용자가 사실은 앞 72바이트로만 로그인된다. argon2는 그 제약이 없어 규칙과 구현이 일치한다 |
| JWT 만료 시간 | **1440분(24시간)** | U1의 `.env.example`이 `JWT_EXPIRE_MINUTES=1440`으로 이미 확정했다. 리프레시 토큰이 없으므로(FR-1.2) 데모 중 재로그인이 생기지 않을 만큼 길어야 한다 |
| BR-1.4 응답 시간 균일화(타이밍 방어) | **구현한다** | argon2 검증기가 이미 있으므로 아이디 없을 때 더미 해시를 한 번 검증하는 것이 3줄이다. BR-1.4가 "하지 않기로 했다면 그 사실을 알고 하지 않는 것"이라 못 박았는데, 이 값에는 안 할 이유가 없다 |
| `display_name` 초기값 | **`username`을 복사** | `domain-entities.md`가 "후자가 화면을 하나 덜 만든다"고 적었다. 표시명 변경 기능이 요구사항에 없어 별도 입력칸이 순수 비용이다 |
| 회원가입 직후 자동 로그인 | **자동 로그인** | 화면 전환이 하나 줄고, 방금 만든 자격증명으로 다시 로그인하게 만들 이유가 없다. 구현은 `POST /auth/signup` 응답에 토큰을 함께 실어 프론트가 그대로 저장 |
| 클라이언트 비밀번호 길이 문구를 상수로 뺄지 | **양쪽 다 상수로** | 서버는 `app/auth/constants.py`의 `PASSWORD_MIN_LENGTH`, 프론트는 `src/lib/constants.ts`의 같은 값. **문구는 서버 응답을 그대로 쓰고 프론트는 자기 문구를 만들지 않는다** — 두 곳에 같은 문자열을 두면 어긋난다 |
| 대소문자 구분 | **그대로 둔다** (조치 없음) | `business-rules.md`가 이미 "일관되므로 그대로 둔다"로 닫았다. `utf8mb4_unicode_ci`가 검색과 유일성에 동일하게 적용된다 |

### 새로 추가되는 의존성

U1의 `backend/requirements.txt`에 두 줄을 더한다. **파일은 ASCII 전용을 유지한다**(pip이 Windows에서 로케일 코드페이지로 읽는다).

| 패키지 | 왜 |
|---|---|
| `argon2-cffi` | 위 결정 |
| `PyJWT` | JWT 발급·검증. `python-jose`보다 유지보수가 활발하고 표면이 작다 |

---

## API 표면

`component-methods.md`가 고정한 경로를 그대로 쓴다. `/api` 접두어를 붙이지 않는다.

| 메서드 | 경로 | 워크플로 | 응답 |
|---|---|---|---|
| POST | `/auth/signup` | W1 | 201 `{token, user}` / 400 `WEAK_PASSWORD` / 409 `USERNAME_TAKEN` |
| POST | `/auth/login` | W2 | 200 `{token, user}` / 401 `INVALID_CREDENTIALS` |
| GET | `/users/search?username=` | W4 | 200 `{user}` 또는 200 `{user: null}` |
| GET | `/friends` | — | 200 `{friends: [...]}` |
| POST | `/friends` | W5 | 201 / 400 `ALIAS_REQUIRED` / 400 `CANNOT_FRIEND_SELF` / 404 `USER_NOT_FOUND` / 409 `ALREADY_FRIEND` |
| PATCH | `/friends/{id}` | W6 | 200 / 400 `ALIAS_REQUIRED` / 403 `FORBIDDEN` |

**`password_hash`는 어떤 응답 스키마에도 없다.** Pydantic 응답 모델이 그것을 구조적으로 보장한다 — 서비스가 실수로 넘겨도 직렬화에서 빠진다.

## 다른 단위에 제공하는 것

`unit-of-work-dependency.md`가 기록한 계약이다. **이 셋의 시그니처를 바꾸면 U4·U5가 깨진다.**

```python
def verify_token(token: str) -> int                    # 동기 순수 함수, U4의 WS 첫 프레임용
async def current_user(...) -> User                     # FastAPI 의존성
async def resolve_display_names(session, owner_id: int, user_ids: list[int]) -> dict[int, str]
```

`verify_token()`이 **FastAPI 의존성이 아니어야 하는 것**이 BR-1.5의 핵심이다. WebSocket 핸들러는 HTTP 헤더를 받지 않으므로, 의존성으로 만들면 U4가 재사용할 수 없어 검증 로직이 두 벌이 된다.

---

## 실행 단계

### Step 1 — 모듈 골격과 상수
- [x] `app/auth/{__init__,constants,schemas,security,service,router,exceptions}.py`
- [x] `app/friends/{__init__,schemas,service,router,exceptions}.py`
- [x] `app/auth/constants.py` — `PASSWORD_MIN_LENGTH = 8`
- [x] `requirements.txt`에 `argon2-cffi`·`PyJWT` 추가 (ASCII 유지)
- 대응: 구조

### Step 2 — 도메인 예외와 매핑
- [x] `app/auth/exceptions.py` — `UsernameTaken`(409), `WeakPassword`(400), `InvalidCredentials`(401), `InvalidToken`(401)
- [x] `app/friends/exceptions.py` — `AliasRequired`(400), `UserNotFound`(404), `AlreadyFriend`(409), `CannotFriendSelf`(400), `FriendshipForbidden`(403)
- [x] 전부 U1의 `DomainError`를 상속하고 `code` 문자열을 가진다. 매핑은 `core/errors.py`의 한 곳에서 해석
- [x] **DB 무결성 위반(`IntegrityError`)을 서비스 계층에서 도메인 예외로 변환** — 라우터까지 올려보내지 않는다
- 대응: BR-1.1, BR-2.4, `business-logic-model.md` § 오류 처리

### Step 3 — `auth/security.py`
- [x] `hash_password(raw) -> str` / `verify_password(raw, hash) -> bool` — argon2id
- [x] `DUMMY_HASH` 상수와 그것을 검증하는 경로 — BR-1.4의 응답 시간 균일화
- [x] `create_token(user_id) -> str` — 클레임은 `sub`·`exp`만. `settings.JWT_SECRET.get_secret_value()`
- [x] `verify_token(token) -> int` — **동기 순수 함수.** 서명·만료·형식 실패는 `InvalidToken`
- 대응: FR-1.1, FR-1.2, FR-1.3, BR-1.3, BR-1.4, BR-1.5, BR-1.6

### Step 4 — `auth/service.py`와 라우터
- [x] `signup()` — W1 순서 그대로: 길이 검사 → **해싱(트랜잭션 밖)** → INSERT → `IntegrityError`를 409로. `display_name = username`
- [x] `login()` — W2. 사용자 없어도 `DUMMY_HASH`를 검증하고 동일한 401
- [x] `current_user()` FastAPI 의존성 — `Authorization: Bearer` → `verify_token` → SELECT → `User`
- [x] `router.py` — `/auth/signup`, `/auth/login`. 응답에 토큰 포함(자동 로그인)
- [x] 사전 중복 조회를 **하지 않는다** — UNIQUE 제약이 최종 방어선이고 조회는 창을 좁힐 뿐이다
- 대응: FR-1.1, FR-1.2, BR-1.1, BR-1.2, BR-1.4

### Step 5 — `friends/service.py`와 라우터
- [x] `search_user(username) -> User | None` — 정확 일치. 없으면 `None`이고 **404가 아니다** (BR-2.1)
- [x] `list_friends(owner_id)` — `friendships` 조회. 별칭만 반환, 상대 `display_name`은 응답 스키마에 없다
- [x] `add_friend(owner_id, username, alias)` — W5의 4단계 순서 그대로 (별칭 트림 → 대상 조회 → 자기 자신 → INSERT/무결성)
- [x] `update_alias(owner_id, friendship_id, alias)` — W6. **없는 id와 남의 id 모두 403** (BR-2.7)
- [x] 저장 시 트림한 값을 넣는다 (BR-2.2)
- [x] `router.py` — `/users/search`, `/friends` GET·POST, `/friends/{id}` PATCH
- 대응: FR-2.1~FR-2.3, BR-2.1~BR-2.7

### Step 6 — `resolve_display_names()`
- [x] **일괄 조회 2회.** ① `friendships`에서 `owner_id` + `friend_id IN (...)` ② ①에 안 나온 id에 대해서만 `users.display_name`
- [x] ②는 남은 id가 있을 때만 실행 — 전원이 친구면 쿼리 1회로 끝난다
- [x] **반복문 안에서 조회하지 않는다.** N+1이 되면 U4·U5의 응답 시간을 갉아먹는다
- 대응: FR-2.4, BR-2.8, `business-logic-model.md` § 표시명 해석

### Step 7 — 백엔드 테스트
Test Strategy **Standard**. 컴포넌트당 5~8개 + 경계 통합.
- [x] `tests/test_auth_security.py` — 해싱 왕복, 같은 입력의 해시가 매번 다름, 80바이트 비밀번호가 **잘리지 않음**(argon2 선택의 증거), 토큰 발급·검증 왕복, 만료·위조 토큰, 클레임에 `sub`·`exp`만 (7~8개)
- [x] `tests/test_auth_api.py` — 가입 201·해시가 평문과 다름, 7자 400, 중복 409, **동시 가입에서 무결성 위반이 409로 변환**, 로그인 200, 틀린 비밀번호 401, **없는 아이디와 틀린 비밀번호의 응답이 동일**, 보호 엔드포인트 401 (8개)
- [x] `tests/test_friends_api.py` — 정확 일치 검색 1명, `"ali"`로 검색 시 빈 결과 + **200**, 별칭 필수 400, **트림 후 빈 값도 400**, 단방향(B의 목록에 A 없음), 중복 409, 자기 자신 400, 없는 대상 404, 별칭 수정 200, 빈 값 수정 400 + 기존 값 유지, 남의 friendship 403, 없는 id도 403 (10~12개)
- [x] `tests/test_display_names.py` — 전원 친구면 쿼리 1회, 친구 아닌 id는 `display_name` 폴백, 빈 입력, **쿼리 횟수가 대상 수에 비례하지 않음**(N+1 회귀 방지) (5개)
- [x] MariaDB 미가용 시 skip하는 U1의 픽스처를 재사용. skip을 통과로 보고하지 않는다
- 대응: NFR-7 — FR-2.x의 수용 기준 전부

### Step 8 — 프론트 API 클라이언트와 스토어
- [x] `src/lib/constants.ts` — `PASSWORD_MIN_LENGTH = 8`
- [x] `src/lib/apiClient.ts` — JWT 부착, 오류 정규화(`{code, message}`), 타임아웃. **409를 예외로 던지지 않는다** — 정상 흐름의 갈래다
- [x] `src/store/chatStore.ts` — Zustand 스토어에 `auth`·`friends` 슬라이스. 토큰은 메모리 + `localStorage`(degraded와 달리 유지가 맞다)
- 대응: ADR-004, `components.md` § apiClient

### Step 9 — `AuthView`와 `FriendsView`
- [x] `AuthView` — 로그인/회원가입 전환, 로딩 시 제출 비활성화 + 스피너, 오류는 **폼 상단에** (필드별 아님)
- [x] 401 문구는 서버 응답을 그대로 — 프론트가 "아이디가 없습니다"로 바꾸면 BR-1.4의 비구분이 UI에서 깨진다
- [x] 비밀번호 길이는 제출 전 클라이언트에서도 검사(왕복 절약). **서버가 진실이고 클라이언트는 편의다**
- [x] 가입 성공 시 응답 토큰을 그대로 저장 — 자동 로그인
- [x] `FriendsView` — 검색 → **결과 안에 별칭 입력칸** → 추가. 별칭이 비면 추가 버튼 `disabled`
- [x] 목록에 상대 `display_name`을 **절대** 표시하지 않는다 (FR-2.4)
- [x] 비어 있음 상태: "아직 친구가 없습니다. 아이디로 검색해 추가하세요."
- [x] 접근성 — 모든 입력에 보이는 `<label>`, 오류는 `aria-live="polite"`, 검색 결과 개수를 스크린리더에 알림, `disabled` 버튼에 `aria-describedby`
- [x] `data-testid` 9개 — `auth-login-submit`, `auth-signup-submit`, `friends-search-input`, `friends-search-submit`, `friends-add-alias-input`, `friends-add-submit`, `friends-list`, `friends-list-item-{id}`, `friends-alias-edit-{id}`
- 대응: FR-1.1, FR-1.2, FR-2.1~FR-2.4, `business-logic-model.md` § 프론트엔드

### Step 10 — 프론트 테스트
- [x] `AuthView.test.tsx` — 로그인 제출, 짧은 비밀번호가 제출을 막음, 401 문구가 서버 응답 그대로, 로딩 중 버튼 비활성화, 가입 후 자동 로그인 (5~6개)
- [x] `FriendsView.test.tsx` — 검색 결과 1명 렌더, 결과 없음 문구, 별칭 비면 추가 버튼 비활성화, 추가 성공 후 목록 갱신, **목록에 `display_name`이 나타나지 않음**, 별칭 수정 (6개)
- [x] `npx vitest run` 통과
- 대응: NFR-7

---

## 요구사항 → 단계 추적

| FR/BR | 단계 |
|---|---|
| FR-1.1 회원가입 + 해싱 + 8자 | 3, 4 / 검증 7 |
| FR-1.2 JWT, 리프레시 없음 | 3, 4 / 검증 7 |
| FR-1.3 `verify_token()`을 순수 함수로 (U4가 쓴다) | 3 / 검증 7 |
| FR-2.1 정확 일치 검색 | 5, 9 / 검증 7, 10 |
| FR-2.2 단방향 즉시 등록 + 별칭 필수 | 5, 9 / 검증 7, 10 |
| FR-2.3 별칭 수정 | 5, 9 / 검증 7, 10 |
| FR-2.4 별칭만 표시 | 6, 9 / 검증 7, 10 |
| BR-1.4 로그인 실패 비구분 + 시간 균일화 | 3, 4, 9 / 검증 7 |
| BR-2.7 없는 id도 403 | 5 / 검증 7 |
| BR-2.8 표시명 해석 (U4·U5가 쓴다) | 6 / 검증 7 |

## 계획에서 뺀 것

- **마이그레이션.** 테이블은 U1이 이미 만들었다. 컬럼을 추가할 이유가 없다
- **친구 삭제·차단** — `domain-entities.md`: "요구사항에 없다. 만들지 않는다"
- **부분 일치 검색·목록 정렬·승인 절차** — FR-2.1이 명시적으로 배제
- **리프레시 토큰·자동 만료 갱신** — FR-1.2가 명시적으로 배제
- **탈퇴·비활성화·표시명 변경** — 범위 밖
- **방·메시지·판정** — U4·U5·judgment-core 소관. 이 단위는 `room_members`·`rooms`·`messages`·`judgment_logs`를 만지지 않는다

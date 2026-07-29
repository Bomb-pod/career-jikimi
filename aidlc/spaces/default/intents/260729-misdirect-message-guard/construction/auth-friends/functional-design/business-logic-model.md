# Business Logic Model — auth-friends

`../../../inception/units-generation/unit-of-work.md`의 U3이 수행하는 흐름이다. 배정된 요구사항은 `../../../inception/units-generation/unit-of-work-story-map.md`에, 그 내용은 `../../../inception/requirements-analysis/requirements.md`의 FR-1.1~FR-1.3·FR-2.1~FR-2.4에 있다. 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 서명은 `../../../inception/application-design/component-methods.md`, 프로세스·트랜잭션 형태는 `../../../inception/application-design/services.md`가 정한다.

규칙 번호(`BR-*`)는 같은 디렉터리의 `business-rules.md`를, 테이블 구조는 `domain-entities.md`를 가리킨다.

## 워크플로

### W1 · 회원가입

```
[요청: username, password]
   |
   |-- 1. BR-1.2 비밀번호 길이 검사 ----- 실패 --> 400 WEAK_PASSWORD
   |
   |-- 2. 비밀번호 해싱 (bcrypt/argon2)
   |
   |-- 3. INSERT users
   |        |
   |        +-- UNIQUE 위반 --> 409 USERNAME_TAKEN   (BR-1.1)
   |
   +-- 4. 201 { id, username, display_name }
```

<!-- Text fallback: 회원가입은 비밀번호 길이를 먼저 검사하고, 통과하면 해싱한 뒤 users에 INSERT한다. UNIQUE 제약 위반이면 409를 반환하고, 성공하면 201과 사용자 정보를 반환한다. 비밀번호 해시는 응답에 포함하지 않는다. -->

**해싱을 INSERT 앞에 두는 이유** — 해싱은 의도적으로 느리다(bcrypt 기본 cost에서 수십~수백 ms). 트랜잭션 안에 넣으면 그동안 커넥션을 붙들고 있다. 해싱은 DB와 무관하므로 밖에서 끝낸다.

**사전 중복 조회를 하지 않는다.** 경쟁 조건에서 어차피 UNIQUE 제약이 잡아야 하고, 조회를 추가해도 창을 좁힐 뿐 없애지 못한다. 조회 한 번을 아끼고 무결성 위반을 409로 변환하는 쪽이 정직하다.

응답에 `password_hash`를 절대 포함하지 않는다.

### W2 · 로그인

```
[요청: username, password]
   |
   |-- 1. SELECT users WHERE username = ?
   |        |
   |        +-- 없음 --> 401 INVALID_CREDENTIALS   (BR-1.4)
   |
   |-- 2. 해시 검증
   |        |
   |        +-- 불일치 --> 401 INVALID_CREDENTIALS  (동일 응답)
   |
   |-- 3. JWT 발급 (sub=user_id, exp)
   |
   +-- 4. 200 { token, user }
```

<!-- Text fallback: 로그인은 username으로 사용자를 조회하고, 없거나 비밀번호가 틀리면 동일한 401을 반환한다. 성공하면 JWT를 발급해 200과 함께 반환한다. -->

**1번과 2번의 실패가 구분되지 않아야 한다**(BR-1.4). 응답 본문, 상태 코드, 오류 코드가 모두 같다.

JWT 클레임은 `sub`(user_id)와 `exp`만 담는다. 사용자명·표시명을 넣지 않는다 — 바뀔 수 있는 값을 토큰에 넣으면 토큰이 낡는다.

### W3 · 토큰 검증

두 경로에서 쓰인다. **같은 함수를 쓰되 실패 표현이 다르다.**

```
verify_token(token) -> user_id
   |
   +-- 서명·만료·형식 검사 --> 실패 시 InvalidToken 예외
   |
   +-- 성공 --> user_id (int)

경로 A: HTTP 의존성 current_user()
   verify_token → user_id → SELECT users → User 객체
   실패 → 401

경로 B: WebSocket 첫 프레임 (U4가 호출)
   verify_token → user_id
   실패 → auth_error 프레임 전송 후 연결 종료
```

<!-- Text fallback: verify_token은 토큰의 서명·만료·형식을 검사해 user_id를 반환하는 동기 순수 함수다. HTTP 경로에서는 current_user 의존성이 이를 감싸 사용자 객체를 만들고 실패 시 401을 낸다. WebSocket 경로에서는 U4가 직접 호출해 실패 시 auth_error 프레임을 보내고 연결을 끊는다. -->

**`verify_token()`이 FastAPI 의존성이 아니어야 하는 이유** — WebSocket 핸들러는 HTTP 헤더를 받지 않는다. 의존성으로 만들면 U4가 재사용할 수 없어 검증 로직이 두 벌이 된다 (FR-1.3, BR-1.5).

### W4 · 사용자 검색

```
[요청: username]
   |
   +-- SELECT id, username, display_name FROM users WHERE username = ?
   |
   +-- 200 { user } 또는 200 { user: null }
```

<!-- Text fallback: 사용자 검색은 username 정확 일치로 조회해 결과가 있으면 사용자 정보를, 없으면 null을 200과 함께 반환한다. -->

**없어도 200이다**(BR-2.1). 검색은 성공했고 결과가 비었을 뿐이다. `password_hash`는 SELECT 목록에 넣지 않는다.

### W5 · 친구 등록

```
[요청: username, alias]
   |
   |-- 1. alias 트림 후 검사 --------- 빈 값 --> 400 ALIAS_REQUIRED   (BR-2.2)
   |
   |-- 2. SELECT users WHERE username = ?
   |        |
   |        +-- 없음 --> 404 USER_NOT_FOUND                          (BR-2.6)
   |
   |-- 3. friend_id == owner_id ? ---- 예 --> 400 CANNOT_FRIEND_SELF (BR-2.5)
   |
   |-- 4. INSERT friendships (owner_id, friend_id, alias=트림된 값)
   |        |
   |        +-- UNIQUE 위반 --> 409 ALREADY_FRIEND                   (BR-2.4)
   |
   +-- 5. 201 { friendship }
```

<!-- Text fallback: 친구 등록은 별칭을 트림해 검사하고, 대상 사용자를 조회하고, 자기 자신인지 확인한 뒤 friendships에 INSERT한다. 각 단계의 실패는 400, 404, 400, 409로 응답한다. 규칙 판정은 DB 접근이 없는 것부터 순서대로 한다. -->

순서가 `business-rules.md`의 "규칙 간 우선순위"를 따른다 — 입력만 보면 되는 검사가 먼저다.

### W6 · 별칭 수정

```
[요청: friendship_id, alias]
   |
   |-- 1. alias 트림 후 검사 --------- 빈 값 --> 400 ALIAS_REQUIRED (기존 값 유지)
   |
   |-- 2. SELECT friendships WHERE id = ?
   |        |
   |        +-- 없음 또는 owner_id != 호출자 --> 403 FORBIDDEN      (BR-2.7)
   |
   |-- 3. UPDATE friendships SET alias = ?
   |
   +-- 4. 200 { friendship }
```

<!-- Text fallback: 별칭 수정은 트림 후 빈 값이면 400을 내고 기존 값을 유지한다. friendship이 없거나 남의 것이면 둘 다 403을 낸다. 통과하면 UPDATE하고 200을 반환한다. -->

**없는 id와 남의 id를 모두 403으로 응답한다**(BR-2.7). 404를 주면 id의 존재 여부가 새어나간다.

## 알고리즘: 표시명 해석

`resolve_display_names(owner_id, user_ids) -> dict[int, str]`

이 단위가 다른 두 단위에 제공하는 함수다. **표시명 규칙이 흩어지지 않게 하는 유일한 출처**이므로 정확히 정의한다.

```
입력: owner_id, user_ids = [3, 7, 12]

1. SELECT friend_id, alias
     FROM friendships
    WHERE owner_id = ? AND friend_id IN (...)
   → { 3: "회사 김대리", 7: "동생" }

2. 남은 id (12) 에 대해
   SELECT id, display_name FROM users WHERE id IN (...)
   → { 12: "carol" }

3. 병합 (1번이 우선)
   → { 3: "회사 김대리", 7: "동생", 12: "carol" }
```

<!-- Text fallback: 표시명 해석은 먼저 friendships에서 owner_id와 대상 id들로 별칭을 일괄 조회하고, 별칭이 없는 id에 대해서만 users에서 display_name을 일괄 조회한 뒤 병합한다. 별칭이 우선한다. -->

**두 번의 일괄 조회다. 반복문 안에서 조회하지 않는다.** 방 참여자가 늘면 N+1이 되어 `rooms`·`messages`의 응답 시간을 갉아먹는다 (`component-dependency.md`의 열린 항목).

2번은 1번에서 안 나온 id가 있을 때만 실행한다. 친구 목록 조회처럼 전원이 친구인 경우 쿼리가 한 번으로 끝난다.

**폴백이 발생하는 조건**은 하나뿐이다 — 방에 내가 친구로 등록하지 않은 참여자가 있을 때(다른 사람이 초대, FR-10.1). 친구 목록에서는 절대 일어나지 않는다.

## 프론트엔드

이 단위는 `AuthView`와 `FriendsView`를 포함한다. `kind: service`라 `frontend-components.md`가 산출물에서 제외되었으므로 여기에 적는다.

### `AuthView`

| 상태 | 내용 |
|---|---|
| 기본 | 로그인 폼 (아이디, 비밀번호) + "회원가입" 전환 링크 |
| 회원가입 | 아이디, 비밀번호, 비밀번호 확인 |
| 로딩 | 제출 버튼 비활성화 + 스피너 |
| 오류 | 폼 상단에 메시지. 필드별 표시는 하지 않는다 |

**검증 시점** — 비밀번호 길이는 제출 전 클라이언트에서도 검사한다(왕복 절약). 다만 서버 검사가 진실이며 클라이언트 검사는 편의다.

**오류 문구** — 401은 "아이디 또는 비밀번호가 올바르지 않습니다"로 표시한다. BR-1.4의 비구분 원칙이 UI까지 이어져야 한다.

성공 시 토큰을 `chatStore.auth`에 넣고 `wsClient.connect(token)`을 호출한다(U4 소관).

### `FriendsView`

| 영역 | 내용 |
|---|---|
| 검색 | 아이디 입력 + 검색 버튼. 결과는 0명 또는 1명 |
| 검색 결과 | 사용자 표시 + **별칭 입력칸** + "추가" 버튼 |
| 목록 | 별칭 목록. 각 항목에 "이름 수정" |
| 비어 있음 | "아직 친구가 없습니다. 아이디로 검색해 추가하세요." |

**별칭 입력칸이 검색 결과 안에 있어야 한다.** 추가 버튼을 누른 뒤 별칭을 묻는 2단계로 만들면, 사용자가 별칭이 필수라는 걸 누른 다음에야 알게 된다. 입력칸이 비어 있으면 "추가" 버튼을 비활성화한다 — 오류 메시지보다 나은 오류 예방이다.

**목록에는 상대의 `display_name`을 절대 보여주지 않는다**(FR-2.4). 별칭만 보인다.

### 접근성

| 요소 | 요구 |
|---|---|
| 폼 라벨 | 모든 입력에 보이는 `<label>`. placeholder만으로 대신하지 않는다 |
| 오류 | `aria-live="polite"` 영역에 렌더링 |
| 검색 결과 | 결과 개수를 스크린리더에 알린다 ("1명 찾음" / "결과 없음") |
| 버튼 비활성화 | `disabled` + 이유를 `aria-describedby`로 |

### 자동화 훅

`data-testid`를 붙인다 — `auth-login-submit`, `auth-signup-submit`, `friends-search-input`, `friends-search-submit`, `friends-add-alias-input`, `friends-add-submit`, `friends-list`, `friends-list-item-{id}`, `friends-alias-edit-{id}`.

## 오류 처리

| 계층 | 방식 |
|---|---|
| 서비스 함수 | 도메인 예외 (`UsernameTaken`, `WeakPassword`, `InvalidCredentials`, `AliasRequired`, `UserNotFound`, `AlreadyFriend`, `CannotFriendSelf`, `Forbidden`) |
| 라우터 | 예외 → HTTP 상태 매핑을 **한 곳에** 둔다 |
| DB 무결성 위반 | 서비스 계층에서 도메인 예외로 변환 (BR-1.1, BR-2.4) |

**무결성 위반을 라우터까지 올려보내지 않는다.** 올려보내면 DB 방언이 HTTP 계층에 새고, MariaDB를 바꾸면 라우터가 깨진다.

## Assumptions & Open Questions

- JWT 만료 시간이 정해지지 않았다. 리프레시 토큰이 없으므로(FR-1.2) 짧으면 데모 중 재로그인이 생긴다. 길게 잡는 편이 낫다.
- 회원가입 직후 자동 로그인할지 로그인 화면으로 보낼지 정하지 않았다. 자동 로그인이 화면 전환을 하나 줄인다.
- `display_name` 초기값 처리가 `domain-entities.md`에서 이월된 채 남아 있다.
- 클라이언트 측 비밀번호 길이 검사의 문구가 서버 오류 문구와 일치해야 하는데, 두 곳에 같은 문자열을 두면 어긋난다. 상수로 뺄지 정하지 않았다.

# Domain Entities — auth-friends

`../../../inception/units-generation/unit-of-work.md`의 U3이 소유하는 엔티티다. 배정 근거는 `../../../inception/units-generation/unit-of-work-story-map.md`, 요구사항은 `../../../inception/requirements-analysis/requirements.md`의 FR-1.1~FR-1.3·FR-2.1~FR-2.4, 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 표면은 `../../../inception/application-design/component-methods.md`, 배포 형태는 `../../../inception/application-design/services.md`가 정한다.

**테이블 생성은 U1(foundation)의 초기 마이그레이션이 한다.** 이 문서는 이 단위가 읽고 쓰는 두 테이블의 구조와 불변식을 정의한다.

## `users`

가입한 사람. 시스템의 모든 소유권이 여기서 출발한다.

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | |
| `username` | VARCHAR(50) | NOT NULL, UNIQUE | 로그인 아이디이자 친구 검색 키 (FR-2.1) |
| `display_name` | VARCHAR(50) | NOT NULL | 본인이 설정한 표시명. **친구 목록에는 쓰이지 않는다** (FR-2.4) |
| `password_hash` | VARCHAR(255) | NOT NULL | bcrypt 또는 argon2. 평문 저장 금지 (FR-1.1) |
| `created_at` | DATETIME(6) | NOT NULL, DEFAULT NOW(6) | |

**인덱스**: `username`의 UNIQUE 인덱스가 검색과 중복 방지를 겸한다. 별도 인덱스 불필요.

**`display_name`이 존재하는 이유** — 친구가 아닌 참여자를 방에서 표시할 때 쓰인다(`component-methods.md`의 `resolve_display_names()` 폴백). 친구 목록에서는 절대 쓰이지 않는다. FR-2.4가 "내가 붙인 별칭만"을 요구하기 때문이다.

**불변식**
- `username`은 전역 유일하다
- `password_hash`는 이 단위 밖으로 나가지 않는다. API 응답에 절대 포함하지 않는다

**생애주기**: 생성 후 변하지 않는다. 탈퇴·비활성화는 범위 밖이다.

## `friendships`

**단방향** 관계다. A가 B를 등록해도 B의 목록에 A는 없다 (FR-2.2).

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | |
| `owner_id` | BIGINT | NOT NULL, FK → `users.id` | 등록한 쪽 |
| `friend_id` | BIGINT | NOT NULL, FK → `users.id` | 등록당한 쪽 |
| `alias` | VARCHAR(50) | **NOT NULL** | 내가 붙인 이름. 빈 값 불가 (FR-2.2) |
| `created_at` | DATETIME(6) | NOT NULL, DEFAULT NOW(6) | |

**인덱스**
- `UNIQUE (owner_id, friend_id)` — 같은 상대를 두 번 등록할 수 없다
- `INDEX (owner_id)` — 친구 목록 조회. 위 UNIQUE의 선행 컬럼이라 별도로 만들 필요는 없다

**`alias`가 NOT NULL인 것이 이 엔티티의 핵심 제약이다.** DB 레벨에서 강제하므로 애플리케이션 버그가 있어도 별칭 없는 행이 생기지 않는다. 다만 NOT NULL은 빈 문자열을 막지 못하므로 **공백만 있는 값의 거부는 애플리케이션이 해야 한다**(`business-rules.md` BR-2.2).

**불변식**
- `owner_id != friend_id` — 자기 자신을 친구로 등록할 수 없다. DB 제약으로 표현하기 번거로우므로 애플리케이션이 막는다
- `(owner_id, friend_id)` 쌍은 유일하다
- `alias`는 트림 후 1자 이상이다

**생애주기**

```
[없음] --add_friend--> [등록됨] --update_alias--> [등록됨]
```

<!-- Text fallback: 친구 관계는 등록되면 그 상태로 유지되며 별칭만 바뀐다. 삭제 상태는 없다. -->

친구 삭제는 요구사항에 없다. 만들지 않는다.

## 관계

```
users (1) ----owner----< (N) friendships (N) >----friend---- (1) users
```

<!-- Text fallback: users와 friendships는 두 개의 1:N 관계로 이어진다. 한 사용자는 여러 friendships의 owner일 수 있고, 동시에 여러 friendships의 friend일 수도 있다. -->

한 사용자가 owner이자 friend일 수 있다. A→B와 B→A가 둘 다 있으면 상호 친구지만, 시스템은 그것을 특별히 다루지 않는다 — 두 개의 독립된 단방향 관계일 뿐이다.

## 다른 단위와의 접점

이 단위가 **제공**하는 것 (`unit-of-work-dependency.md`의 통합 계약):

| 대상 | 무엇을 |
|---|---|
| U4 rooms-realtime | `auth.verify_token()` — WebSocket 첫 프레임 인증 (FR-1.3) |
| U4 rooms-realtime | `friends.resolve_display_names()` — 방 참여자 표시명 |
| U5 messaging | `friends.resolve_display_names()` — 히스토리 발신자 표시명 |
| 전체 | `auth.current_user()` — HTTP 의존성 |

`room_members`·`rooms`·`messages`·`judgment_logs`는 **이 단위가 만지지 않는다.** `friendships.friend_id`가 `users`를 가리킬 뿐, 방 관련 테이블과 직접 조인하지 않는다.

## Assumptions & Open Questions

- `display_name`의 초기값을 회원가입 시 어떻게 정할지 요구사항에 없다. 별도 입력을 받을지 `username`을 복사할지 정해지지 않았다. 후자가 화면을 하나 덜 만든다.
- `VARCHAR(50)` 길이는 이 단계에서 정한 값이다. 요구사항에 근거가 없다.
- 자기 자신을 친구로 등록하는 것을 막는 규칙이 요구사항에 명시적으로 없다. 상식적 제약으로 추가했다.
- 친구 삭제·차단이 없으므로 잘못 등록하면 별칭만 바꿀 수 있다. 데모 범위에서 수용한다.

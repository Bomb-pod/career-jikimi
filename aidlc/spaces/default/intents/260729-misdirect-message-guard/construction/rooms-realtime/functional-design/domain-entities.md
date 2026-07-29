# Domain Entities — rooms-realtime

`../../../inception/units-generation/unit-of-work.md`의 U4가 소유하는 엔티티다. 배정은 `../../../inception/units-generation/unit-of-work-story-map.md`, 요구사항은 `../../../inception/requirements-analysis/requirements.md`의 FR-1.3·FR-3.1~FR-3.3·FR-5.1~FR-5.4·FR-6.1·FR-10, 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 표면은 `../../../inception/application-design/component-methods.md`, 프로세스 형태는 `../../../inception/application-design/services.md`가 정한다.

테이블 생성은 U1(foundation)의 초기 마이그레이션이 한다.

## `rooms`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | |
| `name` | VARCHAR(100) | NULL 허용 | 없으면 참여자 이름으로 화면에서 조립 |
| `last_seq` | BIGINT | NOT NULL, DEFAULT 0 | **이 단위가 소유하되 U5가 증가시킨다** |
| `created_by` | BIGINT | NOT NULL, FK → `users.id` | |
| `created_at` | DATETIME(6) | NOT NULL, DEFAULT NOW(6) | |

**`last_seq`의 소유권이 이 엔티티의 특이점이다.** 스키마와 초기화는 이 단위가 소유하지만, 증가는 U5가 한다 — 채번이 메시지 저장과 같은 트랜잭션 안에 있어야 하기 때문이다 (ADR-003).

이 단위는 `last_seq`를 **읽기만** 한다(안 읽은 개수 계산). 쓰지 않는다.

**`name`이 NULL 허용인 이유** — 1:1 방에 이름을 강제하면 사용자가 매번 지어야 한다. 비어 있으면 화면이 참여자 표시명으로 조립한다.

## `room_members`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `room_id` | BIGINT | PK(복합), FK → `rooms.id` | |
| `user_id` | BIGINT | PK(복합), FK → `users.id` | |
| `ai_check_enabled` | BOOLEAN | NOT NULL, DEFAULT TRUE | **개인별** 설정 (FR-6.1) |
| `last_read_seq` | BIGINT | NOT NULL, DEFAULT 0 | 안 읽은 개수의 기준 (FR-5.2) |
| `joined_at` | DATETIME(6) | NOT NULL, DEFAULT NOW(6) | |

**복합 PK `(room_id, user_id)`** 가 중복 참여를 막는다.

**인덱스**: `INDEX (user_id)` — 방 목록 조회(내가 속한 방)의 진입점. 복합 PK의 선행 컬럼이 `room_id`라 별도로 필요하다.

### `ai_check_enabled`가 `rooms`가 아니라 여기 있는 것

이 프로젝트의 핵심 결정 하나다 (FR-6.1). 방 단위였다면 `rooms`에 있었을 것이다.

**개인별인 이유** — 이 기능은 "내가 실수하는 걸 막는" 기능이지 남을 위한 것이 아니다. 방장이 켜면 전원이 1~3초씩 기다리게 되는데, 남이 내 전송 지연을 결정하면 안 된다.

`README.md`가 한때 "방별 토글"로 적혀 있었고 그것이 Intent Capture에서 모순으로 잡혀 개인별로 확정되었다.

### `last_read_seq`

안 읽은 개수는 이 값보다 큰 `seq`를 가진 메시지 수다 (FR-5.2).

**전진만 한다.** 이미 더 큰 값이면 갱신을 무시한다 — 순서가 뒤바뀐 요청이 배지를 되살리는 것을 막는다 (BR-5.3).

## 인메모리: 연결 레지스트리

테이블이 아니다. **프로세스 메모리에만 있다** — 그래서 CON-1(단일 프로세스)이 생긴다.

```python
_connections: dict[int, WebSocket]   # user_id -> 소켓
```

| 특성 | 값 |
|---|---|
| 수명 | 프로세스 수명. 재시작하면 사라진다 |
| 크기 | 동시 접속자 수 |
| 동시성 | 단일 프로세스 + async 단일 스레드라 잠금 불필요 |
| 사용자당 | **1개**. 두 번째 연결이 오면 첫 번째를 교체한다 (FR-5.1) |

**이것이 확장의 병목이자 유일한 교체 지점이다.** Redis pub/sub으로 바꾸면 멀티 워커가 가능해진다. 표면이 세 함수(`register`·`unregister`·`push_to_users`)뿐인 것은 그 교체를 싸게 만들기 위해서다.

**재시작하면 전부 끊긴다.** 클라이언트가 재연결하면 복구되며, 그 사이 메시지는 히스토리로 받는다 — 유실이 아니다.

## 관계

```
users (1) ----created_by----< (N) rooms (1) ----< (N) room_members (N) >---- (1) users
                                    |
                                    | last_seq (U5가 증가)
                                    v
                                 messages
```

<!-- Text fallback: rooms는 created_by로 users를 참조하고, room_members가 rooms와 users 사이의 다대다 관계를 복합 키로 표현한다. rooms의 last_seq는 messages의 seq 채번에 쓰이며 U5가 증가시킨다. -->

## 생애주기

### 방

```
[생성] --add_member--> [생성]  (FR-10.1, Should)
   |
   +--leave_room--> [참여자 감소]  (FR-10.2, Should)
```

<!-- Text fallback: 방은 생성 후 참여자가 늘거나 줄 뿐 삭제 상태가 없다. -->

**방 삭제가 없다.** 마지막 참여자가 나가도 방은 남는다 — 요구사항에 없고, 메시지가 남아 있어 지우면 히스토리가 깨진다.

### 참여자

```
[없음] --create_room / add_member--> [참여] --leave_room--> [없음]
                                        |
                                        +-- set_ai_check (토글)
                                        +-- mark_read (전진만)
```

<!-- Text fallback: 참여자는 방 생성이나 초대로 추가되고, 나가면 제거된다. 참여 중에는 AI 검증 토글을 바꾸거나 읽음 위치를 전진시킬 수 있다. -->

**나갔다 다시 초대되면 `ai_check_enabled`와 `last_read_seq`가 기본값으로 돌아간다.** 행이 지워졌다 새로 생기기 때문이다. 읽음 위치가 0이 되어 이전 메시지가 전부 안 읽음으로 보인다 — 아래 열린 항목 참조.

## 다른 단위와의 접점

**소비**

| 대상 | 무엇을 |
|---|---|
| U3 auth-friends | `verify_token()` — WebSocket 첫 프레임 인증 (FR-1.3) |
| U3 auth-friends | `resolve_display_names()` — 참여자 표시명 (FR-2.4) |
| U1 foundation | `get_session()`, `settings` |

**제공**

| 대상 | 무엇을 |
|---|---|
| U5 messaging | `get_membership()` — 참여자 자격 + `ai_check_enabled` |
| U5 messaging | `member_user_ids()` — 브로드캐스트 대상 |
| U5 messaging | `ws_registry.push_to_users()` — 실제 전송 |

이 단위는 `messages` 테이블을 **읽는다**(안 읽은 개수 계산). 쓰지 않는다.

## Assumptions & Open Questions

- 방을 나갔다 재초대되면 `last_read_seq`가 0으로 초기화되어 과거 메시지가 전부 안 읽음으로 표시된다. 나갈 때 값을 보존할지(soft delete) 정하지 않았다. FR-10은 Should 등급이라 잘릴 수도 있다.
- `rooms.name`이 NULL일 때 화면이 조립하는 규칙(참여자 몇 명까지 나열할지)이 정해지지 않았다.
- `VARCHAR(100)`은 이 단계에서 정한 값이다.
- 방 삭제가 없으므로 데모 중 만든 방이 계속 쌓인다. 시연 전에 DB를 비우는 것 외에 정리 수단이 없다.

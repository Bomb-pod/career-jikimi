# Component Methods — career-jikimi

`components.md`가 정한 각 컴포넌트의 공개 표면을 서명 수준으로 편 것이다. **상세한 업무 규칙은 Functional Design의 몫**이며, 여기서는 무엇을 받고 무엇을 돌려주며 어떤 오류가 나는지만 정한다.

`../requirements-analysis/requirements.md`의 FR 번호로 대응을 표기한다.

## 오류 처리 방침

| 계층 | 방식 |
|---|---|
| 서비스 함수 | 도메인 예외를 던진다 (`AliasRequired`, `NotAFriend`, `RoomNotFound`, …) |
| 라우터 | 도메인 예외를 HTTP 상태로 변환한다. 예외 → 상태 매핑은 한 곳에 모은다 |
| 판정 실패 | **예외가 아니다.** `JudgeResult.Failed`라는 정상 반환값이다 — 실패가 흐름의 일부이기 때문이다 (FR-8) |
| 부적절 판정 | **예외가 아니다.** 409 응답이며 클라이언트의 정상 분기다 |

판정 실패와 부적절 판정을 예외로 만들지 않는 것이 이 설계의 핵심이다. 둘 다 "일어나면 안 되는 일"이 아니라 "일어나기로 되어 있는 일"이다.

---

## `core/ws_registry`

```python
async def register(user_id: int, ws: WebSocket) -> None
```
사용자의 연결을 등록한다. 같은 사용자의 기존 연결이 있으면 그것을 닫고 교체한다 — 사용자당 1개 원칙(FR-5.1).

```python
async def unregister(user_id: int) -> None
```
연결 해제. 이미 없으면 조용히 통과한다.

```python
async def push_to_users(user_ids: list[int], payload: dict) -> None
```
연결된 사용자에게만 밀어낸다. 연결이 없는 사용자는 건너뛴다 — **오류가 아니다**(오프라인일 뿐이며, 그 사용자는 다음 입장 시 히스토리로 받는다). 전송 중 소켓이 죽으면 그 사용자를 unregister하고 나머지는 계속 보낸다.

---

## `auth`

```python
async def signup(username: str, password: str) -> User
```
- 오류: `UsernameTaken`(409), `WeakPassword`(400, 8자 미만)
- FR-1.1

```python
async def login(username: str, password: str) -> str        # JWT
```
- 오류: `InvalidCredentials`(401)
- FR-1.2

```python
def verify_token(token: str) -> int                          # user_id
```
동기 순수 함수. HTTP 의존성과 WebSocket 인증 양쪽에서 쓴다.
- 오류: `InvalidToken`
- FR-1.2, FR-1.3

```python
async def current_user(...) -> User                          # FastAPI 의존성
```
`Authorization: Bearer` 헤더를 검증해 사용자를 반환한다.

---

## `friends`

```python
async def search_user(username: str) -> User | None
```
**정확 일치만.** 부분 일치·유사도 검색을 하지 않는다 (FR-2.1).

```python
async def add_friend(owner_id: int, target_username: str, alias: str) -> Friendship
```
- `alias`가 빈 문자열이거나 공백뿐이면 `AliasRequired`(400) — FR-2.2
- 대상이 없으면 `UserNotFound`(404)
- 이미 등록되어 있으면 `AlreadyFriend`(409)
- 단방향이다. 상대의 친구 목록은 바뀌지 않는다

```python
async def update_alias(owner_id: int, friendship_id: int, alias: str) -> Friendship
```
- 빈 별칭이면 `AliasRequired`(400), 기존 값 유지 — FR-2.3
- 남의 friendship이면 `Forbidden`(403)

```python
async def list_friends(owner_id: int) -> list[Friendship]
```
별칭 포함. 정렬 규정 없음 (FR-2.1).

```python
async def resolve_display_names(owner_id: int, user_ids: list[int]) -> dict[int, str]
```
표시명 해석의 **단일 출처**. `rooms`가 참여자를 보여줄 때 이것을 쓴다. 친구가 아닌 참여자는 계정 표시명으로 떨어진다 — 방에는 친구가 아닌 사람도 있을 수 있기 때문이다(다른 참여자가 초대한 경우, FR-10.1). FR-2.4가 규정하는 것은 *친구인 상대*의 표시이며, 친구가 아닌 참여자까지 별칭을 강제하지는 않는다.

---

## `rooms`

```python
async def create_room(owner_id: int, friend_user_ids: list[int], name: str | None) -> Room
```
- `friend_user_ids`가 비어 있으면 `EmptyRoom`(400) — 최소 2명(FR-3.1)
- 친구가 아닌 id가 섞이면 `NotAFriend`(400)
- 모든 참여자의 `room_members.ai_check_enabled`를 **true**로 초기화 (FR-6.1)
- `rooms.last_seq`를 0으로 초기화

```python
async def list_rooms(user_id: int) -> list[RoomSummary]
```
`RoomSummary`는 방 정보 + `unread_count` + 참여자 표시명을 담는다. `unread_count`는 `last_read_seq`보다 큰 메시지 수 (FR-5.2).

```python
async def mark_read(user_id: int, room_id: int, up_to_seq: int) -> None
```
`last_read_seq`를 전진시킨다. **뒤로 가지 않는다** — 이미 더 큰 값이면 무시한다. 순서가 뒤바뀐 요청이 배지를 되살리는 것을 막는다 (FR-5.2).

```python
async def set_ai_check(user_id: int, room_id: int, enabled: bool) -> None
```
**호출자 본인의** `room_members` 행만 바꾼다. 다른 참여자의 설정에 영향을 주지 않는다 (FR-6.1).

```python
async def member_user_ids(room_id: int) -> list[int]
```
브로드캐스트 대상 조회. `messages`가 쓴다.

```python
async def get_membership(user_id: int, room_id: int) -> RoomMember | None
```
호출자의 `room_members` 행을 반환한다 — `ai_check_enabled`, `last_read_seq` 포함. `None`이면 참여자가 아니다.

`messages.send_message`가 **두 가지를 한 번에** 확인하는 데 쓴다: 참여자 자격(FR-3.x)과 검증 토글(FR-6.1). `member_user_ids()`는 브로드캐스트 대상만 주므로 토글을 알 수 없다.

```python
async def get_room_detail(user_id: int, room_id: int) -> RoomDetail
```
`GET /rooms/{id}`의 반환. 방 정보 + 참여자 목록(**`friends.resolve_display_names()`로 해석된 표시명 포함**, FR-2.4) + 호출자의 `ai_check_enabled` + `last_read_seq`.
- 참여자가 아니면 `Forbidden`(403)

```python
async def add_member(actor_id: int, room_id: int, friend_user_id: int) -> None   # Should
async def leave_room(user_id: int, room_id: int) -> None                          # Should
```
FR-10.1, FR-10.2.

---

## `judgment`

```python
@dataclass
class JudgeResult:
    outcome: Literal["appropriate", "inappropriate", "failed"]
    log_id: int
    score: float | None          # failed면 None
```

```python
async def judge(
    user_id: int,                # 로그 소유자 — force_log_id 검증에 쓰인다
    room_id: int,
    context: list[Message],      # 최근 N개, 오래된 것부터
    candidate_text: str,
) -> JudgeResult
```

- 문맥은 `AI_CONTEXT_N`개 (기본 10). **참여자 이름·아이디·별칭을 포함하지 않는다** (FR-6.2)
- Structured Outputs로 `{"score": float}`만 받는다 (ADR-005)
- `score >= AI_VERDICT_THRESHOLD`면 `inappropriate`
- 타임아웃 `AI_TIMEOUT_SECONDS`, **재시도 1회**, 총 대기 상한을 넘기지 않는다 (FR-8.1)
- 성공·실패 모두 `judgment_logs`에 행을 남기고 `log_id`를 돌려준다 (FR-7.2). 실패면 `score`·`verdict`가 NULL
- **예외를 던지지 않는다.** 실패는 `outcome="failed"`로 표현한다

```python
async def set_user_action(log_id: int, action: Literal["auto_sent","sent","cancelled"]) -> None
```
판정 로그의 라벨을 기록한다 (FR-7.2, FR-7.3). **이미 채워져 있으면 `AlreadyResolved`를 던진다** — 라벨이 덮어써지면 집계가 왜곡되고, `force_log_id`의 1회성도 깨진다.

```python
async def get_log_for_force(user_id: int, room_id: int, log_id: int) -> JudgmentLog
```
`force_log_id` 검증 전용 조회. 소유자·방·미소진 세 조건을 확인해 반환하고, 하나라도 어긋나면 예외를 던진다. 검증 로직이 `messages`에 흩어지지 않게 `judgment`가 소유한다.

### 미해소 로그 (orphan)

부적절 판정 후 사용자가 팝업에 답하지 않고 창을 닫으면 `user_action`이 비어 있는 로그가 남는다. **이것은 오류가 아니라 관찰 결과다** — "경고를 받고 아무것도 하지 않았다"는 사실 자체가 정보다.

FR-7.4의 집계는 `verdict IS NOT NULL`인 행을 쓰므로 이 미해소 로그도 분모에 들어간다. `user_action`이 NULL인 건은 TP도 FP도 아니므로 precision 계산에서는 제외하고, **별도로 "미응답 건수"로 보고한다.** 이 수치가 크면 팝업이 무시당하고 있다는 신호다.

```python
async def link_message(log_id: int, message_id: int) -> None
```
전송이 확정된 뒤 로그를 메시지에 연결한다. 취소된 건은 호출되지 않아 `message_id`가 NULL로 남는다.

```python
async def compute_metrics(since: datetime | None) -> MetricsReport
```
FR-7.5의 지표를 산출한다. **`recall` 필드는 수치가 아니라 `"산출 불가 — 라벨 데이터셋 필요"` 문자열이다.** 집계 대상은 `judgment_logs`이며 `verdict IS NOT NULL`인 행만 쓴다 (FR-7.4).

---

## `messages`

```python
async def send_message(
    user_id: int,
    room_id: int,
    text: str,
    force_log_id: int | None = None,   # 부적절 판정 강행 시
    degraded: bool = False,            # 클라이언트가 degraded 상태임을 알림
) -> SendResult
```

전송 경로 전체를 오케스트레이션한다. 반환은 판별 가능한 두 갈래다.

| 반환 | 언제 | HTTP |
|---|---|---|
| `Sent(message)` | 저장·브로드캐스트 완료 | 201 |
| `Blocked(log_id, score)` | 부적절 판정, 저장 안 함 | 409 |

처리 순서:

1. `rooms.get_membership()`으로 참여자 자격과 `ai_check_enabled`를 함께 확인 — 참여자가 아니면 `Forbidden`(403)
2. `force_log_id`가 있으면 **네 가지를 검증한 뒤에만** 판정을 건너뛰고 `flagged_sent`로 진행 (FR-6.6):

   | 검증 | 실패 시 |
   |---|---|
   | 그 로그가 존재하는가 | `InvalidForceToken`(400) |
   | 그 로그를 만든 사용자가 호출자인가 | `Forbidden`(403) |
   | 그 로그의 `room_id`가 이 방인가 | `InvalidForceToken`(400) |
   | 그 로그의 `user_action`이 아직 비어 있는가 (**1회성**) | `InvalidForceToken`(400) |

   네 검증을 통과하면 `user_action='sent'`로 기록한다. `user_action`을 채우는 것이 곧 토큰 소진이므로, 같은 `force_log_id`로 두 번 보낼 수 없다 — 더블클릭이 메시지를 두 개 만들지 않는다.

   `judgment_logs`에는 이 검증을 위해 `user_id`가 필요하다. `judge()`가 로그를 만들 때 함께 기록한다.
3. 아니면 `verification_status`를 결정한다:
   - 발신자 토글 꺼짐 → `disabled`, 판정 없음
   - `degraded=True`이고 프로브 차례가 아님 → `degraded`, 판정 없음
   - 방 메시지 수 < `AI_CONTEXT_N` → `skipped_no_context`, 판정 없음
   - 그 외 → `judgment.judge()` 호출
4. 판정 결과 분기:
   - `appropriate` → `ok`, `user_action='auto_sent'`
   - `inappropriate` → **저장하지 않고** `Blocked` 반환
   - `failed` → `failed`, 그대로 전송 (FR-8.3)
5. 저장 트랜잭션: `SELECT rooms.last_seq FOR UPDATE` → `+1` → `messages` INSERT → `rooms.last_seq` UPDATE (FR-4.2)
6. 커밋 **후에** `ws_registry.push_to_users(참여자, 메시지)` (FR-4.1)
7. 판정 로그를 메시지에 연결

**5번과 6번의 순서가 FR-4.1의 전부다.** 브로드캐스트가 커밋 밖에 있어야 롤백된 메시지가 화면에 남지 않는다.

```python
async def list_messages(user_id: int, room_id: int, before: int | None, limit: int = 50) -> list[Message]
```
`seq` 내림차순. `before`가 있으면 그보다 작은 것만 (FR-4.4).
- 참여자가 아니면 `Forbidden`(403)
- `limit`은 상한 100으로 자른다

```python
async def report_misdirect(user_id: int, message_id: int) -> None
async def unreport_misdirect(user_id: int, message_id: int) -> None
```
- **발신자 본인만.** 남의 메시지면 `Forbidden`(403) — FR-11.1
- `misdirect_reported_at`을 설정/해제한다
- `verification_status`와 무관하게 모든 전송된 메시지에 가능 (FR-11.2)

---

## 프론트엔드

### `apiClient`

```ts
type SendOutcome =
  | { kind: 'sent';    message: Message }
  | { kind: 'blocked'; logId: number; score: number }

async function sendMessage(
  roomId: number, text: string,
  opts?: { forceLogId?: number; degraded?: boolean }
): Promise<SendOutcome>
```

409를 **예외로 던지지 않는다.** 정상 분기다. 네트워크 오류·5xx만 throw한다.

```ts
async function judgmentAction(logId: number, action: 'sent' | 'cancelled'): Promise<void>
async function reportMisdirect(messageId: number, on: boolean): Promise<void>
async function markRead(roomId: number, upToSeq: number): Promise<void>
```

### `wsClient`

```ts
function connect(token: string): void
```
연결 후 **첫 프레임으로** `{type: 'auth', token}`을 보낸다 (FR-1.3). 그 외에는 보내지 않는다.

수신 프레임:

| type | 내용 | 처리 |
|---|---|---|
| `auth_ok` | — | 연결 확립 표시 |
| `auth_error` | reason | 연결 종료, 재로그인 유도 |
| `message` | 메시지 객체 (`room_id` 포함) | `chatStore.receiveMessage()` |

### `chatStore` 주요 액션

```ts
receiveMessage(msg: Message): void
```
현재 보고 있는 방이면 목록에 추가하고 `markRead`를 호출한다. 아니면 `unread[roomId]`를 올리고 토스트를 띄운다 (FR-5.2, FR-5.3). **메시지 ID로 중복을 제거한다** — 낙관적 렌더링된 내 메시지가 브로드캐스트로 다시 올 수 있다 (FR-4.3).

```ts
enterRoom(roomId: number): Promise<void>
```
**구독이 먼저, 히스토리가 나중이다** (FR-3.3). WebSocket은 이미 연결되어 모든 방 메시지를 받고 있으므로, "구독"은 현재 방 포인터를 옮기는 것이다. 그 다음 히스토리를 fetch하고 ID로 병합한다.

```ts
markDegraded(): void
clearDegraded(): void
shouldProbe(): boolean
```
`shouldProbe()`는 degraded 중 전송 횟수를 세어 5번째마다 true를 반환한다 (FR-8.5).

## Assumptions & Open Questions

- `send_message`의 `degraded` 플래그를 클라이언트가 보낸다. 서버가 클라이언트의 상태를 신뢰하는 구조인데, degraded가 브라우저 탭 단위 상태(FR-8.3)라 서버가 알 방법이 없어서다. 악용 시 검증을 우회할 수 있으나 데모 범위에서 위협 모델에 없다.
- 프로브 차례 판단(`shouldProbe`)을 클라이언트가 한다. 같은 이유다.
- `resolve_display_names`가 친구가 아닌 참여자에게 계정 표시명을 쓰는 것은 FR-2.4의 문언을 넘는 해석이다. 대안은 "아이디만 표시"인데 읽기 어렵다. Functional Design에서 확정한다.
- `list_messages`의 `limit` 상한 100은 이 단계에서 정한 값이며 요구사항에 근거가 없다.

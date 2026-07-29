# Component Dependency — career-jikimi

`components.md`가 정의한 컴포넌트 사이의 의존 관계, 통신 방식, 데이터 흐름이다. Units Generation(2.7)이 이 그래프를 작업 단위 분해의 입력으로 쓴다.

## 의존 행렬 — 백엔드

읽는 법: **행이 열에 의존한다.**

| ↓의존 / 의존대상→ | config | db | ws_registry | auth | friends | rooms | messages | judgment |
|---|---|---|---|---|---|---|---|---|
| **config** | — | | | | | | | |
| **db** | ● | — | | | | | | |
| **ws_registry** | | | — | | | | | |
| **auth** | ● | ● | | — | | | | |
| **friends** | | ● | | ● | — | | | |
| **rooms** | | ● | | ● | ● | — | | |
| **messages** | ● | ● | ● | ● | ● | ● | — | ● |
| **judgment** | ● | ● | | | | | | — |

**순환이 없다.** 위상 정렬하면 `config → db → {ws_registry, auth} → friends → rooms → judgment → messages`. `messages`가 `friends`에 직접 의존하는 간선이 추가되었으나 순서는 그대로다.

`messages`가 가장 많이 의존한다 — 전송 경로 전체를 오케스트레이션하기 때문이다. 이것은 의도된 것이며, 그 대신 다른 모듈이 서로를 참조하지 않는다.

### 주목할 의존 관계

**`rooms → friends`** — 참여자 표시명을 해석하려면 별칭이 필요하다(FR-2.4). 표시명 규칙을 두 곳에 두지 않기 위해 `friends.resolve_display_names()`를 호출한다.

**`messages → rooms`** — `get_membership()`으로 참여자 자격과 `ai_check_enabled`(FR-6.1)를 한 번에 확인하고, `member_user_ids()`로 브로드캐스트 대상을 얻는다. 그리고 `rooms.last_seq`를 증가시킨다.

**`messages → friends`** — 히스토리 응답에 발신자 표시명을 실으려면 별칭 해석이 필요하다(FR-2.4). `rooms`를 거치지 않고 `friends.resolve_display_names()`를 직접 부른다 — `rooms`를 경유하면 `rooms`가 메시지 표현을 알게 되어 경계가 흐려진다.

> `rooms`가 `last_seq`를 소유하는데 `messages`가 그것을 쓰는 것은 소유권 위반처럼 보인다. 실제로 그렇고, 의도적이다 — 채번이 메시지 저장과 **같은 트랜잭션 안에** 있어야 하기 때문이다(FR-4.2). 트랜잭션을 나누면 seq가 중복되거나 구멍이 생긴다. 근거는 ADR-003.

**`messages → judgment`** — 판정 호출. `messages`는 `JudgeResult`의 세 갈래만 알고 프롬프트·모델·스키마는 모른다.

**`judgment`가 아무에게도 의존하지 않는 것**(config·db 제외)이 중요하다. 판정 로직을 다른 모듈에서 떼어내 단독으로 테스트하고 실험할 수 있다. 이 프로젝트가 공들이는 곳이므로 그 격리가 값어치가 있다.

**`ws_registry`가 아무것도 의존하지 않는 것** — 나중에 Redis pub/sub으로 교체할 때 이 격리가 교체 비용을 결정한다.

## 의존 그래프 — 백엔드

```
                     config
                       |
          +------------+------------+
          |                         |
          v                         v
         db                    ws_registry
          |                         |
     +----+----+                    |
     |         |                    |
     v         v                    |
   auth    judgment                 |
     |         |                    |
     v         |                    |
  friends      |                    |
     |         |                    |
     v         |                    |
   rooms       |                    |
     |         |                    |
     +----+----+--------------------+
          |
          v
       messages
       (friends에도 직접 의존)
```

<!-- Text fallback: config가 최상위이며 db와 ws_registry가 그에 의존한다. db 위에 auth와 judgment가 선다. auth 위에 friends, friends 위에 rooms가 선다. 최하위의 messages가 rooms, friends, judgment, ws_registry, auth, db, config 모두에 의존한다. 순환은 없다. -->

## 통신 방식

컴포넌트 간 호출은 **전부 동기 함수 호출**이다. 이벤트 버스도, 메시지 큐도 없다(CON-2).

| 경계 | 방식 | 이유 |
|---|---|---|
| 컴포넌트 ↔ 컴포넌트 | 동기 async 함수 호출 | 같은 프로세스 안이다. 추상화를 더할 이유가 없다 |
| `app` ↔ 브라우저 (전송) | HTTP 요청/응답 | 요청-응답 의미가 필요하다 (ADR-001) |
| `app` → 브라우저 (푸시) | WebSocket | 서버가 먼저 말해야 한다 |
| `app` ↔ DB | 동기 async (SQLAlchemy) | — |
| `app` → OpenAI | 동기 async HTTP | 전송 전 차단이므로 기다려야 한다 |

**유일한 비동기 지점은 WebSocket 푸시다.** 브로드캐스트는 응답을 기다리지 않고, 연결이 없는 사용자는 조용히 건너뛴다.

## 데이터 흐름 — 메시지 전송 (핵심 경로)

```
[브라우저]
   |
   | 1. POST /rooms/{id}/messages  { text }
   v
[messages.send_message]
   |
   |-- 2. rooms.get_membership()        → 참여자 자격 + ai_check_enabled
   |      rooms.member_user_ids()      → 브로드캐스트 대상 (6번에서 사용)
   |
   |-- 3. messages.list recent N       → 문맥 조회 (판정 필요한 경우)
   |
   |-- 4. judgment.judge()             → OpenAI 호출 (트랜잭션 밖!)
   |        |                             3~5초, 재시도 1회
   |        +-- judgment_logs INSERT
   |
   |   +-- inappropriate → 409 { log_id, score }  ─────┐  저장 안 함
   |   |                                               |
   |   +-- appropriate / failed / (판정 안 함)          |
   |        |                                          |
   |-- 5. BEGIN TRANSACTION                            |
   |      SELECT rooms.last_seq FOR UPDATE             |
   |      INSERT messages (seq = last_seq + 1)         |
   |      UPDATE rooms.last_seq                        |
   |      COMMIT                                       |
   |                                                   |
   |-- 6. ws_registry.push_to_users(참여자, 메시지)     |
   |                                                   |
   +-- 7. 201 { message }                              |
                                                       |
[브라우저] ←────────────────────────────────────────────┘
   |
   | 409를 받으면: 확인 팝업
   |    "보내기" → POST 재요청 { text, force_log_id }  → 위 5~7번
   |    "취소"   → PATCH /judgments/{log_id} { user_action: cancelled }
   v
```

<!-- Text fallback: 브라우저가 HTTP POST로 메시지를 보내면, messages 모듈이 get_membership으로 참여자 자격과 검증 토글을 확인하고, 필요하면 최근 N개 문맥을 조회해 judgment 모듈로 판정을 요청한다. 판정은 DB 트랜잭션 밖에서 일어나며 판정 로그를 남긴다. 부적절이면 저장하지 않고 409를 반환하고, 그 외에는 트랜잭션 안에서 seq를 채번해 저장한 뒤 커밋하고, 커밋 후에 WebSocket으로 브로드캐스트하고 201을 반환한다. 브라우저가 409를 받으면 확인 팝업을 띄우고, 보내기를 고르면 force_log_id를 붙여 재요청하며, 취소를 고르면 판정 로그의 user_action만 갱신한다. -->

**4번이 5번보다 먼저이고 트랜잭션 밖인 것**이 이 흐름의 핵심 설계다. LLM 호출을 잠금 안에 넣으면 그 방의 모든 전송이 3~5초씩 막힌다.

**6번이 커밋 뒤인 것**이 FR-4.1의 전부다.

## 데이터 흐름 — 메시지 수신

```
[다른 사용자의 전송] → [ws_registry.push_to_users]
                              |
                              v
                      [브라우저 wsClient]
                              |
                              v
                    [chatStore.receiveMessage]
                              |
              +---------------+---------------+
              |                               |
     현재 보고 있는 방                    다른 방
              |                               |
              v                               v
      메시지 목록에 추가                unread[roomId] += 1
      markRead() 호출                   토스트 표시
              |
              v
      (ID로 중복 제거 — 낙관적 렌더링된 내 메시지가
       브로드캐스트로 다시 올 수 있다)
```

<!-- Text fallback: 다른 사용자가 전송하면 ws_registry가 참여자들에게 푸시하고, 브라우저의 wsClient가 받아 chatStore.receiveMessage를 호출한다. 현재 보고 있는 방이면 메시지 목록에 추가하고 읽음 처리를 하며, 다른 방이면 안 읽은 개수를 올리고 토스트를 띄운다. 메시지 ID로 중복을 제거해 낙관적 렌더링된 자기 메시지가 두 번 보이지 않게 한다. -->

## 공유 자원

| 자원 | 공유하는 컴포넌트 | 경합 지점 |
|---|---|---|
| `rooms.last_seq` 행 | `messages`(쓰기), `rooms`(읽기) | **`FOR UPDATE` 잠금.** 같은 방의 동시 전송이 직렬화된다. 다른 방은 영향 없음 |
| DB 커넥션 풀 | 전부 | 데모 규모에서 경합 없음 |
| `ws_registry` dict | `messages`(푸시), WS 엔드포인트(등록/해제) | 단일 프로세스 + async 단일 스레드라 잠금 불필요. **멀티 워커가 되면 이 가정이 깨진다** (CON-1) |
| OpenAI API rate limit | `judgment` | 데모 규모에서 문제 없으나, 부하 테스트를 한다면 여기가 먼저 막힌다 |

## 프론트엔드 의존

```
   AuthView   FriendsView   RoomListView   ChatView
      |            |             |            |
      +------------+------+------+------------+
                          |
                     chatStore
                     (Zustand)
                     |        |
              apiClient    wsClient
                     |        |
                    HTTP      WS
```

<!-- Text fallback: 네 개의 뷰가 모두 chatStore에 의존하고, chatStore가 apiClient와 wsClient에 의존한다. 뷰끼리는 서로 의존하지 않는다. -->

**뷰끼리 의존하지 않는다.** 모든 상태 공유는 `chatStore`를 거친다.

`wsClient`는 `chatStore`를 직접 갱신한다 — Zustand의 `getState()`가 컴포넌트 밖에서도 동작하기 때문이며, 이것이 Context 대신 Zustand를 고른 이유다(ADR-004).

## Units Generation을 위한 절단선

이 그래프에서 자연스러운 작업 단위 경계는 다음과 같다. 확정은 2.7의 몫이다.

| 후보 단위 | 포함 | 선행 조건 |
|---|---|---|
| 기반 | `config`, `db`, 스키마, Alembic, 컨테이너 | 없음 |
| 인증 | `auth` + `AuthView` | 기반 |
| 친구 | `friends` + `FriendsView` | 인증 |
| 방·연결 | `rooms`, `ws_registry` + `RoomListView` | 인증, 친구 |
| 전송 | `messages`(판정 제외) + `ChatView` 기본 | 방·연결 |
| 판정 | `judgment` + 확인 팝업 + 배지 | 전송 |
| 실패 처리 | degraded·프로브 + 팝업 | 판정 |
| 신고·지표 | FR-11 + `compute_metrics` | 판정 |

**walking skeleton은 이 표를 세로로 관통하는 가장 얇은 선이다** — 기반의 최소 테이블, 인증의 로그인 하나, 방 하나, 전송 한 건, 판정 한 번. 그리고 그 전부가 컨테이너 안에서 돈다.

## Assumptions & Open Questions

- `rooms → friends` 의존이 `resolve_display_names`를 위한 것인데, 방 참여자가 많으면 N+1 조회가 될 수 있다. 데모 규모에서는 문제없으나 구현 시 일괄 조회로 짜야 한다.
- 프론트엔드에서 `chatStore`가 커지면 슬라이스를 파일로 나눠야 한다. 지금은 하나로 두고 커지면 나눈다.
- 위 "절단선" 표는 제안이며 Units Generation이 확정한다. 특히 판정과 실패 처리를 한 단위로 합칠지 나눌지가 열려 있다.

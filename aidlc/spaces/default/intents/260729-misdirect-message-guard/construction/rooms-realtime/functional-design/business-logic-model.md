# Business Logic Model — rooms-realtime

`../../../inception/units-generation/unit-of-work.md`의 U4가 수행하는 흐름이다. 배정은 `../../../inception/units-generation/unit-of-work-story-map.md`, 요구사항은 `../../../inception/requirements-analysis/requirements.md`의 FR-1.3·FR-3.1~FR-3.3·FR-5.1~FR-5.4·FR-6.1·FR-10, 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 서명은 `../../../inception/application-design/component-methods.md`, 프로세스·통신 형태는 `../../../inception/application-design/services.md`가 정한다.

규칙 번호(`BR-*`)는 같은 디렉터리의 `business-rules.md`를, 테이블은 `domain-entities.md`를 가리킨다.

## W1 · 방 생성

```
[요청: friend_user_ids[], name?]
   |
   |-- 1. 비어 있나? --------------- 예 --> 400 EMPTY_ROOM        (BR-3.1)
   |
   |-- 2. 전부 내 친구인가?
   |      friends.list_friends(me) 와 대조
   |        |
   |        +-- 아님 --> 400 NOT_A_FRIEND                          (BR-3.2)
   |
   |-- 3. BEGIN
   |      INSERT rooms (name, last_seq=0, created_by=me)
   |      INSERT room_members × (me + 초대 대상)
   |          ai_check_enabled=TRUE, last_read_seq=0               (BR-6.2)
   |      COMMIT
   |
   +-- 4. 201 { room }
```

<!-- Text fallback: 방 생성은 초대 대상이 비었는지, 전부 친구인지 확인한 뒤 하나의 트랜잭션 안에서 rooms와 room_members를 INSERT한다. 모든 참여자의 AI 검증 토글은 TRUE로, 읽음 위치는 0으로 초기화된다. -->

**한 트랜잭션이다.** 방만 만들어지고 참여자가 안 들어가면 아무도 접근할 수 없는 유령 방이 남는다.

친구 확인은 **한 번의 조회**로 한다. `friend_user_ids`를 순회하며 개별 확인하지 않는다.

## W2 · 방 목록

```
[요청]
   |
   |-- 1. SELECT rooms JOIN room_members WHERE user_id = me
   |
   |-- 2. 방별 안 읽은 개수
   |      SELECT room_id, COUNT(*) FROM messages
   |       WHERE room_id IN (...) AND seq > (그 방의 last_read_seq)
   |      → 한 번의 쿼리로 전부                                    (BR-5.1)
   |
   |-- 3. 참여자 표시명
   |      friends.resolve_display_names(me, 전체 참여자 id)
   |      → 한 번의 호출로 전부
   |
   +-- 4. 200 [ { room, unread_count, members[] } ]
```

<!-- Text fallback: 방 목록은 내가 속한 방을 조회하고, 안 읽은 개수를 한 번의 쿼리로 방별 집계하고, 참여자 표시명을 한 번의 호출로 해석한 뒤 합쳐서 반환한다. -->

**2번과 3번이 각각 한 번씩이다.** 방마다 반복하면 N+1이 된다 (`component-dependency.md`의 열린 항목).

안 읽은 개수 쿼리는 방마다 다른 `last_read_seq`와 비교해야 하므로 `room_members`와 조인한다:

```sql
SELECT rm.room_id, COUNT(m.id) AS unread
  FROM room_members rm
  LEFT JOIN messages m
    ON m.room_id = rm.room_id AND m.seq > rm.last_read_seq
 WHERE rm.user_id = ?
 GROUP BY rm.room_id
```

`LEFT JOIN`이라 메시지가 없는 방도 0으로 나온다.

## W3 · 방 상세

```
[요청: room_id]
   |
   |-- 1. get_membership(me, room_id)
   |        |
   |        +-- None --> 403 FORBIDDEN                             (BR-3.3)
   |
   |-- 2. 참여자 목록 + resolve_display_names()
   |
   +-- 3. 200 { room, members[], ai_check_enabled, last_read_seq }
```

<!-- Text fallback: 방 상세는 참여자 자격을 확인하고 없으면 403을 낸다. 통과하면 참여자 표시명을 해석해 방 정보, 참여자 목록, 호출자의 토글 상태와 읽음 위치를 반환한다. -->

**존재하지 않는 방도 403이다** (BR-3.3). `get_membership()`이 `None`을 주는 두 경우를 구분하지 않는다.

응답에 호출자 본인의 `ai_check_enabled`가 들어간다 — 화면의 토글이 그 값으로 그려진다. **다른 참여자의 토글 상태는 넣지 않는다.** 개인 설정이며 남이 알 필요가 없다.

## W4 · 읽음 처리

```
mark_read(user_id, room_id, up_to_seq)

UPDATE room_members
   SET last_read_seq = ?
 WHERE room_id = ? AND user_id = ? AND last_read_seq < ?    ← 조건이 핵심
   |
   +-- 영향 행 0 --> 이미 더 앞서 있음. 200 (오류 아님)     (BR-5.3)
   +-- 영향 행 1 --> 200
```

<!-- Text fallback: 읽음 처리는 조건부 UPDATE로 한다. 현재 값보다 큰 경우에만 갱신하며, 영향받은 행이 0이어도 오류가 아니라 정상 응답이다. -->

**`last_read_seq < ?` 조건이 전진만을 보장한다** (BR-5.3). 사용자가 방을 빠르게 오갈 때 순서가 뒤바뀐 요청이 실제로 들어오며, 조건이 없으면 배지가 되살아난다.

## W5 · WebSocket 수명주기

```
[연결 수립]
   |
   |-- 5초 타이머 시작
   |
   |-- 첫 프레임 수신 대기
   |     |
   |     +-- 타임아웃 -----------------> 연결 종료               (BR-5.6)
   |     +-- type != 'auth' -----------> auth_error → 종료
   |     +-- type == 'auth'
   |           |
   |           +-- verify_token() 실패 --> auth_error → 종료
   |           |
   |           +-- 성공
   |                 |
   |                 |-- 기존 연결 있나?
   |                 |     |
   |                 |     +-- 예 --> 기존에 session_replaced 전송
   |                 |                --> 기존 닫기              (BR-5.4)
   |                 |
   |                 |-- 레지스트리에 등록
   |                 |
   |                 +-- auth_ok 전송
   |
   |-- 수신 루프 (사실상 대기만 한다 — 클라이언트는 더 보내지 않는다)
   |
   +-- [연결 종료] --> unregister
```

<!-- Text fallback: WebSocket은 연결 후 5초 안에 auth 프레임을 받아야 하며, 실패하면 auth_error를 보내고 끊는다. 성공하면 같은 사용자의 기존 연결에 session_replaced를 보내 닫고 새 연결을 등록한 뒤 auth_ok를 보낸다. 이후에는 서버가 밀어내기만 하고 클라이언트는 더 보내지 않는다. 연결이 끊기면 레지스트리에서 제거한다. -->

**`session_replaced`를 보내고 닫는 순서가 중요하다** (BR-5.4). 그냥 닫으면 밀려난 탭이 네트워크 오류로 오인해 재연결하고, 두 탭이 서로를 밀어내는 순환이 생긴다.

**인증 후 수신 루프는 사실상 비어 있다.** 전송이 HTTP이기 때문이다(ADR-001). 루프는 연결 종료를 감지하는 용도다.

## 알고리즘: 브로드캐스트

`push_to_users(user_ids, payload)`

```
for user_id in user_ids:
    ws = _connections.get(user_id)
    if ws is None:
        continue                    ← 오프라인. 오류 아님        (BR-5.7)
    try:
        await ws.send_json(payload)
    except (연결 끊김 등):
        unregister(user_id)         ← 죽은 소켓 정리
        continue                    ← 나머지는 계속
```

<!-- Text fallback: 브로드캐스트는 대상 사용자마다 레지스트리에서 소켓을 찾아 보낸다. 소켓이 없으면 오프라인이므로 건너뛰고, 전송 중 실패하면 그 사용자를 레지스트리에서 제거한 뒤 나머지에게 계속 보낸다. -->

**try를 루프 안에 둔다.** 밖에 두면 한 소켓의 실패가 나머지 참여자의 수신을 막는다.

**발신자에게도 보낸다** (BR-5.8) — 다른 탭·기기의 세션이 갱신되어야 한다. 중복은 클라이언트가 ID로 제거한다.

## 프론트엔드

이 단위는 `RoomListView`·`wsClient`·`ToastHost`와 `chatStore`의 rooms·unread·toasts 슬라이스를 포함한다. `kind: service`라 `frontend-components.md`가 산출물에서 제외되어 여기에 적는다.

### `wsClient`

```js
connect(token) {
  ws = new WebSocket(WS_URL)
  ws.onopen  = () => ws.send(JSON.stringify({ type: 'auth', token }))
  ws.onmessage = (e) => route(JSON.parse(e.data))
  ws.onclose = () => { if (!replaced) scheduleReconnect() }
}

route(frame) {
  auth_ok          -> 연결 확립 표시
  auth_error       -> 재로그인 유도
  session_replaced -> replaced = true; 배너 표시; 재연결 안 함   (BR-5.5)
  message          -> chatStore.getState().receiveMessage(frame)
}
```

<!-- Text fallback: wsClient는 연결 직후 auth 프레임을 보내고, 수신 프레임을 타입별로 분배한다. session_replaced를 받으면 replaced 플래그를 세워 재연결을 막고 배너를 띄운다. message 프레임은 chatStore로 넘긴다. -->

**`replaced` 플래그가 재연결을 막는 장치다.** 이게 없으면 밀려난 탭이 다시 붙어 순환한다.

Zustand의 `getState()`로 컴포넌트 밖에서 스토어를 갱신한다 (ADR-004).

### `chatStore.receiveMessage(msg)`

```
현재 보고 있는 방인가?
  |
  +-- 예 --> 메시지 목록에 추가 (ID로 중복 제거)
  |          markRead(방, msg.seq) 호출
  |
  +-- 아니오 --> unread[room_id] += 1                            (BR-5.9)
                토스트 추가
```

<!-- Text fallback: 수신한 메시지가 현재 보고 있는 방이면 목록에 추가하고 읽음 처리를 호출한다. 다른 방이면 안 읽은 개수를 올리고 토스트를 띄운다. -->

**중복 제거가 필수다** — 내가 보낸 메시지는 HTTP 응답과 WebSocket 푸시 양쪽으로 온다 (BR-5.8, FR-4.3).

### `RoomListView`

| 영역 | 내용 |
|---|---|
| 목록 | 방 이름(없으면 참여자 표시명 조립) + 안 읽은 배지 |
| 배지 | 0이면 표시 안 함 |
| 생성 | 친구 다중 선택 + 방 이름(선택) |
| 비어 있음 | "채팅방이 없습니다. 친구를 초대해 만들어보세요." |
| 배너 | `session_replaced` 시 상단 고정 |

### `ToastHost`

`aria-live="polite"` 영역에 렌더링한다 — 스크린리더가 새 메시지 도착을 읽는다.

클릭 시 그 방으로 이동하고 배지가 사라진다 (BR-5.9).

### 접근성

| 요소 | 요구 |
|---|---|
| 안 읽은 배지 | 숫자만 두지 않고 `aria-label="안 읽은 메시지 3개"` |
| 토스트 | `aria-live="polite"`, 자동 소멸이라 focus를 뺏지 않는다 |
| 배너 | `role="status"` |
| 방 목록 | 리스트 시맨틱(`<ul>`/`<li>`), 각 항목은 링크 또는 버튼 |
| 토글 | `<input type="checkbox">` + 보이는 라벨. div로 만들지 않는다 |

### 자동화 훅

`data-testid` — `room-list`, `room-list-item-{id}`, `room-unread-badge-{id}`, `room-create-open`, `room-create-submit`, `room-ai-toggle`, `toast-{roomId}`, `session-replaced-banner`.

## 테스트 대상 (NFR-7)

이 단위가 지는 테스트 의무는 하나다.

| 대상 | 무엇을 검증 |
|---|---|
| 구독·fetch 순서와 중복 제거 (FR-3.3) | 방 입장 중(포인터 이동 후 히스토리 응답 전) 도착한 메시지가 유실되지 않는가. 히스토리와 구독 스트림에 같은 메시지가 있어도 한 번만 표시되는가 |

히스토리 조회 API 자체는 U5 소관이므로, 이 테스트는 **클라이언트 측 병합 로직**을 대상으로 한다.

## Assumptions & Open Questions

- WebSocket 재연결 백오프(간격, 최대 시도)가 정해지지 않았다. `session_replaced`가 아닌 단절에는 재연결해야 하는데 정책이 없다.
- `rooms.name`이 NULL일 때 참여자 표시명을 몇 명까지 나열할지 정하지 않았다.
- 토스트 표시 시간과 동시 표시 상한이 정해지지 않았다.
- 방 목록의 안 읽은 개수 쿼리가 `LEFT JOIN` + `GROUP BY`인데, 메시지가 많아지면 느려진다. `(room_id, seq)` 인덱스가 있어 데모 규모에서는 문제없다.

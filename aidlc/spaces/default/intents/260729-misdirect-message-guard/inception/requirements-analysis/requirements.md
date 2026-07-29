# Requirements — career-jikimi

## Intent Analysis

`../../ideation/intent-capture/intent-statement.md`가 정한 목표는 하나다: **채팅방을 착각해 보낸 메시지가 상대에게 도달하기 전에 막는 것.** 도달 후의 회수나 사과가 아니라 전송 전 차단이며, 판단 근거는 대화 문맥이다.

`../../ideation/scope-definition/scope-document.md`가 그 목표를 경계로 옮겼다 — 판정 경로(메시지 저장·문맥 조회·판정 로그)에 노력을 몰아주고, 인증·친구·방은 사슬이 끊기지 않을 만큼만 얕게 만든다. `../../ideation/scope-definition/intent-backlog.md`가 이를 proto-Unit 11개로 폈다.

팀 관행(`team-practices`)은 이 워크플로가 `practices-discovery` 단계를 건너뛰었으므로 확립되지 않았다. 활성 공간의 `team.md`와 `project.md`의 관행 절은 비어 있고 `org.md`의 프레임워크 기본값이 적용된다 — trunk-based 개발, 테스트를 Bolt마다 1급 산출물로 취급, 린터·포매터는 프로젝트 설정에 위임. NFR-7이 그 기본값을 이 프로젝트의 맥락으로 좁힌다.

이 문서는 그 경계를 **통과/실패를 판정할 수 있는 요구사항**으로 바꾼다. 각 요구사항은 Given/When/Then 수용 기준을 갖는다.

우선 지표는 **precision**이다. 이 선택이 요구사항 곳곳에 나타난다 — 판정 임계값을 설정값으로 뺀 것(FR-6.3), `user_action`을 라벨로 기록하는 것(FR-7.2), 성능 집계를 판정 로그 위에 정의한 것(FR-7.4)이 모두 "오탐을 줄이고 그 효과를 측정한다"는 한 방향을 향한다.

## 표기

- **Must / Should** — `scope-document.md`의 MoSCoW 등급을 따른다.
- 요구사항 ID는 `FR-<영역>.<번호>` / `NFR-<번호>` / `CON-<번호>`.

| 태그 | 출처 |
|---|---|
| `[IS]` | `../../ideation/intent-capture/intent-statement.md` |
| `[SD]` | `../../ideation/scope-definition/scope-document.md` |
| `[BL]` | `../../ideation/scope-definition/intent-backlog.md` |
| `[SD-Q<n>]` | `../../ideation/scope-definition/scope-definition-questions.md`의 답변 |
| `[Q<n>]` | 이 단계 `requirements-analysis-questions.md`의 답변 |
| `[dec]` | **이 단계에서 새로 정한 값.** 상류 출처가 없으며 ASM-5에 모아두었다 |

---

## Functional Requirements

### FR-1 인증 (Must)

**FR-1.1** 시스템은 아이디와 비밀번호로 회원가입을 받는다. 비밀번호는 bcrypt 또는 argon2로 해싱해 저장한다. 평문 저장은 허용하지 않는다. 비밀번호 최소 길이는 8자다. `[SD]` `[dec]`(8자)

```
Given 미가입 아이디 "alice"와 비밀번호 "pw123456"
When 회원가입을 요청하면
Then 계정이 생성되고, DB의 password 컬럼은 평문 "pw123456"과 일치하지 않는다

Given 이미 존재하는 아이디 "alice"
When 같은 아이디로 회원가입을 요청하면
Then 409를 반환하고 계정은 생성되지 않는다

Given 비밀번호가 7자다
When 회원가입을 요청하면
Then 400을 반환하고 계정은 생성되지 않는다
```

**FR-1.2** 로그인 성공 시 JWT를 발급한다. 리프레시 토큰과 자동 만료 갱신은 만들지 않는다. `[SD]`

```
Given 가입된 계정의 올바른 아이디·비밀번호
When 로그인을 요청하면
Then JWT가 반환되고, 그 토큰으로 보호된 엔드포인트에 접근할 수 있다

Given 틀린 비밀번호
When 로그인을 요청하면
Then 401을 반환하고 토큰을 발급하지 않는다
```

**FR-1.3** WebSocket 연결은 **연결 직후 첫 프레임으로 전달된 auth 토큰**으로 인증한다. 인증 프레임을 받기 전에 도착한 다른 메시지는 처리하지 않고, 5초 안에 인증 프레임이 오지 않으면 연결을 종료한다. `[Q3]` `[dec]`(5초)

```
Given WebSocket 연결이 수립되었고 아직 인증 프레임을 보내지 않았다
When 메시지 전송 프레임을 보내면
Then 서버는 그 메시지를 처리하지 않고 인증 요구 오류를 반환한다

Given WebSocket 연결이 수립되었다
When 5초 동안 인증 프레임을 보내지 않으면
Then 서버가 연결을 종료한다

Given 유효한 JWT를 첫 프레임으로 보냈다
When 인증이 성공하면
Then 이후 프레임이 정상 처리되고, 해당 사용자의 연결로 레지스트리에 등록된다
```

**FR-1.4** 비밀(JWT 서명 키, DB 접속 정보, OpenAI API 키)은 환경변수로 주입한다. 소스 코드에 하드코딩하지 않는다. `[SD]`

```
Given 저장소 전체
When 소스 코드를 검색하면
Then API 키·비밀번호·서명 키에 해당하는 리터럴 문자열이 존재하지 않는다
```

### FR-2 친구 (Must)

**FR-2.1** 아이디 **정확 일치** 검색으로만 친구를 찾는다. 부분 일치 검색·목록 정렬·승인 절차는 만들지 않는다. `[SD-Q3]` `[SD]`

```
Given 아이디가 "alice"인 사용자가 존재한다
When "alice"로 검색하면
Then 해당 사용자 한 명이 반환된다

Given 아이디가 "alice"인 사용자가 존재한다
When "ali"로 검색하면
Then 결과가 비어 있다
```

**FR-2.2** 친구 등록은 **단방향 즉시 등록**이며, **별칭 입력이 필수**다. 별칭 없는 등록 요청은 거절한다. `[IS]` `[SD]`

```
Given 검색으로 찾은 상대 아이디와 별칭 "회사 김대리"
When 친구 등록을 요청하면
Then 승인 대기 없이 즉시 친구 목록에 나타나고 별칭이 "회사 김대리"로 저장된다

Given 별칭이 비어 있거나 공백만 있다
When 친구 등록을 요청하면
Then 400을 반환하고 친구는 등록되지 않는다

Given A가 B를 친구로 등록했다
When B의 친구 목록을 조회하면
Then A는 포함되지 않는다 (단방향)
```

**FR-2.3** 등록 이후 별칭을 수정할 수 있다. 수정 시에도 빈 값은 허용하지 않는다. `[IS]`

```
Given 별칭이 "회사 김대리"인 친구가 있다
When 별칭을 "김철수 팀장"으로 수정하면
Then 친구 목록에 "김철수 팀장"으로 표시된다

Given 별칭이 있는 친구가 있다
When 별칭을 빈 문자열로 수정하려 하면
Then 400을 반환하고 기존 별칭이 유지된다
```

**FR-2.4** 친구 목록과 방 참여자 표시에는 상대가 스스로 설정한 이름이 아니라 **내가 붙인 별칭만** 표시된다. `[IS]`

```
Given B의 계정 표시명이 "bob"이고 A가 B에게 붙인 별칭이 "회사 김대리"다
When A가 친구 목록을 조회하면
Then "회사 김대리"가 표시되고 "bob"은 어디에도 표시되지 않는다

Given 같은 조건에서 A와 B가 같은 방에 있다
When A가 방의 참여자 목록을 보면
Then B는 "회사 김대리"로 표시된다
```

### FR-3 채팅방 (Must)

**FR-3.1** 친구를 다수 선택해 방을 만든다. 방은 **본인 포함 최소 2명**이며 상한은 없다. `[Q6]`

```
Given 친구가 2명 있다
When 그중 1명을 선택해 방을 만들면
Then 본인 포함 2명인 방이 생성된다

Given 친구를 한 명도 선택하지 않았다
When 방 생성을 요청하면
Then 400을 반환하고 방은 생성되지 않는다

Given 친구가 아닌 사용자의 id를 참여자로 지정했다
When 방 생성을 요청하면
Then 400을 반환하고 방은 생성되지 않는다
```

**FR-3.2** 사용자는 자신이 속한 방 목록을 조회할 수 있다. 정렬 순서는 규정하지 않는다. `[SD]`

```
Given 사용자가 방 2개에 속해 있고 속하지 않은 방이 1개 더 있다
When 방 목록을 조회하면
Then 속한 방 2개만 반환되고 속하지 않은 방은 포함되지 않는다

Given 사용자가 어떤 방에도 속해 있지 않다
When 방 목록을 조회하면
Then 빈 목록이 반환된다 (오류가 아니다)
```

**FR-3.3** 방에 입장하면 **구독을 먼저 걸고 그 다음에 히스토리를 가져온다.** 겹치는 메시지는 메시지 ID로 중복 제거한다. `[SD]`

```
Given 방에 입장하는 중이다
When 구독 완료 시점과 히스토리 응답 도착 시점 사이에 새 메시지가 도착하면
Then 그 메시지가 화면에 나타나고 유실되지 않는다

Given 히스토리 응답과 구독 스트림에 같은 메시지가 모두 포함되었다
When 화면을 렌더링하면
Then 그 메시지는 한 번만 표시된다
```

### FR-4 메시지 전송과 순서 (Must)

**FR-4.1** 메시지는 **DB 저장을 완료한 뒤에** 방 참여자에게 브로드캐스트한다. 순서를 뒤집지 않는다. `[SD]`

```
Given DB INSERT가 실패하는 상황
When 메시지를 전송하면
Then 어떤 참여자에게도 브로드캐스트되지 않고 발신자는 실패를 통보받는다
```

**FR-4.2** 메시지 정렬 기준은 `created_at`이 아니라 **`(room_id, seq)`** 다. `seq`는 방 안에서 단조 증가하며, 한 트랜잭션 안에서 `SELECT last_seq ... FOR UPDATE` → `+1` → INSERT로 채번한다. `[SD]`

```
Given 같은 방에 두 사용자가 동시에 메시지를 보낸다
When 두 전송이 동시에 처리되면
Then 두 메시지의 seq는 서로 다르고 연속하며, 모든 참여자가 같은 순서로 본다

Given 서로 다른 두 방에 동시에 메시지가 전송된다
When 두 전송이 처리되면
Then 한 방의 채번이 다른 방의 전송을 지연시키지 않는다
```

**FR-4.3** 클라이언트는 임시 ID로 낙관적 렌더링을 하고, 서버 ack에 담긴 실제 ID·`seq`로 교체한다. `[SD]`

```
Given 사용자가 메시지를 전송했다
When 서버 ack가 아직 오지 않았다
Then 메시지는 임시 상태로 화면에 보인다

Given 서버 ack가 도착했다
When 클라이언트가 처리하면
Then 임시 메시지가 실제 ID·seq를 가진 메시지로 교체되고 중복 표시되지 않는다
```

**FR-4.4** 히스토리는 `GET /rooms/{id}/messages?before=<seq>&limit=50` 형태의 **seq 커서 페이지네이션**으로 가져온다. `[SD]`

```
Given 방에 메시지가 120개 있다
When before 없이 조회하면
Then 가장 최근 50개가 seq 내림차순으로 반환된다

Given 앞선 응답의 가장 오래된 seq가 71이다
When before=71로 조회하면
Then seq 70 이하의 메시지 50개가 반환되고 71은 포함되지 않는다
```

### FR-5 새 메시지 알림 (Must)

**FR-5.1** WebSocket 연결은 **사용자당 1개**를 유지하고, payload의 `room_id`로 여러 방을 멀티플렉싱한다. 방마다 연결을 새로 열지 않는다. `[SD]`

```
Given 사용자가 방 3개에 속해 있다
When 앱을 열고 방 하나에 입장하면
Then 서버의 연결 레지스트리에 그 사용자의 연결은 1개만 등록된다

Given 사용자가 방 A를 보고 있다
When 방 B에 메시지가 도착하면
Then 같은 연결로 room_id=B인 메시지 프레임이 전달된다
```

**FR-5.2** 사용자가 보고 있지 않은 방에 메시지가 도착하면, 방 목록의 **안 읽은 개수 배지**가 증가한다. 안 읽은 개수는 `room_members.last_read_seq`보다 큰 `seq`를 가진 메시지 수다. `[Q8]`

```
Given 사용자가 방 A를 보고 있고 방 B의 last_read_seq는 10이다
When 방 B에 seq 11, 12 메시지가 도착하면
Then 방 목록의 방 B에 안 읽은 개수 2가 표시된다

Given 방 B에 안 읽은 메시지가 2개 있다
When 사용자가 방 B에 입장하면
Then last_read_seq가 갱신되고 배지가 사라진다
```

**FR-5.3** 보고 있지 않은 방에 메시지가 도착하면 앱 내 토스트를 표시하고, 토스트를 누르면 해당 방으로 이동한다. `[Q8]`

```
Given 사용자가 방 A를 보고 있다
When 방 B에 메시지가 도착하면
Then 토스트가 표시되고 그 안에 방 B의 이름이 보인다

Given 방 B에 대한 토스트가 표시되어 있다
When 토스트를 클릭하면
Then 방 B로 이동하고 방 B의 배지가 사라진다

Given 사용자가 방 A를 보고 있다
When 방 A에 메시지가 도착하면
Then 토스트가 표시되지 않는다 (이미 보고 있는 방이다)
```

**FR-5.4** 알림은 **앱이 브라우저 탭에 열려 있는 동안**만 동작한다. 브라우저를 닫은 상태의 푸시 알림은 제공하지 않는다. `[Q8]`

### FR-6 AI 검증 판정 (Must)

**FR-6.1** AI 검증 토글은 **참여자 개인 단위**(`room_members.ai_check_enabled`)이며, 신규 방의 기본값은 켜짐이다. 한 참여자의 설정이 다른 참여자의 전송에 영향을 주지 않는다. `[IS]`

```
Given 방에 A와 B가 있고 A는 검증 켜짐, B는 꺼짐
When B가 메시지를 보내면
Then 판정 없이 즉시 전송되고 verification_status는 disabled다

Given 같은 방에서 A가 메시지를 보내면
Then A의 메시지는 판정을 거친다
```

**FR-6.2** 판정 입력은 **해당 방의 최근 `N`개 메시지 + 지금 보내려는 메시지**다. `N`은 환경변수 `AI_CONTEXT_N`으로 설정하며 기본값은 **10**이다. **참여자 정보는 입력에 포함하지 않는다.** `[Q1]` `[BL]`

```
Given AI_CONTEXT_N이 10이고 방에 메시지가 25개 있다
When 판정을 요청하면
Then 가장 최근 10개와 후보 메시지가 모델 입력에 포함되고, 참여자 이름·아이디·별칭은 포함되지 않는다
```

**FR-6.3** 모델은 **0.0~1.0의 부적절 점수만** 반환한다. 적절/부적절 판정은 **서버가 설정된 임계값과 비교해** 내린다. 임계값은 환경변수로 조정 가능하다. `[Q5]`

```
Given 임계값이 0.7이고 모델이 0.85를 반환했다
When 서버가 판정하면
Then 부적절로 판정한다

Given 임계값이 0.7이고 모델이 0.65를 반환했다
When 서버가 판정하면
Then 적절로 판정한다

Given 임계값을 0.9로 바꾸었다
When 모델이 0.85를 반환하면
Then 코드 변경 없이 적절로 판정한다
```

**FR-6.4** 방 안 메시지가 `N`개 미만이면 **판정을 건너뛰고 그대로 전송**하며, `verification_status`를 `skipped_no_context`로 기록한다. `[SD]`

```
Given AI_CONTEXT_N이 10이고 방에 메시지가 4개 있다
When 검증이 켜진 사용자가 메시지를 보내면
Then 모델을 호출하지 않고 전송되며 verification_status는 skipped_no_context다
```

**FR-6.5** 판정 대기 중에는 **전송 버튼을 비활성화하고 "확인 중..." 표시**를 띄운다. `[SD]`

```
Given 검증이 켜진 방에서 Enter를 눌렀다
When 판정 응답이 아직 오지 않았다
Then 전송 버튼이 비활성화되고 "확인 중..." 표시가 보인다
```

**FR-6.6** 부적절 판정 시 **"이 방에 맞지 않는 것 같습니다. 그래도 보낼까요?"** 확인 팝업을 띄운다. `[SD]`

```
Given 부적절로 판정되었다
When 팝업에서 "보내기"를 누르면
Then 메시지가 전송되고 verification_status는 flagged_sent다

Given 부적절로 판정되었다
When 팝업에서 "취소"를 누르면
Then 메시지는 전송되지 않고 messages 테이블에 저장되지 않으며, 입력창의 텍스트는 유지된다
```

**FR-6.7** 판정 대상은 **"이 방의 문맥에 맞는가"뿐이다.** 욕설·비방·민감정보 등 내용 자체의 부적절성은 판정 대상이 아니다. `[SD-Q2]`

### FR-7 판정 로그와 상태 (Must)

**FR-7.1** `messages.verification_status`는 다음 6값을 갖는다. 구분 기준은 **모델 호출을 시도했는가**와 **그 결과가 무엇이었는가**다. `failed`와 `degraded`를 하나로 합치지 않는다 — 합치면 API 장애 빈도를 셀 때 degraded 구간이 섞여 과대 집계된다. `[SD]`

| 값 | 의미 | 모델 호출 | 판정 로그 |
|---|---|---|---|
| `ok` | 호출 성공, 점수가 임계값 미만 (적절) | 함 | 남김 |
| `flagged_sent` | 호출 성공, 부적절 판정, 사용자가 전송 강행 | 함 | 남김 |
| `failed` | 호출을 시도했으나 에러·타임아웃. 검증 없이 전송됨 | 시도함 | 남김 (verdict NULL) |
| `degraded` | degraded 상태여서 호출을 아예 하지 않고 건너뜀 | 안 함 | 안 남김 |
| `skipped_no_context` | 문맥이 `N`개 미만이라 건너뜀 | 안 함 | 안 남김 |
| `disabled` | 발신자의 검증 토글이 꺼짐 | 안 함 | 안 남김 |

여섯 값의 도달 경로:

```
검증 토글 꺼짐 ------------------------------------> disabled
검증 켜짐, 방 메시지 < N --------------------------> skipped_no_context
검증 켜짐, degraded 상태이고 프로브 차례 아님 -----> degraded
검증 켜짐, 호출함
   |
   +-- 성공, 점수 < 임계값 -------------------------> ok
   +-- 성공, 점수 >= 임계값
   |      +-- 사용자 "보내기" ----------------------> flagged_sent
   |      +-- 사용자 "취소" ------------------------> (메시지 없음, 로그만 남음)
   +-- 에러/타임아웃 (재시도 1회 포함)
          +-- 첫 실패, 사용자 수락 -----------------> failed
          +-- 첫 실패, 사용자 거절 -----------------> (메시지 없음, 로그만 남음)
          +-- 프로브 실패 -------------------------> failed
```

<!-- Text fallback: 검증 토글이 꺼져 있으면 disabled. 켜져 있고 방 메시지가 N개 미만이면 skipped_no_context. 켜져 있고 degraded 상태이며 프로브 차례가 아니면 degraded. 실제로 호출한 경우, 성공하고 점수가 임계값 미만이면 ok, 임계값 이상인데 사용자가 보내기를 누르면 flagged_sent, 취소하면 메시지가 저장되지 않고 로그만 남는다. 에러나 타임아웃이면 첫 실패에서 사용자가 수락한 경우와 프로브가 실패한 경우 모두 failed이며, 첫 실패에서 거절하면 메시지가 저장되지 않고 로그만 남는다. -->

**FR-7.2** **모델 호출을 시도한 모든 건**은 판정 로그에 행을 남긴다. 호출하지 않은 건(`disabled`, `skipped_no_context`, `degraded`)은 로그를 남기지 않는다. `[SD]` `[Q5]`

로그 컬럼: `message_id`(nullable), `room_id`, `context_from_seq`, `context_to_seq`, `score`(nullable), `verdict`(nullable), `threshold`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `user_action`.

`user_action`의 값은 셋이다:

| 값 | 언제 |
|---|---|
| `auto_sent` | 적절 판정이라 사용자에게 묻지 않고 전송 |
| `sent` | 부적절 판정 후 사용자가 "보내기"를 선택 |
| `cancelled` | 부적절 판정 후 사용자가 "취소"를 선택 |

```
Given 부적절 판정 후 사용자가 취소했다
When 로그를 조회하면
Then 해당 행이 message_id=NULL, user_action='cancelled', verdict='inappropriate'로 존재하고 messages 테이블에는 그 메시지가 없다

Given 적절 판정으로 자동 전송되었다
When 로그를 조회하면
Then message_id가 실제 메시지를 가리키고 user_action='auto_sent'이며 context_from_seq~context_to_seq가 실제 사용된 문맥 범위와 일치한다

Given 호출이 타임아웃되어 verification_status가 failed다
When 로그를 조회하면
Then 해당 행이 score=NULL, verdict=NULL, latency_ms에 실제 대기 시간이 기록된 채 존재한다
```

**FR-7.3** 판정 성능의 라벨은 두 갈래다. `[Q2]` `[Q9]`

| 라벨 | 출처 | 무엇을 알려주는가 |
|---|---|---|
| `user_action` | 부적절 판정 시 사용자의 선택 | 모델이 **부적절이라 한 건**이 맞았는지 — `cancelled`=TP, `sent`=FP |
| 오발송 신고 (FR-11) | 전송된 메시지에 대한 사용자의 사후 신고 | 모델이 **놓친 건**이 있었는지 — FN 후보 |

두 라벨 모두 근사다. `user_action`의 한계는 ASM-1에, 신고 라벨의 한계는 ASM-6에 기록되어 있다. **집계 결과를 해석할 때 반드시 함께 읽어야 한다.**

**FR-7.4** 성능 집계는 **판정 로그를 대상으로 하며, `verdict`가 NULL이 아닌 행만** 사용한다. `messages.verification_status`를 필터로 쓰지 않는다 — 취소된 건은 `messages` 행이 없어 그 필터로는 영원히 잡히지 않기 때문이다. `[Q2]` `[SD]`

```
Given 부적절 판정 10건 중 7건이 cancelled, 3건이 sent이다
When precision을 계산하면
Then 7/(7+3) = 0.7이 나온다

Given verification_status가 disabled인 메시지가 100건 있다
When 성능 집계를 실행하면
Then 그 100건은 판정 로그에 행이 없으므로 집계에 포함되지 않는다

Given 호출이 실패해 verdict가 NULL인 로그 행이 5건 있다
When 성능 집계를 실행하면
Then 그 5건은 제외된다
```

**FR-7.5** 이번 범위에서 산출하는 지표는 다음이 전부다. 산출 불가능한 지표를 산출 가능한 것처럼 보고하지 않는다. `[Q9]`

| 지표 | 산출 가능 | 정의 |
|---|---|---|
| precision (근사) | 가능 | 부적절 판정 건 중 `cancelled` 비율 |
| flag rate | 가능 | 판정한 건 중 부적절로 판정된 비율. **이 값이 높으면 precision과 무관하게 기능을 못 쓴다** |
| 신고율 | 가능 | 전송된 메시지 중 오발송으로 신고된 비율 (FR-11) |
| 미검출 후보 | 가능 | 신고된 메시지 중 `verification_status`가 `ok`였던 건 — 모델이 적절이라 했는데 사용자가 오발송이라 한 경우 |
| 판정 지연 | 가능 | `latency_ms`의 분포 |
| 토큰 비용 | 가능 | `prompt_tokens` + `completion_tokens` 합계 |
| API 실패율 | 가능 | `verdict`가 NULL인 로그 행의 비율 |
| **recall** | **불가능** | 놓친 오발송의 전체 모수를 알 수 없다. 신고는 자발적이라 하한만 준다. 정확한 recall은 라벨링된 데이터셋(트랙 2)이 있어야 한다 |

```
Given 판정 로그와 신고 데이터가 쌓여 있다
When 성능 리포트를 생성하면
Then recall 항목은 수치 대신 "산출 불가 — 라벨 데이터셋 필요"로 표기된다
```

### FR-8 검증 실패 처리 (Must)

**FR-8.1** 모델 호출은 타임아웃 3~5초를 적용하고 **재시도는 1회만** 한다. `[SD]`

```
Given 모델 응답이 오지 않는다
When 타임아웃이 발생하면
Then 1회만 재시도하고, 재시도도 실패하면 실패 처리로 넘어간다. 총 대기 시간은 10초를 넘지 않는다
```

**FR-8.2** 검증 실패 시 **조용히 전송하지 않는다.** 세션 중 첫 실패에는 "검증 서버에 연결할 수 없습니다. 그래도 보내시겠습니까?"를 한 번 묻는다. `[SD]`

```
Given 세션 중 첫 검증 실패다
When 실패가 발생하면
Then 확인 팝업이 표시되고 사용자의 응답 전에는 전송되지 않는다
```

**FR-8.3** 사용자가 수락하면 **그 메시지는 `failed`로 전송되고**(호출을 실제로 시도했기 때문이다), 이후 **degraded 상태로 전환**한다. degraded는 **모든 방에 적용**되며(방을 옮겨도 다시 묻지 않는다), **브라우저 탭의 메모리에만** 저장한다. 새로고침하거나 새 탭을 열면 초기화되어 정상 검증을 다시 시도한다. `[SD]` `[Q4]`

```
Given 첫 검증 실패 팝업에서 "보내기"를 선택했다
When 메시지가 전송되면
Then 그 메시지의 verification_status는 failed이고, 이후 상태가 degraded로 전환된다

Given degraded 상태에서 방 A에 있다
When 방 B로 이동해 메시지를 보내면
Then 같은 팝업이 다시 뜨지 않고 그 메시지의 verification_status는 degraded다

Given degraded 상태다
When 페이지를 새로고침하면
Then degraded가 해제되고 다음 전송에서 정상 검증을 시도한다
```

**FR-8.4** 사용자가 거절하면 전송을 취소하고 입력창 텍스트를 유지하며, **입력창 옆에 "다시 시도" 버튼을 표시**한다. 그 버튼을 누르면 같은 텍스트로 검증부터 다시 시작한다. degraded로 넘어가지 않는다. `[SD]`

```
Given 첫 검증 실패 팝업에서 "취소"를 선택했다
When 팝업이 닫히면
Then 메시지는 전송되지 않고 입력창 텍스트가 그대로 남으며 "다시 시도" 버튼이 보인다

Given "다시 시도" 버튼이 표시되어 있다
When 버튼을 누르면
Then 같은 텍스트로 검증이 다시 시도된다

Given 검증 실패를 거절한 직후다
When 다른 메시지를 새로 입력해 보내면
Then degraded 상태가 아니므로 정상 검증을 시도한다
```

**FR-8.5** degraded 상태에서도 **5번째 메시지마다 한 번은 검증을 시도**한다(프로브). 성공하면 정상 복귀하고 "AI 검증이 다시 켜졌습니다"를 알린다. 실패하면 팝업 없이 degraded를 유지하며, **그 프로브 메시지의 상태는 `failed`**다(호출을 시도했기 때문이다). `[SD]`

```
Given degraded 상태에서 4개의 메시지를 보냈다
When 5번째 메시지를 보내면
Then 검증을 시도한다

Given 프로브 검증이 성공했다
When 결과를 처리하면
Then degraded가 해제되고 복귀 알림이 표시되며, 그 메시지의 상태는 판정 결과에 따라 ok 또는 flagged_sent다

Given 프로브 검증이 실패했다
When 결과를 처리하면
Then 팝업 없이 degraded가 유지되고, 그 메시지는 verification_status=failed로 전송된다
```

**FR-8.6** 검증받지 못한 메시지(`failed`, `degraded`, `skipped_no_context`)에는 **"검증 안 됨" 배지**를 표시한다. 나중에 스크롤해서 봐도 그 사실을 알 수 있어야 한다. `[SD]`

### FR-9 컨테이너화 (Must)

**FR-9.1** `docker compose up` 한 번으로 앱과 MariaDB가 모두 기동한다. `[SD-Q10]`

```
Given 저장소를 clone하고 환경변수 파일만 채웠다
When docker compose up을 실행하면
Then 추가 수동 절차 없이 앱에 접속할 수 있다
```

**FR-9.2** 앱 컨테이너는 DB가 **healthy 상태가 된 뒤에** 기동한다. 앱 시작 시 DB 연결 재시도도 갖춘다. `[SD]`

```
Given DB 컨테이너가 아직 초기화 중이다
When 앱 컨테이너가 기동을 시도하면
Then DB healthcheck 통과를 기다렸다가 시작하고, 그래도 연결이 실패하면 재시도한다
```

**FR-9.3** MariaDB는 **`utf8mb4`** 문자셋으로 구성한다. `[SD]`

```
Given 한글과 이모지가 포함된 메시지
When 저장하고 다시 조회하면
Then 문자가 깨지지 않고 원본과 일치한다
```

**FR-9.4** 백엔드는 **단일 프로세스**로 실행한다(`uvicorn` 워커 1개). `[SD]` `[BL]`

```
Given 앱 컨테이너가 기동했다
When 컨테이너 안의 프로세스 목록을 확인하면
Then uvicorn 워커 프로세스가 1개만 존재한다

Given 두 사용자가 같은 방에 접속해 있다
When 한 사용자가 메시지를 보내면
Then 다른 사용자에게 실시간으로 전달된다 (연결 레지스트리가 갈라지지 않는다)
```

**FR-9.5** 개발 중에는 Vite dev 서버를 사용하고, 배포 시에는 빌드된 정적 파일을 FastAPI가 서빙한다. 개발 프로파일에만 CORS 허용을 둔다. `[Q7]`

### FR-11 오발송 신고 (Must)

**FR-11.1** 전송된 메시지에 **"잘못 보냈어요" 신고**를 달 수 있다. 신고는 발신자 본인만 자기 메시지에 대해 할 수 있으며, 취소할 수 있다. `[Q9]`

```
Given 내가 보낸 메시지가 화면에 있다
When 그 메시지에서 "잘못 보냈어요"를 선택하면
Then 그 메시지에 신고 표시가 남고 신고 시각이 기록된다

Given 내가 신고한 메시지가 있다
When 신고를 취소하면
Then 신고 표시가 사라지고 기록이 해제된다

Given 다른 사람이 보낸 메시지가 화면에 있다
When 그 메시지를 보면
Then "잘못 보냈어요" 선택지가 표시되지 않는다
```

**FR-11.2** 신고는 **검증 상태와 무관하게** 모든 전송된 메시지에 가능하다. 이것이 이 기능의 존재 이유다 — 검증이 꺼졌거나(`disabled`), 문맥이 부족했거나(`skipped_no_context`), degraded였거나(`degraded`), 호출이 실패했거나(`failed`), 적절로 판정된(`ok`) 메시지 — 즉 `flagged_sent`를 제외한 다섯 상태 전부가 지금은 사용자 판단에 대한 신호를 남기지 않는 사각지대다. `[Q9]`

```
Given verification_status가 ok인 내 메시지가 있다
When 그 메시지를 오발송으로 신고하면
Then 신고가 기록되고, 미검출 후보(FR-7.5)로 집계된다

Given verification_status가 disabled인 내 메시지가 있다
When 그 메시지를 오발송으로 신고하면
Then 신고가 기록된다
```

**FR-11.3** 신고 여부는 메시지에 기록한다(`messages.misdirect_reported_at`, nullable). 별도 신고 테이블을 두지 않는다 — 발신자 본인만 자기 메시지에 한 번 신고하므로 1:1 관계다. `[Q9]` `[dec]`

### FR-10 방 참여자 관리 (Should)

일정이 밀리면 가장 먼저 잘린다. `[SD]`

**FR-10.1** 기존 방에 친구를 추가 초대할 수 있다.

```
Given 2명인 방에 속해 있고 초대할 친구가 있다
When 그 친구를 추가하면
Then 방 참여자가 3명이 되고, 추가된 참여자의 방 목록에 그 방이 나타난다

Given 이미 방에 있는 사용자를 추가하려 한다
When 추가를 요청하면
Then 400을 반환하고 참여자 수는 변하지 않는다
```

**FR-10.2** 방에서 나갈 수 있다. 나간 뒤에는 방 목록에서 사라지고 새 메시지를 받지 않는다.

```
Given 방에 속해 있다
When 방에서 나가면
Then 그 방이 방 목록에서 사라진다

Given 방에서 나간 직후다
When 그 방에 다른 참여자가 메시지를 보내면
Then 나간 사용자에게는 그 메시지가 전달되지 않는다
```

---

## Non-Functional Requirements

**NFR-1 판정 지연** — 검증이 켜진 메시지의 전송 대기 시간은 정상 경로에서 **5초 이내**, 재시도를 포함한 최악의 경우 **10초 이내**여야 한다. `[SD]`

**NFR-2 응답성** — 판정 대기 중 UI는 멈춘 것처럼 보이지 않아야 한다. FR-6.5의 비활성화 + "확인 중..." 표시가 이 요구사항의 구현이며, 그 존재 여부로 검증한다. `[SD]`

**NFR-3 데이터 무결성** — 브로드캐스트된 메시지는 반드시 DB에 존재해야 한다. 새로고침 후 사라지는 메시지가 있어서는 안 된다. FR-4.1이 이를 보장한다. `[SD]`

**NFR-4 순서 일관성** — 같은 방의 모든 참여자는 메시지를 같은 순서로 본다. FR-4.2가 이를 보장한다. `[SD]`

**NFR-5 프라이버시 고지** — AI 검증이 켜진 방에서 최근 `N`개 메시지가 OpenAI API로 전송된다는 사실을 사용자에게 고지한다. `[SD]`

**NFR-6 비밀 관리** — 자격증명·API 키는 환경변수로만 주입한다. FR-1.4가 이를 보장한다. `[SD]`

**NFR-7 테스트** — 테스트 전략은 Standard다. `practices-discovery`를 건너뛰어 팀 관행(`team-practices`)이 확립되지 않았으므로 `org.md`의 프레임워크 기본값이 적용된다. FR-4.2(동시 채번), FR-3.3(구독·fetch 순서), FR-8.3~8.5(degraded 상태 기계)는 실제 테스트로 검증한다 — 이 셋이 산문으로만 남으면 구현이 흔들린다. `[SD]`

## Constraints

**CON-1** 서버는 단일 프로세스로 고정한다. WebSocket 연결 레지스트리가 프로세스 메모리에 있어, 워커를 늘리면 다른 워커에 붙은 사용자에게 메시지가 가지 않는다. 확장이 필요해지면 Redis pub/sub을 도입해야 하나 이번 범위 밖이다. `[SD]`

**CON-2** 메시지 브로커(Kafka 등)를 사용하지 않는다. AI 검증이 전송 전 동기 차단 방식이라 비동기 파이프라인이 필요 없다. `[SD]`

**CON-3** 일정이 고정되어 있다 — 중간 점검 2026-07-31, 최종 발표 2026-08-04. 구현자는 1인이다. `[IS]`

**CON-4** 브라우저는 WebSocket 연결에 커스텀 헤더를 붙일 수 없다. FR-1.3의 첫 프레임 인증이 이 제약에 대한 대응이다. `[Q3]`

## Assumptions

**ASM-1** `user_action`을 정답 라벨로 쓰는 것은 근사다. 사용자가 부적절 판정에 동의해 취소했는지, 귀찮아서 취소했는지 구별하지 못한다. 반대로 강행 전송이 항상 오탐인 것도 아니다 — 판정이 맞았지만 그래도 보내야 했을 수 있다. 이 한계를 안고 시작한다. `[Q2]`

**ASM-2** degraded가 탭 단위이므로, 탭을 두 개 열면 각 탭의 degraded 상태가 다를 수 있다. `scope-document.md`의 "사용자 전역"은 *방을 건너서* 유지된다는 뜻으로 읽는다. `[Q4]`

**ASM-3** 모델이 반환하는 0.0~1.0 점수는 자기보고이며 교정된 확률이 아니다. 임계값은 실사용 로그를 보고 조정할 값이지, 이론적으로 도출할 값이 아니다. `[Q5]`

**ASM-4** `AI_CONTEXT_N`의 기본값 10은 실험 시작점이다. 최적값은 판정 로그가 쌓인 뒤에 정한다. `[Q1]`

**ASM-5** 다음 값들은 상류 산출물이나 답변에 근거가 없고 **이 단계에서 정한 것**이다. 근거가 생기면 언제든 바뀔 수 있다.

| 값 | 요구사항 | 근거 |
|---|---|---|
| 비밀번호 최소 8자 | FR-1.1 | 통상적 최소선. 데모 규모에서 더 강한 정책은 사용성만 해친다 |
| WebSocket 인증 타임아웃 5초 | FR-1.3 | 정상 클라이언트가 첫 프레임을 보내기에 충분하고, 방치된 연결을 오래 붙들지 않는 값 |
| 임계값 환경변수명 `AI_VERDICT_THRESHOLD` | FR-6.3 | `AI_CONTEXT_N`과 접두어를 맞춘 것 |
| 신고를 별도 테이블 대신 컬럼으로 | FR-11.3 | 발신자 1인이 자기 메시지에 한 번 신고하므로 1:1. 테이블을 나눌 이유가 없다 |

**ASM-6** 오발송 신고 수는 실제 오발송 수의 하한도 상한도 아니다. 두 방향으로 어긋난다 — 신고하지 않고 넘어간 오발송이 있어 **과소** 집계되고, 오발송이 아닌데 다른 이유(오타, 마음 바뀜)로 신고한 건이 있어 **과대** 집계된다. 두 오차의 크기를 알 수 없으므로 방향조차 단정할 수 없다.

따라서 신고 데이터는 **실제 오발송 모수를 추정하는** 지표 — recall이 대표적이다 — 의 분모나 분자로 쓸 수 없다. 그 모수가 미지수이기 때문이다.

관찰 가능한 분모에 대한 비율은 예외다. FR-7.5의 `신고율`(전송된 메시지 대비 신고된 메시지)은 분모가 실측값이므로 성립한다 — 다만 그 값이 재는 것은 **신고 행위의 빈도**이지 오발송의 빈도가 아니다.

FR-7.5의 `미검출 후보`도 같은 성격이다. 신고된 것 중 모델이 `ok`라 했던 건을 세어 "모델이 놓쳤을 수 있는 사례"를 **표본으로 확보**하는 것이지, 놓친 비율을 재는 것이 아니다. `[Q9]`

**ASM-8** FR-11은 이 단계의 Q9에서 나온 신규 Must이며, `scope-document.md`의 경계에는 없던 범위다. 그 문서의 위험 등록부는 이미 "07-31까지 Must 전량 완료"를 가능성 High / 영향 High로 잡아두었고, Must가 하나 늘어난 만큼 그 위험은 커졌다. 절단 순서는 Should 2건(FR-10) → 프로브 회복 감지(FR-8.5) → FR-11이다. 앞의 둘은 `scope-document.md`의 위험 등록부가 이미 정해둔 순서를 그대로 잇는다.

FR-11을 그 뒤에 두는 근거는 **대체재의 유무**다. FR-8.5의 프로브 회복은 빠져도 새로고침이라는 값싼 대체 경로가 있어 기능이 죽지 않는다. FR-11이 수집하는 미검출 후보 신호는 대체재가 없다 — 빼면 모델이 놓친 사례를 관찰할 창구가 이번 범위에서 완전히 사라지고, 트랙 2의 라벨 데이터셋이 생길 때까지 아무것도 알 수 없다. 구현 비용이 작다는 점(컬럼 하나 + 버튼 하나)도 같은 방향으로 작용한다.

**FR-11이 precision을 가능하게 하는 것은 아니다.** precision은 FR-7.4가 집계 축을 판정 로그로 옮긴 시점에 이미 계산 가능해졌다. FR-11이 더하는 것은 precision이 아니라 **다른 종류의 신호**이며, ASM-6이 밝힌 대로 그 신호도 비율이 아닌 표본이다.

Delivery 단계에서 이 순서를 재확인해야 한다. `[Q9]` `[SD]`

**ASM-7** `intent-statement.md`의 성공 지표 표는 recall을 "측정하되 우선순위 아님"으로 적었으나, 실사용 로그만으로는 recall을 산출할 수 없다는 것이 이 단계에서 드러났다. FR-7.5가 그 정정이다. precision을 1순위로 둔 판단 자체는 오히려 이 사실로 뒷받침된다 — 라이브에서 측정 가능한 것이 그것뿐이다. `[Q9]`

## Out of Scope

`scope-document.md`의 "만들지 않는 것"을 그대로 따른다.

- 내용 기준 필터링(욕설·비방·민감정보)
- 데이터셋 구축(트랙 2), 성능 테스트·베이스라인 측정(트랙 3)
- 타이핑 인디케이터, 읽음 표시, 파일·이미지 전송
- 브라우저를 닫은 상태의 푸시 알림 (Service Worker + Web Push)
- 원격 서버 배포, CI 파이프라인, 이미지 레지스트리 푸시, 관측성 스택
- 상대가 설정한 이름 표시, 친구 목록 정렬·검색, 친구 승인 절차
- 리프레시 토큰, 자동 만료 갱신

## Open Questions

- **판정 프롬프트 설계** — FR-6.3이 모델에게 0.0~1.0 점수를 요구하는데, 그 점수를 안정적으로 얻는 프롬프트가 아직 없다. Application Design 또는 Functional Design에서 닫는다.
- **판정 임계값의 초기값** — FR-6.3이 임계값을 설정값으로 뺐으나 시작값이 정해지지 않았다. precision 우선 방침상 보수적으로(높게) 잡아야 한다.
- **Should 항목(FR-10)의 절단 시점** — walking skeleton Bolt 완료 시점이 자연스러운 결정 지점이다.
- **신고 UI의 위치** — FR-11.1이 "메시지에서 선택"이라고만 했다. 롱프레스인지, 호버 메뉴인지, 컨텍스트 메뉴인지는 정하지 않았다. Application Design에서 닫는다.

## Review

**Reviewer:** aidlc-product-lead-agent

**Verdict: READY**

Fourth pass, final confirmation. Both corrections land. I checked each against every row of FR-7.5 (not just the two rows named) and against FR-8.3's actual text (not just the summary claim), specifically hunting for anything the fix itself might have broken. I found none — zero contradictions. Two observations below are refinements, explicitly labeled as such per the instruction not to treat them as blocking.

### Finding B — verified fixed against all eight rows of FR-7.5, not just the two named

ASM-6 now bans report data only as the numerator/denominator of indicators that **estimate the unknown true-misdirect population** ("실제 오발송 모수를 추정하는 지표 — recall이 대표적이다"), and explicitly carves out ratios with an observable denominator, naming `신고율` by name as valid with the caveat that it measures "신고 행위의 빈도이지 오발송의 빈도가 아니다." I checked this against every row, not just the two the coordinator named:

- `precision`, `flag rate`, `판정 지연`, `토큰 비용`, `API 실패율` — none of these are built from `misdirect_reported_at` at all (they come from `judgment_logs`), so ASM-6 doesn't apply to them and there's nothing to check.
- `신고율` — explicitly carved out by name, consistent.
- `미검출 후보` — explicitly reframed as a sample, consistent, unchanged from the prior pass.
- `recall` — explicitly still the banned case (estimates the unknown true population), consistent — this is exactly what the carve-out excludes.

All eight rows are consistent with the new ASM-6. No contradiction.

**One refinement, not a contradiction:** FR-7.5's own row wording for `신고율` — "전송된 메시지 중 **오발송으로 신고된** 비율" — read in isolation, without ASM-6's adjacent caveat, could be misparsed as claiming the ratio measures the misdirect rate rather than the reporting-action rate. It doesn't actually assert that (the verb is "신고된," reported, not "오발송인," was-a-misdirect), and ASM-6 disambiguates it two paragraphs later, so nothing in the document is factually wrong — but tightening the row itself to something like "신고 빈도 (오발송 여부와는 별개)" would make the row self-sufficient without needing the reader to cross to ASM-6. Recording this for the approval gate, not blocking on it.

### Finding C — verified fixed, and the substitutability claim holds

ASM-8 now explicitly disclaims what I flagged: "FR-11이 precision을 가능하게 하는 것은 아니다. precision은 FR-7.4가 집계 축을 판정 로그로 옮긴 시점에 이미 계산 가능해졌다." I checked this against FR-7.5's `precision` row (built from `judgment_logs`, no reference to FR-11 or reports) and FR-7.3's two-track label table (which already separated "모델이 부적절이라 한 건이 맞았는지" from "모델이 놓친 건이 있었는지" — precision was only ever attached to the first track). Consistent; no contradiction.

On the substitutability argument itself — I specifically checked whether "새로고침" is a fallack that FR-8.3 actually supports, since if the fallback claim were factually wrong the whole ordering would collapse. FR-8.3's own text: "새로고침하거나 새 탭을 열면 초기화되어 **정상 검증을 다시 시도한다**." That is exactly the factual premise ASM-8 relies on, and it's stated directly in the requirement it's citing — not invented at the assumption level. It's also not a new claim: `scope-document.md`'s Risk Register already named this same mitigation ("이것만 빼도 degraded 상태 관리가 크게 단순해지며 회복은 새로고침으로 대체된다") before this stage started, and this stage's own Q4/FR-8.3 work went on to confirm the mechanism concretely (tab-scoped, memory-only, refresh clears it) rather than just assume it. So the factual premise is correct and it isn't a fresh, unbacked assertion — it's an inherited, since-confirmed one. No contradiction.

**One refinement, not a contradiction:** "adequate" fallback is doing more work than "refresh clears degraded" alone proves. What's genuinely lost by cutting FR-8.5 isn't just automation — it's the *detection and notification* half of recovery. Without the probe, nothing tells a degraded user that verification might be working again; they'd have to refresh speculatively, with no system-provided signal that doing so is worth trying, and refreshing has the side effect of re-triggering FR-3.3's resubscribe-then-refetch room entry, not just clearing one flag. FR-8.3's text doesn't contradict this — it only establishes that refresh *works* as a recovery mechanism, not that it's *equivalent in UX* to an active, notified recovery. This doesn't undermine the ordering (implementation-cost and no-substitute-for-FR-11 are both still valid independent reasons, and the underlying premise is factually sound and already human-approved upstream), but "adequate" slightly overstates parity between a system-detected recovery and a user-guessed one. Worth a half-sentence acknowledgment, not a re-ordering.

### Summary

Zero contradictions found in this pass. Two refinements recorded above, both explicitly non-blocking per this round's stated bar, carried forward to the approval gate rather than requiring another fix cycle. All prior blocking findings (the FR-7.3/FR-7.4 aggregation bug, `failed` unreachability, seven GWT-less requirements) remain fixed and re-verified across four passes. The document is ready for engineering to build from without needing to come back and ask a clarifying question.

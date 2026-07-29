# Application Design — Questions

**Stage**: application-design
**Phase**: INCEPTION
**Depth**: Standard
**Mode**: guided — 아키텍트가 6문항 전부에 근거를 붙여 제안하고 사용자가 일괄 승인

## 입력

`../requirements-analysis/requirements.md` — FR 11영역 46개, NFR 7, CON 4, ASM 8.

요구사항은 **무엇을** 만들지 정했다. 이 단계는 **어떤 구조로** 만들지 정한다. 아래는 그중 사용자의 판단이 필요한 것만 묻는다 — 나머지는 아키텍트로서 제가 정하고 `decisions.md`에 대안과 함께 ADR로 남긴다.

일정이 촉박하므로(중간 점검 07-31, 발표 08-04) **익숙한 것 / 단순한 것**을 고르는 편이 대체로 옳다. 각 문항의 권장안은 그 기준으로 잡았다.

---

## Q1. 판정 요청을 어떤 경로로 보내는가?

> FR-6.5는 판정 대기 중 전송 버튼 비활성화와 "확인 중..." 표시를 요구한다. 그 대기를 어떤 채널로 처리할지가 갈린다.

- A. **WebSocket 프레임** — 메시지 전송 프레임을 보내면 서버가 판정하고, 결과를 별도 프레임으로 회신한다. 연결이 하나라 상태 추적이 한 곳에 모인다. 대신 요청·응답 짝을 클라이언트가 직접 관리해야 한다(임시 ID 매칭)
- B. **별도 REST 엔드포인트** — `POST /rooms/{id}/judge`로 판정만 받고, 적절이면 그다음 WebSocket으로 전송한다. HTTP 요청·응답이라 대기·타임아웃·재시도를 다루기 쉽고 테스트도 쉽다. 왕복이 두 번이 된다
- C. **REST로 판정+전송을 한 번에** — `POST /rooms/{id}/messages`가 판정·저장·브로드캐스트를 모두 처리하고, WebSocket은 수신 전용으로 쓴다. 전송 경로가 하나로 단순해진다. FR-4.3의 낙관적 렌더링은 그대로 가능하다
- D. Not yet defined
- X. Other (please specify)

[Answer]: C. REST로 판정+전송을 한 번에 — WebSocket은 수신 전용. 부적절 판정 시 409 + judgment_log_id를 반환하고, 사용자가 강행하면 force_log_id를 붙여 재요청한다

---

## Q2. 판정 임계값(`AI_VERDICT_THRESHOLD`)의 초기값을 얼마로 두는가?

> FR-6.3에서 모델은 0.0~1.0 부적절 점수만 반환하고 서버가 임계값으로 가른다. precision 우선 방침이면 **높게** 잡아야 한다 — 확실할 때만 팝업을 띄우는 쪽이다.
>
> 낮게 잡으면 팝업이 자주 뜨고(높은 flag rate), 사용자가 습관적으로 닫기 시작하면 기능이 죽는다. 높게 잡으면 놓치는 게 늘지만 recall은 어차피 측정 불가다.

- A. **0.8** — 보수적. 확실한 것만 잡는다. precision 우선에 가장 부합
- B. **0.7** — 중간
- C. **0.6** — 공격적. 의심스러우면 일단 묻는다
- D. 데모 중 조정할 수 있게 두고 시작값만 정한다 (값은 X에 기재)
- E. Not yet defined
- X. Other (please specify)

[Answer]: B. 0.7 — 보정 데이터가 없는 상태의 시작값. 리허설에서 조정한다

---

## Q3. 프론트엔드 상태 관리를 무엇으로 하는가?

> 관리할 상태: 인증 토큰, 친구 목록, 방 목록과 안 읽은 개수, 현재 방의 메시지, WebSocket 연결, degraded 플래그, 토스트 큐.
>
> 6일 일정에서는 **익숙한 것**이 가장 빠르다. 처음 쓰는 라이브러리를 배우는 시간이 그 라이브러리가 절약해주는 시간보다 크다.

- A. **React Context + useReducer** — 라이브러리 추가 없음. 이 규모에 충분하고 러닝커브가 없다
- B. **Zustand** — 보일러플레이트가 적고 배우는 데 10분. Context보다 리렌더 제어가 쉽다
- C. **Redux Toolkit** — 가장 구조적이지만 설정과 보일러플레이트가 많다
- D. **TanStack Query + 로컬 state** — 서버 상태와 클라이언트 상태를 분리한다. 캐싱·재검증이 공짜지만 WebSocket 실시간 갱신과 섞으면 복잡해진다
- E. Not yet defined
- X. Other (please specify)

[Answer]: B. Zustand

---

## Q4. 백엔드 모듈 구조를 어느 깊이로 나누는가?

> FastAPI 애플리케이션의 내부 구조다. 깊게 나누면 테스트하기 좋지만 파일이 많아지고, 얕으면 빠르지만 판정 로직이 라우터에 섞인다.

- A. **얕은 계층** — `routers/` + `models/` + `services/` 세 층. 판정·seq 채번 같은 로직은 `services/`에 둔다. 파일 수가 적고 6일에 현실적
- B. **기능별 모듈** — `auth/`, `friends/`, `rooms/`, `messages/`, `judgment/` 각각 안에 router·model·service를 둔다. 경계가 명확하고 Unit 분해와 1:1로 맞는다
- C. **헥사고날** — 도메인 계층이 프레임워크·DB를 모르게 격리한다. 테스트가 가장 쉽지만 어댑터 코드가 늘어난다
- D. Not yet defined
- X. Other (please specify)

[Answer]: B. 기능별 모듈 — auth / friends / rooms / messages / judgment / core

---

## Q5. 모델이 점수를 안정적으로 내놓게 하려면 출력 형식을 어떻게 강제하는가?

> FR-6.3이 0.0~1.0 점수를 요구하는데, LLM이 설명을 붙이거나 형식을 흐트러뜨리면 파싱이 깨진다. 이건 판정 품질보다 **안정성** 문제다.

- A. **Structured Outputs (JSON 스키마 강제)** — OpenAI의 `response_format`에 스키마를 주면 형식이 보장된다. 파싱 실패가 원천적으로 없다
- B. **JSON 모드 + 수동 파싱** — `response_format={"type":"json_object"}`로 JSON은 보장되나 필드 구조는 프롬프트로 유도한다. 파싱 실패 처리 필요
- C. **함수 호출(tool calling)** — 판정 결과를 받는 함수를 정의하고 모델이 호출하게 한다. 스키마가 보장되지만 코드가 조금 더 복잡하다
- D. **평문 숫자만 요청** — "0에서 1 사이 숫자만 답하라". 가장 단순하지만 모델이 말을 덧붙이면 깨진다
- E. Not yet defined
- X. Other (please specify)

[Answer]: A. Structured Outputs (JSON 스키마 강제, strict: true)

---

## Q6. DB 스키마 변경을 어떻게 관리하는가?

> `README.md`는 Alembic을 적었으나 확정된 결정은 아니다. 6일 일정에서 스키마가 몇 번 바뀔 것을 감안한다.

- A. **Alembic** — 정석. 마이그레이션 이력이 남고 롤백이 가능하다. 초기 설정에 30분쯤 든다
- B. **시작 시 `create_all()`** — SQLAlchemy가 테이블을 만든다. 가장 빠르지만 스키마를 바꾸면 DB를 지우고 다시 만들어야 한다. 데모 데이터가 날아간다
- C. **`create_all()`로 시작하고 필요해지면 Alembic 도입** — 초반 속도를 취하고 스키마가 안정되면 옮긴다
- D. Not yet defined
- X. Other (please specify)

[Answer]: A. Alembic


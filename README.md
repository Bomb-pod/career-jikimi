# career-jikimi

> 채팅창을 착각해 잘못 보내는 메세지. 제가 당신의 회사생활을 지켜드리겠습니다.

기존 대화의 문맥을 파악해, 채팅방을 착각하여 잘못 보낸 문맥에 맞지 않는 메시지를 전송 전에 경고하는 프로젝트.

세 갈래로 구성한다.

1. **채팅 웹앱 데모** — 경고 기능을 실제로 체험할 수 있는 채팅 앱
2. **데이터셋 구축** — 대화 스니펫 + 후보 메시지 + 라벨
3. **성능 테스트** — ChatGPT API를 붙여 판정 성능 측정

현재 단계는 **1번 웹앱**이다.

---

## 기술 스택

- 프론트엔드: React
- 백엔드: FastAPI
- 실시간 전송: WebSocket
- LLM: OpenAI API (ChatGPT)
- DB: MariaDB (InnoDB, `utf8mb4`). SQLAlchemy + `asyncmy` 드라이버, 마이그레이션은 Alembic
  - 로컬은 docker-compose로 띄운다. 문자셋을 `utf8mb4`로 명시할 것 — 기본값이 아닐 수 있고, 한글·이모지가 깨진다.
  - InnoDB 행 잠금이 `(room_id, seq)` 채번과 잘 맞는다. 아래 4번 참조.

메시지 브로커(Kafka 등)는 **사용하지 않는다.** AI 검증이 전송 전 동기 차단 방식이라 비동기 파이프라인이 필요 없고, 데모 규모에서 운영 비용만 늘어난다.

---

## 범위

### 만드는 것

- 회원가입 / 로그인
- 아이디로 친구 등록 (별칭 **필수** 입력, 등록 후 수정 가능)
- 친구를 초대해 채팅방 생성 (다수 선택 가능, 방 여러 개)
- 방별 메시지 저장 + 실시간 전송
- 방 입장 시 이전 대화 불러오기
- **로컬 컨테이너화** — Dockerfile + docker-compose로 `docker compose up` 한 번에 기동
- **참여자 개인별 AI 검증 토글** + 부적절 판정 시 전송 확인 팝업

### 만들지 않는 것

- 타이핑 인디케이터 ("○○○님이 입력 중...")
- 읽음 표시
- 파일 / 이미지 전송

### 우선순위 최하 (시간 남으면)

- 채팅방 참여자 추가
- 채팅방 나가기

> 회원가입·친구·방 생성은 **측정 대상이 아닌 껍데기**다. 최소한으로 만든다.
> 공들일 곳은 메시지 저장 / 문맥 조회 / 판정 로그 세 군데다.

---

## 웹앱 기능

### 1. 인증

- 회원가입, 로그인. JWT 사용.
- WebSocket은 브라우저에서 커스텀 헤더를 못 붙이므로, 연결 직후 첫 프레임으로 auth 토큰을 전송한다. *(가정)*

### 2. 친구

- 아이디 **정확 일치** 검색으로 **단방향 즉시 등록**. 승인 절차 없음. 등록 시 별칭을 반드시 입력한다.
- 부분 일치 검색·목록 정렬·승인 절차는 만들지 않는다.

### 3. 채팅방

- 친구를 다수 선택해 방 생성. 방은 여러 개 생성 가능.
- 방 헤더에 **AI 검증 토글**이 항상 보인다.

### 4. 메시지 전송

**저장 먼저, 브로드캐스트 나중.** 순서가 반대면 DB 쓰기 실패 시 화면엔 보이는데 새로고침하면 사라진다.

```
클라이언트 (임시 ID로 낙관적 렌더링)
   → 서버: 검증(켜진 경우) → DB INSERT → 방 참여자에게 브로드캐스트
   → 클라이언트: ack의 실제 ID로 교체
```

- WebSocket 연결은 **사용자당 1개**를 유지하고, payload의 `room_id`로 여러 방을 멀티플렉싱한다. 방마다 연결을 새로 열지 않는다.
- 정렬은 `created_at`이 아니라 **`(room_id, seq)`** 로 한다. 방 내부에서 단조 증가하는 시퀀스. 동시 도착 시 순서가 흔들리는 걸 막는다.
  - 채번은 한 트랜잭션 안에서 `SELECT last_seq FROM rooms WHERE id=? FOR UPDATE` → `+1` → INSERT. InnoDB 행 잠금이라 **방 단위로만 직렬화**되고 다른 방의 전송은 막지 않는다.
- **서버는 단일 프로세스로 고정한다.** `uvicorn --workers 2` 이상으로 띄우면 연결 레지스트리가 프로세스 메모리에 있어서 다른 워커에 붙은 사용자에게 메시지가 안 간다. 확장이 필요해지면 그때 Redis pub/sub.

### 5. 대화 이어보기

- `GET /rooms/{id}/messages?before=<seq>&limit=50` — seq 커서 페이지네이션.
- 방 입장 순서는 **구독 먼저, 히스토리 fetch 나중.** 반대로 하면 그 사이에 도착한 메시지가 유실된다. 겹치는 건 메시지 ID로 중복 제거.

---

## AI 검증

### 켜고 끄기

- **개인별 설정**이다. `room_members.ai_check_enabled` 컬럼. 방장이 켜면 전원 적용되는 방식이 아니다.
  - 이 기능은 "내가 실수하는 걸 막는" 기능이지 남을 위한 게 아니다. 남이 내 전송 지연을 결정하면 안 된다.
- UI는 방 헤더의 토글. 신규 방 **기본값은 켜짐.**

### 판정 입력

```
최근 N개 메시지 + 지금 보내려는 메시지  →  적절 / 부적절
```

- **참여자 정보는 사용하지 않는다.** 순수하게 대화 문맥만 본다.
- `N = 10~20`으로 시작. *(실험 변수 — 판정 로그에 실제 사용한 문맥 범위를 seq 시작~끝으로 기록해 재현 가능하게 한다)*

### 전송 흐름 (검증 켜진 방)

1. Enter → **전송 버튼 비활성화 + "확인 중..." 표시**
   대기가 1~3초라 반응이 없으면 앱이 멈춘 줄 안다. 반드시 필요하다.
2. 판정 결과
   - 적절 → 그대로 전송
   - 부적절 → **"이 방에 맞지 않는 것 같습니다. 그래도 보낼까요?"** 팝업
     - 보내기 → 전송 (`flagged_sent`)
     - 취소 → 전송 안 함, 입력창 텍스트 유지

### 콜드 스타트

방 안 메시지가 N개 미만이면 **판정을 건너뛰고 그냥 전송**한다. 문맥이 없으면 판단이 불가능하다.

새로 만든 방에서 바로 마주칠 상황이므로 규칙을 명시해 두고, 로그에 `skipped_no_context`로 남겨 성능 집계에서 제외한다.

### 실패 처리

타임아웃 3~5초, **재시도는 1회만.** (2회 재시도하면 사용자가 9초를 기다린다.)

실패하면 조용히 보내지 않는다 — 사용자는 검증받았다고 믿고 있다.

**첫 실패 시 한 번만 묻는다:**

> 검증 서버에 연결할 수 없습니다.
> 그래도 보내시겠습니까? *(서버가 정상화될 때까지 검증 없이 전송합니다)*

- **수락** → degraded 상태로 전환. 이후 팝업 없이 전송.
  - **범위: 사용자 전역.** API 장애는 방별로 일어나지 않는다. 방 단위로 관리하면 방을 옮길 때마다 같은 팝업이 다시 뜬다.
  - **저장: 세션 단위.** 새로고침하면 초기화되고 정상 검증을 다시 시도한다. 장애가 이미 끝났을 수 있다.
  - **회복 감지: 프로브 방식.** degraded 상태에서도 5번째 메시지마다 한 번은 검증을 시도한다. 성공하면 정상 복귀 + "AI 검증이 다시 켜졌습니다" 알림. 실패하면 조용히 유지(팝업 재표시 없음).
    - 별도 헬스체크를 돌리지 않는 이유: degraded 중엔 API를 안 부르므로 회복을 알 방법이 없는데, 프로브가 추가 인프라 없이 이를 해결한다.
- **거절** → 전송 취소. 입력창 텍스트 유지 + 재시도 버튼. degraded로 넘어가지 않고, 다음 전송 때 다시 검증을 시도한다.

**검증받지 못한 메시지에는 "검증 안 됨" 배지를 단다.** 팝업이 안 뜰 뿐이지, 그 사실은 나중에 스크롤해서 봐도 알 수 있어야 한다.

---

## 데이터 모델

### `messages.verification_status`

| 값 | 의미 |
|---|---|
| `ok` | 검증 통과 |
| `flagged_sent` | 부적절 판정, 사용자가 전송 강행 |
| `disabled` | 검증 토글이 꺼진 방 |
| `skipped_no_context` | 문맥 부족 (콜드 스타트) |
| `failed` | 검증을 시도했으나 에러/타임아웃 |
| `degraded` | 동의하에 검증을 아예 건너뜀 |

- `failed`와 `degraded`를 합치지 않는다. 합치면 "API가 얼마나 자주 실패했나"를 셀 때 degraded 구간이 섞여 장애 빈도가 과대 집계된다.
- 성능 집계는 `ok` + `flagged_sent`만 사용한다. 나머지는 제외해야 지표가 오염되지 않는다.

### 판정 로그 테이블 (별도)

**처음부터 넣는다.** 성능 테스트가 목적인데 메시지 테이블만 있으면 실험 데이터가 안 쌓인다.

| 컬럼 | 비고 |
|---|---|
| `message_id` | nullable — 사용자가 취소한 건 메시지가 없다 |
| `room_id` | |
| `context_from_seq` / `context_to_seq` | 실제로 모델에 넣은 문맥 범위 |
| `verdict` | 적절 / 부적절 |
| `confidence` | |
| `latency_ms` | |
| `prompt_tokens` / `completion_tokens` | 비용 추적 |
| `user_action` | `sent` / `cancelled` ← **사실상의 정답 라벨** |

취소된 메시지는 `messages`에 남지 않고 이 로그에만 남는다.

---

## 평가 시 주의

- **false positive가 치명적이다.** 멀쩡한 메시지에 팝업이 계속 뜨면 아무도 못 쓴다. recall보다 **precision을 우선 지표**로 본다.
- 검증이 꺼진 방의 메시지도 DB에 다 남으므로, 나중에 **오프라인 배치로 재판정을 돌려 "만약 켰다면 어땠을까"를 분석**할 수 있다. 실사용 로그가 그대로 추가 평가 데이터가 된다.

---

## 프라이버시

AI 검증이 켜진 방에서는 **최근 N개 메시지가 OpenAI API로 전송된다.** 데모 프로젝트이지만 이 사실을 사용자에게 고지한다.

---

## 미결정

- WebSocket 인증 방식 확정 (첫 프레임 auth vs 쿼리스트링 토큰)
- 판정 프롬프트 설계
- 판정 성능 집계의 정답 라벨 기준
- 데이터셋 구축 방법 및 라벨링 기준
- `N`(문맥 메시지 개수) 최종값
- 프론트엔드를 별도 컨테이너로 서빙할지, FastAPI가 정적 파일을 함께 서빙할지

Ideation에서 닫힌 항목은 위 목록에서 뺐다 — 프로젝트명(`career-jikimi`), 친구 등록
방식(단방향 즉시 + 별칭 필수), AI 검증 토글 단위(참여자 개인별), 내용 기준
필터링 배제, DB 선택(MariaDB).

> *(가정)* 표시된 항목은 반대 의견이 없어 잠정 결정한 것으로, 언제든 바꿀 수 있다.

---

## 실행

### `docker compose up` 한 번으로 (권장)

```bash
git clone <repo> && cd mini_project
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
# .env에서 JWT_SECRET과 OPENAI_API_KEY를 채운다 (둘 다 비어 있으면 앱이 기동하지 않는다)
docker compose up --build
```

접속: <http://localhost:8000>

- `JWT_SECRET` 생성: `python -c "import secrets; print(secrets.token_urlsafe(48))"`
- 기동 순서는 `db` healthy → `alembic upgrade head`(재시도 포함) → `uvicorn`(워커 1개)이다
- 상태 확인: `curl http://localhost:8000/health` → `{"status":"ok","db":"ok"}`
- DB는 호스트에 포트를 노출하지 않는다. 들여다보려면 `docker compose exec db mariadb -u root -p`
- 종료: `docker compose down` (데이터는 명명 볼륨에 남는다. 지우려면 `-v`)

**`.env`는 커밋되지 않는다.** 커밋되는 것은 `.env.example` 템플릿 하나뿐이다.

### 개발 중에는 두 프로세스로

프론트엔드를 고치면서 즉시 반영을 보려면 Vite dev 서버를 따로 띄운다.

```bash
# 1) DB만 컨테이너로
docker compose up -d db

# 2) 백엔드 (backend/)
python -m venv .venv && .venv/Scripts/activate   # Linux/macOS: source .venv/bin/activate
pip install -r requirements-dev.txt
#   .env의 DATABASE_URL 호스트를 db -> 127.0.0.1 로 바꾸고, db 포트를 노출해야 한다
#   CORS_ORIGINS=http://localhost:5173 을 설정한다 (비어 있으면 CORS가 붙지 않는다)
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# 3) 프론트엔드 (frontend/)
npm install
npm run dev        # http://localhost:5173, /auth·/rooms·/ws 등을 8000으로 프록시
```

### 테스트

```bash
# 백엔드 (backend/)
pytest
ruff check . && ruff format --check .

# 프론트엔드 (frontend/)
npm run typecheck && npm run build
npm test
```

`tests/test_schema.py`는 **실제 MariaDB**를 쓴다. `TEST_DATABASE_URL`이 없으면
skip된다 — SQLite로 대체하면 복합 PK와 `utf8mb4` 검증이 거짓 통과하기 때문이다.

```bash
# 예: 테스트 전용 DB를 하나 만들고
TEST_DATABASE_URL='mysql+asyncmy://root:<pw>@127.0.0.1:3306/career_jikimi_test?charset=utf8mb4' pytest
```

---

## 개발 워크플로

이 프로젝트는 [AI-DLC](https://github.com/awslabs/aidlc-workflows) v2로 진행한다.

```
/aidlc --doctor          # 설치 검증
/aidlc --status          # 진행 상황
```

산출물은 `aidlc/spaces/default/intents/260729-misdirect-message-guard/` 아래에 쌓인다.

**범위와 우선순위의 최종 권위는 이 README가 아니라 그 아래 산출물이다.**

| 문서 | 내용 |
|---|---|
| `ideation/intent-capture/intent-statement.md` | 문제 정의, 대상 사용자, 성공 지표, 일정 |
| `ideation/scope-definition/scope-document.md` | 경계(Must/Should/Won't), 위험 등록부 |
| `ideation/scope-definition/intent-backlog.md` | proto-Unit 목록과 의존 그래프 |

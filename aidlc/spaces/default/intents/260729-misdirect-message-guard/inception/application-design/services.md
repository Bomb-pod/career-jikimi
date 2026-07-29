# Services — career-jikimi

배포 단위로서의 서비스 정의다. `components.md`가 코드 수준의 경계를 다뤘다면 이 문서는 **프로세스와 컨테이너 수준**을 다룬다.

`../requirements-analysis/requirements.md`의 FR-9(컨테이너화)와 CON-1(단일 프로세스)이 이 문서의 뼈대다.

## 서비스 목록

이 시스템은 **서비스 두 개**로 구성된다. 마이크로서비스로 나누지 않는 이유는 `decisions.md` ADR-002에 있다.

| 서비스 | 역할 | 컨테이너 | 상태 |
|---|---|---|---|
| `app` | FastAPI — HTTP API + WebSocket + 정적 파일 서빙 | 1개 | **유상태** (WS 연결 레지스트리) |
| `db` | MariaDB | 1개 | 유상태 (볼륨) |

프론트엔드는 별도 서비스가 아니다. 빌드된 정적 파일을 `app`이 서빙한다 (FR-9.5). 개발 중에만 Vite dev 서버가 별도로 뜨며, 그건 배포 구성이 아니다.

## `app` 서비스

### 프로세스 모델

**uvicorn 워커 1개.** 이것은 성능 판단이 아니라 **정합성 요구**다.

```
+---------------------------------------------------+
|  app 컨테이너                                      |
|                                                    |
|  uvicorn (워커 1)                                  |
|    +-- FastAPI 앱                                  |
|    +-- ws_registry: dict[user_id, WebSocket]  <--+ |
|                                                  | |
|         이 dict가 프로세스 메모리에 있다          | |
|         워커를 늘리면 각 워커가 자기 dict를 갖고,  | |
|         다른 워커에 붙은 사용자에게 못 보낸다      | |
+---------------------------------------------------+
```

<!-- Text fallback: app 컨테이너 안에는 uvicorn 워커가 하나만 돌고, 그 안에 FastAPI 앱과 WebSocket 연결 레지스트리(user_id를 키로 하는 딕셔너리)가 있다. 이 딕셔너리가 프로세스 메모리에 있으므로 워커를 늘리면 각 워커가 별도의 딕셔너리를 갖게 되어, 다른 워커에 연결된 사용자에게 메시지를 보낼 수 없다. -->

컨테이너화가 이 제약을 **구조적으로** 지켜준다 — 컨테이너 하나에 프로세스 하나가 기본이고, 늘리려면 명시적으로 `--workers`를 쓰거나 `replicas`를 올려야 한다. 실수로 넘어가기 어렵다.

확장이 필요해지면 `core/ws_registry`만 Redis pub/sub으로 교체한다. 그 컴포넌트의 표면이 세 함수뿐인 것은 이 교체를 염두에 둔 것이다.

### 컨테이너 사양

`aidlc-aws-platform-agent` 관점의 컨테이너 체크리스트를 적용한다. 이 프로젝트에 클라우드는 없지만 컨테이너 위생은 그대로 유효하다.

| 항목 | 결정 |
|---|---|
| 베이스 이미지 | `python:3.12-slim` — 버전 고정, 최소 표면 |
| 멀티스테이지 빌드 | 사용. 빌드 의존성(컴파일러 등)을 런타임 이미지에서 제외 |
| 프론트엔드 빌드 | 별도 스테이지에서 `npm run build` → 결과물만 런타임 이미지로 복사 |
| 비루트 실행 | 전용 사용자 생성 후 그 사용자로 실행 |
| 헬스체크 | `GET /health` — DB 연결까지 확인하는 얕은 체크 |
| Graceful shutdown | SIGTERM 수신 시 새 연결을 막고, 열린 WebSocket을 닫고, 진행 중 요청을 끝낸 뒤 종료 |
| 로그 | stdout/stderr로만. 파일에 쓰지 않는다 |
| 비밀 | 환경변수로 주입. 이미지에 굽지 않는다 (FR-1.4, NFR-6) |
| 리소스 제한 | 데모 규모라 강제하지 않으나 compose에 주석으로 남긴다 |

**Graceful shutdown이 이 앱에서 특별한 이유** — 일반 HTTP 앱은 진행 중 요청만 끝내면 되지만, 이 앱은 **열려 있는 WebSocket이 있다.** 그냥 죽으면 클라이언트가 비정상 종료로 인식해 재연결을 시도하고, 그 사이 컨테이너가 아직 안 떴으면 오류가 뜬다. 종료 코드를 명시적으로 보내야 클라이언트가 조용히 기다린다.

### 기동 순서

```
db 컨테이너 시작
   |
   +-- healthcheck 통과 (mariadb-admin ping)
          |
          +-- app 컨테이너 시작 (depends_on: condition: service_healthy)
                 |
                 +-- Alembic upgrade head
                 |     +-- 실패 시 재시도 (DB가 healthy여도 초기화 중일 수 있다)
                 |
                 +-- uvicorn 기동
```

<!-- Text fallback: db 컨테이너가 먼저 시작하고 healthcheck를 통과하면, depends_on의 service_healthy 조건에 따라 app 컨테이너가 시작한다. app은 먼저 Alembic 마이그레이션을 적용하고(실패 시 재시도) 그 다음 uvicorn을 띄운다. -->

FR-9.2가 요구하는 순서다. **healthcheck만으로는 부족해서 재시도도 넣는다** — MariaDB는 ping에 응답하면서도 아직 초기화 스크립트를 돌리는 중일 수 있다.

## `db` 서비스

| 항목 | 결정 |
|---|---|
| 이미지 | `mariadb:11` — 버전 고정 |
| 문자셋 | `utf8mb4` / `utf8mb4_unicode_ci` **명시** — 기본값에 기대지 않는다 (FR-9.3) |
| 스토리지 엔진 | InnoDB (기본). 행 잠금이 `(room_id, seq)` 채번에 필요하다 (FR-4.2) |
| 볼륨 | 명명 볼륨. 컨테이너를 지워도 데이터가 남는다 |
| 헬스체크 | `mariadb-admin ping` |
| 포트 노출 | 호스트에 노출하지 않는다. `app`만 내부 네트워크로 접근 |
| 자격증명 | 환경변수. `.env` 파일은 커밋하지 않고 `.env.example`만 둔다 |

**포트를 노출하지 않는 것**이 이 데모의 유일한 네트워크 보안 조치다. DB를 직접 들여다보고 싶으면 `docker compose exec db mariadb`로 들어간다.

## 통신 계약

### `app` ↔ `db`

SQLAlchemy async + `asyncmy`. 커넥션 풀은 기본값을 쓴다 — 데모 규모에서 튜닝할 이유가 없다.

**트랜잭션 경계는 요청 하나 = 트랜잭션 하나**가 기본이며, 예외는 메시지 전송이다:

```
send_message 트랜잭션:
  BEGIN
    SELECT last_seq FROM rooms WHERE id = ? FOR UPDATE   -- 방 단위 잠금
    INSERT INTO messages (..., seq = last_seq + 1)
    UPDATE rooms SET last_seq = last_seq + 1
  COMMIT
  -- 커밋 이후에 브로드캐스트
```

판정(LLM 호출)은 **이 트랜잭션 밖**에서 먼저 끝난다. 3~5초짜리 외부 호출을 잠금 안에 넣으면 그동안 그 방의 모든 전송이 막힌다.

### `app` ↔ 브라우저

| 방향 | 채널 | 용도 |
|---|---|---|
| 브라우저 → 서버 | HTTP | 인증, 친구, 방, **메시지 전송**, 히스토리, 신고, 판정 라벨 |
| 서버 → 브라우저 | WebSocket | 메시지 푸시 (본인 것 포함 — 다른 탭·기기 동기화) |
| 브라우저 → 서버 (WS) | WebSocket | **인증 프레임 하나뿐** |

WebSocket 프레임 봉투:

```json
{ "type": "auth",    "token": "<jwt>" }
{ "type": "auth_ok" }
{ "type": "auth_error", "reason": "invalid_token" }
{ "type": "message", "room_id": 12, "message": { ...메시지 객체... } }
```

`type`을 최상위에 두고 나머지를 형제로 둔다. 중첩을 얕게 유지해 파싱 분기가 한 번에 끝나게 한다.

### `app` ↔ OpenAI API

| 항목 | 값 |
|---|---|
| 호출 시점 | 메시지 전송 요청 처리 중, DB 트랜잭션 **이전** |
| 타임아웃 | `AI_TIMEOUT_SECONDS` (3~5초) |
| 재시도 | 1회 (FR-8.1) |
| 응답 형식 | Structured Outputs, `strict: true` (ADR-005) |
| 실패 처리 | 예외가 아니라 `JudgeResult.Failed` 반환 |
| 전송 데이터 | 최근 `N`개 메시지 본문 + 후보 메시지. **참여자 식별 정보 없음** (FR-6.2) |

NFR-5(프라이버시 고지)에 따라 이 외부 전송 사실을 UI에 표시한다.

## 확장 특성

이 데모는 확장하지 않는다. 그래도 어디가 먼저 막히는지는 기록해둔다 — 나중에 이 문서를 읽는 사람이 "왜 이렇게 만들었나"를 물을 것이기 때문이다.

| 한계 | 원인 | 넘어서려면 |
|---|---|---|
| 동시 접속자 | 단일 프로세스 + 메모리 레지스트리 (CON-1) | `ws_registry`를 Redis pub/sub으로 교체 |
| 같은 방의 동시 전송 | `FOR UPDATE` 행 잠금이 방 단위로 직렬화 | 채번을 앱 레벨 시퀀스나 Snowflake ID로 교체 |
| 판정 처리량 | OpenAI API rate limit + 동기 차단 | 전송 전 차단이 요구사항이라 비동기화 불가. rate limit은 큐잉으로 완화 가능 |
| 히스토리 조회 | `(room_id, seq)` 인덱스로 커버됨 | 데모 규모에서 문제 없음 |

**"같은 방의 동시 전송"이 가장 먼저 막히는 곳**이지만, 이 앱의 성격상 한 방에서 초당 여러 명이 동시에 보내는 상황은 드물다. 그리고 방 단위 잠금이라 다른 방은 영향받지 않는다 (FR-4.2).

## Assumptions & Open Questions

- 개발 시 Vite dev 서버와 `app`이 별도 포트에서 돌므로 CORS가 필요하다(FR-9.5). 개발 프로파일에서만 켜야 하는데, compose 프로파일로 나눌지 환경변수로 분기할지 정하지 않았다.
- Graceful shutdown의 유예 시간(SIGTERM → SIGKILL)을 정하지 않았다. compose 기본값은 10초다.
- 헬스체크가 DB 연결까지 확인하면 DB가 잠깐 느릴 때 앱이 unhealthy로 표시된다. 얕은 체크(프로세스 살아있음)와 깊은 체크(DB 도달 가능)를 분리할지 정하지 않았다.
- `.env.example`에 넣을 항목 목록은 Code Generation에서 확정한다.

# Code Generation Plan — U1 foundation

`../../../inception/units-generation/unit-of-work.md`의 **U1 `foundation`** 을 구현하는 계획이다.

이 단위는 `kind: packaging`이라 `functional-design`(3.1)이 도메인 문서를 만들지 않았다. 따라서 근거는 다음에서 온다:

| 무엇 | 어디 |
|---|---|
| 대응 요구사항 | `../../../inception/requirements-analysis/requirements.md` — FR-9.1~FR-9.5, FR-1.4, NFR-6 |
| 컨테이너·프로세스·기동 순서 | `../../../inception/application-design/services.md` |
| `core/config`·`core/db` 공개 표면 | `../../../inception/application-design/components.md` |
| 스키마 관리 방식 | `../../../inception/application-design/decisions.md` — ADR-006 |
| **전체 스키마** | 형제 4개 단위의 `../../<unit>/functional-design/domain-entities.md` |
| 단위 경계 | `../../../inception/units-generation/unit-of-work.md` § U1 |

**이 단위가 소유하지 않는 것** — 비즈니스 로직은 하나도 없다. `auth`·`friends`·`rooms`·`messages`·`judgment` 모듈의 내용은 U2~U5가 채운다. 여기서는 그것들이 설 **바닥**만 만든다.

---

## 스택 확정

`components.md`가 "구체적 도구 선택은 Code Generation에서 정한다"고 남긴 항목을 여기서 닫는다.

| 항목 | 선택 | 근거 |
|---|---|---|
| Python | 3.12 | `services.md` 베이스 이미지 `python:3.12-slim` |
| 웹 프레임워크 | FastAPI + uvicorn (워커 1) | FR-9.4, CON-1 |
| ORM | SQLAlchemy 2.x async | `services.md` § app↔db |
| DB 드라이버 | `asyncmy` | 같은 곳 |
| 마이그레이션 | Alembic (async `env.py`) | ADR-006 |
| 설정 | pydantic-settings v2 | `components.md` — "타입이 붙은 설정 객체" |
| 의존성 관리 | `requirements.txt` (버전 고정) | 1인 6일. poetry/uv의 락파일 이득이 설정 비용을 넘지 않는다 |
| 린터·포매터 | ruff (lint + format) | `org.md` § Code Style이 프로젝트 설정에 위임. ruff 하나가 black+isort+flake8을 대체한다 |
| 테스트 | pytest + pytest-asyncio | |
| 프론트 | React 18 + TypeScript + Vite | `components.md`, FR-9.5 |
| 프론트 상태 | Zustand | ADR-004 |
| 프론트 테스트 | vitest | Vite와 설정을 공유한다 |

### 디렉터리 구조

```
mini_project/
  backend/
    app/
      main.py                 # FastAPI 앱, 라우터 등록 지점, /health
      core/
        config.py             # settings 싱글턴
        db.py                 # 엔진, 세션 팩토리, Base, get_session()
        errors.py             # 도메인 예외 기반 클래스 + 라우터 변환 지점
      models/                 # SQLAlchemy 모델 (테이블 6개)
        __init__.py
        user.py  friendship.py  room.py  room_member.py
        message.py  judgment_log.py
      auth/  friends/  rooms/  messages/  judgment/   # U2~U5가 채운다 (빈 패키지)
    migrations/
      env.py                  # async 구성
      versions/0001_initial_schema.py
    alembic.ini
    requirements.txt
    pyproject.toml            # ruff + pytest 설정
    tests/
      conftest.py
      test_config.py  test_health.py  test_schema.py
  frontend/
    src/
      main.tsx  App.tsx
      lib/  store/  views/     # U3~U5가 채운다
    index.html  package.json  tsconfig.json  vite.config.ts
    vitest.config.ts
  Dockerfile                  # 멀티스테이지 (frontend build → python runtime)
  docker-compose.yml
  .env.example
  .dockerignore
```

**`backend/`와 `frontend/`로 갈라놓는 이유** — Dockerfile의 멀티스테이지가 두 스테이지에서 서로 다른 디렉터리만 복사하면 되어 캐시 무효화가 서로 번지지 않는다. 프론트 파일 하나 고쳤을 때 pip install이 다시 돌지 않는다.

---

## 이 계획이 닫는 열린 항목

`services.md`가 Code Generation으로 넘긴 것들이다.

| 열린 항목 | 결정 | 근거 |
|---|---|---|
| CORS를 compose 프로파일로 나눌지 환경변수로 분기할지 | **환경변수** `CORS_ORIGINS` (비어 있으면 CORS 미들웨어를 아예 붙이지 않음) | `components.md`의 `settings` 표면에 `CORS_ORIGINS`가 이미 있다. 프로파일을 새로 만들면 설정이 두 곳으로 갈라진다 |
| Graceful shutdown 유예 시간 | compose에 `stop_grace_period: 15s` 명시 | 기본 10초는 열린 WebSocket을 닫고 진행 중 요청을 끝내기에 빡빡하다. 명시하면 왜 그 값인지 남는다 |
| 헬스체크의 얕은/깊은 분리 | **하나만 둔다.** `GET /health`가 `SELECT 1`을 2초 타임아웃으로 확인 | `services.md`가 "DB 연결까지 확인하는 얕은 체크"로 이미 정했다. 데모 규모에서 두 엔드포인트를 나눌 값어치가 없고, 타임아웃이 짧아 DB가 잠깐 느릴 때의 오탐도 억제된다 |
| `.env.example` 항목 목록 | 아래 표로 확정 | |

### `.env.example` 확정 목록

| 키 | 기본값 | 누가 쓰나 |
|---|---|---|
| `DATABASE_URL` | `mysql+asyncmy://app:app@db:3306/career_jikimi?charset=utf8mb4` | core/db |
| `JWT_SECRET` | *(빈 값 — 필수)* | U3 auth |
| `JWT_ALGORITHM` | `HS256` | U3 auth |
| `JWT_EXPIRE_MINUTES` | `1440` | U3 auth |
| `OPENAI_API_KEY` | *(빈 값 — 필수)* | U2 judgment |
| `OPENAI_MODEL` | `gpt-4o-mini` | U2 judgment (ADR-005 — 지원 여부는 U2가 확인) |
| `AI_CONTEXT_N` | `10` | U2 (FR-6.2) |
| `AI_VERDICT_THRESHOLD` | `0.7` | U2 (FR-6.3) |
| `AI_TIMEOUT_SECONDS` | `5` | U2 (FR-8.1) |
| `CORS_ORIGINS` | *(빈 값 = 미적용)* | main.py (FR-9.5) |
| `MARIADB_ROOT_PASSWORD` / `MARIADB_DATABASE` / `MARIADB_USER` / `MARIADB_PASSWORD` | 데모 값 | db 컨테이너 |

`JWT_SECRET`과 `OPENAI_API_KEY`는 **기본값을 주지 않는다.** 비어 있으면 앱이 기동 시 즉시 실패한다 — 조용히 빈 키로 도는 것보다 낫다 (FR-1.4, NFR-6).

---

## 스키마 — 테이블 6개

초기 마이그레이션 하나가 전부를 만든다. 근거는 형제 단위의 `domain-entities.md`이며, **U1은 구조만 만들고 어떤 테이블도 읽거나 쓰지 않는다.**

| 테이블 | 출처 | 핵심 제약 |
|---|---|---|
| `users` | auth-friends | `username` UNIQUE |
| `friendships` | auth-friends | `alias` NOT NULL, `UNIQUE (owner_id, friend_id)` |
| `rooms` | rooms-realtime | `last_seq` NOT NULL DEFAULT 0 |
| `room_members` | rooms-realtime | 복합 PK `(room_id, user_id)`, `INDEX (user_id)` |
| `messages` | messaging | `UNIQUE (room_id, seq)`, `INDEX (room_id, seq DESC)` |
| `judgment_logs` | judgment-core | `message_id`·`score`·`verdict`·`user_action` NULL 허용 |

생성 순서는 FK 방향을 따른다: `users` → `friendships` → `rooms` → `room_members` → `messages` → `judgment_logs`.

**모든 테이블에 `CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci`를 명시한다** (FR-9.3). 서버 기본값에 기대지 않는다.

---

## 실행 단계

### Step 1 — 프로젝트 골격
- [x] `backend/` 디렉터리와 빈 패키지(`app/`, `app/core/`, `app/models/`, `app/{auth,friends,rooms,messages,judgment}/`) 생성
- [x] `backend/requirements.txt` — 버전 고정
- [x] `backend/pyproject.toml` — ruff(line-length 100, target py312) + pytest-asyncio 설정
- [x] `.dockerignore`, `.gitignore` 갱신(`.env`, `__pycache__`, `node_modules`, `dist`)
- 대응: FR-9.1

### Step 2 — `core/config`
- [x] `app/core/config.py` — pydantic-settings `Settings` + `settings` 싱글턴
- [x] `.env.example` 항목 전부 반영, `JWT_SECRET`·`OPENAI_API_KEY`는 필수(빈 값이면 기동 실패)
- [x] `os.environ` 직접 읽기가 이 파일 밖에 없도록 유지
- 대응: FR-1.4, NFR-6, FR-9.5(`CORS_ORIGINS`)

### Step 3 — `core/db`
- [x] `app/core/db.py` — async 엔진, `async_sessionmaker`, `Base`(DeclarativeBase), `get_session()` 의존성
- [x] 기동 시 DB 연결 재시도: 지수 백오프, 최대 30초 (FR-9.2)
- [x] `app/core/errors.py` — `DomainError` 기반 클래스와 HTTP 상태 매핑 테이블의 빈 골격 (U2~U5가 자기 예외를 등록)
- 대응: FR-9.2

### Step 4 — SQLAlchemy 모델 6개
- [x] `app/models/` 아래 테이블당 한 파일. 컬럼·타입·제약·인덱스를 형제 단위의 `domain-entities.md` 표 그대로
- [x] `__table_args__`에 `mysql_charset='utf8mb4'`, `mysql_collate='utf8mb4_unicode_ci'` 명시
- [x] `app/models/__init__.py`에서 전부 import — Alembic autogenerate가 보게 한다
- 대응: 전체 스키마 (FR-9.3)

### Step 5 — Alembic
- [x] `backend/alembic.ini`, `backend/migrations/env.py`(async — `connection.run_sync(context.run_migrations)`)
- [x] `migrations/versions/0001_initial_schema.py` — 테이블 6개를 FK 순서로 생성, `downgrade()`는 역순 drop
- [x] `alembic upgrade head`가 빈 DB에서 성공하고 두 번 돌려도 안전한지 확인 — 오프라인 DDL(`upgrade head --sql`)로 6개 테이블·모든 제약·`CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci` 확인 완료. 실제 DB 적용과 2회 실행 멱등성은 `tests/conftest.py`의 `migrated_database` 픽스처가 검증하며, 이 환경에 MariaDB가 없어 **skip** 상태다
- 대응: ADR-006

### Step 6 — FastAPI 앱과 `/health`
- [x] `app/main.py` — 앱 생성, lifespan(시작 시 DB 연결 확인, 종료 시 정리), `GET /health`
- [x] `/health` → `{"status":"ok","db":"ok"}` / DB 실패 시 503
- [x] `CORS_ORIGINS`가 비어 있지 않을 때만 CORSMiddleware 등록 (FR-9.5)
- [x] 빌드된 프론트 정적 파일 서빙: `static/` 디렉터리가 존재할 때만 마운트 + SPA 폴백 (FR-9.5)
- [x] U2~U5 라우터를 등록할 지점을 주석으로 표시 — 정적 SPA 폴백이 catch-all이라 라우터가 **그보다 먼저** 등록되어야 한다는 경고를 함께 남겼다
- 대응: FR-9.5, `services.md` 컨테이너 사양

### Step 7 — 백엔드 테스트
Test Strategy는 **Standard** (`aidlc-state.md`). 컴포넌트당 5~8개 + 경계 통합 테스트.
- [x] `tests/conftest.py` — SQLite 인메모리가 아니라 **테스트용 MariaDB 세션 픽스처**(DB 미가용 시 skip). MariaDB 전용 제약(복합 PK, `FOR UPDATE`)을 SQLite로 검증하면 거짓 통과한다
- [x] `test_config.py` — 필수 키 누락 시 기동 실패, 기본값, `CORS_ORIGINS` 파싱, 비밀이 repr에 노출되지 않음 (23개, 파라미터화 포함)
- [x] `test_health.py` — 200/구조/DB 실패 시 503 (9개 — `/health` 3개 + `check_database` 3개 + `wait_for_database` 재시도 3개)
- [x] `test_schema.py` — 6개 테이블 존재, `utf8mb4` 적용, `UNIQUE (room_id, seq)`·`UNIQUE (owner_id, friend_id)`·복합 PK 강제, `alias` NOT NULL, 한글·이모지 왕복 (13개, FR-9.3의 수용 기준)
- [x] `pytest`가 통과 — **32 passed, 13 skipped**. skip은 전부 `test_schema.py`이며 이 환경에 MariaDB가 없다(Docker 데몬 미기동). `TEST_DATABASE_URL`을 주면 그대로 돈다

### Step 8 — 프론트엔드 골격
- [x] `frontend/package.json`(react, react-dom, zustand, typescript, vite, vitest, @testing-library/react)
- [x] `vite.config.ts` — dev 프록시로 백엔드 경로와 `/ws`를 넘김, 빌드 산출물은 `dist/`
      **계획 수정**: `/api` 접두사를 쓰지 않는다. `components.md`가 엔드포인트를 `POST /auth/signup`처럼 접두사 없이 확정했으므로, 프록시용 `/api`를 새로 만들면 개발과 배포의 경로가 갈라진다. 대신 실제 최상위 접두사 목록(`/auth`·`/users`·`/friends`·`/rooms`·`/messages`·`/judgments`·`/health`)과 `/ws`(`ws: true`)를 프록시한다
- [x] `tsconfig.json`(strict), `index.html`, `src/main.tsx`, `src/App.tsx`(뷰 전환 자리만)
- [x] `src/{lib,store,views}/` 빈 디렉터리 + `.gitkeep` — 각 `.gitkeep`에 그 디렉터리를 누가 무엇으로 채우는지 적었다
- [x] `vitest.config.ts` + `src/App.test.tsx` 스모크 1개 (테스트 6개: 마운트·기본 화면·전환·같은 탭 재클릭·한 번에 한 화면·미구현 안내)
- [x] `npm run build`가 통과 — `tsc --noEmit` + `vite build` 모두 통과, `npx vitest run` 6/6 통과
- 대응: FR-9.5

### Step 9 — 컨테이너화
- [x] `Dockerfile` 멀티스테이지: ① `node:22-alpine`에서 프론트 빌드 ② `python:3.12-slim` 런타임에 백엔드 + ①의 `dist`를 `static/`으로 복사
      **스테이지를 3개로 늘렸다**: ①`frontend-build` ②`python-build`(gcc로 wheel 빌드 — `asyncmy`·`httptools`가 C 확장이다) ③`runtime`(`--no-index`로 wheel만 설치, 컴파일러 없음). 계획의 "빌드 의존성을 런타임 이미지에서 제외"를 실제로 달성하려면 wheel 스테이지가 필요하다
- [x] 비루트 사용자 생성 후 전환(`appuser`, uid 10001), `HEALTHCHECK`에 `/health` (slim에 curl이 없어 `python -c urllib`로 확인)
- [x] 엔트리포인트: `alembic upgrade head`(재시도 포함) → `uvicorn --workers 1` — `backend/docker-entrypoint.sh`
- [x] SIGTERM 처리 — `exec`으로 uvicorn을 PID 1로 만들고 `--timeout-graceful-shutdown 10`을 `stop_grace_period: 15s` 안쪽에 둔다. `.gitattributes`로 `*.sh`를 LF에 고정했다 (CRLF 셔뱅은 컨테이너에서 "no such file or directory"로 죽는다)
- 대응: FR-9.1, FR-9.2, FR-9.4, `services.md`

### Step 10 — docker-compose
- [x] `db`: `mariadb:11`, `utf8mb4`/`utf8mb4_unicode_ci` 커맨드 인자로 명시, 명명 볼륨, `mariadb-admin ping` 헬스체크, **호스트 포트 미노출**
- [x] `app`: 위 Dockerfile 빌드, `depends_on: db: condition: service_healthy`, `env_file: .env`(`required: true`), `stop_grace_period: 15s`, 리소스 제한은 주석으로 (`replicas`를 올리면 안 되는 이유도 함께)
- [x] `docker compose config`가 통과 — exit 0, stderr 없음. `.env`가 없을 때는 `MARIADB_ROOT_PASSWORD is missing a value`로 **실패**하는 것까지 확인했다(조용히 빈 값으로 뜨지 않는다)
- 대응: FR-9.1, FR-9.2, FR-9.3

### Step 11 — 문서
- [x] `backend/README.md`·`frontend/README.md` 대신 루트 `README.md`에 **실행 절**만 추가(clone → `.env` 작성 → `docker compose up` → 접속). 기존 설계 서술은 건드리지 않는다 — "개발 워크플로" 절 바로 위에 삽입했고 그 위의 모든 내용은 그대로다
- [x] `core/config.py`·`core/db.py`·모델의 비자명한 제약에 인라인 주석 (왜 `utf8mb4`를 명시하는지, 왜 `last_seq`를 U5가 증가시키는지)

---

## 요구사항 → 단계 추적

| FR/NFR | 단계 |
|---|---|
| FR-9.1 `docker compose up` 한 번 | 1, 9, 10 |
| FR-9.2 DB healthy 후 기동 + 재시도 | 3, 9, 10 |
| FR-9.3 `utf8mb4` | 4, 5, 10 / 검증 7 |
| FR-9.4 단일 uvicorn 워커 | 9 |
| FR-9.5 개발 Vite / 배포 정적 서빙 | 2, 6, 8, 9 |
| FR-1.4 · NFR-6 비밀은 환경변수로만 | 2 / 검증 7 |
| 전체 스키마 (U2~U5의 전제) | 4, 5 / 검증 7 |

`unit-of-work-dependency.md`가 정한 U1의 제공 계약 — `settings` 싱글턴, `get_session()` 의존성, `Base` — 는 Step 2·3이 만든다. 이 셋의 이름과 시그니처는 U2~U5가 그대로 import하므로 **바꾸면 네 단위가 전부 깨진다.**

## 계획에서 뺀 것

- **비즈니스 로직 전부.** `auth`·`friends`·`rooms`·`messages`·`judgment`는 빈 패키지로만 만든다
- **CI 파이프라인** — `ci-pipeline`(3.7)이 스코프에서 제외되었다
- **원격 배포·이미지 레지스트리** — `requirements.md` § Out of Scope
- **프론트 화면** — `AuthView` 등은 U3~U5 소관. Step 8은 골격뿐이다

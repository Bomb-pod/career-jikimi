# Build Instructions — career-jikimi

다섯 단위의 `../<unit>/code-generation/code-generation-plan.md`와 `../<unit>/code-generation/code-summary.md`가 정한 스택과 실행 경로를 하나로 모은 것이다. **여기 적힌 명령은 전부 실제로 돌려본 것이다** — 결과는 `build-test-results.md`에 있다.

배포 형태의 권위는 `../../inception/application-design/services.md`, 요구사항은 `../../inception/requirements-analysis/requirements.md`의 FR-9다.

## 전제 조건

| 항목 | 값 | 확인 |
|---|---|---|
| Docker | Desktop 실행 중 (`docker info` 성공) | `docker info --format '{{.ServerVersion}}'` |
| Python | 3.12 (로컬 테스트용. 컨테이너는 자체 포함) | `python --version` |
| Node | 22 (로컬 프론트 작업용. 컨테이너는 자체 포함) | `node --version` |
| 포트 | 8000 비어 있어야 함. db는 호스트에 노출하지 않는다 | |

**로컬 파이썬 없이도 앱은 돈다.** `docker compose up` 하나면 되며(FR-9.1), 로컬 설치는 테스트를 돌릴 때만 필요하다.

## 환경 설정

```bash
cp .env.example .env          # PowerShell: Copy-Item .env.example .env
```

`.env`에서 채워야 하는 것:

| 키 | 필수 | 비고 |
|---|---|---|
| `JWT_SECRET` | **필수** | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `OPENAI_API_KEY` | **필수** | 없으면 앱이 기동하지 않는다. 판정 없이 화면만 보려면 아무 문자열이나 넣어도 기동은 된다 |
| `TEST_DATABASE_URL` | 선택 | 비우면 실제 DB가 필요한 테스트가 **skip된다.** 아래 § 테스트 DB 참조 |

**비어 있으면 기동 즉시 실패한다** (FR-1.4, NFR-6). 조용히 빈 키로 도는 것보다 낫다는 판단이며, `backend/app/core/config.py`가 그것을 강제한다.

`.env`는 커밋되지 않는다. `.env.example`만 저장소에 있다.

## 컨테이너 빌드와 기동

```bash
docker compose up -d --build
```

일어나는 일 (`services.md` § 기동 순서):

```
db 컨테이너 시작
  +-- mariadb-admin ping 통과
        +-- app 컨테이너 시작 (depends_on: condition: service_healthy)
              +-- alembic upgrade head   (재시도 포함)
              +-- uvicorn --workers 1
```

Dockerfile은 **3스테이지**다 — `node:22-alpine`에서 프론트 빌드 → `python:3.12-slim`에서 wheel 빌드 → `python:3.12-slim` 런타임이 `--no-index`로 설치. 중간 스테이지가 없으면 `asyncmy`·`httptools`의 C 확장 때문에 빌드 도구가 런타임 이미지에 남는다.

### 빌드 확인

```bash
docker compose ps                                   # 둘 다 (healthy)
curl http://localhost:8000/health                   # {"status":"ok","db":"ok"}
curl -o /dev/null -w '%{http_code}\n' http://localhost:8000/   # 200 (SPA)
```

## 로컬 개발 빌드

컨테이너를 매번 다시 굽지 않고 고칠 때 쓴다.

### 백엔드

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Linux/macOS: .venv/bin/python
```

`requirements.txt`와 `requirements-dev.txt`는 **ASCII 전용이다.** pip이 Windows에서 로케일 코드페이지로 읽어, 한글 주석이 있으면 한국어 Windows(cp949)에서 의존성 해석 전에 `UnicodeDecodeError`가 난다. 주석을 고칠 때 이 제약을 지킨다.

### 프론트엔드

```bash
cd frontend
npm install
npm run build      # dist/
npm run dev        # Vite dev 서버 :5173, /auth·/rooms·/friends·/ws를 :8000으로 프록시
```

dev 서버를 쓸 때만 `.env`에 `CORS_ORIGINS=http://localhost:5173`을 넣는다. 배포 구성에서는 FastAPI가 같은 오리진에서 서빙하므로 **비워둔다** (FR-9.5).

## 테스트 DB

스키마·API 테스트는 **실제 MariaDB**를 쓴다. SQLite로 대체하지 않는다 — 복합 PK, `utf8mb4` 지정, ENUM, `DATETIME(6)`, `SELECT ... FOR UPDATE`가 전부 MariaDB 전용 성질이고, SQLite로 검증하면 그중 어느 것도 실제로 확인되지 않으면서 테스트는 초록이 된다.

```bash
docker run -d --name cj-testdb \
  -e MARIADB_ROOT_PASSWORD=testpw -e MARIADB_DATABASE=career_jikimi_test \
  -p 33061:3306 mariadb:11 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
```

`.env`의 `TEST_DATABASE_URL`을 그 DB로 맞춘다:

```
TEST_DATABASE_URL=mysql+asyncmy://root:testpw@127.0.0.1:33061/career_jikimi_test?charset=utf8mb4
```

`backend/tests/conftest.py`가 저장소 루트 `.env`를 읽어 이 값을 채운다. **없으면 해당 테스트들이 조용히 skip된다** — 통과처럼 보이는 미검증이 검증 없음보다 나쁘므로, skip 개수를 항상 확인한다(`pytest -rs`).

## 자주 겪는 문제

| 증상 | 원인 | 조치 |
|---|---|---|
| `ValidationError: 3 validation errors for Settings` | `.env`에 `DATABASE_URL`·`JWT_SECRET`·`OPENAI_API_KEY`가 비었다 | 세 값을 채운다. **의도된 fail-fast다** (FR-1.4) |
| `pip install`이 `UnicodeDecodeError` | requirements 파일에 비-ASCII가 들어갔다 | ASCII로 되돌린다 |
| `alembic`이 `UnicodeDecodeError` | `alembic.ini`에 비-ASCII가 들어갔다 | 같은 이유. 이 파일도 ASCII 전용이다 |
| pytest가 대량 skip | `TEST_DATABASE_URL`이 비었거나 테스트 DB가 안 떠 있다 | 위 § 테스트 DB |
| `/ws`가 즉시 닫힘 | 첫 프레임이 `{"type":"auth","token":...}`가 아니다 | 연결 직후 5초 안에 auth 프레임을 보낸다 (FR-1.3) |
| 실시간 수신이 멈춤 | 같은 계정으로 다른 탭이 접속했다 | 사용자당 연결 1개다 (FR-5.1). 배너의 안내대로 새로고침 |
| 컨테이너에 새 코드가 없음 | 이미지에 구워 넣는 구성이라 바인드 마운트가 없다 | `docker compose up -d --build` |

## 정리

```bash
docker compose down          # 볼륨은 남는다
docker compose down -v       # DB 데이터까지 삭제
docker rm -f cj-testdb       # 테스트 DB
```

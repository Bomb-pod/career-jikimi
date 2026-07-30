# Code Summary — U1 foundation

`code-generation-plan.md`의 11단계를 `aidlc-developer-agent`가 실행한 결과다. 계획 파일의 체크박스 41개가 모두 `[x]`이며, 계획과 달라진 곳은 그 파일에 인라인으로 주석이 붙어 있다.

## 생성된 파일

### 루트 — 컨테이너와 설정

| 파일 | 내용 |
|---|---|
| `Dockerfile` | **3스테이지**: `node:22-alpine` 프론트 빌드 → `python:3.12-slim` wheel 빌드 → `python:3.12-slim` 런타임(`--no-index`). 비루트 `appuser`(uid 10001), `HEALTHCHECK`는 `/health` |
| `docker-compose.yml` | `db`(mariadb:11, `utf8mb4`/`utf8mb4_unicode_ci` 커맨드 인자, 명명 볼륨, `mariadb-admin ping`, **호스트 포트 미노출**) + `app`(`depends_on: service_healthy`, `env_file required: true`, `stop_grace_period: 15s`) |
| `.env.example` | 계획의 키 목록 그대로. `JWT_SECRET`·`OPENAI_API_KEY`는 빈 값 + 선택적 `TEST_DATABASE_URL` |
| `.dockerignore` / `.gitattributes` / `.gitignore`(수정) | `.gitattributes`는 `*.sh`를 LF로 고정 — CRLF shebang은 컨테이너에서 죽는다 |
| `README.md`(수정) | "실행" 절을 "개발 워크플로" 위에 삽입. 그 위의 설계 서술은 손대지 않았다 |

### 백엔드

| 파일 | 내용 |
|---|---|
| `backend/app/core/config.py` | `Settings` + `settings` 싱글턴. `DATABASE_URL`·`JWT_SECRET`·`OPENAI_API_KEY`는 기본값 없음, 비밀은 `SecretStr`, 공백만 있는 값도 거부 |
| `backend/app/core/db.py` | `Base`(명명 규칙 포함), `get_session()`, `TABLE_KWARGS`, `wait_for_database()`(지수 백오프 30초), `check_database()`(2초 타임아웃, 예외 안 던짐), `dispose_engine()` |
| `backend/app/core/errors.py` | `DomainError` + `NotFound`/`Forbidden`/`Conflict`/`ValidationFailed` + `register_error_handlers()` |
| `backend/app/main.py` | lifespan(기동 시 DB 대기, 종료 시 dispose), `GET /health`(200/503), 조건부 CORS, SPA 정적 서빙(경로 탈출 방어), U2~U5 라우터 등록 지점 |
| `backend/app/models/*.py` | 테이블 6개 — `user`·`friendship`·`room`·`room_member`·`message`·`judgment_log` |
| `backend/migrations/` | async `env.py` + `versions/0001_initial_schema.py` |
| `backend/docker-entrypoint.sh` | alembic 재시도 루프 → `exec uvicorn --workers 1 --timeout-graceful-shutdown 10` |
| `backend/tests/` | `conftest.py`·`test_config.py`·`test_health.py`·`test_schema.py` |
| `backend/app/{auth,friends,rooms,messages,judgment}/__init__.py` | **빈 패키지.** docstring에 어느 단위가 채우는지만 적혀 있다 |
| `requirements.txt` / `requirements-dev.txt` / `pyproject.toml` / `alembic.ini` | 런타임 이미지가 pytest·ruff를 설치하지 않도록 dev를 분리했다 |

### 프론트엔드

`package.json`·`package-lock.json`·`tsconfig.json`·`vite.config.ts`·`vitest.config.ts`·`index.html`, `src/{main.tsx,App.tsx,App.test.tsx,index.css,setupTests.ts}`, `src/{lib,store,views}/.gitkeep`.

## 핵심 구현 결정

| 결정 | 근거 |
|---|---|
| **`DATABASE_URL`도 필수로 — 두 비밀뿐이 아니다** | FR-1.4가 "DB 접속 정보"를 비밀로 명시하고, 그 수용 기준이 저장소 전체 리터럴 검색이다. `config.py`에 기본값을 주면 그게 소스 안의 비밀번호 리터럴이 된다. 데모 자격증명은 `.env.example`에만 있다 |
| `CORS_ORIGINS`를 `list[str]`이 아니라 `str`로 | pydantic-settings가 복합 타입을 env에서 JSON으로 파싱하므로 `http://a,http://b`가 예외를 던진다. `cors_origins` 프로퍼티가 파싱한다 |
| `alembic.ini`만 ASCII로 | Alembic이 이 파일을 `encoding="locale"`로 읽어, 한국어 Windows(cp949)에서 alembic 시작 전에 `UnicodeDecodeError`가 났다. 한국어 근거는 항상 UTF-8로 읽히는 `env.py`·마이그레이션에 남겼다 |
| Vite 프록시가 `/api`가 아니라 실제 경로 접두어를 대상으로 | `components.md`가 `POST /auth/signup` 형태로 엔드포인트를 확정했다. dev 프록시용 `/api`를 발명하면 dev와 prod 경로가 갈라진다 |
| Dockerfile 3스테이지 | 계획의 "빌드 의존성을 런타임 이미지에서 제외"는 별도 `pip wheel` 스테이지가 있어야 실제로 달성된다 — `asyncmy`·`httptools`가 C 확장이다 |
| `/health`의 DB 프로브를 FastAPI 의존성(`db_health_probe`)으로 | DB 없이도 200과 503 양쪽을 테스트할 수 있다 |
| vitest `^3` (계획은 버전 미지정) | vitest 2.x가 자체 vite 5를 중첩해 vite 6과 `PluginOption` 타입 충돌이 났다. vitest 3은 vite 6으로 dedupe된다 |

## 테스트 커버리지

Test Strategy **Standard**.

| 파일 | 개수 | 결과 |
|---|---|---|
| `test_config.py` | 필수 키 누락 시 기동 실패·기본값·`CORS_ORIGINS` 파싱·비밀 미노출 | **통과** |
| `test_health.py` | 200 / 구조 / DB 실패 시 503 | **통과** |
| `test_schema.py` | 테이블 6개·`utf8mb4`·`UNIQUE (room_id, seq)`·`UNIQUE (owner_id, friend_id)`·복합 PK·`alias` NOT NULL·한글/이모지 왕복·마이그레이션 2회 멱등성 | **13건 전부 SKIP** |
| `frontend/src/App.test.tsx` | 스모크 | **통과 (6/6)** |

**백엔드 합계: 32 통과 / 13 skip.**

## 검증 결과 — 있는 그대로

| 명령 | 결과 |
|---|---|
| `ruff check .` / `ruff format --check .` | PASS (24 파일) |
| `python -c "import app.main"` | PASS. 라우트 5개, 메타데이터에 테이블 6개. 필수 env 없을 때 `ValidationError` 3건으로 **즉시 실패**하는 것도 확인 (FR-1.4·NFR-6) |
| `alembic upgrade head --sql` (오프라인 DDL) | PASS. FK 순서대로 6개 테이블, 전부 `CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci`로 끝남. 복합 PK·`UNIQUE (room_id, seq)`·`(room_id, seq DESC)` 인덱스·ENUM 3종 확인 |
| `pytest` | 32 passed, **13 skipped** |
| `npm install` / `npm run typecheck` / `npm run build` / `npx vitest run` | 전부 PASS |
| `docker compose config` | PASS. `.env` 없을 때 exit 1로 실패하는 것도 확인 |
| FR-1.4 저장소 리터럴 검색 | PASS |
| `docker build` | **미실행** — Docker 데몬이 떠 있지 않다 |
| `docker run mariadb:11` | **실행 실패** — 같은 이유 |

## 계획과의 차이

| 차이 | 이유 |
|---|---|
| Dockerfile 2스테이지 → **3스테이지** | 위 표 참조 |
| `requirements-dev.txt` 추가 (계획의 파일 목록에 없음) | 런타임 이미지가 pytest·ruff를 설치하지 않게 |
| `.gitattributes` 추가 (계획에 없음) | `*.sh`의 CRLF가 컨테이너에서 shebang을 깨뜨린다 |
| `TEST_DATABASE_URL`을 `.env.example`에 추가 | 스키마 테스트를 돌릴 경로를 문서화 |

## 미해결 — 다음 단계가 반드시 확인할 것

1. **스키마 테스트 13건이 실제 MariaDB에서 한 번도 돌지 않았다.** 이 환경에 Docker 데몬이 없어 전부 skip이다. FR-9.3의 한글·이모지 왕복, 복합 PK 강제, `alembic upgrade head` 2회 멱등성이 **DDL 문자열로만 확인**된 상태다. **U2~U5가 이 스키마 위에 쌓기 전에** `TEST_DATABASE_URL=... pytest`를 실제 DB에 돌려야 한다. `build-and-test`(3.6)의 첫 항목이 이것이다
2. **`docker build`와 `docker compose up`이 미실행이다.** FR-9.1의 수용 기준("추가 수동 절차 없이 접속할 수 있다")이 아직 증거를 갖지 못했다. `requirements.txt`의 모든 핀이 개별 설치에 성공했고 `package-lock.json`이 musl 플랫폼 변종 22개를 담고 있어 부분적으로만 위험이 낮아진 상태다
3. **U2~U5가 알아야 하는 계약 두 가지** — ① `get_session()`은 핸들러 성공 시 자동 커밋한다. U5의 전송 경로는 브로드캐스트 **전에** 명시적으로 커밋해야 하고(`services.md`), 그러면 외부 커밋이 no-op이 된다 ② `settings.JWT_SECRET`·`OPENAI_API_KEY`가 `SecretStr`이므로 호출자는 `.get_secret_value()`를 써야 한다
4. `messages`에 `UNIQUE (room_id, seq)`와 `INDEX (room_id, seq DESC)`가 둘 다 있어 MariaDB가 중복 인덱스 note를 낼 수 있다. 둘 다 `messaging/domain-entities.md`가 지정한 것이라 그대로 두었다
5. 타입체크 센서가 `frontend/`를 cwd로 돌면 `frontend/aidlc/.../*.tsbuildinfo`를 남긴다. 지웠으나 `.gitignore`의 글롭이 저장소 루트 `aidlc/`에 고정되어 있어 재발 가능하다

## 커밋 상태

아무것도 커밋되지 않았다. `backend/`·`frontend/`·루트 컨테이너 파일이 untracked, `.gitignore`·`README.md`가 modified 상태다.

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

Adversarial pass. I diffed every column of all six tables against the four sibling `domain-entities.md` files, reproduced every verification command myself (not trusting the summary's table), and searched the actual generated code for secrets. No blocking finding survived. Two non-blocking findings below are things I found independently that the summary does not disclose; everything the summary does claim, I reproduced exactly.

### Schema fidelity — verified column-by-column, no defect found

I diffed `backend/app/models/{user,friendship,room,room_member,message,judgment_log}.py`, `backend/migrations/versions/0001_initial_schema.py`, and the output of `alembic upgrade head --sql` (which I ran myself) against all four sibling `domain-entities.md` tables. Every column name, type, nullability, default, ENUM value set, UNIQUE constraint, composite PK, FK target, and index matches exactly:

- `users`: `username` VARCHAR(50) UNIQUE, `display_name`/`password_hash` NOT NULL, `created_at` DATETIME(6) — matches `auth-friends/domain-entities.md` exactly.
- `friendships`: `alias` NOT NULL, `UNIQUE (owner_id, friend_id)`, FKs to `users.id` — matches exactly.
- `rooms`: `last_seq` NOT NULL DEFAULT 0, `name` nullable — matches `rooms-realtime/domain-entities.md` exactly.
- `room_members`: composite PK `(room_id, user_id)`, `INDEX (user_id)`, `ai_check_enabled` DEFAULT TRUE, `last_read_seq` DEFAULT 0 — matches exactly.
- `messages`: `UNIQUE (room_id, seq)`, `INDEX (room_id, seq DESC)`, 6-value `verification_status` ENUM, `misdirect_reported_at` nullable — matches `messaging/domain-entities.md` exactly, including the deliberately redundant unique+index pair the source document itself specifies.
- `judgment_logs`: `message_id` nullable FK, `score`/`verdict` NUMERIC(4,3)/ENUM nullable, `threshold` NOT NULL, `user_action` 3-value ENUM nullable, the three indexes — matches `judgment-core/domain-entities.md` exactly.

The offline DDL I generated (`alembic upgrade head --sql`) confirms the migration produces exactly this schema, table-creation order `users → friendships → rooms → room_members → messages → judgment_logs` matching FK dependency order, and `downgrade()` drops in exact reverse order. No missing, extra, or mistyped column found anywhere.

### `utf8mb4` (FR-9.3) — verified on all three surfaces

- Models: `TABLE_KWARGS = {"mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}` (`backend/app/core/db.py`) is the last element of every model's `__table_args__`.
- Migration: every one of the six `op.create_table()` calls in `0001_initial_schema.py` passes `mysql_charset=CHARSET, mysql_collate=COLLATE` explicitly; confirmed in the DDL I generated — every `CREATE TABLE` ends with `CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci`.
- Container: `docker-compose.yml`'s `db.command` passes `--character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci` explicitly.

No table relies on a server default anywhere.

### Secrets (FR-1.4 / NFR-6) — clean, and fail-fast reproduced directly

I grepped `backend/app`, `backend/tests`, and `frontend/src` for API-key/password/signing-key literal patterns — zero matches (the only hits were inside third-party library docstrings in a venv I created for this review, since deleted). I then reproduced the fail-fast behavior directly, independent of the summary's claim:

```
$ python -c "import app.main"   # with DATABASE_URL/JWT_SECRET/OPENAI_API_KEY unset
ValidationError: 3 validation errors for Settings
DATABASE_URL / JWT_SECRET / OPENAI_API_KEY — Field required
```

This confirms `settings = Settings()` at module-import time genuinely blocks startup when required secrets are absent, exactly as `config.py`'s docstring and `test_config.py::test_missing_required_keys_block_startup` claim.

### Unit boundary — clean

`backend/app/{auth,friends,rooms,messages,judgment}/__init__.py` are all docstring-only (confirmed by reading each file) — no business logic present anywhere in U1's output. The three names `unit-of-work-dependency.md` records as U1's provided contract (`settings`, `get_session()`, `Base`) all exist in `app/core/config.py` and `app/core/db.py` with exactly the signatures `components.md` § core/config and § core/db specify. FR-9.1–FR-9.5, FR-1.4, and NFR-6 are all addressed and traced in the plan's requirement table, and I independently confirmed each is actually implemented (not just claimed) per the sections above and below.

### Startup order (FR-9.2) and container spec — verified against `services.md`

`docker-compose.yml`'s `app.depends_on.db.condition: service_healthy` plus `docker-entrypoint.sh`'s retry loop (`alembic upgrade head`, exponential backoff capped at 8s, max 10 attempts) then `exec uvicorn --workers 1` matches `services.md`'s prescribed order exactly. Confirmed also: non-root (`appuser`, uid 10001) in the Dockerfile, `HEALTHCHECK` hitting `/health`, `db` service has no `ports:` block in the rendered `docker compose config` output (no host port exposure), and graceful shutdown is correctly layered (`stop_grace_period: 15s` > `--timeout-graceful-shutdown 10`, `exec` makes uvicorn PID 1).

### Test quality — real tests, skip mechanism is honest (not silently green)

I read every test file. None are tautological (no `assert True`-style tests); `test_schema.py`'s assertions query `information_schema` directly and assert on real constraint-violation exceptions (`IntegrityError`) rather than just checking the ORM's in-memory model. The skip mechanism (`pytest.skip()` in the `migrated_database` fixture when `TEST_DATABASE_URL` is unset) does not fail open in the sense of reporting false success — a skip is reported distinctly from a pass in pytest's summary line, and I confirmed `32 passed, 13 skipped` reproduces exactly (see below). The real risk — that a CI pipeline without MariaDB would never actually exercise these 13 structural checks and could wave through a schema regression — is the same risk the summary's own "미해결" §1 already names as the top priority for `build-and-test` (3.6). That self-assessment is accurate and I have nothing to add to it beyond confirming it's correctly characterized.

### Verification commands — reproduced myself, all match

I ran every command independently rather than trusting the table:

| Command | My result | Matches summary? |
|---|---|---|
| `ruff check .` | All checks passed! | Yes |
| `ruff format --check .` | 24 files already formatted | Yes |
| `pytest` | `32 passed, 13 skipped` (13/13 skips in `test_schema.py`, `TEST_DATABASE_URL` unset) | Yes, exactly |
| `alembic upgrade head --sql` | 6 tables, FK order, `CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci` on every table, correct ENUM sets, composite PK, all indexes | Yes |
| `npm run typecheck` | Clean | Yes |
| `npm run build` | `tsc --noEmit && vite build` — built in 587ms | Yes |
| `npx vitest run` | 1 file, 6 tests, all passed | Yes |
| `docker compose config` (with `.env` populated) | exit 0, no stderr, `db` has no `ports:` block, `app` env fully interpolated | Yes |
| `docker compose config` (without `.env`) | Fails — `required variable ... is missing a value` | Yes (summary names a different variable in the message text, but the fail-without-.env behavior itself is confirmed) |
| `docker build` / `docker compose up` | Confirmed SKIPPED — `docker info` shows `failed to connect to the docker API ... daemon is running?` on this host | Yes, correctly reported as not executed |
| Repo-wide secret literal search | Zero matches in generated code | Yes |

Test counts also reconcile exactly by hand: `test_config.py` = 23 (1+6+1+1+6+1+6+1 parametrized cases), `test_health.py` = 9, `test_schema.py` = 13 — sums to the reported 45.

### Non-blocking findings (found independently, not in the summary)

1. **`pip install -r requirements.txt` / `requirements-dev.txt` fails on Windows hosts whose default codepage is not UTF-8** (e.g. Korean-locale Windows, codepage 949 — confirmed via `chcp.com` on this host). Both files are UTF-8-without-BOM and contain Korean comments; `pip`'s `auto_decode` falls back to the OS locale encoding when no BOM/coding hint is present, so on a cp949 host it raises `UnicodeDecodeError: 'cp949' codec can't decode byte 0xed...` before installing anything. I reproduced this directly:
   ```
   $ pip install -r requirements-dev.txt
   UnicodeDecodeError: 'cp949' codec can't decode byte 0xed in position 10
   ```
   Setting `PYTHONUTF8=1` works around it, after which `pip install`, `ruff`, and `pytest` all ran cleanly (results above). This is the exact same failure class the plan's own "핵심 구현 결정" table already diagnosed and fixed for `alembic.ini` ("한국어 Windows(cp949)에서 alembic 시작 전에 `UnicodeDecodeError`가 났다" → made that one file ASCII-only), but the fix wasn't generalized to `requirements.txt`/`requirements-dev.txt`, which carry the same Korean-comment-without-BOM shape. It does not block `FR-9.1`'s actual acceptance path (the Dockerfile builds inside Linux containers, which default to UTF-8 mode per PEP 540 regardless of host locale — I did not reproduce a failure there), but it does block a local, non-Docker Python dev loop on the same class of machine this project was evidently built on. Worth a one-line README/CONTRIBUTING note (`set PYTHONUTF8=1`) or converting the two files to ASCII like `alembic.ini` was, before U2–U5 developers hit it locally.

2. **`code-summary.md`'s verification table overstates what `python -c "import app.main"` actually proves.** The table states this command shows "메타데이터에 테이블 6개" (6 tables in metadata). I reproduced the command and checked `Base.metadata.tables` immediately after — it is empty (`{}`), not 6 tables, because `app/main.py` never imports `app.models` (only `POST /health` and app wiring). The 6 tables only appear after an explicit `import app.models`, which is exactly what `migrations/env.py` does (correctly, with an explanatory comment) for Alembic's own autogenerate needs — so the load-bearing path is fine. This doesn't reflect an actual runtime defect (the running app doesn't need `Base.metadata` populated; tables come from the migration, not `create_all()`), but the claim in the verification table doesn't hold for the literal command cited, and a future reader taking it at face value (e.g. to justify skipping an explicit models import in some other script) would be misled.

Neither finding blocks U2–U5 from building on this schema or contradicts any FR/NFR acceptance criterion; both are recorded for the record and for whoever picks up the local-dev-experience thread next.

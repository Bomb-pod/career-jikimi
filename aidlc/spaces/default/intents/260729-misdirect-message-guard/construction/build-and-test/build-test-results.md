# Build and Test Results — career-jikimi

**실행일 2026-07-30.** 아래는 전부 실제로 돌린 결과다. 명령과 방법은 같은 디렉터리의 `build-instructions.md`·`unit-test-instructions.md`·`integration-test-instructions.md`·`security-test-instructions.md`·`performance-test-instructions.md`에 있고, 각 단위가 무엇을 만들었는지는 `../<unit>/code-generation/code-summary.md`에 있다.

## 종합

| 항목 | 결과 |
|---|---|
| 빌드 | **성공** — Dockerfile 3스테이지, 프론트 빌드 포함 |
| 백엔드 테스트 | **314 passed / 0 failed / 0 skipped** |
| 프론트 테스트 | **130 passed / 0 failed** (10 파일) |
| lint·포맷 | ruff **통과** (79 파일) |
| 타입체크 | `tsc --noEmit` **통과** |
| 라이브 종단 스모크 | **29/29 통과** |
| WebSocket 스모크 | **5/5 통과** |
| 의존성 취약점 | npm 0건. pip 23건 → **12건**(수용된 위험 8 + 수정 불가 2 + 개발 전용 1) |
| **발견·수정한 결함** | **1건** (아래) |

## 빌드

```
docker compose up -d --build
```

| 단계 | 결과 |
|---|---|
| `node:22-alpine` 프론트 빌드 | 성공 — 44 모듈, 915ms |
| `python:3.12-slim` wheel 빌드 | 성공 |
| 런타임 이미지 (`--no-index` 설치) | 성공 |
| db healthy → app 기동 | 성공, **~10초** |
| `alembic upgrade head` | 성공 (`alembic_version = 0001`) |
| `GET /health` | `{"status":"ok","db":"ok"}` |
| `GET /` (SPA) | 200 `text/html` |

## 단위·통합 테스트

```
cd backend && .venv/Scripts/python.exe -m pytest -q -rs
→ 314 passed in 23.03s     (skip 0)
```

```
cd frontend && npx vitest run
→ Test Files 10 passed / Tests 130 passed in 10.08s
```

단위별 내역은 `unit-test-instructions.md` § 파일별 대상에 있다. 개수는 `pytest --collect-only`로 셌다.

**skip이 0인 것이 이 결과에서 가장 중요하다.** 스키마·API 테스트는 실제 MariaDB를 요구하고 없으면 skip되게 짜여 있다 — 통과처럼 보이는 미검증을 피하려면 `-rs`로 항상 확인해야 한다.

## 라이브 스택 종단 스모크 — 29/29

실제 컨테이너 대상. 각 항목은 대응 FR/BR을 확인한다.

```
PASS  FR-1.1 signup 201                     PASS  FR-3.1 create room w/ friend 201
PASS  FR-1.1 no password_hash in response   PASS  FR-3.2 room list 200
PASS  second account 201                    PASS  FR-6.1 new room AI toggle ON
PASS  BR-1.1 duplicate 409                  PASS  FR-4.1 send message 201
PASS  BR-1.2 weak password 400              PASS  FR-6.4 cold start -> skipped_no_context
PASS  BR-1.4 wrong password 401             PASS  FR-4.2 first seq == 1
PASS  BR-1.5 no token 401                   PASS  2001 chars -> 400
PASS  FR-2.1 exact search 200               PASS  FR-3.3 history 200
PASS  FR-2.1 partial gives empty + 200      PASS  FR-9.3 korean+emoji roundtrip
PASS  BR-2.2 blank alias 400                PASS  BR-11.1 other's message 403
PASS  FR-2.2 add friend 201                 PASS  FR-11.1 own report 200
PASS  FR-2.2 one-way: B has no A            PASS  BR-11.1 missing message also 403
PASS  FR-2.4 alias shown, no display_name   PASS  FR-11.1 unreport 200
PASS  BR-3.1 empty invite 400               PASS  FR-3.3 room detail 200
                                            PASS  BR-3.3 missing room also 403
```

`FR-9.3` 왕복 실측값: `안녕하세요 🎉 한글과 이모지` — 원본과 일치.

### WebSocket — 5/5

| 확인 | 결과 |
|---|---|
| 핸드셰이크 | `HTTP/1.1 101 Switching Protocols` |
| 유효 토큰 | `{"type":"auth_ok"}` |
| 잘못된 토큰 | `{"type":"auth_error","reason":"invalid_token"}` |
| 인증 전 프레임 | `{"type":"auth_error","reason":"expected_auth_frame"}` |
| 두 번째 연결 | 새 연결 `auth_ok` + 첫 연결에 `{"type":"session_replaced"}` |

## 발견하고 수정한 결함 — 라이브에서만 잡혔다

**`ws_registry.register()`의 `await existing.close()`가 close 핸드셰이크 완료를 기다렸다.**

| 밀려난 탭 | 새 탭의 `auth_ok`까지 |
|---|---|
| close에 응답함 (정상 브라우저) | **0.0초** |
| 응답 안 함 (멈춘 탭·끊긴 네트워크) | **10.0초** |

레지스트리는 그 시점에 이미 새 소켓으로 교체됐고 `session_replaced`도 전달된 뒤라 기다릴 이유가 없다. `EVICTED_CLOSE_TIMEOUT_SECONDS = 1.0` 상한을 걸었다.

**수정 후 실측 1.00초.**

`test_ws_registry.py::test_an_unresponsive_evicted_socket_does_not_delay_the_new_connection`을 붙였다. 상한값이 아니라 "비협조적 상대가 교체를 붙잡지 못한다"는 불변식을 검사한다. **비공허성 확인** — 수정을 되돌리면 실제로 실패한다(`TimeoutError`).

**단위 테스트가 못 잡은 이유** — 가짜 소켓의 `close()`가 즉시 반환한다. 실패 모드가 실제 전송 계층에만 있었다. 컨테이너를 띄워 실제 소켓으로 두드리는 층위를 두는 값어치가 여기 있다.

## 보안 점검

| 항목 | 결과 |
|---|---|
| 비밀 리터럴 스캔 (FR-1.4 수용 기준) | **0건** — 소스에 API 키·비밀번호·서명 키 없음 |
| 문자열 연결 SQL | **0건** — `sa.text()`는 전부 리터럴 상수(서버 기본값·인덱스 표현식·`SELECT 1`·`NOW(6)`), `exec_driver_sql`은 테스트 픽스처에만 |
| 인증·권한 테스트 | **86 passed** (`-k "auth or forbidden or 403 or force"`) |
| 비루트 실행 | `uid=10001(appuser) gid=10001(appuser)` |
| 단일 워커 (FR-9.4) | uvicorn **1개**, PID 1, `--workers 1` |
| db 호스트 포트 | **미노출** (`3306/tcp`, 매핑 없음) |
| `npm audit --omit=dev` | **0건** |
| `pip-audit` | 23건 → 12건 (아래) |

### 의존성 취약점 — 조치와 잔여

| 패키지 | 조치 | 상태 |
|---|---|---|
| `PyJWT` 2.10.1 → **2.13.0** | 올림 | **11건 해소.** 314 테스트 통과, 호출부 변경 없음 |
| `asyncmy` 0.2.10 → **0.2.11** | 올림 | PYSEC-2026-286 — **최신에도 있고 수정 버전 미공개.** 잔여 |
| `pytest` 8.3.4 | 조치 안 함 | 개발 전용, 런타임 이미지에 없음. 잔여(무해) |
| `starlette` 0.41.3 | **수용된 위험** | 8건. 근거는 `security-test-instructions.md` § 의존성 |

`starlette`는 `fastapi`가 끌어오며 수정에는 fastapi 26버전 점프가 필요하다. 올려봤을 때 8건은 사라지고 라우트 등록 확인 테스트 2개가 깨졌다. 로컬 전용 데모라 원격 도달 경로가 없고 최종 발표가 나흘 앞이라, 사람의 결정으로 **두고 기록**했다. 원격 배포 시 첫 처리 항목이다.

## 판정 지표 CLI (ADR-008)

```
docker compose exec app python -m app.judgment.report
```

계약대로 출력된다:

- `recall` → **`산출 불가 — 라벨 데이터셋 필요`** (수치가 아니다)
- `precision` → **`산출 불가 — 부적절 판정 건이 없음`** (0.0이 아니다). 판정 데이터가 있으면 `※ 근사 — ASM-1 참조`가 붙는다
- 하단에 ASM-1 각주 상시 출력

## 검증하지 못한 것 — 그대로

| 항목 | 왜 |
|---|---|
| **NFR-1 판정 지연 (5초/최악 10초)** | **실제 OpenAI 키로 한 번도 돌지 않았다.** `.env`의 키가 자리표시자다. 예산 상한이 구조로 강제되는 것은 검증했으나 실측값이 없다. 방법은 `performance-test-instructions.md` |
| **판정 품질** — 프롬프트가 실제로 문맥 부적합을 잡는가 | 같은 이유. **이 프로젝트의 가장 큰 미지수다.** `try` CLI가 채팅 UI 없이 이것을 시험하는 도구이며 키만 넣으면 바로 돈다 |
| FR-10 방 참여자 추가·나가기 | 위험 등록부의 1순위 절단으로 **미구현** |
| 부하·스트레스·소크 | 트랙 3으로 범위 밖 |
| SAST/DAST·침투 시험 | 파이프라인·배포 대상 없음 |

## 재현

```bash
cp .env.example .env                       # JWT_SECRET, OPENAI_API_KEY 채우기
docker run -d --name cj-testdb -e MARIADB_ROOT_PASSWORD=testpw \
  -e MARIADB_DATABASE=career_jikimi_test -p 33061:3306 mariadb:11 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
# .env의 TEST_DATABASE_URL을 위 DB로

cd backend && python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m ruff check . && .venv/Scripts/python.exe -m pytest -q -rs

cd ../frontend && npm install && npm run typecheck && npm run build && npx vitest run

cd .. && docker compose up -d --build && curl http://localhost:8000/health
```

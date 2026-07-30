# Security Test Instructions — career-jikimi

`aidlc-devsecops-agent` 관점이다. Test Strategy가 **Standard**라 스테이지 프로즈는 이 파일을 요구하지 않으나, 엔진의 `produces`가 선언하고 있고 `../../inception/requirements-analysis/requirements.md`에 보안 요구가 실제로 있다(FR-1.4, NFR-6, 그리고 인증·권한 규칙 다수).

각 단위의 구현은 `../<unit>/code-generation/code-summary.md`, 그 근거는 `../<unit>/code-generation/code-generation-plan.md`에 있다.

**이 데모의 위협 모델은 좁다.** `decisions.md` ADR-007이 "사용자가 자기 자신의 오발송 경고를 우회하는 것은 자해이지 공격이 아니다"로 이미 선을 그었다. 아래 항목은 그 선 안쪽 — **남의 데이터에 닿는 경로와 비밀 노출** — 에 집중한다.

## 실행 요약

```bash
# 1. 비밀 리터럴 스캔 (FR-1.4의 수용 기준 그대로)
git grep -nEi "(sk-[A-Za-z0-9]{20,}|api[_-]?key[\"' ]*[:=][\"' ]*[A-Za-z0-9]{16,})" -- backend/app frontend/src

# 2. 인증·권한 테스트
cd backend && .venv/Scripts/python.exe -m pytest -q -k "auth or forbidden or 403 or force" -rs

# 3. 의존성 취약점
pip install pip-audit && pip-audit -r backend/requirements.txt
cd frontend && npm audit --omit=dev

# 4. 컨테이너 위생
docker compose exec app id                       # uid=10001 (비루트)
docker compose ps --format '{{.Name}}\t{{.Ports}}'   # db에 호스트 포트 없음
```

실행 결과는 `build-test-results.md` § 보안 점검에 있다.

## OWASP Top 10 — 이 앱에 해당하는 것만

| # | 항목 | 이 앱에서 | 검증 |
|---|---|---|---|
| 1 | **Broken Access Control** | 방·메시지·판정 로그가 전부 소유자 기준 | 아래 § 접근 통제 |
| 2 | **Cryptographic Failures** | 비밀번호 해시, JWT 서명 | argon2id, `test_auth_security.py` |
| 3 | **Injection** | SQLAlchemy ORM만 사용, 문자열 연결 없음 | 아래 § 인젝션 |
| 5 | **Security Misconfiguration** | CORS, 비루트, 포트 노출 | 아래 § 구성 |
| 6 | **Vulnerable Components** | 핀 고정된 의존성 | `pip-audit`, `npm audit` |
| 7 | **Authentication Failures** | 로그인, 토큰 | 아래 § 인증 |
| 9 | **Logging Failures** | 비밀이 로그에 안 나올 것 | 아래 § 로깅 |

**해당 없음** — 4(Insecure Design: 위협 모델이 ADR-007에 명시됨), 8(Data Integrity: 역직렬화 없음, 서명 아티팩트 범위 밖), 10(SSRF: 서버가 사용자 입력 URL로 요청하지 않음. OpenAI 엔드포인트는 설정값이다).

## 접근 통제 — 가장 중요한 축

**"없으면 403, 남의 것도 403"이 이 앱의 일관된 규칙이다.** 404를 주면 id의 존재 여부가 새어나간다.

| 자원 | 규칙 | 테스트 |
|---|---|---|
| 방 상세·읽음·토글 | 참여자 아니면 403. **없는 방도 403** | `test_rooms_api.py`, `test_ai_toggle.py` |
| 히스토리·전송 | 같음 | `test_history.py`, `test_send_message.py` |
| friendship 별칭 수정 | 남의 것 403. **없는 id도 403** | `test_friends_api.py` |
| 메시지 신고 | 발신자 본인만. **없는 메시지도 403** | `test_report.py` |
| 판정 로그 (`force_log_id`) | **소유자 불일치만 403**, 나머지 5개 검사는 400 | `test_force_log.py` |

### `force_log_id` — 판정 우회 방어

6중 검사다(BR-6.9). 하나라도 빠지면 판정을 건너뛰는 경로가 생긴다.

```
로그 존재?           아니면 400 InvalidForceToken
user_id == 호출자?   아니면 403 Forbidden       ← 이것만 403
room_id == 이 방?    아니면 400
user_action IS NULL? 아니면 400 (이미 소진)
candidate_text 일치? 아니면 400                 ← application-design에서 이월된 구멍
verdict IN (inappropriate, NULL)?  아니면 400
```

**텍스트 일치 검사가 핵심이다.** 없으면 유효한 미소진 토큰에 *다른 문장*을 실어 판정 없이 `flagged_sent`로 통과시킬 수 있다. UI로는 도달 불가하지만 API 직접 호출로는 가능하다. 비교는 **트림 후 정확 일치** — 정규화(공백 축약·유니코드)까지 하면 우회 여지가 생긴다.

`set_user_action()`의 **원자적 조건부 갱신**(`WHERE ... AND user_action IS NULL`)이 1회성을 실제로 보장한다. SELECT 후 UPDATE로 짜면 동시 요청 둘이 모두 통과해 더블클릭에 메시지 두 개가 저장된다. `test_force_log.py`가 발생한 SQL을 검사한다.

## 인증

| 항목 | 구현 | 근거 |
|---|---|---|
| 비밀번호 해시 | **argon2id** (`argon2-cffi`) | bcrypt는 72바이트를 조용히 자른다 — 한글 24자. BR-1.2의 "상한 없음"과 모순 |
| 평문 저장 | 없음. 응답 스키마에 `password_hash` 필드가 **구조적으로** 없다 | FR-1.1 |
| 로그인 실패 | 아이디 없음과 비밀번호 틀림이 **같은 401 + 같은 본문 + 같은 시간** | BR-1.4 |
| 타이밍 균일화 | 사용자가 없어도 더미 해시를 검증한다 | 리뷰어가 8회씩 측정해 ~120–140ms로 겹침 확인 |
| JWT 클레임 | `sub`·`exp`만. 사용자명·표시명을 넣지 않는다 | 바뀔 수 있는 값을 토큰에 넣으면 토큰이 낡는다 |
| 토큰 없이 접근 | **401** (403 아님) | `HTTPBearer(auto_error=False)` — 기본값은 403을 내며 BR-1.5와 어긋난다 |
| WebSocket | 첫 프레임 auth, 5초 타임아웃, 인증 전 프레임 미처리 | FR-1.3, CON-4(브라우저가 WS에 헤더를 못 붙인다) |

**만들지 않은 것** — 로그인 rate limit, 계정 잠금, MFA. 요구사항에 없고 데모 위협 모델 밖이다. 다중 사용자 서비스로 나가면 rate limit이 첫 번째로 필요해진다.

**리프레시 토큰이 없다**(FR-1.2). 만료는 24시간이며, 토큰이 유출되면 그 시간 동안 유효하다. 수용된 절충이다.

## 인젝션

SQLAlchemy ORM만 쓴다. **문자열 연결로 만든 SQL이 없다.** 확인:

```bash
git grep -nE 'text\(|execute\("|exec_driver_sql' -- backend/app
```

`exec_driver_sql`은 테스트 픽스처의 테이블 정리에만 있고 사용자 입력이 닿지 않는다.

**프롬프트 인젝션은 다르다.** 메시지 본문이 설계대로 그대로 직렬화되므로 `## 보내려는 메시지` 같은 줄이 섹션 헤더를 흉내낼 수 있다. 영향은 한정적이다 — 사용자가 왜곡할 수 있는 것은 **자기 메시지의 판정뿐**이고, `force_log_id`가 이미 같은 결과에 이르는 합법 경로를 준다. 정규화하지 않은 이유는 **판정 대상과 실제 전송 내용이 달라지기** 때문이다. ADR-007의 위협 모델 안이다.

## 구성

| 항목 | 확인 명령 | 기대 |
|---|---|---|
| 비루트 실행 | `docker compose exec app id` | `uid=10001(appuser)` |
| db 포트 미노출 | `docker compose ps` | db에 호스트 매핑 없음 |
| 단일 워커 | 컨테이너 내 프로세스 열거 | uvicorn 1개 (PID 1) |
| CORS | `.env`의 `CORS_ORIGINS` | 배포 시 **비움**. dev에서만 `http://localhost:5173` |
| 비밀 주입 | `.env` / 환경변수만 | 이미지에 굽지 않는다 |
| 서버 헤더 | `--no-server-header` | 버전 노출 억제 |

**만들지 않은 것** — HSTS·CSP·X-Frame-Options 등 보안 헤더. 로컬 HTTP 데모라 HSTS는 의미가 없고, 나머지는 원격 배포 시 추가할 항목이다(`requirements.md` § Out of Scope가 원격 배포를 범위 밖으로 둔다).

## 로깅

**비밀이 로그에 나오면 안 된다.** `settings.JWT_SECRET`과 `OPENAI_API_KEY`가 `SecretStr`이라 `repr`에서 마스킹된다 — `test_config.py`가 그것을 검사한다.

판정 로그(`judgment_logs.candidate_text`)에는 **메시지 본문이 그대로 들어간다.** 설계상 필요하다(`force_log_id`의 텍스트 일치 검증, 재현). 그 테이블은 대화 내용의 파생물이므로 아무나 보면 안 되며, ADR-008이 지표를 UI가 아니라 **CLI로만** 노출한 이유가 그것이다 — 컨테이너에 들어갈 수 있는 사람은 이미 DB도 볼 수 있다.

## 의존성

```bash
cd backend && .venv/Scripts/python.exe -m pip_audit -r requirements.txt
cd frontend && npm audit --omit=dev
```

모든 버전이 핀 고정되어 있다. `ci-pipeline`(3.7)이 스코프에서 제외되어 **자동 스캔 게이트가 없다** — 수동으로 돌린다.

### 이 스테이지에서 돌린 결과

`npm audit --omit=dev` → **0건.**

`pip-audit` → **23건 / 3패키지.** 조치:

| 패키지 | 조치 | 결과 |
|---|---|---|
| `PyJWT` 2.10.1 → **2.13.0** | 올림 | **11건 해소.** 314 테스트 전부 통과, 호출부 변경 없음 |
| `asyncmy` 0.2.10 → **0.2.11** | 올림 | PYSEC-2026-286은 **최신에도 있고 수정 버전이 공개되지 않았다.** 핀을 낮춰도 해결되지 않는다 |
| `pytest` 8.3.4 | 조치 안 함 | 개발 전용. `requirements-dev.txt`에 있고 **런타임 이미지에 들어가지 않는다** |
| `starlette` 0.41.3 (8건) | **수용된 위험** | 아래 |

### `starlette` 8건 — 수용된 위험 (2026-07-30 결정)

`starlette`는 직접 의존성이 아니라 `fastapi`가 끌어온다. 수정은 `>= 1.3.1`이고, 그러려면 **fastapi 0.115.6 → 0.141.1**(마이너 26개)이 필요하다.

실제로 올려봤다 — 8건이 전부 사라지고 `test_ws_auth.py`의 라우트 등록 확인 **2개가 깨진다**(starlette 1.x가 라우트에서 `.path`를 노출하지 않는다). 나머지 312개는 통과한다.

**두기로 한 근거:**

- 이 앱은 **로컬 데모다.** `requirements.md` § Out of Scope가 원격 배포를 명시적으로 범위 밖에 두었고, `docker-compose.yml`은 `localhost:8000`만 노출하며 db는 호스트에 열지 않는다
- 해당 권고들은 HTTP 계층에 닿는 **원격 공격자**를 전제한다. 이 구성에 그 경로가 없다
- 깨진 테스트 2개를 고치는 것 자체는 작다. **위험은 26개 버전 사이의 동작 변화 중 현재 테스트가 덮지 않는 부분**이며, 최종 발표(08-04)가 나흘 앞이다

**원격 배포로 나가는 순간 이것이 첫 번째 처리 항목이다.** 되돌림은 핀 두 줄이다.

## 스코프 밖 — 명시적으로

`requirements.md` § Out of Scope와 ADR-007이 정한 것들이다.

- **SAST/DAST 도구** (CodeGuru·SonarQube·ZAP) — 로컬 데모에 파이프라인이 없다
- **침투 시험** — 배포된 대상이 없다
- **클라우드 보안** (IAM·KMS·Security Hub·GuardDuty) — AWS를 쓰지 않는다
- **컴플라이언스 매핑** (GDPR·SOC2) — 실사용자 데이터가 없다
- **degraded 플래그·프로브 카운터 조작** — ADR-007이 자해로 분류. 다중 사용자 제품에서 관리자가 검증을 강제해야 한다면 이 결정이 성립하지 않는다

## 알려진 미방어 하나

`_decide()`가 `probe=true`를 `degraded=true` 없이도 존중한다. 조작된 `{degraded: false, probe: true}` 요청은 판정 실패 시 BR-8.1의 팝업을 띄우지 않고 `failed`로 조용히 저장할 수 있다. 정상 프론트는 이 조합을 만들지 않으며 ADR-007의 자해 범주 안이지만, **서버 측 방어도 테스트도 없다.** 다중 사용자 환경으로 나가면 `probe`가 `degraded`를 함의하도록 좁혀야 한다.

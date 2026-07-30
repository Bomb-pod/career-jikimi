# Unit Test Instructions — career-jikimi

Test Strategy는 **Standard** (`aidlc-state.md`) — 컴포넌트당 5~8개 + 경계 통합. 각 단위의 `../<unit>/code-generation/code-summary.md`가 그 단위의 테스트 목록을, `../<unit>/code-generation/code-generation-plan.md`가 무엇을 왜 검증하는지를 담고 있다.

## 실행

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q -rs        # Linux/macOS: .venv/bin/python
```

`-rs`를 항상 붙인다 — **skip을 통과로 착각하지 않기 위해서다.** 기대값은 skip 0이며, 0이 아니면 `build-instructions.md` § 테스트 DB를 확인한다.

```bash
cd frontend
npx vitest run
```

### 유용한 필터

```bash
pytest tests/test_seq_allocation.py -q          # 파일 하나
pytest -k "degraded or probe" -q                # 이름으로
pytest tests/test_judge.py::test_... -q         # 하나만
pytest -q -x                                     # 첫 실패에서 멈춤
npx vitest run src/views/degradedFlow.test.tsx  # 프론트 파일 하나
```

## 프레임워크 구성

| 항목 | 값 |
|---|---|
| 백엔드 | pytest 8.3.4 + pytest-asyncio 0.25.0 (`asyncio_mode=auto`, `backend/pyproject.toml`) |
| 프론트 | vitest 3 + @testing-library/react (`frontend/vitest.config.ts`) |
| DB | **실제 MariaDB 11.** SQLite 대체 없음 |
| LLM | **전부 목.** 실제 OpenAI 호출이 테스트에 없다 — 키 없이 돌고 비용이 들지 않는다 |

### 공용 픽스처 (`backend/tests/conftest.py`)

| 이름 | 용도 |
|---|---|
| `migrated_database` | 빈 테스트 DB에 `alembic upgrade head`를 **두 번** 적용. 두 번째가 안전한지가 실제 요구사항이다(엔트리포인트가 재시작마다 돈다) |
| `db_session` / `api_client` | 외부 트랜잭션 + savepoint 격리. `httpx.AsyncClient` + `ASGITransport`로 **테스트와 같은 이벤트 루프**에서 앱을 부른다 — `TestClient`는 별도 루프를 써서 asyncmy 커넥션 공유가 즉시 깨진다 |
| `live_sessionmaker` | **실제 커밋 + 별도 커넥션.** 동시성 테스트 전용 |
| `capture_sql()` / `selects()` | 발생한 SQL 문자열 검사 |
| `make_user` / `make_room` | FK 채우기 |

## 파일별 대상

### 기반 — foundation (U1)

| 파일 | 개수 | 무엇을 |
|---|---|---|
| `test_config.py` | 24 | 필수 키 누락 시 기동 실패, 기본값, `CORS_ORIGINS` 파싱, 비밀이 repr에 안 나옴, **`MAX_ATTEMPTS × 기본 타임아웃 < TOTAL_BUDGET_SECONDS` 불변식** |
| `test_health.py` | 9 | 200 / 구조 / DB 실패 시 503 |
| `test_schema.py` | 13 | 테이블 6개, `utf8mb4`, `UNIQUE (room_id, seq)`·`UNIQUE (owner_id, friend_id)`·복합 PK, `alias` NOT NULL, 한글·이모지 왕복, 마이그레이션 2회 멱등성 |

### 인증·친구 — auth-friends (U3)

| 파일 | 개수 | 무엇을 |
|---|---|---|
| `test_auth_security.py` | 18 | 해싱 왕복, 같은 입력의 해시가 매번 다름, **80바이트 비밀번호가 잘리지 않음**(argon2 선택의 증거), 토큰 왕복·만료·위조, 클레임에 `sub`·`exp`만 |
| `test_auth_api.py` | 14 | 가입 201, 7자 400, 중복 409, **무결성 위반이 409로 변환**, **없는 아이디와 틀린 비밀번호의 응답이 동일**, 보호 엔드포인트 401 |
| `test_friends_api.py` | 19 | 정확 일치 1명, 부분 일치는 빈 결과 **+200**, 별칭 필수, **트림 후 빈 값도 400**, 단방향, 중복 409, 자기 자신 400, 없는 대상 404, **남의·없는 friendship 모두 403** |
| `test_display_names.py` | 11 | 전원 친구면 쿼리 1회, 폴백, **쿼리 횟수가 대상 수에 비례하지 않음**(N+1 회귀) |

### 판정 — judgment-core (U2)

| 파일 | 개수 | 무엇을 |
|---|---|---|
| `test_anonymize.py` | 7 | 등장 순서 라벨, 후보 발신자 유무, 26명 초과, **출력에 `sender_id`가 없음**, 빈 문맥 |
| `test_prompt.py` | 7 | system에 "판단하지 않는 것" 3항목, 점수 구간 4개, user에 참여자 정보 없음, `strict: true`·`additionalProperties: false` |
| `test_client.py` | 22 | 타임아웃 시 **정확히 1회** 재시도, 5xx·429 재시도, **400은 재시도 안 함**, 예산 안, `Retry-After` 초과 시 대기 안 함, 실패도 `latency_ms` 기록, **SDK 자체 재시도 꺼짐** |
| `test_judge.py` | 12 | **로그 행이 호출 전에 생성됨**, 임계값 경계 `>=`, 클램프, 실패가 **예외가 아니라 `Failed` 반환** |
| `test_force_log.py` | 18 | BR-6.9의 6개 검사, **소유자 불일치만 403**, **텍스트 불일치 거부**, `verdict=NULL` 통과, `set_user_action` 2회 시 `AlreadyResolved`, **조건절이 SQL에 실제로 있음** |
| `test_metrics.py` | 13 | precision, **분모 0이면 `None`**, `verdict IS NULL`이 precision에서 빠지고 **실패율에는 포함**, 미응답 별도, **recall이 문자열** |

### 방·실시간 — rooms-realtime (U4)

| 파일 | 개수 | 무엇을 |
|---|---|---|
| `test_ws_registry.py` | **13** | 등록·해제, **`session_replaced`를 보낸 뒤 닫음**, 연결 없는 사용자 건너뜀, **한 소켓이 죽어도 나머지가 받음**, 밀려난 쪽 정리가 **새 연결을 지우지 않음**, **비협조적 소켓이 교체를 붙잡지 않음**(이 스테이지에서 추가) |
| `test_rooms_api.py` | 16 | 생성 201, 빈 초대 400, 친구 아닌 id 400, 한 트랜잭션, 목록이 내 방만, **없는 방도 403**, 상세에 남의 토글 없음 |
| `test_rooms_unread.py` | 10 | 배지 계산, **한 번의 쿼리로 전부**(N+1 회귀), 전진만, **역행 요청 무시 + 200**, 조건절이 SQL에 실제로 있음 |
| `test_ai_toggle.py` | 7 | 본인 행만, **다른 참여자 설정 불변**, 신규 방 기본 TRUE, 비참여자 403 |
| `test_ws_auth.py` | 11 | 5초 타임아웃, 인증 전 프레임 거부, 잘못된 토큰 `auth_error`, 성공 시 등록, 종료 시 unregister |

### 메시지 — messaging (U5)

| 파일 | 개수 | 무엇을 |
|---|---|---|
| `test_seq_allocation.py` | 9 | **NFR-7 명시 의무.** 아래 § 별도 참조 |
| `test_send_message.py` | 25 | 상태 결정 순서, 6값 각각, **부적절 시 저장 안 됨 + 409**, **판정이 트랜잭션 밖**, **브로드캐스트가 커밋 뒤** |
| `test_force_send.py` | 11 | `inappropriate`→`flagged_sent`, **`NULL`→`failed`**(FR-8.3을 성립시키는 장치), 텍스트 불일치·소진 거부 |
| `test_history.py` | 11 | 최신 50개 내림차순, **`before` 경계 미포함**, `limit` 상한 100, 비참여자 403, 표시명 1회 |
| `test_report.py` | 14 | 신고·취소, **남의·없는 메시지 모두 403**, 어느 상태든 신고 가능 |

### 프론트

| 파일 | 개수 |
|---|---|
| `lib/apiClient.test.ts` | 12 |
| `lib/wsClient.test.ts` | 12 |
| `store/chatStore.test.ts` | 17 |
| `views/AuthView.test.tsx` | 11 |
| `views/FriendsView.test.tsx` | 13 |
| `views/RoomListView.test.tsx` | 15 |
| `views/ToastHost.test.tsx` | 4 |
| `views/ChatView.test.tsx` | 27 |
| `views/degradedFlow.test.tsx` | 13 — **NFR-7 명시 의무** |
| `App.test.tsx` | 6 |

## 커버리지 기대

`org.md` § Testing Posture가 `mvp`·`feature` 계열에 **80% 라인 커버리지**를 하한으로 둔다. 이 프로젝트의 스코프는 `greenfield-local-demo`로 그 표에 없으나, Standard 전략의 컴포넌트당 5~8개 기준을 모든 컴포넌트가 충족한다.

**커버리지 수치를 게이트로 강제하지 않는다.** `ci-pipeline`(3.7)이 스코프에서 제외되어 강제할 자리가 없고, `org.md`의 "커버리지는 지침이지 목표가 아니다"에 따라 의미 없는 단언으로 숫자를 채우지 않았다. 대신 **각 FR의 Given/When/Then 수용 기준이 테스트로 존재하는지**를 기준으로 삼았다 — `integration-test-instructions.md`의 추적 표가 그것을 담는다.

커버리지 수치가 필요해지면:

```bash
pip install pytest-cov
pytest --cov=app --cov-report=term-missing -q
```

## 새 테스트를 쓸 때 지킬 것

`project.md`에 학습으로 기록된 것들이다:

- **조용히 skip되는 테스트를 만들지 않는다.** 설정이 없으면 하네스가 찾아내게 하거나, 못 찾으면 실패하게 한다
- **숫자가 아니라 불변식을 고정한다.** `== 4.0`은 다음 사람이 값을 바꾸며 함께 고쳐 사라진다. 상수를 소유 모듈에서 import한 부등식은 어떤 값에서도 상한을 지킨다
- **동시성에 의존하는 경로는 실제 동시 테스트로만 검증된다** (§ 아래)
- 셀 수 있는 것은 스크립트로 센다 — 이 문서의 개수도 `pytest --collect-only`로 셌다

## 동시 채번 — 순차 테스트로는 안 보인다

`test_seq_allocation.py`가 이 프로젝트에서 가장 값비싼 테스트다. `asyncio.gather` + 별도 커넥션 + 실제 커밋으로 **진짜 동시** 전송을 만든다.

이것이 잡아낸 것 — MariaDB InnoDB는 트랜잭션의 read view가 잡힌 뒤 갱신된 행에 잠금 읽기가 닿으면 `1020 Record has changed since last read`를 낸다(MySQL은 최신 커밋본을 준다). `send_message()`의 앞 단계들이 read view를 잡아 **첫 번째 이후의 동시 전송이 전부 실패했다.** 순차 테스트는 전부 초록이었다.

같은 부류의 경로를 새로 만들면 — 한 트랜잭션에서 같은 행을 `FOR UPDATE` 잡기 **전에** 읽는 코드 — 반드시 동시 테스트를 함께 만든다.

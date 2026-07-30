# Build and Test Summary — career-jikimi

Construction 마지막 단계의 종합이다. 실행 결과의 원본은 `build-test-results.md`, 방법은 `build-instructions.md`·`unit-test-instructions.md`·`integration-test-instructions.md`·`performance-test-instructions.md`·`security-test-instructions.md`에 있다.

입력은 다섯 단위의 `../<unit>/code-generation/code-generation-plan.md`와 `../<unit>/code-generation/code-summary.md`다.

## 빌드 상태

**성공.** `docker compose up -d --build` 하나로 db와 app이 뜨고 `~10초`에 healthy가 된다 (FR-9.1).

| 전제 | 상태 |
|---|---|
| Docker Desktop | 필요. 없으면 앱을 못 띄운다 |
| `.env` | **필수.** `JWT_SECRET`·`OPENAI_API_KEY`·`DATABASE_URL`이 비면 기동 즉시 실패한다 (FR-1.4, NFR-6) |
| 로컬 Python·Node | 테스트를 돌릴 때만. 앱 자체는 컨테이너로 자족한다 |
| 테스트 MariaDB | `TEST_DATABASE_URL`. 없으면 관련 테스트가 **조용히 skip된다** |

## 생성한 테스트 지시서

Test Strategy는 **Standard**다. 프로즈는 unit + integration 둘만 요구하지만, 엔진의 `produces`가 다섯을 선언하고 이 프로젝트에 실제 성능·보안 NFR이 있어 전부 만들었다. 다만 뒤 둘은 **그 NFR들에만 범위를 맞췄다**.

| 파일 | 범위 | 상태 |
|---|---|---|
| `build-instructions.md` | 전제·환경·빌드·문제 해결 | 전부 실행 검증됨 |
| `unit-test-instructions.md` | 백엔드 13파일 + 프론트 10파일의 대상과 개수 | 전부 실행됨 |
| `integration-test-instructions.md` | 3층위 — API 통합 / 단위 간 계약 / 라이브 스택 | 전부 실행됨 |
| `performance-test-instructions.md` | **NFR-1 하나에만.** 부하 시험은 트랙 3으로 범위 밖 | **미실행** — 실제 키 필요 |
| `security-test-instructions.md` | OWASP 중 해당 항목, 접근 통제, 의존성 | 전부 실행됨 |

## 커버리지 기대와 실제

| 단위 | 백엔드 | 프론트 |
|---|---|---|
| foundation | 46 (config 24 · health 9 · schema 13) | — |
| auth-friends | 62 | 24 (AuthView 11 · FriendsView 13) |
| judgment-core | 80 (config 부등식 1 포함) | — |
| rooms-realtime | 57 (이 스테이지에서 +1) | 48 |
| messaging | 69 | 40 |
| 공용 (App 셸·apiClient) | — | 18 |
| **합계** | **314** | **130** |

**커버리지 수치를 게이트로 강제하지 않는다.** `ci-pipeline`(3.7)이 스코프 밖이라 강제할 자리가 없고, `org.md`가 "커버리지는 지침이지 목표가 아니다"로 정했다. 대신 **각 FR의 Given/When/Then 수용 기준이 테스트로 존재하는지**를 기준으로 삼았다 — 대응표는 `integration-test-instructions.md` § 요구사항 → 검증 위치.

## 준비도 평가

| 축 | 판정 | 근거 |
|---|---|---|
| **Build-ready** | ✅ | 3스테이지 빌드 성공, 기동 순서 확인, `/health` 200 |
| **Test-ready** | ✅ | 444개(백 314 + 프론트 130) 통과, **skip 0.** 실제 MariaDB 사용 |
| **Demo-ready** | ⚠️ **조건부** | 화면·API·저장은 종단으로 동작한다. **판정 경로만 실제 키로 미검증** |
| **Deployment-ready** | ❌ | 원격 배포가 범위 밖이다. `starlette` 8건이 수용된 위험으로 남아 있고, 원격으로 나가면 그것이 첫 처리 항목이다 |

**Demo-ready가 조건부인 이유가 이 문서에서 가장 중요하다.** `docker compose up`으로 회원가입·친구 등록·방 생성·메시지 전송·히스토리·신고가 전부 실제로 돈다(29/29 스모크). 돌지 않은 것은 **AI 판정 하나**이며, 그것이 이 프로젝트가 증명하려는 바로 그 기능이다.

## 남은 항목

### 반드시 해야 하는 것

1. **`.env`에 실제 `OPENAI_API_KEY`를 넣고 판정을 돌려본다.** `docker compose exec app python -m app.judgment.try --context ... --candidate ...`가 채팅 UI 없이 바로 돈다. 이것이 `judgment-core`를 DAG에서 앞으로 당긴 값어치다
2. **NFR-1 실측** — 위 ①에서 나온 `latency`와, 문맥이 10개 이상 쌓인 방에서의 종단 전송 시간. 방법은 `performance-test-instructions.md`
3. **프롬프트 튜닝** — 점수 구간 설명이 실제로 분포를 벌리는지, 한국어 프롬프트가 맞는 선택인지 둘 다 **검증되지 않은 가정**이다

### 알려진 채로 두는 것

| 항목 | 상태 |
|---|---|
| `starlette` 8건 | 수용된 위험. 로컬 전용이라 도달 경로 없음 |
| `asyncmy` PYSEC-2026-286 | 최신에도 있고 **수정 버전 미공개** |
| FR-10 방 참여자 추가·나가기 | 절단됨. 복원은 U4 계획 Step 7만 실행 |
| FR-8.1 타임아웃 범위의 요구사항 긴장 | FR-8.1이 "3~5초"를 허용하나 NFR-1과 함께 보면 5는 여유가 0이다. 기본값 4로 출하 |
| `probe=true` 서버 측 미방어 | ADR-007의 자해 범주. 다중 사용자로 나가면 좁혀야 한다 |
| 프롬프트 인젝션 (여러 줄 본문) | 자기 메시지 판정만 왜곡 가능. 정규화하면 판정 대상과 전송 내용이 달라진다 |

## 이 스테이지가 바꾼 것

지시서만 쓰고 끝내지 않고 전부 실행했으며, 그 과정에서 코드가 두 곳 바뀌었다.

| 변경 | 왜 |
|---|---|
| `ws_registry.py` — 밀려난 연결 close에 1초 상한 | **라이브에서만 잡힌 결함.** 비협조적 탭이 새 연결을 10초 붙잡았다. 회귀 테스트 포함 |
| `requirements.txt` — `PyJWT` 2.13.0, `asyncmy` 0.2.11 | `pip-audit` 23건 중 11건 해소 |

두 결함 모두 **단위 테스트로는 보이지 않았다** — 하나는 실제 전송 계층에만, 하나는 의존성 트리에만 있었다.

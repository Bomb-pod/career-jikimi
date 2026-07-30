<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is maintained by the orchestrator during stage execution. Add observations at the gate ritual, not by editing here directly.

## Interpretations

- 2026-07-30T00:30:00Z — U1 foundation은 `functional-design` 산출물이 없다; `kind: packaging` 단위라 3.1이 도메인 문서를 만들지 않았다. 대신 `services.md`(배포 형태)·`components.md`(core/config·core/db 표면)·형제 단위 4개의 `domain-entities.md`(전체 스키마)를 계획의 근거로 삼았다. 엔진의 `consumes`에도 `unit-of-work.md`와 `requirements.md`만 들어와 있어 이 판단과 일치한다.

## Deviations

- 2026-07-30T01:40:00Z — 리뷰어가 READY를 준 뒤에도 비차단 지적 하나를 그 자리에서 고쳤다(`requirements.txt`·`requirements-dev.txt`를 ASCII 전용으로); pip이 Windows에서 이 파일을 로케일 코드페이지로 읽어 cp949 호스트에서 의존성 해석 전에 `UnicodeDecodeError`가 났다. `alembic.ini`에서 같은 실패를 이미 진단해 고쳤는데 두 파일로 일반화하지 않은 것이었고, 이 프로젝트를 만드는 호스트가 정확히 그 부류라 로컬 비-Docker 개발이 막혔다. 코드는 `produces[]` 산출물이 아니므로 리뷰 영수증에 영향이 없다.

## Tradeoffs

- 2026-07-30T01:40:00Z — 리뷰어가 지적한 `code-summary.md`의 부정확한 문장("메타데이터에 테이블 6개")을 고치지 않고 남겼다; `main.py`가 `app.models`를 import하지 않아 실제로는 `Base.metadata.tables`가 비어 있다(Alembic은 `migrations/env.py`에서 따로 import하므로 기능 결함은 아니다). 고치면 `produces[]` 산출물에 쓰는 것이 되어 방금 받은 리뷰 영수증이 무효화된다. 리뷰어가 같은 파일의 `## Review` 절에 그 사실을 이미 적어두었으므로 기록은 자기교정 상태다.

- 2026-07-30T02:20:00Z — 사용자가 Docker Desktop을 띄운 뒤 U1의 미검증 항목을 즉시 해소했으나 결과를 `foundation/code-summary.md`에 쓰지 않았다; 그 파일은 `produces[]` 산출물이라 다시 쓰면 방금 받은 foundation 리뷰 영수증이 무효화되어 리뷰어를 다시 돌려야 한다. 그 파일 자체가 "이것이 build-and-test(3.6)의 첫 항목"이라고 적어두었으므로 공식 기록은 3.6이 소유한다. 여기와 사용자 보고에만 남긴다. 검증 결과: `pytest` **45 passed / 0 skipped**(실제 MariaDB 11), `docker build` 성공, `docker compose up`으로 db healthy → `alembic 0001` 적용 → uvicorn 단일 프로세스(PID 1, `--workers 1`) 확인, `/health` 200 `{"status":"ok","db":"ok"}`, SPA `/` 200 text/html, 테이블 6개 전부 `utf8mb4_unicode_ci`, 한글+이모지 왕복이 **바이트 단위로 정확**. FR-9.1~FR-9.5가 이제 DDL 추론이 아닌 실측 증거를 갖는다.
- 2026-07-30T02:20:00Z — `backend/.venv`를 만들어 로컬 테스트 경로를 세웠다; 앞선 세션의 에이전트가 쓴 환경이 사라져 `pytest`가 없었다. `.gitignore`가 이미 `.venv/`를 무시한다. 부수 효과로 ASCII 수정 후의 `pip install -r requirements-dev.txt`가 이 cp949 호스트에서 통과하는 것이 확인되었다 — 리뷰어의 비차단 지적 ①이 실측으로 닫혔다.

- 2026-07-30T04:10:00Z — auth-friends에서 `code-summary.md`를 리뷰어가 만들게 해 리뷰 절만 담긴 파일이 되었고, 스테이지 Step 5가 요구하는 요약을 채우자 리뷰 영수증이 무효화되어 2차 리뷰가 필요해졌다. foundation에서는 요약을 먼저 쓰고 리뷰어를 붙여 이 비용이 없었다. **순서는 항상 요약 먼저, 리뷰어 나중이다** — 리뷰어는 `## Review`를 append하는 역할이고 파일을 창조하는 역할이 아니다. 2차는 "코드 불변, 산문만 추가"로 범위를 좁혀 산문의 검증 가능한 주장만 대조하게 했다.
- 2026-07-30T04:10:00Z — `conftest.py`가 저장소 `.env`를 읽지 않아 `TEST_DATABASE_URL`을 매번 export해야 했고 잊으면 스키마 테스트가 조용히 skip됐다; `.env`의 오타를 고쳐도 증상이 그대로여서 원인이 파일이 아니라 로더의 부재임이 드러났다. 세 `setdefault` **뒤에** `.env`를 setdefault로 얹는 순서가 핵심이다 — `.env`의 `DATABASE_URL`은 compose 내부 호스트명 `db`를 가리켜 호스트에서 닿지 않으므로, 앞에 오면 전체 스위트가 깨진다.

- 2026-07-30T12:40:00Z — judgment-core에서 리뷰어가 NOT-READY를 냈고 지적이 옳았다; 사람이 "타임아웃 4초로"라고 답한 것을 `.env` 두 파일에만 반영하고 `config.py`의 필드 기본값은 5.0으로 두었다. 계획의 Step 1이 `.env` 두 파일만 지목한 것이 원인이며 **계획의 범위 설정 자체가 좁았다.** 설정값 결함을 고칠 때는 설정이 해석되는 **모든 출처**를 세어야 한다 — `.env`, 코드 기본값, 그 기본값을 고정하는 테스트. 하나만 고치면 환경변수를 직접 주입하는 배포에서 조용히 되돌아간다.
- 2026-07-30T12:40:00Z — 수정 테스트를 `== 4.0`이 아니라 `MAX_ATTEMPTS * default < TOTAL_BUDGET_SECONDS` 부등식으로 짰다; 숫자로 박으면 다음 사람이 값을 바꾸며 테스트도 함께 고쳐 불변식이 사라진다. 상수를 소유 모듈에서 import해 부등식으로 검사하면 어떤 값을 골라도 상한을 깨는 순간 붉어진다.

- 2026-07-30T14:30:00Z — messaging에서 순차 테스트로는 절대 안 보이는 MariaDB 버그가 나왔다; InnoDB는 트랜잭션의 read view가 잡힌 뒤 갱신된 행에 잠금 읽기가 닿으면 `1020 Record has changed since last read`를 낸다(MySQL은 최신 커밋본을 준다). `send_message()`의 1~5단계가 read view를 잡아 **첫 번째 이후의 동시 전송이 전부 실패**했다. NFR-7이 "동시 채번"을 명시 테스트 의무로 지목해두지 않았다면 데모 중에 발견했을 것이다. 리뷰어가 `_persist()`의 선행 커밋을 제거한 사본으로 재현해 1 성공 / 7 실패를 직접 확인했다.
- 2026-07-30T14:30:00Z — 리뷰어가 `code-summary.md`의 파일별 테스트 개수 두 칸을 틀린 것으로 잡았다(`test_report.py` 13→14, `test_history.py` 12→11). 합계와 총계는 맞다. **에이전트가 보고한 숫자를 그대로 옮겨 적은 것이 원인이며**, project.md에 이미 "셀 수 있는 것은 스크립트로 센다"가 학습되어 있는데 그 규칙이 내가 쓴 요약에는 적용되지 않았다. 남의 보고를 옮길 때도 같은 규칙이 필요하다.

## Open questions

- 2026-07-30T12:40:00Z — FR-8.1이 문자 그대로 "타임아웃 3~5초"를 허용하는데 BR-6.7의 총 상한 10초와 NFR-1의 실측 대기 시간을 함께 보면 5는 여유가 0이다. 요구사항 수준의 긴장이며 Construction이 임의로 좁힐 자리가 아니다. 리뷰어도 같은 판단이며 후속 단계에서 기록할 항목으로 남긴다.
- 2026-07-30T12:40:00Z — `ContextMessage.seq`와 `judge()`의 내부 커밋 전제가 U2의 코드와 code-summary에만 기록되어 있다. U5의 code-generation은 자기 단위의 functional-design을 읽지 U2의 요약을 읽지 않으므로, U5 계획에 이 둘을 명시적으로 실어야 한다.

- 2026-07-30T00:30:00Z — 각 단위가 백엔드와 프론트를 함께 소유하는데(U3·U4·U5) 한 단위 안에서 어느 쪽을 먼저 만들지 정해지지 않았다. 2026-07-29 세션이 이 질문을 미해결로 남겼다. U1에서는 무의미하지만 U3부터 실제 순서가 갈린다.

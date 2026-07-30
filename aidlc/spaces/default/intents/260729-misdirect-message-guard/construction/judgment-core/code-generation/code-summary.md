# Code Summary — judgment-core (U2)

`code-generation-plan.md`의 11단계를 `aidlc-developer-agent`가 실행한 결과다. 체크박스 64개가 모두 `[x]`다.

**테이블은 새로 만들지 않았다.** U1의 `0001_initial_schema`가 만든 `judgment_logs`에 쓰기만 한다. 프론트엔드 몫이 없는 유일한 서비스 단위다.

## 생성된 파일 — `backend/app/judgment/`

| 파일 | 내용 |
|---|---|
| `constants.py` | 호출 예산 10초, `MAX_ATTEMPTS=2`, `TEMPERATURE=0`, 점수 클램프 경계, recall·precision 산출 불가 문자열, ASM-1 표시와 각주, 두 CLI가 공유하는 `use_utf8_console()` |
| `types.py` | `ContextMessage`, `Appropriate`/`Inappropriate`/`Failed`, `JudgeResult` 별칭, `MetricsReport` |
| `exceptions.py` | `AlreadyResolved`(409), `InvalidForceToken`(400), `ForceTokenForbidden`(403). **`Failed`는 이 계층에 없다** — 반환값이다 |
| `anonymize.py` | `label_speakers()`. 등장 순서 라벨, `Z` 다음은 전단사 base-26으로 `AA` |
| `prompt.py` | `SYSTEM_PROMPT`(설계 문서에서 **그대로** 옮김), `build_user_message()`, `build_messages()`, `RESPONSE_FORMAT`(`strict: true`) |
| `client.py` | `call_model() -> ModelCall`. per-request 타임아웃, **정확히 1회** 재시도, 예산 클램프, 예산 안에서만 `Retry-After` 존중, 실패 분류, `max_retries=0` |
| `service.py` | `judge()`, `get_log_for_force()`, `set_user_action()`, `link_message()` |
| `metrics.py` | `compute_metrics()` — 쿼리 3개, **분모 두 종류** |
| `router.py` | `PATCH /judgments/{log_id}` |
| `report.py` | `python -m app.judgment.report [--since]` (ADR-008) |
| `try.py` | `python -m app.judgment.try` — **DB 없이 돈다** |
| `__init__.py` | U5 계약 재노출 |

### 수정된 파일

| 파일 | 무엇 |
|---|---|
| `requirements.txt` | `openai==1.59.6` (ASCII 유지 확인) |
| `.env` / `.env.example` | `AI_TIMEOUT_SECONDS` **5 → 4** + 근거 주석 (Q1의 답) |
| `app/main.py` | judgment 라우터를 SPA 폴백보다 먼저 등록 |
| `tests/conftest.py` | `make_user`/`make_room` 헬퍼 추가 |
| `migrations/env.py` | **U1 파일** — `fileConfig(..., disable_existing_loggers=False)` (아래 참조) |

## 핵심 구현 결정

| 결정 | 근거 |
|---|---|
| **`ContextMessage`가 `seq`를 갖는다** (계획은 `(sender_id, text)`만이라 적었다) | BR-6.1이 `context_from_seq`/`context_to_seq`를 요구하고 두 컬럼이 NOT NULL인데 `judge()`의 시그니처는 고정이다. 기본값 없는 세 번째 필드로 두어, 2필드 형태로 짠 호출자가 0을 써넣는 대신 **즉시 실패**한다. ORM 의존은 여전히 없다 — `try`가 seq 1..n을 스스로 매긴다 |
| **`judge()`가 로그 INSERT 직후 커밋한다** | `flush()`만 하면 행이 호출자의 열린 트랜잭션 안에 남아, 호출 중 프로세스가 죽으면 사라진다 — BR-6.8이 막으려던 바로 그것이다. 호출자 요구사항으로 문서화: `judge()` 호출 시점에 커밋되지 않은 쓰기가 없어야 한다 |
| **빈 문맥은 `ValueError`** (`Failed`가 아니다) | 모델 호출에서 오는 것은 전부 `Failed`지만 호출자 계약 위반은 아니다. **로그 행이 생기기 전에** 터지므로 API 실패로 오인되지 않고 실패율을 부풀리지 않는다 |
| 라우터가 소유권을 범위 SELECT로 먼저 확인한 뒤 원자적 UPDATE를 호출 | 소유권은 경쟁하지 않고(바뀌지 않는다) `user_action`은 경쟁한다. 나누면 403과 409가 구별된 채 남는다. 없는 id는 403 — U3의 BR-2.7 선례와 같다 |
| **`PATCH`가 `auto_sent`를 거부한다** (422) | 서버가 붙이는 라벨이며 "묻지 않았다"는 뜻이다. 클라이언트가 주장하게 두면 FR-7.3의 라벨 의미가 오염된다 |
| 계약 위반(`json_schema` 거부·본문 파손·거절)은 ERROR로 남기고 **재시도하지 않는다** | 장애(WARNING)와 분리해야 설정 오류를 API 장애로 오해하지 않는다. `try`가 원문을 그대로 보여준다 |
| **`migrations/env.py`에 `disable_existing_loggers=False`** | 기본값 `True`가 마이그레이션이 인프로세스로 돌 때마다 모든 `app.*` 로거를 조용히 껐다. ERROR 로깅 테스트가 단독으로는 통과하고 전체 스위트에서는 실패해 드러났다. U1 파일의 한 줄이며 마이그레이션 동작은 그대로다 |
| 두 CLI가 `use_utf8_console()`을 부른다 | 규칙이 못박은 `—`(U+2014)가 cp949에 없어 `report`와 `try --help`가 `UnicodeEncodeError`로 죽었다. 문자열은 규칙이므로 바꿀 것은 인코딩 쪽이다 |
| **`config.py`의 `AI_TIMEOUT_SECONDS` 기본값도 4.0으로** (리뷰 1차 NOT-READY 후 수정) | 처음에는 `.env` 두 파일만 고치고 코드 기본값을 5.0으로 두었으나, 리뷰어가 `Settings(_env_file=None)`으로 **그 기본값이 실제 런타임 경로임을 증명**했다 — 환경변수를 직접 주입하는 배포(CI·k8s·필수 세 비밀만 남긴 `.env`)에서는 여기가 유일한 출처이고, `docker-compose.yml`의 `env_file: required: true`는 파일 존재만 확인하지 키 존재는 확인하지 않는다. 당시의 방어("`client.py`의 예산이 어차피 클램프한다")는 두 가지를 혼동한 것이다 — 그 테스트가 증명하는 것은 **SDK에 넘기는 두 `timeout=` 값의 합**이 예산을 넘지 않는다는 것뿐인데, 5.0에서 그 합은 정확히 10.0초로 **여유가 0이다.** NFR-1이 재는 것은 사용자가 보는 전송 대기 시간이고 거기에는 `judge()`의 커밋 왕복 두 번(BR-6.8의 호출 전 로그 쓰기, 호출 후 갱신)이 `call_model()` 창 **밖에서** 포함된다 |

## 테스트 커버리지

Test Strategy **Standard**. **OpenAI 호출은 전부 목이다** — 키 없이 돌고 비용이 들지 않는다.

| 파일 | 개수 |
|---|---|
| `test_anonymize.py` | 7 |
| `test_prompt.py` | 7 |
| `test_client.py` | 22 |
| `test_judge.py` | 12 |
| `test_force_log.py` | 18 |
| `test_metrics.py` | 13 |
| `test_config.py`(U1 파일에 추가) | +1 — `MAX_ATTEMPTS * 기본 타임아웃 < TOTAL_BUDGET_SECONDS` 부등식 |

**신규 80개, skip 0.** 전체 **187 passed / 0 skipped** (U1 45+1 + U3 62 + U2 79).

새 테스트가 **숫자가 아니라 불변식을 고정한다.** `== 4.0`으로 박으면 다음 사람이 값을 바꾸면서 함께 고쳐버린다. `MAX_ATTEMPTS`와 `TOTAL_BUDGET_SECONDS`를 `app.judgment.constants`에서 import해 부등식으로 검사하므로, 어떤 값을 고르든 상한을 깨면 붉어진다. 등호가 아니라 **엄격한 부등호**인 것이 핵심이다 — 여유 0이 바로 5.0을 위험하게 만든 상태였다.

## 검증 결과 — 있는 그대로

| 명령 | 결과 |
|---|---|
| `ruff check .` / `ruff format --check .` | PASS (55 파일) |
| `pytest -q` | **187 passed, 0 failed, 0 skipped** |
| **비공허성 확인** | 기본값을 5.0으로 임시 되돌리면 두 테스트가 **실제로 실패**한다(`assert 5.0 == 4.0`, 여유 부등식). 파일 즉시 복구, `default=4.0` 확인 |
| `python -m app.judgment.report` | PASS. 씨드 데이터로 `precision 0.769 (TP 20 / FP 6) ※ 근사 — ASM-1 참조`, `recall 산출 불가 — 라벨 데이터셋 필요`, `API 실패율 2.1% (3/145)`. **빈 DB에서는 `산출 불가 — 부적절 판정 건이 없음`**. DB 불통 시 한 줄 메시지 + exit 1, 트레이스백 없음 |
| `python -m app.judgment.try --dry-run` | PASS. 설계 문서의 예시를 **바이트 단위로 재현**(`A/B/A` + `B: 오늘 저녁에 치킨 어때?`). 자리표시 키로는 401을 받아 **원문 오류를 출력하고 재시도하지 않으며** exit 1 |
| **프롬프트 충실도** | PASS — `SYSTEM_PROMPT`를 `business-logic-model.md`의 펜스 블록과 스크립트로 대조해 `EQUAL: True` |
| `npm run typecheck` / `npm run build` | PASS (영향 없음) |
| 라이브 스택 | **손대지 않았다.** 두 컨테이너 `Up (healthy)`, `/health` 200 |

## 계획과의 차이

| 차이 | 이유 |
|---|---|
| `ContextMessage`에 `seq` 추가 | 위 결정 표. **U5가 `ContextMessage(sender_id=m.sender_id, text=m.body, seq=m.seq)`로 만들어야 한다** |
| `migrations/env.py` 수정 (U1 파일) | 위 결정 표 |
| `conftest.py`에 `make_user`/`make_room` | judgment_logs의 FK를 채우려면 사용자·방이 필요하다 |
| 계획 체크박스를 **마지막에 한 번에** 표시 | 지시는 "진행하며 표시"였다. 에이전트가 스스로 신고했다 |
| `config.py`·`test_config.py` 수정 (계획의 Step 1은 `.env` 두 파일만 지목) | 리뷰 1차 NOT-READY의 차단 지적. 계획의 범위 설정 자체가 좁았다 |

### 기동 시 검증기를 넣지 않은 이유

`2 × timeout >= 10`을 거부하는 검증기를 넣으면 **FR-8.1이 문자 그대로 허용하는 값(`타임아웃 3~5초`)에서 앱이 기동하지 않는다.** 그 긴장을 풀려면 `requirements.md`를 고쳐야 하는데 Construction 단계가 상류 요구사항을 고칠 자리는 아니다. 결함은 **우리가 출하하는 기본값**에 있었지 운영자가 의도적으로 덮어쓰는 값에 있지 않았다. 테스트가 우리 값을 고정하고, 위로 덮어쓰면 `client.py`의 클램프가 측정 창을 여전히 묶는다. 기동 시 경고가 필요하다면 하드 거부가 아니라 WARNING이어야 하며, 그것도 요구사항 변경이 먼저다.

## 미해결 — 다음 단계가 알아야 할 것

1. **떠 있는 컨테이너에 이 코드가 없다.** `docker-compose.yml`이 바인드 마운트 없이 이미지를 굽는다. 다음 `docker compose up --build`가 있어야 `openai`가 설치되고 판정 라우터가 올라온다
2. **여러 줄 본문을 통한 프롬프트 주입.** 본문이 설계대로 그대로 직렬화되므로 `## 보내려는 메시지` 같은 줄이 섹션 헤더를 흉내낼 수 있다. 영향은 한정적이다 — 사용자가 왜곡할 수 있는 것은 **자기 메시지의 판정뿐**이고, `force_log_id`가 이미 같은 결과에 이르는 합법 경로를 준다. 고치지 않은 이유는 사용자 텍스트를 정규화하면 **판정 대상과 실제 전송 내용이 달라지기** 때문이다
3. **`set_user_action()`이 없는 로그 id에 409를 낸다.** 두 호출자 모두 존재를 먼저 확인하므로 진짜 경쟁 상황에서만 발생한다
4. `latency_p50/p95/max`는 판정된 행만 센다. 타임아웃 지연은 설계상 제외되며 API 실패율이 그것을 보고한다. "지연 분포"의 독자 기대와 맞는지 확인 필요
5. **검증되지 않은 가정 셋** — 프롬프트가 한국어인 것, 점수 구간 설명이 실제로 분포를 벌리는지, 윈도우 한정 라벨이 품질에 영향을 주는지. `try`가 이것을 시험하는 도구이며 **실제 키로 아직 돌지 않았다**
6. U5가 바인딩하는 다섯 이름 — `judge`, `get_log_for_force`, `set_user_action`, `link_message`, `compute_metrics`. 전부 `app.judgment`에서 import 가능하다

## 커밋 상태

커밋되지 않았다.

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

### Second pass (re-review after the NOT-READY fix)

This is a **second pass**, scoped to verifying the fix for the one blocking finding from the first pass and re-checking what that fix could have disturbed. I did not re-run the full rule-by-rule sweep (prompt fidelity, `judge()` exception safety, retry-exactly-once, the atomic UPDATE, the six `force_log_id` checks, metrics axis, anonymization) — the fix touches only `config.py`'s default/comment and `test_config.py`, none of which those areas depend on, so those verdicts stand unchanged from the first pass ("What held up under attack," preserved below).

**What I re-verified, independently, not by trusting the lead's report:**

1. **Reproduced my own blocking finding's repro path.** `backend/app/core/config.py:81` now reads `AI_TIMEOUT_SECONDS: float = Field(default=4.0, gt=0.0)`, and the comment above it (lines 67-80) states the actual constraint (BR-6.7's 10s cap, NFR-1's "전송 대기 시간" window, the two commit round-trips in `judge()` that sit outside `call_model()`'s measured window) instead of the old "3~5초" line. I built `Settings` myself, independently of the test suite: with only the three required secrets supplied and `AI_TIMEOUT_SECONDS` absent from the process environment, both a freshly-constructed `Settings(_env_file=None, ...)` and the module-global `settings` singleton resolve to `4.0`. The exact deployment path my first pass flagged (env-var injection with no `AI_TIMEOUT_SECONDS` key) now yields the safe value.
2. **Confirmed the new invariant test is not vacuous, without touching application code** (the task constraints forbid modifying it, so I did not literally revert the default as the lead reportedly did). Instead I computed the assertion's both sides directly from `app.judgment.constants` (`MAX_ATTEMPTS=2`, `TOTAL_BUDGET_SECONDS=10.0`) against candidate values: at `5.0`, `MAX_ATTEMPTS * 5.0 = 10.0`, and `10.0 < 10.0` is `False` — the assertion would fail, so the test genuinely catches a reversion to the old default. At `4.0` it's `8.0 < 10.0` → `True`. The strict `<` matters: `<=` would have let 5.0 back in silently. I also confirmed by reading `test_config.py:109-135` that `test_default_timeout_leaves_margin_under_the_total_budget` reads `_build().AI_TIMEOUT_SECONDS` — a freshly constructed `Settings`, not the module-global `settings` — and that it explicitly `monkeypatch.delenv`s every key in `_OPTIONAL_KEYS` (including `AI_TIMEOUT_SECONDS`) before building, which matters: I separately demonstrated that without that `delenv`, a shell-level `AI_TIMEOUT_SECONDS` env var *does* mask the coded default (built `Settings(_env_file=None, ...)` with `AI_TIMEOUT_SECONDS=7.5` in the environment and no override kwarg → got `7.5`, not the field default) — so the `delenv` step is load-bearing, not decorative, and the test correctly avoids that trap.
3. **Judged the declined startup validator.** The reasoning is sound as far as it goes: `requirements.md:445` (FR-8.1) literally says "타임아웃 3~5초," and `business-rules.md:82` (BR-6.7) repeats "AI_TIMEOUT_SECONDS (3~5초)" alongside "총 상한 10초를 **넘지 않는다**." At `AI_TIMEOUT_SECONDS=5`, the sum of the two per-attempt `timeout=` values is exactly `10.0`, which literally does not exceed BR-6.7's stated cap — so a hard-reject validator on `5` would refuse to boot on a value two requirements documents explicitly permit, and Construction has no mandate to tighten FR-8.1 unilaterally. That is a genuine tension between BR-6.7's narrow accounting (the model-call window only) and NFR-1's broader one (`requirements.md:615`, "전송 대기 시간," which necessarily includes `judge()`'s pre-call and post-call commits) — a requirements-level ambiguity, not a construction bug, and I agree it's correctly deferred rather than "fixed" here by silently overriding what the requirement text allows.
   - **The residual is real and should be named plainly, not glossed over:** an operator who sets `AI_TIMEOUT_SECONDS=5` — a value FR-8.1's text permits — reintroduces the exact zero-margin condition Q1 was raised to close. I judge this residual **acceptable to ship**, because it now requires a deliberate, informed operator action against a documented default (the field comment states the inequality to check before raising the value) rather than being the shipped default everyone gets for free; the risk profile changed from "everyone is exposed" to "someone who overrides against documented advice is exposed."
   - One place I'd push back slightly: the summary's own "기동 시 검증기를 넣지 않은 이유" section declines even a non-blocking startup **WARNING** on the grounds that "그것도 요구사항 변경이 먼저다." I don't think that follows — a `WARNING` log doesn't reject or override a value FR-8.1 permits, it only surfaces the same tension the code comment already documents, at the moment an operator would most want to see it. That's a suggestion for a later construction pass, not a blocker.
   - **Recommend recording this as a requirements-level tension for a later stage**, not something for Construction to resolve by fiat: FR-8.1's literal "3~5초" and NFR-1/BR-6.7's implied need for margin against `judge()`'s out-of-band commit costs are in tension, and only an inception-level pass (or an explicit corrections entry) can settle whether FR-8.1's range should narrow to "3~4" or NFR-1's window should be redefined.
4. **Re-ran the full suite and linters myself.** `backend/.venv/Scripts/python.exe -m pytest -q` → `187 passed in 10.99s`, **0 skipped** (pytest reports skips inline; none appeared). `ruff check .` → `All checks passed!`. `ruff format --check .` → `55 files already formatted`. All match the expected 187/0/0.
5. **Confirmed the fix broke nothing in the budget-clamping path.** Read `client.py:232-320` end to end: `per_attempt_timeout = float(settings.AI_TIMEOUT_SECONDS)` still feeds `timeout = min(per_attempt_timeout, remaining)` unchanged. Read `test_client.py` in full: `test_total_wait_stays_inside_the_ten_second_budget` exercises the real (now-4.0) default through actual budget arithmetic and would pass at either 4.0 or 5.0 (both fit ≤10s), so it isn't newly vacuous, just less tight than it used to be — that tightness is now the new `test_config.py` invariant's job, not this test's. `test_second_attempt_timeout_is_clamped_to_the_remaining_budget` explicitly `monkeypatch.setattr(settings, "AI_TIMEOUT_SECONDS", 8.0)`, independent of the field default, so it's unaffected by the change. Grepped `backend/tests/` for stray `5.0` literals tied to the old default — none found outside `test_config.py` (the one unrelated hit, `test_health.py:143`'s `wait_for_database(timeout=5.0)`, is an unrelated DB-wait parameter). No test now passes only because the default moved from 5.0 to 4.0.

Also confirmed `code-summary.md` (this file) no longer contains the stale "config.py는 5.0 그대로" claim anywhere outside this Review section's own historical record of the original finding (below) — the "핵심 구현 결정" and "계획과의 차이" tables both correctly state the default is now 4.0, and the file's `.env`/`config.py` values match what I independently observed. One minor completeness gap I noticed but don't consider blocking: the "생성된 파일 / 수정된 파일" table doesn't list `app/core/config.py` or `tests/test_config.py` as modified files (they're only mentioned in the decision-rationale and delta tables) — worth a tidy-up, not a defect.

### Original blocking finding (fixed — kept for the record)

**1. The NFR-1 fix from Q1 does not survive a real deployment path — `config.py`'s own default is still the unsafe value the human asked to be fixed.** *(Status: FIXED and independently reverified above.)*

Q1 (`code-generation-questions.md`) exists because `business-rules.md`'s own open-item text says `AI_TIMEOUT_SECONDS` must be **≤4** to keep BR-6.7's 10s cap; at 5, "재시도 포함 대기가 정확히 10초이고... 연결 수립·직렬화 오버헤드가 얹히면 NFR-1... 을 넘는다." The human picked "A. 4로 낮춘다." The plan's Step 1 checkbox scoped the fix to `.env.example`·`.env` only, and that's the only place it landed:

- `backend/app/core/config.py:68` — `AI_TIMEOUT_SECONDS: float = Field(default=5.0, gt=0.0)` — unchanged. Line 67's comment still reads "3~5초," directly contradicting the value business-rules.md computed as unsafe.
- I proved this is the *actual* runtime fallback, not a dead code path: `Settings(_env_file=None)` with only the three required secrets set (no `AI_TIMEOUT_SECONDS`) resolves to `5.0`. Any deployment that injects env vars directly (CI, k8s, a hand-trimmed `.env` that copies only the three `:?`-required secrets and skips the optional ones) silently reverts to 5.0 — nothing enforces that `AI_TIMEOUT_SECONDS` itself is set, only that a `.env` *file* exists (`docker-compose.yml`'s `env_file: { required: true }` checks file presence, not key presence).
- `backend/tests/test_config.py::test_defaults_match_the_design` asserts `config.AI_TIMEOUT_SECONDS == pytest.approx(5.0)` and calls that "매칭 the design" — this now actively pins the pre-fix value and will fail if `config.py`'s default is later corrected to 4, unless it's also updated.
- The summary's own justification ("client.py의 10초 예산이 두 번째 시도를 어차피 클램프하므로 5든 8이든 NFR-1은 지켜진다(8에서 테스트로 증명)") conflates two different things. I traced `test_second_attempt_timeout_is_clamped_to_the_remaining_budget` and `test_total_wait_stays_inside_the_ten_second_budget`: they prove the **sum of the two per-attempt `timeout=` kwargs passed to the SDK** never exceeds `TOTAL_BUDGET_SECONDS`. At the 5.0 default that sum clamps to *exactly* 10.0s with **zero margin** (5 + min(5, 10−5) = 10). But NFR-1 measures "전송 대기 시간" — the full request the user is staring at — which also includes `judge()`'s own `await session.commit()` **before** the model call (BR-6.8's log-first requirement, `service.py:139`) and the second `commit()` **after** it (`service.py:179`), both real DB round-trips sitting outside `call_model()`'s measured window. At AI_TIMEOUT_SECONDS=5 there is no slack left anywhere in the budget to absorb those; at 4 (8s model-call ceiling) there's the 2s margin `business-rules.md` calculated for exactly this overhead. "5 or 8, NFR-1 holds either way" is true of the internal `call_model()` invariant and not established for NFR-1 itself.
- This is precisely the class of gap `project.md` says to raise immediately rather than defer ("산출물을 쓰는 중 질문 목록에 없던 공백을 발견하면... 즉시 사람에게 제기한다") — doubly so here since it's a live regression of an already-answered question (Q1), not a fresh one.

Fix applied: `config.py`'s `AI_TIMEOUT_SECONDS` field default lowered to `4.0` with a rewritten comment stating the actual constraint; `test_config.py::test_defaults_match_the_design` updated to assert `4.0`; new `test_config.py::test_default_timeout_leaves_margin_under_the_total_budget` added, asserting `MAX_ATTEMPTS * default < TOTAL_BUDGET_SECONDS` (imported from `app.judgment.constants`, strict `<`, read off a fresh `Settings`). Verified above.

### Non-blocking (carried forward from the first pass, unchanged — not re-verified this pass per scope)

**2. `ContextMessage.seq` deviates from the approved plan text without a documented path for U5 to learn about it.** The plan explicitly said `ContextMessage`는 "(sender_id, text)만" (and Q2 approved that plan). The shipped `types.py` adds a required third field `seq`, which I judge **sound and effectively necessary** — BR-6.1/`domain-entities.md` require `context_from_seq`/`context_to_seq` to be NOT NULL, `judge()`'s 5-argument signature is frozen, and a 2-field `ContextMessage` has no other way to supply that range. The failure mode if U5 gets it wrong is loud (`TypeError: missing required positional argument 'seq'`), not silent data corruption, so it's not a correctness hole. But `unit-of-work-dependency.md` — the document explicitly named as recording "U2가 U5에 제공하는 계약" — says nothing about `ContextMessage`'s shape, and U2 U5's own construction Step 1 (per `code-generation.md`) reads *its own* unit's functional-design directory, not U2's `code-summary.md`. The only place this contract change is recorded outside the code itself is this summary's "계획과의 차이" section. Same applies to the second internal decision this stage made unilaterally: `judge()` now `commit()`s internally (not just `flush()`), imposing "no uncommitted writes in the caller's session before calling `judge()`" as a hard precondition on U5 — sound (it's the only reading consistent with `business-logic-model.md`'s "호출 중 프로세스가 죽어도 시도한 흔적이 남는다," and compatible with ADR-001's "LLM 호출은 트랜잭션 밖"), but likewise recorded only in code comments and this summary. Recommend surfacing both in `unit-of-work-dependency.md` (or wherever U5's functional-design stage is guaranteed to read) before U5's construction starts, rather than relying on U5 discovering them via this file.

**3. `try.py`'s dry-run default does not reproduce the design doc's worked anonymization example, and the summary's verification claim doesn't say so.** I ran `python -m app.judgment.try --dry-run` with the exact context/candidate text from `business-logic-model.md`'s "단독 검증 경로" example command (which itself omits `--sender`) and got `C: 오늘 저녁에 치킨 어때?` — not the `B:` the design doc's separate "알고리즘: 문맥 익명화" section shows, because that example's `candidate_sender_id=12` is a *returning* speaker while the CLI's undocumented-in-the-summary default (`--sender` unset) assigns a **new** speaker. Reproducing the anonymization example byte-for-byte requires `--sender 2`, which I confirmed produces the exact match. The code-summary's "바이트 단위로 재현" claim is achievable but only with a flag it doesn't mention — not a functional defect (the CLI's default behavior is reasonable and documented in its own `--help`), but the verification entry should show the actual command used.

**4. The "seed data" numbers in the report-CLI verification entry are suspicious.** Every number the summary quotes for `python -m app.judgment.report` (판정 건수 142, flag rate 26/142, precision TP 20/FP 6, 미응답 3건, latency p50/p95/max 1.2s/3.4s/4.9s, tokens 38,410 = 35,120/3,290, API 실패율 3/145, 신고율 2/143, 미검출 후보 1건) is byte-identical to `business-logic-model.md`'s own illustrative report example, and also to `test_metrics.py::_empty_report()`'s hardcoded fixture. I independently confirmed the currently-running container has no path to having produced this via a live run (see #5 below) — it doesn't have this code at all. This is very likely a deliberate reproduction against locally-seeded rows crafted to match the doc's example (a legitimate way to verify rendering fidelity), not fabrication, but phrasing it as "씨드 데이터로" without noting it reproduces the doc's own numbers invites a reader to mistake it for organic validation. Minor, worth tightening in future summaries.

**5. `set_user_action()` doesn't validate `action` itself.** The HTTP boundary (`router.py`'s `Literal["sent", "cancelled"]`) and U5's documented contract are the only things constraining the value; `service.py`'s `set_user_action(session, log_id, action: str)` writes whatever string it's given, relying on SQLAlchemy's `Enum` type to raise at bind time if a future caller passes something outside `USER_ACTION_VALUES`. That failure would surface as a raw `StatementError`/`LookupError`, not a domain exception. No reachable path today (the one wired caller is validated), so not blocking — worth a defensive check if a second internal caller (e.g., U5's own `auto_sent` write) is added without going through the router.

### What held up under attack

- **Prompt fidelity** — script-diffed `SYSTEM_PROMPT` against `business-logic-model.md`'s fenced block character-for-character (`EQUAL: True`, 580 chars). All three "판단하지 않는 것" clauses and all four score bands with their descriptions are present and unmodified.
- **`judge()` never raises** — drove `call_model()` directly with a fake client raising a raw `KeyError` (not in the test suite): caught by the generic `except Exception`, classified `KIND_UNEXPECTED`, `attempts=1`, returned as `ok=False` without escaping. Combined with the existing timeout/connection/5xx/429/400/malformed-body/refusal tests, every failure mode named in the brief is covered and none escapes. The `ValueError`-on-empty-context deviation is sound: it's a caller-contract violation that fires before the log row exists, so it can't pollute the API-failure-rate denominator, and it's tested (`test_empty_context_is_a_caller_error_not_a_judgment_failure`).
- **Retry-exactly-once / budget** — `max_retries=0` is set and asserted by a dedicated test (`test_sdk_retries_are_disabled`); `Retry-After` is honored only within remaining budget (`test_retry_after_beyond_the_budget_does_not_wait` / `..._is_honored`); the fake-clock tests exercise the real budget-clamping arithmetic (assert on the actual `timeout=` values sent), not just call counts.
- **Atomic conditional UPDATE** — `capture_sql()` confirms the literal SQL: single `UPDATE judgment_logs SET user_action=...` starting the statement and containing `user_action is null`, not a SELECT-then-UPDATE (`test_set_user_action_emits_the_null_guard_in_sql`).
- **`get_log_for_force`'s six checks** — traced and tested individually: owner mismatch is the only 403, all five others are `InvalidForceToken`(400); text comparison is trim-then-exact with inner-whitespace collapse correctly rejected as a mismatch; `verdict` accepts `inappropriate` and `NULL`, rejects `appropriate`. No bypass found.
- **Metrics** — aggregation is `judgment_logs WHERE verdict IS NOT NULL` throughout except `api_failure_rate`, which correctly uses the unfiltered `attempted` count; precision returns `None` (not 0.0) at zero denominator and renders `"산출 불가 — 부적절 판정 건이 없음"`; recall is always the literal unavailable string, never a number; the ASM-1 `※ 근사` footnote is unconditional.
- **Anonymization** — traced the bijective base-26 by hand (25→Z, 26→AA, 27→AB) and confirmed against `test_more_than_twenty_six_speakers_continue_with_two_letters`; no off-by-one. `sender_id` never reaches the model (`test_output_never_contains_a_sender_id`).
- **`migrations/env.py`** — the U1 change is exactly one kwarg (`disable_existing_loggers=False`), well-justified, and the full suite (including the double-`alembic upgrade head` idempotency check) passes.
- **Tests** — reproduced every count myself via `pytest --collect-only`, not by trusting the summary: 7/7/22/12/18/13 per file, 186/0/0 for the full suite. All OpenAI calls are mocked; no test needs a real key (confirmed by running the whole suite with a placeholder `OPENAI_API_KEY`).
- **Runs** — `ruff check .` and `ruff format --check .` clean (55 files); `pytest -q` → 186 passed, 0 skipped; `python -m app.judgment.try --dry-run` produces the correct anonymized layout; `python -m app.judgment.report` against an unreachable DB exits 1 with a one-line message and no traceback, matching the documented UX; `npm run typecheck` and `npm run build` clean. Confirmed the live stack was not touched and, separately, that it genuinely lacks this unit's code (`/app/app/judgment` in the running container has only `__init__.py`; `openai` is not installed) — consistent with the summary's own disclosure, not a new finding.

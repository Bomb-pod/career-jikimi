# Code Generation Questions — judgment-core (U2)

`functional-design`의 열린 항목 7건은 계획 안에서 근거를 붙여 닫았다(`code-generation-plan.md` § 이 계획이 닫는 열린 항목). ADR-005가 이월한 모델 지원 확인도 닫혔다 — `gpt-4o-mini`가 `strict: true` Structured Outputs를 지원한다.

사람에게 물어야 하는 것은 하나다. 계획을 쓰다 발견한 **결함**이고, 고치면 이미 승인된 값이 바뀐다.

---

## Q1 — `AI_TIMEOUT_SECONDS`의 현재 기본값 5는 NFR-1을 넘긴다

`business-rules.md` BR-6.7이 정한 것:

- 타임아웃 `AI_TIMEOUT_SECONDS` (3~5초)
- 재시도 **정확히 1회**
- **총 상한 10초를 넘지 않는다**

그 문서 스스로 열린 항목에 이렇게 적어두었다 — *"`AI_TIMEOUT_SECONDS`의 구체적 기본값(3인지 5인지)이 정해지지 않았다. **총 상한 10초를 지키려면 4 이하여야 한다.**"*

그런데 U1의 `.env.example`이 `AI_TIMEOUT_SECONDS=5`로 확정해버렸다. 5초 × (최초 1회 + 재시도 1회) = **정확히 10초**이고, 여기에 연결 수립·직렬화 오버헤드가 얹히면 NFR-1의 "재시도를 포함한 최악의 경우 10초 이내"를 넘는다.

사용자가 체감하는 것은 이것이다 — 판정이 실패하는 최악의 경우 **전송 버튼이 10초 넘게 잠긴 채** "확인 중..."만 보인다.

- A. **4로 낮춘다 (추천)** — 재시도 포함 8초 + 오버헤드. `business-rules.md`가 계산한 값 그대로다. 느린 응답 일부를 타임아웃으로 버리게 되지만 상한을 지킨다
- B. **3으로 낮춘다** — 6초. 여유가 더 크고 체감이 낫다. 정상 응답도 타임아웃될 확률이 A보다 높다
- C. **5를 유지하고 NFR-1의 상한을 12초로 고친다** — 요구사항을 현실에 맞춘다. 상류 문서(`requirements.md`) 수정을 수반한다
- X. Other (please specify)

[Answer]: A. 4로 낮춘다 (추천) — 2026-07-30, **Mode:** guided

> `.env.example`과 `.env`의 `AI_TIMEOUT_SECONDS`를 5 → 4로 바꾼다. `business-rules.md`가 계산해둔 값 그대로이며 상류 요구사항(NFR-1)은 손대지 않는다.

---

## Q2 — Plan Approval

`code-generation-plan.md`의 judgment-core 실행 계획(11단계)을 승인하는가. 프론트엔드 몫이 없는 유일한 서비스 단위이며, 요구사항에 없는 개발 도구 `try` CLI를 포함한다(계획이 근거를 적어두었다).

- A. **Approve Plan** — 계획대로 코드 생성을 진행한다
- B. **Request Changes** — 계획을 수정한다
- X. Other (please specify)

[Answer]: A. Approve Plan — 2026-07-30, **Mode:** guided

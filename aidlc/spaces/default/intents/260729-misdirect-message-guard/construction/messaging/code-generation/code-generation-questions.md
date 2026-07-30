# Code Generation Questions — messaging (U5)

`functional-design`의 열린 항목 5건은 계획 안에서 근거를 붙여 닫았다(`code-generation-plan.md` § 이 계획이 닫는 열린 항목).

사람에게 물어야 하는 것은 하나다. **세 단위가 반복해서 제기했으나 아무도 정하지 않은 값**이며, 정하지 않으면 판정 비용이 무제한으로 열린다.

---

## Q1 — 메시지 본문 길이 상한

세 곳이 각자 열린 항목으로 남겼다:

| 어디 | 뭐라고 |
|---|---|
| `judgment-core/domain-entities.md` | "`candidate_text`가 TEXT라 길이 상한이 없다. 매우 긴 입력이 **토큰 비용을 키운다.** U5의 메시지 길이 제한과 함께 정해야 한다" |
| `messaging/domain-entities.md` | "메시지 본문 길이 상한이 없다(TEXT). 매우 긴 메시지가 판정 토큰 비용을 키우고 `judgment_logs.candidate_text`에도 그대로 들어간다. **상한을 정하는 편이 낫다**" |
| `messaging/business-rules.md` | "메시지 본문 길이 상한이 정해지지 않았다. **판정 토큰 비용과 직결된다**" |

상한이 없으면 한 사람이 긴 글을 붙여넣는 것만으로 그 방의 판정 비용이 크게 뜁니다 — 문맥 10개에 그 긴 메시지가 들어가면 이후 판정마다 반복해서 실립니다. 요구사항에는 이 값이 없습니다.

- A. **2000자 (추천)** — 채팅 메시지로 넉넉하고(한글 원고지 10장쯤) 문맥 10개를 합쳐도 토큰이 통제된다. 초과 시 400 `MESSAGE_TOO_LONG`, 프론트에 `maxLength`
- B. **500자** — 채팅다운 길이. 비용이 가장 안전하나 긴 업무 메시지가 잘린다
- C. **상한을 두지 않는다** — 요구사항에 없으므로 만들지 않는다. 비용 위험을 그대로 안는다
- X. Other (please specify)

[Answer]: A. 2000자 (추천) — 2026-07-30, **Mode:** guided

> 세 문서(`judgment-core/domain-entities.md`, `messaging/domain-entities.md`, `messaging/business-rules.md`)가 각각 남긴 열린 항목이 이 하나의 답으로 닫힌다. 상수 `MESSAGE_MAX_LENGTH = 2000` 하나이므로 되돌림 비용이 없다.

---

## Q2 — Plan Approval

`code-generation-plan.md`의 messaging 실행 계획(11단계)을 승인하는가. **마지막 단위이며 XL이다** — 앞의 네 단위가 여기서 만나고, NFR-7이 명시한 테스트 의무 둘(동시 채번 FR-4.2, degraded 상태 기계 FR-8.3·8.5)이 여기 있다.

- A. **Approve Plan** — 계획대로 코드 생성을 진행한다
- B. **Request Changes** — 계획을 수정한다
- X. Other (please specify)

[Answer]: A. Approve Plan — 2026-07-30, **Mode:** guided

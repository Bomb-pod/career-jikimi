# Code Generation Questions — U1 foundation

Construction 단계의 질문은 예외적이어야 한다(`stage-protocol.md` §3). 여기 두 건뿐이며, Q1은 이전 세션이 미해결로 남긴 공백이고 Q2는 스테이지가 요구하는 필수 계획 승인이다.

---

## Q1 — 한 단위 안에서 백엔드와 프론트 중 무엇을 먼저 만드는가

`unit-of-work.md`의 U3·U4·U5는 백엔드 모듈과 프론트 화면을 **한 단위에** 함께 소유한다. 2026-07-29 세션에서 "프론트를 먼저"라는 의사가 나왔으나 단위 구조가 둘을 묶고 있어 순서가 정해지지 않았다.

U1 foundation에서는 이 선택이 무의미하다(양쪽 골격을 다 만든다). **U3부터 실제로 갈린다.**

- A. **백엔드 먼저, 그 위에 프론트** — 각 단위에서 API를 먼저 완성하고 그 실물 계약 위에 화면을 붙인다. 계약이 실물이라 갈아끼울 일이 없다. 화면이 늦게 보인다
- B. **프론트 먼저, 목(mock) API로** — 화면부터 만들고 나중에 실제 API로 교체한다. 가장 빨리 보이지만 계약 불일치가 단위 끝에 몰려서 터진다
- C. **단위 안에서 얇게 교차** — 기능 하나(예: 로그인)를 백엔드→프론트로 끝내고 다음 기능으로 간다. 각 기능이 종단 간 동작하나 컨텍스트 전환이 잦다
- X. Other (please specify)

[Answer]: A. 백엔드 먼저, 그 위에 프론트 — 2026-07-30, **Mode:** guided

> 이 답변은 U1의 계획을 바꾸지 않는다(U1은 양쪽 골격을 다 만든다). **U3·U4·U5의 계획이 이 순서를 따른다.**

---

## Q2 — Plan Approval

`code-generation-plan.md`의 U1 foundation 실행 계획(11단계)을 승인하는가.

- A. **Approve Plan** — 계획대로 코드 생성을 진행한다
- B. **Request Changes** — 계획을 수정한다
- X. Other (please specify)

[Answer]: A. Approve Plan — 2026-07-30, **Mode:** guided

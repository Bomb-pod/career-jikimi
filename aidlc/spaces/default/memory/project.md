# Project-Level Rules

> Project-specific specialisation and corrections. Loaded after `org.md` and
> `team.md` as strict-additive guidance; contradictions with broader policy
> are rejected. Populated by practices-discovery and the self-learning loop.
>
> Use sparingly: most teams don't need a project layer. Reach for it
> only when this specific project needs stable, durable guidance beyond the
> team practice (for example, package-specific release checks or an additional
> regression suite for a legacy component).

## Way of Working

<!-- Project-specific specialisation. Example: -->
<!-- This monorepo requires package-scoped branch names and a package owner -->
<!-- review in addition to the team's normal merge policy. -->

## Walking Skeleton

<!-- Project-specific specialisation. Example: -->
<!-- The walking skeleton must exercise the legacy service adapter as well -->
<!-- as the new service boundary. -->

## Testing Posture

<!-- Project-specific specialisation. -->

## Deployment

<!-- Project-specific specialisation. -->

## Code Style

<!-- Project-specific specialisation. -->

## Tech Stack

<!-- Technology choices locked for this project. -->

## Decided

<!-- Decisions made in earlier stages that should not be re-asked. -->
<!-- Format: DECIDED: [decision] (Stage [slug], [date]) -->

## Scope Overrides

<!-- Custom scope rules for this project. -->

## Forbidden

<!-- Populated by practices-discovery affirmation gate. -->
<!-- Format: NEVER [behavior] (affirmed [date]) -->
<!-- Example: NEVER throw exceptions across service layer boundaries (affirmed 2026-05-17) -->

## Mandated

<!-- Populated by practices-discovery affirmation gate. -->
<!-- Format: ALWAYS [behavior] (affirmed [date]) -->
<!-- Example: ALWAYS use Result<T,E> for fallible operations in service layer (affirmed 2026-05-17) -->

## Corrections

<!-- Project-specific corrections from human feedback. -->
<!-- Format: NEVER/ALWAYS [behavior] (learned [date]) -->
- README.md는 스테이지의 등록 출처가 아니다. 산출물에 넣어야 할 README 내용은 질문 파일의 답변으로 재확인해 [Q<n>]로 인용한다 (learned 2026-07-29) <!-- cid:intent-capture:c1 -->
- org.md 등 memory 규칙을 [memory:M<n>]로 인용할 때는 물리적 줄 단위로만 정확 매치된다. 줄바꿈으로 잘린 문장은 그 줄 그대로 인용하거나 인용하지 않는다 (learned 2026-07-29) <!-- cid:intent-capture:c8 -->
- 서로 모순되는 선택지를 함께 고른 답변은 오답으로 처리하지 않고 후속 문항으로 재질의한다. 둘 다 취하려는 의도인 경우가 있다 (learned 2026-07-29) <!-- cid:intent-capture:c9 -->
- 앞 단계에서 확정된 결정과 반대 방향인 답변은 그대로 받지 않고 후속 문항으로 재질의한다. 양쪽을 다 살리는 중간 등급이 나오는 경우가 많다 (learned 2026-07-29) <!-- cid:scope-definition:c4 -->
- 우려를 제기한 뒤 사용자가 재확인한 결정은 그대로 따르되, 위험 등록부에 가능성과 영향을 붙인 사실로 남기고 절단 순서를 미리 명시한다 (learned 2026-07-29) <!-- cid:scope-definition:c5 -->
- 집계 결과가 구조적으로 안 나오면 필터 조건이 아니라 집계 축 자체를 의심한다. 집계 대상에 없는 사건은 어떤 필터로도 잡히지 않는다 (learned 2026-07-29) <!-- cid:requirements-analysis:c6 -->
- 산출물을 쓰는 중 질문 목록에 없던 공백을 발견하면 다음 단계로 미루지 말고 즉시 사람에게 제기한다. 그 자리가 반영 비용이 가장 싸다 (learned 2026-07-29) <!-- cid:requirements-analysis:c5 -->
- 요청-응답 의미가 필요한 경로는 HTTP로, 서버가 먼저 말하는 경로만 WebSocket으로 둔다. WS 위에 요청-응답을 얹으면 상관 ID·타임아웃·재시도·중복 방지를 직접 만들어야 한다 (learned 2026-07-29) <!-- cid:application-design:c3 -->
- 사용자가 응답하지 않고 이탈한 건을 오류로 처리하지 않는다. '물었는데 답하지 않았다'는 사실 자체가 관찰값이므로 비율 지표에서 제외하되 별도 건수로 집계한다 (learned 2026-07-29) <!-- cid:application-design:c4 -->
- 커버리지 표나 항목 수처럼 셀 수 있는 것은 눈으로 세지 않고 스크립트로 센다. 손으로 세면 틀리고, 고치면서 또 틀린다 (learned 2026-07-29) <!-- cid:units-generation:c5 -->
- 한 항목이 두 곳에 배정되어 있으면 분할로 선언하기 전에 단독 소유가 가능한지 먼저 따진다. 불필요한 분할은 소유하지 않은 쪽이 자기 몫인 줄 알고 설계하게 만든다 (learned 2026-07-29) <!-- cid:units-generation:c4 -->
- 기존 메커니즘의 의미가 새 상황에도 맞으면 우선순위 특례를 만들지 말고 그 메커니즘을 재사용한다. 특례는 규칙을 늘리고 재사용은 규칙을 줄인다 (learned 2026-07-29) <!-- cid:functional-design:c3 -->
- LLM 프롬프트에는 판단할 것뿐 아니라 판단하지 않을 것도 명시한다. 빼면 모델이 알아서 범위를 넓혀 측정 대상이 둘이 되고 지표 해석이 흐려진다 (learned 2026-07-29) <!-- cid:functional-design:c4 -->

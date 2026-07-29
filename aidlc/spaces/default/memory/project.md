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

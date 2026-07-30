<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is maintained by the orchestrator during stage execution. Add observations at the gate ritual, not by editing here directly.

## Interpretations

- 2026-07-30T15:10:00Z — Test Strategy가 Standard라 스테이지 프로즈는 `unit-test-instructions.md`와 `integration-test-instructions.md`만 요구하지만 7개 산출물을 전부 만들었다; 엔진의 `produces`가 7개를 선언하고 있어 빠지면 승인이 막힌다. 또 프로즈 자체가 "소프트 가이드라인이며 맥락이 요구하면 다른 유형을 추가해도 된다"고 적었고, 이 프로젝트에는 실제로 성능 NFR(NFR-1 판정 지연 5초/10초)과 보안 NFR(FR-1.4·NFR-6 비밀 관리)이 존재한다. 다만 두 파일의 범위는 그 NFR들에만 맞췄고 일반적인 부하·침투 시험 계획으로 부풀리지 않았다.
- 2026-07-30T15:10:00Z — 지시서를 먼저 쓰고 실행하는 프로즈 순서를 뒤집어 **실행을 먼저** 했다; 지시서에 "이 명령을 이렇게 돌리면 이런 결과가 나온다"를 실측값으로 적을 수 있고, 돌려보지 않은 명령을 지시서에 적는 것이 이 스테이지에서 가장 흔한 거짓 산출물이기 때문이다.

## Deviations

## Tradeoffs

## Open questions

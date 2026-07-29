<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is maintained by the orchestrator during stage execution. Add observations at the gate ritual, not by editing here directly.

## Interpretations

- 2026-07-29T09:50:00Z — 절단선을 8개에서 5개로 합침; component-dependency.md가 제안한 8개를 그대로 쓰면 functional-design이 단위마다 반복되어(for_each: unit-of-work) 여덟 번 돈다. 1인 6일 일정에서 그 의례 비용이 경계의 선명함으로 얻는 이득을 넘는다고 판단했다.
- 2026-07-29T09:50:00Z — judgment를 messages와 분리해 foundation 바로 위에 둠; 의존 행렬상 judgment는 config·db 외에 아무것도 의존하지 않아 채팅 UI 없이 CLI만으로 단독 검증이 가능하다. 이 프로젝트의 가장 큰 미지수(LLM이 실제로 문맥 부적합을 판별하는가)를 앱 완성 전에 확인할 수 있게 된다.

## Deviations

- 2026-07-29T09:50:00Z — delivery-planning(2.8)이 스코프에서 제외되어 경제적 Bolt 순서를 정하는 단계가 없다; 스테이지 프로세는 2.7이 순서를 정하지 말라고 명시하나, 순서를 정할 후속 단계 자체가 없으므로 DAG가 허용하는 병렬성만 기록하고 순서 선택은 엔진의 배치 계산에 맡긴다.

## Tradeoffs

- 2026-07-29T10:30:00Z — FR-5.2(안 읽은 배지)의 이중 배정을 분할이 아니라 U4 단독 소유로 해소함; 분할로 처리하면 U5의 functional-design이 자기 몫의 배지 작업을 설계하려 드는데, 실제로 배지 값은 last_read_seq(U4 컬럼)와 수신 시 갱신(U4 chatStore)에서만 나오고 U5가 만질 것이 없다.
- 2026-07-29T10:30:00Z — 커버리지 표의 항목 수를 손으로 세다 세 번 틀림(47을 46으로, U5를 19로, NFR 열거를 6개로); 세 번째에 프로그램으로 세어 한 번에 맞췄다. 셀 수 있는 것은 세는 도구로 세야 한다는 것이 이 스테이지의 실질적 교훈이다.

## Open questions

- 2026-07-29T10:30:00Z — unit-of-work.md의 U2 헤더가 FR-7.1~FR-7.5를 무자격 범위로 적어 부분 소유(FR-7.1의 절반)를 드러내지 않는다. story-map은 정확하다.

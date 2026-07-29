<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is maintained by the orchestrator during stage execution. Add observations at the gate ritual, not by editing here directly.

## Interpretations

- 2026-07-29T11:00:00Z — 단위별 질문 파일을 만들지 않고 진행함; Construction 단계는 프로토콜상 질문이 "예외적이어야" 하고, Inception에서 FR 47개가 전부 Given/When/Then을 갖춘 상태로 확정되었다. 실제 공백 세 건(force_log_id 텍스트 검증, shouldProbe 범위, FR-8.4 재시도 대응)은 전부 messaging 단위 소관이라 그 단위에서만 다룬다.
- 2026-07-29T11:00:00Z — kind 기반 산출물 가지치기로 frontend-components.md가 모든 단위에서 제외되었으나 U3·U4·U5는 실제로 화면을 포함한다; 엔진이 요구하지 않은 파일을 만드는 대신 프론트 관심사를 business-logic-model.md 안의 별도 절로 넣었다. 없는 산출물을 발명하지 않으면서 설계 내용은 잃지 않는 절충이다.

## Deviations

- 2026-07-29T12:00:00Z — 리뷰어가 잡은 FR-8.3 모순을 우선순위 규칙 특례로 풀지 않고 force_log_id 재사용으로 해결함; 판정 실패 수락 경로가 degraded 플래그로 재요청하면 BR-6.1 우선순위에 걸려 degraded로 저장되어 "시도했다"는 사실이 사라진다. force_log_id의 의미가 원래 "판정 시도가 있었고 사용자가 결정했다"이므로 실패 케이스에도 그대로 맞는다. 부적절 판정과 판정 실패가 같은 재요청 경로를 쓰게 되어 설계가 오히려 단순해졌다.

## Tradeoffs

- 2026-07-29T12:00:00Z — 판정 프롬프트에 "판단하지 않는 것" 절을 넣어 내용 기반 판정을 명시적으로 배제함; 없으면 모델이 알아서 욕설을 잡아 측정 대상이 둘로 늘고 precision 해석이 흐려진다. 같은 절에 "화제 전환만으로 부적합으로 보지 말 것"도 넣었는데, 이게 없으면 flag rate가 치솟아 팝업이 무시당하기 시작한다.
- 2026-07-29T12:00:00Z — judgment-core에 요구사항에 없는 try CLI를 설계에 넣음; 이 단위를 DAG에서 앞으로 당긴 값어치가 "채팅 앱 없이 프롬프트를 고치고 바로 돌려본다"인데, 그 도구가 없으면 앞당긴 의미가 절반 사라진다.
- 2026-07-29T12:00:00Z — 판정 실패와 부적절 판정을 둘 다 409로 응답하되 reason으로 가름; 상태 코드를 나누면(503 등) 클라이언트가 네트워크 오류와 헷갈린다. 실패한 것은 판정이지 요청이 아니다.

## Open questions

- 2026-07-29T12:00:00Z — 판정 프롬프트 문안이 초안이며 실제 대화로 검증되지 않았다. 특히 점수 구간 설명이 분포를 실제로 벌리는지 확인 필요.
- 2026-07-29T12:00:00Z — BR 번호가 형제 단위의 business-rules.md 사이에서 충돌한다(각 단위가 독립적으로 BR-6.x를 씀). 단위를 넘나들며 참조할 때 혼동 가능.
- 2026-07-29T12:00:00Z — component-methods.md의 백엔드 send_message() 산문이 옛 4중 검증/flagged_sent 전용 서술로 남아 있다. functional-design 산출물이 권위이므로 오도 위험은 낮으나 동기화 필요.

<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is maintained by the orchestrator during stage execution. Add observations at the gate ritual, not by editing here directly.

## Interpretations

- 2026-07-29T04:35:00Z — Must 등급이 8개로 많은 것을 등급 하향이 아니라 "각 Must의 깊이를 얕게"로 해소함; 이 프로젝트는 인증부터 실시간 전송까지의 사슬이 하나라도 끊기면 데모 자체가 서지 않아, 항목을 빼는 대신 친구 검색을 정확 일치만, 방 목록을 정렬 없이, 인증을 리프레시 토큰 없이 가져가는 방식으로 줄였다.
- 2026-07-29T04:35:00Z — proto-Unit 경계를 실제 Unit of Work와 동일시하지 않고 Units Generation의 입력으로만 규정함; 특히 PU-07(판정)과 PU-08(실패 처리)은 하나로 합쳐질 여지가 커서 미리 못박지 않았다.

## Deviations

- 2026-07-29T04:35:00Z — 사용자가 "Guide me"를 선택했으나 실제로는 파일을 직접 편집해 self-guided로 전환됨; 대화형 배치 제시가 거부되고 파일에 답이 채워져 있었다. 프로토콜이 스테이지 중간 모드 전환을 허용하므로 Mode 필드를 self-guided로 정정했다.
- 2026-07-29T04:35:00Z — Q4의 답변(C)을 그대로 받지 않고 후속 문항 Q8로 재질의함; 앞 단계에서 확정된 노력 배분(친구·방 축소)과 반대 방향이라 모순 검사에 걸렸다. 결과적으로 Should 등급이라는 중간 지점이 나왔다.

## Tradeoffs

- 2026-07-29T04:35:00Z — Q9(마일스톤 분할)에 대해 이틀 안에 Must 전량은 과하다는 우려를 제기했으나 사용자가 분할하지 않기로 재확인함; 결정을 그대로 따르되 위험 등록부에 가능성 High / 영향 High로 사실 기록하고 절단 순서(Should 2건 → 프로브 회복 감지)를 미리 명시했다.
- 2026-07-29T04:35:00Z — 프로브 회복 감지를 Must에서 빼지 않되 "Should 다음 절단 후보"로 백로그에 못박음; Q5=A를 존중하면서도 일정이 밀릴 때 무엇을 먼저 버릴지 논쟁 없이 정해두기 위해서다.

- 2026-07-29T05:05:00Z — 도커 컨테이너화 요청이 승인 게이트에서 들어와, 승인 대신 거부-수정 경로로 돌림; scope-document가 "배포·운영 = Won't have"인 채로 승인되면 downstream 단계 전부가 잘못된 경계를 물려받는다. 게이트에서의 신규 범위 요청은 승인 후 다음 스테이지로 넘기는 것보다 현 스테이지에서 닫는 편이 싸다.
- 2026-07-29T05:05:00Z — 컨테이너화를 위해 infrastructure-design(3.4)을 계획에 되살리지 않고 code-generation 산출물로 처리하기로 함; Dockerfile 두 개와 compose 하나는 게이트 하나를 더 지불할 만한 분량이 아니고, 6일 일정에서 게이트 추가 비용이 설계 이득보다 크다.
- 2026-07-29T05:05:00Z — 컨테이너화를 walking skeleton Bolt에 넣고 순서를 맨 앞으로 당김; 나중에 붙이면 그동안 쌓인 환경 의존이 한꺼번에 드러나고 그 시점이 대개 발표 직전이다. compose 파일은 테이블 하나·엔드포인트 하나일 때 가장 단순하다.

## Open questions

- 2026-07-29T04:35:00Z — N(문맥 메시지 개수) 값이 미정이라 콜드스타트 임계값도 미정; Application Design 또는 Functional Design에서 닫아야 한다.
- 2026-07-29T04:35:00Z — 판정 프롬프트 설계가 미정이며 PU-07의 품질을 좌우한다.
- 2026-07-29T04:35:00Z — 판정 성능 집계의 정답 라벨 기준이 intent-capture에서 이월된 채 여전히 미해결이다.
- 2026-07-29T04:35:00Z — Should 항목(PU-09·PU-10)을 실제로 잘라낼 판단 시점이 정해지지 않았다; walking skeleton Bolt 완료 시점이 자연스러운 결정 지점으로 보인다.

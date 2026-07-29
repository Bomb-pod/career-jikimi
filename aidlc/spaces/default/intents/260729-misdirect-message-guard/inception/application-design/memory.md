<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is maintained by the orchestrator during stage execution. Add observations at the gate ritual, not by editing here directly.

## Interpretations

- 2026-07-29T08:00:00Z — aws-platform 지원 관점이 이 스테이지에 기여할 것이 거의 없다고 판단함; 배포 대상이 로컬 컨테이너뿐이라 AWS 서비스 선택·Well-Architected·CDK·비용 최적화 지식이 전부 적용 대상 밖이다. 다만 infrastructure-guide의 컨테이너 오케스트레이션 체크리스트(healthcheck, graceful shutdown, non-root, stdout 로그, 멀티스테이지 빌드)는 그대로 유효해 그 부분만 설계에 반영했다.

## Deviations

- 2026-07-29T09:30:00Z — 리뷰어 지적 중 `force_log_id`의 텍스트 일치 검증과 `session_replaced` 프레임의 문서 간 동기화를 이 단계에서 고치지 않고 Functional Design으로 넘김; 리뷰 라운드를 한 번 더 도는 비용(약 8분)이 남은 일정에서 값어치를 넘어섰고, 둘 다 상태 머신 상세를 다루는 다음 단계가 자연스러운 자리다.

## Tradeoffs

- 2026-07-29T09:30:00Z — 전송 경로를 WebSocket에서 HTTP로 옮김(ADR-001); WS 위에 요청-응답을 얹으면 상관 ID·타임아웃·재시도·중복 방지를 직접 만들어야 하는데, 그 코드 어느 것도 이 프로젝트가 증명하려는 가설과 무관하다. 부작용으로 다중 탭에서 밀려난 탭이 반쪽은 살아남게 되었다.
- 2026-07-29T09:30:00Z — 미해소 판정 로그(팝업에 답하지 않고 창을 닫은 건)를 오류가 아니라 관찰값으로 처리함; "경고를 받고 아무것도 하지 않았다"는 사실이 flag rate만큼 중요한 신호라고 판단해 precision에서 제외하되 별도 집계로 남겼다.
- 2026-07-29T09:30:00Z — 지표 조회를 관리자 화면 대신 CLI로 정함(ADR-008); 판정 로그가 대화 내용의 파생물이라 HTTP로 노출하는 순간 권한 설계가 붙는데, 컨테이너에 들어갈 수 있는 사람은 이미 DB를 볼 수 있으므로 CLI에는 그 문제가 없다.

## Open questions

- 2026-07-29T09:30:00Z — `force_log_id` 재요청 시 텍스트가 원래 판정받은 것과 같은지 검증하지 않는다. UI로는 도달 불가능하나 API 직접 호출로는 판정 우회가 가능하다.
- 2026-07-29T09:30:00Z — `shouldProbe()`의 카운터 범위(방 단위인가 전역인가)가 명확하지 않다.
- 2026-07-29T09:30:00Z — FR-8.4의 "다시 시도" 동작이 어느 컴포넌트 메서드에 대응하는지 추적되지 않았다.

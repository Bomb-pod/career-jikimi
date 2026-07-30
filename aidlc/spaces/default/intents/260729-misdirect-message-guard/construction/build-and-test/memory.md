<!-- INVARIANT: examples are single-line HTML comments so a fresh template parses to total=0 (MEMORY_EMPTY). Do NOT un-comment or split across lines. t100 guards this. -->
> This file is maintained by the orchestrator during stage execution. Add observations at the gate ritual, not by editing here directly.

## Interpretations

- 2026-07-30T15:10:00Z — Test Strategy가 Standard라 스테이지 프로즈는 `unit-test-instructions.md`와 `integration-test-instructions.md`만 요구하지만 7개 산출물을 전부 만들었다; 엔진의 `produces`가 7개를 선언하고 있어 빠지면 승인이 막힌다. 또 프로즈 자체가 "소프트 가이드라인이며 맥락이 요구하면 다른 유형을 추가해도 된다"고 적었고, 이 프로젝트에는 실제로 성능 NFR(NFR-1 판정 지연)과 보안 NFR(FR-1.4·NFR-6)이 존재한다. 다만 두 파일의 범위는 그 NFR들에만 맞췄고 일반적인 부하·침투 시험 계획으로 부풀리지 않았다.
- 2026-07-30T15:10:00Z — 지시서를 먼저 쓰고 실행하는 프로즈 순서를 뒤집어 **실행을 먼저** 했다; 지시서에 "이 명령을 이렇게 돌리면 이런 결과가 나온다"를 실측값으로 적을 수 있고, 돌려보지 않은 명령을 지시서에 적는 것이 이 스테이지에서 가장 흔한 거짓 산출물이기 때문이다.

## Deviations

- 2026-07-30T16:20:00Z — 스테이지가 "빌드·테스트 실행"만 요구하는데 **코드를 두 곳 고쳤다**(`ws_registry.py`의 close 상한, `requirements.txt`의 의존성 두 개); 스테이지 프로즈의 "On failure: 진단하고 고친다"는 테스트 실패를 전제하지만, 실제로 나온 것은 테스트가 아니라 **내가 라이브 스택을 두드려 찾은 결함**과 `pip-audit`이 찾은 취약점이었다. 발견 즉시 고치지 않으면 이 워크플로에 그것을 고칠 다음 자리가 없다(`ci-pipeline`·Operation 전부 스코프 밖). 둘 다 회귀 테스트와 근거를 함께 남겼다.

## Tradeoffs

- 2026-07-30T16:00:00Z — 밀려난 WebSocket 연결의 close에 1초 상한을 걸었다; 무한정 기다리면 비협조적 탭 하나가 새 탭 접속을 10초 막고(실측), 아예 기다리지 않으면 close 프레임이 나가기 전에 소켓이 죽어 밀려난 탭이 재연결 순환에 빠질 수 있다. 정상 브라우저의 응답 시간이 0.0초라 1초는 정상 경로를 전혀 건드리지 않으면서 비정상 경로만 끊는다.
- 2026-07-30T16:30:00Z — `starlette` 8건을 고치지 않고 수용된 위험으로 기록했다; 고치려면 fastapi를 26개 마이너 버전 올려야 하고 실제로 해보니 라우트 등록 테스트 2개가 깨졌다. 로컬 전용 데모라 원격 공격자 경로가 없고 최종 발표가 나흘 앞이라, 사람이 안정성을 택했다. 되돌림은 핀 두 줄이며 원격 배포 시 첫 처리 항목으로 명시했다.
- 2026-07-30T16:30:00Z — 커버리지 수치를 게이트로 강제하지 않고 **FR의 Given/When/Then 수용 기준이 테스트로 존재하는지**를 기준으로 삼았다; `ci-pipeline`이 스코프 밖이라 강제할 자리가 없고, org.md가 "커버리지는 지침이지 목표가 아니다"로 정했다. 숫자를 채우려고 의미 없는 단언을 만드는 것이 이 단계에서 가장 쉬운 자기기만이다.

## Open questions

- 2026-07-30T16:30:00Z — 판정 경로가 **실제 OpenAI 키로 한 번도 돌지 않았다.** NFR-1의 지연 실측값이 없고, 프롬프트가 실제로 문맥 부적합을 잡는지도 미확인이다. 이 프로젝트의 가장 큰 미지수가 그대로 남아 있으며 `try` CLI가 그것을 확인하는 도구다.
- 2026-07-30T16:30:00Z — `asyncmy` PYSEC-2026-286은 최신 버전에도 있고 수정 버전이 공개되지 않았다. 대체 드라이버(aiomysql)로 옮길지, 공개를 기다릴지 정하지 않았다.

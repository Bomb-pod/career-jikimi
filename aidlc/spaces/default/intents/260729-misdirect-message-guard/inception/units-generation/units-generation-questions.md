# Units Generation — Questions

**Stage**: units-generation
**Phase**: INCEPTION
**Depth**: Standard
**Mode**: guided — 아키텍트가 근거를 붙여 제안하고 사용자가 계획 승인 게이트에서 일괄 확인

## 입력

`../application-design/`의 다섯 산출물(`components.md`, `component-methods.md`, `services.md`, `component-dependency.md`, `decisions.md`)과 `../requirements-analysis/requirements.md`.

사용자 스토리(`stories`)는 `user-stories` 단계가 스코프에서 제외되어 존재하지 않는다. 스토리 맵은 요구사항(FR) 단위로 대체한다.

---

## Q1. 단위 경계를 무엇을 기준으로 나누는가?

- A. 기능별 — auth / friends / rooms / messages / judgment. 백엔드 모듈 구조와 1:1
- B. 계층별 — DB / API / UI를 각각 단위로
- C. 배포 대상별 — 컨테이너 단위
- D. 위험 격리 — 불확실성이 큰 것을 독립 단위로 떼어냄
- X. Other (please specify)

[Answer]: A를 기본으로 하되 D를 겹쳐 적용한다 — 기능별로 나누되, judgment는 의존 관계상 독립 가능하므로 앞으로 당겨 단독 검증이 가능하게 한다

---

## Q2. 단위 크기를 어느 정도로 가져가는가?

> `functional-design`(3.1)이 **단위마다 반복**된다. 단위가 여덟 개면 설계 문서를 여덟 번 쓴다. 1인 6일 일정에서 이 비용이 크다.

- A. 굵게 — 4~5개. 의례 비용이 낮고 일정에 유리하다. 대신 한 단위 안에 여러 관심사가 섞인다
- B. 잘게 — 8개 이상. 경계가 선명하고 병렬화 여지가 크다. 1인 작업에서는 병렬화 이득이 없다
- C. 중간 — 6~7개
- X. Other (please specify)

[Answer]: A. 굵게 — 5개. `component-dependency.md`가 제안한 절단선 8개를 5개로 합친다

---

## Q3. 의존 관계에서 병렬 개발을 허용하는가?

> 1인 작업이라 실제로 동시에 짜지는 않는다. 다만 DAG에 병렬 가능성이 기록되면 "지금 막히면 저걸 먼저 할 수 있다"는 선택지가 생긴다.

- A. 허용 — 독립적인 단위는 DAG에서 형제로 두고 순서를 강제하지 않는다
- B. 엄격한 선형 순서 — 하나씩만
- X. Other (please specify)

[Answer]: A. 허용 — 특히 judgment와 auth-friends는 서로 독립이므로 형제로 둔다

---

## Q4. 단위 간 통합 지점을 무엇으로 두는가?

- A. 함수 호출 — 같은 프로세스 안이므로 모듈 경계가 곧 통합 지점
- B. 내부 API — 단위마다 HTTP 표면을 두고 서로 호출
- C. 이벤트 — 단위 간 결합을 이벤트로
- X. Other (please specify)

[Answer]: A. 함수 호출 — ADR-002가 단일 서비스로 정했으므로 단위 경계는 배포 경계가 아니라 작업 경계다

---

## Q5. 배포 모델은?

- A. 단일 배포 — 모든 단위가 하나의 컨테이너로 함께 나간다
- B. 단위별 독립 배포
- C. 혼합
- X. Other (please specify)

[Answer]: A. 단일 배포 — ADR-002, FR-9.1

# Phase Boundary Verification — Inception → Construction

**Timestamp**: 2026-07-29T10:45:00Z
**Boundary**: INCEPTION → CONSTRUCTION
**Scope**: `greenfield-local-demo` (11단계)

표준 경계는 `delivery-planning` → `functional-design`이나, `delivery-planning`(2.8)이 재구성 시 스코프에서 제외되어 실제 경계는 `units-generation` → `functional-design`이다.

## 체크 결과

| 항목 | 상태 | 근거 |
|---|---|---|
| 모든 요구사항이 설계로 추적되는가 | 통과 | `unit-of-work-story-map.md`가 FR 47 + NFR 7 전부를 단위에 배정. 미배정 0, 분할 4건 선언. 리뷰어가 산술 재검증 통과 |
| 단위가 정의되었는가 | 통과 | 단위 5개, kind·크기·소유물 명시. 기계 판독 간선 블록 비순환 확인 |
| 배포 계획이 승인되었는가 | **해당 없음 (설계상 생략)** | `delivery-planning`이 제외되어 Bolt 순서를 정하는 단계가 없다. 엔진이 DAG에서 배치를 계산한다 |

## 추적성 사슬

```
intent-statement (문제·지표)
      |
scope-document (경계·MoSCoW·위험)  ←  intent-backlog (proto-Unit 11)
      |
requirements (FR 47 · NFR 7 · CON 4 · ASM 8, 전부 Given/When/Then)
      |
application-design (컴포넌트 10 · 메서드 · 서비스 2 · 의존 행렬 · ADR 8)
      |
units-generation (Unit 5 · DAG · FR↔Unit 배정)
      |
      v
functional-design (여기부터 단위별 반복)
```

<!-- Text fallback: intent-statement가 문제와 지표를 정하고, scope-document가 경계를, requirements가 검증 가능한 요구사항을, application-design이 컴포넌트와 결정을, units-generation이 작업 단위와 DAG를 만든다. functional-design부터 단위별로 반복된다. -->

**고아 없음.** Inception의 모든 산출물이 하류에서 소비되거나 이 문서가 참조한다.

## 미충족 항목과 그 영향

- **Bolt 순서를 정하는 경제적 판단 단계가 없다.** `delivery-planning`이 제외되어, "무엇을 먼저 출시할지"를 사람이 정하는 자리가 사라졌다. 엔진이 DAG에서 계산하므로 첫 배치는 `foundation` 단독이 된다.

- **walking skeleton이 원래 의미대로 서지 않는다.** 활성 스코프가 `skeleton: on`이고 `org.md`가 scope-dependent로 위임하므로 첫 Bolt는 게이트를 받는다. 다만 그 Bolt는 `foundation` 하나이며, "종단 간 얇은 수직 슬라이스"가 아니라 바닥 층이다. 컨테이너·DB·마이그레이션이 서는지를 먼저 증명한다는 점에서 값어치는 있으나, WebSocket 동시성과 LLM 판정이라는 두 실질 위험은 U4·U2에서야 만난다.

  **완화**: `judgment-core`(U2)를 `foundation` 바로 위 형제로 배치해 두 위험 중 하나(LLM 판정)를 두 번째 배치에서 만나게 했다. 나머지 하나(WebSocket)는 U4까지 간다.

- **사용자 여정 관점의 검증이 없다.** `user-stories`와 `rough-mockups`가 모두 제외되어, 요구사항이 실제로 쓸 만한 흐름을 만드는지 확인하는 지점이 없다. FR의 Given/When/Then이 각 동작의 정확성은 담보하나 흐름 전체의 사용성은 담보하지 않는다.

- **`intent-statement`의 성공 지표가 하류에서 정정되었다.** recall이 실사용 로그로 산출 불가능하다는 사실이 `requirements.md`의 ASM-7로 기록되었고, FR-7.5가 산출 가능/불가 목록을 명시했다. 상류 문서는 승인된 상태 그대로 두었다.

## 이월되는 미해결 항목

Construction이 닫아야 할 것들이다.

| 항목 | 어디서 |
|---|---|
| `force_log_id` 재요청 시 텍스트 일치 미검증 (API 직접 호출로 판정 우회 가능) | functional-design |
| `shouldProbe()` 카운터 범위 (방 단위 vs 전역) | functional-design |
| FR-8.4 "다시 시도" 동작의 메서드 대응 | functional-design |
| 판정 프롬프트 문안 | functional-design 또는 code-generation |
| 판정 임계값 초기값 0.7의 적정성 | 리허설에서 조정 |
| Structured Outputs 지원 모델 ID 확인 | code-generation |
| `set_user_action`의 원자적 조건부 갱신 여부 | code-generation |

## 판정

**통과 (조건부).** 추적성 사슬이 끊긴 곳이 없고 고아 산출물도 없다. 생략된 단계들은 재구성 시 근거를 남기고 뺀 것이며, 그 결과(walking skeleton의 변질, 사용자 여정 검증 부재)를 위에 명시했다. 이월 항목 7건은 Construction에서 닫는다.

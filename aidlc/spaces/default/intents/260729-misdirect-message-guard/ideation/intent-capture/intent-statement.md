# Intent Statement — 문맥 기반 오발송 메시지 경고

## Problem Statement

사용자가 채팅방을 착각해 엉뚱한 방에 메시지를 보내고, 상대가 이미 읽어 되돌릴 수 없게 되는 상황이 이 프로젝트가 겨냥하는 문제다. [Q1]

해결 접근은 전송 후 회수가 아니라 **전송 전 차단**이다. 기존 대화의 문맥을 파악해, 채팅방을 착각하여 잘못 보낸 문맥에 맞지 않는 메시지를 전송 전에 경고한다. [desc]

경고의 판단 근거는 대화 문맥이며, 판정 결과가 부적절일 때 사용자에게 전송 확인 팝업을 띄우는 것이 개입 지점이다. [desc]

## Target Customer

주 대상은 **여러 채팅방을 동시에 오가는 일반 메신저 사용자**다. 방 전환이 잦을수록 보낼 곳을 헷갈릴 확률이 올라간다. [Q2]

이들이 겪는 불편은 오발송 자체보다 **되돌릴 수 없다는 점**에 있다. 상대가 이미 읽은 뒤에는 삭제도 해명도 손실을 되돌리지 못한다. [Q1]

## Success Metrics

| 지표 | 무엇을 재는가 | 우선순위 | 현재 목표치 | Source |
|---|---|---|---|---|
| 판정 precision | 경고를 띄운 건 중 실제로 부적절했던 비율 | **1순위** | 미정 — 베이스라인 측정 후 결정 | [Q3][Q11][Q4] |
| 판정 recall | 실제 부적절한 건 중 경고를 띄운 비율 | 측정하되 우선순위 아님 | 미정 — 베이스라인 측정 후 결정 | [Q3][Q11][Q4] |
| 판정 로그 축적 | 후속 데이터셋 구축·성능 테스트에 쓸 실험 데이터가 쌓이는 것 | 우선순위 미지정 | 미정 | [Q3] |

두 정확도 지표를 모두 집계하되, 임계값 조정과 성패 판단은 **precision**을 기준으로 한다. false positive가 치명적이기 때문이다 — 멀쩡한 메시지에 팝업이 계속 뜨면 기능 자체가 쓰이지 않는다. [Q11]

목표 수치는 이 단계에서 정하지 않는다. 먼저 베이스라인을 측정하고 그 값을 보고 목표를 정한다. [Q4]

*위 표의 목표치 칸이 비어 있는 이유, 그리고 두 정확도 지표를 실제로 집계하기 위해 아직 해결되지 않은 전제는 이 문서의 `## Assumptions & Open Questions`에 정리되어 있다. 이 절만 읽고 지표가 곧바로 추적 가능하다고 판단해서는 안 된다.* [Q4]

## Initiative Trigger

이 프로젝트는 **포트폴리오 / 취업 준비용 결과물**로 시작되었다. [Q5]

진행 일정은 다음과 같이 고정되어 있다. [Q8]

| 마일스톤 | 날짜 | Source |
|---|---|---|
| 착수 | 2026-07-29 | [Q8] |
| 중간 점검 | 2026-07-31 | [Q8] |
| 최종 발표 | 2026-08-04 | [Q8] |

착수부터 최종 발표까지 6일, 중간 점검까지 2일이다. [Q8] 이 일정이 범위에 압력으로 작용한다는 것은, 그 압력 아래에서 노력 배분을 판정 경로 쪽으로 몰기로 한 결정에서 드러난다. [Q12]

## Initial Scope Signal

**Workflow-selected scope** (워크플로가 선택한 스코프): `greenfield-local-demo` — workflow-selected. [scope]

**User-confirmed product boundary** (사용자가 확인한 제품 경계): 로컬에서 도는 채팅 웹앱 데모 하나가 이번 산출물의 전부다. 데이터셋 구축과 성능 테스트는 이번 범위에 포함하지 않는다. [Q9]

경계 안에서의 우선순위와 확정 사항:

| 항목 | 확정 내용 | Source |
|---|---|---|
| 노력 배분 | 판정 경로(메시지 저장·문맥 조회·판정 로그)에 시간을 몰아주고, 회원가입·친구·방 생성은 더 줄인다 | [Q12] |
| AI 검증 토글 적용 단위 | 참여자 **개인 단위**. 방 참여자 각자가 자기 전송에 대해서만 켜고 끈다 | [Q10] |
| 친구 표시 이름 | 친구 등록 시 별칭을 **반드시** 입력해야 하며, 등록 이후 언제든 수정할 수 있다 | [Q14] |

토글을 개인 단위로 두는 이유는, 이 기능이 "내가 실수하는 걸 막는" 기능이지 남을 위한 기능이 아니기 때문이다. 남이 내 전송 지연을 결정하게 두지 않는다. [Q10]

## Assumptions & Open Questions

- [assumption] 프로젝트명이 아직 정해지지 않았다.
- [assumption] 핵심 문제로 "채팅방 착각 오발송"이 선택되었으나, 욕설·비방·민감정보 등 **내용 기준 필터링**이 범위 밖이라는 확정은 없다. Scope Definition 단계에서 명시적으로 닫아야 한다.
- [assumption] precision·recall의 구체적 목표 수치가 없다. 베이스라인을 언제, 어떤 데이터로 측정할지도 정해지지 않았다.
- [assumption] 판정 성능을 집계할 때 무엇을 정답 라벨로 삼을지 확정되지 않았다. 라벨 기준이 없으면 precision을 계산할 수 없다.
- [assumption] 판정에 사용할 문맥 메시지 개수와 판정 프롬프트 설계가 정해지지 않았다.
- [assumption] 포트폴리오 목적이라는 답변과 중간 점검·최종 발표 일정, 3인 팀 구성의 조합은 교육 과정의 팀 프로젝트로 읽히나, 프로젝트의 공식 성격은 확인되지 않았다.
- [assumption] 별칭이 필수이므로 친구 목록에서 상대가 스스로 설정한 이름은 표시되지 않는다. 이것이 의도된 동작인지, 별칭과 함께 보조 표기로 노출할지는 확인되지 않았다.
- [assumption] 위 "경계 안에서의 우선순위와 확정 사항" 표의 두 항목이 서로 반대 방향으로 당긴다. 노력 배분은 친구 등록 흐름을 **줄이라**고 하는데, 친구 표시 이름 항목은 그 흐름에 필수 입력 필드와 수정 기능을 **추가**한다. 각각은 답변으로 확정되었으나 둘을 어떻게 양립시킬지는 정해지지 않았다. Scope Definition에서 조정해야 한다.
- [assumption] 6일이라는 일정 안에 앱 구현과 베이스라인 측정을 모두 끝낼 수 있는지 검증되지 않았다. 판정 경로 우선이라는 방침은 정해졌으나, 무엇을 실제로 잘라낼지는 Scope Definition의 몫이다.

## Review

**Reviewer:** aidlc-product-lead-agent

**Verdict: READY**

Third pass, re-read both artifacts and `intent-capture-questions.md` fresh (not relying on either prior pass) and specifically re-verified the item the last verdict blocked on, plus the new Q15 split.

**Assumption Confirmation count-check (both directions) — passes.** `intent-statement.md` carries 9 `[assumption]` bullets (lines 63-71); they map 1:1 onto register items 1-8 and the new item 14 (the line-70 Q12/Q14 tension bullet ↔ item 14, substance matches). `stakeholder-map.md` carries 7 `[assumption]` bullets (lines 35-41); they map 1:1 onto register items 9-13 and the new items 15-16 (line 40 ↔ item 15, line 41 ↔ item 16 — line 41 is a verbatim match). That's 16 artifact bullets against 16 register items, no orphan on either side, and `### 2차 검토 후 추가된 항목` closes with a freshly reset `[Answer]: A. Accept assumptions` covering all 16 (`intent-capture-questions.md` line 277). The regression from my last pass is resolved.

**Q15 / row-split check.** `stakeholder-map.md` lines 7-8 split the old merged "팀원 (본인 포함 3명)" row into `본인` and `팀원 2명`. Q15's answer A ("이 프로그램의 구현은 내가 전담한다. 팀원 2명은 프로젝트의 다른 산출물을 맡는다") directly entails both new role cells ("이 프로그램(채팅 웹앱)의 구현 전담" and "프로젝트의 다른 산출물 담당") verbatim in substance — tagged correctly. `[Q6]` is no longer cited on either split row, and that's correct rather than a dropped citation: the old Q6-sourced "함께 개발한다" characterization isn't asserted on either row anymore (it's superseded by the more specific, later-confirmed Q15 division of labor), so nothing is left uncited. `[Q6]` remains correctly attached where it still applies — the mentor row (line 9) and the mentor authority note (line 20).

No stranded claim: the split doesn't leave any part of the old merged row's content unsupported. The `팀원 2명` row's interest cell ("범위와 우선순위를 팀 합의로 결정하는 것") still traces to Q7, same basis as before the split, and `[Q13]`'s "3명" total is consistent with Q15's own "2명" language (redundant, not contradictory).

**Two minor, non-blocking observations for a later pass:**

- `본인` row's interest cell, "이 프로그램을 완성하는 것" (`[Q15]`) — Q15's answer confirms sole implementation *responsibility*, not explicitly a stated *interest*. It's a tight, near-tautological inference (sole owner → interest in completing it) rather than an invented one, so I'm not blocking on it — but it's the same category of role→interest leap as the `팀원` row's Q7-derived interest cell I already let through last pass. Same bar applied both times.
- Assumption/register item 16's parenthetical — "확인된 것은 함께 개발한다는 사실과 범위·우선순위를 합의로 정한다는 사실뿐이다" — is now slightly stale: Q15 confirmed additional team facts (the implementation-responsibility split) after this bullet's wording was set. The core open question it protects (팀원의 일정·품질 관심사 미확인) is still accurate and unaffected, only the "뿐이다" enumeration undersells what's since been confirmed. Cosmetic; doesn't misstate anything load-bearing.

**No regressions found** elsewhere: the five items fixed in the previous round (stakeholder role/interest grounding, the line-11 editorial sentence, the Success Metrics caveat, the "우선순위 미지정" relabel, and the `[Q12]`-attributed schedule-pressure clause) are all unchanged from what I already verified and remain sound. Decision-makers, Communication Requirements, and the other Key Stakeholders rows are untouched and consistent with their sources.

Sign-off: engineering can proceed to Scope Definition without coming back to ask questions about sourcing on these two artifacts.

### Post-review remediation (reviewer iteration budget exhausted)

리뷰어 반복 예산 2회가 소진된 뒤, 위 NOT-READY의 유일한 미해결 지적을 처리했다.
`intent-capture-questions.md`의 `## Assumption Confirmation`에 신규 가정 3건(14·15·16)을
추가하고 `[Answer]:`를 초기화한 뒤, 16건 전체에 대해 사람의 확인을 다시 받아
`A. Accept assumptions`로 기록했다. 이 문서와 `stakeholder-map.md`의 `[assumption]`
항목들은 그 확인 목록과 일치한다.

같은 턴에 후속 문항 Q15(이 프로그램의 구현 책임)가 추가·확정되어
`stakeholder-map.md`의 이해관계자 표에 반영되었다. 이 반영은 새로운 가정을
만들지 않는다 — 팀원의 일정·품질 관심사가 미확인이라는 사실은 확인 목록 16번이
이미 담고 있다.

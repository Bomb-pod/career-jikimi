# Domain Entities — messaging

`../../../inception/units-generation/unit-of-work.md`의 U5가 소유하는 엔티티다. 배정은 `../../../inception/units-generation/unit-of-work-story-map.md`, 요구사항은 `../../../inception/requirements-analysis/requirements.md`의 FR-3.3(히스토리 API)·FR-4.1~FR-4.4·FR-6.4~FR-6.6·FR-7.1(판정 안 함 상태)·FR-8.2~FR-8.6·FR-11, 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 표면은 `../../../inception/application-design/component-methods.md`, 트랜잭션 형태는 `../../../inception/application-design/services.md`가 정한다.

테이블 생성은 U1(foundation)의 초기 마이그레이션이 한다.

## `messages`

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | 클라이언트 중복 제거 키 |
| `room_id` | BIGINT | NOT NULL, FK → `rooms.id` | |
| `sender_id` | BIGINT | NOT NULL, FK → `users.id` | |
| `seq` | BIGINT | NOT NULL | **방 안에서 단조 증가** (FR-4.2) |
| `body` | TEXT | NOT NULL | |
| `verification_status` | ENUM(6값) | NOT NULL | 아래 참조 |
| `misdirect_reported_at` | DATETIME(6) | **NULL 허용** | 오발송 신고 (FR-11.3) |
| `created_at` | DATETIME(6) | NOT NULL, DEFAULT NOW(6) | **정렬 기준이 아니다** |

**인덱스**
- `UNIQUE (room_id, seq)` — 채번 중복을 DB가 최종 방어한다
- `INDEX (room_id, seq DESC)` — 히스토리 커서 페이지네이션 (FR-4.4)

### `seq`가 정렬 기준이고 `created_at`이 아닌 것

FR-4.2의 핵심이다. `created_at`은 동시 도착 시 같은 마이크로초를 가질 수 있고, 시계가 뒤로 갈 수도 있다. `seq`는 `FOR UPDATE` 잠금 아래에서 채번되므로 **방 안에서 전순서가 보장된다.**

`created_at`은 표시용이다. 정렬에 쓰지 않는다.

`UNIQUE (room_id, seq)`는 애플리케이션 버그가 있어도 중복 seq가 들어가지 않게 한다.

### `verification_status` — 6값

| 값 | 모델 호출 | 판정 로그 | 언제 |
|---|---|---|---|
| `ok` | 함 | 남김 | 성공, 점수 < 임계값 |
| `flagged_sent` | 함 | 남김 | 성공, 부적절, 사용자가 강행 |
| `failed` | **시도함** | 남김 (verdict NULL) | 에러·타임아웃. 검증 없이 전송됨 |
| `degraded` | 안 함 | 안 남김 | degraded 상태여서 건너뜀 |
| `skipped_no_context` | 안 함 | 안 남김 | 방 메시지 < `N` |
| `disabled` | 안 함 | 안 남김 | 발신자 토글 꺼짐 |

**구분 기준은 "모델 호출을 시도했는가"다.** `failed`와 `degraded`를 합치지 않는 이유가 여기 있다 — 합치면 API 실패 빈도를 셀 때 degraded 구간이 섞여 과대 집계된다 (FR-7.1).

이 단위가 정하는 것은 **호출하지 않는 세 값**(`disabled`·`skipped_no_context`·`degraded`)이고, 호출 결과에 따른 세 값(`ok`·`flagged_sent`·`failed`)은 U2의 `JudgeResult`가 결정한다.

### `misdirect_reported_at`

별도 신고 테이블을 두지 않았다 (ADR 없음 — `component-methods.md`의 `[dec]`). 발신자 본인이 자기 메시지에 한 번 신고하므로 1:1이다.

**신고 이력이 남지 않는다** — 취소하면 `NULL`로 돌아가고 언제 신고했다 취소했는지 알 수 없다. 데모 범위에서 수용한다.

## 생애주기

```
[전송 요청]
   |
   +-- 판정 부적절 + 사용자 취소 --> 저장 안 됨 (판정 로그만 남음)
   |
   +-- 그 외 --> [저장됨]
                    |
                    +-- report --> [신고됨]
                    +-- unreport --> [저장됨]
```

<!-- Text fallback: 메시지는 전송 요청에서 시작해, 부적절 판정 후 사용자가 취소하면 저장되지 않고 판정 로그만 남는다. 그 외에는 저장되며, 이후 신고와 신고 취소를 오갈 수 있다. 수정과 삭제는 없다. -->

**수정·삭제가 없다.** 요구사항에 없고, `seq` 기반 정렬과 히스토리 커서가 불변을 전제한다.

**취소된 메시지가 `messages`에 없는 것**이 이 설계의 중요한 성질이다 (FR-7.2). 그래서 집계를 `verification_status`가 아니라 판정 로그 위에 정의해야 한다 — 그러지 않으면 TP가 영원히 0이 된다.

## 관계

```
rooms (1) ----< (N) messages (N) >---- (1) users [sender]
   |                   ^
   | last_seq          | message_id (nullable)
   | (U5가 증가)       |
   v                   |
 채번            judgment_logs
```

<!-- Text fallback: messages는 rooms와 users를 참조한다. rooms의 last_seq가 seq 채번의 원천이며 U5가 증가시킨다. judgment_logs가 messages를 nullable로 참조하는데, 취소된 판정은 메시지가 없기 때문이다. -->

**`judgment_logs.message_id`가 nullable인 방향이 중요하다.** 메시지가 로그를 가리키지 않고 로그가 메시지를 가리킨다 — 메시지 없는 판정은 있어도 판정 없는 메시지는 흔하기 때문이다(`disabled` 등).

## 이 단위가 쓰는 다른 단위의 데이터

| 테이블 | 어떻게 | 소유 |
|---|---|---|
| `rooms.last_seq` | **읽고 쓴다** (`FOR UPDATE` → `+1`) | U4 (ADR-003의 예외) |
| `room_members` | 읽는다 (`get_membership()` 경유) | U4 |
| `judgment_logs` | U2의 함수를 통해서만 | U2 |
| `friendships` | `resolve_display_names()` 경유 | U3 |

**`rooms.last_seq`만 직접 쓴다.** 나머지는 소유 단위의 함수를 거친다.

## 클라이언트 측 상태 (DB 아님)

`chatStore`의 두 슬라이스가 이 단위 소관이다.

| 상태 | 저장 위치 | 수명 |
|---|---|---|
| `degraded` (bool) | **메모리만** | 탭 수명. 새로고침 시 초기화 (FR-8.3) |
| `degradedSendCount` (int) | 메모리만 | 프로브 카운터 (FR-8.5) |
| `pendingMessages` | 메모리만 | 낙관적 렌더링 중인 임시 메시지 (FR-4.3) |

**`localStorage`·`sessionStorage`에 쓰지 않는다.** FR-8.3이 새로고침 시 초기화를 요구하므로, 저장하면 요구사항 위반이다.

## Assumptions & Open Questions

- 메시지 본문 길이 상한이 없다(TEXT). 매우 긴 메시지가 판정 토큰 비용을 키우고 `judgment_logs.candidate_text`에도 그대로 들어간다. 상한을 정하는 편이 낫다.
- 신고 이력이 남지 않는다. 신고→취소→신고를 반복해도 마지막 상태만 안다.
- `seq`가 방 삭제 없이 계속 증가한다. BIGINT라 실질적 한계는 없다.
- 메시지 수정·삭제가 없어 오타를 고칠 수 없다. 요구사항에 없으므로 만들지 않는다.

# Domain Entities — judgment-core

`../../../inception/units-generation/unit-of-work.md`의 U2가 소유하는 엔티티다. 배정은 `../../../inception/units-generation/unit-of-work-story-map.md`, 요구사항은 `../../../inception/requirements-analysis/requirements.md`의 FR-6.2·FR-6.3·FR-6.7·FR-7.1~FR-7.5·FR-8.1, 컴포넌트 경계는 `../../../inception/application-design/components.md`, 메서드 표면은 `../../../inception/application-design/component-methods.md`, 배포 형태는 `../../../inception/application-design/services.md`가 정한다.

테이블 생성은 U1(foundation)의 초기 마이그레이션이 한다.

## `judgment_logs`

**모델 호출을 시도한 모든 건**의 기록이다. 호출하지 않은 건(`disabled`·`skipped_no_context`·`degraded`)은 행이 없다 (FR-7.2).

| 컬럼 | 타입 | 제약 | 비고 |
|---|---|---|---|
| `id` | BIGINT | PK, AUTO_INCREMENT | `force_log_id`로 U5가 참조 |
| `user_id` | BIGINT | NOT NULL, FK → `users.id` | 로그 소유자. `force_log_id` 소유권 검증에 쓰인다 |
| `room_id` | BIGINT | NOT NULL, FK → `rooms.id` | 방 일치 검증에 쓰인다 |
| `message_id` | BIGINT | **NULL 허용**, FK → `messages.id` | 취소된 건은 메시지가 없다 |
| `context_from_seq` | BIGINT | NOT NULL | 실제로 모델에 넣은 문맥의 시작 |
| `context_to_seq` | BIGINT | NOT NULL | 끝 |
| `candidate_text` | TEXT | NOT NULL | 판정 대상 문장 |
| `score` | DECIMAL(4,3) | **NULL 허용** | 0.000~1.000. 호출 실패면 NULL |
| `verdict` | ENUM('appropriate','inappropriate') | **NULL 허용** | 호출 실패면 NULL |
| `threshold` | DECIMAL(4,3) | NOT NULL | 판정 당시의 임계값 |
| `latency_ms` | INT | NOT NULL | 실패해도 기록한다 |
| `prompt_tokens` | INT | NULL 허용 | 실패면 NULL |
| `completion_tokens` | INT | NULL 허용 | 실패면 NULL |
| `user_action` | ENUM('auto_sent','sent','cancelled') | **NULL 허용** | 미해소 로그는 NULL |
| `created_at` | DATETIME(6) | NOT NULL, DEFAULT NOW(6) | |

**인덱스**
- `INDEX (user_id, room_id, id)` — `force_log_id` 검증 조회를 커버
- `INDEX (created_at)` — 지표 집계의 기간 필터
- `INDEX (verdict)` — 집계가 `verdict IS NOT NULL`로 거르므로

**`candidate_text`를 저장하는 이유** — U5가 `force_log_id`로 재요청할 때 텍스트가 원래 판정받은 것과 같은지 검증해야 하는데(`application-design`에서 이월된 미해결 항목), 그러려면 원문이 남아 있어야 한다. `business-rules.md` BR-6.9가 이 검증을 정의한다.

**`threshold`를 저장하는 이유** — 임계값은 환경변수라 언제든 바뀐다. 나중에 로그를 볼 때 "이 판정은 어떤 기준으로 내려졌나"를 알 수 없으면 재현이 불가능하다. 점수만 남기고 기준을 안 남기면 데이터가 반쪽이 된다.

### `score`와 `verdict`가 둘 다 NULL일 수 있는 것

**호출 실패를 표현하는 방식이다** (FR-8.1). 실패해도 행은 남는다 — API가 얼마나 자주 실패했는지 세려면 실패한 시도도 기록되어야 하기 때문이다.

집계는 `verdict IS NOT NULL`로 거르므로(FR-7.4) 실패 건이 precision을 오염시키지 않는다. 동시에 API 실패율은 전체 행 대비 `verdict IS NULL` 비율로 나온다.

### `user_action`의 세 값과 NULL

| 값 | 언제 |
|---|---|
| `auto_sent` | 적절 판정 → 묻지 않고 전송 |
| `sent` | 부적절 판정 → 사용자가 "보내기" |
| `cancelled` | 부적절 판정 → 사용자가 "취소" |
| **NULL** | 팝업이 떴는데 사용자가 답하지 않고 이탈 |

NULL은 **오류가 아니라 관찰값이다.** "경고를 받고 아무것도 하지 않았다"는 사실이 데이터다. precision 계산에서는 빼되 "미응답 건수"로 따로 센다 (`business-rules.md` BR-7.4).

## 생애주기

```
[호출 시작]
    |
    v
[행 생성] score/verdict/user_action 미정
    |
    +-- 호출 성공 --> score, verdict 기록
    |     |
    |     +-- 적절 ------> user_action = auto_sent, message_id 연결   [종결]
    |     |
    |     +-- 부적절 ----> user_action 미정 (팝업 대기)
    |            |
    |            +-- "보내기" --> user_action = sent, message_id 연결 [종결]
    |            +-- "취소"  --> user_action = cancelled              [종결]
    |            +-- 이탈    --> user_action = NULL 유지              [미해소]
    |
    +-- 호출 실패 --> score/verdict NULL 유지
          |
          +-- 사용자 수락 --> message_id 연결                         [종결]
          +-- 사용자 거절 --> message_id NULL 유지                    [종결]
```

<!-- Text fallback: 호출 시작과 함께 행이 생성되고, 성공하면 score와 verdict가 기록된다. 적절 판정은 auto_sent로 즉시 종결되고 메시지에 연결된다. 부적절 판정은 사용자 응답을 기다리며, 보내기면 sent, 취소면 cancelled로 종결되고, 응답 없이 이탈하면 user_action이 NULL인 미해소 상태로 남는다. 호출 실패는 score와 verdict가 NULL인 채로, 사용자가 수락하면 메시지에 연결되고 거절하면 연결되지 않는다. -->

**`user_action`은 한 번만 쓰인다.** 이미 값이 있으면 덮어쓰지 않고 예외를 던진다 — 이것이 `force_log_id`의 1회성을 실제로 보장하는 장치다 (BR-6.8).

## 다른 단위와의 접점

| 대상 | 무엇을 |
|---|---|
| U5 messaging | `judge()` → `JudgeResult`, `get_log_for_force()`, `set_user_action()`, `link_message()` |
| U1 foundation | `settings`(API 키·임계값·문맥 개수·타임아웃), `get_session()` |

**이 단위는 `users`·`rooms`·`messages`를 읽지 않는다.** FK로 참조만 하며 조인하지 않는다. 문맥 메시지는 U5가 조회해 인자로 넘긴다 — 그래서 이 단위가 채팅 앱 없이도 돈다.

## Assumptions & Open Questions

- `DECIMAL(4,3)`은 0.000~1.000을 표현한다. 모델이 소수점 넷째 자리를 주면 잘린다. 임계값 비교에 영향이 없는 수준이다.
- `judgment_logs.user_id`의 FK가 U3의 `users`를 가리키므로 스키마 수준의 의존이 생긴다. 단위 간 코드 의존은 없으나 마이그레이션 순서에는 영향을 준다 — U1이 전체 스키마를 한 번에 만들므로 실제 문제는 없다.
- `candidate_text`가 TEXT라 길이 상한이 없다. 메시지 길이 제한이 요구사항에 없어서인데, 매우 긴 입력이 토큰 비용을 키운다. U5의 메시지 길이 제한과 함께 정해야 한다.
- 로그 보존 기간이 정해지지 않았다. 데모 범위에서 문제되지 않는다.

# Units of Work — career-jikimi

`../application-design/components.md`가 정의한 컴포넌트와 `../application-design/component-dependency.md`의 의존 그래프를 **작업 단위**로 묶은 것이다. `../application-design/component-methods.md`가 각 단위가 구현할 메서드 표면을, `../application-design/services.md`가 배포 형태를, `../application-design/decisions.md`가 구조적 제약을 준다. 기능 범위는 `../requirements-analysis/requirements.md`의 FR 번호로 추적한다.

사용자 스토리(`stories`)는 `user-stories` 단계가 스코프에서 제외되어 존재하지 않는다. 단위-스토리 대응은 FR 단위로 대체하며 `unit-of-work-story-map.md`가 그것을 담는다.

## 분해 기준

기능별 경계(백엔드 모듈 구조와 1:1)를 기본으로 하되, **의존 관계상 독립 가능한 것은 앞으로 당겼다.**

`component-dependency.md`는 절단선 8개를 제안했으나 5개로 합쳤다. `functional-design`(3.1)이 단위마다 반복되므로 단위 수가 곧 설계 문서 반복 횟수이며, 1인 6일 일정에서 그 비용이 경계의 선명함으로 얻는 이득을 넘는다고 판단했다.

## 단위 목록

### U1 · foundation

| 항목 | 값 |
|---|---|
| kind | `packaging` |
| 크기 | M |
| 배포 | 단일 배포의 기반 |
| 대응 FR | FR-9.1~FR-9.5, FR-1.4(비밀 주입 경로) |

컨테이너와 데이터가 서는 층이다. 나머지 전부가 이 위에서 돈다.

**소유하는 것**
- `Dockerfile`(멀티스테이지, 비루트, 헬스체크), `docker-compose.yml`(app + db), `.env.example`
- `core/config` — 환경변수를 타입 붙은 설정으로
- `core/db` — SQLAlchemy async 엔진, 세션 의존성
- Alembic 설정(async `env.py` 포함)과 **전체 스키마의 초기 마이그레이션**
- `GET /health`

**스키마 전체를 여기서 만드는 이유** — 테이블을 단위마다 나눠 만들면 마이그레이션 순서가 단위 순서에 묶여 병렬 작업이 막힌다. 스키마는 한 번에 세우고, 각 단위는 자기 테이블을 쓰기만 한다.

**구현 메모**
- MariaDB 문자셋을 `utf8mb4`로 **명시**한다. 기본값에 기대면 한글·이모지가 깨진다 (FR-9.3)
- `depends_on: condition: service_healthy` + 앱 시작 시 DB 연결 재시도 (FR-9.2)
- uvicorn 워커 1개 고정 (FR-9.4, CON-1)
- `alembic upgrade head`가 uvicorn보다 먼저 돈다

### U2 · judgment-core

| 항목 | 값 |
|---|---|
| kind | `service` |
| 크기 | L |
| 배포 | U1의 컨테이너에 함께 |
| 대응 FR | FR-6.2, FR-6.3, FR-6.7, FR-7.1~FR-7.5, FR-8.1 |

**이 프로젝트가 증명하려는 것이 여기 있다.**

**소유하는 것**
- `judgment` 모듈 전체 — 프롬프트 구성, Structured Outputs 스키마, 점수→판정 변환, 타임아웃·재시도
- `judgment_logs` 테이블에 대한 읽기·쓰기
- `compute_metrics()`와 지표 CLI (ADR-008)

**UI가 없다. 메시지도, 방도, 사용자도 없다.** `judge(user_id, room_id, context, candidate_text)`를 CLI나 테스트에서 직접 부를 수 있다.

**이 단위를 앞으로 당긴 이유** — 의존 행렬상 `judgment`는 `config`·`db` 외에 아무것도 의존하지 않는다. 그래서 채팅 앱이 완성되기 전에 **문맥과 후보 문장을 손으로 넣어 판정 품질을 확인할 수 있다.** 이 프로젝트의 가장 큰 미지수가 "LLM이 정말 문맥 부적합을 판별하는가"인데, 그걸 마지막에 확인하면 안 된다는 걸 알았을 때 남은 시간이 없다.

**구현 메모**
- `strict: true` Structured Outputs. 지원 모델 ID를 먼저 확인한다 (ADR-005)
- 판정 입력에 참여자 이름·아이디·별칭을 넣지 않는다 (FR-6.2)
- 실패는 예외가 아니라 `JudgeResult.Failed`다 (FR-8.1)
- `recall`은 수치가 아니라 `"산출 불가 — 라벨 데이터셋 필요"` 문자열로 보고한다 (FR-7.5)
- 미해소 로그(`user_action IS NULL`)는 precision에서 제외하되 "미응답 건수"로 따로 센다

### U3 · auth-friends

| 항목 | 값 |
|---|---|
| kind | `service` |
| 크기 | M |
| 배포 | U1의 컨테이너에 함께 |
| 대응 FR | FR-1.1~FR-1.3, FR-2.1~FR-2.4 |

> FR-1.4(비밀을 환경변수로만)는 U1이 소유한다. 이 단위는 U1이 만든 설정 경로를 쓰기만 한다.

`scope-document.md`가 "껍데기"로 분류한 영역이다. 최소한으로 만든다.

**소유하는 것**
- `auth` 모듈 — 회원가입·로그인·해싱·JWT·`verify_token()`
- `friends` 모듈 — 정확 일치 검색·즉시 등록·별칭 필수·별칭 수정·`resolve_display_names()`
- `AuthView`, `FriendsView`

**구현 메모**
- `verify_token()`은 HTTP 의존성과 분리된 순수 함수로 노출한다 — U4의 WebSocket 인증이 쓴다 (FR-1.3)
- 별칭은 NOT NULL. 빈 값 등록·수정은 400 (FR-2.2, FR-2.3)
- 부분 일치 검색·목록 정렬·승인 절차를 만들지 않는다 (FR-2.1)
- 리프레시 토큰을 만들지 않는다 (FR-1.2)

### U4 · rooms-realtime

| 항목 | 값 |
|---|---|
| kind | `service` |
| 크기 | L |
| 배포 | U1의 컨테이너에 함께 |
| 대응 FR | FR-3.1~FR-3.3, FR-5.1~FR-5.4, FR-6.1, FR-10(Should) |

방과 실시간 연결. **WebSocket 동시성이라는 두 번째 미지수가 여기 있다.**

**소유하는 것**
- `rooms` 모듈 — 생성·목록·상세·읽음 처리·AI 토글
- `core/ws_registry` — 연결 등록·해제·푸시, 다중 탭 교체 처리
- WebSocket 엔드포인트와 첫 프레임 인증
- `RoomListView`, `wsClient`, `chatStore`의 rooms·unread·toasts 슬라이스, `ToastHost`

**구현 메모**
- 사용자당 연결 1개. 두 번째 탭이 붙으면 첫 탭에 `session_replaced` 프레임을 보내고 닫는다
- 밀려난 탭은 재연결하지 않고 배너를 띄운다
- `last_read_seq`는 **전진만** 한다. 뒤로 가는 갱신은 무시 (FR-5.2)
- AI 토글은 **호출자 본인의** `room_members` 행만 바꾼다 (FR-6.1)
- 브로드캐스트 시 연결 없는 사용자는 조용히 건너뛴다 — 오류가 아니다

### U5 · messaging

| 항목 | 값 |
|---|---|
| kind | `service` |
| 크기 | XL |
| 배포 | U1의 컨테이너에 함께 |
| 대응 FR | FR-3.3(히스토리 API 몫), FR-4.1~FR-4.4, FR-6.4~FR-6.6, FR-8.2~FR-8.6, FR-11.1~FR-11.3, NFR-2, NFR-3, NFR-5, NFR-7(일부) |

> **FR-5.2(안 읽은 배지)는 U4가 온전히 소유한다.** 배지 값은 `last_read_seq`와 수신 시 갱신에서 나오며 둘 다 U4의 것이다. 이 단위는 메시지를 저장·브로드캐스트할 뿐 배지를 만지지 않는다.

전송 경로 전체. 앞의 모든 단위가 여기서 만난다.

**소유하는 것**
- `messages` 모듈 — 전송 오케스트레이션, seq 채번, 히스토리, 신고
- 판정 통합 — `judgment.judge()` 호출, 409 흐름, `force_log_id` 검증
- 실패 처리 — degraded 전환·프로브·미검증 배지
- `ChatView`, `JudgeConfirmDialog`, `DegradedDialog`, 프라이버시 고지

**XL인데 나누지 않은 이유** — 전송·순서·판정 통합·실패 처리가 **한 요청 경로 안에서 얽혀 있다.** `send_message()` 하나가 그 전부를 오케스트레이션하므로, 나누면 같은 함수를 두 단위가 나눠 갖게 되어 경계가 오히려 흐려진다.

**구현 메모**
- LLM 호출은 트랜잭션 **밖**, 브로드캐스트는 커밋 **뒤** (FR-4.1)
- `SELECT last_seq FOR UPDATE` → `+1` → INSERT를 한 트랜잭션에 (FR-4.2)
- `force_log_id`는 소유자·방·미소진 검증 후에만 통과. `set_user_action`이 원자적 조건부 갱신이어야 1회성이 실제로 보장된다
- **미해결 항목**: 재요청 텍스트가 원래 판정받은 텍스트와 같은지 검증하지 않는다. `functional-design`에서 닫는다
- degraded 플래그와 프로브 카운터는 클라이언트가 보낸다 (ADR-007)
- 낙관적 렌더링된 자기 메시지가 브로드캐스트로 돌아오므로 ID로 중복 제거 (FR-4.3)

## 크기 합계

| 크기 | 개수 | 단위 |
|---|---|---|
| M | 2 | U1, U3 |
| L | 2 | U2, U4 |
| XL | 1 | U5 |

**U5가 가장 크고 가장 늦다.** 일정이 밀리면 여기가 압박을 받는다. `scope-document.md`가 정한 절단 순서(FR-10 → FR-8.5 프로브 → FR-11 신고)는 모두 U4·U5 안에 있으므로, 잘라내도 단위 구조는 그대로 유지된다.

## Assumptions & Open Questions

- `delivery-planning`(2.8)이 스코프에서 제외되어 경제적 Bolt 순서를 정하는 단계가 없다. 엔진이 DAG에서 배치를 계산하며, 결과적으로 첫 Bolt는 `foundation` 단독이 된다.
- 스키마 전체를 U1에서 만들기로 했으므로, 뒤 단위에서 컬럼이 필요해지면 추가 마이그레이션을 만든다. Alembic이 있으니 비용은 작다.
- U5의 `force_log_id` 텍스트 일치 검증이 미해결 상태로 넘어간다.
- 각 단위의 프론트엔드 몫이 백엔드와 같은 단위에 묶여 있다. 1인 작업이라 문제되지 않으나, 여러 명이면 나누는 편이 낫다.

## Review

**Reviewer:** aidlc-architecture-reviewer-agent

**Verdict: READY**

Short check as scoped — no re-derivation of the DAG or unit boundaries. All three requested checks pass, and I ran a full arithmetic reconciliation on top to make sure nothing else regressed.

### The three requested checks

1. **U5's table now counts 21.** Counted the rows directly (lines 76–96 of the current file): 17 FR rows (including `FR-3.3` and the new `FR-7.1`) + 4 NFR rows = 21. Matches the coverage table's "U5 | 21" and the Assumptions line.
2. **`FR-7.1` appears exactly where the split table says it should.** The "여러 단위에 걸치는 항목" table declares "U2가 판정 결과 상태 3값, U5가 판정 안 함 상태 3값." U2's table carries `FR-7.1 | verification_status 6값 정의 (판정이 결정하는 부분)`; U5's table now carries `FR-7.1 | 판정을 안 하는 경우의 상태 3값 — disabled·skipped_no_context·degraded (판정 결과 3값은 U2)`. Both present, phrasing mirrors each other and cross-references correctly — same pattern as the `FR-3.3` precedent it was modeled on.
3. **The NFR row now enumerates all seven.** "U1 (NFR-6), U2 (NFR-1), U4 (NFR-4, NFR-7 일부), U5 (NFR-2·3·5, NFR-7 일부)" — unique set is {1,2,3,4,5,6,7}, all seven present, with NFR-7 correctly appearing under both halves of its split.

### Full reconciliation (beyond what was asked, to close this out cleanly)

I re-summed both directions to make sure the fix didn't shift an error elsewhere:
- **FR union**: U1(6) + U2(9) + U3(7) + U4(11) + U5(17) = 50 raw appearances = 47 unique FR IDs + 3 doubled declared splits (`FR-1.3`, `FR-3.3`, `FR-7.1`). Exact match.
- **NFR union**: U1(1) + U2(1) + U3(0) + U4(2) + U5(4) = 8 raw appearances = 7 unique NFR IDs + 1 doubled declared split (`NFR-7`). Exact match.
- **Total rows**: 7+10+7+13+21 = 58, which is exactly 54 unique items (47 FR + 7 NFR) + 4 split-doublings (`FR-1.3`, `FR-3.3`, `FR-7.1`, `NFR-7`). This is the number I flagged as the target in the prior round if the fix were complete — it now lands exactly there.

Everything in `unit-of-work-story-map.md`'s coverage section is now internally consistent and matches `requirements.md`'s actual FR/NFR count.

### One thing still off — plainly stated, not blocking

`unit-of-work.md`'s own U2 header (line 48) still reads "FR-6.2, FR-6.3, FR-6.7, **FR-7.1~FR-7.5**, FR-8.1" — an unqualified range that implies U2 owns all of FR-7.1, same shape as the FR-1.4-under-U3 overclaim fixed two rounds ago, just not caught for this one. U5's header already sets the right precedent (`FR-3.3(히스토리 API 몫)`); U2's would ideally read `FR-7.1(일부)~FR-7.5` for symmetry. This is a docs-only nicety — the story-map (the artifact that actually carries the split's substance) is correct and unambiguous, and nothing here could cause a developer to build the wrong thing or duplicate work. Recording it as requested rather than spending another round on it.

The dependency DAG, unit boundaries, and all five original findings are confirmed closed. This is ready for Construction.

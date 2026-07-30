# Integration Test Instructions — career-jikimi

경계를 넘는 검증이다. 단위 안의 검증은 `unit-test-instructions.md`가, 각 단위가 무엇을 소유하는지는 `../<unit>/code-generation/code-summary.md`가 담는다.

Test Strategy **Standard** — 핵심 경계와 단위 간 상호작용을 덮되 E2E는 최소로 둔다.

## 세 층위

| 층위 | 무엇을 넘는가 | 어디서 | 실행 |
|---|---|---|---|
| ① API 통합 | 라우터 → 서비스 → **실제 MariaDB** | `backend/tests/test_*_api.py`, `test_send_message.py`, `test_history.py`, `test_report.py` | `pytest` |
| ② 단위 간 계약 | U5 → U2·U3·U4의 함수 | `test_send_message.py`, `test_force_send.py`, `test_display_names.py` | `pytest` |
| ③ 라이브 스택 | 브라우저 → 컨테이너 → DB | 아래 § 스모크 | 수동 스크립트 |

①과 ②는 `pytest`에 이미 포함된다. ③은 컨테이너를 실제로 띄워야 하므로 별도다.

## ① API 통합 — 실제 DB

`api_client` 픽스처가 `httpx.AsyncClient` + `ASGITransport`로 앱을 **테스트와 같은 이벤트 루프**에서 부른다. `TestClient`를 쓰지 않는 이유는 그것이 앱을 별도 스레드의 별도 루프에서 돌려, 루프에 묶인 asyncmy 커넥션 공유가 즉시 깨지기 때문이다.

격리는 외부 트랜잭션 + `join_transaction_mode="create_savepoint"`다. 테스트 안의 `commit()`은 savepoint 해제가 되고 끝나면 전체가 롤백된다.

**이 격리의 한계** — 진짜 동시 요청은 재현되지 않는다(단일 커넥션). 그래서 동시성이 걸린 곳은 `live_sessionmaker`로 별도 커넥션 + 실제 커밋을 쓴다.

## ② 단위 간 계약 — U5가 나머지를 부른다

`send_message()` 하나가 네 단위를 오케스트레이션한다. 계약이 깨지면 여기서 잡힌다.

| 호출 | 제공 | 검증하는 테스트 |
|---|---|---|
| `rooms.get_membership()` | U4 | 비참여자 403, `ai_check_enabled`로 상태 결정 |
| `judgment.judge()` | U2 | 판정 4갈래, **트랜잭션 밖 호출**, `ContextMessage(sender_id, text, seq)` 구성 |
| `judgment.get_log_for_force()` | U2 | `verdict` 파생 — `inappropriate`→`flagged_sent`, `NULL`→`failed` |
| `judgment.set_user_action()` / `link_message()` | U2 | `AlreadyResolved`가 메시지까지 롤백 |
| `rooms.member_user_ids()` + `ws_registry.push_to_users()` | U4 | **커밋 뒤** 브로드캐스트 |
| `friends.resolve_display_names()` | U3 | 히스토리 발신자 표시명, **N+1 없음** |

**U3의 `resolve_display_names`에는 쿼리 횟수 회귀 테스트가 붙어 있다.** U4·U5가 참여자 목록 경로에서 N+1을 만들면 그 테스트가 붉어진다 — 단위를 넘는 성능 계약을 테스트가 지키는 구조다.

## ③ 라이브 스택 스모크

컨테이너가 실제로 뜬 상태에서 종단 흐름을 확인한다. **`pytest`가 덮지 못하는 것** — Dockerfile의 3스테이지 빌드, 기동 순서, SPA 폴백보다 앞선 라우터 등록, 실제 WebSocket 프레이밍이 여기서만 검증된다.

```bash
docker compose up -d --build
curl http://localhost:8000/health          # {"status":"ok","db":"ok"}
```

### HTTP 흐름 (29항목)

`build-test-results.md` § 라이브 스모크에 실행 결과가 있다. 덮는 것:

```
회원가입 → 중복 409 → 짧은 비밀번호 400 → 로그인 실패 401 → 토큰 없이 401
  → 정확 일치 검색 → 부분 일치 빈 결과 200 → 공백 별칭 400 → 친구 등록
  → 단방향 확인 → 별칭만 표시(display_name 없음)
  → 빈 초대 400 → 친구 선택 방 생성 → 방 목록 → AI 토글 기본 켜짐
  → 메시지 전송 → 콜드스타트 skipped_no_context → seq=1 → 2001자 400
  → 히스토리 → 한글·이모지 왕복
  → 남의 메시지 신고 403 → 본인 신고 → 없는 메시지 403 → 신고 취소
  → 방 상세 → 없는 방 403
```

### WebSocket 흐름

raw 소켓으로 확인한다(브라우저 없이). **프레임 길이가 126바이트를 넘으면 확장 길이 필드가 필요하다** — JWT를 실은 auth 프레임이 정확히 그 경우이고, 빠뜨리면 서버가 `expected_auth_frame`으로 올바르게 거부한다.

| 확인 | 기대 |
|---|---|
| 핸드셰이크 | `101 Switching Protocols` |
| 유효 토큰 | `{"type":"auth_ok"}` |
| 잘못된 토큰 | `{"type":"auth_error","reason":"invalid_token"}` |
| 인증 전 다른 프레임 | `{"type":"auth_error","reason":"expected_auth_frame"}` |
| 두 번째 연결 | 새 연결 `auth_ok` + **첫 연결에 `session_replaced`** |
| **비협조적 밀려난 탭** | 새 연결이 **1초 안에** `auth_ok` (수정 전 10초) |

마지막 항목이 이 스테이지에서 찾은 결함이다 — § 아래.

### 판정 지표 CLI (ADR-008)

```bash
docker compose exec app python -m app.judgment.report
```

확인할 것: `recall`이 **수치가 아니라** `산출 불가 — 라벨 데이터셋 필요`, precision 옆에 **`※ 근사 — ASM-1 참조`**, 부적절 판정이 없으면 `산출 불가 — 부적절 판정 건이 없음`(0.0이 아니다).

## 라이브에서만 잡힌 결함

**`register()`의 `await existing.close()`가 close 핸드셰이크 완료를 기다렸다.**

| 밀려난 탭 | 새 탭의 `auth_ok`까지 |
|---|---|
| 응답함 (정상 브라우저) | 0.0초 |
| 응답 안 함 (멈춘 탭·끊긴 네트워크) | **10.0초** |

레지스트리는 이미 새 소켓으로 교체됐고 `session_replaced`도 전달된 뒤라 기다릴 이유가 없었다. 1초 상한을 걸어 **1.00초**로 확인했고, `test_ws_registry.py`에 회귀 테스트를 붙였다.

**단위 테스트가 이것을 못 잡은 이유** — 가짜 소켓의 `close()`가 즉시 반환한다. 실패 모드가 실제 전송 계층에만 있었다. 이것이 ③ 층위를 두는 값어치다.

## 요구사항 → 검증 위치

| FR/NFR | 층위 | 어디 |
|---|---|---|
| FR-1.1·1.2 인증 | ①③ | `test_auth_api.py`, 스모크 |
| FR-1.3 WS 첫 프레임 | ①③ | `test_ws_auth.py`, WS 스모크 |
| FR-1.4·NFR-6 비밀 | ① | `test_config.py`, 리터럴 스캔 |
| FR-2.1~2.4 친구 | ①③ | `test_friends_api.py`, 스모크 |
| FR-3.1~3.3 방·히스토리 | ①③ | `test_rooms_api.py`, `test_history.py`, 스모크 |
| FR-4.1 저장 후 브로드캐스트 | ② | `test_send_message.py` |
| FR-4.2 seq 채번 | ② | `test_seq_allocation.py` (**진짜 동시**) |
| FR-4.3 낙관적 렌더링 | 프론트 | `ChatView.test.tsx` |
| FR-4.4 커서 | ①③ | `test_history.py`, 스모크 |
| FR-5.1 연결 1개 | ①③ | `test_ws_registry.py`, WS 스모크 |
| FR-5.2·5.3 배지·토스트 | ①프론트 | `test_rooms_unread.py`, `chatStore.test.ts` |
| FR-6.1 개인별 토글 | ①③ | `test_ai_toggle.py`, 스모크 |
| FR-6.2·6.3·6.7 판정 입력·출력 | ① | `test_anonymize.py`, `test_prompt.py`, `test_judge.py` |
| FR-6.4 콜드스타트 | ①③ | `test_send_message.py`, 스모크 |
| FR-6.5·6.6 대기 UI·팝업 | 프론트 | `ChatView.test.tsx` |
| FR-7.1~7.5 로그·지표 | ①③ | `test_metrics.py`, report CLI |
| FR-8.1 타임아웃·재시도 | ① | `test_client.py` |
| FR-8.2~8.6 실패 처리 | ②프론트 | `test_force_send.py`, `degradedFlow.test.tsx` |
| FR-9.1~9.5 컨테이너 | ③ | 스모크 |
| FR-11 신고 | ①③ | `test_report.py`, 스모크 |
| NFR-3 데이터 무결성 | ② | `test_send_message.py` (커밋 뒤 브로드캐스트) |
| NFR-5 프라이버시 고지 | 프론트 | `ChatView.test.tsx` |
| **NFR-1 판정 지연** | — | **미검증.** `performance-test-instructions.md` 참조 |
| **FR-10 참여자 관리** | — | **절단됨.** 구현 없음 |

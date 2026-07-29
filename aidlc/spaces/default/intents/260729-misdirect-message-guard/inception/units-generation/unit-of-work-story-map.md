# Unit ↔ Requirement Map — career-jikimi

`unit-of-work.md`의 다섯 단위에 `../requirements-analysis/requirements.md`의 요구사항을 배정한 것이다. 배정 근거는 `../application-design/components.md`의 컴포넌트 소유권과 `../application-design/component-methods.md`의 메서드 표면이며, 단위 간 순서 제약은 `unit-of-work-dependency.md`가, 구조적 제약은 `../application-design/decisions.md`가, 배포 형태는 `../application-design/services.md`가, 컴포넌트 간 호출 관계는 `../application-design/component-dependency.md`가 정한다.

**사용자 스토리 대신 FR을 쓴다.** `user-stories`(2.4) 단계가 스코프에서 제외되어 스토리 산출물이 없다. 요구사항이 이미 Given/When/Then 수용 기준을 갖고 있어 스토리의 역할을 대신한다.

## 배정

### U1 · foundation

| FR | 내용 |
|---|---|
| FR-9.1 | `docker compose up` 한 번으로 기동 |
| FR-9.2 | DB healthy 후 앱 기동 + 연결 재시도 |
| FR-9.3 | MariaDB `utf8mb4` |
| FR-9.4 | 단일 uvicorn 워커 |
| FR-9.5 | 개발 Vite / 배포 FastAPI 정적 서빙 |
| FR-1.4 | 비밀을 환경변수로만 주입 (설정 경로 소유) |
| NFR-6 | 비밀 관리 |

**전체 스키마의 초기 마이그레이션**도 여기 속한다. 특정 FR에 대응하지 않지만 나머지 모든 단위의 전제다.

### U2 · judgment-core

| FR | 내용 |
|---|---|
| FR-6.2 | 최근 `N`개 문맥 + 후보. 참여자 정보 제외 |
| FR-6.3 | 모델은 점수만, 서버가 임계값으로 판정 |
| FR-6.7 | 판정 대상은 문맥 적합성뿐 |
| FR-7.1 | `verification_status` 6값 정의 (판정이 결정하는 부분) |
| FR-7.2 | 판정 로그 적재, `user_action` 세 값 |
| FR-7.3 | `user_action`을 라벨로 |
| FR-7.4 | 집계는 판정 로그의 `verdict IS NOT NULL` 행 |
| FR-7.5 | 산출 가능 지표 목록, `recall`은 산출 불가 표기 |
| FR-8.1 | 타임아웃 + 재시도 1회 |
| NFR-1 | 판정 지연 5초 / 최악 10초 (호출 측 보장) |

**FR-7.1은 U2와 U5가 나눠 갖는다.** 여섯 값의 정의와 판정 결과에 따른 값(`ok`, `flagged_sent`, `failed`)은 U2가, 판정을 안 하는 경우의 값(`disabled`, `skipped_no_context`, `degraded`)은 U5가 정한다.

### U3 · auth-friends

| FR | 내용 |
|---|---|
| FR-1.1 | 회원가입, 해싱, 8자 최소 |
| FR-1.2 | 로그인, JWT |
| FR-1.3 | `verify_token()` 제공 (WS 인증은 U4가 소비) |
| FR-2.1 | 아이디 정확 일치 검색 |
| FR-2.2 | 단방향 즉시 등록, 별칭 필수 |
| FR-2.3 | 별칭 수정 |
| FR-2.4 | 별칭만 표시 (`resolve_display_names()` 제공) |

### U4 · rooms-realtime

| FR | 내용 |
|---|---|
| FR-1.3 | WebSocket 첫 프레임 인증 (U3의 `verify_token()` 소비) |
| FR-3.1 | 방 생성, 최소 2명 |
| FR-3.2 | 방 목록 |
| FR-3.3 | 구독 먼저·중복 제거 (히스토리 API는 U5) |
| FR-5.1 | 사용자당 WS 연결 1개, `room_id` 멀티플렉싱 |
| FR-5.2 | 안 읽은 개수 배지, `last_read_seq` |
| FR-5.3 | 앱 내 토스트 |
| FR-5.4 | 앱이 열린 동안만 |
| FR-6.1 | 개인별 AI 검증 토글 |
| NFR-7 | 테스트 — 구독·fetch 순서와 중복 제거(FR-3.3) |
| FR-10.1 | 참여자 추가 (Should) |
| FR-10.2 | 방 나가기 (Should) |
| NFR-4 | 순서 일관성 (수신 측) |

**FR-3.3은 U4와 U5가 나눠 갖는다.** 구독 순서와 중복 제거 로직은 U4의 `chatStore`·`wsClient`가, 히스토리 조회 API는 U5가 소유한다.

### U5 · messaging

| FR | 내용 |
|---|---|
| FR-4.1 | 저장 먼저·브로드캐스트 나중 |
| FR-4.2 | `(room_id, seq)` 채번, `FOR UPDATE` |
| FR-4.3 | 낙관적 렌더링 + ack 교체 |
| FR-4.4 | seq 커서 히스토리 |
| FR-6.4 | 콜드스타트 스킵 |
| FR-6.5 | 전송 버튼 비활성화 + "확인 중..." |
| FR-6.6 | 부적절 판정 확인 팝업 |
| FR-8.2 | 첫 실패 시 1회 확인 |
| FR-8.3 | degraded 전환, `failed` 상태 |
| FR-8.4 | 거절 시 취소 + "다시 시도" 버튼 |
| FR-8.5 | 5번째 메시지 프로브, 복귀 알림 |
| FR-8.6 | "검증 안 됨" 배지 |
| FR-11.1 | 오발송 신고 |
| FR-11.2 | 검증 상태 무관 신고 가능 |
| FR-11.3 | `misdirect_reported_at` 컬럼 |
| FR-3.3 | 히스토리 조회 API 몫 (구독 순서·중복 제거는 U4) |
| FR-7.1 | 판정을 안 하는 경우의 상태 3값 — `disabled`·`skipped_no_context`·`degraded` (판정 결과 3값은 U2) |
| NFR-2 | 응답성 |
| NFR-3 | 데이터 무결성 |
| NFR-5 | 프라이버시 고지 |
| NFR-7 | 테스트 — 동시 채번(FR-4.2), degraded 상태 기계(FR-8.3·8.5) |

## 커버리지 확인

### 모든 FR이 배정되었는가

| 영역 | 항목 수 | 배정 |
|---|---|---|
| FR-1 인증 | 4 | U3 (FR-1.3은 U4와 공유) |
| FR-2 친구 | 4 | U3 |
| FR-3 방 | 3 | U4 (FR-3.3은 U5와 공유) |
| FR-4 전송·순서 | 4 | U5 |
| FR-5 알림 | 4 | U4 |
| FR-6 판정 | 7 | U2 (6.2·6.3·6.7), U4 (6.1), U5 (6.4·6.5·6.6) |
| FR-7 로그·상태 | 5 | U2 (FR-7.1은 U5와 공유) |
| FR-8 실패 처리 | 6 | U2 (8.1), U5 (8.2~8.6) |
| FR-9 컨테이너 | 5 | U1 |
| FR-10 참여자 관리 | 2 | U4 (Should) |
| FR-11 신고 | 3 | U5 |
| NFR | 7 | U1 (NFR-6), U2 (NFR-1), U4 (NFR-4, NFR-7 일부), U5 (NFR-2·3·5, NFR-7 일부) |
| CON | 4 | U1 (CON-1·2), U4 (CON-4 — WebSocket 커스텀 헤더 불가), CON-3(일정)은 전역 |

**미배정 FR 없음.** `requirements.md`의 FR 항목 47개와 NFR 7개가 모두 단위를 갖는다.

### 모든 단위가 요구사항을 갖는가

| 단위 | FR 수 |
|---|---|
| U1 | 6 + 스키마 |
| U2 | 10 |
| U3 | 7 |
| U4 | 13 |
| U5 | 21 |

**요구사항 없는 단위 없음.**

### 여러 단위에 걸치는 항목

네 개다. 각각 어느 단위가 무엇을 갖는지 위에 명시했다.

| FR | 나뉜 방식 |
|---|---|
| FR-1.3 | U3이 `verify_token()` 제공, U4가 WS 첫 프레임에서 소비 |
| FR-3.3 | U4가 구독 순서·중복 제거, U5가 히스토리 조회 API |
| FR-7.1 | U2가 판정 결과 상태 3값, U5가 판정 안 함 상태 3값 |
| NFR-7 | U4가 구독·fetch 순서 테스트, U5가 동시 채번·degraded 상태 기계 테스트 |

**걸치는 항목이 넷뿐인 것이 이 분해의 품질 지표다.** 단위 경계가 요구사항 경계와 대체로 일치한다는 뜻이다.

**FR-5.2는 걸치지 않는다.** U4가 온전히 소유한다 — 배지 값은 `last_read_seq`(U4의 `room_members` 컬럼)와 수신 시 갱신(U4의 `chatStore`)에서 나오며, U5는 메시지를 저장·브로드캐스트할 뿐 배지를 만지지 않는다.

## 단위 내 구현 순서

단위 **안에서의** 순서만 적는다. 단위 **사이의** 순서는 `unit-of-work-dependency.md`의 DAG가 허용하는 범위이며 이 문서가 정하지 않는다.

| 단위 | 내부 순서 |
|---|---|
| U1 | compose·Dockerfile → config → db → Alembic 설정 → 스키마 마이그레이션 → healthcheck |
| U2 | 스키마 확인 → 프롬프트 초안 → Structured Outputs 호출 → 점수·임계값 → 로그 적재 → 타임아웃·재시도 → 지표 CLI |
| U3 | 해싱·JWT → 회원가입·로그인 → `verify_token()` → 친구 검색·등록·별칭 → 두 화면 |
| U4 | 방 CRUD → WS 엔드포인트·인증 → 레지스트리·푸시 → 다중 탭 처리 → 배지·토스트 → AI 토글 |
| U5 | seq 채번·저장·브로드캐스트 → 히스토리 → 판정 통합·409 흐름 → 팝업 → degraded·프로브 → 배지 → 신고 |

**U2의 "프롬프트 초안"이 가장 먼저 손대야 할 실질적 미지수다.** 나머지는 전부 알려진 작업이다.

## Assumptions & Open Questions

- FR을 스토리 대용으로 쓰므로 사용자 여정 관점의 검증(이 흐름이 실제로 쓸 만한가)이 빠진다. `rough-mockups`가 스코프에서 제외되어 그 검증 지점이 없다.
- CON-3(일정 고정)은 특정 단위에 배정하지 않았다. 전역 제약이다. CON-1(단일 프로세스)·CON-2(브로커 없음)는 U1이, CON-4(WS 커스텀 헤더 불가)는 U4가 받는다.
- U5가 21개 항목으로 가장 무겁다. 일정이 밀리면 여기가 압박을 받으며, 절단 순서(FR-10 → FR-8.5 → FR-11)의 마지막 둘이 이 단위 안에 있다.
- 단위 내부 순서는 제안이며 구속력이 없다.

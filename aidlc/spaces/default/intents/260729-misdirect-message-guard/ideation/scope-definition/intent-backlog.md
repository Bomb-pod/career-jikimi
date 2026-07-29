# Intent Backlog — 문맥 기반 오발송 메시지 경고

우선순위가 매겨진 proto-Unit 목록이다. `scope-document.md`의 경계와 MoSCoW 등급을 작업 단위로 편 것이며, `../intent-capture/intent-statement.md`의 노력 배분 결정(판정 경로 집중)을 순서에 반영했다.

여기서의 "proto-Unit"은 확정된 Unit of Work가 아니다. Units Generation(2.7)이 의존 관계를 포함한 실제 Unit으로 재정의하며, 이 목록은 그 입력이다.

## 등급 요약

| 등급 | proto-Unit 수 |
|---|---|
| Must | 9 |
| Should | 2 |
| Won't (this time) | 7 |

## Must

### PU-01 · 데이터 스키마와 마이그레이션

MariaDB(InnoDB, `utf8mb4`) 스키마. `users`, `friendships`(`alias` NOT NULL), `rooms`(`last_seq`), `room_members`(`ai_check_enabled`), `messages`(`seq`, `verification_status`), `judgment_logs`.

- 다른 모든 Unit이 여기에 의존한다. 가장 먼저 선다.
- `verification_status`는 6값을 모두 정의한다: `ok` / `flagged_sent` / `disabled` / `skipped_no_context` / `failed` / `degraded`.
- `judgment_logs.message_id`는 nullable — 사용자가 취소한 건은 메시지가 없다.
- 문자셋을 명시하지 않으면 한글·이모지가 깨진다.

### PU-02 · 인증

회원가입·로그인, 비밀번호 해싱, JWT 발급·검증, 인증 의존성 주입. 리프레시 토큰과 만료 갱신은 만들지 않는다.

- WebSocket 첫 프레임 auth는 PU-04에 속한다 — 토큰 검증 함수만 여기서 제공한다.
- 자격증명 하드코딩은 금지되어 있다. 비밀은 환경변수로 읽는다.

### PU-03 · 친구와 별칭

아이디 정확 일치 검색, 승인 없는 즉시 등록(별칭 필수 입력), 별칭 수정, 친구 목록 조회.

- 최소 구현이 방침이다. 부분 일치 검색·정렬·승인 절차는 만들지 않는다.
- 별칭이 NOT NULL이므로 등록 요청에 별칭이 없으면 400으로 거절한다.

### PU-04 · WebSocket 연결과 방

친구 다수 선택 초대로 방 생성, 방 목록, 방 입장. 사용자당 단일 WebSocket 연결, 연결 직후 첫 프레임 auth, payload의 `room_id`로 방 멀티플렉싱, 프로세스 메모리 연결 레지스트리.

- 서버는 단일 프로세스로 고정한다. 워커를 늘리면 레지스트리가 갈라져 메시지가 유실된다.
- 방마다 연결을 새로 열지 않는다.

### PU-05 · 메시지 전송과 순서 보장

저장 먼저·브로드캐스트 나중. `SELECT last_seq FROM rooms WHERE id=? FOR UPDATE` → `+1` → INSERT를 한 트랜잭션에 묶는다. 클라이언트는 임시 ID로 낙관적 렌더링 후 ack의 실제 ID로 교체한다.

- 정렬 기준은 `created_at`이 아니라 `(room_id, seq)`다.
- 순서가 반대면(브로드캐스트 먼저) DB 쓰기 실패 시 화면엔 보이는데 새로고침하면 사라진다.
- 이 Unit이 위험 우선 순서에서 앞자리를 차지하는 이유는 동시성 때문이다.

### PU-06 · 대화 이어보기

`GET /rooms/{id}/messages?before=<seq>&limit=50` — seq 커서 페이지네이션. 방 입장 시 **구독 먼저, 히스토리 fetch 나중**, 겹치는 건 메시지 ID로 중복 제거.

- 순서가 반대면 그 사이에 도착한 메시지가 유실된다.

### PU-07 · AI 검증 판정

개인별 토글(`room_members.ai_check_enabled`, 신규 방 기본 켜짐), 최근 N개 문맥 + 후보 메시지로 적절/부적절 판정, 부적절 시 전송 확인 팝업, 문맥이 N개 미만이면 콜드스타트 스킵. 판정 로그 적재(문맥 범위 `context_from_seq`~`context_to_seq`, verdict, confidence, latency, 토큰 수, `user_action`).

- 판정 입력에 참여자 정보는 넣지 않는다. 대화 문맥만 본다.
- 취소된 메시지는 `messages`에 남지 않고 판정 로그에만 남는다.
- 전송 대기 중 전송 버튼 비활성화 + "확인 중..." 표시가 필수다. 1~3초 무반응은 멈춘 것으로 읽힌다.
- 프로젝트의 존재 이유다. 노력이 여기로 간다.

### PU-08 · 검증 실패 처리

타임아웃 3~5초, 재시도 1회, 첫 실패 시 1회 확인 → 승낙하면 degraded 전환(**사용자 전역** 범위, **세션 단위** 저장), degraded 중 5번째 메시지마다 프로브로 검증 시도해 성공 시 정상 복귀 + 알림, 검증받지 못한 메시지에 "검증 안 됨" 배지.

- 실패해도 조용히 보내지 않는다. 사용자는 검증받았다고 믿고 있다.
- 거절하면 전송 취소, 입력창 텍스트 유지, degraded로 넘어가지 않는다.
- 재시도는 1회다. 2회면 사용자가 9초를 기다린다.
- `failed`와 `degraded`를 한 상태로 합치지 않는다. 합치면 장애 빈도가 과대 집계된다.
- **일정 압박 시 프로브 회복 감지가 Should 다음의 절단 후보다.** 빼면 상태 관리가 크게 단순해지고 회복은 새로고침으로 대체된다.

### PU-11 · 컨테이너화

백엔드 Dockerfile(단일 uvicorn 프로세스), 프론트엔드 빌드 후 정적 서빙 컨테이너, `docker-compose.yml`로 앱 + MariaDB 오케스트레이션. DB healthcheck 후 앱 기동(`depends_on: condition: service_healthy`) + 앱 시작 시 연결 재시도. 비밀은 환경변수로 주입한다.

- MariaDB 이미지에 `utf8mb4` 문자셋을 명시한다. 기본값이 아닐 수 있다.
- `OPENAI_API_KEY`, DB 접속 정보는 하드코딩하지 않는다. Construction 가드레일이 금지한다.
- **walking skeleton Bolt에 포함한다 — 마지막이 아니라 처음이다.** 테이블 하나·엔드포인트 하나일 때가 compose 파일이 가장 단순하고, 나중에 붙이면 그동안 쌓인 환경 의존이 한꺼번에 드러난다.
- 컨테이너 하나에 프로세스 하나가 기본이라, "단일 프로세스로 고정" 제약이 구조적으로 지켜진다.

## Should

일정이 밀리면 가장 먼저 잘린다.

### PU-09 · 채팅방 참여자 추가

기존 방에 친구를 추가 초대. 방 멤버 INSERT + 초대 UI.

### PU-10 · 채팅방 나가기

방에서 나가기. 멤버 DELETE + 목록 갱신 + 남은 인원 처리.

## Won't have (this time)

| 항목 | 사유 |
|---|---|
| 내용 기준 필터링 (욕설·비방·민감정보) | 판정 대상을 문맥 적합성 하나로 유지한다 |
| 데이터셋 구축 | 제품 경계 밖 (트랙 2) |
| 성능 테스트·베이스라인 측정 | 제품 경계 밖 (트랙 3). 이번엔 측정 도구까지만 |
| 타이핑 인디케이터 | 판정과 무관 |
| 읽음 표시 | 판정과 무관 |
| 파일·이미지 전송 | 판정과 무관하고 저장·전송 경로가 복잡해진다 |
| 원격 서버 배포·CI 파이프라인·이미지 레지스트리 푸시·관측성 | 컨테이너화(PU-11)는 **로컬까지**다. 클라우드 호스트·도메인·HTTPS·비밀 관리 서비스는 범위 밖 |

## 순서 제안

위험 우선(Q7) 기준의 잠정 순서다. 확정은 Units Generation과 Delivery 판단의 몫이다.

```
PU-11 (컨테이너화) ---- 처음부터. 아래 전부가 이 안에서 돈다
  |
PU-01 (스키마)
  |
  +-- PU-02 (인증) --+
  |                  |
  +-- PU-04 (WS/방) -+-- PU-05 (전송/seq) -- PU-07 (판정) -- PU-08 (실패 처리)
  |                  |                          |
  +-- PU-03 (친구) --+                    PU-06 (히스토리)
                                                |
                                    PU-09, PU-10 (Should)
```

<!-- Text fallback: PU-11 컨테이너화가 가장 바깥이며 나머지 전부가 그 안에서 돈다. PU-01 스키마가 애플리케이션의 밑단이다. 그 위에 PU-02 인증, PU-03 친구, PU-04 WebSocket/방이 병렬로 선다. PU-05 메시지 전송과 seq 채번은 PU-02와 PU-04에 의존한다. PU-07 AI 판정은 PU-05에 의존하고, PU-08 실패 처리는 PU-07에 의존한다. PU-06 히스토리는 PU-05에 의존한다. Should 등급인 PU-09와 PU-10은 마지막이다. -->

walking skeleton Bolt는 이 그래프를 가로지르는 가장 얇은 수직선이다 — PU-11의 compose 뼈대, PU-01의 최소 테이블, PU-02의 로그인 하나, PU-04의 방 하나, PU-05의 메시지 한 건, PU-07의 판정 한 번, 판정 로그 한 줄. 이 선이 서면 두 개의 큰 위험(WebSocket 동시성, LLM 판정)이 증명되고, 그 전부가 컨테이너 안에서 돈다는 것까지 함께 증명된다.

## Assumptions & Open Questions

- `N`(문맥 메시지 개수)의 값이 미정이라 PU-07의 콜드스타트 임계값도 미정이다.
- 판정 프롬프트 설계가 미정이다. PU-07의 품질을 좌우한다.
- PU-09·PU-10을 실제로 잘라낼 판단 시점이 정해지지 않았다. walking skeleton 완료 시점이 자연스러운 결정 지점이다.
- proto-Unit의 경계가 실제 Unit of Work와 1:1로 대응하는지는 Units Generation에서 확정된다. 특히 PU-07과 PU-08은 하나의 Unit으로 합쳐질 수 있다.
- 프론트엔드를 별도 nginx 컨테이너로 서빙할지, FastAPI가 정적 파일을 함께 서빙할지 정해지지 않았다. Application Design에서 닫는다.

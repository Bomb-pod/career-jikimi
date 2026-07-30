# Performance Test Instructions — career-jikimi

Test Strategy가 **Standard**라 스테이지 프로즈는 이 파일을 요구하지 않는다. 만드는 이유는 둘이다 — 엔진의 `produces`가 선언하고 있고, `../../inception/requirements-analysis/requirements.md`에 **실제 성능 NFR이 하나 있다**(NFR-1). 그 하나에만 범위를 맞췄고 일반적인 부하 시험 계획으로 부풀리지 않았다.

각 단위가 무엇을 구현했는지는 `../<unit>/code-generation/code-summary.md`, 왜 그렇게 했는지는 `../<unit>/code-generation/code-generation-plan.md`에 있다.

## 대상 NFR

| NFR | 목표 | 현재 상태 |
|---|---|---|
| **NFR-1 판정 지연** | 정상 경로 **5초 이내**, 재시도 포함 최악 **10초 이내** | **미검증** — 실제 OpenAI 키로 한 번도 돌지 않았다 |
| NFR-2 응답성 | 판정 대기 중 UI가 멈춘 것처럼 보이지 않을 것 | 구현·검증됨 (아래) |

**NFR-2는 성능 시험 대상이 아니다.** `requirements.md`가 "FR-6.5의 비활성화 + '확인 중...' 표시가 이 요구사항의 구현이며, **그 존재 여부로 검증한다**"고 정했다. `ChatView.test.tsx`가 그것을 덮는다.

성능 NFR이 하나뿐인 것은 우연이 아니다 — `scope-document.md`가 성능 테스트·베이스라인 측정을 **트랙 3으로 분리해 이번 범위 밖**에 두었다.

## 지금까지 확보한 예산 증거

지연을 직접 재지는 못했으나 **상한이 구조로 강제되는지**는 검증했다.

| 장치 | 어디 | 검증 |
|---|---|---|
| per-request 타임아웃 `AI_TIMEOUT_SECONDS`(기본 4) | `app/judgment/client.py` | `test_client.py` |
| 재시도 **정확히 1회**, SDK 자체 재시도 꺼짐(`max_retries=0`) | 같은 곳 | `test_client.py::test_sdk_retries_are_disabled` |
| 두 시도의 합이 `TOTAL_BUDGET_SECONDS`(10) 안 | 같은 곳 | `test_client.py` 예산 클램프 테스트 |
| `Retry-After`를 **남은 예산 안에서만** 존중 | 같은 곳 | `test_client.py` |
| **기본값이 여유를 남기는지** — `MAX_ATTEMPTS × 기본값 < 10` | `app/core/config.py` | `test_config.py::test_default_timeout_leaves_margin_under_the_total_budget` |

마지막 항목이 중요하다. 기본값 5.0이면 두 시도의 합이 **정확히 10.0초로 여유가 0**이고, `judge()`의 커밋 왕복 두 번은 그 창 **밖**에 있어 NFR-1의 실측 대기 시간을 넘긴다. 4로 낮춰 2초의 여유를 남겼다.

**측정 창이 무엇인지 구분해야 한다** — `client.py`의 예산은 SDK에 넘기는 타임아웃의 합만 묶는다. NFR-1이 재는 것은 **사용자가 보는 전송 대기 시간**이고, 거기에는 문맥 조회·로그 INSERT·커밋·seq 채번 트랜잭션·브로드캐스트가 더 붙는다.

## 실제 측정 방법 — 키를 넣은 뒤

`.env`의 `OPENAI_API_KEY`를 실제 키로 바꾼 다음.

### ① 판정 단독 지연 — `try` CLI

가장 싸고 빠른 경로다. 채팅 UI도 방도 필요 없다.

```bash
docker compose exec app python -m app.judgment.try \
  --context "내일 회의 몇 시죠?" "10시입니다" "자료는 제가 준비할게요" \
  --candidate "오늘 저녁에 치킨 어때?"
```

출력에 `latency`와 토큰이 찍힌다. 문맥을 여러 벌 만들어 10~20회 돌리고 분포를 본다 — p50과 최댓값을 함께 봐야 한다. **평균은 보지 않는다**: 평균 1.5초가 최댓값 9초를 가린다.

### ② 종단 전송 지연 — 사용자가 실제로 기다리는 시간

방에 메시지가 `AI_CONTEXT_N`(10)개 이상 쌓여 있어야 판정이 돈다(FR-6.4).

```bash
curl -s -o /dev/null -w 'total=%{time_total}s\n' \
  -X POST http://localhost:8000/rooms/<id>/messages \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer <token>' \
  -d '{"text":"측정용 메시지"}'
```

**이 숫자가 NFR-1이 재는 값이다.** 20회 돌려 p50·p95·max를 낸다.

| 판정 | 기준 |
|---|---|
| PASS | p95 < 5초 이고 max < 10초 |
| 주의 | p95는 통과하나 max가 8~10초 — 타임아웃을 3으로 낮추는 것을 검토 |
| FAIL | max ≥ 10초 — 예산 계산이나 그 밖의 단계에 새는 시간이 있다 |

### ③ 실패 경로의 최악값

키를 일부러 틀리게 두면 재시도까지 전부 소진하는 경로를 잴 수 있다.

```bash
docker compose exec -e OPENAI_API_KEY=sk-invalid app \
  python -m app.judgment.try --context "..." --candidate "..."
```

**주의** — 잘못된 키는 401(4xx)이라 재시도 대상이 아니다(BR-6.7). 진짜 최악값(타임아웃 2회)을 재려면 도달 불가 엔드포인트로 `OPENAI_BASE_URL`을 돌리는 편이 낫다.

### ④ 동시 채번의 직렬화 비용

같은 방 동시 전송은 `FOR UPDATE`로 직렬화된다(설계 의도). 다른 방은 막히지 않는다.

`test_seq_allocation.py`가 정확성은 이미 검증했다. 지연 관점의 측정이 필요하면 같은 픽스처(`live_sessionmaker`)에 시간 측정을 얹는다. **데모 규모에서는 불필요하다** — `services.md`가 "한 방에서 초당 여러 명이 동시에 보내는 상황은 드물다"로 이미 정리했다.

## 하지 않는 것

`scope-document.md`와 `requirements.md` § Out of Scope가 범위 밖으로 정한 것들이다. 도구를 붙이지 않았다.

- **부하 시험** (k6·Locust·Artillery) — 동시 사용자 목표가 없다. 데모 사용자는 시연자와 몇 명뿐이다
- **스트레스·소크 시험** — 실행 시간이 데모 수명보다 길다
- **자동 확장 검증** — 단일 프로세스로 고정되어 있다 (CON-1, FR-9.4). 확장 지점은 `ws_registry`를 Redis pub/sub으로 바꾸는 것이며 그때 필요해진다
- **DB 용량 계획** — `(room_id, seq)` 인덱스가 히스토리를 덮고, `services.md`가 데모 규모에서 문제없다고 이미 판단했다

## 알려진 병목 — 넘어설 때 볼 것

`services.md` § 확장 특성이 기록한 순서다.

| 한계 | 원인 | 넘어서려면 |
|---|---|---|
| 동시 접속자 | 단일 프로세스 + 메모리 레지스트리 (CON-1) | `ws_registry`를 Redis pub/sub으로 |
| **같은 방의 동시 전송** | `FOR UPDATE` 행 잠금이 방 단위로 직렬화 | 앱 레벨 시퀀스나 Snowflake ID |
| 판정 처리량 | OpenAI rate limit + 동기 차단 | 전송 전 차단이 요구사항이라 비동기화 불가. 큐잉으로 완화 |

**"같은 방의 동시 전송"이 가장 먼저 막히지만** 방 단위 잠금이라 다른 방은 영향받지 않는다.

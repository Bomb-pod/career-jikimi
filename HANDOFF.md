# 이어서 하기

**AI-DLC 워크플로는 종료되었다 — 11/11.** `main` = `c7a11f3` (2026-07-30 마지막).

설계·구현·검증·UI가 전부 끝났고, **남은 것은 하나다** — 실제 API 키.

> 워크플로가 완료 상태이므로 `/aidlc --resume`으로 이어받을 스테이지가 없다.
> 새 작업이 생기면 `/aidlc`가 두 번째 인텐트를 제안한다.

---

## 지금 당장 할 것 — API 키 넣기. 그것뿐이다.

`.env`의 `OPENAI_API_KEY`가 아직 `PLACEHOLDER-...`다. **그 한 줄만 바꾸면 아래 셋이 즉시 돈다.** 다른 준비는 없다.

```bash
# 1) 키를 넣는다
#    .env 의 OPENAI_API_KEY=PLACEHOLDER-... 를 실제 키로

# 2) 컨테이너에 반영 (재빌드 아니라 재시작이면 된다 — env_file은 런타임에 읽는다)
docker compose up -d

# 3) 판정 한 건 — 채팅 UI도 방도 사용자도 필요 없다
docker compose exec app python -m app.judgment.try \
  --context "내일 회의 몇 시죠?" "10시입니다" "자료는 제가 준비할게요" \
  --candidate "오늘 저녁에 치킨 어때?"
```

`--show-prompt`를 붙이면 조립된 프롬프트를 눈으로 확인할 수 있고, `--dry-run`은 **키 없이도** 익명화를 보여준다.

### 그리고 이것 — 라벨 데이터셋으로 recall을 실제로 산출한다

```bash
cd backend
.venv/Scripts/python.exe -m app.judgment.evaluate --limit 40
```

`dataset/`의 744행 라벨 데이터셋에 **판정 경로와 똑같은 프롬프트**를 돌려 precision·**recall**·F1·혼동행렬·점수 분포·난이도별 성능·임계값 스윕을 낸다.

**FR-7.5가 "recall은 산출 불가 — 라벨 데이터셋 필요"라고 못박은 그 항목이 여기서 산출된다.** 라이브 지표(`report`)에서 불가인 이유는 놓친 오발송의 모수를 모르기 때문이고, 라벨은 그 모수를 준다.

| | 무엇을 재는가 | recall |
|---|---|---|
| `python -m app.judgment.report` | 실사용 중 사용자가 어떻게 반응했는가 | 산출 불가 |
| `python -m app.judgment.evaluate` | 모델이 정답 라벨을 맞히는가 | **산출된다** |

`--limit 40`은 첫 실행을 싸게 하려는 값이다(토큰 추정 비용이 함께 찍힌다). 전량은 `--limit 0`, 표본별 결과 저장은 `--out result.csv`. **표본은 두 라벨에서 번갈아 뽑아 항상 50:50이고, 같은 `--limit`은 매번 같은 표본을 준다** — 프롬프트를 고친 전후를 비교할 수 있어야 하기 때문이다.

임계값 스윕이 `ASM-3`("임계값은 데이터를 보고 정할 값")에 답한다 — 0.05 간격으로 훑어 F1이 가장 높은 지점을 현재 설정값과 나란히 보여준다.

### 확인할 것 셋 — 전부 아직 검증되지 않은 가정이다

1. **프롬프트가 실제로 문맥 부적합을 잡는가** — 이 프로젝트의 가장 큰 미지수. `evaluate`의 recall과 점수 분포가 답한다
2. **점수 구간 설명이 분포를 벌리는가** — `evaluate`가 두 라벨의 평균 간격을 출력하고, 0.1 미만이면 경고한다
3. **NFR-1** — 정상 5초 / 최악 10초. `evaluate`가 p50·p95·max와 5초 초과 건수를 함께 낸다

방법의 상세는 `aidlc/.../construction/build-and-test/performance-test-instructions.md`.

---

## 실행

```bash
cp .env.example .env      # JWT_SECRET, OPENAI_API_KEY 채우기
docker compose up -d --build
# → http://localhost:8000
```

지금 동작하는 것: **회원가입 → 친구 추가 → 방 생성(친구 선택) → 방 클릭으로 대화 진입 → 메시지 전송 → 히스토리 → 오발송 신고 → 로그아웃.** 라이브 스모크 29/29로 확인됨.

새로고침해도 로그인이 유지된다 — 부팅 시 `GET /auth/me`로 세션을 복구하고 방 목록으로 보낸다. 토큰이 만료됐으면(401) 지우고 로그인 화면으로, 서버가 잠깐 죽은 것이면(네트워크·5xx) 토큰을 지키고 이름만 비워둔다.

**UI는 한국 메신저 관용구를 따른다** — 하단 탭(친구/채팅/대화), 내 말풍선 오른쪽·상대 왼쪽에 아바타와 별칭, 안 읽은 배지, 하단 고정 입력바. 브랜드(로고·특정 서비스 색 값)는 가져오지 않았다. 접근성 제약이 디자인보다 앞이라 "검증 안 됨"은 색이 아니라 아이콘+문구로, 내/상대는 좌우 위치와 꼬리 방향으로 갈린다.

### 지금 떠 있는 컨테이너

어제 세션에서 띄운 것이 남아 있을 수 있다.

```bash
docker compose ps                # app + db
docker compose down              # 끄기 (볼륨은 남는다)
docker rm -f cj-testdb           # 테스트 DB (포트 33061)
```

### 테스트

```bash
# 테스트 DB (한 번만)
docker run -d --name cj-testdb -e MARIADB_ROOT_PASSWORD=testpw \
  -e MARIADB_DATABASE=career_jikimi_test -p 33061:3306 mariadb:11 \
  --character-set-server=utf8mb4 --collation-server=utf8mb4_unicode_ci
# .env의 TEST_DATABASE_URL을 위 DB로 맞춘다

cd backend && python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest -q -rs        # 338 passed / skip 0

cd ../frontend && npm install && npx vitest run   # 147 passed
```

**`-rs`를 항상 붙인다.** 스키마 테스트는 실제 MariaDB를 요구하고 없으면 skip된다 — 통과처럼 보이는 미검증이 가장 나쁘다.

### 지표

```bash
docker compose exec app python -m app.judgment.report      # 라이브 지표
cd backend && .venv/Scripts/python.exe -m app.judgment.evaluate --limit 40   # 오프라인 평가
```

`report`에서 `recall`이 수치가 아니라 `산출 불가 — 라벨 데이터셋 필요`로 나오는 것이 **정상이다** (FR-7.5). 그 값이 필요하면 `evaluate`를 쓴다 — 위 § 지금 당장 할 것.

---

## 환경 상태

| 항목 | 상태 |
|---|---|
| AI-DLC | v2.5.11 · 워크플로 **완료 (11/11)** |
| bun | `C:\Users\403\.bun\bin\bun.exe` |
| 스코프 | `greenfield-local-demo` |
| git | `main` → `github.com/Bomb-pod/career-jikimi` · `construction/code-generation` 브랜치에 세부 이력 |
| 테스트 | 백엔드 **338** / 프론트 **147** / **skip 0** |
| 스택 | `python:3.12-slim` + FastAPI + SQLAlchemy async + asyncmy · React 18 + TS + Vite + Zustand |

`--doctor`에서 bun이 실패하면 VSCode가 완전히 종료되지 않은 것이다. 창만 닫지 말고 `파일 > 끝내기`로 나갔다 다시 열 것.

---

## 알아두어야 하는 것

### 컨테이너에 코드를 굽는다 — 바인드 마운트가 없다

`docker-compose.yml`이 이미지에 코드를 넣는다. **고친 뒤에는 `docker compose up -d --build`** 를 해야 반영된다. 프론트는 `deploy/Dockerfile` 1스테이지에서 `npm run build`한 결과를 FastAPI가 `static/`으로 서빙한다 (FR-9.5).

빠른 반복은 Vite dev 서버로 한다 — `.env`에 `CORS_ORIGINS=http://localhost:5173`을 넣고 `cd frontend && npm run dev`.

### 서버는 단일 프로세스로 고정

`uvicorn --workers 2` 이상이면 WebSocket 연결 레지스트리가 갈라진다 (CON-1, FR-9.4). 컨테이너화가 이 제약을 구조적으로 지켜준다.

### 프론트 레이아웃은 jsdom이 못 잡는다

프론트 테스트 147개가 전부 통과하는 상태에서 **입력창이 화면에서 사라져 있던 적이 있다.** jsdom은 DOM 구조만 보고 실제 크기를 계산하지 않아 "버튼이 있다"는 통과하고 "버튼이 화면을 다 먹었다"도 통과한다.

CSS나 레이아웃을 고쳤으면 **실제 브라우저로 한 번 봐야 한다.** playwright를 `--no-save`로 설치해 구동하는 방법을 썼다(`package.json`은 건드리지 않는다):

```bash
cd frontend && npm install --no-save playwright && npx playwright install chromium
```

### ASCII 전용 파일 셋

`backend/requirements.txt`·`requirements-dev.txt`·`alembic.ini`는 **ASCII만** 담는다. pip과 alembic이 Windows에서 로케일 코드페이지로 읽어, 한글 주석이 있으면 한국어 Windows(cp949)에서 실행 전에 `UnicodeDecodeError`가 난다. 한국어 근거는 항상 UTF-8로 읽히는 `.py` 파일에 남긴다.

### 상류 배포판에서 손댄 것 — `.claude/settings.json`

원본은 이 프로젝트를 AWS Bedrock으로 강제한다. **이 PC에 AWS 자격증명이 없어** 그대로 두면 Claude Code가 실행되지 않으므로 관련 6줄을 지우고 `AWS_AIDLC_DEFAULT_SCOPE`만 남겼다. 재설치·업데이트 시 다시 적용해야 한다.

`.claude/CLAUDE.md`의 Prerequisites에는 여전히 "AWS Bedrock access 필요"라고 적혀 있다 — 배포판 원문이니 무시해도 된다.

---

## 미해결 항목

| 항목 | 상태 |
|---|---|
| **프롬프트 품질·NFR-1 실측** | **미검증 — 키 필요.** 위 § 지금 당장 할 것 |
| 한국어 프롬프트가 맞는 선택인지 | 미검증 가정 |
| FR-10 방 참여자 추가·나가기 | **절단됨.** 복원은 U4 계획 `Step 7`만 실행 (체크박스가 작업 목록으로 남아 있다) |
| `starlette` 취약점 8건 | **수용된 위험.** 로컬 전용이라 원격 도달 경로 없음. 원격 배포 시 **첫 처리 항목** |
| `asyncmy` PYSEC-2026-286 | 최신에도 있고 수정 버전 미공개 |
| `probe=true` 서버 측 미방어 | ADR-007의 자해 범주. 다중 사용자로 나가면 좁혀야 한다 |
| 프롬프트 인젝션 (여러 줄 본문) | 자기 메시지 판정만 왜곡 가능. 정규화하면 판정 대상과 전송 내용이 달라진다 |
| FR-8.1 "3~5초" vs NFR-1 | 요구사항 수준의 긴장. Construction이 좁힐 자리가 아니라 기록만 |

---

## 문서 위치

| 무엇 | 어디 |
|---|---|
| 설계 개요 | [README.md](README.md) |
| 오늘 로그 | [docs/daily/2026-07-30.md](docs/daily/2026-07-30.md) |
| 요구사항 (권위) | `aidlc/.../inception/requirements-analysis/requirements.md` |
| 구조 결정 (ADR 8건) | `aidlc/.../inception/application-design/decisions.md` |
| 작업 단위 | `aidlc/.../inception/units-generation/unit-of-work.md` |
| 판정 프롬프트 | `aidlc/.../construction/judgment-core/functional-design/business-logic-model.md` |
| **단위별 구현 요약** | `aidlc/.../construction/<unit>/code-generation/code-summary.md` |
| **빌드·테스트 결과** | `aidlc/.../construction/build-and-test/build-test-results.md` |
| 실행·테스트 방법 | `aidlc/.../construction/build-and-test/build-instructions.md` |

**범위와 요구사항의 최종 권위는 README가 아니라 `aidlc/` 산출물이다.**

`dataset/`(744행 라벨)과 `training/`(A.X-Encoder 파인튜닝)은 요구사항이 **트랙 2**로 분류해 이번 범위 밖에 둔 작업이다. FR-7.5가 "recall은 라벨 데이터셋이 있어야 산출 가능"이라고 적었으므로, 그 데이터셋이 **오프라인 recall 평가의 입력**이 된다.

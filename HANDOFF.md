# 인수인계 — 2026-07-29

VSCode 재시작 후 이 파일부터 읽으면 바로 이어서 진행할 수 있다.

**설계 내용은 여기 없다. [README.md](README.md)에 있다.** 이 문서는 환경 세팅 상태와 다음 할 일만 담는다.

---

## 지금 상태

AI-DLC 세팅 완료. **워크플로는 아직 시작 안 함** (`aidlc/spaces/default/intents/` 비어 있음).

| 항목 | 상태 |
|---|---|
| AI-DLC | v2.5.11 (`dist/claude` 배포판) — `.claude/` + `aidlc/` |
| `--doctor` | 42/42 통과 |
| bun | 1.3.14 — `C:\Users\403\.bun\bin\bun.exe` |
| 기본 scope | `mvp` |
| 설계 문서 | README.md 정리 완료 |

출처: https://github.com/awslabs/aidlc-workflows (v2 브랜치)

---

## 재시작 후 할 일

```
/aidlc --doctor    # 맨 위 "bun installed" 항목 확인
/aidlc             # README 내용으로 워크플로 시작
```

`--doctor`에서 bun이 실패하면 VSCode가 완전히 종료되지 않은 것이다. 창만 닫지 말고 `파일 > 끝내기`로 나갔다 다시 열 것.

scope는 `settings.json`에 `mvp`로 잡혀 있어 따로 지정할 필요 없다. 시작 후 바꾸려면 `/aidlc --scope <이름>`.

---

## 상류 배포판에서 손댄 것 2가지

`dist/claude` 원본과 다른 부분이다. 나중에 재설치하거나 업데이트할 때 다시 적용해야 한다.

### 1. Bedrock 설정 제거 — `.claude/settings.json`

원본은 `env`에 아래를 넣어 이 프로젝트를 AWS Bedrock으로 강제한다.

```
CLAUDE_CODE_USE_BEDROCK=1 / AWS_REGION=us-east-1
ANTHROPIC_DEFAULT_{FABLE,OPUS,SONNET,HAIKU}_MODEL=global.anthropic.*
```

**이 PC에 AWS 자격증명이 없어서**(`~/.aws/` 없음, 환경변수 없음, AWS CLI 미설치) 그대로 두면 이 폴더에서 Claude Code가 실행되지 않는다. 위 6줄을 지우고 `AWS_AIDLC_DEFAULT_SCOPE`만 남겼다.

> `.claude/CLAUDE.md`의 Prerequisites에는 여전히 "AWS Bedrock access 필요"라고 적혀 있다. 배포판 원문 그대로 둔 것이니 무시해도 된다.

### 2. 기본 scope 변경 — `workshop` → `mvp`

`workshop`은 AI-DLC 교육용 기본값이라 OPERATION 7단계(배포 파이프라인, 환경 프로비저닝, 관측성, 인시던트 대응 등)를 전부 실행하고 테스트 전략이 `Minimal`이다. 로컬 데모에는 운영 단계가 낭비고, 판정 성능 측정이 목적이라 테스트는 `Standard`가 필요하다.

`mvp`는 OPERATION을 건너뛰고 IDEATION 4단계(의도 파악·타당성·범위 정의·개략 목업)를 가볍게 돈다.

---

## 그 외 환경 메모

- **서버는 단일 프로세스로 띄울 것.** `uvicorn --workers 2` 이상이면 WebSocket 연결 레지스트리가 깨진다. (README 4번 항목 참조)
- **`.mcp.json`** — 다음 실행 시 MCP 서버 승인을 물어본다. `context7`은 `CONTEXT7_API_KEY`가, AWS 서버 4종은 AWS 자격증명이 필요하다. 없으면 비활성으로 남고 워크플로를 막지는 않는다. 안 쓸 거면 파일을 지우면 된다. (`uvx`는 설치되어 있음)
- **git 미초기화.** `.gitignore`는 깔려 있지만 아직 레포가 아니다. AI-DLC는 `aidlc/` 트리를 커밋하는 걸 전제로 설계돼 있어 `git init`을 권한다.

---

## 미결정

README 하단 "미결정" 섹션 참조. 요약하면 프로젝트명, DB 확정, WebSocket 인증 방식, 친구 등록 방식, 판정 프롬프트, 데이터셋 라벨링 기준, `N` 최종값.

README에서 `(가정)`으로 표시된 항목은 반대 의견이 없어 잠정 결정한 것이라 언제든 바꿀 수 있다.

---

*이 파일은 `/aidlc` 워크플로가 시작되면 역할이 끝난다. 그때 지워도 된다.*

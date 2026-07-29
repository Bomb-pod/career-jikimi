# 이어서 하기

```
/aidlc --resume
```

워크플로는 `code-generation` **직전**에서 파킹되어 있다. 설계는 전부 끝났고 다음이 코드다.

**오늘 무엇을 했고 내일 무엇부터 정해야 하는지는 [docs/daily/2026-07-29.md](docs/daily/2026-07-29.md)에 있다.**

---

## 환경 상태

| 항목 | 상태 |
|---|---|
| AI-DLC | v2.5.11 · `--doctor` 42/42 통과 |
| bun | 1.3.14 — `C:\Users\403\.bun\bin\bun.exe` |
| 스코프 | `greenfield-local-demo` (재구성 후 11단계) |
| git | `main` → `github.com/Bomb-pod/career-jikimi` · 오늘 작업 전부 푸시됨 |
| 진행 | 9/11 단계 승인 |

`--doctor`에서 bun이 실패하면 VSCode가 완전히 종료되지 않은 것이다. 창만 닫지 말고 `파일 > 끝내기`로 나갔다 다시 열 것.

---

## 상류 배포판에서 손댄 것 2가지

`dist/claude` 원본과 다른 부분이다. 재설치·업데이트 시 다시 적용해야 한다.

### 1. Bedrock 설정 제거 — `.claude/settings.json`

원본은 `env`에 아래를 넣어 이 프로젝트를 AWS Bedrock으로 강제한다.

```
CLAUDE_CODE_USE_BEDROCK=1 / AWS_REGION=us-east-1
ANTHROPIC_DEFAULT_{FABLE,OPUS,SONNET,HAIKU}_MODEL=global.anthropic.*
```

**이 PC에 AWS 자격증명이 없어서**(`~/.aws/` 없음, 환경변수 없음, AWS CLI 미설치) 그대로 두면 이 폴더에서 Claude Code가 실행되지 않는다. 위 6줄을 지우고 `AWS_AIDLC_DEFAULT_SCOPE`만 남겼다.

> `.claude/CLAUDE.md`의 Prerequisites에는 여전히 "AWS Bedrock access 필요"라고 적혀 있다. 배포판 원문 그대로 둔 것이니 무시해도 된다.

### 2. 기본 scope 변경 — `workshop` → `mvp`

`workshop`은 교육용 기본값이라 OPERATION 7단계를 전부 실행하고 테스트 전략이 `Minimal`이다. 로컬 데모에 운영 단계는 낭비다.

실제 이 프로젝트는 컴포저가 만든 `greenfield-local-demo` 스코프로 돌고 있다 — `.claude/scopes/aidlc-greenfield-local-demo.md`.

---

## 그 외

- **서버는 단일 프로세스로 띄울 것.** `uvicorn --workers 2` 이상이면 WebSocket 연결 레지스트리가 깨진다. 컨테이너화가 이 제약을 구조적으로 지켜준다.
- **`.mcp.json`** — `context7`은 `CONTEXT7_API_KEY`가, AWS 서버 4종은 AWS 자격증명이 필요하다. 없으면 비활성으로 남고 워크플로를 막지는 않는다.

---

## 문서 위치

| 무엇 | 어디 |
|---|---|
| 설계 개요 | [README.md](README.md) |
| 오늘 로그 | [docs/daily/2026-07-29.md](docs/daily/2026-07-29.md) |
| 요구사항 (권위) | `aidlc/.../inception/requirements-analysis/requirements.md` |
| 구조 결정 (ADR 8건) | `aidlc/.../inception/application-design/decisions.md` |
| 작업 단위 | `aidlc/.../inception/units-generation/unit-of-work.md` |
| 판정 프롬프트 | `aidlc/.../construction/judgment-core/functional-design/business-logic-model.md` |

**범위와 요구사항의 최종 권위는 README가 아니라 `aidlc/` 산출물이다.**

"""`messages`의 상수 — 본문 길이 상한과 히스토리 페이지 크기.

출처: `construction/messaging/code-generation/code-generation-plan.md` Step 1과
§ 이 계획이 닫는 열린 항목.
"""

from __future__ import annotations

from typing import Final

#: 메시지 본문 길이 상한. 초과하면 400 `MESSAGE_TOO_LONG` (Step 1).
#:
#: **세 단위가 반복해서 제기한 열린 항목을 여기서 닫는다.** 상한이 없으면 한 메시지가
#: 판정 토큰 비용을 무제한으로 키우고, 그 원문이 `judgment_logs.candidate_text`에도
#: 그대로 쌓인다. 2000자는 채팅 메시지로 넉넉하고(한글 기준 원고지 10장) 문맥 10개를
#: 합쳐도 토큰이 통제된다.
#:
#: **DB가 막아주지 않는다.** `messages.body`는 TEXT(64KB)라 여기서 걸러야 한다 —
#: 컬럼 폭에 기대면 상한이 사실상 없는 것과 같다.
#:
#: 프론트엔드의 `MESSAGE_MAX_LENGTH`와 **같은 값**이어야 한다
#: (`frontend/src/lib/constants.ts`). 두 곳에 두는 것을 받아들인 이유는 U3의
#: `PASSWORD_MIN_LENGTH`와 같다 — 제출 전에 막으면 확실히 실패할 요청의 왕복을 아낀다.
MESSAGE_MAX_LENGTH: Final[int] = 2000

#: `GET /rooms/{id}/messages`의 기본 페이지 크기 (BR-4.4).
HISTORY_DEFAULT_LIMIT: Final[int] = 50

#: 같은 엔드포인트의 상한. 요청이 더 큰 값을 주면 **거부하지 않고 잘라낸다** —
#: 페이지 크기는 도메인 규칙이 아니라 서버가 정하는 자원 한도이고, 400을 주면
#: 클라이언트가 상한을 알아야만 조회할 수 있게 된다 (BR-4.4).
HISTORY_MAX_LIMIT: Final[int] = 100

__all__ = [
    "HISTORY_DEFAULT_LIMIT",
    "HISTORY_MAX_LIMIT",
    "MESSAGE_MAX_LENGTH",
]

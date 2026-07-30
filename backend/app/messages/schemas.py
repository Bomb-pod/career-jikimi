"""`messages`의 요청·응답 스키마.

**409 두 종이 같은 스키마를 쓰고 `reason`으로 갈린다** (`BlockedResponse`). 상태
코드를 나누면(예: 503) 클라이언트가 네트워크 오류와 헷갈린다 — 여기서 실패한 것은
판정이지 요청이 아니다.

**`BlockedResponse`는 `{"error": {...}}` 봉투를 쓰지 않는다.** 409는 오류가 아니라
정상 분기이며(BR-6.3), 클라이언트가 `log_id`를 그대로 꺼내 `force_log_id`로 되돌려
보낸다. 오류 봉투에 실으면 그 값이 `details` 안쪽으로 밀려나고, 프론트엔드의 오류
정규화 경로를 타면서 "실패"로 표시된다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class SendMessageRequest(BaseModel):
    """`POST /rooms/{id}/messages` 요청 — W1.

    **`text`에 `max_length`를 걸지 않는다.** 걸면 상한 초과가 422가 되어 계획이 정한
    **400 `MESSAGE_TOO_LONG`** 이 사라진다. U4가 `friend_user_ids`에, U3이 빈 별칭에
    같은 판단을 했다 — 도메인 규칙의 위반은 서비스가 판정한다.

    `min_length=1`은 건다. 빈 문자열은 형식의 문제이지 도메인 규칙이 아니고, 빈
    메시지를 보내는 정상 경로가 없다.
    """

    text: Annotated[str, Field(min_length=1, description="메시지 본문. 트림하지 않는다")]

    force_log_id: Annotated[
        int | None,
        Field(default=None, ge=1, description="팝업에서 강행을 고른 경우의 판정 로그 id (BR-6.4)"),
    ] = None

    degraded: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "클라이언트가 degraded 상태인가 (ADR-007). 브라우저 탭 단위 상태라 "
                "서버가 알 수 없어 클라이언트가 알려준다"
            ),
        ),
    ] = False

    probe: Annotated[
        bool,
        Field(
            default=False,
            description=(
                "이번 전송이 프로브인가 (BR-8.5). degraded 중에도 5번째마다 한 번은 "
                "판정을 시도하며, 그 차례 판단은 클라이언트가 한다. 프로브 실패는 "
                "팝업 없이 201 `failed`로 끝난다"
            ),
        ),
    ] = False


class MessageOut(BaseModel):
    """저장된 메시지 하나. **WebSocket 프레임의 `message`와 같은 필드다.**

    두 경로의 모양이 다르면 클라이언트가 ID로 중복을 접을 때 나중 것이 앞의 것을
    덮으며 필드가 사라진다 (FR-3.3, FR-4.3).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    sender_id: int
    #: **정렬 기준이다.** `created_at`이 아니다 (FR-4.2, NFR-4).
    seq: int
    body: str
    #: 6값 중 하나. 클라이언트는 `failed`·`degraded`·`skipped_no_context`에만
    #: "검증 안 됨" 배지를 붙인다 (BR-8.6).
    verification_status: str
    #: `null`이면 신고되지 않은 상태다 (FR-11.3).
    misdirect_reported_at: datetime | None
    created_at: datetime


class HistoryMessageOut(MessageOut):
    """히스토리의 한 줄 — `MessageOut` + **호출자 기준** 발신자 표시명.

    표시명이 전송 응답에는 없고 여기에만 있는 이유 — 보는 사람마다 다른 값이라
    (내가 붙인 별칭, FR-2.4) 전원에게 같은 프레임을 보내는 브로드캐스트에는 담을 수
    없다. 조회는 호출자가 정해져 있어 담을 수 있다.
    """

    sender_display_name: str


class MessageListResponse(BaseModel):
    """`GET /rooms/{id}/messages`의 응답. **`seq` 내림차순이다** (BR-4.4).

    배열을 그대로 반환하지 않고 객체로 감싸는 이유는 U3·U4와 같다 — 나중에 필드를
    더할 때 최상위 타입이 바뀌면 프론트엔드가 깨진다.
    """

    messages: list[HistoryMessageOut]


class BlockedResponse(BaseModel):
    """409 두 종의 공통 본문. **`reason`이 판별자다.**

    | `reason` | 언제 | 클라이언트 |
    |---|---|---|
    | `inappropriate` | 부적절 판정 (BR-6.3) | `JudgeConfirmDialog` |
    | `judge_failed` | 판정 실패, degraded 아님 (BR-8.2) | `DegradedDialog` |

    **두 갈래가 같은 재요청 경로를 쓴다.** 사용자가 강행하면 받은 `log_id`를
    `force_log_id`로 실어 다시 보내고, 서버가 그 로그의 `verdict`로 상태를 정한다
    (`inappropriate` → `flagged_sent`, NULL → `failed`).

    **`score`는 부적절 판정에만 있다.** 판정 실패에 점수를 만들어 주면 클라이언트가
    그것을 판정으로 착각한다 — U2가 `Failed`에 `score` 필드를 두지 않은 것과 같다.
    """

    log_id: int
    reason: Literal["inappropriate", "judge_failed"]
    score: float | None = None


class ReportResponse(BaseModel):
    """신고·신고 취소의 응답. `null`이면 신고되지 않은 상태다 (BR-11.3)."""

    misdirect_reported_at: datetime | None


__all__ = [
    "BlockedResponse",
    "HistoryMessageOut",
    "MessageListResponse",
    "MessageOut",
    "ReportResponse",
    "SendMessageRequest",
]

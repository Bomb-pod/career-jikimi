"""`/rooms/{id}/messages`와 `/messages/{id}/report` — W1~W3의 HTTP 표면.

경로에 `/api` 접두사를 붙이지 않는다. `component-methods.md`가 접두사 없이 확정했다.

| 메서드 | 경로 | 응답 |
|---|---|---|
| POST | `/rooms/{id}/messages` | 201 / **409** inappropriate / **409** judge_failed / 400 / 403 |
| GET | `/rooms/{id}/messages` | 200 / 403 |
| POST | `/messages/{id}/report` | 200 / 403 |
| DELETE | `/messages/{id}/report` | 200 / 403 |

**두 409가 같은 재요청 경로를 쓴다.** 상태 코드를 나누면(예: 503) 클라이언트가
네트워크 오류와 헷갈린다 — 실패한 것은 판정이지 요청이 아니다.

전 엔드포인트가 `current_user` 의존성을 요구한다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import current_user
from app.core.db import get_session
from app.messages import history as history_service
from app.messages import report as report_service
from app.messages import service as send_service
from app.messages.constants import HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT, MESSAGE_MAX_LENGTH
from app.messages.schemas import (
    BlockedResponse,
    HistoryMessageOut,
    MessageListResponse,
    MessageOut,
    ReportResponse,
    SendMessageRequest,
)
from app.models import User

router = APIRouter(tags=["messages"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(current_user)]
RoomId = Annotated[int, Path(ge=1, description="`rooms.id`")]
MessageId = Annotated[int, Path(ge=1, description="`messages.id`")]

#: 참여자가 아닐 때의 응답 설명 (BR-3.3). U4의 같은 규칙과 문구를 맞춘다.
_ROOM_FORBIDDEN = {
    403: {
        "description": (
            "`FORBIDDEN` — 참여자가 아니거나 **존재하지 않는 방** (BR-3.3). "
            "404를 주지 않는 이유는 방 id의 존재 여부가 새기 때문이다"
        )
    }
}

_MESSAGE_FORBIDDEN = {
    403: {
        "description": (
            "`FORBIDDEN` — 남의 메시지이거나 **존재하지 않는 메시지** (BR-11.1). "
            "404를 주지 않는 이유는 메시지 id의 존재 여부가 새기 때문이다"
        )
    }
}


@router.post(
    "/rooms/{room_id}/messages",
    status_code=status.HTTP_201_CREATED,
    # 201과 409의 본문 모양이 달라 `response_model`을 하나로 고정할 수 없다.
    # 명시적 `None`이 없으면 FastAPI가 반환 애노테이션에서 모델을 추론해 409 본문을
    # 201 스키마로 검증하려 든다.
    response_model=None,
    summary="메시지 전송 (판정 → 채번 → 저장 → 브로드캐스트)",
    responses={
        201: {"model": MessageOut, "description": "저장·브로드캐스트 완료"},
        400: {
            "description": (
                f"`MESSAGE_TOO_LONG` — 본문이 {MESSAGE_MAX_LENGTH}자를 넘음 / "
                "`INVALID_FORCE_TOKEN` — `force_log_id`를 쓸 수 없음 (BR-6.9)"
            )
        },
        409: {
            "model": BlockedResponse,
            "description": (
                "**오류가 아니라 정상 분기다** (BR-6.3). `reason=inappropriate`는 "
                "부적절 판정, `reason=judge_failed`는 판정 실패. 둘 다 저장되지 "
                "않았으며, 강행하려면 받은 `log_id`를 `force_log_id`로 재요청한다. "
                "`ALREADY_RESOLVED`도 이 코드로 온다 (BR-7.1)"
            ),
        },
        **_ROOM_FORBIDDEN,
    },
)
async def send_message(
    payload: SendMessageRequest,
    session: SessionDep,
    caller: CurrentUser,
    room_id: RoomId,
) -> JSONResponse:
    """메시지를 보낸다 — W1의 9단계.

    **`JSONResponse`를 직접 만드는 이유** — 201과 409의 본문 모양이 다르고, 409는
    `{"error": {...}}` 봉투를 쓰지 않는다. 봉투에 실으면 `log_id`가 `details` 안쪽으로
    밀려나고 프론트엔드의 오류 정규화 경로를 타면서 정상 분기가 실패로 표시된다.
    """
    outcome = await send_service.send_message(
        session,
        caller.id,
        room_id,
        payload.text,
        force_log_id=payload.force_log_id,
        degraded=payload.degraded,
        probe=payload.probe,
    )

    if isinstance(outcome, send_service.Blocked):
        body = BlockedResponse(log_id=outcome.log_id, reason=outcome.reason, score=outcome.score)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=body.model_dump(mode="json"),
        )

    sent = MessageOut.model_validate(outcome.message)
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=sent.model_dump(mode="json"),
    )


@router.get(
    "/rooms/{room_id}/messages",
    response_model=MessageListResponse,
    summary="히스토리 (seq 커서 페이지네이션)",
    responses=_ROOM_FORBIDDEN,
)
async def list_messages(
    session: SessionDep,
    caller: CurrentUser,
    room_id: RoomId,
    before: Annotated[
        int | None,
        Query(ge=1, description="이 `seq`**보다 작은** 것만 (경계 미포함, BR-4.4)"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, description=f"최대 {HISTORY_MAX_LIMIT}개. 더 큰 값은 잘린다"),
    ] = HISTORY_DEFAULT_LIMIT,
) -> MessageListResponse:
    """그 방의 메시지를 `seq` 내림차순으로 — W2.

    **`before`는 경계를 포함하지 않는다.** 포함하면 페이지 경계에서 한 건이 중복된다.

    **빈 배열도 200이다** — 빈 방인 것과 커서가 처음을 지난 것은 오류가 아니다.
    """
    views = await history_service.list_messages(
        session, caller.id, room_id, before=before, limit=limit
    )
    return MessageListResponse(messages=[HistoryMessageOut.model_validate(view) for view in views])


@router.post(
    "/messages/{message_id}/report",
    response_model=ReportResponse,
    summary="오발송 신고",
    responses=_MESSAGE_FORBIDDEN,
)
async def report_message(
    session: SessionDep, caller: CurrentUser, message_id: MessageId
) -> ReportResponse:
    """내 메시지를 오발송으로 신고한다 — W3.

    **검증 상태와 무관하게 가능하다** (BR-11.2). 6값 어느 상태든 신고할 수 있으며,
    그것이 이 기능의 존재 이유다.
    """
    reported_at = await report_service.report(session, caller.id, message_id)
    return ReportResponse(misdirect_reported_at=reported_at)


@router.delete(
    "/messages/{message_id}/report",
    response_model=ReportResponse,
    summary="오발송 신고 취소",
    responses=_MESSAGE_FORBIDDEN,
)
async def unreport_message(
    session: SessionDep, caller: CurrentUser, message_id: MessageId
) -> ReportResponse:
    """신고를 취소한다 — `misdirect_reported_at`을 NULL로 (BR-11.3).

    **이력이 남지 않는다.** 취소하면 언제 신고했는지 알 수 없다.
    """
    await report_service.unreport(session, caller.id, message_id)
    return ReportResponse(misdirect_reported_at=None)


__all__ = ["router"]

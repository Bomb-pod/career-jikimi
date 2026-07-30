"""`/rooms*` 엔드포인트 — W1~W4.

경로에 `/api` 접두사를 붙이지 않는다. `component-methods.md`가 `GET /rooms/{id}`처럼
접두사 없이 확정했다.

전 엔드포인트가 `current_user` 의존성을 요구한다 — 방은 참여자만 접근한다(BR-3.3).
WebSocket 엔드포인트는 헤더를 쓸 수 없어 `ws.py`에 따로 있다 (FR-1.3, CON-4).

**`POST /rooms/{id}/members`와 `DELETE /rooms/{id}/members/me`가 없는 것은 누락이
아니다.** FR-10(Should)이 절단되었다 (`code-generation-plan.md` Step 7, 2026-07-30).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import current_user
from app.core.db import get_session
from app.models import User
from app.rooms import service
from app.rooms.schemas import (
    AiCheckRequest,
    AiCheckResponse,
    CreateRoomRequest,
    MarkReadRequest,
    MarkReadResponse,
    RoomDetailResponse,
    RoomListResponse,
    RoomSummaryOut,
)

router = APIRouter(tags=["rooms"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(current_user)]
RoomId = Annotated[int, Path(ge=1, description="`rooms.id`")]

#: 참여자가 아닐 때의 응답 설명. 세 엔드포인트가 같은 규칙을 쓴다 (BR-3.3).
_FORBIDDEN_RESPONSE = {
    403: {
        "description": (
            "`FORBIDDEN` — 참여자가 아니거나 **존재하지 않는 방** (BR-3.3). "
            "404를 주지 않는 이유는 방 id의 존재 여부가 새기 때문이다"
        )
    }
}


@router.post(
    "/rooms",
    response_model=RoomDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="친구를 초대해 방 생성",
    responses={
        400: {
            "description": (
                "`EMPTY_ROOM` — 초대 대상이 비어 있음 (BR-3.1) / "
                "`NOT_A_FRIEND` — 친구가 아닌 id가 섞임 (BR-3.2)"
            )
        }
    },
)
async def create_room(
    payload: CreateRoomRequest, session: SessionDep, caller: CurrentUser
) -> RoomDetailResponse:
    """방을 만든다 — W1. 본인은 자동으로 참여자가 된다 (FR-3.1).

    **응답이 `GET /rooms/{id}`와 같은 모양이다.** 만든 직후 화면이 그 방으로 바로
    들어갈 수 있고, 프론트엔드의 파싱 분기가 하나로 유지된다.
    """
    room = await service.create_room(session, caller.id, payload.friend_user_ids, payload.name)
    detail = await service.get_room_detail(session, caller.id, room.id)
    return RoomDetailResponse.model_validate(detail)


@router.get(
    "/rooms",
    response_model=RoomListResponse,
    summary="내 방 목록 (안 읽은 개수 포함)",
)
async def list_rooms(session: SessionDep, caller: CurrentUser) -> RoomListResponse:
    """내가 속한 방만 돌려준다 — W2 (BR-3.4).

    **빈 목록도 200이다.** 어떤 방에도 속하지 않은 것은 오류가 아니다.
    """
    summaries = await service.list_rooms(session, caller.id)
    return RoomListResponse(rooms=[RoomSummaryOut.model_validate(item) for item in summaries])


@router.get(
    "/rooms/{room_id}",
    response_model=RoomDetailResponse,
    summary="방 상세 (참여자 + 내 설정)",
    responses=_FORBIDDEN_RESPONSE,
)
async def get_room(session: SessionDep, caller: CurrentUser, room_id: RoomId) -> RoomDetailResponse:
    """방 정보와 참여자, **호출자 본인의** 토글·읽음 위치 — W3.

    다른 참여자의 `ai_check_enabled`는 담기지 않는다 (FR-6.1).
    """
    detail = await service.get_room_detail(session, caller.id, room_id)
    return RoomDetailResponse.model_validate(detail)


@router.post(
    "/rooms/{room_id}/read",
    response_model=MarkReadResponse,
    summary="읽음 위치 전진",
    responses=_FORBIDDEN_RESPONSE,
)
async def mark_read(
    payload: MarkReadRequest, session: SessionDep, caller: CurrentUser, room_id: RoomId
) -> MarkReadResponse:
    """`last_read_seq`를 전진시킨다 — W4.

    **전진하지 못해도 200이다** (BR-5.3). 요청 값이 현재 값 이하인 것은 순서가
    뒤바뀐 요청일 뿐 오류가 아니다 — 응답에는 현재 값이 담긴다.
    """
    last_read_seq = await service.mark_read(session, caller.id, room_id, payload.up_to_seq)
    return MarkReadResponse(last_read_seq=last_read_seq)


@router.patch(
    "/rooms/{room_id}/ai-check",
    response_model=AiCheckResponse,
    summary="내 AI 검증 토글 변경",
    responses=_FORBIDDEN_RESPONSE,
)
async def set_ai_check(
    payload: AiCheckRequest, session: SessionDep, caller: CurrentUser, room_id: RoomId
) -> AiCheckResponse:
    """**호출자 본인의** 검증 토글만 바꾼다 (BR-6.1).

    방장 개념이 없다 — 다른 참여자의 설정은 변하지 않는다.
    """
    enabled = await service.set_ai_check(session, caller.id, room_id, payload.enabled)
    return AiCheckResponse(ai_check_enabled=enabled)


__all__ = ["router"]

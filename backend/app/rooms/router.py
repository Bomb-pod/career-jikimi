"""`/rooms*` 엔드포인트 — W1~W4.

경로에 `/api` 접두사를 붙이지 않는다. `component-methods.md`가 `GET /rooms/{id}`처럼
접두사 없이 확정했다.

전 엔드포인트가 `current_user` 의존성을 요구한다 — 방은 참여자만 접근한다(BR-3.3).
WebSocket 엔드포인트는 헤더를 쓸 수 없어 `ws.py`에 따로 있다 (FR-1.3, CON-4).

**참여자 관리 두 엔드포인트는 2026-07-31에 복원되었다** (FR-10, Should). 2026-07-30에
일정 때문에 절단했다가(`code-generation-plan.md` Step 7) 절단 사유였던 U5 압박이
사라져 되살렸다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import current_user
from app.core.db import get_session
from app.models import User
from app.rooms import service
from app.rooms.schemas import (
    AddMemberRequest,
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


@router.post(
    "/rooms/{room_id}/members",
    response_model=RoomDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="기존 방에 친구 추가 (FR-10.1)",
    responses={
        400: {
            "description": (
                "`ALREADY_MEMBER` — 이미 참여 중 (BR-10.1) / "
                "`NOT_A_FRIEND` — 호출자의 친구가 아님 (BR-3.2)"
            )
        },
        **_FORBIDDEN_RESPONSE,
    },
)
async def add_member(
    payload: AddMemberRequest, session: SessionDep, caller: CurrentUser, room_id: RoomId
) -> RoomDetailResponse:
    """방에 친구 한 명을 추가한다 — FR-10.1.

    **응답이 `GET /rooms/{id}`와 같은 모양이다.** `POST /rooms`가 이미 그 규약이며,
    화면이 참여자 목록을 다시 부르지 않고 바로 갱신할 수 있다.

    **초대하는 사람도 참여자여야 한다** (BR-3.3). 방장 개념이 없으므로 참여자면
    누구나 초대할 수 있다 — `rooms.created_by`는 기록이지 권한이 아니다.
    """
    await service.add_member(session, caller.id, room_id, payload.friend_user_id)
    detail = await service.get_room_detail(session, caller.id, room_id)
    return RoomDetailResponse.model_validate(detail)


@router.delete(
    "/rooms/{room_id}/members/me",
    status_code=status.HTTP_204_NO_CONTENT,
    # **204에는 본문이 없다.** 두 인자를 다 적어야 한다 — `-> None` 반환 표기만으로는
    # FastAPI가 응답 모델을 만들어 두고 "204는 본문을 가질 수 없다"며 등록 시점에
    # 터진다. `response_class`는 그 위에서 JSON 직렬화 자체를 끈다.
    response_model=None,
    response_class=Response,
    summary="방에서 나가기 (FR-10.2)",
    responses=_FORBIDDEN_RESPONSE,
)
async def leave_room(session: SessionDep, caller: CurrentUser, room_id: RoomId) -> Response:
    """방에서 나간다 — FR-10.2.

    **경로가 `/members/me`다.** 남을 내보내는 기능은 없으며, 경로에 대상 id를 받지
    않는 것이 그 사실을 구조로 못박는다 — 받아두면 "본인만"이라는 검사를 어딘가에서
    빠뜨리는 날 남을 내보낼 수 있게 된다.

    **204다.** 돌려줄 방 상태가 없다 — 호출자는 방금 그 방에서 빠졌고, 상세를 주면
    참여자가 아닌 사람에게 방 내용을 주는 셈이 된다.
    """
    await service.leave_room(session, caller.id, room_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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

"""`/users/search`와 `/friends/*` 엔드포인트.

경로 접두사가 둘로 갈리므로(`/users`와 `/friends`) 라우터에 `prefix`를 두지 않고
전체 경로를 적는다. `component-methods.md`가 고정한 경로 그대로이며 `/api` 접두사를
붙이지 않는다.

세 엔드포인트 전부 `current_user` 의존성을 요구한다 — 남의 친구 목록을 볼 수 있는
경로를 만들지 않는다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.constants import USERNAME_MAX_LENGTH
from app.auth.schemas import UserOut
from app.auth.service import current_user
from app.core.db import get_session
from app.friends import service
from app.friends.schemas import (
    AddFriendRequest,
    FriendListResponse,
    FriendOut,
    SearchResponse,
    UpdateAliasRequest,
)
from app.models import Friendship, User

router = APIRouter(tags=["friends"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(current_user)]


def _to_out(friendship: Friendship) -> FriendOut:
    """`Friendship` 행을 응답 항목으로 바꾼다.

    `FriendOut`이 세 필드만 선언하므로 상대의 `display_name`이나 `username`이
    응답에 실릴 수 없다 (FR-2.4). 여기서 dict를 직접 만들지 않는 이유가 그것이다.
    """
    return FriendOut.model_validate(friendship)


@router.get(
    "/users/search",
    response_model=SearchResponse,
    summary="아이디 정확 일치 검색",
)
async def search_users(
    session: SessionDep,
    _caller: CurrentUser,
    username: Annotated[
        str,
        Query(
            min_length=1,
            max_length=USERNAME_MAX_LENGTH,
            description="찾을 아이디. 부분 일치·유사도 검색은 하지 않는다 (FR-2.1)",
        ),
    ],
) -> SearchResponse:
    """아이디가 정확히 일치하는 사용자 한 명을 찾는다 — W4.

    **없어도 200이고 `user`가 `null`이다** (BR-2.1). 404를 주지 않는다 — 검색은
    성공했고 결과가 비었을 뿐이다.

    쿼리 문자열을 트림하는 이유 — URL에 들어온 앞뒤 공백은 사용자가 화면에서 볼 수
    없다. 트림하지 않으면 `" alice"`가 결과 없음으로 나와 사용자가 원인을 알 수
    없다. 트림 후 빈 문자열이면 일치하는 아이디가 없어 `null`이 나간다 — 이것도
    BR-2.1의 정상 응답이다.
    """
    found = await service.search_user(session, username.strip())
    return SearchResponse(user=UserOut.model_validate(found) if found is not None else None)


@router.get(
    "/friends",
    response_model=FriendListResponse,
    summary="내 친구 목록",
)
async def list_friends(session: SessionDep, caller: CurrentUser) -> FriendListResponse:
    """내가 등록한 친구 목록. **별칭만 담긴다** (FR-2.4).

    단방향이므로(BR-2.3) 나를 등록한 사람은 여기에 없다.
    """
    friendships = await service.list_friends(session, caller.id)
    return FriendListResponse(friends=[_to_out(item) for item in friendships])


@router.post(
    "/friends",
    response_model=FriendOut,
    status_code=status.HTTP_201_CREATED,
    summary="친구 등록 (단방향, 별칭 필수)",
    responses={
        400: {
            "description": (
                "`ALIAS_REQUIRED` — 트림 후 빈 별칭 (BR-2.2) / "
                "`CANNOT_FRIEND_SELF` — 자기 자신 (BR-2.5)"
            )
        },
        404: {"description": "`USER_NOT_FOUND` — 대상 아이디가 없음 (BR-2.6)"},
        409: {"description": "`ALREADY_FRIEND` — 이미 등록된 상대 (BR-2.4)"},
    },
)
async def add_friend(
    payload: AddFriendRequest, session: SessionDep, caller: CurrentUser
) -> FriendOut:
    """상대를 내 친구 목록에 즉시 추가한다 — W5.

    승인 대기가 없고 상대의 목록은 변하지 않는다 (BR-2.3).
    """
    friendship = await service.add_friend(session, caller.id, payload.username, payload.alias)
    return _to_out(friendship)


@router.patch(
    "/friends/{friendship_id}",
    response_model=FriendOut,
    summary="별칭 수정",
    responses={
        400: {"description": "`ALIAS_REQUIRED` — 트림 후 빈 별칭. 기존 값 유지 (BR-2.2)"},
        403: {
            "description": (
                "`FORBIDDEN` — 남의 friendship이거나 **존재하지 않는 id** (BR-2.7). "
                "404를 주지 않는 이유는 id의 존재 여부가 새기 때문이다"
            )
        },
    },
)
async def update_alias(
    payload: UpdateAliasRequest,
    session: SessionDep,
    caller: CurrentUser,
    friendship_id: Annotated[int, Path(ge=1, description="`friendships.id`")],
) -> FriendOut:
    """별칭을 바꾼다 — W6.

    없는 id도 남의 id도 **403**이다 (BR-2.7).
    """
    friendship = await service.update_alias(session, caller.id, friendship_id, payload.alias)
    return _to_out(friendship)


__all__ = ["router"]

"""`friends`의 요청·응답 스키마.

**`FriendOut`에 상대의 `display_name`이 없는 것이 이 파일의 핵심이다** (FR-2.4).
친구 목록에 표시되는 것은 내가 붙인 별칭뿐이며, 응답 모델이 그것을 구조적으로
보장한다 — 서비스가 `Friendship`을 그대로 넘겨도 다른 값이 새지 않는다.

`username`도 넣지 않는다. FR-2.4의 수용 기준이 "상대가 스스로 설정한 이름은
어디에도 표시되지 않는다"이고, 목록 화면에는 별칭 외에 상대를 가리키는 문자열이
필요하지 않다. `friend_user_id`는 U4가 방을 만들 때 쓰는 식별자다.
"""

from __future__ import annotations

from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

from app.auth.schemas import Username, UserOut

#: `friendships.alias`의 VARCHAR(50)과 같은 값 (`domain-entities.md` § friendships).
ALIAS_MAX_LENGTH: Final[int] = 50

#: 별칭 입력 타입.
#:
#: **트림하지 않고 `min_length`도 걸지 않는다.** BR-2.2가 "없거나, 빈 문자열이거나,
#: 트림 후 빈 문자열"의 응답을 **400 `ALIAS_REQUIRED`** 로 정했다. pydantic 제약으로
#: 걸면 422가 나가고 그 오류 코드가 사라진다. 트림과 판정은 서비스가 한다.
#:
#: `max_length`만 거는 이유 — 51자 별칭이 DB까지 내려가면 드라이버 오류(500)가 된다.
#: 이것은 도메인 규칙이 아니라 컬럼 폭이라 형식 오류(422)로 거르는 것이 맞다.
Alias = Annotated[str, Field(max_length=ALIAS_MAX_LENGTH)]


class SearchResponse(BaseModel):
    """`GET /users/search`의 응답 — W4.

    **없어도 200이고 `user`가 `null`이다** (BR-2.1). 검색은 성공했고 결과가 비었을
    뿐이다. 등록(BR-2.6)이 404를 주는 것과 **의도적으로 다르다** — 검색은
    "찾아봤다"이고 등록은 "이 대상에 대해 작업하라"이기 때문이다.

    `{user: null}`을 빈 배열이 아니라 nullable 단일 값으로 두는 이유 — 정확 일치
    검색이라 결과는 0명 또는 1명뿐이다(FR-2.1). 배열로 두면 프론트엔드가 "여러 명이
    나올 수도 있나"를 매번 다시 판단하게 된다.
    """

    user: UserOut | None


class FriendOut(BaseModel):
    """친구 목록의 한 항목. **별칭만 담는다** (FR-2.4).

    `id`는 `friendships.id`다 — 별칭 수정(`PATCH /friends/{id}`)의 대상이다.
    `friend_user_id`는 `users.id`이며 U4가 방을 만들 때 참여자로 지정한다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    friend_user_id: int = Field(validation_alias="friend_id")
    alias: str


class FriendListResponse(BaseModel):
    """`GET /friends`의 응답.

    배열을 그대로 반환하지 않고 객체로 감싸는 이유 — 나중에 총 개수나 페이지 정보를
    붙일 때 최상위 타입이 바뀌면 프론트엔드가 깨진다. 지금 감싸두면 필드 추가로 끝난다.
    """

    friends: list[FriendOut]


class AddFriendRequest(BaseModel):
    """`POST /friends` 요청 — W5.

    `username`이 `auth.schemas.Username`인 이유 — 검색·등록·가입이 모두 같은
    `users.username` 컬럼을 가리킨다. 제약이 갈라지면 검색으로 찾은 아이디를
    등록에서 거부하는 상황이 생긴다.
    """

    username: Username
    alias: Alias


class UpdateAliasRequest(BaseModel):
    """`PATCH /friends/{id}` 요청 — W6."""

    alias: Alias


__all__ = [
    "ALIAS_MAX_LENGTH",
    "AddFriendRequest",
    "Alias",
    "FriendListResponse",
    "FriendOut",
    "SearchResponse",
    "UpdateAliasRequest",
]

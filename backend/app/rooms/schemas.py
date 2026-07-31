"""`rooms`의 요청·응답 스키마.

**응답에 다른 참여자의 `ai_check_enabled`가 없는 것이 이 파일의 핵심이다**
(FR-6.1, `business-logic-model.md` W3). AI 검증 토글은 개인 설정이며 남이 알 필요가
없다. `MemberOut`이 `user_id`와 `display_name` 두 필드만 선언하므로, 서비스가
`RoomMember` 행을 그대로 넘겨도 남의 토글 상태가 샐 수 없다.

표시명은 **`friends.resolve_display_names()`가 해석한 값**이다 (FR-2.4, BR-2.8).
`users.display_name`을 이 모듈이 직접 읽지 않는다 — 규칙이 두 벌이 되면 한 화면에서만
상대의 본명이 보이는 버그가 생긴다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

#: `rooms.name`의 VARCHAR(100)과 같은 값 (`domain-entities.md` § rooms).
ROOM_NAME_MAX_LENGTH: Final[int] = 100

#: 방 이름 입력 타입. **NULL을 허용한다** — 1:1 방에 이름을 강제하면 사용자가 매번
#: 지어야 하고, 비어 있으면 화면이 참여자 표시명으로 조립한다.
#:
#: `max_length`만 거는 이유는 U3의 `Alias`와 같다 — 101자가 DB까지 내려가면 드라이버
#: 오류(500)가 된다. 컬럼 폭은 도메인 규칙이 아니라 형식 제약이라 422가 맞다.
RoomName = Annotated[str, Field(max_length=ROOM_NAME_MAX_LENGTH)]


class CreateRoomRequest(BaseModel):
    """`POST /rooms` 요청 — W1.

    **`friend_user_ids`에 `min_length=1`을 걸지 않는다.** 걸면 빈 목록이 422가 되어
    BR-3.1의 **400 `EMPTY_ROOM`** 이 사라진다. FR-3.1의 수용 기준이 400을 요구하므로
    판정은 서비스가 한다. U3이 빈 별칭에 같은 판단을 했다.

    `name`을 주지 않으면 `None`이다 — 화면이 참여자 표시명으로 조립한다.
    """

    friend_user_ids: list[int]
    name: RoomName | None = None


class MemberOut(BaseModel):
    """방 참여자 한 명. **표시명만 담는다.**

    `ai_check_enabled`가 없는 것이 의도다 (FR-6.1) — 개인 설정이므로 남의 값을
    응답에 싣지 않는다. 필드를 선언하지 않으면 실수로 실릴 수 없다.

    `from_attributes`가 여기에도 필요하다 — 바깥 모델에만 붙이면 중첩된
    `RoomMemberView`(dataclass)가 dict가 아니라는 이유로 거부된다.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    display_name: str


class RoomSummaryOut(BaseModel):
    """방 목록의 한 항목 — W2.

    `unread_count`는 `room_members.last_read_seq`보다 큰 `seq`를 가진 메시지 수다
    (BR-5.1). 메시지가 없는 방은 0이다.

    `ai_check_enabled`는 **호출자 본인의 값**이다 (FR-6.1). 목록 쿼리가 이미 호출자의
    행과 조인하므로 따라오며, 화면이 방마다 상세를 다시 부르지 않아도 자기 토글을
    그릴 수 있다. 다른 참여자의 값은 `MemberOut`에 필드 자체가 없어 실릴 수 없다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    last_seq: int
    created_at: datetime
    unread_count: int
    last_read_seq: int
    ai_check_enabled: bool
    members: list[MemberOut]


class RoomListResponse(BaseModel):
    """`GET /rooms`의 응답.

    **빈 배열도 200이다** (BR-3.4). 어떤 방에도 속하지 않은 것은 오류가 아니다.

    배열을 그대로 반환하지 않고 객체로 감싸는 이유는 U3의 `FriendListResponse`와
    같다 — 나중에 필드를 더할 때 최상위 타입이 바뀌면 프론트엔드가 깨진다.
    """

    rooms: list[RoomSummaryOut]


class RoomDetailResponse(BaseModel):
    """`GET /rooms/{id}`와 `POST /rooms`의 응답 — W1·W3.

    `ai_check_enabled`와 `last_read_seq`는 **호출자 본인의 값**이다. 화면의 토글이
    이 값으로 그려진다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    last_seq: int
    created_at: datetime
    members: list[MemberOut]
    ai_check_enabled: bool
    last_read_seq: int


class MarkReadRequest(BaseModel):
    """`POST /rooms/{id}/read` 요청 — W4.

    `ge=0`만 거는 이유 — 음수 seq는 존재할 수 없으므로 형식 오류(422)다. 반대로
    "현재 값보다 작은 값"은 형식 오류가 아니라 **정상 요청**이며 무시된다(BR-5.3).
    그 판정을 여기서 할 수 없다(현재 값을 모른다).
    """

    up_to_seq: Annotated[int, Field(ge=0)]


class MarkReadResponse(BaseModel):
    """읽음 처리 후의 `last_read_seq`.

    **전진하지 못했어도 200이고, 그때는 기존 값이 그대로 담긴다** (BR-5.3).
    클라이언트가 이 값으로 자기 배지 상태를 맞출 수 있다.
    """

    last_read_seq: int


class AddMemberRequest(BaseModel):
    """`POST /rooms/{id}/members` 요청 — FR-10.1.

    **한 번에 한 명이다.** 목록을 받지 않는 이유는 오류 규약이 단수를 전제하기
    때문이다 — BR-10.1의 `ALREADY_MEMBER`와 BR-3.2의 `NOT_A_FRIEND`가 "어느
    대상이 문제인가"를 담지 않으므로(담으면 임의의 id로 관계를 탐색할 수 있다),
    여러 명을 받으면 사용자가 누구 때문에 거절됐는지 알 수 없다. `POST /rooms`가
    목록을 받는 것은 그쪽이 전부 아니면 전무이기 때문이고, 여기는 이미 있는 방에
    한 명씩 더하는 일이다.
    """

    friend_user_id: int


class AiCheckRequest(BaseModel):
    """`PATCH /rooms/{id}/ai-check` 요청."""

    enabled: bool


class AiCheckResponse(BaseModel):
    """토글 변경 후 **호출자 본인의** 값 (BR-6.1)."""

    ai_check_enabled: bool


__all__ = [
    "ROOM_NAME_MAX_LENGTH",
    "AddMemberRequest",
    "AiCheckRequest",
    "AiCheckResponse",
    "CreateRoomRequest",
    "MarkReadRequest",
    "MarkReadResponse",
    "MemberOut",
    "RoomDetailResponse",
    "RoomListResponse",
    "RoomName",
    "RoomSummaryOut",
]

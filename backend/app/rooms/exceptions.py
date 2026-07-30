"""`rooms`의 도메인 예외.

`friends/exceptions.py`와 같은 원리다 — U1의 `DomainError` 계열을 상속하면 단일
핸들러가 응답을 만든다. `code`가 클라이언트의 분기 키다.

응답 코드는 `business-rules.md`가 규칙별로 정한 값 그대로다. 여기서 새로 정하는
값은 없다.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import Forbidden, ValidationFailed


class EmptyRoom(ValidationFailed):
    """초대 대상이 비어 있다 — BR-3.1, 400.

    **pydantic의 `min_length=1`로 막지 않는 이유** — 그러면 422가 나가고 이 코드가
    사라진다. FR-3.1의 수용 기준이 "400을 반환하고 방은 생성되지 않는다"이므로
    판정은 서비스가 하고 응답 코드는 여기가 정한다. U3의 `AliasRequired`가 같은
    이유로 같은 모양이다.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "EMPTY_ROOM"


class NotAFriend(ValidationFailed):
    """초대 대상 중 호출자의 친구가 아닌 id가 섞였다 — BR-3.2, 400.

    **호출자 기준이다.** A가 만든 방에 A의 친구 B, C가 들어오면 B와 C는 서로 친구가
    아닐 수 있고 그것은 허용된다 — 그래서 참여자 표시명에 폴백이 필요하다(U3 BR-2.8).

    자기 자신을 참여자로 지정한 경우도 여기로 온다. 자기 자신은 자기 친구가 아니기
    때문이다(U3 BR-2.5가 자기 친구 등록을 막는다). 별도 코드를 만들지 않는 이유 —
    화면이 친구 목록에서 고르게 되어 있어 사용자가 도달할 수 있는 경로가 아니다.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "NOT_A_FRIEND"


class RoomForbidden(Forbidden):
    """호출자가 그 방의 참여자가 아니다 — BR-3.3, 403.

    **존재하지 않는 방도 403이다.** 404를 주면 방 id의 존재 여부가 새어나간다.
    `get_membership()`이 `None`을 주는 두 경우(방이 없음 / 참여자가 아님)를
    구분하지 않는 것이 이 예외의 목적이다. U3의 `FriendshipForbidden`(BR-2.7)이
    같은 판단을 먼저 했고 여기서 그 선례를 따른다.
    """

    code = "FORBIDDEN"


class AlreadyMember(ValidationFailed):
    """이미 참여 중인 사용자를 다시 추가했다 — BR-10.1, 400.

    **이 예외를 던지는 곳은 아직 없다.** 유일한 발생 지점인 `add_member()`가
    FR-10(Should)과 함께 절단되었기 때문이다
    (`code-generation-plan.md` Step 7, 2026-07-30). 규칙과 응답 코드는 이미
    확정되어 있으므로 자리를 남겨둔다 — FR-10을 되살릴 때 `service.add_member()`와
    라우터만 추가하면 되고 오류 규약을 다시 정하지 않는다.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "ALREADY_MEMBER"


__all__ = [
    "AlreadyMember",
    "EmptyRoom",
    "NotAFriend",
    "RoomForbidden",
]

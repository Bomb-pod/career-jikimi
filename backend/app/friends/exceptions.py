"""`friends`의 도메인 예외.

`auth/exceptions.py`와 같은 원리다 — U1의 `DomainError` 계열을 상속하면 단일
핸들러가 응답을 만든다. `code`가 클라이언트의 분기 키다.

응답 코드는 `business-rules.md`가 규칙별로 정한 값 그대로다. 여기서 새로 정하는
값은 없다.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import Conflict, Forbidden, NotFound, ValidationFailed


class AliasRequired(ValidationFailed):
    """별칭이 없거나 트림 후 빈 문자열이다 — BR-2.2, 400.

    `friendships.alias`의 NOT NULL은 `"   "`를 막지 못한다. 그 검사는 여기서만
    한다. 등록과 수정 양쪽에 쓰이며, 수정의 경우 **기존 값이 유지된다**(UPDATE를
    실행하기 전에 던지므로 자동으로 그렇게 된다).
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "ALIAS_REQUIRED"


class UserNotFound(NotFound):
    """등록 대상 `username`에 해당하는 사용자가 없다 — BR-2.6, 404.

    **검색(BR-2.1)은 빈 결과에 200을 준다.** 의도적으로 다르다 — 검색은 "찾아봤다"
    이고 등록은 "이 대상에 대해 작업하라"이기 때문이다. 두 규칙을 하나로 합치지
    않는다.
    """

    code = "USER_NOT_FOUND"


class AlreadyFriend(Conflict):
    """`(owner_id, friend_id)`가 이미 있다 — BR-2.4, 409.

    `UsernameTaken`과 같이 INSERT의 UNIQUE 위반을 변환한 것이다.
    """

    code = "ALREADY_FRIEND"


class CannotFriendSelf(ValidationFailed):
    """`friend_id == owner_id` — BR-2.5, 400.

    요구사항에 없던 상식 제약이며 Functional Design에서 추가했다. DB 제약으로
    표현하기 번거로워 애플리케이션이 막는다(`domain-entities.md` § 불변식).
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "CANNOT_FRIEND_SELF"


class FriendshipForbidden(Forbidden):
    """그 friendship이 없거나 남의 것이다 — BR-2.7, 403.

    **없는 id에도 404가 아니라 403을 준다.** 404를 주면 "그 id는 존재하지만
    네 것이 아니다"와 "그 id는 없다"가 구분되어, 남의 friendship id 존재 여부가
    새어나간다. 두 경우를 하나의 응답으로 덮는 것이 이 예외의 목적이다.
    """

    code = "FORBIDDEN"


__all__ = [
    "AliasRequired",
    "AlreadyFriend",
    "CannotFriendSelf",
    "FriendshipForbidden",
    "UserNotFound",
]

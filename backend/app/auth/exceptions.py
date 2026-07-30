"""`auth`의 도메인 예외.

전부 U1의 `core.errors.DomainError` 계열을 상속한다. 상속만 하면
`register_error_handlers()`가 이미 붙여둔 단일 핸들러가 상태 코드와 본문을
만든다 — 라우터에 `try/except`를 반복해 넣지 않는다
(`business-logic-model.md` § 오류 처리: "예외 → HTTP 상태 매핑을 한 곳에").

`code` 문자열은 **클라이언트의 분기 키**다. `message`는 사람이 읽는 문구이며
언제든 바뀔 수 있으므로 프론트엔드는 `code`로만 분기한다.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import Conflict, DomainError, ValidationFailed


class UsernameTaken(Conflict):
    """같은 `username`이 이미 있다 — BR-1.1, 409.

    사전 조회로 잡은 경우가 아니라 **INSERT의 UNIQUE 위반을 변환한 것**이다.
    이 단위는 사전 중복 조회를 하지 않는다 — 경쟁 조건에서 어차피 제약이 잡아야
    하고, 조회를 더해도 창을 좁힐 뿐이다.
    """

    code = "USERNAME_TAKEN"


class WeakPassword(ValidationFailed):
    """비밀번호가 최소 길이 미만이다 — BR-1.2, 400.

    U1의 `ValidationFailed`는 422이지만 `business-rules.md`가 이 규칙의 응답을
    **400**으로 못 박았으므로 상태 코드를 덮어쓴다. 의미(입력이 도메인 규칙 위반)는
    같아서 계층은 유지한다.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "WEAK_PASSWORD"


class InvalidCredentials(DomainError):
    """아이디가 없거나 비밀번호가 틀렸다 — BR-1.4, 401.

    **두 경우를 구분하지 않는다.** 상태·코드·문구가 모두 같아야 계정 존재 여부가
    새어나가지 않는다. 그래서 이 예외는 두 상황을 모두 표현하며, 호출자는 어느
    쪽인지 알 수 없는 하나의 문구만 넣는다.

    `DomainError`를 직접 상속하는 이유 — U1의 네 하위 클래스에 401이 없다.
    401은 "인증되지 않았다"이고 `Forbidden`(403)은 "인증됐지만 권한이 없다"라서
    그 둘을 겹치면 의미가 흐려진다.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_CREDENTIALS"


class InvalidToken(DomainError):
    """토큰의 서명·만료·형식이 잘못됐거나 가리키는 사용자가 없다 — BR-1.5, 401.

    HTTP 경로에서는 이 예외가 401로 나간다. WebSocket 경로(U4)는 이 예외를 잡아
    `auth_error` 프레임을 보내고 연결을 끊는다 — **같은 예외, 다른 표현**이다.
    그래서 `verify_token()`은 HTTPException을 던지지 않는다.
    """

    status_code = status.HTTP_401_UNAUTHORIZED
    code = "INVALID_TOKEN"


__all__ = [
    "InvalidCredentials",
    "InvalidToken",
    "UsernameTaken",
    "WeakPassword",
]

"""`messages`의 도메인 예외.

U1의 `DomainError` 계열을 상속하면 `register_error_handlers()`가 붙여둔 단일
핸들러가 상태 코드와 본문을 만든다. `code`가 클라이언트의 분기 키다.

**판정 관련 예외는 여기에 없다.** `InvalidForceToken`·`ForceTokenForbidden`·
`AlreadyResolved`는 U2가 소유하며(`app.judgment.exceptions`), 이 단위는 그대로
올려보낸다 — 같은 상황에 두 벌의 예외가 생기면 클라이언트가 분기할 코드가 둘이 된다.

**409 두 종도 여기에 없다.** 부적절 판정과 판정 실패는 오류가 아니라 정상 분기이며
(BR-6.3), `service.Blocked`라는 **반환값**으로 표현한다. 예외로 만들면 호출자가
정상 흐름을 `try/except`로 쓰게 되고 진짜 오류와 섞인다 — U2가 `Failed`를 반환값으로
둔 것과 같은 이유다.
"""

from __future__ import annotations

from fastapi import status

from app.core.errors import DomainError, Forbidden


class MessageTooLong(DomainError):
    """본문이 `MESSAGE_MAX_LENGTH`를 넘었다 — 400.

    **가장 싼 검사이므로 참여자 확인 바로 뒤에 온다** (Step 2). 판정도 채번도
    시작하기 전에 걸러야 한다 — 그러지 않으면 상한을 넘은 본문이 외부 API로
    나가고 `judgment_logs.candidate_text`에도 남는다.

    `ValidationFailed`(422)를 쓰지 않는 이유 — 계획이 400 `MESSAGE_TOO_LONG`을
    명시했고, 클라이언트가 `maxLength`로 이미 막으므로 여기 도달하는 것은 폼이
    아니라 API 직접 호출이다.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    code = "MESSAGE_TOO_LONG"


class MessageForbidden(Forbidden):
    """그 방 또는 그 메시지에 대한 권한이 없다 — 403 (BR-3.3, BR-11.1).

    **세 상황이 같은 403으로 모인다:**

    - 방의 참여자가 아니다 (BR-3.3)
    - 존재하지 않는 방이다 — `get_membership()`이 두 경우를 구분하지 않는다
    - 남의 메시지이거나 **존재하지 않는 메시지**다 (BR-11.1)

    **없는 것에 404를 주지 않는 이유** — 방 id와 메시지 id의 존재 여부가 새어나간다.
    U3의 `PATCH /friends/{id}`, U4의 `GET /rooms/{id}`, U2의 `PATCH /judgments/{id}`가
    모두 같은 판단을 했다.
    """

    code = "FORBIDDEN"


__all__ = [
    "MessageForbidden",
    "MessageTooLong",
]

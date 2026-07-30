"""`core/errors` — 도메인 예외 기반 클래스와 HTTP 상태 매핑.

U1은 **골격만** 만든다. U2~U5는 여기의 클래스를 상속해 자기 예외를 정의하면
라우터에 예외 처리 코드를 반복해 넣지 않아도 된다:

    # U3 auth
    class UsernameTaken(Conflict):
        code = "username_taken"

    raise UsernameTaken("이미 사용 중인 아이디입니다")
    # -> 409 {"error": {"code": "username_taken", "message": "..."}}

**매핑 테이블이 클래스 계층인 이유** — dict로 두면 예외를 정의한 곳과 상태 코드를
정한 곳이 갈라져, 새 예외를 만들고 등록을 잊으면 조용히 500이 된다.
상속으로 두면 등록을 잊을 수 없다.

**주의**: 여기 있는 것은 오류의 전달 형식뿐이다. 어떤 상황이 어떤 오류인지는
각 단위의 `business-rules.md`가 정한다. U1은 그 판단을 하지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """도메인 규칙 위반. 버그가 아니라 예상된 실패다.

    하위 클래스가 `status_code`와 `code`를 덮어쓴다. 직접 상속해서 쓰기보다
    아래 네 하위 클래스 중 의미가 맞는 것을 쓴다.

    Attributes:
        status_code: HTTP 상태 코드.
        code: 클라이언트가 분기에 쓸 기계 판독용 식별자. 사람이 읽는 문구는
            `message`이며, 그 문구는 언제든 바뀔 수 있으므로 프론트엔드는
            `code`로 분기해야 한다.
    """

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    code: str = "domain_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        """응답 본문. 모든 오류가 같은 모양이라 프론트엔드의 파싱 분기가 하나다."""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return {"error": payload}


class NotFound(DomainError):
    """대상이 없다."""

    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Forbidden(DomainError):
    """인증은 됐지만 그 대상에 대한 권한이 없다.

    예: 방 참여자가 아닌 사용자가 방 상세를 조회 (U4).
    """

    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class Conflict(DomainError):
    """현재 상태와 충돌한다.

    부적절 판정(409)도 이 갈래에 실린다 (ADR-001). 그것은 오류가 아니라
    정상 흐름의 한 갈래이므로, U5가 별도 응답 스키마를 쓸 수도 있다.
    """

    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class ValidationFailed(DomainError):
    """입력이 도메인 규칙을 어겼다.

    pydantic이 잡는 형식 오류(422)와 구별된다. 여기 오는 것은 형식은 맞지만
    규칙에 어긋나는 값이다 — 예: 공백만 있는 별칭 (BR-2.2).
    """

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    code = "validation_failed"


async def domain_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """`DomainError`를 그 클래스가 정한 상태 코드로 변환한다.

    시그니처의 타입이 `Exception`인 것은 Starlette의 핸들러 규약 때문이다.
    실제로는 `DomainError`만 이 핸들러로 들어온다.

    5xx만 스택트레이스를 남긴다 — 4xx는 예상된 실패이므로 트레이스를 남기면
    로그가 사용자 실수로 가득 차고, 정작 봐야 할 5xx가 묻힌다.
    """
    if not isinstance(exc, DomainError):  # pragma: no cover - 방어적 분기
        raise exc

    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("%s %s -> %s", request.method, request.url.path, exc.code, exc_info=exc)
    else:
        logger.info("%s %s -> %d %s", request.method, request.url.path, exc.status_code, exc.code)

    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


def register_error_handlers(app: FastAPI) -> None:
    """앱에 도메인 오류 핸들러를 등록한다. `main.py`가 한 번 호출한다."""
    app.add_exception_handler(DomainError, domain_error_handler)

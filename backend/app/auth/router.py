"""`/auth/*` 엔드포인트.

라우터는 **HTTP 관심사만** 다룬다 — 상태 코드, 응답 모델, 토큰 발급. 규칙 판정과
DB 접근은 `service.py`가 하고, 도메인 예외 → HTTP 상태 변환은 U1의
`register_error_handlers()`가 이미 붙여둔 단일 핸들러가 한다. 그래서 이 파일에
`try/except`가 없다.

경로에 `/api` 접두사를 붙이지 않는다 — `component-methods.md`가 `POST /auth/signup`
으로 확정했다.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import service
from app.auth.schemas import AuthResponse, LoginRequest, SignupRequest, UserOut
from app.auth.security import create_token
from app.auth.service import current_user
from app.core.db import get_session
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

#: 요청 단위 세션. 두 핸들러가 같은 표기를 쓰도록 별칭으로 둔다.
SessionDep = Annotated[AsyncSession, Depends(get_session)]

#: 인증된 호출자. `GET /auth/me`가 쓴다.
CurrentUserDep = Annotated[User, Depends(current_user)]


def _authenticated(user: User) -> AuthResponse:
    """사용자 하나로 `{token, user}` 응답을 만든다.

    **토큰 발급이 이 함수 하나에만 있다.** 회원가입과 로그인이 같은 응답을 주므로
    (자동 로그인, 계획 § 열린 항목) 두 곳에서 `create_token`을 부르면 한쪽만
    바뀌는 사고가 생긴다.

    `UserOut.model_validate`가 `password_hash`를 떨어뜨린다 — `UserOut`이 세 필드만
    선언했기 때문이다. 여기서 dict를 직접 만들지 않는 이유가 그것이다.
    """
    return AuthResponse(token=create_token(user.id), user=UserOut.model_validate(user))


@router.post(
    "/signup",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="회원가입",
    responses={
        400: {"description": "`WEAK_PASSWORD` — 비밀번호가 최소 길이 미만 (BR-1.2)"},
        409: {"description": "`USERNAME_TAKEN` — 아이디 중복 (BR-1.1)"},
    },
)
async def signup(payload: SignupRequest, session: SessionDep) -> AuthResponse:
    """계정을 만들고 **곧바로 토큰을 준다** — W1 + 자동 로그인.

    방금 만든 자격증명으로 다시 로그인하게 만들 이유가 없어 응답에 토큰을 실었다.
    프론트엔드는 로그인 성공과 같은 경로로 그 토큰을 저장한다.
    """
    user = await service.signup(session, payload.username, payload.password)
    return _authenticated(user)


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="로그인",
    responses={
        401: {
            "description": (
                "`INVALID_CREDENTIALS` — 아이디가 없거나 비밀번호가 틀림. "
                "**두 경우를 구분하지 않는다** (BR-1.4)"
            )
        },
    },
)
async def login(payload: LoginRequest, session: SessionDep) -> AuthResponse:
    """자격증명을 검증해 토큰을 준다 — W2.

    실패는 401 `INVALID_CREDENTIALS` 하나뿐이다. 프론트엔드는 이 응답의 `message`를
    그대로 보여준다 — "아이디가 없습니다"로 바꾸면 BR-1.4의 비구분이 UI에서 깨진다.
    """
    user = await service.login(session, payload.username, payload.password)
    return _authenticated(user)


@router.get(
    "/me",
    response_model=UserOut,
    summary="현재 사용자",
    responses={
        401: {"description": "토큰이 없거나 유효하지 않음 (BR-1.5)"},
    },
)
async def me(user: CurrentUserDep) -> UserOut:
    """토큰이 가리키는 사용자를 돌려준다.

    **왜 필요한가** — 프론트엔드는 토큰만 `localStorage`에 남긴다(FR-1.2에 리프레시
    토큰이 없으므로 사용자 객체를 저장할 이유도 없다). 그래서 새로고침 후에는 토큰은
    유효한데 "내가 누구인지"를 모르는 상태가 된다. 이 엔드포인트가 그 한 조각을
    복구한다.

    `component-methods.md`에 없던 표면이다. U4·U5의 `code-summary.md`가 둘 다
    "화면이 현재 사용자 이름을 보여주려면 `GET /auth/me`가 필요하다"로 남겨둔
    항목이며, 프론트엔드를 마무리하면서 그 필요가 실제로 발생했다.

    **새 토큰을 발급하지 않는다.** 토큰 갱신은 FR-1.2가 범위 밖으로 정했다 —
    여기서 갱신하면 사실상 무기한 세션이 되어 그 결정이 뒤집힌다.
    """
    return UserOut.model_validate(user)


__all__ = ["router"]

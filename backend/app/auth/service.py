"""회원가입·로그인·현재 사용자 해석 — W1·W2·W3의 구현.

`security.py`가 암호 계층이고 이 모듈이 **DB와 닿는 계층**이다. 라우터는 여기를
호출하고 HTTP 관심사(상태 코드·헤더)만 다룬다.

대응: FR-1.1, FR-1.2, FR-1.3, BR-1.1, BR-1.2, BR-1.4, BR-1.5.
"""

from __future__ import annotations

import logging
from typing import Annotated

import sqlalchemy as sa
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.constants import PASSWORD_MIN_LENGTH
from app.auth.exceptions import (
    InvalidCredentials,
    InvalidToken,
    UsernameTaken,
    WeakPassword,
)
from app.auth.security import DUMMY_HASH, hash_password, verify_password, verify_token
from app.core.db import get_session
from app.models import User

logger = logging.getLogger(__name__)

#: OpenAPI(`/docs`)에 Authorize 버튼을 만들고 `Authorization` 헤더를 파싱한다.
#:
#: **`auto_error=False`가 핵심이다.** 기본값(True)이면 헤더가 없을 때 FastAPI가
#: **403**을 낸다. BR-1.5는 **401**을 요구한다 — 403은 "인증됐지만 권한이 없다"이고
#: 여기는 "인증되지 않았다"다. False로 두고 `None`을 받아 우리 예외로 바꾼다.
_bearer = HTTPBearer(auto_error=False, description="로그인으로 받은 JWT")


async def signup(session: AsyncSession, username: str, password: str) -> User:
    """계정을 만든다 — W1.

    Args:
        session: 요청 단위 세션. 커밋은 `get_session()`이 한다.
        username: 트림된 아이디 (스키마가 트림한다).
        password: 원문 비밀번호.

    Returns:
        `id`가 채워진 `User`. 호출자가 토큰을 발급한다.

    Raises:
        WeakPassword: 8자 미만 (BR-1.2, 400).
        UsernameTaken: 아이디 중복 (BR-1.1, 409).

    **순서가 W1 그대로다** — 길이 검사, 해싱, INSERT.

    **해싱을 INSERT 앞(트랜잭션 밖)에 두는 이유** — argon2는 의도적으로 느리다
    (수십~수백 ms). INSERT 뒤에 두면 그 시간 동안 DB 트랜잭션이 열려 있어 커넥션을
    붙들고 있다. 해싱은 DB와 무관하므로 밖에서 끝낸다.

    **사전 중복 조회를 하지 않는다.** 두 요청이 동시에 들어오면 사전 조회는 둘 다
    통과하고, 결국 UNIQUE 제약이 잡아야 한다. 조회를 더해도 창을 좁힐 뿐 없애지
    못하므로, 조회 한 번을 아끼고 무결성 위반을 409로 변환하는 쪽이 정직하다
    (BR-1.1).
    """
    _require_strong_password(password)

    user = User(
        username=username,
        # `display_name`의 초기값은 `username` 복사다 — 표시명 변경 기능이
        # 요구사항에 없어 별도 입력칸은 순수 비용이다
        # (`domain-entities.md`의 열린 항목, 계획에서 확정).
        display_name=username,
        password_hash=hash_password(password),
    )
    session.add(user)
    try:
        # `flush()`가 INSERT를 보내 `user.id`를 채운다. **여기가 UNIQUE 위반이
        # 드러나는 지점이다** — 커밋까지 미루면 예외가 `get_session()` 안에서
        # 터져 라우터가 잡을 수 없고, 그러면 DB 방언 예외가 500으로 나간다.
        await session.flush()
    except IntegrityError as exc:
        # 무결성 위반을 **서비스 계층에서** 도메인 예외로 바꾼다
        # (`business-logic-model.md` § 오류 처리). 라우터까지 올려보내면 DB 방언이
        # HTTP 계층에 새고, MariaDB를 다른 것으로 바꾸면 라우터가 깨진다.
        #
        # 실패한 flush 뒤의 세션은 롤백 없이는 쓸 수 없다. `get_session()`도
        # 롤백하지만 여기서 먼저 되돌려 이 함수가 남기는 상태를 스스로 정리한다.
        await session.rollback()
        raise UsernameTaken("이미 사용 중인 아이디입니다") from exc

    logger.info("계정을 생성했습니다 (id=%s)", user.id)
    return user


async def login(session: AsyncSession, username: str, password: str) -> User:
    """자격증명을 검증해 사용자를 돌려준다 — W2.

    Args:
        session: 요청 단위 세션.
        username: 트림된 아이디.
        password: 원문 비밀번호.

    Returns:
        검증된 `User`. **토큰 발급은 호출자(라우터)가 한다.**

    Raises:
        InvalidCredentials: 아이디가 없거나 비밀번호가 틀림 (BR-1.4, 401).

    **`component-methods.md`의 `login() -> str`(JWT)와 다른 반환값이다.** 응답이
    `{token, user}` 두 필드를 담기로 확정되었고(자동 로그인, 계획 § 열린 항목),
    토큰만 돌려주면 라우터가 사용자를 다시 SELECT해야 한다 — 이미 손에 든 행을
    한 번 더 읽는 것이다. 회원가입과 반환 모양을 맞춰 토큰 발급을 라우터 한 곳에
    모으는 편이 낫다.

    **BR-1.4의 비구분이 이 함수의 전부다.** 아이디가 없는 경우와 비밀번호가 틀린
    경우가 같은 상태·같은 코드·같은 문구로 나가고, **응답 시간까지 같다** —
    아이디가 없을 때도 `DUMMY_HASH`를 한 번 검증해 argon2의 수십~수백 ms를 똑같이
    소비한다. 이것이 없으면 본문이 같아도 시간 차이로 계정 존재 여부를 알 수 있다.
    """
    user = await _find_by_username(session, username)

    if user is None:
        # **더미 검증**. 결과를 쓰지 않는다 — 목적은 시간을 쓰는 것이다.
        # `DUMMY_HASH`는 어떤 계정의 비밀번호도 아니므로 이 검증은 반드시 실패한다.
        verify_password(password, DUMMY_HASH)
        raise InvalidCredentials("아이디 또는 비밀번호가 올바르지 않습니다")

    if not verify_password(password, user.password_hash):
        # 위와 **같은 문구, 같은 코드, 같은 상태**다. 하나만 바꾸면 BR-1.4가 깨진다.
        raise InvalidCredentials("아이디 또는 비밀번호가 올바르지 않습니다")

    return user


async def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """`Authorization: Bearer` 헤더를 검증해 사용자를 돌려주는 FastAPI 의존성 — W3 경로 A.

    Raises:
        InvalidToken: 헤더가 없거나 형식이 잘못됐거나 토큰이 유효하지 않거나
            토큰이 가리키는 사용자가 없다 (BR-1.5, 401).

    **`verify_token()`을 감싸는 얇은 껍데기다.** 검증 자체는 그 동기 함수가 하고
    여기서는 헤더 파싱과 사용자 조회만 한다. U4의 WebSocket 경로는 이 의존성을
    쓰지 않고 `verify_token()`을 직접 부른다 — 브라우저가 WebSocket에 커스텀 헤더를
    붙일 수 없어서다(CON-4, FR-1.3).

    토큰이 가리키는 사용자가 없는 경우를 401로 다룬다(BR-1.5). 이 프로젝트에
    탈퇴가 없어 실제로는 일어나지 않지만, 서명이 유효한 토큰이 없는 사용자를
    가리키면 그것은 키가 유출됐거나 DB가 초기화된 상황이다 — 어느 쪽이든 통과시킬
    수 없다.
    """
    if credentials is None:
        # 헤더가 없거나 `Bearer`가 아니다. `HTTPBearer(auto_error=False)`가 두 경우를
        # 모두 None으로 준다 — 구분해 알려줄 이유가 없다.
        raise InvalidToken("인증이 필요합니다")

    user_id = verify_token(credentials.credentials)

    user = await session.get(User, user_id)
    if user is None:
        logger.warning("유효한 토큰이 없는 사용자를 가리킵니다 (user_id=%s)", user_id)
        raise InvalidToken("토큰이 유효하지 않습니다")
    return user


# --------------------------------------------------------------------------
# 내부 헬퍼
# --------------------------------------------------------------------------
def _require_strong_password(password: str) -> None:
    """BR-1.2를 판정한다. 통과하면 아무것도 하지 않는다.

    **상한을 검사하지 않는다** — BR-1.2가 "상한은 두지 않는다"로 정했고, argon2를
    고른 것이 그 결정의 결과다(bcrypt라면 72바이트에서 조용히 잘렸다).

    문구에 `PASSWORD_MIN_LENGTH`를 끼워 넣는 이유 — 상수를 바꿨을 때 문구가 함께
    따라오지 않으면 "8자 이상"이라고 말하면서 12자를 요구하는 응답이 나간다.
    프론트엔드는 이 문구를 그대로 보여주고 자기 문구를 만들지 않는다.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        raise WeakPassword(f"비밀번호는 {PASSWORD_MIN_LENGTH}자 이상이어야 합니다")


async def _find_by_username(session: AsyncSession, username: str) -> User | None:
    """아이디로 사용자를 찾는다. 없으면 `None`.

    **MariaDB의 `utf8mb4_unicode_ci`는 대소문자를 구분하지 않는다.** `Alice`로
    조회해도 `alice`가 나온다. `business-rules.md`가 이것을 "일관되므로 그대로
    둔다"로 닫았다 — 유일성(BR-1.1)과 검색(BR-2.1)이 같은 콜레이션을 따르므로
    `Alice`와 `alice`가 동시에 가입할 수도 없다.
    """
    result = await session.execute(sa.select(User).where(User.username == username))
    return result.scalar_one_or_none()


__all__ = ["current_user", "login", "signup"]

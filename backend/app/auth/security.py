"""비밀번호 해싱과 JWT — `auth`의 순수 암호 계층.

**이 모듈은 DB도 FastAPI도 모른다.** 세션을 받지 않고 요청 객체를 보지 않는다.
그래서 `verify_token()`이 HTTP와 WebSocket 양쪽에서 같은 코드로 쓰인다
(FR-1.3, BR-1.5).

대응: FR-1.1, FR-1.2, FR-1.3, BR-1.3, BR-1.4, BR-1.5, BR-1.6.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.auth.exceptions import InvalidToken
from app.core.config import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 비밀번호 해싱 — argon2id (BR-1.3)
# --------------------------------------------------------------------------
#: `argon2-cffi`의 기본 파라미터를 그대로 쓴다.
#:
#: **argon2를 고른 이유** (code-generation-questions.md Q1a, 사람이 답했다) —
#: BR-1.2가 "비밀번호 상한은 두지 않는다"고 정했는데 bcrypt는 72바이트를 넘으면
#: **조용히 잘라낸다.** 한글은 한 글자가 3바이트라 25글자 비밀번호를 만든 사용자가
#: 실제로는 앞 24글자로만 로그인되며 본인은 그 사실을 알 수 없다. argon2에는 그
#: 제약이 없어 규칙과 구현이 일치한다.
#:
#: 기본값을 조정하지 않는 이유 — argon2-cffi의 기본값은 RFC 9106의 권장 프로파일에
#: 맞춰 유지되는 값이다. 근거 없이 낮추면 안전성이 내려가고, 근거 없이 올리면
#: 로그인 지연만 늘어난다. 이 데모에는 조정할 근거가 없다.
_hasher: Final[PasswordHasher] = PasswordHasher()

#: 아이디가 없을 때도 검증을 한 번 돌리기 위한 더미 해시 — **BR-1.4의 응답 시간
#: 균일화**다.
#:
#: 이것이 없으면 "없는 아이디"는 SELECT 한 번에 즉시 401이 나가고 "틀린 비밀번호"는
#: argon2 검증(수십~수백 ms)을 거친 뒤 401이 나간다. 응답 본문이 같아도 **시간이
#: 다르면 계정 존재 여부를 알 수 있다.** 더미 해시를 한 번 검증해 그 차이를 없앤다.
#:
#: 모듈 import 시점에 실제로 해싱해 만든다 — 리터럴 해시를 소스에 두면 FR-1.4의
#: "소스 코드에 비밀 리터럴이 없다"를 훑는 검사에 걸리고, 무엇보다 그 리터럴이
#: 무슨 비밀번호의 해시인지 아무도 모르게 된다. 여기서 만들면 원본이 아래
#: 문자열이라는 것이 코드에 드러난다 — 이 값은 **비밀이 아니다.** 어떤 계정의
#: 비밀번호도 아니며, 검증은 반드시 실패한다.
DUMMY_HASH: Final[str] = _hasher.hash("argon2-timing-equalizer-not-a-credential")


def hash_password(raw_password: str) -> str:
    """비밀번호를 argon2id 해시로 바꾼다.

    같은 입력이라도 매번 다른 해시가 나온다 — 솔트가 해시 문자열에 포함되기
    때문이다. 그래서 해시를 비교해 비밀번호가 같은지 알 수 없고, 그것이 의도다.

    **길이 검사를 하지 않는다.** BR-1.2의 판정은 `service.signup()`이 하며, 이
    함수는 받은 것을 그대로 해싱한다. 검사를 두 곳에 두면 어느 쪽이 진실인지
    모르게 된다.
    """
    return _hasher.hash(raw_password)


def verify_password(raw_password: str, password_hash: str) -> bool:
    """비밀번호가 해시와 맞는지 검사한다. 예외를 던지지 않고 불리언만 준다.

    argon2-cffi는 불일치를 `VerifyMismatchError` 예외로 알린다. 여기서 불리언으로
    바꾸는 이유 — 호출자(`login()`)는 "맞다/틀리다"만 알면 되고, 예외를 그대로
    올리면 호출자가 argon2의 예외 종류를 알아야 한다.

    `InvalidHashError`는 DB의 `password_hash`가 argon2 형식이 아닐 때 나온다
    (예: U1의 스키마 테스트가 넣은 `"not-a-real-hash"`). 그 경우도 False다 —
    **조용히 통과시키지 않는다.** 다만 이것은 데이터 이상이므로 경고를 남긴다.
    """
    try:
        return _hasher.verify(password_hash, raw_password)
    except VerifyMismatchError:
        return False
    except InvalidHashError:
        # 저장된 해시가 argon2 형식이 아니다 — 데이터 이상이지 사용자 실수가 아니다.
        # 비밀번호 원문은 절대 로그에 남기지 않는다.
        logger.warning("저장된 password_hash가 argon2 형식이 아닙니다")
        return False
    except VerificationError:
        # argon2의 그 밖의 검증 실패(손상된 해시 등). 위와 같이 실패로 다룬다.
        logger.warning("password_hash 검증에 실패했습니다", exc_info=True)
        return False


# --------------------------------------------------------------------------
# JWT (FR-1.2)
# --------------------------------------------------------------------------
def create_token(user_id: int) -> str:
    """`sub`와 `exp`만 담은 JWT를 발급한다.

    **사용자명·표시명을 넣지 않는다**(`business-logic-model.md` W2). 바뀔 수 있는
    값을 토큰에 넣으면 토큰이 낡는다 — 리프레시가 없어(FR-1.2) 만료까지 최대
    24시간 동안 낡은 값이 돌아다닌다.

    `sub`를 문자열로 넣는 이유 — RFC 7519가 `sub`를 StringOrURI로 정의하고,
    PyJWT 2.10부터 정수 `sub`를 거부한다. 되돌릴 때 `int()`로 바꾼다.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(
        payload,
        # BR-1.6: 서명 키는 `core/config`를 통해서만 읽는다. `SecretStr`이라
        # 꺼낼 때 `.get_secret_value()`가 필요하다 — 로그·repr에 값이 찍히지
        # 않게 하는 U1의 장치다.
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def verify_token(token: str) -> int:
    """토큰을 검증해 `user_id`를 돌려준다. **동기 순수 함수다.**

    Args:
        token: 원본 JWT 문자열. `Bearer ` 접두사는 붙어 있지 않아야 한다.

    Returns:
        토큰의 `sub` 클레임(사용자 id).

    Raises:
        InvalidToken: 서명 불일치, 만료, 형식 오류, `sub` 누락·비정수.

    **FastAPI 의존성이 아닌 것이 이 함수의 계약이다**(FR-1.3, BR-1.5).
    WebSocket 핸들러는 HTTP 헤더를 받지 않으므로 브라우저가 첫 프레임으로 토큰을
    보낸다(CON-4). 의존성으로 만들면 U4가 재사용할 수 없어 검증 로직이 두 벌이
    되고, 두 벌은 반드시 어긋난다.

    **`HTTPException`을 던지지 않는 것도 같은 이유다.** HTTP 경로에서는
    `current_user()`가 이 예외를 401로 바꾸고, WebSocket 경로에서는 U4가 잡아
    `auth_error` 프레임을 보낸다 — 표현은 호출자가 정한다.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
            # `sub`가 없는 토큰을 형식 오류로 잡는다. 이것이 없으면 아래 `get`이
            # None을 받고, 그 None이 어디까지 흘러갈지 알 수 없다.
            options={"require": ["sub", "exp"]},
        )
    except jwt.InvalidTokenError as exc:
        # PyJWT의 모든 검증 실패(ExpiredSignature·InvalidSignature·DecodeError·
        # MissingRequiredClaim)가 이 하나를 상속한다. **각각을 구분하지 않는다** —
        # "만료됨"과 "위조됨"을 나눠 알려줄 이유가 없다.
        raise InvalidToken("토큰이 유효하지 않습니다") from exc

    subject = payload.get("sub")
    try:
        return int(subject)
    except (TypeError, ValueError) as exc:
        # `sub`가 있지만 정수로 읽을 수 없다 — 다른 시스템이 발급한 토큰이거나
        # 우리 형식이 바뀌었다. 어느 쪽이든 이 앱에서는 유효하지 않다.
        raise InvalidToken("토큰이 유효하지 않습니다") from exc


__all__ = [
    "DUMMY_HASH",
    "create_token",
    "hash_password",
    "verify_password",
    "verify_token",
]

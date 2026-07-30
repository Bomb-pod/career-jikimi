"""`auth`의 요청·응답 스키마.

**`password_hash`가 어떤 응답 모델에도 없는 것이 이 파일의 핵심이다**
(`domain-entities.md` § users 불변식). `UserOut`이 세 필드만 선언하므로, 서비스가
`User` 인스턴스를 그대로 넘겨도 직렬화에서 해시가 빠진다 — 규율이 아니라 구조가
막는다. 응답 모델을 거치지 않고 dict를 직접 반환하는 핸들러를 만들지 않는다.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.auth.constants import USERNAME_MAX_LENGTH

#: 아이디 입력 타입. `friends`의 스키마도 이것을 쓴다 — 검색·등록의 대상 아이디가
#: 같은 컬럼을 가리키므로 제약이 갈라지면 안 된다.
#:
#: **앞뒤 공백을 제거하는 이유** — `" alice"`를 그대로 저장하면 아이디 유일성
#: (BR-1.1)과 정확 일치 검색(BR-2.1)이 사용자가 예상하지 못하는 방식으로 갈라진다.
#: 사용자는 자기가 공백을 넣었다는 것을 화면에서 볼 수 없다.
#: 트림 후 빈 값은 pydantic이 422로 거른다 — 도메인 규칙 위반이 아니라 형식 오류다.
#:
#: `max_length`가 `users.username`의 VARCHAR(50)과 같아야 한다. 크면 51자 입력이
#: DB까지 내려가 드라이버 오류(500)가 된다.
Username = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=USERNAME_MAX_LENGTH),
]

#: 비밀번호 입력 타입. **트림하지 않고 최소 길이도 걸지 않는다.**
#:
#: 트림하지 않는 이유 — 공백은 비밀번호의 일부다. 여기서 지우면 사용자가 만든
#: 비밀번호와 저장된 비밀번호가 달라진다.
#:
#: 최소 길이를 pydantic에 걸지 않는 이유 — BR-1.2가 8자 미만의 응답을 **400
#: `WEAK_PASSWORD`** 로 정했다. pydantic 제약으로 걸면 422가 나가고 오류 코드가
#: 사라진다. 판정은 `service.signup()`이 한다.
#:
#: **상한도 걸지 않는다** (BR-1.2: "상한은 두지 않는다"). argon2는 bcrypt의
#: 72바이트 절단이 없으므로 긴 비밀번호가 조용히 잘리지 않는다.
#:
#: 제약이 하나도 없어 `str` 그대로지만, 이름을 붙여두면 "여기에 제약을 걸지
#: 않은 것이 결정이다"가 코드에 남는다.
Password = str


class SignupRequest(BaseModel):
    """`POST /auth/signup` 요청."""

    username: Username
    password: Password


class LoginRequest(BaseModel):
    """`POST /auth/login` 요청.

    `SignupRequest`와 필드가 같지만 합치지 않는다 — 회원가입의 비밀번호는 규칙
    검사를 받고 로그인의 비밀번호는 받지 않는다. 한 모델로 합치면 나중에 한쪽에만
    제약을 붙일 때 다른 쪽이 조용히 따라간다.
    """

    username: Username
    password: Password


class UserOut(BaseModel):
    """응답에 실리는 사용자. **`password_hash`가 없다** (FR-1.1, NFR-6).

    `display_name`을 담는 이유 — W4(사용자 검색)의 SELECT 목록에 있다. 다만
    **친구 목록에는 이 모델을 쓰지 않는다** (FR-2.4). 친구 목록 전용 모델은
    `friends/schemas.py`의 `FriendOut`이며 그쪽에는 `display_name`이 없다.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str


class AuthResponse(BaseModel):
    """`POST /auth/signup`과 `POST /auth/login`의 공통 응답.

    **회원가입도 토큰을 함께 준다** — 방금 만든 자격증명으로 다시 로그인하게 만들
    이유가 없어 자동 로그인으로 정했다(`code-generation-plan.md` § 이 계획이 닫는
    열린 항목). 두 응답이 같은 모양이라 프론트엔드의 성공 처리 분기가 하나다.
    """

    token: str
    user: UserOut


__all__ = [
    "AuthResponse",
    "LoginRequest",
    "Password",
    "SignupRequest",
    "UserOut",
    "Username",
]

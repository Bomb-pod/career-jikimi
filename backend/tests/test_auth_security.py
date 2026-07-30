"""`auth/security.py` — 해싱과 JWT의 단위 테스트.

**DB가 필요 없다.** 이 모듈은 순수 함수뿐이라 실제 MariaDB 없이도 전부 돈다.

대응: FR-1.1, FR-1.2, FR-1.3, BR-1.3, BR-1.4, BR-1.5.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.exceptions import InvalidToken
from app.auth.security import (
    DUMMY_HASH,
    create_token,
    hash_password,
    verify_password,
    verify_token,
)
from app.core.config import settings

PASSWORD = "pw123456"


# --------------------------------------------------------------------------
# 해싱 (FR-1.1, BR-1.3)
# --------------------------------------------------------------------------
def test_hash_round_trip() -> None:
    """해싱한 비밀번호는 그 원문으로 검증된다."""
    stored = hash_password(PASSWORD)

    assert verify_password(PASSWORD, stored) is True


def test_hash_is_not_the_plaintext() -> None:
    """저장 형태가 평문과 다르다 — FR-1.1의 수용 기준 그대로.

    Then DB의 password 컬럼은 평문 "pw123456"과 일치하지 않는다
    """
    stored = hash_password(PASSWORD)

    assert stored != PASSWORD
    assert PASSWORD not in stored
    # argon2id임을 형식으로 확인한다. bcrypt로 되돌아가면 이 접두사가 `$2b$`가 된다.
    assert stored.startswith("$argon2id$")


def test_wrong_password_does_not_verify() -> None:
    """틀린 비밀번호는 False다. 예외를 던지지 않는다 — 호출자는 불리언만 본다."""
    stored = hash_password(PASSWORD)

    assert verify_password("pw123457", stored) is False


def test_same_password_hashes_differently_every_time() -> None:
    """같은 입력의 해시가 매번 다르다 (솔트).

    같으면 해시 비교로 "두 사용자가 같은 비밀번호를 쓴다"를 알 수 있고, 레인보우
    테이블 한 번으로 전원이 뚫린다.
    """
    first = hash_password(PASSWORD)
    second = hash_password(PASSWORD)

    assert first != second
    # 그래도 둘 다 원문으로 검증된다 — 솔트가 해시 문자열에 들어 있기 때문이다.
    assert verify_password(PASSWORD, first) is True
    assert verify_password(PASSWORD, second) is True


def test_long_password_is_not_truncated() -> None:
    """**argon2를 고른 이유의 증거다** (Q1a, BR-1.2).

    한글 30자 = 90바이트 비밀번호를 만들어, 앞 72바이트만으로는 검증되지 않음을
    확인한다. bcrypt라면 72바이트에서 잘려 앞부분만으로도 통과하고, 사용자는 자기
    비밀번호가 사실 24글자였다는 것을 알 수 없다.
    """
    long_password = "비밀번호를아주길게만들어봅니다열자더붙입니다여덟자"
    assert len(long_password.encode()) > 72, "이 테스트의 전제 — 72바이트를 넘겨야 한다"

    stored = hash_password(long_password)
    truncated = long_password.encode()[:72].decode(errors="ignore")

    assert verify_password(long_password, stored) is True
    # 잘린 앞부분으로는 통과하지 못한다. bcrypt였다면 여기가 True가 된다.
    assert verify_password(truncated, stored) is False


def test_dummy_hash_never_matches_anything() -> None:
    """`DUMMY_HASH`는 어떤 비밀번호로도 검증되지 않는다 — BR-1.4의 안전 조건.

    이 값이 실제 어떤 계정의 비밀번호와 맞으면, 아이디가 없는 로그인 요청이
    성공하는 통로가 된다. 그런 일이 없음을 확인한다.
    """
    assert DUMMY_HASH.startswith("$argon2id$")
    for candidate in (PASSWORD, "", "argon2-timing-equalizer", "admin"):
        assert verify_password(candidate, DUMMY_HASH) is False


def test_broken_stored_hash_is_a_failure_not_a_pass() -> None:
    """argon2 형식이 아닌 저장값은 False다 — **조용히 통과시키지 않는다.**

    U1의 스키마 테스트가 `password_hash`에 `"not-a-real-hash"`를 넣는다. 그런 행이
    로그인에 성공하면 안 된다.
    """
    assert verify_password(PASSWORD, "not-a-real-hash") is False


# --------------------------------------------------------------------------
# JWT (FR-1.2, FR-1.3, BR-1.5)
# --------------------------------------------------------------------------
def test_token_round_trip() -> None:
    """발급한 토큰을 검증하면 같은 `user_id`가 나온다."""
    token = create_token(42)

    assert verify_token(token) == 42


def test_token_carries_only_sub_and_exp() -> None:
    """클레임이 `sub`·`exp` 둘뿐이다 (`business-logic-model.md` W2).

    사용자명·표시명을 넣으면 토큰이 낡는다 — 리프레시가 없어(FR-1.2) 만료까지 최대
    24시간 동안 낡은 값이 돌아다닌다.
    """
    claims = jwt.decode(create_token(42), options={"verify_signature": False})

    assert set(claims) == {"sub", "exp"}
    # `sub`는 문자열이다 — RFC 7519가 StringOrURI로 정의하고 PyJWT 2.10이 정수를 거부한다.
    assert claims["sub"] == "42"


def test_expired_token_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """만료된 토큰은 `InvalidToken`이다.

    만료 시간을 음수로 돌려 이미 지난 토큰을 만든다. 실제 시간을 기다리지 않는다.
    """
    monkeypatch.setattr(settings, "JWT_EXPIRE_MINUTES", -1)
    expired = create_token(42)

    with pytest.raises(InvalidToken):
        verify_token(expired)


def test_tampered_token_is_rejected() -> None:
    """서명을 건드린 토큰은 `InvalidToken`이다."""
    token = create_token(42)
    header, payload, signature = token.split(".")
    # 서명의 첫 글자를 다른 글자로 바꾼다.
    flipped = "B" if signature[0] == "A" else "A"
    tampered = f"{header}.{payload}.{flipped}{signature[1:]}"

    with pytest.raises(InvalidToken):
        verify_token(tampered)


def test_token_signed_with_another_secret_is_rejected() -> None:
    """다른 키로 서명한 토큰은 거부된다 — 우리 서명 키의 검증이 실제로 돈다.

    이 테스트가 없으면 `verify_token`이 서명을 아예 확인하지 않는 구현도 통과한다.
    """
    foreign = jwt.encode(
        {"sub": "42", "exp": datetime.now(UTC) + timedelta(minutes=10)},
        "a-different-signing-key",
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(InvalidToken):
        verify_token(foreign)


def test_token_without_sub_is_rejected() -> None:
    """`sub`가 없는 토큰은 형식 오류다 — 우리 키로 서명했어도 거부된다."""
    no_subject = jwt.encode(
        {"exp": datetime.now(UTC) + timedelta(minutes=10)},
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(InvalidToken):
        verify_token(no_subject)


def test_non_numeric_sub_is_rejected() -> None:
    """`sub`가 정수로 읽히지 않으면 거부한다.

    이것이 없으면 `int(subject)`가 `ValueError`로 500이 되거나, 더 나쁘게는 None이
    사용자 조회까지 흘러간다.
    """
    weird = jwt.encode(
        {"sub": "alice", "exp": datetime.now(UTC) + timedelta(minutes=10)},
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )

    with pytest.raises(InvalidToken):
        verify_token(weird)


@pytest.mark.parametrize("garbage", ["", "not-a-token", "a.b.c", "Bearer abc.def.ghi"])
def test_malformed_tokens_are_rejected(garbage: str) -> None:
    """형식 자체가 JWT가 아닌 입력도 `InvalidToken`이다.

    `"Bearer abc.def.ghi"`가 목록에 있는 이유 — 호출자가 접두사를 떼지 않고 넘기는
    실수가 흔하고, 그 경우도 조용히 통과하면 안 된다.
    """
    with pytest.raises(InvalidToken):
        verify_token(garbage)

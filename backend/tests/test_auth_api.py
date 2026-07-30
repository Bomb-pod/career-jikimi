"""`/auth/*` 엔드포인트 — FR-1.1·FR-1.2의 수용 기준.

**실제 MariaDB에서 돈다.** `TEST_DATABASE_URL`이 없거나 DB에 닿지 못하면 전부
skip된다 (conftest의 `migrated_database`). SQLite로 대체하지 않는 이유는 conftest의
모듈 주석에 있다 — 여기서 검증하는 UNIQUE 위반의 409 변환은 실제 제약이 있어야
확인된다.

대응: FR-1.1, FR-1.2, BR-1.1, BR-1.2, BR-1.4, BR-1.5.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from tests.conftest import VALID_PASSWORD, bearer, capture_sql, signup_via_api


async def _password_hash_of(sessionmaker: Any, username: str) -> str | None:
    """DB에 저장된 해시를 직접 읽는다. 없으면 `None`.

    API 응답이 아니라 **DB 컬럼**을 보는 이유 — FR-1.1의 수용 기준이
    "DB의 password 컬럼은 평문과 일치하지 않는다"이기 때문이다.
    """
    async with sessionmaker() as session:
        result = await session.execute(
            sa.text("SELECT password_hash FROM users WHERE username = :username"),
            {"username": username},
        )
        row = result.first()
    return None if row is None else str(row[0])


# --------------------------------------------------------------------------
# 회원가입 (FR-1.1)
# --------------------------------------------------------------------------
async def test_signup_creates_account_and_stores_a_hash(
    api_client: Any, db_bound_sessionmaker: Any
) -> None:
    """가입은 201을 주고, DB에는 평문이 아닌 해시가 들어간다 — FR-1.1의 첫 기준.

    응답에 `password_hash`가 **없다는 것도 함께 확인한다** — `UserOut`이 세 필드만
    선언해 구조적으로 막지만, 그 구조가 실제로 지켜지는지는 응답 본문으로 봐야 한다.
    """
    response = await api_client.post(
        "/auth/signup", json={"username": "alice", "password": VALID_PASSWORD}
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user"] == {"id": body["user"]["id"], "username": "alice", "display_name": "alice"}
    # 해시가 응답 어디에도 없다. 문자열 전체를 훑어 필드 이름 변경까지 잡는다.
    assert "password" not in response.text

    stored = await _password_hash_of(db_bound_sessionmaker, "alice")
    assert stored is not None
    assert stored != VALID_PASSWORD
    assert stored.startswith("$argon2id$")


async def test_signup_returns_a_usable_token(api_client: Any) -> None:
    """가입 응답의 토큰이 **곧바로** 보호 엔드포인트에 통한다 — 자동 로그인.

    이것이 되지 않으면 사용자가 가입 직후 다시 로그인해야 한다.
    """
    created = await signup_via_api(api_client, "auto-login")

    protected = await api_client.get("/friends", headers=bearer(created["token"]))

    assert protected.status_code == 200


async def test_signup_rejects_a_seven_character_password(
    api_client: Any, db_bound_sessionmaker: Any
) -> None:
    """7자 비밀번호는 400 `WEAK_PASSWORD`이고 **계정이 만들어지지 않는다** — BR-1.2.

    계정 생성 여부를 함께 확인하는 이유 — 400을 주면서 행을 남기는 구현도 상태
    코드만 보면 통과한다.
    """
    response = await api_client.post(
        "/auth/signup", json={"username": "shorty", "password": "pw12345"}
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "WEAK_PASSWORD"
    # 문구에 최소 길이가 들어 있다 — 프론트엔드가 이 문구를 그대로 보여준다.
    assert "8" in response.json()["error"]["message"]
    assert await _password_hash_of(db_bound_sessionmaker, "shorty") is None


async def test_duplicate_username_is_a_conflict(api_client: Any) -> None:
    """이미 있는 아이디로 가입하면 409 `USERNAME_TAKEN`이다 — BR-1.1, FR-1.1의 둘째 기준."""
    await signup_via_api(api_client, "alice")

    second = await api_client.post(
        "/auth/signup", json={"username": "alice", "password": "another-pw-1"}
    )

    assert second.status_code == 409
    assert second.json()["error"]["code"] == "USERNAME_TAKEN"


async def test_conflict_comes_from_the_unique_constraint_not_a_pre_check(
    api_client: Any,
) -> None:
    """409가 **INSERT의 무결성 위반**에서 나온다 — 사전 중복 조회를 하지 않는다.

    BR-1.1이 "두 요청이 동시에 들어오면 사전 조회는 둘 다 통과한다"고 못 박았고,
    계획이 그래서 사전 조회를 없앴다. 이 테스트는 그 결정을 회귀로부터 지킨다 —
    누군가 "409를 더 빨리 주자"며 `SELECT ... WHERE username = ?`를 넣으면
    여기서 붉어진다.

    사전 조회가 들어와도 409는 그대로 나오므로, 상태 코드만 보는 테스트로는
    이 회귀를 잡을 수 없다. **나간 SQL을 봐야 한다.**
    """
    await signup_via_api(api_client, "alice")

    with capture_sql() as statements:
        second = await api_client.post(
            "/auth/signup", json={"username": "alice", "password": "another-pw-1"}
        )

    assert second.status_code == 409
    users_selects = [
        item
        for item in statements
        if item.lstrip().upper().startswith("SELECT") and "users" in item.lower()
    ]
    assert not users_selects, f"가입 경로에 users 사전 조회가 있다: {users_selects}"
    assert any(item.lstrip().upper().startswith("INSERT") for item in statements)


async def test_username_is_trimmed_before_storing(api_client: Any) -> None:
    """앞뒤 공백은 저장 전에 제거된다.

    `" alice "`를 그대로 저장하면 유일성(BR-1.1)과 정확 일치 검색(BR-2.1)이 사용자가
    화면에서 볼 수 없는 방식으로 갈라진다 — 같은 아이디를 두 번 만들 수 있게 된다.
    """
    created = await api_client.post(
        "/auth/signup", json={"username": "  alice  ", "password": VALID_PASSWORD}
    )

    assert created.status_code == 201
    assert created.json()["user"]["username"] == "alice"
    # 트림했으므로 같은 아이디로 다시 가입할 수 없다.
    again = await api_client.post(
        "/auth/signup", json={"username": "alice", "password": VALID_PASSWORD}
    )
    assert again.status_code == 409


# --------------------------------------------------------------------------
# 로그인 (FR-1.2, BR-1.4)
# --------------------------------------------------------------------------
async def test_login_returns_a_token_that_opens_protected_endpoints(api_client: Any) -> None:
    """FR-1.2의 첫 기준 그대로 — 토큰이 반환되고 그 토큰으로 보호 경로에 접근한다."""
    await signup_via_api(api_client, "alice")

    response = await api_client.post(
        "/auth/login", json={"username": "alice", "password": VALID_PASSWORD}
    )

    assert response.status_code == 200
    token = response.json()["token"]
    assert response.json()["user"]["username"] == "alice"

    protected = await api_client.get("/friends", headers=bearer(token))
    assert protected.status_code == 200


async def test_wrong_password_is_unauthorized(api_client: Any) -> None:
    """틀린 비밀번호는 401이고 토큰을 발급하지 않는다 — FR-1.2의 둘째 기준."""
    await signup_via_api(api_client, "alice")

    response = await api_client.post(
        "/auth/login", json={"username": "alice", "password": "wrong-password"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert "token" not in response.json()


async def test_unknown_username_and_wrong_password_are_indistinguishable(
    api_client: Any,
) -> None:
    """**BR-1.4의 핵심** — 두 실패의 상태·본문이 완전히 같다.

    하나라도 다르면 계정 존재 여부가 새어나간다. 문구를 한쪽만 바꾸는 실수가
    가장 흔하므로 본문 전체를 비교한다.
    """
    await signup_via_api(api_client, "alice")

    wrong_password = await api_client.post(
        "/auth/login", json={"username": "alice", "password": "wrong-password"}
    )
    unknown_user = await api_client.post(
        "/auth/login", json={"username": "nobody-here", "password": "wrong-password"}
    )

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json()


async def test_unknown_username_still_runs_a_hash_verification(api_client: Any) -> None:
    """아이디가 없어도 `DUMMY_HASH` 검증이 돈다 — BR-1.4의 **응답 시간** 균일화.

    시간을 재는 테스트는 CI에서 불안정하므로 시간을 재지 않는다. 대신 **조회는 있고
    그 뒤에 아무 일도 없는 경로가 아님**을 확인한다: 사용자를 찾지 못한 요청도
    사용자를 찾은 요청과 같은 개수의 SELECT를 낸다는 사실로는 부족하고,
    `verify_password`가 실제로 호출되는지를 봐야 한다.

    그래서 `security.verify_password`를 감시한다. 호출이 0번이면 더미 검증이
    빠졌다는 뜻이고, 그 순간 응답 시간이 갈라진다.
    """
    calls: list[str] = []
    from app.auth import service as auth_service

    original = auth_service.verify_password

    def _spy(raw: str, stored: str) -> bool:
        calls.append(stored)
        return original(raw, stored)

    auth_service.verify_password = _spy  # type: ignore[assignment]
    try:
        response = await api_client.post(
            "/auth/login", json={"username": "nobody-here", "password": "whatever1"}
        )
    finally:
        auth_service.verify_password = original  # type: ignore[assignment]

    assert response.status_code == 401
    assert len(calls) == 1, "아이디가 없을 때 더미 해시 검증이 돌지 않았다 (BR-1.4)"
    assert calls[0].startswith("$argon2id$")


# --------------------------------------------------------------------------
# 보호 엔드포인트 (BR-1.5)
# --------------------------------------------------------------------------
async def test_protected_endpoint_without_a_token_is_unauthorized(api_client: Any) -> None:
    """토큰 없이 보호 경로에 가면 401이다 — 403이 아니다.

    403은 "인증됐지만 권한이 없다"다. FastAPI의 `HTTPBearer` 기본값이 403을 내므로
    `auto_error=False`로 껐다. 이 테스트가 그 설정을 지킨다.
    """
    response = await api_client.get("/friends")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_protected_endpoint_with_a_garbage_token_is_unauthorized(api_client: Any) -> None:
    """형식이 잘못된 토큰도 401이다 — 500이 되지 않는다."""
    response = await api_client.get("/friends", headers=bearer("not-a-real-jwt"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_token_for_a_missing_user_is_unauthorized(api_client: Any) -> None:
    """서명은 맞지만 없는 사용자를 가리키는 토큰은 401이다 — BR-1.5.

    이 프로젝트에 탈퇴가 없어 실제로는 일어나지 않지만, 서명 키가 유출됐거나 DB가
    초기화된 상황에서 통과시킬 수 없다.
    """
    from app.auth.security import create_token

    response = await api_client.get("/friends", headers=bearer(create_token(999_999_999)))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_non_bearer_authorization_header_is_unauthorized(api_client: Any) -> None:
    """`Bearer`가 아닌 스킴은 401이다."""
    response = await api_client.get("/friends", headers={"Authorization": "Basic YWxpY2U6cHc="})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


# --------------------------------------------------------------------------
# GET /auth/me — 새로고침 후 "내가 누구인지" 복구
# --------------------------------------------------------------------------
# `component-methods.md`에 없던 표면이다. U4·U5의 code-summary가 둘 다 "화면이
# 현재 사용자를 보여주려면 필요하다"로 남겨둔 항목이며, 프론트엔드를 마무리하면서
# 그 필요가 실제로 발생했다.


async def test_me_returns_the_token_owner(api_client: Any) -> None:
    """유효한 토큰으로 부르면 그 토큰이 가리키는 사용자를 준다."""
    created = await signup_via_api(api_client, "me_owner")

    response = await api_client.get("/auth/me", headers=bearer(created["token"]))

    assert response.status_code == 200
    assert response.json() == created["user"]


async def test_me_does_not_leak_the_password_hash(api_client: Any) -> None:
    """응답에 `password_hash`가 없다 — FR-1.1.

    `UserOut`이 세 필드만 선언해 구조적으로 막혀 있으나, 새 엔드포인트가 그 모델을
    실제로 쓰는지는 별도로 고정해야 한다.
    """
    created = await signup_via_api(api_client, "me_nohash")

    response = await api_client.get("/auth/me", headers=bearer(created["token"]))

    assert response.status_code == 200
    assert set(response.json()) == {"id", "username", "display_name"}
    assert "password_hash" not in response.text


async def test_me_without_a_token_is_unauthorized(api_client: Any) -> None:
    """토큰이 없으면 401이다 — BR-1.5.

    프론트엔드가 이 401을 **토큰을 지우라는 신호**로 쓴다. 403이면 "로그인은 됐는데
    권한이 없다"로 읽혀 낡은 토큰이 계속 남는다.
    """
    response = await api_client.get("/auth/me")

    assert response.status_code == 401


async def test_me_with_a_garbage_token_is_unauthorized(api_client: Any) -> None:
    """위조 토큰도 401이다 — 만료·서명 오류와 같은 경로."""
    response = await api_client.get("/auth/me", headers=bearer("not-a-real-token"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


async def test_me_does_not_issue_a_new_token(api_client: Any) -> None:
    """응답에 토큰이 없다.

    갱신하면 사실상 무기한 세션이 되어 FR-1.2가 리프레시 토큰을 범위 밖으로 둔
    결정이 뒤집힌다. `AuthResponse`가 아니라 `UserOut`을 반환하는 이유다.
    """
    created = await signup_via_api(api_client, "me_notoken")

    response = await api_client.get("/auth/me", headers=bearer(created["token"]))

    assert "token" not in response.json()

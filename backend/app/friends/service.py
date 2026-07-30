"""친구 검색·등록·별칭 수정·표시명 해석 — W4·W5·W6과 표시명 알고리즘.

`resolve_display_names()`는 **U4·U5가 호출하는 계약**이다
(`unit-of-work-dependency.md`). 시그니처를 바꾸면 두 단위가 깨진다.

대응: FR-2.1~FR-2.4, BR-2.1~BR-2.8.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.friends.exceptions import (
    AliasRequired,
    AlreadyFriend,
    CannotFriendSelf,
    FriendshipForbidden,
    UserNotFound,
)
from app.models import Friendship, User

logger = logging.getLogger(__name__)


async def search_user(session: AsyncSession, username: str) -> User | None:
    """아이디 **정확 일치**로 사용자를 찾는다 — W4.

    Returns:
        찾은 `User`, 또는 없으면 `None`. **예외를 던지지 않는다** (BR-2.1) —
        결과가 없는 것은 검색의 실패가 아니라 검색의 결과다. 라우터가 이 `None`을
        `200 {"user": null}`로 실어 보낸다.

    부분 일치·유사도 검색을 하지 않는다 (FR-2.1이 명시적으로 배제). `"ali"`로
    `"alice"`를 찾을 수 없다.

    **대소문자는 구분되지 않는다.** MariaDB의 `utf8mb4_unicode_ci` 콜레이션 때문에
    `Alice`로 검색해도 `alice`가 나온다. `business-rules.md`가 이것을 "일관되므로
    그대로 둔다"로 닫았다 — 유일성(BR-1.1)이 같은 콜레이션을 쓰므로 `Alice`와
    `alice`가 동시에 가입할 수도 없다.
    """
    result = await session.execute(sa.select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def list_friends(session: AsyncSession, owner_id: int) -> list[Friendship]:
    """내가 등록한 친구 전부를 돌려준다.

    **단방향이다** (BR-2.3) — `owner_id`가 나인 행만 본다. 남이 나를 등록한 행은
    그 사람의 목록에 있고 내 목록에는 없다.

    `id` 순서로 정렬하는 이유 — FR-2.1이 정렬 **기능**(사용자가 고르는 정렬 기준)을
    배제했을 뿐이고, 순서를 지정하지 않으면 같은 데이터가 요청마다 다른 순서로 와서
    화면이 흔들린다. 등록 순서가 사용자에게 가장 예측 가능한 순서다.
    """
    result = await session.execute(
        sa.select(Friendship).where(Friendship.owner_id == owner_id).order_by(Friendship.id)
    )
    return list(result.scalars().all())


async def add_friend(
    session: AsyncSession, owner_id: int, target_username: str, alias: str
) -> Friendship:
    """친구를 단방향으로 즉시 등록한다 — W5.

    Args:
        session: 요청 단위 세션.
        owner_id: 등록하는 사람(호출자).
        target_username: 등록 대상 아이디.
        alias: 내가 붙일 이름. 트림 전 원문을 받는다.

    Raises:
        AliasRequired: 트림 후 빈 별칭 (BR-2.2, 400).
        UserNotFound: 대상 아이디가 없음 (BR-2.6, 404).
        CannotFriendSelf: 대상이 나 자신 (BR-2.5, 400).
        AlreadyFriend: 이미 등록된 상대 (BR-2.4, 409).

    **판정 순서가 `business-rules.md` § 규칙 간 우선순위 그대로다** — DB 접근이 없는
    검사가 먼저다. 별칭 검사(입력만 봄) → 대상 존재(조회 1회) → 자기 자신(조회
    결과로 판정) → 중복(INSERT 무결성 위반). 여러 규칙을 동시에 위반해도 **첫 번째
    위반만 응답한다.**

    **승인 절차가 없다** (BR-2.3) — 등록하면 즉시 내 목록에 나타나고, 상대의 목록은
    변하지 않으며 상대는 알림도 받지 않는다.
    """
    trimmed = _require_alias(alias)

    target = await search_user(session, target_username)
    if target is None:
        # 검색은 같은 상황에 200 + null을 주지만 **등록은 404다** (BR-2.6).
        # 의도적으로 다르다 — 두 규칙을 하나로 합치지 않는다.
        raise UserNotFound("해당 아이디의 사용자를 찾을 수 없습니다")

    if target.id == owner_id:
        raise CannotFriendSelf("자기 자신은 친구로 등록할 수 없습니다")

    friendship = Friendship(owner_id=owner_id, friend_id=target.id, alias=trimmed)
    session.add(friendship)
    try:
        # 사전 중복 조회를 하지 않는다 — `UNIQUE (owner_id, friend_id)`가 최종
        # 방어선이고, 조회를 더해도 경쟁 조건의 창을 좁힐 뿐이다 (BR-2.4).
        await session.flush()
    except IntegrityError as exc:
        # 무결성 위반을 **서비스 계층에서** 도메인 예외로 바꾼다. 라우터까지
        # 올려보내면 DB 방언이 HTTP 계층에 새고, 500이 나간다.
        await session.rollback()
        raise AlreadyFriend("이미 친구로 등록된 사용자입니다") from exc

    return friendship


async def update_alias(
    session: AsyncSession, owner_id: int, friendship_id: int, alias: str
) -> Friendship:
    """별칭을 바꾼다 — W6.

    Raises:
        AliasRequired: 트림 후 빈 별칭 (BR-2.2, 400). **기존 값이 유지된다** —
            UPDATE를 실행하기 전에 던지므로 자동으로 그렇게 된다.
        FriendshipForbidden: 그 friendship이 없거나 남의 것이다 (BR-2.7, 403).

    **없는 id와 남의 id를 하나의 조회로 합친 것이 이 함수의 요점이다.** BR-2.7이
    두 경우에 같은 403을 요구하므로, `WHERE id = ? AND owner_id = ?`로 물어
    `None`이면 그대로 403을 낸다. 두 경우를 나눠 조회하고 같은 예외를 던지는 것보다
    낫다 — 나눠두면 나중에 한쪽만 404로 바꾸는 실수가 가능하고, 그 실수는 남의
    friendship id 존재 여부를 새게 만든다.
    """
    trimmed = _require_alias(alias)

    result = await session.execute(
        sa.select(Friendship).where(
            Friendship.id == friendship_id,
            Friendship.owner_id == owner_id,
        )
    )
    friendship = result.scalar_one_or_none()
    if friendship is None:
        logger.info("허용되지 않은 별칭 수정 시도 (friendship_id=%s)", friendship_id)
        raise FriendshipForbidden("해당 친구 항목을 수정할 권한이 없습니다")

    friendship.alias = trimmed
    # `get_session()`이 핸들러 성공 시 커밋한다. flush를 명시하는 이유는 이 함수가
    # 돌려주는 객체가 DB에 반영된 값과 같음을 이 자리에서 확정하기 위해서다.
    await session.flush()
    return friendship


async def resolve_display_names(
    session: AsyncSession, owner_id: int, user_ids: list[int]
) -> dict[int, str]:
    """각 사용자를 호출자에게 어떻게 보여줄지 해석한다 — BR-2.8.

    Args:
        session: 요청 단위 세션.
        owner_id: 보는 사람. 이 사람이 붙인 별칭이 우선한다.
        user_ids: 해석할 사용자 id 목록. 중복이 있어도 되고 순서는 무관하다.

    Returns:
        `{user_id: 표시명}`. 친구로 등록한 상대는 **별칭**, 아니면 그 사용자의
        `display_name`. **`users`에 없는 id는 키가 아예 없다** — 호출자가
        `dict.get()`으로 다뤄야 한다. 없는 사용자에게 가짜 이름을 만들어주지 않는다.

    **표시명 규칙의 단일 출처다** (`business-logic-model.md` § 표시명 해석). U4가
    방 참여자를, U5가 히스토리 발신자를 이 함수로 해석한다. 규칙이 세 곳에 복제되면
    한 화면에서만 상대의 본명이 보이는 버그가 생긴다.

    **일괄 조회 2회이며, 두 번째는 필요할 때만 돈다.**

    1. `friendships`에서 `owner_id` + `friend_id IN (...)` → 별칭
    2. 1번에 안 나온 id가 **있을 때만** `users`에서 `display_name`

    친구 목록처럼 전원이 친구인 경우 쿼리가 한 번으로 끝난다. 폴백이 발생하는
    조건은 하나뿐이다 — 방에 내가 친구로 등록하지 않은 참여자가 있을 때(다른 사람이
    초대, FR-10.1).

    **반복문 안에서 조회하지 않는다.** 방 참여자가 늘면 N+1이 되어 U4의 방 상세와
    U5의 히스토리 응답 시간을 그 인원수만큼 갉아먹는다. `component-dependency.md`가
    이것을 열린 항목으로 남겼고 여기서 닫는다.

    `owner_id`가 `user_ids`에 들어 있어도 된다 — 자기 자신은 자기 친구가 아니므로
    2번으로 떨어져 자기 `display_name`이 나온다. 방 참여자 목록에 자신이 포함되는
    경우가 그렇다.
    """
    # 중복을 미리 접는다. `IN (...)` 목록이 짧아지고, 아래 차집합 계산이 정확해진다.
    wanted = set(user_ids)
    if not wanted:
        # **쿼리를 아예 보내지 않는다.** `IN ()`은 MariaDB에서 구문 오류이고,
        # SQLAlchemy가 대신 만들어주는 항상-거짓 표현식도 왕복 한 번을 쓴다.
        return {}

    alias_rows = await session.execute(
        sa.select(Friendship.friend_id, Friendship.alias).where(
            Friendship.owner_id == owner_id,
            Friendship.friend_id.in_(wanted),
        )
    )
    resolved: dict[int, str] = {row.friend_id: row.alias for row in alias_rows}

    remaining = wanted - resolved.keys()
    if not remaining:
        # 전원이 친구다 — 쿼리 1회로 끝난다.
        return resolved

    display_rows = await session.execute(
        sa.select(User.id, User.display_name).where(User.id.in_(remaining))
    )
    for row in display_rows:
        # 별칭이 우선하므로 1번 결과를 덮어쓰지 않는다 — `remaining`이 이미
        # 1번에서 해석된 id를 제외했으므로 충돌이 발생하지 않는다.
        resolved[row.id] = row.display_name

    return resolved


# --------------------------------------------------------------------------
# 내부 헬퍼
# --------------------------------------------------------------------------
def _require_alias(alias: str) -> str:
    """별칭을 트림해 돌려준다. 트림 후 비면 `AliasRequired`.

    **트림 후 검사가 BR-2.2의 핵심이다.** `friendships.alias`의 NOT NULL은 `"   "`를
    막지 못한다 — DB가 볼 때 그것은 값이 있는 문자열이다.

    **저장에도 트림된 값을 쓴다.** 앞뒤 공백이 남으면 목록에서 항목이 들쭉날쭉하게
    보이고, 같은 이름을 두 번 붙였는데 다르게 보이는 일이 생긴다.

    등록과 수정이 같은 함수를 쓴다 — 규칙이 하나이므로 구현도 하나여야 한다.
    """
    trimmed = alias.strip()
    if not trimmed:
        raise AliasRequired("별칭을 입력하세요")
    return trimmed


__all__ = [
    "add_friend",
    "list_friends",
    "resolve_display_names",
    "search_user",
    "update_alias",
]

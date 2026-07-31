"""방 생성·목록·상세·읽음 처리·AI 토글 — W1~W4의 구현.

`get_membership()`과 `member_user_ids()`는 **U5 messaging이 호출하는 계약**이다
(`unit-of-work-dependency.md`). 시그니처를 바꾸면 U5가 깨진다:

    await get_membership(session, user_id, room_id) -> RoomMember | None
    await member_user_ids(session, room_id) -> list[int]

`get_membership()`이 참여 자격과 `ai_check_enabled`를 **한 번에** 주는 것이 그
계약의 요점이다 — U5의 `send_message()` 1단계가 그 둘을 함께 필요로 한다.

**이 모듈은 `messages` 테이블을 읽기만 한다**(안 읽은 개수 계산). 쓰지 않는다.
`rooms.last_seq`도 마찬가지다 — 증가는 U5가 한다 (ADR-003).

**`friendships`를 직접 조회하지 않는다.** 친구 판정은 U3의 `list_friends()`를 통해서만
한다 — 그 테이블의 소유자가 U3이고, 단방향 규칙(BR-2.3)이 두 곳에 복제되면 한쪽만
바뀐다.

대응: FR-3.1~FR-3.3, FR-5.2, FR-6.1, BR-3.1~BR-3.4, BR-5.1, BR-5.3, BR-6.1, BR-6.2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.friends.service import list_friends, resolve_display_names
from app.models import Message, Room, RoomMember
from app.rooms.exceptions import AlreadyMember, EmptyRoom, NotAFriend, RoomForbidden

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 반환 타입
# --------------------------------------------------------------------------
# ORM 객체를 그대로 라우터에 넘기지 않는 이유 — `RoomMember`를 넘기면 남의
# `ai_check_enabled`가 응답 스키마 하나만 바뀌어도 샐 수 있다(FR-6.1). 서비스가
# 무엇을 내보내는지 여기서 고정한다.
@dataclass(frozen=True)
class RoomMemberView:
    """참여자 한 명의 **표시명까지 해석된** 모습."""

    user_id: int
    display_name: str


@dataclass(frozen=True)
class RoomSummary:
    """방 목록의 한 항목 — W2.

    `ai_check_enabled`는 **호출자 본인의 값**이다 (FR-6.1). 목록 쿼리가 이미 호출자의
    `room_members` 행과 조인하므로 공짜로 따라온다 — 화면이 방마다 상세를 다시 부르지
    않아도 자기 토글 상태를 그릴 수 있다. 남의 값은 어떤 경로로도 담기지 않는다.
    """

    id: int
    name: str | None
    last_seq: int
    created_at: datetime
    unread_count: int
    last_read_seq: int
    ai_check_enabled: bool
    members: list[RoomMemberView]


@dataclass(frozen=True)
class RoomDetail:
    """방 상세 — W3. `ai_check_enabled`·`last_read_seq`는 **호출자 본인의 값**이다."""

    id: int
    name: str | None
    last_seq: int
    created_at: datetime
    members: list[RoomMemberView]
    ai_check_enabled: bool
    last_read_seq: int


# --------------------------------------------------------------------------
# U5가 소비하는 계약
# --------------------------------------------------------------------------
async def get_membership(session: AsyncSession, user_id: int, room_id: int) -> RoomMember | None:
    """호출자의 `room_members` 행을 준다. `None`이면 참여자가 아니다.

    Returns:
        `ai_check_enabled`와 `last_read_seq`를 포함한 행, 또는 `None`.

    **`None`의 두 경우를 구분하지 않는다** — 방이 없는 것과 참여자가 아닌 것이
    같은 결과다. 호출자는 둘 다 403으로 응답해야 한다 (BR-3.3). 여기서 구분해
    돌려주면 나중에 한쪽만 404로 바꾸는 실수가 가능해지고, 그 실수가 방 id의
    존재 여부를 새게 한다.

    **U5가 부르는 계약이다.** `send_message()`가 참여 자격(FR-3.x)과 검증
    토글(FR-6.1)을 한 번의 조회로 함께 확인한다.
    """
    result = await session.execute(
        sa.select(RoomMember).where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def member_user_ids(session: AsyncSession, room_id: int) -> list[int]:
    """브로드캐스트 대상 조회 전용 — 그 방 참여자 전원의 id.

    **발신자도 포함된다** (BR-5.8). 거르지 않는 것이 의도다 — 다른 탭·기기의 세션도
    갱신되어야 하고, 중복은 클라이언트가 메시지 ID로 제거한다.

    **매 호출마다 조회한다.** 캐시하지 않는 이유는 참여자가 바뀌면(FR-10) 캐시가
    즉시 틀려지기 때문이다 — 나간 사람에게 계속 보내는 것은 조용한 정보 유출이다.
    """
    result = await session.execute(
        sa.select(RoomMember.user_id)
        .where(RoomMember.room_id == room_id)
        .order_by(RoomMember.user_id)
    )
    return list(result.scalars().all())


# --------------------------------------------------------------------------
# W1 · 방 생성
# --------------------------------------------------------------------------
async def create_room(
    session: AsyncSession,
    owner_id: int,
    friend_user_ids: list[int],
    name: str | None,
) -> Room:
    """방을 만들고 참여자를 넣는다 — W1.

    Args:
        session: 요청 단위 세션. 커밋은 `get_session()`이 한다.
        owner_id: 만드는 사람. 참여자에 자동으로 포함된다.
        friend_user_ids: 초대 대상. 중복은 접는다.
        name: 방 이름. `None`이면 화면이 참여자 표시명으로 조립한다.

    Returns:
        `id`가 채워진 `Room`.

    Raises:
        EmptyRoom: 초대 대상이 비어 있다 (BR-3.1, 400).
        NotAFriend: 호출자의 친구가 아닌 id가 섞였다 (BR-3.2, 400).

    **판정 순서가 W1 그대로다** — DB 접근이 없는 검사(빈 목록)가 먼저다.

    **하나의 트랜잭션이다.** `rooms` INSERT와 `room_members` INSERT 전부가 한
    트랜잭션 안에서 일어난다. 나뉘면 참여자가 없는 방, 즉 **아무도 접근할 수 없는
    유령 방**이 남는다 — 방 목록은 `room_members`로 조회하므로 그 방은 어떤 화면에도
    나타나지 않고 삭제 수단도 없다. 중간에 실패하면 `get_session()`이 롤백해
    `rooms` 행도 함께 사라진다.
    """
    targets = _require_targets(friend_user_ids, owner_id)
    await _require_all_friends(session, owner_id, targets)

    room = Room(name=name, created_by=owner_id)
    session.add(room)
    # `flush()`가 INSERT를 보내 `room.id`를 채운다. **커밋이 아니다** — 아래
    # 참여자 INSERT가 실패하면 이 행도 함께 롤백된다.
    await session.flush()

    await _insert_members(session, room.id, [owner_id, *targets])

    logger.info("방을 생성했습니다 (room_id=%s, 참여자=%d명)", room.id, len(targets) + 1)
    return room


async def _insert_members(session: AsyncSession, room_id: int, user_ids: list[int]) -> None:
    """참여자 행을 한 번에 넣는다 (BR-6.2).

    **모든 참여자의 `ai_check_enabled`가 TRUE이고 `last_read_seq`가 0이다.**
    기본이 켜짐인 이유 — 이 앱의 존재 이유가 그 기능이다. 꺼진 채로 시작하면
    아무도 켜지 않는다.

    별도 함수인 이유는 두 가지다. 하나는 `create_room()`이 "검사 → 방 → 참여자"
    세 단계로 읽히게 하는 것이고, 다른 하나는 **참여자 INSERT만 실패하는 상황을
    테스트가 만들 수 있게** 하는 것이다(한 트랜잭션인지 검증하는 회귀 테스트).
    """
    session.add_all(
        [
            RoomMember(
                room_id=room_id,
                user_id=user_id,
                ai_check_enabled=True,
                last_read_seq=0,
            )
            for user_id in user_ids
        ]
    )
    await session.flush()


# --------------------------------------------------------------------------
# W2 · 방 목록
# --------------------------------------------------------------------------
async def list_rooms(session: AsyncSession, user_id: int) -> list[RoomSummary]:
    """내가 속한 방과 각 방의 안 읽은 개수 — W2.

    **빈 목록은 오류가 아니다** (BR-3.4). 어떤 방에도 속하지 않으면 빈 리스트다.

    **조회 횟수가 방 개수와 무관하다.** 방이 1개든 30개든 같다:

    1. 방 + 안 읽은 개수 — `LEFT JOIN` + `GROUP BY` 한 번 (BR-5.1)
    2. 참여자 id 전부 — `room_id IN (...)` 한 번
    3. 표시명 — `resolve_display_names()` 한 번 (그 안에서 1~2회)

    방마다 반복하면 N+1이 된다(`component-dependency.md`의 열린 항목). U3의
    `resolve_display_names()`에는 **쿼리 횟수 회귀 테스트가 붙어 있고**, 여기서
    반복 호출하면 그 테스트가 아니라 이 모듈의 테스트가 붉어진다.

    정렬은 요구사항이 규정하지 않았다(FR-3.2). `id` 내림차순으로 고정하는 이유는
    순서를 지정하지 않으면 같은 데이터가 요청마다 다른 순서로 와서 화면이 흔들리기
    때문이다 — 최근에 만든 방이 위에 오는 것이 사용자에게 가장 자연스럽다.
    """
    unread_count = sa.func.count(Message.id).label("unread_count")
    rows = await session.execute(
        sa.select(
            Room.id,
            Room.name,
            Room.last_seq,
            Room.created_at,
            RoomMember.last_read_seq,
            # 호출자 본인의 값이다 — `WHERE rm.user_id = 호출자`가 이미 걸려 있다.
            RoomMember.ai_check_enabled,
            unread_count,
        )
        .select_from(RoomMember)
        .join(Room, Room.id == RoomMember.room_id)
        # **`LEFT JOIN`이라 메시지가 없는 방도 0으로 나온다.** INNER JOIN이면 그 방이
        # 목록에서 통째로 사라진다 — 방금 만든 방이 보이지 않는 버그가 된다.
        .outerjoin(
            Message,
            sa.and_(
                Message.room_id == RoomMember.room_id,
                Message.seq > RoomMember.last_read_seq,
            ),
        )
        .where(RoomMember.user_id == user_id)
        # 선택한 비집계 컬럼을 전부 적는다. MariaDB의 기본 sql_mode는
        # ONLY_FULL_GROUP_BY가 아니라 생략해도 돌지만, 그 설정이 켜진 서버에서는
        # 즉시 오류가 된다.
        .group_by(
            Room.id,
            Room.name,
            Room.last_seq,
            Room.created_at,
            RoomMember.last_read_seq,
            RoomMember.ai_check_enabled,
        )
        .order_by(Room.id.desc())
    )
    summaries = list(rows.all())
    if not summaries:
        return []

    room_ids = [row.id for row in summaries]
    members_by_room = await _members_by_room(session, room_ids)
    names = await _display_names_for(session, user_id, members_by_room)

    return [
        RoomSummary(
            id=row.id,
            name=row.name,
            last_seq=row.last_seq,
            created_at=row.created_at,
            unread_count=row.unread_count,
            last_read_seq=row.last_read_seq,
            ai_check_enabled=row.ai_check_enabled,
            members=[
                RoomMemberView(user_id=member_id, display_name=_name_of(names, member_id))
                for member_id in members_by_room.get(row.id, [])
            ],
        )
        for row in summaries
    ]


# --------------------------------------------------------------------------
# W3 · 방 상세
# --------------------------------------------------------------------------
async def get_room_detail(session: AsyncSession, user_id: int, room_id: int) -> RoomDetail:
    """방 정보와 참여자, 그리고 **호출자 본인의** 토글·읽음 위치 — W3.

    Raises:
        RoomForbidden: 참여자가 아니거나 **방이 존재하지 않는다** (BR-3.3, 403).

    **403이 먼저다.** 방을 먼저 읽어 404를 내면 방 id의 존재 여부가 새어나간다.

    응답에 **다른 참여자의 `ai_check_enabled`를 넣지 않는다** (FR-6.1). 개인 설정이며
    남이 알 필요가 없다 — `RoomMemberView`에 그 필드가 없어 실을 방법이 없다.
    """
    membership = await get_membership(session, user_id, room_id)
    if membership is None:
        logger.info("참여자가 아닌 방에 접근 시도 (user_id=%s, room_id=%s)", user_id, room_id)
        raise RoomForbidden("이 방에 접근할 권한이 없습니다")

    room = await session.get(Room, room_id)
    if room is None:
        # 참여 행이 있는데 방이 없다 = FK가 보장하는 불변식이 깨진 상태다.
        # 사용자에게는 같은 403을 주되(존재 여부를 새게 하지 않는다) 경고를 남긴다.
        logger.error("참여 행은 있으나 방이 없습니다 (room_id=%s)", room_id)
        raise RoomForbidden("이 방에 접근할 권한이 없습니다")

    members_by_room = await _members_by_room(session, [room_id])
    names = await _display_names_for(session, user_id, members_by_room)

    return RoomDetail(
        id=room.id,
        name=room.name,
        last_seq=room.last_seq,
        created_at=room.created_at,
        members=[
            RoomMemberView(user_id=member_id, display_name=_name_of(names, member_id))
            for member_id in members_by_room.get(room_id, [])
        ],
        ai_check_enabled=membership.ai_check_enabled,
        last_read_seq=membership.last_read_seq,
    )


# --------------------------------------------------------------------------
# W4 · 읽음 처리와 AI 토글
# --------------------------------------------------------------------------
async def mark_read(session: AsyncSession, user_id: int, room_id: int, up_to_seq: int) -> int:
    """`last_read_seq`를 전진시킨다 — W4.

    Returns:
        처리 후의 `last_read_seq`. 전진하지 못했으면 **기존 값**이다.

    Raises:
        RoomForbidden: 참여자가 아니다 (BR-3.3, 403).

    **`last_read_seq < ?` 조건절이 이 함수의 전부다** (BR-5.3). 조건이 없으면 순서가
    뒤바뀐 요청이 배지를 되살린다 — 사용자가 방을 빠르게 오갈 때 실제로 일어난다.
    방 A(seq 30)를 읽고 방 B로 갔다가 다시 A로 오면, 늦게 도착한 옛 요청이
    `last_read_seq`를 30에서 12로 되돌릴 수 있다.

    **영향 행이 0이어도 200이다.** "이미 더 앞서 있다"는 정상이지 오류가 아니다 —
    오류로 다루면 클라이언트가 정상 동작에 대해 재시도하거나 사용자에게 실패를
    보여준다.
    """
    membership = await get_membership(session, user_id, room_id)
    if membership is None:
        raise RoomForbidden("이 방에 접근할 권한이 없습니다")

    result = await session.execute(
        sa.update(RoomMember)
        .where(
            RoomMember.room_id == room_id,
            RoomMember.user_id == user_id,
            # ← 이 줄이 전진만을 보장한다.
            RoomMember.last_read_seq < up_to_seq,
        )
        .values(last_read_seq=up_to_seq)
    )

    if result.rowcount == 0:
        # 요청 값이 현재 값 이하다. 무시하고 현재 값을 돌려준다 (BR-5.3).
        return membership.last_read_seq
    return up_to_seq


async def set_ai_check(session: AsyncSession, user_id: int, room_id: int, enabled: bool) -> bool:
    """**호출자 본인의** AI 검증 토글을 바꾼다 (BR-6.1).

    Returns:
        변경 후의 값.

    Raises:
        RoomForbidden: 참여자가 아니다 (BR-3.3, 403).

    **방장 개념이 없다.** `rooms.created_by`는 기록이지 권한이 아니며, 이 함수는
    `WHERE user_id = 호출자`로 자기 행만 건드린다. 다른 참여자의 설정은 변하지
    않는다 — 방장이 켜면 전원이 1~3초씩 기다리게 되는데, 남이 내 전송 지연을
    결정하면 안 된다.
    """
    membership = await get_membership(session, user_id, room_id)
    if membership is None:
        raise RoomForbidden("이 방에 접근할 권한이 없습니다")

    await session.execute(
        sa.update(RoomMember)
        .where(
            RoomMember.room_id == room_id,
            # ← 자기 행만. 이 줄을 빼면 방 전체의 설정이 바뀐다.
            RoomMember.user_id == user_id,
        )
        .values(ai_check_enabled=enabled)
    )
    return enabled


# --------------------------------------------------------------------------
# FR-10 · 참여자 관리 (Should)
# --------------------------------------------------------------------------
# 이 절은 `code-generation-plan.md` Step 7이다. 2026-07-30에 절단되었다가
# 2026-07-31에 복원되었다 — 절단 사유(U5에 시간을 돌려준다)가 U5 완료로 사라졌다.
#
# **새 규칙을 만들지 않는다.** 친구 확인은 `_require_all_friends()`, 참여자 INSERT는
# `_insert_members()`를 그대로 쓴다. 두 함수가 BR-3.2와 BR-6.2의 단일 출처이며,
# 여기서 같은 판단을 다시 쓰면 한쪽만 바뀌는 날 방 생성과 초대의 규칙이 갈라진다.
async def add_member(
    session: AsyncSession, caller_id: int, room_id: int, friend_user_id: int
) -> None:
    """기존 방에 친구 한 명을 추가한다 — FR-10.1.

    Args:
        session: 요청 단위 세션. 커밋은 `get_session()`이 한다.
        caller_id: 초대하는 사람. **그 방의 참여자여야 한다.**
        room_id: 대상 방.
        friend_user_id: 초대 대상. `caller_id`의 친구여야 한다.

    Raises:
        RoomForbidden: 호출자가 참여자가 아니거나 방이 없다 (BR-3.3, 403).
        AlreadyMember: 대상이 이미 참여 중이다 (BR-10.1, 400).
        NotAFriend: 대상이 호출자의 친구가 아니다 (BR-3.2, 400).

    **판정 순서가 403 → ALREADY_MEMBER → NOT_A_FRIEND다.**

    403이 먼저인 것은 다른 검사가 방의 내용을 건드리기 때문이다 — 참여자가 아닌
    사람에게 `ALREADY_MEMBER`를 주면 그 방에 누가 있는지 확인해주는 셈이 된다.

    `ALREADY_MEMBER`가 `NOT_A_FRIEND`보다 먼저인 이유는 **정확한 사유를 주기
    위해서다.** 이 시점의 호출자는 이미 참여자이므로 W3으로 참여자 명단 전체를 볼 수
    있고, 따라서 "이미 있다"는 답은 새로운 정보를 흘리지 않는다. 반대로 친구 검사를
    먼저 두면, 나중에 들어온 참여자(내 친구가 아닐 수 있다 — BR-3.2가 초대자 기준이라
    참여자끼리는 친구가 아닐 수 있다)를 다시 추가할 때 `NOT_A_FRIEND`가 나가
    사용자가 원인을 잘못 읽는다. FR-10.1의 둘째 수용 기준도 친구 여부를 조건으로
    달지 않는다.

    **`last_read_seq`는 0으로 시작한다** (`_insert_members()`, BR-6.2). 방에 이미
    메시지 50개가 있으면 추가된 사람의 배지가 50이 된다. 그것이 사실이다 — 그 사람은
    아직 아무것도 읽지 않았고 히스토리는 볼 수 있다. `rooms.last_seq`로 맞춰 배지를
    0으로 만드는 선택도 있으나, 그러면 FR-10.1의 "추가된 참여자의 방 목록에 그 방이
    나타난다"가 화면에서 눈에 띄지 않게 된다. `RoomMember`의 생애주기 주석이 이미
    "나갔다 다시 초대되면 기본값으로 돌아간다"고 못박아 두었다.
    """
    if await get_membership(session, caller_id, room_id) is None:
        logger.info("참여자가 아닌 방에 초대 시도 (caller_id=%s, room_id=%s)", caller_id, room_id)
        raise RoomForbidden("이 방에 접근할 권한이 없습니다")

    if await get_membership(session, friend_user_id, room_id) is not None:
        raise AlreadyMember("이미 이 방에 참여 중인 사용자입니다")

    await _require_all_friends(session, caller_id, [friend_user_id])
    await _insert_members(session, room_id, [friend_user_id])

    logger.info("방에 참여자를 추가했습니다 (room_id=%s, user_id=%s)", room_id, friend_user_id)


async def leave_room(session: AsyncSession, caller_id: int, room_id: int) -> None:
    """방에서 나간다 — FR-10.2.

    Raises:
        RoomForbidden: 참여자가 아니거나 방이 없다 (BR-3.3, 403).

    **행을 지우는 것이 전부다** (BR-10.2). 브로드캐스트 대상은 `member_user_ids()`가
    **매 전송마다** 조회하므로, 이 DELETE 하나로 "새 메시지를 받지 않는다"가 성립한다.
    그 함수가 결과를 캐시했다면 여기서 캐시 무효화를 함께 해야 했고, 빠뜨리는 날
    나간 사람에게 계속 전송되는 조용한 정보 유출이 됐을 것이다.

    방 목록에서 사라지는 것도 같은 이유다 — `list_rooms()`가 `room_members`에서
    출발한다.

    **마지막 참여자가 나가도 방을 지우지 않는다.** `create_room()`이 경계하는 "유령
    방"과 겉모습이 같지만 성격이 다르다:

    - 그쪽은 **메시지가 없는** 방이 트랜잭션 분리로 생기는 결함이다
    - 이쪽은 **메시지와 판정 로그가 이미 쌓인** 방이 정상 경로로 비는 것이다

    지우려면 `messages`와 `judgment_logs`를 함께 지워야 하는데(FK가 RESTRICT다),
    그것은 이 프로젝트가 모으려는 실험 데이터 자체다 — FR-7의 지표와 오프라인 재판정이
    그 행들을 읽는다. 사용자 눈에서 사라지는 것으로 FR-10.2는 충족되고, 데이터는
    남는다. 되살릴 수단이 없다는 점은 경고 로그로 남긴다.
    """
    if await get_membership(session, caller_id, room_id) is None:
        raise RoomForbidden("이 방에 접근할 권한이 없습니다")

    await session.execute(
        sa.delete(RoomMember).where(
            RoomMember.room_id == room_id,
            # ← 자기 행만. 이 줄을 빼면 방 전체가 비워진다.
            RoomMember.user_id == caller_id,
        )
    )

    remaining = await session.scalar(
        sa.select(sa.func.count()).select_from(RoomMember).where(RoomMember.room_id == room_id)
    )
    if not remaining:
        logger.warning(
            "마지막 참여자가 나가 방이 비었습니다 — 아무도 다시 들어올 수 없습니다 "
            "(room_id=%s). 메시지와 판정 로그는 남습니다",
            room_id,
        )
    logger.info("방에서 나갔습니다 (room_id=%s, user_id=%s)", room_id, caller_id)


# --------------------------------------------------------------------------
# 내부 헬퍼
# --------------------------------------------------------------------------
def _require_targets(friend_user_ids: list[int], owner_id: int) -> list[int]:
    """초대 대상을 정리해 돌려준다. 비면 `EmptyRoom` (BR-3.1).

    중복을 접는 이유 — 같은 id가 두 번 오면 복합 PK `(room_id, user_id)` 위반으로
    500이 된다. 사용자가 같은 친구를 두 번 고른 것은 규칙 위반이 아니라 입력의
    잡음이므로 조용히 정리한다.

    `dict.fromkeys`로 접는 이유는 순서 보존이다 — `set`을 쓰면 참여자 INSERT 순서가
    실행마다 달라져 테스트가 흔들린다.

    **호출자 자신은 목록에서 뺀다.** 화면이 친구 목록에서 고르게 되어 있어 정상
    경로로는 들어올 수 없지만, 들어오면 "자기 자신은 자기 친구가 아니다"라는 이유로
    `NOT_A_FRIEND`가 나가 사용자가 원인을 알 수 없다. 어차피 아래에서 참여자로
    자동 추가되므로 여기서 제거하는 것이 의미가 같다.
    """
    targets = [user_id for user_id in dict.fromkeys(friend_user_ids) if user_id != owner_id]
    if not targets:
        # 본인 혼자 남았다 = 본인 포함 최소 2명(FR-3.1)을 만족하지 못한다.
        raise EmptyRoom("방에 초대할 친구를 한 명 이상 선택하세요")
    return targets


async def _require_all_friends(session: AsyncSession, owner_id: int, target_ids: list[int]) -> None:
    """대상이 전부 호출자의 친구인지 **한 번의 조회로** 확인한다 (BR-3.2).

    Raises:
        NotAFriend: 하나라도 친구가 아니다 (400).

    **`target_ids`를 순회하며 개별 확인하지 않는다.** 친구 10명을 초대하면 조회가
    10번이 되고, 그 비용은 참여자 수에 비례해 늘어난다.

    `list_friends()`(U3)를 쓰는 이유 — `friendships`는 U3의 테이블이고 친구 관계는
    **단방향**이다(BR-2.3). 여기서 직접 조회하면 그 방향 규칙이 두 곳에 복제되고,
    한쪽만 바뀌는 날 서로 다른 답이 나온다.

    **어떤 id가 친구가 아닌지 응답에 담지 않는다.** 담으면 임의의 id를 넣어보며
    친구 관계를 탐색할 수 있다.
    """
    friend_ids = {friendship.friend_id for friendship in await list_friends(session, owner_id)}
    strangers = [user_id for user_id in target_ids if user_id not in friend_ids]
    if strangers:
        logger.info(
            "친구가 아닌 대상으로 방 생성 시도 (owner_id=%s, %d명)", owner_id, len(strangers)
        )
        raise NotAFriend("친구로 등록한 사용자만 초대할 수 있습니다")


async def _members_by_room(session: AsyncSession, room_ids: list[int]) -> dict[int, list[int]]:
    """여러 방의 참여자 id를 **한 번의 조회로** 모은다.

    `member_user_ids()`를 방마다 부르지 않는 이유가 N+1이다. 그 함수는 U5가 방 하나에
    대해 부르는 계약이고, 목록 화면은 방 전체를 한 번에 다뤄야 한다.
    """
    if not room_ids:
        return {}

    rows = await session.execute(
        sa.select(RoomMember.room_id, RoomMember.user_id)
        .where(RoomMember.room_id.in_(room_ids))
        .order_by(RoomMember.room_id, RoomMember.user_id)
    )
    grouped: dict[int, list[int]] = {room_id: [] for room_id in room_ids}
    for row in rows:
        grouped[row.room_id].append(row.user_id)
    return grouped


async def _display_names_for(
    session: AsyncSession, owner_id: int, members_by_room: dict[int, list[int]]
) -> dict[int, str]:
    """모든 방의 참여자 표시명을 **한 번의 호출로** 해석한다 (FR-2.4, BR-2.8).

    방마다 부르면 U3이 붙여둔 쿼리 횟수 회귀 테스트의 취지가 무너진다 — 그 함수는
    내부적으로 일괄 조회를 하지만, 방마다 부르면 그 일괄 조회가 방 개수만큼 돈다.
    """
    everyone = {user_id for ids in members_by_room.values() for user_id in ids}
    return await resolve_display_names(session, owner_id, list(everyone))


def _name_of(names: dict[int, str], user_id: int) -> str:
    """표시명을 꺼낸다. 없으면 id를 그대로 보여준다.

    `resolve_display_names()`는 `users`에 없는 id를 키에서 아예 뺀다. `room_members`의
    FK가 그 상황을 막으므로 실제로는 도달하지 않지만, `KeyError`로 응답 전체가 500이
    되는 것보다 그 한 명만 이렇게 보이는 편이 낫다.
    """
    return names.get(user_id, f"사용자 {user_id}")


__all__ = [
    "RoomDetail",
    "RoomMemberView",
    "RoomSummary",
    "create_room",
    "get_membership",
    "get_room_detail",
    "list_rooms",
    "mark_read",
    "member_user_ids",
    "set_ai_check",
]

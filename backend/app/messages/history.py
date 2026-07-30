"""메시지 히스토리 — W2의 커서 페이지네이션 (FR-3.3, FR-4.4, BR-4.4).

    GET /rooms/{id}/messages?before=<seq>&limit=50
       1. get_membership() --> None이면 403                (BR-3.3)
       2. WHERE room_id = ? AND (before IS NULL OR seq < ?)
          ORDER BY seq DESC LIMIT min(limit, 100)          (BR-4.4)
       3. friends.resolve_display_names(me, 발신자 id들)   [U3] — **한 번**
       4. 200 [ { message, sender_display_name } ]

**오프셋 페이지네이션을 쓰지 않는다.** 그 사이 메시지가 추가되면 경계가 밀려
중복·누락이 생긴다 — 채팅처럼 목록의 앞쪽이 계속 자라는 자료에서는 반드시 일어난다.

**`before`는 경계를 포함하지 않는다** (`<`). 포함하면 페이지 경계에서 한 건이
매번 중복된다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.friends.service import resolve_display_names
from app.messages.constants import HISTORY_DEFAULT_LIMIT, HISTORY_MAX_LIMIT
from app.messages.exceptions import MessageForbidden
from app.models import Message
from app.rooms.service import get_membership

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageView:
    """히스토리 한 줄 — 저장된 메시지 + **호출자 기준으로 해석된** 발신자 표시명.

    ORM 객체를 그대로 라우터에 넘기지 않는 이유는 U4의 `RoomSummary`와 같다 —
    응답에 무엇이 실리는지를 서비스가 고정한다.
    """

    id: int
    room_id: int
    sender_id: int
    seq: int
    body: str
    verification_status: str
    misdirect_reported_at: datetime | None
    created_at: datetime
    #: `friends.resolve_display_names()`가 해석한 값 (FR-2.4, BR-2.8). 내가 붙인
    #: 별칭이 있으면 그것, 없으면 계정 표시명이다.
    sender_display_name: str


async def list_messages(
    session: AsyncSession,
    user_id: int,
    room_id: int,
    before: int | None = None,
    limit: int = HISTORY_DEFAULT_LIMIT,
) -> list[MessageView]:
    """그 방의 메시지를 `seq` 내림차순으로 돌려준다 — W2.

    Args:
        session: 요청 단위 세션.
        user_id: 호출자. 참여 자격 확인과 표시명 해석의 기준이다.
        room_id: 방.
        before: 이 값**보다 작은** `seq`만 (경계 미포함). `None`이면 최신부터.
        limit: 최대 개수. `HISTORY_MAX_LIMIT`으로 잘린다.

    Raises:
        MessageForbidden: 참여자가 아니거나 없는 방이다 (BR-3.3, 403).

    **표시명 해석이 한 번이다.** 발신자 id를 모아 `resolve_display_names()`를 딱 한 번
    부른다 — 그 함수에는 U3이 붙여둔 **쿼리 횟수 회귀 테스트**가 있고, 반복문 안에서
    부르면 이 경로가 그 테스트의 취지를 무너뜨린다(N+1).
    """
    membership = await get_membership(session, user_id, room_id)
    if membership is None:
        logger.info("참여자가 아닌 방의 히스토리 조회 (user_id=%s, room_id=%s)", user_id, room_id)
        raise MessageForbidden("이 방에 접근할 권한이 없습니다")

    # 상한을 넘는 요청은 거부하지 않고 자른다 (BR-4.4). 하한도 둔다 — `limit=0`이
    # 오면 MariaDB가 빈 결과를 주고 클라이언트는 "끝에 도달했다"로 오해한다.
    page_size = min(max(limit, 1), HISTORY_MAX_LIMIT)

    query = sa.select(Message).where(Message.room_id == room_id)
    if before is not None:
        # `<`이지 `<=`가 아니다. `<=`면 페이지마다 커서 행이 한 번 더 온다.
        query = query.where(Message.seq < before)

    rows = await session.execute(query.order_by(Message.seq.desc()).limit(page_size))
    messages = list(rows.scalars().all())
    if not messages:
        # 빈 방도, 커서가 처음을 지난 것도 오류가 아니다.
        return []

    # `set`으로 모아 한 번에 해석한다 — 같은 사람이 여러 번 보냈어도 조회는 한 번이다.
    sender_ids = {message.sender_id for message in messages}
    names = await resolve_display_names(session, user_id, list(sender_ids))

    return [
        MessageView(
            id=message.id,
            room_id=message.room_id,
            sender_id=message.sender_id,
            seq=message.seq,
            body=message.body,
            verification_status=message.verification_status,
            misdirect_reported_at=message.misdirect_reported_at,
            created_at=message.created_at,
            sender_display_name=_name_of(names, message.sender_id),
        )
        for message in messages
    ]


def _name_of(names: dict[int, str], user_id: int) -> str:
    """표시명을 꺼낸다. 없으면 id를 그대로 보여준다.

    `resolve_display_names()`는 `users`에 없는 id를 키에서 아예 뺀다.
    `messages.sender_id`의 FK가 그 상황을 막으므로 실제로는 도달하지 않지만,
    `KeyError`로 히스토리 전체가 500이 되는 것보다 그 한 명만 이렇게 보이는 편이 낫다.
    U4의 `rooms/service.py`가 같은 판단을 했다.
    """
    return names.get(user_id, f"사용자 {user_id}")


__all__ = ["MessageView", "list_messages"]

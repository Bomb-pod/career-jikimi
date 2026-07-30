"""오발송 신고 — W3 (FR-11.1~FR-11.3, BR-11.1~BR-11.3).

    POST /messages/{id}/report      DELETE /messages/{id}/report
       SELECT messages WHERE id = ?
         +-- 없음 또는 sender_id != me --> 403                (BR-11.1)
       UPDATE messages SET misdirect_reported_at = NOW(6) (또는 NULL)
       200

**`verification_status`를 보지 않는다** (BR-11.2). 6값 어느 상태의 메시지든 신고할 수
있으며, 그것이 이 기능의 존재 이유다 — `flagged_sent`를 제외한 다섯 상태가 사용자
판단에 대한 신호를 남기지 않는 사각지대이고, 신고가 그것을 메운다.

**없는 메시지도 403이다** (BR-11.1). 404를 주면 메시지 id의 존재 여부가 새어나간다.

**남의 메시지는 신고할 수 없다.** 이것은 "내가 잘못 보냈다"는 자기 신고이지 타인
신고 기능이 아니다.
"""

from __future__ import annotations

import logging
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.messages.exceptions import MessageForbidden
from app.models import Message

logger = logging.getLogger(__name__)


async def report(session: AsyncSession, user_id: int, message_id: int) -> datetime:
    """내 메시지를 오발송으로 신고한다 — W3.

    Returns:
        기록된 `misdirect_reported_at`. 클라이언트가 배지를 그리는 근거다.

    Raises:
        MessageForbidden: 남의 메시지이거나 **없는 메시지**다 (BR-11.1, 403).

    **이미 신고된 메시지를 다시 신고해도 200이다.** 시각만 갱신된다 — 멱등한 동작을
    409로 막으면 더블클릭이 사용자에게 오류로 보인다. 이력이 남지 않는 설계이므로
    (BR-11.3) 덮어써도 잃는 정보가 없다.
    """
    message = await _require_own_message(session, user_id, message_id)

    # `NOW(6)`을 DB에서 만든다 — `created_at`이 `CURRENT_TIMESTAMP(6)`이므로 같은
    # 시계를 쓴다. 파이썬의 `datetime.now()`를 넣으면 앱과 DB의 시간대·시계가
    # 어긋나는 만큼 두 컬럼이 서로 다른 시간축에 놓인다.
    await session.execute(
        sa.update(Message)
        .where(Message.id == message_id)
        .values(misdirect_reported_at=sa.text("NOW(6)"))
    )
    # Core UPDATE는 ORM 객체를 갱신하지 않는다. 실제로 기록된 값을 읽어 돌려준다.
    await session.refresh(message, ["misdirect_reported_at"])

    reported_at = message.misdirect_reported_at
    if reported_at is None:  # pragma: no cover - NOW(6)이 NULL일 수 없다
        raise RuntimeError(f"신고 시각이 기록되지 않았습니다: message_id={message_id}")

    logger.info("오발송 신고 (user_id=%s, message_id=%s)", user_id, message_id)
    return reported_at


async def unreport(session: AsyncSession, user_id: int, message_id: int) -> None:
    """신고를 취소한다 — `misdirect_reported_at`을 NULL로 되돌린다 (BR-11.3).

    Raises:
        MessageForbidden: 남의 메시지이거나 **없는 메시지**다 (BR-11.1, 403).

    **이력이 남지 않는다.** 언제 신고했다 취소했는지 알 수 없다 — 별도 신고 테이블을
    두지 않은 대가이며 데모 범위에서 수용한다 (`domain-entities.md`).

    신고되지 않은 메시지에 대해서도 200이다. 취소의 결과 상태가 "신고 안 됨"으로
    같으므로 오류로 다룰 이유가 없다.
    """
    await _require_own_message(session, user_id, message_id)

    await session.execute(
        sa.update(Message).where(Message.id == message_id).values(misdirect_reported_at=None)
    )
    logger.info("오발송 신고 취소 (user_id=%s, message_id=%s)", user_id, message_id)


async def _require_own_message(session: AsyncSession, user_id: int, message_id: int) -> Message:
    """내가 보낸 메시지인지 확인한다. 아니면 403 (BR-11.1).

    **없는 것과 남의 것을 같은 403으로 묶는다.** 나누면 메시지 id의 존재 여부를
    탐색할 수 있다 — U2의 `PATCH /judgments/{id}`, U3의 `PATCH /friends/{id}`가
    같은 판단을 했다.

    `verification_status`를 **읽지 않는다** (BR-11.2). 조건절에 넣을 자리도 두지
    않는 것이 규칙을 지키는 가장 확실한 방법이다.
    """
    message = await session.get(Message, message_id)
    if message is None or message.sender_id != user_id:
        logger.info(
            "신고 권한이 없는 메시지 (user_id=%s, message_id=%s, 존재=%s)",
            user_id,
            message_id,
            message is not None,
        )
        raise MessageForbidden("이 메시지에 대한 권한이 없습니다")
    return message


__all__ = ["report", "unreport"]

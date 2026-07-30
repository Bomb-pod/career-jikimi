"""`rooms` — 채팅방.

출처: `construction/rooms-realtime/functional-design/domain-entities.md` § rooms
소유: U4 rooms-realtime. **U1은 구조만 만들고 읽거나 쓰지 않는다.**
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TABLE_KWARGS, Base


class Room(Base):
    """채팅방 하나.

    생애주기: 생성 후 참여자가 늘거나 줄 뿐 삭제 상태가 없다. 마지막 참여자가
    나가도 방은 남는다 — 메시지가 남아 있어 지우면 히스토리가 깨진다.
    """

    __tablename__ = "rooms"
    __table_args__ = (TABLE_KWARGS,)

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)

    #: NULL 허용. 1:1 방에 이름을 강제하면 사용자가 매번 지어야 하므로,
    #: 비어 있으면 화면이 참여자 표시명으로 조립한다.
    name: Mapped[str | None] = mapped_column(sa.String(100), nullable=True)

    #: 이 방에서 마지막으로 채번된 메시지 seq.
    #:
    #: **소유권의 예외 지점이다 (ADR-003).** 스키마와 초기화는 U4 rooms가 소유하지만
    #: **증가시키는 것은 U5 messages다.** 채번이 메시지 저장과 같은 트랜잭션 안에
    #: 있어야 하기 때문이다 (FR-4.2):
    #:
    #:     BEGIN
    #:       SELECT last_seq FROM rooms WHERE id = ? FOR UPDATE   -- 방 단위 잠금
    #:       INSERT INTO messages (..., seq = last_seq + 1)
    #:       UPDATE rooms SET last_seq = last_seq + 1
    #:     COMMIT
    #:
    #: 이를 U4에 두면 U4가 `messages`에 INSERT하게 되어 소유권이 반대로 깨진다.
    #: U4는 이 값을 **읽기만** 한다 (안 읽은 개수 계산).
    #:
    #: `AUTO_INCREMENT`로 대체할 수 없다 — MariaDB의 AUTO_INCREMENT는 테이블
    #: 전역이라 방 안에서의 단조 증가를 만들 수 없다.
    last_seq: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
    )

    created_by: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", name="fk_rooms_created_by_users"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )

    def __repr__(self) -> str:
        return f"<Room id={self.id} name={self.name!r} last_seq={self.last_seq}>"

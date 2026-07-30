"""`room_members` — 방 참여자와 그 사람의 개인 설정.

출처: `construction/rooms-realtime/functional-design/domain-entities.md` § room_members
소유: U4 rooms-realtime. **U1은 구조만 만들고 읽거나 쓰지 않는다.**
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TABLE_KWARGS, Base


class RoomMember(Base):
    """한 방에 대한 한 사람의 참여 사실과 개인 설정.

    생애주기: 방 생성이나 초대로 추가되고, 나가면 제거된다. 나갔다 다시
    초대되면 `ai_check_enabled`와 `last_read_seq`가 기본값으로 돌아간다 —
    행이 지워졌다 새로 생기기 때문이다.
    """

    __tablename__ = "room_members"
    __table_args__ = (
        # 방 목록 조회(내가 속한 방)의 진입점.
        # 복합 PK의 선행 컬럼이 room_id라서 user_id 단독 조회를 커버하지 못한다 —
        # 그래서 이 인덱스가 별도로 필요하다.
        sa.Index("ix_room_members_user_id", "user_id"),
        TABLE_KWARGS,
    )

    #: 복합 PK `(room_id, user_id)`가 중복 참여를 막는다.
    #: `autoincrement=False`를 명시하는 이유 — SQLAlchemy는 복합 PK의 첫 정수
    #: 컬럼을 AUTO_INCREMENT로 만들려 할 수 있고, 그러면 room_id가 제멋대로 채워진다.
    room_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("rooms.id", name="fk_room_members_room_id_rooms"),
        primary_key=True,
        autoincrement=False,
    )
    user_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", name="fk_room_members_user_id_users"),
        primary_key=True,
        autoincrement=False,
    )

    #: **개인별** AI 검증 설정 (FR-6.1). 방 단위가 아니다.
    #:
    #: 이 컬럼이 `rooms`가 아니라 여기 있는 것이 이 프로젝트의 핵심 결정 하나다.
    #: 이 기능은 "내가 실수하는 걸 막는" 기능이지 남을 위한 것이 아니다. 방장이
    #: 켜면 전원이 1~3초씩 기다리게 되는데, 남이 내 전송 지연을 결정하면 안 된다.
    #:
    #: 신규 방 기본값은 켜짐.
    ai_check_enabled: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        server_default=sa.text("1"),
    )

    #: 안 읽은 개수의 기준 (FR-5.2). 배지 값은 이 값보다 큰 seq를 가진 메시지 수다.
    #:
    #: **전진만 한다** — 이미 더 큰 값이면 갱신을 무시한다 (BR-5.3). 순서가 뒤바뀐
    #: 요청이 배지를 되살리는 것을 막는다. DB 제약으로 표현할 수 없으므로 U4가 강제한다.
    last_read_seq: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("0"),
    )

    joined_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )

    def __repr__(self) -> str:
        return f"<RoomMember room_id={self.room_id} user_id={self.user_id}>"

"""`friendships` — **단방향** 친구 관계.

A가 B를 등록해도 B의 목록에 A는 없다 (FR-2.2).

출처: `construction/auth-friends/functional-design/domain-entities.md` § friendships
소유: U3 auth-friends. **U1은 구조만 만들고 읽거나 쓰지 않는다.**
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TABLE_KWARGS, Base


class Friendship(Base):
    """내가 등록한 친구 한 명.

    생애주기: 등록되면 그 상태로 유지되며 별칭만 바뀐다. 삭제 상태는 없다 —
    친구 삭제는 요구사항에 없다.

    불변식:
      - `(owner_id, friend_id)` 쌍은 유일하다 (UNIQUE 제약이 강제)
      - `owner_id != friend_id` — 자기 자신을 친구로 등록할 수 없다.
        DB 제약으로 표현하기 번거로우므로 **U3이 애플리케이션에서 막는다**
      - `alias`는 트림 후 1자 이상이다. NOT NULL은 빈 문자열을 막지 못하므로
        **공백만 있는 값의 거부는 U3이 한다** (BR-2.2)
    """

    __tablename__ = "friendships"
    __table_args__ = (
        # 같은 상대를 두 번 등록할 수 없다.
        # 친구 목록 조회용 `INDEX (owner_id)`는 따로 만들지 않는다 — 이 UNIQUE의
        # 선행 컬럼이 owner_id라서 같은 조회를 이미 커버한다.
        sa.UniqueConstraint("owner_id", "friend_id", name="uq_friendships_owner_friend"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)

    #: 등록한 쪽.
    owner_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", name="fk_friendships_owner_id_users"),
        nullable=False,
    )

    #: 등록당한 쪽. 이 사람은 자기가 등록당한 사실을 모른다 (단방향, FR-2.2).
    friend_id: Mapped[int] = mapped_column(
        sa.BigInteger,
        sa.ForeignKey("users.id", name="fk_friendships_friend_id_users"),
        nullable=False,
    )

    #: 내가 붙인 이름. **NOT NULL이 이 엔티티의 핵심 제약이다** (FR-2.2).
    #: DB 레벨에서 강제하므로 애플리케이션 버그가 있어도 별칭 없는 행이 생기지 않는다.
    #: 친구 목록에 표시되는 것은 이 값뿐이며 `users.display_name`이 아니다 (FR-2.4).
    alias: Mapped[str] = mapped_column(sa.String(50), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )

    def __repr__(self) -> str:
        return f"<Friendship owner_id={self.owner_id} friend_id={self.friend_id}>"

"""`users` — 가입한 사람. 시스템의 모든 소유권이 여기서 출발한다.

출처: `construction/auth-friends/functional-design/domain-entities.md` § users
소유: U3 auth-friends. **U1은 구조만 만들고 읽거나 쓰지 않는다.**
"""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import TABLE_KWARGS, Base


class User(Base):
    """가입한 사용자.

    생애주기: 생성 후 변하지 않는다. 탈퇴·비활성화는 범위 밖이다.

    불변식:
      - `username`은 전역 유일하다 (UNIQUE 제약이 강제)
      - `password_hash`는 U3 밖으로 나가지 않는다. API 응답에 절대 포함하지 않는다
        (DB로 강제할 수 없는 규칙이라 U3의 스키마 설계가 지켜야 한다)
    """

    __tablename__ = "users"
    __table_args__ = (
        # 이 UNIQUE 인덱스가 중복 방지와 친구 검색(FR-2.1)을 겸한다.
        # 별도 인덱스는 만들지 않는다 — 같은 컬럼에 두 개를 만들 이유가 없다.
        sa.UniqueConstraint("username", name="uq_users_username"),
        TABLE_KWARGS,
    )

    id: Mapped[int] = mapped_column(sa.BigInteger, primary_key=True, autoincrement=True)

    #: 로그인 아이디이자 친구 검색 키 (FR-2.1 — 정확 일치 검색).
    username: Mapped[str] = mapped_column(sa.String(50), nullable=False)

    #: 본인이 설정한 표시명. **친구 목록에는 쓰이지 않는다** (FR-2.4).
    #: 친구가 아닌 방 참여자를 표시할 때의 폴백으로만 쓰인다
    #: (`resolve_display_names()`). FR-2.4가 친구 목록에는 "내가 붙인 별칭만"을
    #: 요구하므로 이 값이 그 자리에 새면 요구사항 위반이다.
    display_name: Mapped[str] = mapped_column(sa.String(50), nullable=False)

    #: bcrypt 또는 argon2 해시. 평문 저장 금지 (FR-1.1). 알고리즘 선택은 U3 몫이다.
    #: 255자는 argon2의 긴 인코딩 형식까지 담기는 길이다.
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)

    #: DATETIME(6) — 마이크로초까지. 서버 기본값으로 채운다.
    created_at: Mapped[datetime] = mapped_column(
        mysql.DATETIME(fsp=6),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP(6)"),
    )

    def __repr__(self) -> str:
        # password_hash를 절대 포함하지 않는다 — 로그·디버거에 해시가 찍히면
        # 그 자체가 유출 경로다 (NFR-6).
        return f"<User id={self.id} username={self.username!r}>"

"""initial schema

테이블 6개를 FK 방향 순서로 만든다. 근거는 형제 4개 단위의 `domain-entities.md`이며
전체 스키마를 U1이 한 번에 세운다 (unit-of-work.md § U1).

생성 순서: users -> friendships -> rooms -> room_members -> messages -> judgment_logs
`downgrade()`는 정확히 역순으로 지운다 — FK가 걸린 테이블을 먼저 지우면 실패한다.

**모든 테이블에 CHARSET/COLLATE를 명시한다** (FR-9.3). 서버 기본값에 기대지 않는다:
compose 인자가 지워지거나 다른 MariaDB에 적용하면 기본값이 utf8mb3/latin1일 수 있고,
그때 한글이 깨지거나 이모지가 잘린다 — 데이터가 이미 망가진 뒤에 드러난다.

Revision ID: 0001
Revises:
Create Date: 2026-07-30

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 여섯 테이블 전부에 붙는다. app/core/db.py의 TABLE_KWARGS와 같은 값이며,
# 마이그레이션은 모델을 import하지 않는 것이 원칙이므로(모델이 바뀌어도 이미 적용된
# 마이그레이션의 의미는 변하지 않아야 한다) 여기서 다시 선언한다.
CHARSET = "utf8mb4"
COLLATE = "utf8mb4_unicode_ci"

NOW6 = sa.text("CURRENT_TIMESTAMP(6)")


def upgrade() -> None:
    # ---------------------------------------------------------------- users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), server_default=NOW6, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        # 중복 방지와 친구 검색(FR-2.1)을 겸한다. 별도 인덱스를 만들지 않는다.
        sa.UniqueConstraint("username", name="uq_users_username"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )

    # ---------------------------------------------------------- friendships
    op.create_table(
        "friendships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("friend_id", sa.BigInteger(), nullable=False),
        # NOT NULL이 이 테이블의 핵심 제약이다 (FR-2.2). 공백만 있는 값의 거부는
        # NOT NULL로 표현할 수 없어 U3이 애플리케이션에서 한다 (BR-2.2).
        sa.Column("alias", sa.String(length=50), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), server_default=NOW6, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_friendships"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_friendships_owner_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["friend_id"], ["users.id"], name="fk_friendships_friend_id_users"
        ),
        # 같은 상대를 두 번 등록할 수 없다. 선행 컬럼이 owner_id라서
        # 친구 목록 조회(INDEX (owner_id))도 이 인덱스가 커버한다.
        sa.UniqueConstraint("owner_id", "friend_id", name="uq_friendships_owner_friend"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )

    # ---------------------------------------------------------------- rooms
    op.create_table(
        "rooms",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        # NULL 허용 — 1:1 방에 이름을 강제하지 않는다. 비면 화면이 참여자로 조립한다.
        sa.Column("name", sa.String(length=100), nullable=True),
        # U4가 소유하되 **U5가 증가시킨다** (ADR-003). 채번이 메시지 저장과 같은
        # 트랜잭션 안에 있어야 하기 때문이다 (FR-4.2).
        sa.Column("last_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.Column("created_at", mysql.DATETIME(fsp=6), server_default=NOW6, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_rooms"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_rooms_created_by_users"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )

    # --------------------------------------------------------- room_members
    op.create_table(
        "room_members",
        sa.Column("room_id", sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.BigInteger(), autoincrement=False, nullable=False),
        # **개인별** 설정 (FR-6.1). 방 단위가 아니다 — 남이 내 전송 지연을 정하면 안 된다.
        sa.Column(
            "ai_check_enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        # 안 읽은 개수의 기준 (FR-5.2). 전진만 한다 (BR-5.3, U4가 강제).
        sa.Column(
            "last_read_seq", sa.BigInteger(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("joined_at", mysql.DATETIME(fsp=6), server_default=NOW6, nullable=False),
        # 복합 PK가 중복 참여를 막는다.
        sa.PrimaryKeyConstraint("room_id", "user_id", name="pk_room_members"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_room_members_room_id_rooms"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_room_members_user_id_users"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    # 방 목록 조회(내가 속한 방)의 진입점. 복합 PK의 선행 컬럼이 room_id라서
    # user_id 단독 조회를 커버하지 못한다 — 그래서 별도로 필요하다.
    op.create_index("ix_room_members_user_id", "room_members", ["user_id"], unique=False)

    # ------------------------------------------------------------- messages
    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_id", sa.BigInteger(), nullable=False),
        # 방 안에서 단조 증가 (FR-4.2). 정렬 기준은 이 컬럼이고 created_at이 아니다.
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "verification_status",
            sa.Enum(
                "ok",
                "flagged_sent",
                "failed",
                "degraded",
                "skipped_no_context",
                "disabled",
                name="verification_status",
            ),
            nullable=False,
        ),
        # 오발송 신고 시각 (FR-11.3). NULL이면 신고되지 않은 상태.
        sa.Column("misdirect_reported_at", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("created_at", mysql.DATETIME(fsp=6), server_default=NOW6, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], name="fk_messages_room_id_rooms"),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"], name="fk_messages_sender_id_users"),
        # 채번 중복을 DB가 최종 방어한다 (FR-4.2).
        sa.UniqueConstraint("room_id", "seq", name="uq_messages_room_seq"),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    # 히스토리 커서 페이지네이션 (FR-4.4). MariaDB 10.8+가 내림차순 인덱스를
    # 실제로 지원한다 — 그 이전 버전은 DESC를 파싱만 하고 무시했다.
    op.create_index(
        "ix_messages_room_seq_desc",
        "messages",
        ["room_id", sa.text("seq DESC")],
        unique=False,
    )

    # -------------------------------------------------------- judgment_logs
    op.create_table(
        "judgment_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("room_id", sa.BigInteger(), nullable=False),
        # NULL 허용 — 취소된 건은 메시지가 없다 (FR-7.2).
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("context_from_seq", sa.BigInteger(), nullable=False),
        sa.Column("context_to_seq", sa.BigInteger(), nullable=False),
        sa.Column("candidate_text", sa.Text(), nullable=False),
        # score/verdict가 함께 NULL인 것이 호출 실패의 표현이다 (FR-8.1).
        sa.Column("score", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "verdict",
            sa.Enum("appropriate", "inappropriate", name="judgment_verdict"),
            nullable=True,
        ),
        # 판정 당시의 임계값. 안 남기면 나중에 판정을 재현할 수 없다.
        sa.Column("threshold", sa.Numeric(precision=4, scale=3), nullable=False),
        # 실패해도 기록한다 — 타임아웃이 몇 초에서 끊겼는지가 관찰값이다.
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        # NULL = 팝업에 응답하지 않고 이탈. 오류가 아니라 관찰값이다 (BR-7.4).
        sa.Column(
            "user_action",
            sa.Enum("auto_sent", "sent", "cancelled", name="judgment_user_action"),
            nullable=True,
        ),
        sa.Column("created_at", mysql.DATETIME(fsp=6), server_default=NOW6, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_judgment_logs"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_judgment_logs_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["rooms.id"], name="fk_judgment_logs_room_id_rooms"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], name="fk_judgment_logs_message_id_messages"
        ),
        mysql_charset=CHARSET,
        mysql_collate=COLLATE,
    )
    # force_log_id 검증 조회(소유자·방·미소비)를 커버한다.
    op.create_index(
        "ix_judgment_logs_user_room_id",
        "judgment_logs",
        ["user_id", "room_id", "id"],
        unique=False,
    )
    # 지표 집계의 기간 필터.
    op.create_index(
        "ix_judgment_logs_created_at", "judgment_logs", ["created_at"], unique=False
    )
    # 집계가 verdict IS NOT NULL로 거르므로 (FR-7.4).
    op.create_index("ix_judgment_logs_verdict", "judgment_logs", ["verdict"], unique=False)


def downgrade() -> None:
    # 생성의 정확한 역순. FK가 걸린 부모 테이블을 먼저 지우면 실패한다.
    op.drop_index("ix_judgment_logs_verdict", table_name="judgment_logs")
    op.drop_index("ix_judgment_logs_created_at", table_name="judgment_logs")
    op.drop_index("ix_judgment_logs_user_room_id", table_name="judgment_logs")
    op.drop_table("judgment_logs")

    op.drop_index("ix_messages_room_seq_desc", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_room_members_user_id", table_name="room_members")
    op.drop_table("room_members")

    op.drop_table("rooms")
    op.drop_table("friendships")
    op.drop_table("users")

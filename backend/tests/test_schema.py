"""초기 마이그레이션이 만든 스키마 검증 — FR-9.3과 전체 스키마의 수용 기준.

**실제 MariaDB에서 돈다.** `TEST_DATABASE_URL`이 없거나 DB에 닿지 못하면 전부
skip된다 (conftest 참조). SQLite로 대체하지 않는 이유는 conftest의 모듈 주석에 있다 —
복합 PK·`utf8mb4`·ENUM은 SQLite에서 거짓 통과한다.

이 테스트가 지키는 계약은 U2~U5 전체의 전제다. 여기가 깨지면 네 단위가 잘못된
스키마 위에서 개발된다.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.conftest import EXPECTED_TABLES

pytestmark = pytest.mark.usefixtures("migrated_database")

#: FR-9.3이 요구하는 값. 서버 기본값이 아니라 DDL에 명시된 값을 확인한다.
EXPECTED_CHARSET = "utf8mb4"
EXPECTED_COLLATION = "utf8mb4_unicode_ci"


async def _insert_returning_id(conn: AsyncConnection, sql: str, params: dict[str, object]) -> int:
    """INSERT 후 새 PK를 돌려준다.

    `LAST_INSERT_ID()`를 따로 묻는 이유 — `text()` 기반 INSERT에서는
    `inserted_primary_key`가 채워지지 않고, `lastrowid`는 드라이버에 따라
    커서 상태에 의존한다.
    """
    await conn.execute(sa.text(sql), params)
    result = await conn.execute(sa.text("SELECT LAST_INSERT_ID()"))
    return int(result.scalar_one())


async def _make_user(conn: AsyncConnection, username: str, display_name: str = "표시명") -> int:
    return await _insert_returning_id(
        conn,
        "INSERT INTO users (username, display_name, password_hash) "
        "VALUES (:username, :display_name, :password_hash)",
        {
            "username": username,
            "display_name": display_name,
            # 해시 자리 채우기 — 이 테스트는 해싱 알고리즘을 검증하지 않는다 (U3 몫).
            "password_hash": "not-a-real-hash",
        },
    )


async def _make_room(conn: AsyncConnection, created_by: int, name: str | None = None) -> int:
    return await _insert_returning_id(
        conn,
        "INSERT INTO rooms (name, created_by) VALUES (:name, :created_by)",
        {"name": name, "created_by": created_by},
    )


async def _insert_message(
    conn: AsyncConnection,
    *,
    room_id: int,
    sender_id: int,
    seq: int,
    body: str = "본문",
    status: str = "ok",
) -> None:
    await conn.execute(
        sa.text(
            "INSERT INTO messages (room_id, sender_id, seq, body, verification_status) "
            "VALUES (:room_id, :sender_id, :seq, :body, :status)"
        ),
        {
            "room_id": room_id,
            "sender_id": sender_id,
            "seq": seq,
            "body": body,
            "status": status,
        },
    )


# --------------------------------------------------------------------------
# 구조
# --------------------------------------------------------------------------
async def test_all_six_tables_exist(db_connection: AsyncConnection) -> None:
    """초기 마이그레이션 하나가 테이블 6개 전부를 만든다.

    스키마를 단위마다 나눠 만들지 않는 것이 U1의 결정이다 — 그러면 마이그레이션
    순서가 단위 순서에 묶여 병렬 작업이 막힌다.
    """
    result = await db_connection.execute(
        sa.text(
            "SELECT TABLE_NAME FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
        )
    )
    present = {row[0] for row in result}

    assert set(EXPECTED_TABLES) <= present
    # alembic이 버전 테이블도 만든다 — 마이그레이션이 실제로 적용됐다는 증거다.
    assert "alembic_version" in present


async def test_every_table_is_utf8mb4(db_connection: AsyncConnection) -> None:
    """6개 테이블 전부가 `utf8mb4` / `utf8mb4_unicode_ci`다 (FR-9.3).

    서버 기본값에 기대지 않고 DDL에 명시했는지를 확인한다. 명시가 없으면 다른
    MariaDB 인스턴스에 마이그레이션을 돌렸을 때 한글이 깨진다.
    """
    result = await db_connection.execute(
        sa.text(
            "SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN :names"
        ).bindparams(sa.bindparam("names", value=list(EXPECTED_TABLES), expanding=True))
    )
    collations = dict(result.all())

    assert set(collations) == set(EXPECTED_TABLES)
    wrong = {name: value for name, value in collations.items() if value != EXPECTED_COLLATION}
    assert not wrong, f"utf8mb4_unicode_ci가 아닌 테이블: {wrong}"


async def test_every_character_column_is_utf8mb4(db_connection: AsyncConnection) -> None:
    """문자 컬럼(VARCHAR·TEXT·ENUM)이 모두 `utf8mb4`다 (FR-9.3).

    테이블 기본값이 맞아도 컬럼에 다른 charset이 붙을 수 있다. 컬럼 단위로 확인한다.
    """
    result = await db_connection.execute(
        sa.text(
            "SELECT TABLE_NAME, COLUMN_NAME, CHARACTER_SET_NAME, COLLATION_NAME "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN :names "
            "AND CHARACTER_SET_NAME IS NOT NULL"
        ).bindparams(sa.bindparam("names", value=list(EXPECTED_TABLES), expanding=True))
    )
    rows = result.all()

    assert rows, "문자 컬럼을 하나도 찾지 못했다 — 조회가 잘못됐다"
    wrong = [
        f"{table}.{column} = {charset}/{collation}"
        for table, column, charset, collation in rows
        if charset != EXPECTED_CHARSET or collation != EXPECTED_COLLATION
    ]
    assert not wrong, f"utf8mb4가 아닌 컬럼: {wrong}"


async def test_enum_columns_carry_the_designed_values(db_connection: AsyncConnection) -> None:
    """세 ENUM의 값 집합이 설계 문서 그대로다.

    `verification_status`의 6값은 "모델 호출을 시도했는가"로 갈린다 (FR-7.1) —
    값이 하나 빠지면 U5가 그 상태를 표현할 수 없고, 하나 늘면 집계가 흐려진다.
    """
    result = await db_connection.execute(
        sa.text(
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND DATA_TYPE = 'enum'"
        )
    )
    enums = {(row[0], row[1]): row[2] for row in result}

    def values(table: str, column: str) -> set[str]:
        raw = enums[(table, column)]
        inner = raw[len("enum(") : -1]
        return {item.strip().strip("'") for item in inner.split(",")}

    assert values("messages", "verification_status") == {
        "ok",
        "flagged_sent",
        "failed",
        "degraded",
        "skipped_no_context",
        "disabled",
    }
    assert values("judgment_logs", "verdict") == {"appropriate", "inappropriate"}
    assert values("judgment_logs", "user_action") == {"auto_sent", "sent", "cancelled"}


async def test_expected_indexes_exist(db_connection: AsyncConnection) -> None:
    """설계가 요구한 인덱스가 전부 있다.

    빠지면 기능은 돌지만 히스토리 조회와 방 목록이 풀스캔이 된다 — 데모에서는
    티가 안 나고, 그래서 지금 확인해야 한다.
    """
    result = await db_connection.execute(
        sa.text(
            "SELECT INDEX_NAME FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME IN :names"
        ).bindparams(sa.bindparam("names", value=list(EXPECTED_TABLES), expanding=True))
    )
    indexes = {row[0] for row in result}

    for expected in (
        "uq_users_username",
        "uq_friendships_owner_friend",
        "ix_room_members_user_id",
        "uq_messages_room_seq",
        "ix_messages_room_seq_desc",
        "ix_judgment_logs_user_room_id",
        "ix_judgment_logs_created_at",
        "ix_judgment_logs_verdict",
    ):
        assert expected in indexes, f"{expected} 인덱스가 없다"


# --------------------------------------------------------------------------
# 제약이 실제로 강제되는가
# --------------------------------------------------------------------------
async def test_messages_room_seq_is_unique(db_connection: AsyncConnection) -> None:
    """`UNIQUE (room_id, seq)`가 채번 중복을 최종 방어한다 (FR-4.2).

    U5의 `FOR UPDATE` 잠금이 1차 방어이고 이 제약이 2차다. 애플리케이션 버그가
    있어도 같은 방에 같은 seq가 두 개 들어가지 않는다 — 들어가면 방 참여자마다
    메시지 순서가 달라지고(NFR-4 위반), 그건 나중에 고칠 수 없는 데이터 손상이다.
    """
    user_id = await _make_user(db_connection, "seq-owner")
    room_id = await _make_room(db_connection, user_id)

    await _insert_message(db_connection, room_id=room_id, sender_id=user_id, seq=1)

    with pytest.raises(IntegrityError):
        await _insert_message(db_connection, room_id=room_id, sender_id=user_id, seq=1)


async def test_same_seq_in_a_different_room_is_allowed(db_connection: AsyncConnection) -> None:
    """seq는 **방 안에서만** 유일하다. 다른 방의 seq 1은 정상이다.

    전역 유일로 잘못 만들면(예: AUTO_INCREMENT) 방 안 연속성이 깨져 FR-4.2를
    충족하지 못한다. 이 테스트가 그 실수를 잡는다.
    """
    user_id = await _make_user(db_connection, "two-rooms")
    first_room = await _make_room(db_connection, user_id, "방 1")
    second_room = await _make_room(db_connection, user_id, "방 2")

    await _insert_message(db_connection, room_id=first_room, sender_id=user_id, seq=1)
    await _insert_message(db_connection, room_id=second_room, sender_id=user_id, seq=1)

    result = await db_connection.execute(sa.text("SELECT COUNT(*) FROM messages WHERE seq = 1"))
    assert result.scalar_one() == 2


async def test_friendships_owner_friend_pair_is_unique(db_connection: AsyncConnection) -> None:
    """`UNIQUE (owner_id, friend_id)` — 같은 상대를 두 번 등록할 수 없다 (FR-2.2)."""
    owner_id = await _make_user(db_connection, "friend-owner")
    friend_id = await _make_user(db_connection, "friend-target")

    insert = (
        "INSERT INTO friendships (owner_id, friend_id, alias) "
        "VALUES (:owner_id, :friend_id, :alias)"
    )
    await db_connection.execute(
        sa.text(insert), {"owner_id": owner_id, "friend_id": friend_id, "alias": "김대리"}
    )

    with pytest.raises(IntegrityError):
        await db_connection.execute(
            sa.text(insert),
            {"owner_id": owner_id, "friend_id": friend_id, "alias": "다른 별칭"},
        )


async def test_reverse_friendship_is_a_separate_row(db_connection: AsyncConnection) -> None:
    """친구 관계는 **단방향**이다 — A→B와 B→A는 독립된 두 행이다 (FR-2.2).

    UNIQUE 제약을 `(owner_id, friend_id)` 순서쌍이 아니라 무순 쌍으로 잘못 만들면
    두 번째 INSERT가 막히고, 상호 친구를 표현할 수 없게 된다.
    """
    a_id = await _make_user(db_connection, "user-a")
    b_id = await _make_user(db_connection, "user-b")
    insert = (
        "INSERT INTO friendships (owner_id, friend_id, alias) "
        "VALUES (:owner_id, :friend_id, :alias)"
    )

    await db_connection.execute(
        sa.text(insert), {"owner_id": a_id, "friend_id": b_id, "alias": "비"}
    )
    await db_connection.execute(
        sa.text(insert), {"owner_id": b_id, "friend_id": a_id, "alias": "에이"}
    )

    result = await db_connection.execute(sa.text("SELECT COUNT(*) FROM friendships"))
    assert result.scalar_one() == 2


async def test_friendship_alias_cannot_be_null(db_connection: AsyncConnection) -> None:
    """`alias` NOT NULL이 DB 레벨에서 강제된다 (FR-2.2).

    이것이 `friendships`의 핵심 제약이다 — 애플리케이션 버그가 있어도 별칭 없는
    행이 생기지 않는다. (공백만 있는 값은 NOT NULL로 막을 수 없어 U3이 거른다.)
    """
    owner_id = await _make_user(db_connection, "alias-owner")
    friend_id = await _make_user(db_connection, "alias-target")

    with pytest.raises(IntegrityError):
        await db_connection.execute(
            sa.text(
                "INSERT INTO friendships (owner_id, friend_id, alias) "
                "VALUES (:owner_id, :friend_id, NULL)"
            ),
            {"owner_id": owner_id, "friend_id": friend_id},
        )


async def test_room_members_composite_pk_blocks_duplicate_membership(
    db_connection: AsyncConnection,
) -> None:
    """복합 PK `(room_id, user_id)`가 중복 참여를 막는다.

    **SQLite로는 검증되지 않는 종류의 제약이다** — conftest가 실제 MariaDB를
    요구하는 이유 중 하나다.
    """
    user_id = await _make_user(db_connection, "member-user")
    room_id = await _make_room(db_connection, user_id)

    insert = "INSERT INTO room_members (room_id, user_id) VALUES (:room_id, :user_id)"
    await db_connection.execute(sa.text(insert), {"room_id": room_id, "user_id": user_id})

    with pytest.raises(IntegrityError):
        await db_connection.execute(sa.text(insert), {"room_id": room_id, "user_id": user_id})


async def test_room_member_defaults_are_applied(db_connection: AsyncConnection) -> None:
    """`ai_check_enabled`는 기본 **켜짐**, `last_read_seq`는 0이다 (FR-6.1, FR-5.2).

    기본값이 꺼짐이면 사용자가 아무것도 안 했을 때 검증이 돌지 않아, 이 프로젝트가
    보여주려는 기능이 데모에서 안 보인다.
    """
    user_id = await _make_user(db_connection, "defaults-user")
    room_id = await _make_room(db_connection, user_id)

    await db_connection.execute(
        sa.text("INSERT INTO room_members (room_id, user_id) VALUES (:room_id, :user_id)"),
        {"room_id": room_id, "user_id": user_id},
    )
    result = await db_connection.execute(
        sa.text(
            "SELECT ai_check_enabled, last_read_seq FROM room_members "
            "WHERE room_id = :room_id AND user_id = :user_id"
        ),
        {"room_id": room_id, "user_id": user_id},
    )
    ai_check_enabled, last_read_seq = result.one()

    assert bool(ai_check_enabled) is True
    assert last_read_seq == 0
    # rooms.last_seq도 0에서 시작한다 — U5가 여기서 +1로 채번한다 (ADR-003).
    room_seq = await db_connection.execute(
        sa.text("SELECT last_seq FROM rooms WHERE id = :room_id"), {"room_id": room_id}
    )
    assert room_seq.scalar_one() == 0


# --------------------------------------------------------------------------
# FR-9.3의 수용 기준: 한글·이모지 왕복
# --------------------------------------------------------------------------
async def test_korean_and_emoji_round_trip(db_connection: AsyncConnection) -> None:
    """한글과 이모지가 포함된 값이 깨지지 않고 원본과 일치한다.

    FR-9.3의 수용 기준 그대로다:
        Given 한글과 이모지가 포함된 메시지
        When 저장하고 다시 조회하면
        Then 문자가 깨지지 않고 원본과 일치한다

    이모지는 4바이트라 `utf8mb3`에서는 저장 시점에 잘리거나 `?`로 바뀐다 —
    이 테스트가 `utf8mb4` 명시의 실질적 검증이다.
    """
    body = "부장님 이거 진짜 웃기죠 ㅋㅋㅋ 🤣🔥 안녕하세요 — 전각 문자 ｜ 𝄞"
    alias = "김부장 🙇"
    display_name = "홍길동 😀"

    sender_id = await _make_user(db_connection, "emoji-sender", display_name)
    friend_id = await _make_user(db_connection, "emoji-friend")
    room_id = await _make_room(db_connection, sender_id, "회사 단톡방 💼")

    await db_connection.execute(
        sa.text(
            "INSERT INTO friendships (owner_id, friend_id, alias) "
            "VALUES (:owner_id, :friend_id, :alias)"
        ),
        {"owner_id": sender_id, "friend_id": friend_id, "alias": alias},
    )
    await _insert_message(db_connection, room_id=room_id, sender_id=sender_id, seq=1, body=body)

    stored_body = await db_connection.execute(
        sa.text("SELECT body FROM messages WHERE room_id = :room_id AND seq = 1"),
        {"room_id": room_id},
    )
    stored_alias = await db_connection.execute(
        sa.text("SELECT alias FROM friendships WHERE owner_id = :owner_id"),
        {"owner_id": sender_id},
    )
    stored_display = await db_connection.execute(
        sa.text("SELECT display_name FROM users WHERE id = :user_id"), {"user_id": sender_id}
    )
    stored_room_name = await db_connection.execute(
        sa.text("SELECT name FROM rooms WHERE id = :room_id"), {"room_id": room_id}
    )

    assert stored_body.scalar_one() == body
    assert stored_alias.scalar_one() == alias
    assert stored_display.scalar_one() == display_name
    assert stored_room_name.scalar_one() == "회사 단톡방 💼"

"""동시 채번 — **NFR-7이 이 단위에 지운 두 테스트 의무 중 하나** (FR-4.2).

`business-logic-model.md` § 테스트 대상이 이것을 지목한 이유는 하나다:
**눈으로 검증할 수 없다.** 순차 전송은 `FOR UPDATE`가 없어도 통과한다 — 잠금이
실제로 무엇을 하는지는 두 요청이 정말 겹쳐야만 드러난다.

그래서 이 파일은 다른 테스트들과 달리 **savepoint 픽스처를 쓰지 않는다.**
`db_bound_sessionmaker`는 커넥션 하나 위에 세션을 얹으므로 동시성이 만들어지지
않는다 — 커넥션이 하나면 두 요청이 물리적으로 겹칠 수 없고, 통과해도 아무것도
증명하지 못한다. 여기서는 **별도 커넥션 여러 개**를 열고 실제로 커밋한다.

검증 대상:

| 무엇 | 왜 |
|---|---|
| 같은 방 동시 전송 → seq가 중복 없이 연속 | FR-4.2의 본문 |
| **다른 방은 막히지 않는다** | 행 잠금이지 테이블 잠금이 아님 (ADR-003) |
| `SELECT ... FOR UPDATE`가 실제 SQL에 있다 | 잠금이 코드에 남아 있는지 |
| `UNIQUE (room_id, seq)`가 최종 방어선 | 잠금이 실패해도 중복이 안 들어감 |
| 판정이 잠금 **밖**에서 끝난다 | BR-4.3 — 잠금 안의 외부 호출 금지 |
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.messages import service
from app.models import Message, Room, RoomMember, User
from tests.conftest import capture_sql, make_room, make_user
from tests.messaging_support import (
    FakeJudge,
    appropriate,
    make_log,
    seed_membership,
    seed_messages,
)

#: 같은 방에 동시에 밀어넣는 전송 수. 커넥션 풀 기본값(5 + overflow 10) 안이다.
CONCURRENT_SENDS = 8

#: 잠긴 방의 전송이 "정말 막혀 있는지" 관찰하는 시간. 짧게 잡는 이유는 통과 조건이
#: "이 시간 안에 끝나지 **않는다**"이기 때문이다 — 길게 잡을수록 테스트만 느려진다.
BLOCKED_OBSERVE_SECONDS = 0.6

#: 잠금이 풀린 뒤 완료를 기다리는 상한. 넉넉히 준다 — 여기서 걸리면 그것은
#: 타이밍이 아니라 교착이다.
RELEASE_TIMEOUT_SECONDS = 10.0


async def _seed_room(factory: Any, username: str, room_name: str) -> tuple[int, int]:
    """사용자 하나와 방 하나를 **커밋해서** 만든다. `(user_id, room_id)`.

    `ai_check_enabled=False`로 두는 이유 — 이 파일이 검증하는 것은 채번이지 판정이
    아니다. 토글을 끄면 전송 경로가 `disabled`로 흘러 외부 호출이 아예 일어나지
    않고, 남는 것은 잠금과 INSERT뿐이다.
    """
    async with factory() as session:
        user = await make_user(session, username)
        room = await make_room(session, user.id, room_name)
        await seed_membership(session, room.id, [user.id], ai_check_enabled=False)
        await session.commit()
        return user.id, room.id


async def _send(factory: Any, user_id: int, room_id: int, text: str) -> Any:
    """자기 커넥션을 가진 세션 하나로 전송한다."""
    async with factory() as session:
        return await service.send_message(session, user_id, room_id, text)


# --------------------------------------------------------------------------
# 같은 방 동시 전송 (FR-4.2)
# --------------------------------------------------------------------------
async def test_concurrent_sends_to_one_room_produce_contiguous_seq(live_sessionmaker: Any) -> None:
    """FR-4.2의 본문 — **실제로 동시에** 보내도 seq가 중복 없이 1..N으로 이어진다.

    `asyncio.gather`로 띄우고 세션마다 커넥션이 다르므로 여덟 트랜잭션이 정말 겹친다.
    `FOR UPDATE`가 없으면 여럿이 같은 `last_seq`를 읽어 같은 seq를 만들고,
    `UNIQUE (room_id, seq)` 때문에 대부분이 `IntegrityError`로 죽는다.
    """
    user_id, room_id = await _seed_room(live_sessionmaker, "seq_alice", "동시 채번")

    outcomes = await asyncio.gather(
        *(
            _send(live_sessionmaker, user_id, room_id, f"동시 전송 {index}")
            for index in range(CONCURRENT_SENDS)
        )
    )

    seqs = sorted(outcome.message.seq for outcome in outcomes)
    assert seqs == list(range(1, CONCURRENT_SENDS + 1))
    # 중복이 없다는 것은 위 등식에 이미 포함되지만, 실패했을 때 무엇이 틀렸는지
    # 바로 보이도록 따로 남긴다.
    assert len(set(seqs)) == CONCURRENT_SENDS


async def test_concurrent_sends_leave_room_last_seq_consistent(live_sessionmaker: Any) -> None:
    """`rooms.last_seq`가 마지막 메시지의 seq와 같다.

    여기가 어긋나면 다음 전송이 이미 쓰인 seq를 다시 채번한다 — 그때는 오늘이 아니라
    **내일** 실패한다. 채번과 갱신이 한 트랜잭션인지가 이 한 줄로 드러난다 (BR-4.2).
    """
    user_id, room_id = await _seed_room(live_sessionmaker, "seq_bob", "last_seq 정합")

    await asyncio.gather(
        *(
            _send(live_sessionmaker, user_id, room_id, f"동시 전송 {index}")
            for index in range(CONCURRENT_SENDS)
        )
    )

    async with live_sessionmaker() as session:
        last_seq = await session.scalar(sa.select(Room.last_seq).where(Room.id == room_id))
        stored = await session.scalar(
            sa.select(sa.func.max(Message.seq)).where(Message.room_id == room_id)
        )
        stored_count = await session.scalar(
            sa.select(sa.func.count(Message.id)).where(Message.room_id == room_id)
        )

    assert last_seq == CONCURRENT_SENDS
    assert stored == CONCURRENT_SENDS
    # 구멍도 없다 — 개수와 최대값이 같다.
    assert stored_count == CONCURRENT_SENDS


# --------------------------------------------------------------------------
# 다른 방은 막히지 않는다 (ADR-003)
# --------------------------------------------------------------------------
async def test_a_locked_room_does_not_block_another_room(live_sessionmaker: Any) -> None:
    """방 A의 잠금이 방 B의 전송을 지연시키지 않는다.

    **이것이 MariaDB를 고른 이유 중 하나다** — InnoDB의 행 잠금이라 `rooms`의 한 행만
    잠기고 다른 행은 자유롭다. 테이블 잠금이었다면 방 하나의 느린 전송이 서비스
    전체를 멈춘다.

    잠금을 직접 잡는다(트랜잭션을 열어둔 채 `FOR UPDATE`). 그 상태에서 방 B로
    보내면 즉시 끝나야 한다.
    """
    alice, room_a = await _seed_room(live_sessionmaker, "seq_carol", "방 A")
    async with live_sessionmaker() as session:
        room_b_row = await make_room(session, alice, "방 B")
        await seed_membership(session, room_b_row.id, [alice], ai_check_enabled=False)
        await session.commit()
        room_b = room_b_row.id

    holder = live_sessionmaker()
    try:
        # 방 A의 행을 잡고 놓지 않는다.
        await holder.execute(sa.select(Room.last_seq).where(Room.id == room_a).with_for_update())

        outcome = await asyncio.wait_for(
            _send(live_sessionmaker, alice, room_b, "다른 방은 자유롭다"),
            timeout=RELEASE_TIMEOUT_SECONDS,
        )
        assert outcome.message.seq == 1
    finally:
        await holder.rollback()
        await holder.close()


async def test_a_locked_room_blocks_that_room_until_release(live_sessionmaker: Any) -> None:
    """같은 방의 전송은 잠금이 풀릴 때까지 **실제로 기다린다.**

    앞 테스트의 짝이다. "다른 방이 안 막힌다"만 보면 잠금이 아예 없어도 통과하므로,
    **잠긴 방은 정말 막히는지**를 함께 확인해야 `FOR UPDATE`가 동작한다는 결론이 선다.

    취소로 검증하지 않는 이유 — 진행 중인 쿼리를 취소하면 그 커넥션이 어중간한
    상태로 남는다. 대신 잠금을 풀어 **완료되는 것까지** 본다.
    """
    alice, room_a = await _seed_room(live_sessionmaker, "seq_dave", "잠긴 방")

    holder = live_sessionmaker()
    blocked = asyncio.create_task(_send(live_sessionmaker, alice, room_a, "잠금이 풀리면 저장된다"))
    try:
        await holder.execute(sa.select(Room.last_seq).where(Room.id == room_a).with_for_update())
        # 잠금을 잡은 뒤에 태스크가 실제로 DB까지 갔는지 확인한다.
        done, _pending = await asyncio.wait({blocked}, timeout=BLOCKED_OBSERVE_SECONDS)
        assert done == set(), "잠긴 방의 전송이 대기하지 않았다 — FOR UPDATE가 없다"
    finally:
        await holder.rollback()
        await holder.close()

    outcome = await asyncio.wait_for(blocked, timeout=RELEASE_TIMEOUT_SECONDS)
    assert outcome.message.seq == 1


# --------------------------------------------------------------------------
# 잠금이 SQL에 실제로 있는가 + 판정이 잠금 밖인가
# --------------------------------------------------------------------------
async def test_send_emits_select_for_update(db_session: Any) -> None:
    """발생한 SQL에 `SELECT ... FOR UPDATE`가 **실제로 있다**.

    위 두 테스트가 동작을 보고, 이 테스트가 **구현을 본다.** 둘 다 필요한 이유는
    나중에 누가 `with_for_update()`를 빼도 단일 커넥션 테스트는 통과하기 때문이다.
    """
    alice = await make_user(db_session, "sql_alice")
    room = await make_room(db_session, alice.id, "SQL 확인")
    await seed_membership(db_session, room.id, [alice.id], ai_check_enabled=False)

    with capture_sql() as statements:
        await service.send_message(db_session, alice.id, room.id, "잠금 확인")

    locking = [item for item in statements if "FOR UPDATE" in item.upper()]
    assert len(locking) == 1, f"FOR UPDATE가 정확히 한 번이어야 한다: {statements}"
    assert "rooms" in locking[0].lower()


async def test_judgment_happens_before_the_lock_is_taken(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BR-4.3 — 판정이 **잠금을 잡기 전에** 끝난다.

    3~5초짜리 외부 호출을 `FOR UPDATE`와 `COMMIT` 사이에 두면 그 방의 모든 전송이
    그동안 대기한다. 순서를 문장 단위로 확인한다: 판정이 불린 시점까지 나간 SQL 수가
    `FOR UPDATE`의 위치보다 앞이어야 한다.

    **트랜잭션 안에 외부 호출이 하나도 없다**는 주장이 이 한 줄로 검증된다.
    """
    alice = await make_user(db_session, "order_alice")
    room = await make_room(db_session, alice.id, "순서 확인")
    await seed_membership(db_session, room.id, [alice.id])
    await seed_messages(db_session, room.id, alice.id, 10)
    log = await make_log(db_session, alice.id, room.id, "순서 확인 메시지", verdict="appropriate")
    await db_session.commit()

    seen: list[int] = []
    with capture_sql() as statements:
        fake = FakeJudge(appropriate(log.id), on_call=lambda: seen.append(len(statements)))
        monkeypatch.setattr(service, "judge", fake)
        await service.send_message(db_session, alice.id, room.id, "순서 확인 메시지")

        for_update_at = next(
            index for index, item in enumerate(statements) if "FOR UPDATE" in item.upper()
        )

    assert fake.calls, "판정이 호출되지 않았다 — 준비가 잘못됐다"
    assert (
        seen[0] <= for_update_at
    ), f"판정이 잠금 뒤에 호출됐다 (판정 시점={seen[0]}, FOR UPDATE={for_update_at})"


# --------------------------------------------------------------------------
# 최종 방어선 (UNIQUE)
# --------------------------------------------------------------------------
async def test_duplicate_seq_is_rejected_by_the_unique_constraint(db_session: Any) -> None:
    """`UNIQUE (room_id, seq)`가 중복 seq를 거부한다.

    **잠금의 대체재가 아니라 최종 방어선이다.** 여기까지 왔다는 것은 이미 요청 하나가
    실패했다는 뜻이지만, 그래도 잘못된 데이터가 들어가는 것보다는 낫다 — 한번
    들어가면 `seq` 정렬과 히스토리 커서가 통째로 어긋난다.
    """
    alice = await make_user(db_session, "uniq_alice")
    room = await make_room(db_session, alice.id, "유니크")
    db_session.add(
        Message(
            room_id=room.id, sender_id=alice.id, seq=1, body="첫 번째", verification_status="ok"
        )
    )
    await db_session.flush()

    db_session.add(
        Message(
            room_id=room.id, sender_id=alice.id, seq=1, body="같은 seq", verification_status="ok"
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


async def test_the_same_seq_in_a_different_room_is_allowed(db_session: Any) -> None:
    """제약이 `(room_id, seq)` 복합이라 **다른 방의 같은 seq는 허용된다.**

    경계 사례다. `seq`에 전역 UNIQUE를 걸면 방마다 1부터 시작하는 설계가 불가능해진다
    — 그것이 `AUTO_INCREMENT`를 쓸 수 없는 이유이기도 하다.
    """
    alice = await make_user(db_session, "uniq_bob")
    first = await make_room(db_session, alice.id, "방 1")
    second = await make_room(db_session, alice.id, "방 2")

    db_session.add_all(
        [
            Message(
                room_id=first.id, sender_id=alice.id, seq=1, body="A", verification_status="ok"
            ),
            Message(
                room_id=second.id, sender_id=alice.id, seq=1, body="B", verification_status="ok"
            ),
        ]
    )
    await db_session.flush()

    stored = await db_session.scalar(sa.select(sa.func.count(Message.id)))
    assert stored == 2


# --------------------------------------------------------------------------
# 준비 헬퍼가 실제로 격리되는지 (픽스처의 자기 검증)
# --------------------------------------------------------------------------
async def test_live_fixture_cleans_up_after_itself(live_sessionmaker: Any) -> None:
    """`live_sessionmaker`가 남긴 행이 없는 상태에서 시작한다.

    이 픽스처만 실제로 커밋하므로, 앞 테스트의 정리가 새면 여기서 드러난다.
    격리가 깨진 채로 도는 테스트는 통과해도 아무것도 보장하지 않는다.
    """
    async with live_sessionmaker() as session:
        users = await session.scalar(sa.select(sa.func.count(User.id)))
        members = await session.scalar(sa.select(sa.func.count(RoomMember.user_id)))

    assert users == 0
    assert members == 0

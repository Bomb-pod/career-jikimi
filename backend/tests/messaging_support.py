"""U5 messaging 테스트가 공유하는 준비 헬퍼.

`conftest.py`에 두지 않은 이유 — 이 단위에만 쓰이는 준비 코드이고, 공용 conftest는
다섯 단위가 모두 읽는 파일이다. 파일명이 `test_`로 시작하지 않아 pytest가 수집하지
않는다.

**판정을 가짜로 갈아끼우는 두 헬퍼가 이 모듈의 핵심이다.** 실제 OpenAI 호출은 어떤
테스트에서도 하지 않는다 — 비용과 비결정성 이전에, 판정의 내부는 U2가 이미 검증했고
이 단위가 검증할 것은 **세 갈래를 어떻게 분기하는가**뿐이다.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from app.judgment.types import Appropriate, Failed, Inappropriate, JudgeResult
from app.models import JudgmentLog, Message, Room, RoomMember


async def seed_membership(
    session: Any,
    room_id: int,
    user_ids: list[int],
    *,
    ai_check_enabled: bool = True,
) -> None:
    """참여자 행을 심는다. `create_room()`을 거치지 않는 이유는 친구 관계(BR-3.2)를
    준비하지 않고도 전송 경로만 격리해 검증하기 위해서다.
    """
    session.add_all(
        [
            RoomMember(
                room_id=room_id,
                user_id=user_id,
                ai_check_enabled=ai_check_enabled,
                last_read_seq=0,
            )
            for user_id in user_ids
        ]
    )
    await session.flush()


async def seed_messages(
    session: Any,
    room_id: int,
    sender_id: int,
    count: int,
    *,
    status: str = "ok",
    start_seq: int = 1,
) -> list[Message]:
    """방에 메시지 `count`개를 심고 `rooms.last_seq`를 맞춘다.

    콜드스타트(BR-6.2)를 넘기려면 방에 `AI_CONTEXT_N`개가 있어야 한다 — 그 준비가
    거의 모든 전송 테스트의 첫 줄이다.

    **`rooms.last_seq`를 함께 올리는 것이 중요하다.** 안 맞추면 다음 채번이 1부터
    다시 시작해 `UNIQUE (room_id, seq)`에 걸린다 — 테스트가 실패하되 이유가
    전송 로직처럼 보인다.
    """
    messages = [
        Message(
            room_id=room_id,
            sender_id=sender_id,
            seq=start_seq + offset,
            body=f"준비 메시지 {start_seq + offset}",
            verification_status=status,
        )
        for offset in range(count)
    ]
    session.add_all(messages)
    await session.flush()

    last_seq = start_seq + count - 1
    await session.execute(sa.update(Room).where(Room.id == room_id).values(last_seq=last_seq))
    await session.flush()
    return messages


async def count_logs(session: Any, user_id: int) -> int:
    """그 사용자의 판정 로그 개수. "로그를 남기지 않는다"를 확인하는 데 쓴다."""
    result = await session.scalar(
        sa.select(sa.func.count(JudgmentLog.id)).where(JudgmentLog.user_id == user_id)
    )
    return int(result or 0)


async def make_log(
    session: Any,
    user_id: int,
    room_id: int,
    candidate_text: str,
    *,
    verdict: str | None,
    score: float | None = None,
    user_action: str | None = None,
) -> JudgmentLog:
    """판정 로그 하나를 직접 심는다 — 강행 전송 테스트의 준비.

    `judge()`를 부르지 않고 심는 이유 — 강행 전송이 보는 것은 **로그의 상태**뿐이며,
    `verdict=NULL`(호출 실패) 로그를 실제 실패로 만들어내려면 클라이언트까지
    가짜로 갈아끼워야 한다. 여기서 필요한 것은 그 결과 상태 하나다.
    """
    log = JudgmentLog(
        user_id=user_id,
        room_id=room_id,
        context_from_seq=1,
        context_to_seq=10,
        candidate_text=candidate_text,
        threshold=0.700,
        latency_ms=123,
        verdict=verdict,
        score=score,
        user_action=user_action,
    )
    session.add(log)
    await session.flush()
    return log


class FakeJudge:
    """`judge()`를 대신하는 호출 기록기.

    **`judge()`와 같은 시그니처를 지킨다.** 인자 이름이나 개수가 달라지면 이 가짜가
    통과시키는 호출을 진짜가 거부하게 되고, 그 차이는 테스트가 아니라 배포에서
    드러난다.

    `on_call`은 호출 **시점**을 관찰하는 훅이다 — "판정이 트랜잭션 밖인가"를 확인할
    때 그 순간까지 나간 SQL을 세는 데 쓴다.
    """

    def __init__(self, result: JudgeResult, on_call: Any = None) -> None:
        self.result = result
        self.on_call = on_call
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        session: Any,
        user_id: int,
        room_id: int,
        context: list[Any],
        candidate_text: str,
    ) -> JudgeResult:
        self.calls.append(
            {
                "user_id": user_id,
                "room_id": room_id,
                "context": list(context),
                "candidate_text": candidate_text,
            }
        )
        if self.on_call is not None:
            self.on_call()
        # 진짜 `judge()`는 로그 행을 만들고 **커밋한다**. 그 커밋이 호출자의 세션
        # 상태에 영향을 주므로(뒤이어 열리는 채번 트랜잭션이 새로 시작된다) 가짜도
        # 같은 일을 한다 — 그러지 않으면 실제와 다른 트랜잭션 경계를 검증하게 된다.
        await session.commit()
        return self.result


def appropriate(log_id: int, score: float = 0.10) -> Appropriate:
    return Appropriate(score, log_id)


def inappropriate(log_id: int, score: float = 0.93) -> Inappropriate:
    return Inappropriate(score, log_id)


def failed(log_id: int) -> Failed:
    return Failed(log_id)


__all__ = [
    "FakeJudge",
    "appropriate",
    "count_logs",
    "failed",
    "inappropriate",
    "make_log",
    "seed_membership",
    "seed_messages",
]

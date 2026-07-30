"""메시지 전송 오케스트레이션 — W1의 9단계.

**앞의 네 단위가 여기서 만난다.** `send_message()` 하나가 U2 판정, U3 표시명, U4 방·
WebSocket, U1 세션·설정을 전부 엮는다. 이 단위가 XL인 이유다.

`business-rules.md` § 규칙 판정 순서의 7단계 그대로다:

    1. BR-3.3  참여자 자격 + 토글 조회 (get_membership 1회)
    2. BR-6.4  force_log_id 있으면 검증 → 로그의 verdict에서 상태 파생
    3. BR-6.1  없으면 상태 결정 (disabled / degraded / cold / 호출)
    4. BR-4.3  판정 (트랜잭션 밖)
    5. BR-6.3  부적절이면 409 반환하고 종료
    6. BR-4.2  트랜잭션: 채번 + 저장
    7. BR-4.1  커밋 후 브로드캐스트

**틀리면 가장 크게 다치는 세 가지**를 여기 먼저 적는다:

1. **판정은 트랜잭션이 열리기 전에 끝난다** (BR-4.3). 3~5초짜리 외부 호출을 행
   잠금 안에 넣으면 그 방의 모든 전송이 그동안 막힌다.
2. **브로드캐스트는 커밋 뒤다** (BR-4.1, NFR-3). 안에 두면 커밋 전에 나갈 수 있고,
   롤백되면 화면에만 있는 유령 메시지가 남는다.
3. **채번 트랜잭션 안에 외부 호출이 하나도 없다** (BR-4.2, ADR-003).
   `UNIQUE (room_id, seq)`는 최종 방어선이지 채번 메커니즘이 아니다.

**`component-methods.md`의 이 함수 산문은 낡았다** — "네 가지를 검증한 뒤
`flagged_sent`로 진행"이라 적혀 있고 `NULL` verdict → `failed` 분기가 없다.
functional-design 리뷰어가 잔여 항목으로 기록했다. 충돌하면 `functional-design/`가
권위다.

대응: FR-4.1~FR-4.3, FR-6.4~FR-6.6, FR-7.1, FR-8.2·FR-8.3·FR-8.5, NFR-3.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.ws_registry import push_to_users
from app.judgment.service import (
    VERDICT_INAPPROPRIATE,
    get_log_for_force,
    judge,
    link_message,
    set_user_action,
)
from app.judgment.types import Appropriate, ContextMessage, Failed, Inappropriate
from app.messages.constants import MESSAGE_MAX_LENGTH
from app.messages.exceptions import MessageForbidden, MessageTooLong
from app.models import Message, Room, RoomMember
from app.rooms.service import get_membership, member_user_ids

logger = logging.getLogger(__name__)

#: `verification_status`의 6값 중 이 모듈이 직접 붙이는 것들.
#: 호출 결과 세 값(`ok`·`flagged_sent`·`failed`)도 여기서 붙지만 **판단은 U2가**
#: 한다 — 이 모듈은 `JudgeResult` 세 갈래를 상태 문자열로 옮길 뿐이다.
STATUS_OK: Final[str] = "ok"
STATUS_FLAGGED_SENT: Final[str] = "flagged_sent"
STATUS_FAILED: Final[str] = "failed"
STATUS_DEGRADED: Final[str] = "degraded"
STATUS_SKIPPED_NO_CONTEXT: Final[str] = "skipped_no_context"
STATUS_DISABLED: Final[str] = "disabled"

#: 강행 전송·자동 전송이 판정 로그에 남기는 라벨 (BR-6.4, FR-7.2).
ACTION_SENT: Final[str] = "sent"
ACTION_AUTO_SENT: Final[str] = "auto_sent"

#: 409 두 종의 판별자. **상태 코드를 나누지 않는다** — 503을 쓰면 클라이언트가
#: 네트워크 오류와 헷갈린다. 여기서 실패한 것은 판정이지 요청이 아니다.
REASON_INAPPROPRIATE: Final[str] = "inappropriate"
REASON_JUDGE_FAILED: Final[str] = "judge_failed"


# --------------------------------------------------------------------------
# 반환 타입 — 판별 가능한 두 갈래
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Sent:
    """저장·브로드캐스트까지 끝났다 — 201."""

    message: Message


@dataclass(frozen=True)
class Blocked:
    """저장하지 않았다 — 409. `reason`이 판별자다 (BR-6.3, BR-8.2).

    Attributes:
        log_id: 클라이언트가 강행할 때 `force_log_id`로 되돌려 보낼 값.
        reason: `inappropriate`(부적절 판정) 또는 `judge_failed`(판정 실패).
        score: 부적절 판정일 때만 있다. **판정 실패에는 점수가 없다** —
            만들어 주면 클라이언트가 그것을 판정으로 착각한다 (U2 `Failed` 참조).
    """

    log_id: int
    reason: Literal["inappropriate", "judge_failed"]
    score: float | None = None


#: `send_message()`의 반환 타입. **이 둘이 전부다.**
SendOutcome = Sent | Blocked


@dataclass(frozen=True)
class _Decision:
    """저장하기로 정해진 뒤의 결론 — 이 모듈 안에서만 쓴다.

    Attributes:
        status: `messages.verification_status`에 넣을 6값 중 하나.
        log_id: 남길 판정 로그. 호출하지 않은 세 값(`disabled`·`degraded`·
            `skipped_no_context`)은 `None`이다 (BR-6.1, BR-6.2).
        user_action: 그 로그에 남길 사용자 라벨. `sent`(강행) / `auto_sent`(적절
            판정으로 묻지 않고 전송) / `None`(물을 일이 없었다).

    **`user_action`을 여기에 담아 저장 트랜잭션까지 미루는 것이 의도다.** 결정
    시점에 바로 쓰면 그 UPDATE가 read view를 열어(아래 `_persist` 참조) 채번의
    잠금 읽기가 깨지고, 저장이 실패해도 라벨만 남는다.
    """

    status: str
    log_id: int | None = None
    user_action: str | None = None


# --------------------------------------------------------------------------
# W1 · 전송
# --------------------------------------------------------------------------
async def send_message(
    session: AsyncSession,
    user_id: int,
    room_id: int,
    text: str,
    force_log_id: int | None = None,
    degraded: bool = False,
    probe: bool = False,
) -> SendOutcome:
    """메시지를 판정하고 채번해 저장한 뒤 브로드캐스트한다 — W1.

    Args:
        session: 요청 단위 세션.
        user_id: 보내는 사람.
        room_id: 보낼 방.
        text: 본문. **트림하지 않는다** — U2의 텍스트 일치 검사가 원문을 기준으로
            삼으므로, 여기서 손대면 강행 전송이 자기 자신과 어긋난다.
        force_log_id: 팝업에서 "보내기"/"수락"을 고른 경우의 판정 로그 id (BR-6.4).
        degraded: **클라이언트가 degraded 상태인가** (ADR-007). 서버가 알 수 없는
            브라우저 탭 단위 상태라 클라이언트가 알려준다.
        probe: **이번 전송이 프로브인가** (BR-8.5). degraded 중에도 5번째마다 한 번은
            판정을 시도하는데, 그 차례 판단(`shouldProbe()`)이 클라이언트에 있다.

    Returns:
        `Sent(message)` 또는 `Blocked(log_id, reason, score)`.

    Raises:
        MessageForbidden: 참여자가 아니거나 없는 방이다 (BR-3.3, 403).
        MessageTooLong: 본문이 상한을 넘었다 (400).
        InvalidForceToken: `force_log_id`가 쓸 수 없는 값이다 (U2, 400).
        ForceTokenForbidden: 남의 판정 로그다 (U2, 403).
        AlreadyResolved: 그 로그에 이미 응답이 기록되어 있다 (U2, 409).

    **`degraded`와 `probe`가 별개 인자인 이유.** BR-6.1의 2번 규칙이
    "degraded **이고 프로브 차례가 아님**"이고, 5b가 "판정 실패 + 프로브면 저장하고
    201"이다. 두 판단 모두 서버가 해야 하므로 서버가 둘을 알아야 한다. 프로브를
    `degraded=false`로 위장해 보내면 서버가 프로브 실패와 세션 첫 실패를 구분하지
    못해 팝업이 뜨고, BR-8.5의 "팝업 없이 조용히 진행"이 깨진다.
    """
    # ---- 1. BR-3.3 — 참여자 자격과 토글을 한 번의 조회로 (get_membership 1회) ----
    membership = await get_membership(session, user_id, room_id)
    if membership is None:
        logger.info("참여자가 아닌 방에 전송 시도 (user_id=%s, room_id=%s)", user_id, room_id)
        raise MessageForbidden("이 방에 접근할 권한이 없습니다")

    # 본문 길이는 **가장 싼 검사**다. 판정도 채번도 시작하기 전에 걸러낸다.
    if len(text) > MESSAGE_MAX_LENGTH:
        raise MessageTooLong(f"메시지는 {MESSAGE_MAX_LENGTH}자를 넘을 수 없습니다")

    if force_log_id is not None:
        # ---- 2. BR-6.4 — 강행 전송. 상태를 **로그의 verdict에서** 파생한다 ----
        decided = await _resolve_forced(session, user_id, room_id, force_log_id, text)
    else:
        # ---- 3~5. BR-6.1 상태 결정 → BR-4.3 판정(트랜잭션 밖) → BR-6.3 409 ----
        decided = await _decide(session, user_id, room_id, text, membership, degraded, probe)
        if isinstance(decided, Blocked):
            # 5a·5b — 저장하지 않고 끝난다. `messages` INSERT가 없다.
            return decided

    # ---- 6~7. BR-4.2 — 채번과 저장. **외부 호출이 하나도 없다** ----
    message = await _persist(session, user_id, room_id, text, decided)

    # ---- 8. BR-4.1 — **커밋 뒤** 브로드캐스트 ----
    await _broadcast(session, room_id, message)

    # ---- 9. 201 ----
    return Sent(message)


# --------------------------------------------------------------------------
# 2. 강행 전송 (BR-6.4)
# --------------------------------------------------------------------------
async def _resolve_forced(
    session: AsyncSession,
    user_id: int,
    room_id: int,
    force_log_id: int,
    text: str,
) -> _Decision:
    """`force_log_id`를 검증하고 그 로그의 `verdict`에서 상태를 파생한다.

    | 로그의 `verdict` | 결과 상태 | 왜 |
    |---|---|---|
    | `inappropriate` | `flagged_sent` | 경고를 보고도 보냈다 |
    | NULL (호출 실패) | `failed` | 검증을 **시도했으나** 못 받고 보냈다 |

    **이것이 FR-8.3의 "수락한 그 메시지는 `failed`"를 실제로 성립시키는 장치다.**
    `degraded` 플래그만 세워 재요청하면 BR-6.1의 우선순위(2번 규칙)에 걸려
    `degraded`로 저장되고, "판정을 시도했다"는 사실이 사라진다. 두 값을 나눠 둔
    이유(FR-7.1) 자체가 여기서 무너진다.

    `user_action='sent'`는 **두 갈래 모두**에 붙는다 (BR-6.4) — "경고 또는 미검증을
    알고도 보냈다"가 둘의 공통 의미다. 이 기록이 토큰 소진이기도 하다:
    `set_user_action()`의 조건부 UPDATE가 같은 로그로 두 번 보내는 것을 막는다.
    **그 UPDATE는 저장 트랜잭션 안에서 일어난다** — 여기서 미리 쓰면 저장이 실패해도
    토큰만 소진되어, 사용자가 같은 판정으로 다시 보낼 수 없게 된다.
    """
    # 여섯 검사(존재/소유자/방/미소진/텍스트 일치/verdict)는 전부 U2가 한다.
    # 여기서 다시 검사하면 규칙이 두 벌이 되고, 한쪽만 바뀌는 날 우회 경로가 생긴다.
    log = await get_log_for_force(session, user_id, room_id, force_log_id, text)

    status = STATUS_FLAGGED_SENT if log.verdict == VERDICT_INAPPROPRIATE else STATUS_FAILED

    logger.info(
        "강행 전송 (user_id=%s, room_id=%s, log_id=%s, status=%s)",
        user_id,
        room_id,
        force_log_id,
        status,
    )
    return _Decision(status=status, log_id=force_log_id, user_action=ACTION_SENT)


# --------------------------------------------------------------------------
# 3~5. 상태 결정과 판정 (BR-6.1, BR-4.3, BR-6.3, BR-8.2, BR-8.5)
# --------------------------------------------------------------------------
async def _decide(
    session: AsyncSession,
    user_id: int,
    room_id: int,
    text: str,
    membership: RoomMember,
    degraded: bool,
    probe: bool,
) -> _Decision | Blocked:
    """`verification_status`를 정한다. 저장하지 않을 경우 `Blocked`를 돌려준다.

    **BR-6.1의 순서 그대로이며 첫 번째로 걸리는 것을 적용한다:**

        1. 토글 꺼짐              -> disabled            (호출 안 함, 로그 없음)
        2. degraded이고 프로브 아님 -> degraded            (호출 안 함, 로그 없음)
        3. 방 메시지 < AI_CONTEXT_N -> skipped_no_context  (호출 안 함, 로그 없음)
        4. 그 외                   -> judge()

    **순서에 실질적 의미가 있다.** 싼 판정부터 한다 — 토글이 꺼져 있으면 콜드스타트를
    따질 필요가 없고, degraded면 문맥 조회(DB 1회)를 아예 아낀다. 2번이 3번보다
    앞인 것이 그 절약이다.
    """
    if not membership.ai_check_enabled:
        # 1. 사용자가 스스로 껐다 (FR-6.1). 판정 로그도 남기지 않는다.
        return _Decision(STATUS_DISABLED)

    if degraded and not probe:
        # 2. degraded 구간 — 호출하지 않는다 (BR-8.5). 아래 문맥 조회를 건너뛴다.
        return _Decision(STATUS_DEGRADED)

    # 3. 콜드스타트 (BR-6.2). **개수를 세지 않고 최근 N개를 바로 가져온다** —
    #    N개 미만이 돌아오면 그것이 곧 "방 메시지 수 < N"이다. COUNT(*) 한 번과
    #    SELECT 한 번을 하나로 접는다.
    context_n = settings.AI_CONTEXT_N
    context = await _recent_context(session, room_id, context_n)
    if len(context) < context_n:
        logger.info(
            "문맥 부족으로 판정을 건너뜁니다 (room_id=%s, %d/%d)",
            room_id,
            len(context),
            context_n,
        )
        return _Decision(STATUS_SKIPPED_NO_CONTEXT)

    # 4. BR-4.3 — **트랜잭션 밖에서** 판정한다.
    #
    # 여기까지 세션에 커밋되지 않은 쓰기가 없다(위는 전부 SELECT다). `judge()`가
    # 내부에서 커밋하므로 그 전제가 깨지면 남의 쓰기가 함께 커밋된다.
    result = await judge(session, user_id, room_id, context, text)

    if isinstance(result, Inappropriate):
        # 5a. BR-6.3 — **저장하지 않는다.** 사용자가 강행하면 이 log_id가
        #     force_log_id로 돌아온다.
        logger.info(
            "부적절 판정으로 전송을 보류합니다 (user_id=%s, room_id=%s, log_id=%s)",
            user_id,
            room_id,
            result.log_id,
        )
        return Blocked(log_id=result.log_id, reason=REASON_INAPPROPRIATE, score=result.score)

    if isinstance(result, Failed):
        if probe:
            # 5b(예) — 프로브 실패는 **팝업이 없다** (BR-8.5). 조용히 저장하고 201을
            # 준다. 사용자는 이미 degraded를 수락해 두었으므로 다시 묻지 않는다.
            logger.info(
                "프로브 실패 — degraded를 유지하고 failed로 저장합니다 (room_id=%s)", room_id
            )
            return _Decision(STATUS_FAILED, log_id=result.log_id)
        # 5b(아니오) — 세션 첫 실패다. **저장하지 않고** 묻는다 (BR-8.1, BR-8.2).
        logger.info(
            "판정 실패로 전송을 보류합니다 (user_id=%s, room_id=%s, log_id=%s)",
            user_id,
            room_id,
            result.log_id,
        )
        return Blocked(log_id=result.log_id, reason=REASON_JUDGE_FAILED)

    if not isinstance(result, Appropriate):  # pragma: no cover - 방어적 분기
        raise TypeError(f"알 수 없는 판정 결과입니다: {type(result).__name__}")

    # 적절 — 묻지 않고 보낸다. 그 사실을 `auto_sent`로 남긴다 (FR-7.2).
    # **여기서 쓰지 않고 저장 트랜잭션까지 미룬다** (`_Decision` 참조).
    return _Decision(STATUS_OK, log_id=result.log_id, user_action=ACTION_AUTO_SENT)


async def _recent_context(session: AsyncSession, room_id: int, limit: int) -> list[ContextMessage]:
    """판정 문맥 — 그 방의 최근 `limit`개를 **`seq` 오름차순**으로 (BR-6.1).

    **오래된 것이 먼저다.** judgment-core가 `context[0].seq`를 `context_from_seq`로,
    `context[-1].seq`를 `context_to_seq`로 쓴다 — 뒤집으면 두 값이 뒤바뀌어 로그의
    범위가 거꾸로 남고, 프롬프트의 대화도 역순으로 읽힌다.

    `ContextMessage`는 U2의 값 객체이며 **세 필드**다. `seq`가 필수인 이유가 위의
    두 NOT NULL 컬럼이다 — 계획 문서상 2필드였으나 U2가 구현하며 추가했다.
    """
    rows = await session.execute(
        sa.select(Message.sender_id, Message.body, Message.seq)
        .where(Message.room_id == room_id)
        # 최근 N개를 고르려면 내림차순으로 잘라야 한다. 오름차순 정렬은 아래에서.
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    newest_first = list(rows.all())
    return [
        ContextMessage(sender_id=row.sender_id, text=row.body, seq=row.seq)
        for row in reversed(newest_first)
    ]


# --------------------------------------------------------------------------
# 6~7. 채번과 저장 (BR-4.2, ADR-003)
# --------------------------------------------------------------------------
async def _persist(
    session: AsyncSession,
    user_id: int,
    room_id: int,
    text: str,
    decision: _Decision,
) -> Message:
    """`seq`를 채번해 메시지를 저장하고 커밋한다.

        BEGIN                                                  <- 여기서 연다
          SELECT last_seq FROM rooms WHERE id = ? FOR UPDATE   -- 방 단위 행 잠금
          INSERT INTO messages (..., seq = last_seq + 1)
          UPDATE rooms SET last_seq = last_seq + 1
          UPDATE judgment_logs SET message_id = ?               -- 로그가 있으면
          UPDATE judgment_logs SET user_action = ?              -- 라벨이 있으면
        COMMIT

    **`FOR UPDATE`가 행 잠금을 건다.** InnoDB의 행 잠금이라 같은 방만 직렬화되고
    다른 방의 전송은 막지 않는다 — MariaDB를 고른 이유 중 하나다(ADR-003).

    **이 블록 안에 외부 호출이 하나도 없다.** 판정은 이미 끝났고 브로드캐스트는
    커밋 뒤다. 여기 3~5초짜리 호출이 들어가면 그 방의 모든 전송이 그동안 대기한다.

    **첫 줄의 `commit()`이 없으면 동시 전송이 깨진다.** MariaDB의 InnoDB는
    REPEATABLE READ에서 이미 read view가 열린 트랜잭션이 그 스냅숏 이후에 갱신된
    행을 잠금 읽기로 잡으려 하면 `1020 Record has changed since last read`를 낸다
    (MySQL은 최신 커밋본을 돌려주지만 MariaDB는 오류다). 1~5단계의 조회가 이미
    read view를 열어 두었으므로, 잠금 읽기를 **새 트랜잭션의 첫 문장**으로 만들어야
    한다. 이 시점에 커밋되지 않은 쓰기는 없다 — `judge()`는 내부에서 커밋하고,
    `user_action` 기록은 `_Decision`에 담겨 아래로 미뤄져 있다.

    `link_message()`와 `set_user_action()`이 커밋 **안**에 있는 것은 원자성 때문이다.
    밖에 두면 메시지는 저장됐는데 로그와 연결되지 않거나, 반대로 토큰만 소진되고
    메시지는 없는 행이 남는다. 둘 다 DB 호출이라 잠금 시간에 실질적 영향이 없다.

    Raises:
        AlreadyResolved: 같은 `force_log_id`로 이미 보냈다 (BR-7.1, 409). 잠금 안에서
            나므로 이 메시지도 함께 롤백된다 — 더블클릭에 두 개가 저장되지 않는다.
    """
    # 위 주석 참조. 열려 있는 read view를 닫아 잠금 읽기를 새 트랜잭션의 첫 문장으로
    # 만든다. 쓸 것이 없으므로 이 커밋 자체는 아무것도 바꾸지 않는다.
    await session.commit()

    last_seq = await session.scalar(
        sa.select(Room.last_seq).where(Room.id == room_id).with_for_update()
    )
    if last_seq is None:
        # 참여 행은 있는데 방이 없다 = FK가 보장하는 불변식이 깨진 상태다.
        # 사용자에게는 같은 403을 주되(존재 여부를 새게 하지 않는다) 경고를 남긴다.
        logger.error("참여 행은 있으나 방이 없습니다 (room_id=%s)", room_id)
        raise MessageForbidden("이 방에 접근할 권한이 없습니다")

    seq = last_seq + 1
    message = Message(
        room_id=room_id,
        sender_id=user_id,
        seq=seq,
        body=text,
        verification_status=decision.status,
    )
    session.add(message)
    # `flush()`가 INSERT를 보내 `message.id`를 채운다. 아직 커밋이 아니다.
    await session.flush()

    await session.execute(sa.update(Room).where(Room.id == room_id).values(last_seq=seq))

    if decision.log_id is not None:
        await link_message(session, decision.log_id, message.id)
        if decision.user_action is not None:
            # 조건부 UPDATE다 — 동시 요청 둘이 모두 통과하는 경로가 없다. 두 번째는
            # `AlreadyResolved`(409)로 떨어지고 그 트랜잭션이 통째로 롤백된다.
            await set_user_action(session, decision.log_id, decision.user_action)

    await session.commit()

    # `created_at`은 `CURRENT_TIMESTAMP(6)` 서버 기본값이라 커밋 시점까지 파이썬 쪽에
    # 값이 없다. **커밋 뒤에** 읽어온다 — 잠금 안에서 읽으면 그만큼 잠금이 길어지고,
    # 읽지 않으면 async 지연 로드가 응답 직렬화 중에 터진다.
    await session.refresh(message, ["created_at"])

    logger.info(
        "메시지를 저장했습니다 (room_id=%s, message_id=%s, seq=%s, status=%s)",
        room_id,
        message.id,
        seq,
        decision.status,
    )
    return message


# --------------------------------------------------------------------------
# 8. 브로드캐스트 (BR-4.1, NFR-3)
# --------------------------------------------------------------------------
async def _broadcast(session: AsyncSession, room_id: int, message: Message) -> None:
    """참여자 전원에게 밀어낸다. **커밋이 끝난 뒤에만 호출된다.**

    **발신자도 대상에 포함된다** (BR-5.8) — 다른 탭·기기의 세션도 갱신되어야 하고,
    중복은 클라이언트가 메시지 ID로 제거한다 (FR-4.3).

    **`sender_display_name`을 프레임에 담지 않는다.** 표시명은 보는 사람마다 다르다
    (내가 붙인 별칭, FR-2.4) — 하나의 프레임을 전원에게 보내는 이 경로에서는 누구의
    표시명을 담아도 나머지에게 틀린다. 클라이언트는 방 참여자 목록에서 해석한다.

    **실패해도 예외를 올리지 않는다.** 메시지는 이미 커밋되었고, 여기서 터지면
    `get_session()`이 롤백을 시도하지만 되돌릴 것이 없는 채로 사용자만 500을 본다.
    연결이 없는 사용자는 다음 입장 시 히스토리로 받으므로 유실이 아니다
    (`push_to_users()`가 이미 소켓 단위 실패를 흡수한다).
    """
    recipients = await member_user_ids(session, room_id)
    payload = {
        "type": "message",
        "room_id": room_id,
        "message": _message_frame(message),
    }
    try:
        await push_to_users(recipients, payload)
    except Exception:
        # 조용히 삼키지 않는다 — 경고로 남긴다. 전송 자체는 성공이다.
        logger.warning("브로드캐스트에 실패했습니다 (room_id=%s)", room_id, exc_info=True)


def _message_frame(message: Message) -> dict[str, Any]:
    """WebSocket 프레임에 싣는 메시지 표현. HTTP 201 본문과 같은 필드다.

    두 경로의 모양을 같게 두는 이유 — 클라이언트가 같은 병합 함수로 다루므로
    한쪽에만 필드가 있으면 중복 제거 시 나중 것이 앞의 것을 덮으며 필드가 사라진다.
    """
    return {
        "id": message.id,
        "room_id": message.room_id,
        "sender_id": message.sender_id,
        "seq": message.seq,
        "body": message.body,
        "verification_status": message.verification_status,
        "misdirect_reported_at": (
            None
            if message.misdirect_reported_at is None
            else message.misdirect_reported_at.isoformat()
        ),
        "created_at": message.created_at.isoformat(),
    }


__all__ = [
    "ACTION_AUTO_SENT",
    "ACTION_SENT",
    "REASON_INAPPROPRIATE",
    "REASON_JUDGE_FAILED",
    "STATUS_DEGRADED",
    "STATUS_DISABLED",
    "STATUS_FAILED",
    "STATUS_FLAGGED_SENT",
    "STATUS_OK",
    "STATUS_SKIPPED_NO_CONTEXT",
    "Blocked",
    "SendOutcome",
    "Sent",
    "send_message",
]

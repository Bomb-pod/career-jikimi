"""판정 서비스 — `judge()`와 판정 로그의 생애주기.

`unit-of-work-dependency.md`가 기록한 **U2가 U5에 제공하는 계약**이 이 파일에 있다.
**시그니처를 바꾸면 U5가 깨진다:**

    judge(session, user_id, room_id, context, candidate_text) -> JudgeResult
    get_log_for_force(session, user_id, room_id, log_id, candidate_text) -> JudgmentLog
    set_user_action(session, log_id, action) -> None          # AlreadyResolved
    link_message(session, log_id, message_id) -> None

**이 단위는 `users`·`rooms`·`messages`를 판정 경로에서 읽지 않는다.** 문맥은 U5가
조회해 인자로 넘긴다 — 그래서 이 단위가 채팅 앱 없이 돈다. 예외는 `metrics.py`의
신고 관련 두 지표뿐이다.

대응: FR-6.2·FR-6.3·FR-7.2·FR-8.1, BR-6.1·BR-6.2·BR-6.5~BR-6.9, BR-7.1.
"""

from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.judgment.client import call_model
from app.judgment.constants import SCORE_DECIMAL_PLACES, SCORE_MAX, SCORE_MIN
from app.judgment.exceptions import AlreadyResolved, ForceTokenForbidden, InvalidForceToken
from app.judgment.prompt import build_messages
from app.judgment.types import (
    Appropriate,
    ContextMessage,
    Failed,
    Inappropriate,
    JudgeResult,
)
from app.models import JudgmentLog

logger = logging.getLogger(__name__)

#: `judgment_logs.verdict`의 두 값. `app.models.VERDICT_VALUES`와 같은 것이며,
#: 여기서는 비교에 쓰는 이름으로 다시 묶는다.
VERDICT_APPROPRIATE: Final[str] = "appropriate"
VERDICT_INAPPROPRIATE: Final[str] = "inappropriate"

#: `DECIMAL(4,3)`에 맞춘 양자화 단위.
_SCORE_QUANTUM: Final[Decimal] = Decimal(1).scaleb(-SCORE_DECIMAL_PLACES)


def _to_decimal(value: float) -> Decimal:
    """`DECIMAL(4,3)`에 넣을 값으로 반올림한다.

    드라이버가 조용히 자르게 두지 않는다 — `0.8567`이 `0.856`이 될지 `0.857`이
    될지가 드라이버 구현에 달리면 같은 점수가 환경마다 다르게 저장된다.
    """
    return Decimal(repr(value)).quantize(_SCORE_QUANTUM, rounding=ROUND_HALF_UP)


def _clamp(score: float) -> float:
    """점수를 `[0.0, 1.0]`으로 자른다 — **실패로 처리하지 않는다** (BR-6.6).

    JSON 스키마의 `number`는 범위를 강제하지 않아 모델이 1.2를 줄 수 있다.
    실패로 처리하면 멀쩡한 판정을 버리게 된다 — 1.2는 "매우 부적절"이라는 뜻이지
    "모델이 고장났다"는 뜻이 아니다.
    """
    return min(SCORE_MAX, max(SCORE_MIN, score))


async def judge(
    session: AsyncSession,
    user_id: int,
    room_id: int,
    context: list[ContextMessage],
    candidate_text: str,
) -> JudgeResult:
    """문맥에 비추어 후보 문장을 판정한다 — W1.

    Args:
        session: 요청 단위 세션.
        user_id: 보내려는 사람이자 로그 소유자. `force_log_id` 소유권 검증에 쓰인다.
        room_id: 방.
        context: 최근 `AI_CONTEXT_N`개, **오래된 것부터** (BR-6.1). U5가 조회해 넘긴다.
        candidate_text: 판정 대상 문장. 트림하지 않고 원문 그대로 저장한다 —
            BR-6.9의 텍스트 일치 검사가 이 값을 기준으로 삼는다.

    Returns:
        `Appropriate` / `Inappropriate` / `Failed` 셋 중 하나. **`Failed`는 예외가
        아니라 반환값이다** (BR-6.7).

    Raises:
        ValueError: `context`가 비었다. **호출자의 계약 위반이지 판정 실패가 아니다** —
            `context_from_seq`·`context_to_seq`가 NOT NULL이라 빈 문맥은 남길 범위가
            없다. 실제 경로에서는 U5가 문맥 부족을 먼저 걸러낸다 (FR-6.4). 이 예외는
            로그 행을 만들기 **전에** 나므로 API 실패율에 섞이지 않는다.

    **모델 호출의 어떤 실패도 이 함수 밖으로 나가지 않는다** (BR-6.7). 타임아웃·
    연결 오류·5xx·429·설정 오류가 전부 `Failed`가 된다. DB 오류는 다르다 — 그것은
    판정 실패가 아니라 진짜 오류라서 그대로 올라간다.

    `business-rules.md` § 규칙 판정 순서의 9단계 그대로다:

        1. 문맥 구성(입력 검증)  2. 익명화  3. 프롬프트 조립
        4. 로그 행 생성  5. 호출+재시도  6. 클램프  7. 임계값 판정
        8. 로그 갱신  9. 반환
    """
    # 1. BR-6.1 — 문맥 구성. 범위를 남길 수 없으면 로그 자체가 성립하지 않는다.
    if not context:
        raise ValueError(
            "판정 문맥이 비어 있습니다. 방 메시지가 AI_CONTEXT_N개 미만이면 "
            "호출자가 skipped_no_context로 건너뛰어야 합니다 (FR-6.4)"
        )

    threshold = float(settings.AI_VERDICT_THRESHOLD)

    # 2~3. BR-6.2 익명화 + BR-6.3 프롬프트 조립. 이 안에서 sender_id가 라벨로 바뀐다.
    messages = build_messages(context, user_id, candidate_text)

    # 4. 로그 행을 **호출보다 먼저** 만든다 (BR-6.8).
    log = JudgmentLog(
        user_id=user_id,
        room_id=room_id,
        # 후보 문장은 아직 seq가 없다(저장 전이므로). `to_seq`는 문맥의 마지막
        # 메시지의 seq다 (BR-6.1).
        context_from_seq=context[0].seq,
        context_to_seq=context[-1].seq,
        candidate_text=candidate_text,
        threshold=_to_decimal(threshold),
        # NOT NULL이라 자리를 채운다. 호출이 끝나면 실제 대기 시간으로 덮어쓴다.
        latency_ms=0,
    )
    session.add(log)
    await session.flush()
    # **커밋한다.** flush만 하면 트랜잭션 안에만 있어서, 호출 중 프로세스가 죽으면
    # 행이 사라진다 — BR-6.8이 요구하는 "시도한 흔적"이 그때 없어지고 API 실패율이
    # 실제보다 낮게 나온다. 호출자는 `judge()` 앞에 커밋되지 않은 쓰기를 세션에
    # 남기지 않아야 한다(U5는 판정 뒤에 저장 트랜잭션을 연다).
    await session.commit()
    log_id: int = log.id
    # 커밋 뒤에도 `log`의 속성을 읽고 쓸 수 있는 것은 U1의 세션 팩토리가
    # `expire_on_commit=False`이기 때문이다 (`core/db.py`). 그 설정이 바뀌면
    # 여기서 만료된 속성에 접근하며 async 지연 로드가 터진다.

    # 5. BR-6.7 — 호출 + 타임아웃 + 재시도 1회. 예외가 올라오지 않는다.
    call = await call_model(messages)

    # BR-6.8 — 실패해도 실제 대기 시간을 남긴다.
    log.latency_ms = call.latency_ms

    if not call.ok or call.score is None:
        # `score`·`verdict`를 NULL로 **유지**한다. 그 조합이 호출 실패를 표현하는
        # 방식이며(FR-8.1), 집계는 `verdict IS NOT NULL`로 걸러 이 행을 precision에서
        # 제외하되 API 실패율에는 포함한다 (BR-7.2).
        await session.flush()
        await session.commit()
        logger.info(
            "판정 실패로 기록했습니다 (log_id=%s, kind=%s, %dms)",
            log_id,
            call.error_kind,
            call.latency_ms,
        )
        return Failed(log_id)

    # 6. BR-6.6 — 클램프. 범위 밖을 실패로 처리하지 않는다.
    score = _clamp(call.score)
    if score != call.score:
        logger.info("모델 점수 %s를 %s로 클램프했습니다 (log_id=%s)", call.score, score, log_id)

    # 7. BR-6.5 — 임계값 판정. **같으면 부적절이다.**
    verdict = VERDICT_INAPPROPRIATE if score >= threshold else VERDICT_APPROPRIATE

    # 8. 로그 갱신.
    log.score = _to_decimal(score)
    log.verdict = verdict
    log.prompt_tokens = call.prompt_tokens
    log.completion_tokens = call.completion_tokens
    await session.flush()
    await session.commit()

    # 9. 반환.
    if verdict == VERDICT_INAPPROPRIATE:
        return Inappropriate(score, log_id)
    return Appropriate(score, log_id)


async def get_log_for_force(
    session: AsyncSession,
    user_id: int,
    room_id: int,
    log_id: int,
    candidate_text: str,
) -> JudgmentLog:
    """`force_log_id`가 이 재요청에 쓸 수 있는 토큰인지 검증한다 — W2, BR-6.9.

    Args:
        session: 요청 단위 세션.
        user_id: 호출자.
        room_id: 재요청이 향하는 방.
        log_id: 클라이언트가 보낸 `force_log_id`.
        candidate_text: 재요청의 본문. **원래 판정받은 문장과 같아야 한다.**

    Returns:
        검증을 통과한 로그. 호출자가 `verdict`로 결과 상태를 파생한다:

        | 로그의 `verdict` | `verification_status` |
        |---|---|
        | `inappropriate` | `flagged_sent` — 경고를 보고 보냈다 |
        | NULL (호출 실패) | `failed` — 검증을 시도했으나 못 받고 보냈다 |

    Raises:
        ForceTokenForbidden: 남의 로그다 (403). **여섯 검사 중 유일한 403이다.**
        InvalidForceToken: 나머지 다섯 중 하나 (400).

    검사 순서는 `business-rules.md` BR-6.9의 표 그대로다 — 존재 / 소유자 / 방 /
    미소진 / 텍스트 일치 / `verdict`. (`business-logic-model.md` W2 다이어그램은
    마지막 둘의 순서가 반대지만, 둘 다 같은 400이라 결과는 같다.)

    **텍스트 일치 검사가 `application-design`에서 이월된 구멍의 해소다.** 없으면
    소유자·방·미소진을 만족하는 토큰에 *다른 문장*을 실어 판정 없이 `flagged_sent`로
    통과시킬 수 있다. UI로는 도달할 수 없지만 API 직접 호출로는 가능하다.

    **NULL `verdict`를 허용하는 것이 FR-8.3을 성립시키는 장치다.** 판정 실패를
    사용자가 수락했을 때 그 메시지는 `failed`여야 하는데(시도는 했으므로),
    `degraded` 플래그만 세워 재요청하면 우선순위 규칙에 걸려 `degraded`로 저장된다.
    `force_log_id`가 "이 시도는 이미 있었다"를 전달한다.
    """
    log = await session.get(JudgmentLog, log_id)

    if log is None:
        logger.info("존재하지 않는 force_log_id (log_id=%s, user_id=%s)", log_id, user_id)
        raise InvalidForceToken("판정 결과를 찾을 수 없습니다. 다시 시도해 주세요")

    if log.user_id != user_id:
        # **유일한 403.** 남의 판정 로그로 강행 전송하는 것을 막는다.
        logger.warning(
            "다른 사용자의 판정 로그로 강행 전송을 시도했습니다 (log_id=%s, user_id=%s)",
            log_id,
            user_id,
        )
        raise ForceTokenForbidden("이 판정 결과에 대한 권한이 없습니다")

    if log.room_id != room_id:
        logger.info("방이 다른 force_log_id (log_id=%s, room_id=%s)", log_id, room_id)
        raise InvalidForceToken("다른 방의 판정 결과입니다. 다시 시도해 주세요")

    if log.user_action is not None:
        # 소진됨 — 이미 보내거나 취소한 판정이다. 이 검사가 1회성의 절반이고,
        # 나머지 절반은 `set_user_action()`의 조건부 UPDATE다 (BR-7.1).
        logger.info("이미 소진된 force_log_id (log_id=%s)", log_id)
        raise InvalidForceToken("이미 처리된 판정 결과입니다. 다시 시도해 주세요")

    # **트림 후 정확 일치.** 정규화(공백 축약·유니코드 정규화)를 하지 않는다 —
    # 정규화할수록 "같다"의 범위가 넓어지고, 넓어진 만큼 우회 여지가 생긴다.
    if log.candidate_text.strip() != candidate_text.strip():
        logger.warning(
            "force_log_id의 텍스트가 재요청과 다릅니다 (log_id=%s, user_id=%s)",
            log_id,
            user_id,
        )
        raise InvalidForceToken("판정받은 메시지와 내용이 다릅니다. 다시 시도해 주세요")

    if log.verdict == VERDICT_APPROPRIATE:
        # 적절 판정은 이미 자동 전송되었으므로 강행할 대상이 아니다. 막지 않으면
        # 그 경로로 판정을 건너뛸 수 있다.
        logger.info("적절 판정 로그로 강행 전송을 시도했습니다 (log_id=%s)", log_id)
        raise InvalidForceToken("이 판정 결과는 강행 전송 대상이 아닙니다")

    return log


async def set_user_action(session: AsyncSession, log_id: int, action: str) -> None:
    """판정 로그에 사용자의 선택을 기록한다 — W3, BR-7.1.

    Args:
        session: 요청 단위 세션.
        log_id: 판정 로그.
        action: `auto_sent` / `sent` / `cancelled` 중 하나.

    Raises:
        AlreadyResolved: 이미 값이 있거나 그 로그가 없다 (409).

    **원자적 조건부 갱신이다.** `WHERE id = ? AND user_action IS NULL`로 한 문장에
    검사와 갱신을 담고, 영향 행이 0이면 예외를 던진다. SELECT 후 UPDATE로 짜면
    동시 요청 둘이 모두 NULL을 보고 모두 갱신한다 — **그것이 더블클릭에 메시지가
    두 개 저장되는 경로다.** 이 조건절이 `force_log_id` 1회성을 실제로 보장한다.

    존재하지 않는 `log_id`도 같은 409로 떨어진다. 두 경우를 나누려면 조회를 한 번
    더 해야 하는데, 그 조회는 경쟁 조건을 되살리지 않을 뿐 아무것도 알려주지
    않는다 — 라우터가 호출 전에 소유권과 존재를 이미 확인하고, U5는
    `get_log_for_force()`를 먼저 거친다.
    """
    result = await session.execute(
        sa.update(JudgmentLog)
        .where(JudgmentLog.id == log_id, JudgmentLog.user_action.is_(None))
        .values(user_action=action)
    )

    if result.rowcount == 0:
        logger.info("이미 해소된 판정 로그에 user_action을 쓰려 했습니다 (log_id=%s)", log_id)
        raise AlreadyResolved("이미 처리된 판정 결과입니다")

    await session.flush()


async def link_message(session: AsyncSession, log_id: int, message_id: int) -> None:
    """전송이 확정된 뒤 판정 로그를 메시지에 연결한다.

    취소된 건은 호출되지 않아 `message_id`가 NULL로 남는다 — **그것이 정상이다.**
    참조 방향이 로그 → 메시지인 이유이기도 하다 (`domain-entities.md`).

    Raises:
        ValueError: 그 로그가 없다. 호출자가 방금 `judge()`에서 받은 id를 넘기므로
            이 경우는 데이터 손상이다. 조용히 넘기면 그 메시지는 영원히 판정과
            연결되지 않고, 나중에 로그를 볼 때 원인을 찾을 수 없다.
    """
    result = await session.execute(
        sa.update(JudgmentLog).where(JudgmentLog.id == log_id).values(message_id=message_id)
    )

    if result.rowcount == 0:
        # 영향 행 0은 "행이 없다"일 수도 있고 "값이 이미 같다"(재연결)일 수도 있다.
        # MariaDB가 변경된 행만 세기 때문이다. 존재만 한 번 더 확인해 두 경우를
        # 가른다 — 이 조회는 비정상 경로에서만 돈다.
        found = await session.scalar(sa.select(JudgmentLog.id).where(JudgmentLog.id == log_id))
        if found is None:
            logger.error("존재하지 않는 판정 로그에 메시지를 연결하려 했습니다 (log_id=%s)", log_id)
            raise ValueError(f"판정 로그를 찾을 수 없습니다: log_id={log_id}")

    await session.flush()


__all__ = [
    "VERDICT_APPROPRIATE",
    "VERDICT_INAPPROPRIATE",
    "get_log_for_force",
    "judge",
    "link_message",
    "set_user_action",
]

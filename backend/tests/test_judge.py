"""`judge()` — 판정 흐름과 로그 (FR-6.2·FR-6.3·FR-7.2·FR-8.1, BR-6.1·BR-6.5~BR-6.8).

**OpenAI 호출은 전부 목이다.** 두 가지 방식을 섞어 쓴다:

- `_returning(...)`: `call_model`을 갈아끼워 점수만 통제한다 (판정 규칙 검증용)
- `_failing_openai(...)`: 진짜 `call_model`을 돌리되 SDK 클라이언트만 가짜로 둔다
  (예외가 `judge()` 밖으로 새지 않는지 확인용 — 이건 통합 경로여야 의미가 있다)

**실제 MariaDB에서 돈다.** `TEST_DATABASE_URL`이 없으면 skip된다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from openai import APITimeoutError

from app.judgment import client as client_module
from app.judgment import service as service_module
from app.judgment.client import ModelCall
from app.judgment.service import judge
from app.judgment.types import Appropriate, ContextMessage, Failed, Inappropriate
from app.models import JudgmentLog
from tests.conftest import make_room, make_user

CONTEXT = [
    ContextMessage(sender_id=1, text="내일 회의 몇 시죠?", seq=11),
    ContextMessage(sender_id=2, text="10시입니다", seq=12),
    ContextMessage(sender_id=1, text="자료는 제가 준비할게요", seq=13),
]
CANDIDATE = "오늘 저녁에 치킨 어때?"


async def _actors(session: Any) -> tuple[int, int]:
    """`(user_id, room_id)`. FK를 만족시키는 최소 준비다."""
    user = await make_user(session, "judge-caller")
    room = await make_room(session, created_by=user.id)
    return user.id, room.id


def _returning(
    monkeypatch: pytest.MonkeyPatch,
    score: float | None,
    *,
    ok: bool = True,
    latency_ms: int = 1234,
    on_call: Any = None,
) -> None:
    """`call_model`을 고정 결과로 갈아끼운다.

    `on_call`을 주면 호출 **직전에** 부른다 — "로그 행이 호출보다 먼저 있는가"를
    그 자리에서 확인하는 데 쓴다 (BR-6.8).
    """

    async def _fake(messages: list[dict[str, str]], **_: Any) -> ModelCall:
        if on_call is not None:
            await on_call(messages)
        return ModelCall(
            ok=ok,
            latency_ms=latency_ms,
            score=score,
            prompt_tokens=312 if ok else None,
            completion_tokens=8 if ok else None,
            error=None if ok else "타임아웃",
            error_kind=None if ok else "timeout",
            attempts=1 if ok else 2,
        )

    monkeypatch.setattr(service_module, "call_model", _fake)


def _failing_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    """SDK 클라이언트만 가짜로 두고 진짜 `call_model`을 돌린다.

    `call_model`을 통째로 갈아끼우면 "예외가 새지 않는다"를 검증할 수 없다 —
    그 예외가 나는 곳이 바로 갈아끼운 자리이기 때문이다.
    """

    class _Completions:
        async def create(self, **_: Any) -> Any:
            raise APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/chat"))

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(client_module, "get_client", _Client)


async def _log(session: Any, log_id: int) -> JudgmentLog:
    row = await session.get(JudgmentLog, log_id)
    assert row is not None
    await session.refresh(row)
    return row


# --------------------------------------------------------------------------
# 로그가 호출보다 먼저다 (BR-6.8)
# --------------------------------------------------------------------------
async def test_the_log_row_exists_before_the_model_is_called(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**호출 시점에 이미 로그 행이 있다** (BR-6.8).

    호출 중 프로세스가 죽어도 시도한 흔적이 남아야 API 실패율(FR-7.5)을 셀 수
    있다. 순서가 뒤집히면 죽은 호출이 통계에서 사라지고, 실패율이 실제보다 낮게
    나온다 — 가장 나쁜 종류의 오류다(측정 자체가 거짓말이 된다).
    """
    user_id, room_id = await _actors(db_session)
    seen: list[dict[str, Any]] = []

    async def _inspect(_messages: list[dict[str, str]]) -> None:
        rows = (
            await db_session.execute(sa.select(JudgmentLog).where(JudgmentLog.user_id == user_id))
        ).scalars()
        seen.extend(
            {"candidate_text": row.candidate_text, "score": row.score, "verdict": row.verdict}
            for row in rows
        )

    _returning(monkeypatch, 0.5, on_call=_inspect)

    await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    assert len(seen) == 1
    assert seen[0]["candidate_text"] == CANDIDATE
    # 아직 판정 전이므로 둘 다 비어 있어야 한다.
    assert seen[0]["score"] is None
    assert seen[0]["verdict"] is None


# --------------------------------------------------------------------------
# 임계값 판정 (BR-6.5)
# --------------------------------------------------------------------------
async def test_score_above_the_threshold_is_inappropriate(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0.85 / 임계값 0.7 → 부적절 — FR-6.3의 수용 기준 그대로."""
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, 0.85)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    assert isinstance(result, Inappropriate)
    assert result.score == pytest.approx(0.85)
    assert (await _log(db_session, result.log_id)).verdict == "inappropriate"


async def test_score_below_the_threshold_is_appropriate(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0.65 / 임계값 0.7 → 적절 — FR-6.3의 수용 기준 그대로."""
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, 0.65)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    assert isinstance(result, Appropriate)
    assert (await _log(db_session, result.log_id)).verdict == "appropriate"


async def test_score_equal_to_the_threshold_is_inappropriate(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**경계에서 같으면 부적절이다** (`>=`, BR-6.5).

    실질적 의미는 없지만 정해두지 않으면 구현마다 달라지고 재현이 깨진다.
    """
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, 0.7)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    assert isinstance(result, Inappropriate)


# --------------------------------------------------------------------------
# 클램프 (BR-6.6)
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "clamped"),
    [(1.2, 1.0), (-0.3, 0.0)],
)
async def test_out_of_range_scores_are_clamped_not_failed(
    db_session: Any, monkeypatch: pytest.MonkeyPatch, raw: float, clamped: float
) -> None:
    """범위 밖 점수는 **클램프한다. 실패로 처리하지 않는다** (BR-6.6).

    JSON 스키마의 `number`는 범위를 강제하지 않아 모델이 1.2를 줄 수 있다.
    실패로 처리하면 멀쩡한 판정을 버린다 — 1.2는 "매우 부적절"이지 "고장"이 아니다.
    """
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, raw)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    assert not isinstance(result, Failed)
    assert result.score == pytest.approx(clamped)
    assert (await _log(db_session, result.log_id)).score == Decimal(f"{clamped:.3f}")


# --------------------------------------------------------------------------
# 실패 (BR-6.7, BR-6.8)
# --------------------------------------------------------------------------
async def test_failure_returns_failed_without_raising(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**타임아웃이 `judge()` 밖으로 새지 않는다** (BR-6.7).

    SDK 클라이언트만 가짜로 두고 진짜 재시도 경로를 통과시킨다. `Failed`는
    예외가 아니라 반환값이며, 그것이 FR-8의 degraded 경로를 성립시킨다 —
    예외로 만들면 호출자가 정상 분기를 `try/except`로 쓰게 된다.
    """
    user_id, room_id = await _actors(db_session)
    _failing_openai(monkeypatch)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    assert isinstance(result, Failed)


async def test_failed_log_keeps_score_and_verdict_null_with_a_latency(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """실패 로그는 `score`·`verdict`가 NULL이고 `latency_ms`는 채워진다 (BR-6.8).

    그 조합이 호출 실패를 표현하는 방식이다 (FR-8.1). 집계는 `verdict IS NOT NULL`로
    걸러 이 행을 precision에서 빼되 API 실패율에는 넣는다 (BR-7.2).
    """
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, None, ok=False, latency_ms=8123)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    assert isinstance(result, Failed)
    row = await _log(db_session, result.log_id)
    assert row.score is None
    assert row.verdict is None
    assert row.latency_ms == 8123
    assert row.prompt_tokens is None


# --------------------------------------------------------------------------
# 로그에 남는 것 (BR-6.1, BR-6.5)
# --------------------------------------------------------------------------
async def test_the_log_records_the_actual_context_range(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`context_from_seq`~`context_to_seq`가 실제로 넣은 범위다 (BR-6.1).

    **`to_seq`는 후보 문장이 아니라 문맥의 마지막 메시지의 seq다** — 후보는 아직
    저장 전이라 seq가 없다. N은 환경변수라 언제든 바뀌고 방에 메시지가 N개보다
    적을 수도 있어서, 실제 범위를 남기지 않으면 재현이 불가능하다.
    """
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, 0.2)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    row = await _log(db_session, result.log_id)
    assert row.context_from_seq == 11
    assert row.context_to_seq == 13


async def test_the_log_records_the_threshold_and_tokens(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """판정 당시의 임계값이 남는다 (BR-6.5).

    임계값은 환경변수라 언제든 바뀐다. 점수만 남기고 기준을 안 남기면 나중에
    "이 판정은 어떤 기준으로 내려졌나"를 알 수 없어 데이터가 반쪽이 된다.
    """
    from app.core.config import settings

    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, 0.42)

    result = await judge(db_session, user_id, room_id, CONTEXT, CANDIDATE)

    row = await _log(db_session, result.log_id)
    assert row.threshold == Decimal(f"{settings.AI_VERDICT_THRESHOLD:.3f}")
    assert row.prompt_tokens == 312
    assert row.completion_tokens == 8
    assert row.user_action is None
    assert row.message_id is None


async def test_the_log_stores_the_candidate_text_verbatim(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """후보 문장을 원문 그대로 남긴다 — BR-6.9의 텍스트 일치 검사가 이 값을 쓴다.

    트림해 저장하면 원문과 다른 것을 기준으로 비교하게 된다. 비교 시점에 양쪽을
    트림하는 것과, 저장 시점에 한쪽만 트림하는 것은 다르다.
    """
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, 0.1)
    padded = "  앞뒤에 공백이 있는 문장  "

    result = await judge(db_session, user_id, room_id, CONTEXT, padded)

    assert (await _log(db_session, result.log_id)).candidate_text == padded


# --------------------------------------------------------------------------
# 입력 검증 (BR-6.1)
# --------------------------------------------------------------------------
async def test_empty_context_is_a_caller_error_not_a_judgment_failure(
    db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """빈 문맥은 **호출자의 계약 위반**이지 판정 실패가 아니다.

    `context_from_seq`·`context_to_seq`가 NOT NULL이라 남길 범위가 없다. 실제
    경로에서는 U5가 문맥 부족을 먼저 걸러낸다 (FR-6.4). 이 예외는 로그 행을 만들기
    **전에** 나므로 API 실패율에 섞이지 않는다 — 그것을 `Failed`로 삼키면
    "모델이 실패했다"는 거짓 기록이 남는다.
    """
    user_id, room_id = await _actors(db_session)
    _returning(monkeypatch, 0.5)

    with pytest.raises(ValueError, match="문맥"):
        await judge(db_session, user_id, room_id, [], CANDIDATE)

    remaining = await db_session.scalar(
        sa.select(sa.func.count()).select_from(JudgmentLog).where(JudgmentLog.user_id == user_id)
    )
    assert remaining == 0

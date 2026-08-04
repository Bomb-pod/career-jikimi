"""OpenAI 호출 한 겹 — 타임아웃·재시도·예산을 여기서 끝낸다 (FR-8.1, BR-6.7, NFR-1).

**이 모듈은 예외를 밖으로 내지 않는다.** 모든 실패가 `ModelCall(ok=False, ...)`로
돌아온다. `judge()`가 그것을 `Failed`로 바꾼다 — 실패는 흐름의 일부이지 오류가
아니다 (BR-6.7).

**DB를 모른다.** 그래서 `try` CLI가 이 모듈만으로 판정을 돌려볼 수 있다.

## 재시도 규칙 (BR-6.7)

| 상황 | 재시도 |
|---|---|
| 타임아웃 | 한다 |
| 연결 오류 | 한다 |
| 5xx | 한다 |
| 429 (rate limit) | 한다 — 단 `Retry-After`가 남은 예산을 넘으면 대기하지 않고 실패 |
| **그 외 4xx** | **안 한다** — 요청 자체가 잘못된 것이라 다시 보내도 같다 |

**SDK 자체 재시도를 끈다(`max_retries=0`).** 켜두면 SDK가 안에서 두 번, 우리가
밖에서 두 번 시도해 "정확히 1회"가 조용히 깨지고, 사용자 대기 시간이 예산을
넘긴다. 이 설정을 지우면 규칙이 깨지므로 테스트가 값을 고정한다.

**모델이 `json_schema`를 거부하면(4xx) 그것을 판정 실패로 조용히 삼키지 않는다.**
`ok=False`로 돌아가는 것은 같지만 `ERROR` 레벨로 원문 오류를 남긴다 — 설정 오류를
API 장애로 오해하면 며칠을 헤맨다.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Final

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from app.core.config import settings
from app.judgment.constants import MAX_ATTEMPTS, TEMPERATURE, TOTAL_BUDGET_SECONDS
from app.judgment.prompt import RESPONSE_FORMAT, SCORE_KEY, ChatMessage

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 실패 분류
# --------------------------------------------------------------------------

#: 네트워크·API 장애 — FR-8.1이 정의한 실패 경로. 재시도 대상이다.
KIND_TIMEOUT: Final[str] = "timeout"
KIND_CONNECTION: Final[str] = "connection"
KIND_SERVER: Final[str] = "server"
KIND_RATE_LIMIT: Final[str] = "rate_limit"

#: **장애가 아니라 우리 쪽 문제.** 재시도하지 않고 ERROR로 남긴다.
#: `json_schema` 거부·잘못된 모델 ID·인증 실패가 여기 온다.
KIND_REQUEST: Final[str] = "request"
#: `strict: true`가 보장하는 형식이 깨졌다 — 계약 위반이다 (BR-6.4).
KIND_CONTRACT: Final[str] = "contract"
#: 분류되지 않은 예외. 삼키지 않고 ERROR로 남긴다.
KIND_UNEXPECTED: Final[str] = "unexpected"

#: 재시도하는 실패 종류 (BR-6.7).
RETRYABLE_KINDS: Final[frozenset[str]] = frozenset(
    {KIND_TIMEOUT, KIND_CONNECTION, KIND_SERVER, KIND_RATE_LIMIT}
)

#: 장애가 아니라 설정·계약 문제라서 ERROR로 남기는 종류.
_LOUD_KINDS: Final[frozenset[str]] = frozenset({KIND_REQUEST, KIND_CONTRACT, KIND_UNEXPECTED})

#: 이 값 이상이 서버 오류(5xx)다. 재시도 대상과 아닌 것의 경계라 이름을 붙인다.
_SERVER_ERROR_FLOOR: Final[int] = 500


@dataclass(frozen=True, slots=True)
class ModelCall:
    """호출 한 번(재시도 포함)의 결과. **성공·실패 모두 이 타입이다.**

    Attributes:
        ok: 점수를 받았는가.
        latency_ms: **실패해도 실제 대기 시간이 들어간다** (BR-6.8) — 타임아웃이
            몇 초에서 끊겼는지가 관찰값이다. 재시도와 `Retry-After` 대기를 포함한
            전체 경과 시간이다.
        score: 모델이 준 원값. **클램프하지 않았다** — 범위 판단은 `judge()`가
            한다 (BR-6.6). 실패면 `None`.
        prompt_tokens / completion_tokens: 비용 추적. 실패면 `None`.
        error: 실패의 **원문** 메시지. 요약하거나 우리 문구로 갈아끼우지 않는다.
        error_kind: 위 `KIND_*` 중 하나. 실패의 성격을 호출자가 구분할 수 있게
            한다 — `try` CLI가 설정 오류와 장애를 다르게 보여주는 근거다.
        attempts: 실제로 보낸 요청 수. **1 또는 2다** (BR-6.7).
    """

    ok: bool
    latency_ms: int
    score: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    error_kind: str | None = None
    attempts: int = 0


# --------------------------------------------------------------------------
# 테스트 이음매 — 시계와 sleep을 모듈 함수로 둔다
# --------------------------------------------------------------------------
# 예산 계산을 실제 시간으로 검증하려면 테스트가 10초를 기다려야 한다. 두 함수를
# monkeypatch할 수 있게 빼두면 가짜 시계로 "두 번째 시도의 타임아웃이 남은 예산에
# 맞춰 깎였는가"를 즉시 확인할 수 있다. 운영 동작은 그대로다.


def _monotonic() -> float:
    """예산 계산용 단조 시계. 벽시계를 쓰지 않는다 — NTP 보정에 뒤로 갈 수 있다."""
    return time.monotonic()


async def _sleep(seconds: float) -> None:
    """`Retry-After` 대기. 테스트가 갈아끼운다."""
    await asyncio.sleep(seconds)


# --------------------------------------------------------------------------
# 클라이언트
# --------------------------------------------------------------------------
_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """프로세스 공용 `AsyncOpenAI`. 처음 부를 때 만든다.

    **`max_retries=0`이 이 함수의 존재 이유다** (BR-6.7). 기본값(2)이면 SDK가
    안에서 재시도하고 우리가 밖에서 또 재시도해 최대 6번이 나간다 — "정확히 1회"가
    깨지고 사용자 대기 시간이 NFR-1의 10초를 크게 넘는다.

    타임아웃은 여기 두지 않고 **요청마다** 준다. 남은 예산에 맞춰 두 번째 시도의
    타임아웃을 깎아야 하기 때문이다.

    import 시점이 아니라 첫 호출에 만드는 이유 — `report` CLI처럼 판정을 하지
    않는 진입점이 API 키 없이도 돌 수 있게 한다.
    """
    # 프로세스 공용 자원 하나를 지연 생성한다. 커넥션 풀을 요청마다 새로 만들지
    # 않기 위해서다 — 매번 새 클라이언트를 만들면 TLS 핸드셰이크가 지연에 얹힌다.
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.OPENAI_API_KEY.get_secret_value(),
            # None이면 OpenAI, 값이 있으면 Ollama 같은 호환 엔드포인트다.
            # **프로세스 공용 캐시라 백엔드를 바꿨으면 재시작해야 한다.**
            base_url=settings.active_base_url,
            max_retries=0,
        )
    return _client


def _classify(exc: Exception) -> tuple[str, bool]:
    """예외를 `(종류, 재시도 여부)`로 가른다 — BR-6.7의 표 그대로.

    **`APITimeoutError`를 먼저 본다.** SDK에서 그것이 `APIConnectionError`의
    하위 클래스라서 순서를 바꾸면 타임아웃이 연결 오류로 기록된다. 재시도 여부는
    같지만 로그에서 원인을 구분할 수 없게 된다.
    """
    if isinstance(exc, APITimeoutError):
        return KIND_TIMEOUT, True
    if isinstance(exc, APIConnectionError):
        return KIND_CONNECTION, True
    if isinstance(exc, RateLimitError):
        return KIND_RATE_LIMIT, True
    if isinstance(exc, APIStatusError):
        if exc.status_code >= _SERVER_ERROR_FLOOR:
            return KIND_SERVER, True
        # 429 외 4xx. **재시도하지 않는다** — 요청 자체가 틀린 것이라 다시 보내도
        # 같다. `json_schema` 거부(400)·모델 ID 오류(404)·인증 실패(401)가 여기다.
        return KIND_REQUEST, False
    return KIND_UNEXPECTED, False


def _retry_after_seconds(exc: Exception) -> float | None:
    """429 응답의 `Retry-After` 헤더를 초로 읽는다. 없거나 못 읽으면 `None`.

    HTTP 날짜 형식(`Retry-After: Wed, 21 Oct 2015 07:28:00 GMT`)은 파싱하지 않는다 —
    OpenAI는 초를 보내고, 날짜를 만나면 `None`으로 떨어져 즉시 재시도한다. 예산이
    상한을 지키므로 그 경로도 안전하다.
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    raw = response.headers.get("retry-after") if hasattr(response, "headers") else None
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("Retry-After를 초로 읽지 못했습니다: %r", raw)
        return None


def _parse_score(completion: object) -> float:
    """응답에서 점수를 꺼낸다. 형식이 어긋나면 예외를 올린다.

    `strict: true`가 형식을 보장하므로(BR-6.4) 여기서 실패하는 것은 **API 장애가
    아니라 계약 위반**이다. 호출자가 `KIND_CONTRACT`로 분류해 ERROR로 남긴다.
    """
    choices = completion.choices  # type: ignore[attr-defined]
    if not choices:
        raise ValueError("응답에 choices가 없습니다")

    message = choices[0].message
    refusal = getattr(message, "refusal", None)
    if refusal:
        raise ValueError(f"모델이 응답을 거부했습니다: {refusal}")

    content = message.content
    if not content:
        raise ValueError("응답 본문이 비어 있습니다")

    payload = json.loads(content)
    if SCORE_KEY not in payload:
        raise ValueError(f"응답에 {SCORE_KEY!r} 키가 없습니다: {content!r}")
    return float(payload[SCORE_KEY])


def _usage(completion: object) -> tuple[int | None, int | None]:
    """토큰 사용량. 응답에 없으면 `(None, None)` — 비용 추적이 판정을 막지 않는다."""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return None, None
    return getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)


async def call_model(
    messages: list[ChatMessage],
    *,
    client: AsyncOpenAI | None = None,
) -> ModelCall:
    """모델을 호출하고 점수를 받는다. **예외를 던지지 않는다.**

    Args:
        messages: `prompt.build_messages()`가 만든 것.
        client: 테스트가 가짜 클라이언트를 넣는 이음매. 기본값은 프로세스 공용
            클라이언트다.

    Returns:
        성공이면 `ok=True`와 `score`, 실패면 `ok=False`와 `error`·`error_kind`.
        **어느 쪽이든 `latency_ms`에 실제 대기 시간이 들어간다** (BR-6.8).

    예산 계산 (NFR-1):

        시도 1: timeout = min(AI_TIMEOUT_SECONDS, 남은 예산)
        (429면 Retry-After만큼 대기 — 남은 예산을 넘으면 대기하지 않고 실패)
        시도 2: timeout = min(AI_TIMEOUT_SECONDS, 남은 예산)

    `AI_TIMEOUT_SECONDS`가 4면 4+4=8초에 오버헤드가 얹혀도 10초 안이다. 설정이
    잘못돼 8초여도 두 번째 시도가 남은 예산(약 2초)으로 깎여 **상한은 지켜진다.**
    """
    started = _monotonic()
    api = client if client is not None else get_client()
    per_attempt_timeout = float(settings.AI_TIMEOUT_SECONDS)

    last_error: str | None = None
    last_kind: str | None = None
    attempts = 0

    for attempt in range(1, MAX_ATTEMPTS + 1):
        remaining = TOTAL_BUDGET_SECONDS - (_monotonic() - started)
        if remaining <= 0:
            # 앞 시도와 대기로 예산을 다 썼다. 보내봐야 사용자를 더 세울 뿐이다.
            logger.warning("판정 호출 예산(%.1f초)을 소진했습니다", TOTAL_BUDGET_SECONDS)
            break

        attempts = attempt
        timeout = min(per_attempt_timeout, remaining)

        try:
            completion = await api.chat.completions.create(
                model=settings.active_model,
                messages=messages,  # type: ignore[arg-type]  # SDK의 TypedDict와 호환된다
                response_format=RESPONSE_FORMAT,  # type: ignore[arg-type]
                temperature=TEMPERATURE,
                timeout=timeout,
            )
        except Exception as exc:  # noqa: BLE001 - 어떤 예외도 밖으로 내지 않는다 (BR-6.7)
            kind, retryable = _classify(exc)
            last_error, last_kind = str(exc), kind
            _log_failure(kind, attempt, exc)

            if not retryable or attempt == MAX_ATTEMPTS:
                break

            if not await _wait_before_retry(exc, kind, started):
                break
            continue

        try:
            score = _parse_score(completion)
        except Exception as exc:  # noqa: BLE001 - 계약 위반도 예외로 내보내지 않는다
            last_error, last_kind = str(exc), KIND_CONTRACT
            _log_failure(KIND_CONTRACT, attempt, exc)
            # **재시도하지 않는다.** `strict: true`가 보장하는 형식이 깨진 것은
            # 일시적 장애가 아니라 설정·계약 문제다 (BR-6.4).
            break

        prompt_tokens, completion_tokens = _usage(completion)
        return ModelCall(
            ok=True,
            latency_ms=_elapsed_ms(started),
            score=score,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            attempts=attempt,
        )

    return ModelCall(
        ok=False,
        latency_ms=_elapsed_ms(started),
        error=last_error,
        error_kind=last_kind,
        attempts=attempts,
    )


async def _wait_before_retry(exc: Exception, kind: str, started: float) -> bool:
    """재시도 전 대기. 예산이 남지 않으면 `False`를 돌려 재시도를 포기시킨다.

    타임아웃·연결 오류·5xx는 **즉시** 재시도한다 — 백오프를 넣으면 예산만 먹고,
    한 번뿐인 재시도를 늦출 이유가 없다.

    429는 `Retry-After`를 **남은 예산 안에서만** 존중한다. 서버가 30초를 기다리라
    해도 사용자를 30초 세울 수는 없다 — BR-6.7의 총 상한 10초와 NFR-1이 우선한다.
    """
    if kind != KIND_RATE_LIMIT:
        return True

    retry_after = _retry_after_seconds(exc)
    if retry_after is None:
        return True

    remaining = TOTAL_BUDGET_SECONDS - (_monotonic() - started)
    if retry_after >= remaining:
        # 대기만으로 예산이 끝난다. 기다렸다가 실패하느니 지금 실패한다 —
        # 사용자에게 돌아가는 결과는 같고, 대기한 만큼이 순수한 손해다.
        logger.warning(
            "Retry-After %.1f초가 남은 예산 %.1f초를 넘어 재시도하지 않습니다",
            retry_after,
            remaining,
        )
        return False

    await _sleep(retry_after)
    return True


def _log_failure(kind: str, attempt: int, exc: Exception) -> None:
    """실패를 남긴다. **설정·계약 문제는 ERROR, 장애는 WARNING.**

    등급을 나누는 이유 — `json_schema` 거부(설정 오류)를 API 장애와 같은 줄로
    남기면 판정 실패율만 보고 "OpenAI가 불안정하다"고 결론 내리게 된다. 실제로는
    모든 호출이 같은 이유로 실패하는 중이며, 고칠 곳은 우리 설정이다.
    """
    if kind in _LOUD_KINDS:
        logger.error(
            "판정 호출이 %s로 실패했습니다 (시도 %d) — API 장애가 아니라 요청·설정 문제일 수 "
            "있습니다. 원문: %s",
            kind,
            attempt,
            exc,
            exc_info=exc,
        )
    else:
        logger.warning("판정 호출 실패 (%s, 시도 %d): %s", kind, attempt, exc)


def _elapsed_ms(started: float) -> int:
    """경과 시간(ms). 음수가 나오지 않게 0에서 자른다."""
    return max(0, int((_monotonic() - started) * 1000))


__all__ = [
    "KIND_CONNECTION",
    "KIND_CONTRACT",
    "KIND_RATE_LIMIT",
    "KIND_REQUEST",
    "KIND_SERVER",
    "KIND_TIMEOUT",
    "KIND_UNEXPECTED",
    "RETRYABLE_KINDS",
    "ModelCall",
    "call_model",
    "get_client",
]

"""OpenAI 호출의 타임아웃·재시도·예산 — FR-8.1, BR-6.7, BR-6.8, NFR-1.

**실제 API를 부르지 않는다.** 가짜 클라이언트를 주입하고, 시계와 sleep을
갈아끼운다. 그러지 않으면 테스트에 API 키가 필요하고, 비용이 들고, 예산 검증에
실제로 10초를 기다려야 한다.

시계를 가짜로 쓰는 것이 이 파일의 핵심 장치다 — "두 번째 시도의 타임아웃이 남은
예산에 맞춰 깎였는가"는 시간이 흘러야 확인되는데, 진짜로 흘려보내면 테스트가
느려진다.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.judgment import client as client_module
from app.judgment.client import (
    KIND_CONNECTION,
    KIND_CONTRACT,
    KIND_RATE_LIMIT,
    KIND_REQUEST,
    KIND_SERVER,
    KIND_TIMEOUT,
    call_model,
    get_client,
)
from app.judgment.constants import MAX_ATTEMPTS, TOTAL_BUDGET_SECONDS

MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


# --------------------------------------------------------------------------
# 가짜 SDK
# --------------------------------------------------------------------------
class _FakeCompletions:
    """`client.chat.completions.create`를 흉내낸다.

    호출마다 `outcomes`에서 하나를 꺼내 예외면 던지고 아니면 돌려준다. 받은
    `timeout`을 기록해두므로 예산 계산을 그 목록으로 검증할 수 있다.
    """

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.timeouts: list[float] = []
        self.calls = 0

    async def create(self, **kwargs: Any) -> Any:
        self.calls += 1
        self.timeouts.append(kwargs["timeout"])
        # 준비한 것보다 많이 불렸다면 그 자체가 재시도 규칙 위반이다. 조용히
        # 이상한 값을 돌려주면 엉뚱한 곳에서 실패해 원인을 찾기 어렵다.
        assert self._outcomes, f"{self.calls}번째 호출인데 준비된 응답이 없습니다"
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes: list[Any]) -> None:
        self.completions = _FakeCompletions(outcomes)
        self.chat = type("_Chat", (), {"completions": self.completions})()


class _Message:
    def __init__(self, content: str | None, refusal: str | None = None) -> None:
        self.content = content
        self.refusal = refusal


class _Usage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _Completion:
    def __init__(self, content: str | None, refusal: str | None = None) -> None:
        self.choices = [type("_Choice", (), {"message": _Message(content, refusal)})()]
        self.usage = _Usage(312, 8)


def _response(status_code: int, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        headers=headers or {},
        request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
    )


def _status_error(status_code: int, headers: dict[str, str] | None = None) -> APIStatusError:
    response = _response(status_code, headers)
    error_type = RateLimitError if status_code == 429 else APIStatusError  # noqa: PLR2004
    return error_type(f"HTTP {status_code}", response=response, body=None)


def _timeout() -> APITimeoutError:
    return APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/chat"))


def _connection_error() -> APIConnectionError:
    return APIConnectionError(request=httpx.Request("POST", "https://api.openai.com/v1/chat"))


# --------------------------------------------------------------------------
# 시계·sleep 이음매
# --------------------------------------------------------------------------
@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """가짜 단조 시계. 리스트의 0번 값을 읽고, 테스트가 직접 올린다."""
    now = [0.0]
    monkeypatch.setattr(client_module, "_monotonic", lambda: now[0])
    return now


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """실제로 자지 않고 잠든 시간만 기록한다."""
    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(client_module, "_sleep", _record)
    return recorded


# --------------------------------------------------------------------------
# 성공 경로
# --------------------------------------------------------------------------
async def test_successful_call_returns_the_score_and_usage() -> None:
    """점수와 토큰 사용량을 그대로 돌려준다. **클램프하지 않는다** — 그것은 `judge()` 몫."""
    fake = _FakeClient([_Completion('{"score": 0.82}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is True
    assert call.score == pytest.approx(0.82)
    assert call.prompt_tokens == 312
    assert call.completion_tokens == 8
    assert call.attempts == 1
    assert fake.completions.calls == 1


async def test_success_on_the_retry_after_a_timeout(sleeps: list[float]) -> None:
    """첫 시도가 타임아웃이면 **한 번** 재시도하고, 성공하면 그 결과를 쓴다."""
    fake = _FakeClient([_timeout(), _Completion('{"score": 0.4}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is True
    assert call.attempts == 2
    assert fake.completions.calls == 2
    # 타임아웃·연결 오류·5xx는 즉시 재시도한다 — 백오프는 예산만 먹는다.
    assert sleeps == []


# --------------------------------------------------------------------------
# 재시도 규칙 (BR-6.7)
# --------------------------------------------------------------------------
async def test_timeout_retries_exactly_once() -> None:
    """**정확히 1회다** (BR-6.7). 2회면 사용자가 최대 15초를 기다린다."""
    fake = _FakeClient([_timeout(), _timeout(), _Completion('{"score": 0.1}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert call.error_kind == KIND_TIMEOUT
    assert call.attempts == MAX_ATTEMPTS == 2
    # 세 번째 응답(성공)까지 갔다면 재시도가 두 번이라는 뜻이다.
    assert fake.completions.calls == 2


async def test_connection_error_retries() -> None:
    """연결 오류는 재시도 대상이다 (BR-6.7)."""
    fake = _FakeClient([_connection_error(), _Completion('{"score": 0.2}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is True
    assert fake.completions.calls == 2


async def test_server_error_retries() -> None:
    """5xx는 재시도 대상이다 — 서버 쪽 일시적 실패일 수 있다."""
    fake = _FakeClient([_status_error(503), _Completion('{"score": 0.3}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is True
    assert fake.completions.calls == 2


async def test_rate_limit_retries() -> None:
    """429는 재시도 대상이다. `Retry-After`가 없으면 즉시 다시 보낸다."""
    fake = _FakeClient([_status_error(429), _Completion('{"score": 0.9}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is True
    assert fake.completions.calls == 2


@pytest.mark.parametrize(
    ("make_error", "expected_kind"),
    [
        (_timeout, KIND_TIMEOUT),
        (_connection_error, KIND_CONNECTION),
        (lambda: _status_error(503), KIND_SERVER),
        (lambda: _status_error(429), KIND_RATE_LIMIT),
        (lambda: _status_error(400), KIND_REQUEST),
    ],
)
async def test_failure_kinds_are_classified(make_error: Any, expected_kind: str) -> None:
    """실패의 종류가 뭉개지지 않는다.

    특히 **타임아웃이 연결 오류로 기록되면 안 된다** — SDK에서
    `APITimeoutError`가 `APIConnectionError`의 하위 클래스라, 분류 순서를 바꾸면
    조용히 같은 종류가 된다. 재시도 여부는 같지만 로그에서 원인을 구분할 수 없게
    되고, "타임아웃이 잦다"와 "연결이 안 된다"는 대응이 다르다.
    """
    fake = _FakeClient([make_error(), make_error()])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert call.error_kind == expected_kind


async def test_client_error_does_not_retry() -> None:
    """**429 외 4xx는 재시도하지 않는다** — 요청 자체가 틀린 것이라 다시 보내도 같다.

    `json_schema` 거부(400)가 이 경로로 온다. 재시도하면 같은 오류를 두 번 받고
    사용자 대기 시간만 두 배가 된다.
    """
    fake = _FakeClient([_status_error(400), _Completion('{"score": 0.5}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert call.error_kind == KIND_REQUEST
    assert call.attempts == 1
    assert fake.completions.calls == 1


async def test_a_rejected_json_schema_keeps_the_original_error_text() -> None:
    """모델이 `json_schema`를 거부하면 **원문 오류를 잃지 않는다.**

    설정 오류를 API 장애로 오해하면 며칠 헤맨다. `ModelCall.error`에 원문이
    남아야 `try` CLI가 그것을 그대로 보여줄 수 있다.
    """
    response = _response(400)
    rejection = APIStatusError(
        "Invalid parameter: 'response_format' of type 'json_schema' is not supported "
        "with this model.",
        response=response,
        body=None,
    )
    fake = _FakeClient([rejection])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.error_kind == KIND_REQUEST
    assert "json_schema" in (call.error or "")


async def test_malformed_response_is_a_contract_failure_not_a_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`strict: true`가 보장하는 형식이 깨지면 **재시도하지 않고 ERROR로 남긴다** (BR-6.4).

    파싱 오류를 FR-8.1의 실패 경로로 흘려보내지 않는다 — 그 경로는 네트워크·API
    장애용이다.
    """
    fake = _FakeClient([_Completion('{"verdict": "bad"}')])

    with caplog.at_level("ERROR"):
        call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert call.error_kind == KIND_CONTRACT
    assert fake.completions.calls == 1
    assert any(record.levelname == "ERROR" for record in caplog.records)


async def test_refusal_is_a_contract_failure() -> None:
    """모델이 응답을 거부하면 계약 위반으로 분류한다 — 장애가 아니다."""
    fake = _FakeClient([_Completion(None, refusal="죄송하지만 도와드릴 수 없습니다")])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert call.error_kind == KIND_CONTRACT
    assert "거부" in (call.error or "")


# --------------------------------------------------------------------------
# 예산 (NFR-1)
# --------------------------------------------------------------------------
async def test_total_wait_stays_inside_the_ten_second_budget(clock: list[float]) -> None:
    """두 시도의 타임아웃 합이 10초 예산을 넘지 않는다 — NFR-1, BR-6.7.

    기본값 4초면 4+4=8초이고 오버헤드가 얹혀도 10초 안이다.
    """
    fake = _FakeClient([_timeout(), _timeout()])

    async def _advance(**kwargs: Any) -> Any:
        # 타임아웃이 실제로 그 시간만큼 기다린 것처럼 시계를 민다.
        clock[0] += kwargs["timeout"]
        raise _timeout()

    fake.completions.create = _advance  # type: ignore[method-assign]

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert sum(fake.completions.timeouts) <= TOTAL_BUDGET_SECONDS
    assert call.latency_ms <= TOTAL_BUDGET_SECONDS * 1000


async def test_second_attempt_timeout_is_clamped_to_the_remaining_budget(
    clock: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    """설정이 잘못돼 타임아웃이 8초여도 **두 번째 시도가 남은 예산으로 깎인다.**

    이것이 `AI_TIMEOUT_SECONDS`를 잘못 설정해도 NFR-1의 10초가 지켜지는 이유다.
    설정 실수 하나가 사용자를 16초 세우지 않게 하는 마지막 방어선이다.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "AI_TIMEOUT_SECONDS", 8.0)

    fake = _FakeClient([])
    recorded: list[float] = []

    async def _advance(**kwargs: Any) -> Any:
        recorded.append(kwargs["timeout"])
        clock[0] += kwargs["timeout"]
        raise _timeout()

    fake.completions.create = _advance  # type: ignore[method-assign]

    await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert recorded[0] == pytest.approx(8.0)
    assert recorded[1] == pytest.approx(TOTAL_BUDGET_SECONDS - 8.0)
    assert sum(recorded) <= TOTAL_BUDGET_SECONDS


async def test_retry_after_beyond_the_budget_does_not_wait(
    clock: list[float], sleeps: list[float]
) -> None:
    """`Retry-After`가 남은 예산을 넘으면 **대기하지 않고 즉시 실패한다.**

    서버가 30초를 기다리라 해도 사용자를 30초 세울 수는 없다 — BR-6.7의 총 상한
    10초와 NFR-1이 우선한다. 기다렸다가 실패하나 지금 실패하나 결과는 같고,
    기다린 만큼이 순수한 손해다.
    """
    fake = _FakeClient([_status_error(429, {"Retry-After": "30"}), _Completion('{"score": 0.1}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert call.error_kind == KIND_RATE_LIMIT
    assert sleeps == []
    assert fake.completions.calls == 1


async def test_retry_after_inside_the_budget_is_honored(
    clock: list[float], sleeps: list[float]
) -> None:
    """예산 안이면 `Retry-After`를 존중한다 — 바로 다시 보내면 또 429다."""
    fake = _FakeClient([_status_error(429, {"Retry-After": "1"}), _Completion('{"score": 0.1}')])

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is True
    assert sleeps == [1.0]
    assert fake.completions.calls == 2


async def test_exhausted_budget_skips_the_retry(clock: list[float]) -> None:
    """앞 시도가 예산을 다 썼으면 재시도를 보내지 않는다."""
    fake = _FakeClient([])

    async def _burn_budget(**kwargs: Any) -> Any:
        clock[0] += TOTAL_BUDGET_SECONDS
        raise _timeout()

    fake.completions.create = _burn_budget  # type: ignore[method-assign]

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    assert call.attempts == 1


# --------------------------------------------------------------------------
# 기록 (BR-6.8)
# --------------------------------------------------------------------------
async def test_failure_still_records_the_latency(clock: list[float]) -> None:
    """**실패해도 실제 대기 시간을 기록한다** (BR-6.8).

    타임아웃이 몇 초에서 끊겼는지가 관찰값이다. 0으로 남기면 지연 분포와 API
    실패율을 함께 읽을 수 없다.
    """
    fake = _FakeClient([])

    async def _advance(**kwargs: Any) -> Any:
        clock[0] += 2.0
        raise _timeout()

    fake.completions.create = _advance  # type: ignore[method-assign]

    call = await call_model(MESSAGES, client=fake)  # type: ignore[arg-type]

    assert call.ok is False
    # 두 번 시도해 2초씩 = 4초.
    assert call.latency_ms == 4000


# --------------------------------------------------------------------------
# SDK 설정
# --------------------------------------------------------------------------
def test_sdk_retries_are_disabled() -> None:
    """**`max_retries=0`이다** (BR-6.7).

    기본값(2)이면 SDK가 안에서 재시도하고 우리가 밖에서 또 재시도해 최대 6번이
    나간다 — "정확히 1회"가 조용히 깨지고 사용자 대기 시간이 NFR-1을 크게 넘는다.
    이 단언이 그 설정을 지우지 못하게 한다.
    """
    assert get_client().max_retries == 0

"""`/health`와 DB 연결 재시도 테스트 — FR-9.2, `services.md` § 컨테이너 사양.

두 관심사가 한 파일에 있는 이유는 둘 다 "DB에 닿는가"를 다루기 때문이다.
`/health`는 그 사실을 바깥에 알리고, `wait_for_database()`는 기동 시 그것을 기다린다.

실제 DB 없이 돈다 — 실패·타임아웃 경로가 오히려 실제 DB로는 재현하기 어렵다.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core import db as db_module
from app.main import app, db_health_probe


def _connection_refused() -> OperationalError:
    """드라이버가 연결을 거부했을 때 SQLAlchemy가 감싸 던지는 예외 모양."""
    return OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))


# --------------------------------------------------------------------------
# GET /health
# --------------------------------------------------------------------------
def test_health_returns_ok_when_db_is_reachable(client: TestClient) -> None:
    """DB에 닿으면 200과 약속된 본문 구조를 준다."""
    app.dependency_overrides[db_health_probe] = lambda: True

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}


def test_health_returns_503_when_db_is_unreachable(client: TestClient) -> None:
    """DB에 닿지 못하면 **503**이다 — 500이 아니다.

    DB 도달 실패는 서버 버그가 아니라 의존 서비스 이용 불가다. 500으로 내보내면
    Docker HEALTHCHECK 로그와 사람이 원인을 오해한다.
    """
    app.dependency_overrides[db_health_probe] = lambda: False

    response = client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "db": "error"}


def test_health_does_not_leak_a_traceback_on_db_failure(client: TestClient) -> None:
    """DB 실패 시 응답 본문에 예외 정보가 섞이지 않는다.

    `check_database()`가 예외를 삼키고 bool만 돌려주므로 성립한다. 그 계약이
    깨지면 여기서 500과 스택트레이스가 나온다.
    """
    app.dependency_overrides[db_health_probe] = lambda: False

    body = client.get("/health").text

    assert "Traceback" not in body
    assert "OperationalError" not in body


# --------------------------------------------------------------------------
# check_database() — /health가 쓰는 얕은 체크
# --------------------------------------------------------------------------
async def test_check_database_returns_false_on_driver_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """연결 거부는 예외가 아니라 `False`로 나온다."""

    async def refuse(_: AsyncEngine) -> None:
        raise _connection_refused()

    monkeypatch.setattr(db_module, "_ping", refuse)

    assert await db_module.check_database(timeout=1.0) is False


async def test_check_database_returns_false_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DB가 응답하지 않으면 타임아웃 안에 `False`로 끊는다.

    타임아웃이 없으면 헬스체크 요청이 걸린 채 쌓이고, Docker HEALTHCHECK도
    자기 타임아웃까지 기다린 뒤에야 실패로 판정한다.
    """

    async def never_answers(_: AsyncEngine) -> None:
        await asyncio.sleep(10)

    monkeypatch.setattr(db_module, "_ping", never_answers)

    started = time.perf_counter()
    result = await db_module.check_database(timeout=0.05)
    elapsed = time.perf_counter() - started

    assert result is False
    assert elapsed < 2.0, "타임아웃이 실제로 끊지 못했다"


async def test_check_database_returns_true_when_ping_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """정상 경로."""

    async def answer(_: AsyncEngine) -> None:
        return None

    monkeypatch.setattr(db_module, "_ping", answer)

    assert await db_module.check_database(timeout=1.0) is True


# --------------------------------------------------------------------------
# wait_for_database() — 기동 시 재시도 (FR-9.2)
# --------------------------------------------------------------------------
async def test_wait_for_database_retries_until_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실패해도 백오프로 다시 시도해 결국 성공하면 조용히 통과한다.

    이것이 FR-9.2의 "그래도 연결이 실패하면 재시도한다"다. MariaDB는 healthcheck를
    통과하면서도 초기화 스크립트를 돌리는 중일 수 있어, 첫 시도가 자주 실패한다.
    """
    monkeypatch.setattr(db_module, "BACKOFF_INITIAL_SECONDS", 0.01)
    monkeypatch.setattr(db_module, "BACKOFF_MAX_SECONDS", 0.02)
    attempts = 0

    async def fail_twice(_: AsyncEngine) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _connection_refused()

    monkeypatch.setattr(db_module, "_ping", fail_twice)

    await db_module.wait_for_database(timeout=5.0)

    assert attempts == 3


async def test_wait_for_database_gives_up_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """예산을 다 쓰면 `DatabaseUnavailableError`를 던진다.

    조용히 통과하면 DB 없이 앱이 뜨고, 모든 요청이 오류가 되는데 컨테이너는
    healthy로 보인다. 여기서 죽는 편이 낫다 — 재시작 정책이 다시 시도한다.
    """
    monkeypatch.setattr(db_module, "BACKOFF_INITIAL_SECONDS", 0.01)
    monkeypatch.setattr(db_module, "BACKOFF_MAX_SECONDS", 0.02)

    async def always_refuse(_: AsyncEngine) -> None:
        raise _connection_refused()

    monkeypatch.setattr(db_module, "_ping", always_refuse)

    with pytest.raises(db_module.DatabaseUnavailableError) as excinfo:
        await db_module.wait_for_database(timeout=0.1)

    # 원인 예외를 잃지 않는다 — 로그에서 "왜 못 붙었나"를 알 수 있어야 한다.
    assert isinstance(excinfo.value.__cause__, OperationalError)


async def test_wait_for_database_respects_its_time_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """재시도가 주어진 예산을 크게 넘기지 않는다.

    넘기면 컨테이너 기동이 무한정 늘어져, 무엇이 잘못됐는지 모른 채 기다리게 된다.
    """
    monkeypatch.setattr(db_module, "BACKOFF_INITIAL_SECONDS", 0.05)
    monkeypatch.setattr(db_module, "BACKOFF_MAX_SECONDS", 0.05)

    async def always_refuse(_: AsyncEngine) -> None:
        raise _connection_refused()

    monkeypatch.setattr(db_module, "_ping", always_refuse)

    started = time.perf_counter()
    with pytest.raises(db_module.DatabaseUnavailableError):
        await db_module.wait_for_database(timeout=0.2)
    elapsed = time.perf_counter() - started

    assert elapsed < 2.0, f"예산 0.2초를 크게 넘겼다 ({elapsed:.2f}초)"

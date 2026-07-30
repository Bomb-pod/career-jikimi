"""`core/db` — SQLAlchemy async 엔진, 세션 팩토리, 선언적 기반 클래스.

공개 표면 (`inception/application-design/components.md` § core/db):

    Base            — 모든 모델의 선언적 기반 클래스
    get_session()   — 요청 단위 세션 FastAPI 의존성

`unit-of-work-dependency.md`가 정한 U1의 제공 계약이 이 둘(과 `settings`)이다.
**이름과 시그니처를 바꾸면 U2~U5 네 단위가 전부 깨진다.**

이 모듈이 추가로 노출하는 것(U1 내부용이지만 뒤 단위가 써도 되는 것):

    TABLE_KWARGS         — 모든 테이블에 붙는 utf8mb4 지정
    wait_for_database()  — 기동 시 DB 연결 재시도 (FR-9.2)
    check_database()     — /health의 얕은 DB 체크
    dispose_engine()     — 종료 시 커넥션 풀 정리

**트랜잭션 경계**는 요청 하나 = 트랜잭션 하나가 기본이다. 예외는 U5의 seq 채번이며
(FR-4.2), 그 안에서 `SELECT ... FOR UPDATE`로 명시적으로 잠금을 건다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Final

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# 재시도·타임아웃 상수
# --------------------------------------------------------------------------

#: 기동 시 DB 연결을 포기하기까지의 총 대기 시간 (FR-9.2).
#: compose의 `depends_on: service_healthy`가 이미 db healthcheck를 기다리지만
#: MariaDB는 ping에 응답하면서도 초기화 스크립트를 돌리는 중일 수 있다 —
#: healthcheck만으로 부족해서 재시도를 함께 둔다 (services.md § 기동 순서).
STARTUP_TIMEOUT_SECONDS: Final[float] = 30.0

#: 지수 백오프의 첫 대기와 상한. 상한을 두는 이유는 30초 예산 안에서
#: 시도 횟수를 확보하기 위해서다 — 상한이 없으면 0.5→1→2→4→8→16으로
#: 여섯 번 만에 예산을 다 쓴다.
BACKOFF_INITIAL_SECONDS: Final[float] = 0.5
BACKOFF_MAX_SECONDS: Final[float] = 4.0

#: `/health`의 DB 체크 타임아웃 (code-generation-plan.md § 열린 항목).
#: 2초로 짧게 잡아 DB가 잠깐 느릴 때의 오탐을 억제한다. 이보다 오래 걸리는
#: DB는 이 앱에게 실질적으로 죽은 것이다 — 사용자 요청도 그만큼 밀린다.
HEALTH_CHECK_TIMEOUT_SECONDS: Final[float] = 2.0

# --------------------------------------------------------------------------
# 테이블 공통 옵션
# --------------------------------------------------------------------------

#: 모든 테이블의 `__table_args__` 마지막 요소로 붙는다.
#:
#: **서버 기본값에 기대지 않고 테이블마다 명시하는 이유** (FR-9.3) — compose의
#: `--character-set-server` 인자를 누가 지우거나, 다른 MariaDB 인스턴스에
#: 마이그레이션을 돌리면 기본값이 `latin1`이나 `utf8mb3`일 수 있다. 그러면
#: 한글이 깨지거나 이모지가 잘리고, 그 사실은 데이터가 이미 망가진 뒤에 드러난다.
#: DDL에 박아두면 어느 서버에서 돌려도 같은 결과가 나온다.
TABLE_KWARGS: Final[dict[str, str]] = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_unicode_ci",
}

#: 제약·인덱스 이름 규칙. 이 프로젝트의 모델은 제약 이름을 전부 명시하지만
#: (명시가 규칙보다 우선한다), 뒤 단위가 `alembic revision --autogenerate`로
#: 컬럼을 추가할 때 익명 제약에 안정적인 이름이 붙게 하려고 함께 둔다.
#: 이름이 없으면 마이그레이션 downgrade에서 무엇을 지울지 특정할 수 없다.
NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """모든 모델의 선언적 기반 클래스.

    `Base.metadata`가 Alembic의 `target_metadata`다 (ADR-006). 테이블은
    `create_all()`이 아니라 마이그레이션이 만든다 — 이 클래스는 스키마의
    **선언**이고, 적용은 `migrations/`가 한다.
    """

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


class DatabaseUnavailableError(RuntimeError):
    """기동 재시도 예산을 다 써도 DB에 닿지 못했다.

    이 예외는 잡지 않는다 — lifespan에서 올라가 프로세스가 죽고, 컨테이너
    재시작 정책이 다시 시도한다. 조용히 DB 없이 뜨는 앱보다 낫다.
    """


# --------------------------------------------------------------------------
# 엔진과 세션 팩토리
# --------------------------------------------------------------------------

#: 커넥션 풀은 기본값을 쓴다 — 데모 규모에서 튜닝할 이유가 없다
#: (services.md § app<->db).
#:
#: `pool_pre_ping=True`: 죽은 커넥션을 체크아웃하기 전에 걸러낸다. db 컨테이너를
#: 재시작하면 풀에 남은 커넥션이 전부 끊기는데, 이것이 없으면 재시작 후 첫 요청들이
#: 사용자에게 오류로 보인다.
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

#: `expire_on_commit=False`: 커밋 후에도 ORM 객체의 속성을 읽을 수 있다. 이것이
#: 없으면 커밋 뒤 응답을 직렬화할 때 만료된 속성마다 추가 SELECT가 나간다(async에서는
#: 그 지연 로드가 아예 예외가 된다).
SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    """요청 단위 세션을 주는 FastAPI 의존성.

    사용법:

        @router.get("/rooms")
        async def list_rooms(session: AsyncSession = Depends(get_session)): ...

    **요청 하나 = 트랜잭션 하나.** 핸들러가 정상 종료하면 커밋하고, 예외가 나면
    롤백한 뒤 그 예외를 그대로 올린다 — 삼켜서 반쯤 쓰인 상태를 남기지 않는다.

    핸들러 안에서 직접 `await session.commit()`을 불러도 된다. U5의 seq 채번처럼
    브로드캐스트를 커밋 이후로 미뤄야 하는 경우가 그렇다 (services.md).
    이미 커밋된 세션에 대한 여기서의 커밋은 아무 일도 하지 않는다.
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def _ping(target: AsyncEngine) -> None:
    """`SELECT 1` 한 번. 실패하면 드라이버 예외가 그대로 올라온다.

    별도 함수로 뺀 이유는 테스트에서 이 지점만 갈아끼워 타임아웃·연결 실패
    경로를 실제 DB 없이 검증하기 위해서다.
    """
    async with target.connect() as connection:
        await connection.execute(sa.text("SELECT 1"))


async def wait_for_database(
    *,
    # ASYNC109를 끄는 이유 — ruff는 호출자가 `asyncio.timeout`으로 감싸라고 권한다.
    # 그러면 "예산 안에서 백오프로 몇 번 시도한다"는 이 함수의 핵심 동작이 사라진다.
    # 타임아웃은 취소 시점이 아니라 **재시도 예산**이므로 이 함수가 소유해야 한다.
    timeout: float = STARTUP_TIMEOUT_SECONDS,  # noqa: ASYNC109
    target: AsyncEngine | None = None,
) -> None:
    """DB에 닿을 때까지 지수 백오프로 재시도한다 (FR-9.2).

    Args:
        timeout: 총 대기 예산(초). 이 시간을 넘기면 포기한다.
        target: 검사할 엔진. 기본값은 모듈 전역 엔진.

    Raises:
        DatabaseUnavailableError: 예산 안에 연결하지 못했다.
    """
    checked = target if target is not None else engine
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    delay = BACKOFF_INITIAL_SECONDS
    attempt = 0
    last_error: BaseException | None = None

    while True:
        attempt += 1
        try:
            await _ping(checked)
        except Exception as exc:  # 드라이버 예외 종류가 다양해 광범위하게 잡는다
            last_error = exc
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            sleep_for = min(delay, remaining)
            logger.warning(
                "DB 연결 실패 (시도 %d) — %.1f초 후 재시도합니다: %s",
                attempt,
                sleep_for,
                exc,
            )
            await asyncio.sleep(sleep_for)
            delay = min(delay * 2, BACKOFF_MAX_SECONDS)
        else:
            logger.info("DB 연결 확인 (시도 %d)", attempt)
            return

    raise DatabaseUnavailableError(
        f"{timeout:.0f}초 동안 {attempt}번 시도했으나 DB에 연결하지 못했습니다"
    ) from last_error


async def check_database(
    *,
    # ASYNC109를 끄는 이유 — 헬스체크의 타임아웃 값은 이 함수의 계약이다.
    # 호출자(FastAPI 핸들러)가 매번 정하게 하면 엔드포인트마다 값이 갈라지고,
    # "2초"라는 결정이 어디에 있는지 알 수 없게 된다.
    timeout: float = HEALTH_CHECK_TIMEOUT_SECONDS,  # noqa: ASYNC109
    target: AsyncEngine | None = None,
) -> bool:
    """`/health`용 얕은 DB 체크. 예외를 던지지 않고 성공 여부만 돌려준다.

    **예외를 밖으로 내지 않는 이유** — 헬스체크의 실패는 500(서버 버그)이 아니라
    503(의존 서비스 이용 불가)이다. 여기서 예외가 올라가면 FastAPI가 500과
    스택트레이스를 만들고, Docker HEALTHCHECK도 사람도 원인을 오해한다.
    대신 경고 로그를 남긴다 — 조용히 실패하지 않는다.
    """
    checked = target if target is not None else engine
    try:
        await asyncio.wait_for(_ping(checked), timeout=timeout)
    except TimeoutError:
        logger.warning("DB 헬스체크 타임아웃 (%.1f초)", timeout)
        return False
    except Exception:
        logger.warning("DB 헬스체크 실패", exc_info=True)
        return False
    return True


async def dispose_engine() -> None:
    """커넥션 풀을 닫는다. 종료 시 한 번 호출한다.

    이것을 빼먹으면 SIGTERM 이후 MariaDB 쪽에 커넥션이 잠시 남아
    "Aborted connection" 경고가 로그에 쌓인다.
    """
    await engine.dispose()
    logger.info("DB 커넥션 풀을 정리했습니다")

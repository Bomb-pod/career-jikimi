"""Alembic 실행 환경 — **async 구성** (ADR-006).

드라이버가 `asyncmy`(async)이므로 Alembic의 동기 마이그레이션 실행을
`connection.run_sync()`로 감싼다. Alembic 자체는 동기 API로 동작하고,
async 커넥션 위에서 그 동기 코드를 돌리는 다리가 `run_sync`다.

접속 URL의 우선순위:
  1. `alembic.ini`의 `sqlalchemy.url` (테스트가 런타임에 주입한다)
  2. `settings.DATABASE_URL` (환경변수 — 평소 경로)

`alembic.ini`에 URL을 비워두는 이유는 자격증명을 소스에 남기지 않기 위해서다
(FR-1.4, NFR-6).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.core.db import Base

# `app.models`를 import해야 6개 테이블이 Base.metadata에 등록된다.
# 이 import가 없으면 autogenerate가 모든 테이블을 "모델에 없다"고 보고
# DROP TABLE 마이그레이션을 만든다.
import app.models  # noqa: F401  # isort:skip

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers=False`가 기본값(True)과 다르다. 기본값이면 이
    # 호출이 **이미 만들어진 모든 로거를 꺼버린다** — `alembic.ini`의 [loggers]에
    # 이름이 없는 것 전부, 즉 `app.*` 전체다. 별도 프로세스로 마이그레이션을
    # 돌리는 운영 경로에서는 드러나지 않지만, 같은 프로세스에서 돌리면(테스트의
    # `migrated_database` 픽스처) 그 뒤로 앱 로그가 조용히 사라진다.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """마이그레이션을 적용할 대상 URL."""
    override = config.get_main_option("sqlalchemy.url", default="")
    return override or settings.DATABASE_URL


def _configure(connection: Connection | None = None, *, url: str | None = None) -> None:
    """`context.configure`의 공통 인자를 한곳에 모은다.

    `compare_type`/`compare_server_default`를 켜는 이유 — 뒤 단위가 컬럼 타입이나
    기본값을 바꿀 때 autogenerate가 그 차이를 잡아준다. 끄면 모델은 바뀌었는데
    마이그레이션이 비어 있고, 그 불일치는 운영 DB에서만 드러난다.
    """
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # 마이그레이션 SQL을 트랜잭션으로 감싼다. MariaDB의 DDL은 트랜잭션이
        # 아니지만(암묵 커밋), 버전 테이블 갱신에는 의미가 있다.
        transaction_per_migration=True,
    )


def run_migrations_offline() -> None:
    """`--sql` 모드 — DB에 붙지 않고 SQL만 출력한다.

    운영에서 DBA가 SQL을 먼저 검토하는 흐름을 위한 것이다. 이 데모에서는 쓰지
    않지만, 빼두면 `alembic upgrade head --sql`이 알 수 없는 오류로 죽는다.
    """
    _configure(url=_database_url())
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """동기 커넥션 위에서 실제 마이그레이션을 돌린다.

    `run_sync`가 넘겨주는 것은 async 커넥션을 감싼 동기 프록시다.
    """
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """async 엔진을 열어 `do_run_migrations`를 실행한다.

    `NullPool`을 쓰는 이유 — 마이그레이션은 한 번 붙고 끝나므로 풀을 만들 이유가
    없고, 풀을 쓰면 프로세스 종료 시 정리되지 않은 커넥션 경고가 남는다.
    """
    connectable = create_async_engine(_database_url(), poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """DB에 붙어 마이그레이션을 적용한다 — 평소 경로."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

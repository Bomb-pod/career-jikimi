"""pytest 공용 픽스처.

**필수 환경변수를 여기서 먼저 넣는 이유** — `app.core.config`는 import 시점에
`settings`를 만들고 필수 키가 비어 있으면 실패한다(그것이 FR-1.4/NFR-6의 장치다).
conftest는 테스트 모듈보다 먼저 import되므로, 여기가 그 값을 넣을 수 있는 유일한
지점이다.

**테스트 DB로 SQLite 인메모리를 쓰지 않는다** (code-generation-plan.md Step 7).
이 스키마는 MariaDB 전용 성질에 기대고 있다 — 복합 PK, `utf8mb4` 지정, ENUM,
`DATETIME(6)`, U5가 쓸 `SELECT ... FOR UPDATE`. SQLite로 검증하면 그중 어느 것도
실제로 확인되지 않으면서 테스트는 초록색이 된다. 거짓 통과가 검증 없음보다 나쁘다.

그래서 스키마 테스트는 **실제 MariaDB**를 쓰고, 없으면 **skip**한다.
`TEST_DATABASE_URL`을 넣으면 돈다:

    TEST_DATABASE_URL=mysql+asyncmy://root:<pw>@127.0.0.1:3306/career_jikimi_test?charset=utf8mb4
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# app import 이전에 필수 환경변수를 채운다
# --------------------------------------------------------------------------
# 여기 값은 **연결에 쓰이지 않는 자리 채우기**다. 자격증명 형태를 피해 사용자/비밀번호를
# 넣지 않았다 — 이 저장소에는 어떤 형태의 비밀 리터럴도 두지 않는다 (FR-1.4).
# 실제 DB에 붙는 테스트는 아래 TEST_DATABASE_URL을 쓴다.
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://127.0.0.1:3306/unused?charset=utf8mb4")
os.environ.setdefault("JWT_SECRET", "placeholder-for-unit-tests")
os.environ.setdefault("OPENAI_API_KEY", "placeholder-for-unit-tests")


def _load_repo_dotenv() -> None:
    """저장소 루트의 `.env`에서 아직 환경에 없는 키만 채운다.

    없으면 `TEST_DATABASE_URL`을 매번 손으로 export해야 하고, 잊으면 스키마
    테스트가 조용히 skip된다 — 통과처럼 보이는 미검증이 가장 나쁘다. 그냥
    `pytest`만 쳐도 `.env`를 채운 개발자의 의도대로 돈다.

    **이 호출이 위 세 `setdefault` 뒤에 오는 것이 중요하다.** `.env`의
    `DATABASE_URL`은 compose 네트워크의 호스트명 `db`를 가리켜 호스트에서
    닿지 않는다. 뒤에 오면 자리 채우기 값이 이미 들어가 있어 그 URL이
    적용되지 않는다.

    python-dotenv를 쓰지 않는다 — 테스트 하네스에 런타임 의존성을 하나
    늘리는 것보다 `KEY=VALUE` 파싱 여덟 줄이 싸다.
    """
    dotenv = BACKEND_DIR.parent / ".env"
    if not dotenv.is_file():
        return
    for raw in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            os.environ.setdefault(key, value)


_load_repo_dotenv()

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()

#: 초기 마이그레이션이 만드는 테이블 6개 (alembic_version은 제외).
EXPECTED_TABLES: tuple[str, ...] = (
    "users",
    "friendships",
    "rooms",
    "room_members",
    "messages",
    "judgment_logs",
)


# --------------------------------------------------------------------------
# 실제 MariaDB 픽스처
# --------------------------------------------------------------------------
async def _reachable(url: str) -> bool:
    """DB에 붙을 수 있는지 확인한다. 실패 이유는 skip 메시지로 흘려보낸다."""
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            await connection.execute(sa.text("SELECT 1"))
    except Exception:
        return False
    else:
        return True
    finally:
        await engine.dispose()


async def _drop_all_tables(url: str) -> None:
    """테스트 DB를 비운다 — `alembic_version`까지 지워 빈 DB에서 시작하게 한다.

    FK가 서로 걸려 있어 삭제 순서를 맞추기 번거로우므로 외래키 검사를 잠시 끈다.
    """
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            rows = await connection.execute(
                sa.text(
                    "SELECT TABLE_NAME FROM information_schema.TABLES "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
                )
            )
            names = [row[0] for row in rows]
            if not names:
                return
            await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
            try:
                for name in names:
                    await connection.exec_driver_sql(f"DROP TABLE IF EXISTS `{name}`")
            finally:
                await connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
    finally:
        await engine.dispose()


def _alembic_upgrade_head(url: str) -> None:
    """`alembic upgrade head`를 프로그램에서 실행한다.

    `script_location`을 절대 경로로 덮어쓰는 이유 — alembic은 상대 경로를 CWD
    기준으로 푼다. pytest를 backend/ 밖에서 돌리면 마이그레이션을 못 찾는다.
    """
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # env.py가 이 값을 settings.DATABASE_URL보다 우선한다.
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


@pytest.fixture(scope="session")
def migrated_database() -> str:
    """빈 테스트 DB에 초기 마이그레이션을 적용하고 그 URL을 준다.

    `alembic upgrade head`를 **두 번** 돌린다 — 두 번째는 아무것도 하지 않아야
    한다(버전 테이블이 이미 head를 가리킨다). 컨테이너가 재시작할 때마다
    엔트리포인트가 이것을 돌리므로, 두 번째 실행이 안전한지가 실제 요구사항이다.
    """
    if not TEST_DATABASE_URL:
        pytest.skip(
            "TEST_DATABASE_URL이 설정되지 않아 실제 MariaDB 스키마 테스트를 건너뜁니다. "
            ".env.example의 TEST_DATABASE_URL 주석 참조"
        )
    if not asyncio.run(_reachable(TEST_DATABASE_URL)):
        pytest.skip(
            "TEST_DATABASE_URL의 MariaDB에 연결할 수 없어 스키마 테스트를 건너뜁니다 "
            "(DB가 떠 있고 해당 데이터베이스가 만들어져 있어야 합니다)"
        )

    asyncio.run(_drop_all_tables(TEST_DATABASE_URL))
    _alembic_upgrade_head(TEST_DATABASE_URL)
    # 멱등성 확인 — 실패하면 여기서 예외가 올라가 테스트가 붉어진다.
    _alembic_upgrade_head(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.fixture
async def db_connection(migrated_database: str) -> AsyncIterator[object]:
    """마이그레이션된 DB의 커넥션. 테스트가 끝나면 **롤백**한다.

    커밋하지 않으므로 테스트끼리 데이터가 새지 않는다. TRUNCATE로 정리하는
    방식보다 빠르고, 정리를 잊을 여지가 없다.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(migrated_database)
    try:
        async with engine.connect() as connection:
            try:
                yield connection
            finally:
                await connection.rollback()
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------
# HTTP 클라이언트
# --------------------------------------------------------------------------
@pytest.fixture
def client() -> Iterator[object]:
    """`/health`를 두드릴 TestClient.

    **컨텍스트 매니저로 열지 않는다** — 그러면 lifespan이 돌고, lifespan은 실제 DB
    연결을 30초까지 기다린다(FR-9.2). DB 없이 엔드포인트 자체를 검증하려면
    lifespan을 건너뛰어야 한다. DB 도달 여부는 `db_health_probe` 의존성을
    덮어써서 주입한다.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        app.dependency_overrides.clear()


# --------------------------------------------------------------------------
# U3 auth-friends — 실제 DB에 붙는 세션과 API 클라이언트
# --------------------------------------------------------------------------
# **`TestClient`를 쓰지 않고 `httpx.AsyncClient` + `ASGITransport`를 쓰는 이유** —
# `TestClient`는 앱을 별도 스레드의 별도 이벤트 루프에서 돌린다. asyncmy 커넥션은
# 자기를 만든 루프에 묶여 있어서, 테스트가 만든 세션을 앱이 쓰면 즉시 깨진다.
# `ASGITransport`는 **테스트와 같은 루프**에서 앱을 호출하므로 커넥션을 공유할 수 있다.
#
# `TestClient`를 쓰는 U1의 `client` 픽스처는 그대로 둔다 — `/health`는 DB 세션을
# 쓰지 않아 이 문제가 없다.


@pytest.fixture
async def db_bound_sessionmaker(migrated_database: str) -> AsyncIterator[Any]:
    """테스트 하나 동안 살아 있는 세션 팩토리. 끝나면 **전부 롤백**한다.

    바깥 트랜잭션 하나를 열어두고 그 위의 세션에 `join_transaction_mode=
    "create_savepoint"`를 준다. 그러면 앱이 `session.commit()`을 불러도 SAVEPOINT만
    풀리고 바깥 트랜잭션은 열려 있어, 테스트 끝에 한 번 롤백하면 그 테스트가 만든
    모든 행이 사라진다.

    **TRUNCATE로 정리하지 않는 이유** — 정리를 잊을 여지가 없고, 테스트가 중간에
    죽어도 데이터가 남지 않는다. U1의 `db_connection`이 같은 원리를 쓴다.

    `commit()`이 진짜 커밋이 아니라는 점이 이 픽스처의 유일한 거짓이다. 대신
    `IntegrityError` → `session.rollback()` 경로는 SAVEPOINT 롤백으로 실제와 같게
    동작하므로, 이 단위가 검증해야 하는 것(무결성 위반의 도메인 예외 변환)은
    그대로 확인된다.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(migrated_database)
    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield factory
    finally:
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest.fixture
async def db_session(db_bound_sessionmaker: Any) -> AsyncIterator[Any]:
    """서비스 함수를 직접 부를 때 쓰는 세션 (라우터를 거치지 않는 테스트용)."""
    async with db_bound_sessionmaker() as session:
        yield session


@pytest.fixture
async def live_sessionmaker(migrated_database: str) -> AsyncIterator[Any]:
    """**진짜로 커밋하는** 세션 팩토리. 세션마다 자기 커넥션을 잡는다 (U5 messaging).

    위의 `db_bound_sessionmaker`는 커넥션 하나 위에 savepoint를 얹어 롤백으로
    격리하므로 두 가지를 검증할 수 없다:

    - **동시성** — 커넥션이 하나면 두 요청이 물리적으로 겹치지 않는다. `FOR UPDATE`가
      없어도 통과하므로 아무것도 증명하지 못한다 (FR-4.2, NFR-7의 명시 의무).
    - **커밋 가시성** — 아무것도 진짜로 커밋되지 않아 "브로드캐스트 시점에 다른
      커넥션에서 그 행이 보이는가"를 물을 수 없다 (FR-4.1, NFR-3).

    끝나면 이 픽스처가 만든 행을 지운다. **다른 테스트는 savepoint로 롤백해 커밋된
    행을 남기지 않으므로** 여기서 다섯 테이블을 비워도 남의 데이터를 건드리지 않는다.
    FK 순서대로 지운다 — 역순이면 참조 오류가 난다.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(migrated_database)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            # 테이블 이름은 아래 리터럴 튜플에서만 온다 — 사용자 입력이 닿지 않는다.
            for table in ("judgment_logs", "messages", "room_members", "rooms", "users"):
                await connection.exec_driver_sql(f"DELETE FROM `{table}`")  # noqa: S608
        await engine.dispose()


@pytest.fixture
async def api_client(db_bound_sessionmaker: Any) -> AsyncIterator[Any]:
    """`get_session`을 테스트 DB로 갈아끼운 HTTP 클라이언트.

    override가 U1의 `get_session()`과 **같은 트랜잭션 규약**을 흉내낸다 — 핸들러가
    성공하면 커밋, 예외가 나면 롤백. 그 규약이 다르면 `IntegrityError` 뒤의 세션
    상태가 실제와 달라져 테스트가 거짓으로 통과한다.
    """
    import httpx

    from app.core.db import get_session
    from app.main import app

    async def _override() -> AsyncIterator[Any]:
        async with db_bound_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = _override
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_session, None)


# --------------------------------------------------------------------------
# 쿼리 수 계측 — N+1 회귀 방지 (BR-2.8)
# --------------------------------------------------------------------------
@contextmanager
def capture_sql() -> Iterator[list[str]]:
    """블록 안에서 드라이버로 나간 SQL 문장을 모은다.

    `Engine` **클래스**에 리스너를 붙이므로 엔진 인스턴스를 넘겨받을 필요가 없다.
    테스트가 끝나면 반드시 떼어낸다 — 남으면 다른 테스트의 SQL까지 쌓인다.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    statements: list[str] = []

    def _record(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(Engine, "before_cursor_execute", _record)


def selects(statements: list[str]) -> list[str]:
    """모은 문장 중 SELECT만 고른다.

    SAVEPOINT·RELEASE 같은 트랜잭션 제어문을 세면 픽스처 구현이 테스트 수치에
    섞인다. 쿼리 수를 논할 때 세고 싶은 것은 조회다.
    """
    return [item for item in statements if item.lstrip().upper().startswith("SELECT")]


# --------------------------------------------------------------------------
# API 테스트 공용 헬퍼
# --------------------------------------------------------------------------
#: 테스트에서 쓰는 기본 비밀번호. BR-1.2의 8자를 넘긴다.
VALID_PASSWORD = "pw123456"


def bearer(token: str) -> dict[str, str]:
    """`Authorization` 헤더를 만든다."""
    return {"Authorization": f"Bearer {token}"}


async def make_user(session: Any, username: str, display_name: str | None = None) -> Any:
    """사용자 하나를 심는다. `display_name`을 주지 않으면 `username`을 복사한다.

    U2의 테스트가 쓰는 준비 헬퍼다 — `judgment_logs.user_id`가 `users.id`를 FK로
    참조하므로 로그를 만들려면 사용자가 먼저 있어야 한다. 회원가입(W1)의 초기값
    규칙과 같게 둔다.
    """
    from app.models import User

    user = User(
        username=username,
        display_name=display_name if display_name is not None else username,
        # 이 헬퍼를 쓰는 테스트는 해싱을 검증하지 않는다. 자리 채우기 값이다.
        password_hash="$argon2id$placeholder",
    )
    session.add(user)
    await session.flush()
    return user


async def make_room(session: Any, created_by: int, name: str | None = None) -> Any:
    """방 하나를 심는다. `judgment_logs.room_id`의 FK를 만족시키기 위한 것이다."""
    from app.models import Room

    room = Room(name=name, created_by=created_by)
    session.add(room)
    await session.flush()
    return room


async def signup_via_api(
    client: Any, username: str, password: str = VALID_PASSWORD
) -> dict[str, Any]:
    """가입해서 `{token, user}`를 돌려준다. 실패하면 그 자리에서 터진다.

    친구 테스트의 준비 단계를 API로 하는 이유 — 서비스 함수로 사용자를 심으면
    라우터·스키마 경로가 빠져 "실제로 그 응답으로 만들어진 데이터"가 아니게 된다.
    """
    response = await client.post("/auth/signup", json={"username": username, "password": password})
    assert response.status_code == 201, response.text
    payload: dict[str, Any] = response.json()
    return payload

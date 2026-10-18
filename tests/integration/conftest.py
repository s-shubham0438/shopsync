"""Fixtures for tests that need a real PostgreSQL.

Uses TEST_DATABASE_URL (default: the local shopsync_test database). If it isn't reachable,
every test in this package is skipped, so the unit suite still runs anywhere.
"""

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://shopsync:shopsync@localhost:5432/shopsync_test"
)

pytestmark = pytest.mark.integration


def alembic_config(url: str = TEST_DATABASE_URL) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = url
    return cfg


async def _can_connect(url: str) -> bool:
    engine = create_async_engine(url, poolclass=NullPool, connect_args={"timeout": 3})
    try:
        async with engine.connect():
            return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def migrated_db() -> Iterator[str]:
    """A test database migrated from scratch to head (once per test session)."""
    if (
        make_url(TEST_DATABASE_URL).database
        == make_url("postgresql://x@localhost/shopsync").database
    ):
        pytest.exit("TEST_DATABASE_URL points at the development database; refusing to wipe it.")
    if not asyncio.run(_can_connect(TEST_DATABASE_URL)):
        safe_url = make_url(TEST_DATABASE_URL).render_as_string()  # password masked
        pytest.skip(f"PostgreSQL test database not reachable at {safe_url}")
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield TEST_DATABASE_URL


@pytest.fixture
async def engine(migrated_db: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated_db, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with engine.connect() as conn:
        trans = await conn.begin()
        yield conn
        await trans.rollback()  # every test leaves the database exactly as it found it


@pytest.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    # session.commit() inside tests only releases a SAVEPOINT; the outer transaction is
    # rolled back by the `connection` fixture.
    async with AsyncSession(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    ) as session:
        yield session

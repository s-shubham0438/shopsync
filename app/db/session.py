from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_pre_ping=True,
        echo=settings.db_echo,
        connect_args={
            "timeout": settings.db_connect_timeout_seconds,
            "server_settings": {"application_name": settings.app_name},
        },
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: with async sessions, touching an expired attribute
    # after commit would trigger implicit IO and raise MissingGreenlet.
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    """One session per request. Services own the transaction and call commit();
    anything uncommitted is rolled back when the session closes."""
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.db_sessionmaker
    async with sessionmaker() as session:
        yield session


def get_engine(request: Request) -> AsyncEngine:
    engine: AsyncEngine = request.app.state.db_engine
    return engine

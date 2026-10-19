from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


# Single engine per process; created lazily by get_engine().
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        # Pool limits apply to server-side databases only.
        connect_args: dict = {}
        engine_kwargs: dict = {
            "echo": False,
            "future": True,
        }
        if url.startswith("postgresql"):
            engine_kwargs.update(pool_size=10, max_overflow=20, pool_pre_ping=True)
        if url.startswith("sqlite"):
            connect_args = {"timeout": 30}
            engine_kwargs.update(poolclass=None)
        _engine = create_async_engine(url, connect_args=connect_args, **engine_kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _sessionmaker


async def reset_engine() -> None:
    """Dispose engine (used by tests between model-bound test DBs)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        yield session


def override_get_db(sessionmaker: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async def _inner() -> AsyncGenerator[AsyncSession, None]:
        async with sessionmaker() as session:
            yield session

    return _inner

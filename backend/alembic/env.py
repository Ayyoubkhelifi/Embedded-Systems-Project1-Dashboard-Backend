import asyncio
import os

from alembic import context
from sqlalchemy.engine import Connection

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_engine
from app import models  # noqa: F401 — registers all tables on Base.metadata

config = context.config

# Alembic connects with a *sync* URL; async drivers are translated here.
def _sync_url() -> str:
    url = os.environ.get("DATABASE_URL", get_settings().database_url)
    if "+aiosqlite" in url:
        return url.replace("+aiosqlite", "+sqlite")
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    return url


target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = get_engine()
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


def run_migrations_online() -> None:
    if _sync_url().startswith(("postgresql+", "postgres://")):
        # Prefer the configured async engine (pools, auth via URL/env).
        asyncio.run(run_async_migrations())
        return
    # SQLite fallback: connect synchronously with a short-lived engine.
    from sqlalchemy import create_engine

    engine = create_engine(_sync_url(), echo=False)
    with engine.connect() as connection:
        do_run_migrations(connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

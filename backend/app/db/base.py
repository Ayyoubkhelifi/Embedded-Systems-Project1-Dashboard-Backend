from datetime import UTC, datetime, timezone
from typing import Annotated

from sqlalchemy import BigInteger, DateTime, Integer, types as sa_types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, mapped_column
from sqlalchemy.types import JSON

intpk = Annotated[
    int,
    mapped_column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    ),
]
"""Auto-increment big-integer PK (INTEGER on SQLite so it aliases rowid)."""


class UTCDateTime(sa_types.TypeDecorator):
    """DateTime that always round-trips timezone-aware UTC values.

    PostgreSQL `timestamptz` is natively aware; SQLite returns naive values.
    Wrapping normalizes everything to aware UTC so Pydantic serializes the
    same shape regardless of the dialect backing the tests vs production.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    """Declarative base for all models (Alembic autogenerate target)."""


def utcnow() -> datetime:
    """Timezone-aware UTC timestamp used for every default."""
    return datetime.now(UTC)


def json_column():
    """Portable JSON column: JSONB on PostgreSQL, JSON (TEXT) on SQLite."""
    return JSON().with_variant(JSONB(), "postgresql")

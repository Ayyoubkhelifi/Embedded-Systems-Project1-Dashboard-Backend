import os

os.environ.setdefault("ENV", "testing")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")
os.environ.setdefault("SECRET_JWT_KEY", "testing-secret-key-not-for-production-0123456789")
os.environ.setdefault("RATE_LIMIT_GENERAL_PER_MINUTE", "1000000")
os.environ.setdefault("RATE_LIMIT_INGEST_PER_MINUTE", "1000000")
os.environ.setdefault("DEVICE_FRESHNESS_TIMEOUT_SECONDS", "900")
os.environ.setdefault("JWT_ALGORITHM", "HS256")

import uuid
from pathlib import Path

import pytest
import pytest_asyncio  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.core.security import gateway_key_fingerprint, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import reset_engine  # noqa: E402
from app.models import Device, Gateway, User  # noqa: E402
from app.services.settings_service import seed_defaults  # noqa: E402

TEST_GATEWAY_KEY = "ess_gw_test-key-0001"
TEST_ADMIN_USER = "admin@test.local"
TEST_ADMIN_PASS = "supersecretpass1"


@pytest_asyncio.fixture
async def client():
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture(autouse=True)
async def test_db(monkeypatch, tmp_path: Path):
    await reset_engine()
    db_file = tmp_path / f"test-{uuid.uuid4().hex}.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        poolclass=NullPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_pragma(dbapi_conn, _rec):  # enforce FKs on every fresh connection
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    sm = async_sessionmaker(engine, expire_on_commit=False)

    import app.db.session as session_mod

    monkeypatch.setattr(session_mod, "_engine", engine)
    monkeypatch.setattr(session_mod, "_sessionmaker", sm)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with sm() as session:
        session.add(
            User(
                username=TEST_ADMIN_USER,
                password_hash=hash_password(TEST_ADMIN_PASS),
                role="admin",
            )
        )
        session.add(
            Gateway(
                name="primary",
                gateway_ref="gw-1",
                api_key_hash=hash_password(TEST_GATEWAY_KEY),
                api_key_fingerprint=gateway_key_fingerprint(TEST_GATEWAY_KEY),
            )
        )
        await seed_defaults(session)
        await session.commit()

    yield {"sessionmaker": sm, "engine": engine, "path": db_file}

    await engine.dispose()
    await reset_engine()
    try:
        db_file.unlink(missing_ok=True)
    except OSError:
        pass


async def _register_device(device_id: int, name: str, location: str = "lab") -> None:
    from app.models import Device

    sm = current_sessionmaker()
    async with sm() as session:
        session.add(Device(device_id=device_id, name=name, location=location))
        await session.commit()


def current_sessionmaker():
    """Fetch the current injected sessionmaker (must be called inside a test)."""
    import app.db.session as session_mod

    return session_mod._sessionmaker


async def login_and_get_token(client, username: str = TEST_ADMIN_USER, password: str = TEST_ADMIN_PASS) -> str:
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def gateway_headers() -> dict:
    return {"X-Gateway-Key": TEST_GATEWAY_KEY}

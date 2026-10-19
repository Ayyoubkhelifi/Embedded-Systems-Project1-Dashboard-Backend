"""Development seed: admin user, gateway credentials, demo devices, alert rules.

Usage (after `alembic upgrade head`):
    python -m app.db.seed

Env-driven (see .env.example). Idempotent — repeated runs fill gaps only.
Demo devices created here carry the `seeded` flag in their location so the
dashboard development mode can label simulated data clearly.
"""
import asyncio
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.core.security import gateway_key_fingerprint, hash_password
from app.db.session import get_sessionmaker
from app.models import Base, Device, Gateway, User
from app.services.settings_service import seed_defaults


async def _upsert_admin(session) -> tuple[User, bool]:
    s = get_settings()
    username = s.admin_username
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            username=username,
            password_hash=hash_password(s.admin_password),
            role="admin",
        )
        session.add(user)
        await session.flush()
        return user, True
    return user, False


async def _upsert_gateway(session) -> tuple[Gateway, bool]:
    s = get_settings()
    name = "primary"
    result = await session.execute(select(Gateway).where(Gateway.name == name))
    gateway = result.scalar_one_or_none()
    if gateway is None:
        key = s.gateway_api_key
        gateway = Gateway(
            name=name,
            gateway_ref=s.gateway_id,
            api_key_hash=hash_password(key),
            api_key_fingerprint=gateway_key_fingerprint(key),
        )
        session.add(gateway)
        await session.flush()
        return gateway, True
    return gateway, False


async def _upsert_devices(session) -> list[Device]:
    demo_devices = [
        (101, "ESP32 Node A", "env_node_dht11_mq2_water", "Greenhouse — Bay 1"),
        (102, "ESP32 Node B", "env_node_dht11_mq2_water", "Greenhouse — Bay 2"),
    ]
    created: list[Device] = []
    for lora_id, name, dtype, location in demo_devices:
        result = await session.execute(select(Device).where(Device.device_id == lora_id))
        device = result.scalar_one_or_none()
        if device is None:
            device = Device(device_id=lora_id, name=name, device_type=dtype, location=location)
            session.add(device)
            await session.flush()
            created.append(device)
    return created


async def run_seed() -> None:
    setup_logging("INFO", json_output=False)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        admin, admin_new = await _upsert_admin(session)
        gateway, gw_new = await _upsert_gateway(session)
        devices = await _upsert_devices(session)
        await session.commit()

        from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect  # noqa: F401

        await seed_defaults(session)

    print("Seed complete:")
    print(f"  admin '{admin.username}': {'created' if admin_new else 'already present'}")
    print(f"  gateway '{gateway.name}' (ref={gateway.gateway_ref}): {'created' if gw_new else 'already present'}")
    print(f"  devices: +{len(devices)} new")


def main() -> None:
    sys.exit(asyncio.run(run_seed()) or 0)


if __name__ == "__main__":
    main()

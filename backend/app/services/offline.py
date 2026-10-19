"""Background freshness monitoring — raises/clears device_offline alerts.

Designed for graceful degradation: DB problems are caught, logged, and
retried on the next tick; nothing cascades into uvicorn workers.
"""
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_sessionmaker
from app.models import Device
from app.services.alerts import mark_offline, resolve_offline
from app.services.realtime import manager

logger = get_logger("app.offline")


async def _scan(session: AsyncSession) -> tuple[list[int], list[int]]:
    """Returns (devices that went offline, devices that came back)."""
    timeout = await _current_timeout(session)
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout)

    result = await session.execute(select(Device).where(Device.is_active.is_(True)))
    devices = result.scalars().all()

    went_offline: list[int] = []
    came_back: list[int] = []

    for device in devices:
        last = device.last_seen_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        is_stale = last is None or last < cutoff

        if is_stale and device.status != "offline":
            device.status = "offline"
            alert = await mark_offline(session, device.id)
            if alert is not None:
                went_offline.append(device.id)
        elif not is_stale and device.status == "offline":
            device.status = "online"
            closed = await resolve_offline(session, device.id)
            if closed is not None:
                came_back.append(device.id)

    await session.commit()
    return went_offline, came_back


async def _current_timeout(session: AsyncSession) -> int:
    from app.services.settings_service import get_freshness_timeout

    try:
        return await get_freshness_timeout(session)
    except Exception:  # noqa: BLE001 — fall back to env config on read failure
        return get_settings().device_freshness_timeout_seconds


async def check_device_freshness_once() -> tuple[list[int], list[int]]:
    """One scan — exposed for tests."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        try:
            return await _scan(session)
        except Exception:  # noqa: BLE001 — DB outage must never kill the loop
            logger.exception("freshness scan failed")
            try:
                await session.rollback()
            except Exception:  # noqa: BLE001
                pass
            return [], []


async def offline_monitor_loop(stop_event: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(5, settings.offline_check_interval_seconds)
    logger.info("offline monitor started interval=%ss", interval)
    while not stop_event.is_set():
        try:
            offline, back = await check_device_freshness_once()
            for device_pk in offline:
                await manager.broadcast(
                    "device_status", {"device_id": device_pk, "status": "offline"}
                )
            for device_pk in back:
                await manager.broadcast(
                    "device_status", {"device_id": device_pk, "status": "online"}
                )
        except Exception:  # noqa: BLE001 — belt & braces around the whole tick
            logger.exception("offline monitor tick failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass
    logger.info("offline monitor stopped")

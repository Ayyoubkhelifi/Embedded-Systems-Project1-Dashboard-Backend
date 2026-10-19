"""Telemetry ingestion pipeline — idempotent, device-aware, alert-aware.

Order of operations (all within a single transaction):
1. Compile the caller's validated payload into a SensorReading row.
2. INSERT — a unique-constraint violation on (device_id_ref, packet_seq)
   means this exact packet was already stored (gateway retry): treat as
   duplicate, return stored=False, and still bump gateway liveness.
3. Update the device liveness columns (last_seen, last_seq, rssi, snr).
4. Run the alert engine over the newly-persisted reading.
5. Commit; the caller broadcasts WS events *after* the commit succeeds.
"""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.core.logging import get_logger
from app.models import Device, Gateway, SensorReading
from app.schemas.telemetry import IngestResult, TelemetryIn, TelemetryOut
from app.services.alerts import evaluate_reading
from app.services.realtime import manager

logger = get_logger("app.ingestion")


def _payload_to_row(device_id_ref: int, payload: TelemetryIn) -> SensorReading:
    flags = payload.flags
    return SensorReading(
        device_id_ref=device_id_ref,
        packet_seq=payload.seq,
        temperature_c=payload.temperature_c if flags.temp else None,
        humidity_pct=payload.humidity_pct if flags.hum else None,
        mq2_raw=payload.mq2_raw if flags.mq2 else None,
        water_raw=payload.water_raw if flags.water else None,
        battery_mv=payload.battery_mv if flags.battery else None,
        temp_valid=flags.temp,
        hum_valid=flags.hum,
        mq2_valid=flags.mq2,
        water_valid=flags.water,
        battery_valid=flags.battery,
        water_detected=bool(flags.water_detected and flags.water),
        simulated=flags.simulated,
        rssi=payload.rssi,
        snr=payload.snr,
        gateway_id=payload.gateway_id,
        gateway_time=payload.gateway_time or datetime.now(UTC),
        device_time=None,
    )


async def get_device_by_lora_id(session: AsyncSession, lora_device_id: int) -> Device:
    result = await session.execute(select(Device).where(Device.device_id == lora_device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise ApiError(
            "DEVICE_NOT_REGISTERED",
            f"Device {lora_device_id} is not registered. Register it first via POST /api/v1/devices.",
            status_code=404,
        )
    if not device.is_active:
        raise ApiError(
            "DEVICE_INACTIVE",
            f"Device {lora_device_id} is deactivated and rejects telemetry.",
            status_code=409,
        )
    return device


async def ingest(session: AsyncSession, gateway: Gateway, payload: TelemetryIn) -> IngestResult:
    settings = get_settings()
    if flags_simulated(payload) and settings.is_production and settings.simulate_ingest_disabled_in_production:
        raise ApiError(
            "SIMULATED_TELEMETRY_REJECTED",
            "Simulated telemetry is disabled in production deployments.",
            status_code=403,
        )

    device = await get_device_by_lora_id(session, payload.device_id)
    row = _payload_to_row(device.id, payload)
    session.add(row)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        return IngestResult(stored=False, duplicate=True)

    gateway.last_seen_at = row.gateway_time

    was_offline = device.status == "offline"
    if device.last_seq is None or payload.seq > device.last_seq:
        device.last_seq = payload.seq
    device.last_seen_at = row.gateway_time
    device.status = "online"
    device.last_rssi = payload.rssi
    device.last_snr = payload.snr

    evaluated = await evaluate_reading(session, device.id, row)
    recovered = None
    if was_offline:
        from app.services.alerts import resolve_offline

        recovered = await resolve_offline(session, device.id)
    await session.commit()

    reading_id = row.id

    # Broadcast *after* commit so consumers see only durable state.
    out_payload = {
        "id": reading_id,
        "device_id": payload.device_id,
        "packet_seq": payload.seq,
        "temperature_c": row.temperature_c,
        "humidity_pct": row.humidity_pct,
        "mq2_raw": row.mq2_raw,
        "water_raw": row.water_raw,
        "battery_mv": row.battery_mv,
        "temp_valid": row.temp_valid,
        "hum_valid": row.hum_valid,
        "mq2_valid": row.mq2_valid,
        "water_valid": row.water_valid,
        "battery_valid": row.battery_valid,
        "gas_alarm": row.gas_alarm,
        "water_detected": row.water_detected,
        "simulated": row.simulated,
        "rssi": row.rssi,
        "snr": row.snr,
        "gateway_id": row.gateway_id,
        "gateway_time": row.gateway_time.isoformat() if row.gateway_time else None,
        "device_time": None,
    }
    await manager.broadcast("telemetry", out_payload)

    for alert in evaluated.created:
        await manager.broadcast("alert", _alert_event(alert, payload.device_id))
    for alert in evaluated.closed:
        await manager.broadcast("alert_closed", _alert_event(alert, payload.device_id))
    if recovered is not None:
        await manager.broadcast("alert_closed", _alert_event(recovered, payload.device_id))
        await manager.broadcast(
            "device_status", {"device_id": payload.device_id, "status": "online"}
        )

    statuses = [alert.status for alert in evaluated.created]
    logger.info(
        "telemetry ingested device=%s seq=%s stored=%s alerts=%s",
        payload.device_id,
        payload.seq,
        True,
        statuses,
    )

    return IngestResult(
        stored=True,
        duplicate=False,
        reading_id=reading_id,
        alerts_created=[a.id for a in evaluated.created if a.id is not None],
        alerts_closed=[a.id for a in evaluated.closed if a.id is not None],
    )


def flags_simulated(payload: TelemetryIn) -> bool:
    return payload.flags.simulated


def _reading_out(row, lora_device_id: int) -> dict:
    r = row
    return {
        "id": r.id,
        "device_id": lora_device_id,
        "packet_seq": r.packet_seq,
        "temperature_c": r.temperature_c,
        "humidity_pct": r.humidity_pct,
        "mq2_raw": r.mq2_raw,
        "water_raw": r.water_raw,
        "battery_mv": r.battery_mv,
        "temp_valid": r.temp_valid,
        "hum_valid": r.hum_valid,
        "mq2_valid": r.mq2_valid,
        "water_valid": r.water_valid,
        "battery_valid": r.battery_valid,
        "gas_alarm": r.gas_alarm,
        "water_detected": r.water_detected,
        "simulated": r.simulated,
        "rssi": r.rssi,
        "snr": r.snr,
        "gateway_id": r.gateway_id,
        "gateway_time": r.gateway_time,
        "device_time": r.device_time,
    }


def telemetry_out(row, lora_device_id: int) -> TelemetryOut:
    return TelemetryOut.model_validate(_reading_out(row, lora_device_id))


async def fetch_latest(
    session: AsyncSession, device_id_ref: int | None, limit: int
) -> list[TelemetryOut]:
    stmt = (
        select(SensorReading, Device.device_id)
        .join(Device, Device.id == SensorReading.device_id_ref)
        .order_by(SensorReading.gateway_time.desc(), SensorReading.id.desc())
    )
    if device_id_ref is not None:
        stmt = stmt.where(SensorReading.device_id_ref == device_id_ref)
    stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return [telemetry_out(r, lora) for r, lora in result.all()]


async def fetch_history(
    session: AsyncSession,
    device_id_ref: int | None,
    start: datetime,
    end: datetime,
    limit: int,
    offset: int,
    order: str,
) -> list[TelemetryOut]:
    from sqlalchemy import desc as sa_desc
    from sqlalchemy import asc as sa_asc

    stmt = (
        select(SensorReading, Device.device_id)
        .join(Device, Device.id == SensorReading.device_id_ref)
        .where(SensorReading.gateway_time >= start, SensorReading.gateway_time < end)
    )
    if device_id_ref is not None:
        stmt = stmt.where(SensorReading.device_id_ref == device_id_ref)

    time_sort = sa_desc(SensorReading.gateway_time) if order == "desc" else sa_asc(SensorReading.gateway_time)
    id_sort = sa_desc(SensorReading.id) if order == "desc" else sa_asc(SensorReading.id)
    stmt = stmt.order_by(time_sort, id_sort).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return [telemetry_out(r, lora) for r, lora in result.all()]


def _alert_event(alert, lora_device_id: int) -> dict:
    return {
        "id": alert.id,
        "device_id": lora_device_id,
        "rule_key": alert.rule_key,
        "severity": alert.severity,
        "description": alert.description,
        "status": alert.status,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "acknowledged_at": alert.acknowledged_at.isoformat() if alert.acknowledged_at else None,
        "closed_at": alert.closed_at.isoformat() if alert.closed_at else None,
    }

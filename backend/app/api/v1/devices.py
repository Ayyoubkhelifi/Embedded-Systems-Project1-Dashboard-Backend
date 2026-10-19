from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import AdminUser, DbSession, ViewerUser
from app.core.errors import ApiError
from app.models import Device, SensorReading
from app.schemas.device import DeviceCreate, DeviceDetail, DeviceDetailList, DeviceOut, DeviceUpdate
from app.services.ingestion import telemetry_out

router = APIRouter(prefix="/devices", tags=["devices"])


async def _load_device(session, lora_device_id: int) -> Device:
    result = await session.execute(select(Device).where(Device.device_id == lora_device_id))
    device = result.scalar_one_or_none()
    if device is None:
        raise ApiError("DEVICE_NOT_FOUND", f"Device {lora_device_id} not found.", 404)
    return device


@router.get("", response_model=DeviceDetailList)
async def list_devices(
    _: ViewerUser,
    session: DbSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, pattern="^(online|offline|all)$"),
    include_latest: bool = Query(default=True),
) -> DeviceDetailList:
    total_stmt = select(func.count()).select_from(Device)
    if status and status != "all":
        total_stmt = total_stmt.where(Device.status == status)
    total = (await session.execute(total_stmt)).scalar_one()

    stmt = select(Device).order_by(Device.device_id)
    if status and status != "all":
        stmt = stmt.where(Device.status == status)
    stmt = stmt.limit(limit).offset(offset)
    devices = (await session.execute(stmt)).scalars().all()

    # One grouped query for latest reading ids — avoids N+1 per device.
    latest_by_device: dict[int, SensorReading] = {}
    if include_latest and devices:
        device_pks = [d.id for d in devices]
        id_rows = (
            await session.execute(
                select(SensorReading.device_id_ref, func.max(SensorReading.id)).where(
                    SensorReading.device_id_ref.in_(device_pks)
                ).group_by(SensorReading.device_id_ref)
            )
        ).all()
        reading_ids = [row[1] for row in id_rows if row[1] is not None]
        if reading_ids:
            rows = (
                await session.execute(
                    select(SensorReading).where(SensorReading.id.in_(reading_ids))
                )
            ).scalars().all()
            for r in rows:
                latest_by_device[r.device_id_ref] = r

    items: list[DeviceDetail] = []
    for d in devices:
        item = DeviceDetail.model_validate(d)
        reading = latest_by_device.get(d.id)
        item.latest_reading = telemetry_out(reading, d.device_id) if reading else None
        items.append(item)

    return DeviceDetailList(items=items, total=total)


@router.post("", response_model=DeviceOut, status_code=201)
async def register_device(payload: DeviceCreate, _: AdminUser, session: DbSession) -> DeviceOut:
    existing = await session.execute(select(Device).where(Device.device_id == payload.device_id))
    if existing.scalar_one_or_none() is not None:
        raise ApiError("DEVICE_ID_TAKEN", f"Device {payload.device_id} is already registered.", 409)
    device = Device(
        device_id=payload.device_id,
        name=payload.name,
        device_type=payload.device_type,
        location=payload.location,
    )
    session.add(device)
    await session.commit()
    await session.refresh(device)
    return DeviceOut.model_validate(device)


@router.get("/{device_id}", response_model=DeviceDetail)
async def device_detail(device_id: int, _: ViewerUser, session: DbSession) -> DeviceDetail:
    device = await _load_device(session, device_id)
    detail = DeviceDetail.model_validate(device)
    latest = (
        await session.execute(
            select(SensorReading)
            .where(SensorReading.device_id_ref == device.id)
            .order_by(SensorReading.gateway_time.desc(), SensorReading.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    detail.latest_reading = telemetry_out(latest, device.device_id) if latest else None
    return detail


@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    payload: DeviceUpdate,
    _: AdminUser,
    session: DbSession,
) -> DeviceOut:
    device = await _load_device(session, device_id)
    data = payload.model_dump(exclude_none=True)
    for field, value in data.items():
        setattr(device, field, value)
    await session.commit()
    await session.refresh(device)
    return DeviceOut.model_validate(device)


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, _: AdminUser, session: DbSession) -> None:
    device = await _load_device(session, device_id)
    await session.delete(device)
    await session.commit()

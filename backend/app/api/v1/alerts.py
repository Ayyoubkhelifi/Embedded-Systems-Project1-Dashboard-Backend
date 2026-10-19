from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DbSession, OperatorUser, ViewerUser
from app.core.errors import ApiError
from app.models import Alert, AlertStatus, Device
from app.schemas.alert import AlertAckIn, AlertList, AlertOut
from app.services.realtime import manager

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _alert_out(alert: Alert, lora_device_id: int) -> AlertOut:
    return AlertOut(
        id=alert.id,
        device_id=lora_device_id,
        rule_key=alert.rule_key,
        severity=alert.severity,
        description=alert.description,
        status=alert.status,
        created_at=alert.created_at,
        acknowledged_at=alert.acknowledged_at,
        acknowledged_by=alert.acknowledged_by,
        closed_at=alert.closed_at,
    )


async def _list_base(session: AsyncSession, filters: list) -> tuple[list[AlertOut], int]:
    device_map: dict[int, int] = {}
    rows = (
        await session.execute(
            select(Alert, Device.device_id)
            .join(Device, Device.id == Alert.device_id_ref)
            .where(*filters)
            .order_by(Alert.created_at.desc())
        )
    )
    items: list[AlertOut] = []
    for alert, lora_id in rows.all():
        device_map[alert.id] = lora_id
        items.append(_alert_out(alert, lora_id))
    # `_list_base` counts outside ordering; total computed by caller when needed.
    return items, len(items)


@router.get("", response_model=AlertList)
async def list_alerts(
    _: ViewerUser,
    session: DbSession,
    status: str | None = Query(default=None, pattern="^(open|acknowledged|closed|all)$"),
    device_id: int | None = Query(default=None, ge=1, le=4294967295),
    rule_key: str | None = Query(default=None, max_length=64),
    severity: str | None = Query(default=None, pattern="^(info|warning|critical)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AlertList:
    filters = []
    if status and status != "all":
        filters.append(Alert.status == status)
    if severity:
        filters.append(Alert.severity == severity)
    if rule_key:
        filters.append(Alert.rule_key == rule_key)
    if device_id is not None:
        device = (
            await session.execute(select(Device).where(Device.device_id == device_id))
        ).scalar_one_or_none()
        if device is None:
            raise ApiError("DEVICE_NOT_FOUND", f"Device {device_id} not found.", 404)
        filters.append(Alert.device_id_ref == device.id)

    count_stmt = select(func.count()).select_from(Alert).where(*filters)
    total = (await session.execute(count_stmt)).scalar_one()

    rows = (
        await session.execute(
            select(Alert, Device.device_id)
            .join(Device, Device.id == Alert.device_id_ref)
            .where(*filters)
            .order_by(Alert.created_at.desc(), Alert.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return AlertList(items=[_alert_out(a, lora) for a, lora in rows], total=total)


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(alert_id: int, _: ViewerUser, session: DbSession) -> AlertOut:
    row = (
        await session.execute(
            select(Alert, Device.device_id)
            .join(Device, Device.id == Alert.device_id_ref)
            .where(Alert.id == alert_id)
        )
    ).first()
    if row is None:
        raise ApiError("ALERT_NOT_FOUND", f"Alert {alert_id} not found.", 404)
    alert, lora_id = row
    return _alert_out(alert, lora_id)


@router.patch("/{alert_id}", response_model=AlertOut)
async def acknowledge_alert(
    alert_id: int,
    payload: AlertAckIn,
    actor: OperatorUser,
    session: DbSession,
) -> AlertOut:
    """Acknowledge an open alert (operator or admin)."""
    row = (
        await session.execute(
            select(Alert, Device.device_id)
            .join(Device, Device.id == Alert.device_id_ref)
            .where(Alert.id == alert_id)
        )
    ).first()
    if row is None:
        raise ApiError("ALERT_NOT_FOUND", f"Alert {alert_id} not found.", 404)
    alert, lora_id = row

    if alert.status == AlertStatus.CLOSED:
        raise ApiError(
            "ALERT_ALREADY_CLOSED",
            "Acknowledgement applies to open alerts only.",
            409,
        )

    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_at = datetime.now(UTC)
    alert.acknowledged_by = actor.id
    await session.commit()
    await manager.broadcast("alert_ack", _alert_out(alert, lora_id).model_dump(mode="json"))
    return _alert_out(alert, lora_id)

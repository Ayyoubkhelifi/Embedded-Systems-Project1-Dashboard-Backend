"""Threshold alert evaluation with hysteresis, sustained windows and dedup.

Design notes
------------
* Condition-is-true requires the *whole* sustained window to exceed the
  threshold — this is the "sustained readings" anti-flap mechanism.
* Alert-clear requires the whole sustained window to fall below
  `threshold - hysteresis` — hysteresis anti-flap on the way down.
* An alert is never duplicated while one is open (or acknowledged) for the
  same (device, rule_key): open alerts block re-raise; acknowledged alerts
  are closed-and-reopened only after the condition actually clears.
* MQ-2 alerts are explicitly labelled preliminary indications; MQ-2 readings
  are raw ADC counts, never calibrated ppm (see docs/hardware.md).
"""
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.base import utcnow
from app.models import Alert, AlertRule, AlertStatus, AlertSeverity, SensorReading

logger = get_logger("app.alerts")

# metric extractors: reading -> comparable float|None (None = invalid/not fitted)
METRIC_FIELD: dict[str, str] = {
    "temp_high": "temperature_c",
    "humidity_high": "humidity_pct",
    "mq2_threshold": "mq2_raw",
}
RULE_SENSORS: dict[str, str] = {
    "temp_high": "temperature",
    "humidity_high": "humidity",
    "mq2_threshold": "mq2",
}
VALIDITY_FIELD: dict[str, str] = {
    "temperature": "temp_valid",
    "humidity": "hum_valid",
    "mq2": "mq2_valid",
    "water": "water_valid",
    "battery": "battery_valid",
}
SENSOR_RULE_TEXT = {
    "temperature": "temperature (DHT11)",
    "humidity": "humidity (DHT11)",
    "mq2": "gas/smoke (MQ-2)",
    "water": "water sensor",
    "battery": "battery monitor",
}


class EvaluatedAlert:
    __slots__ = ("created", "closed")

    def __init__(self, created: list[Alert], closed: list[Alert]) -> None:
        self.created = created
        self.closed = closed


def _metric_value(rule_key: str, rw: Any) -> float | None:
    if rule_key == "water_detected":
        return 1.0 if (rw.water_valid and rw.water_detected) else 0.0
    if rule_key == "sensor_malfunction":
        return None  # handled by dedicated checker
    field = METRIC_FIELD.get(rule_key)
    if field is None:
        return None
    # Validity must hold for the metric to be trusted.
    sensor = RULE_SENSORS[rule_key]
    if not getattr(rw, VALIDITY_FIELD[sensor], False):
        return None
    return float(getattr(rw, field) or 0.0)


async def _recent_readings(session: AsyncSession, device_id_ref: int, limit: int) -> list[Any]:
    result = await session.execute(
        select(SensorReading)
        .where(SensorReading.device_id_ref == device_id_ref)
        .order_by(SensorReading.gateway_time.desc(), SensorReading.id.desc())
        .limit(limit)
    )
    # Return oldest-first so the latest value is the last element.
    return list(reversed(result.scalars().all()))


async def _existing_active_alert(
    session: AsyncSession, device_id_ref: int, rule_key: str
) -> Alert | None:
    result = await session.execute(
        select(Alert)
        .where(
            Alert.device_id_ref == device_id_ref,
            Alert.rule_key == rule_key,
            Alert.status.in_((AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)),
        )
        .order_by(Alert.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _window_true(values: list[float | None], threshold: float, sustained: int) -> bool:
    """Whole sustained window must exceed `threshold`; window must be complete."""
    if len(values) < sustained:
        return False
    return all(v is not None and v > threshold for v in values[-sustained:])


async def evaluate_reading(session: AsyncSession, device_id_ref: int, reading: Any) -> EvaluatedAlert:
    """Run every enabled rule against the newly-ingested reading.

    The `reading` must already be persisted (or at least have complete values)
    so the sustained-window query includes it as the newest row.
    """
    created: list[Alert] = []
    closed: list[Alert] = []

    result = await session.execute(select(AlertRule).where(AlertRule.enabled.is_(True)))
    rules = result.scalars().all()
    rule_map = {r.rule_key: r for r in rules}

    for rule_key in ("temp_high", "humidity_high", "mq2_threshold", "water_detected"):
        rule = rule_map.get(rule_key)
        if rule is None:
            continue
        window = await _recent_readings(session, device_id_ref, max(rule.sustained, 1))
        values = [_metric_value(rule_key, w) for w in window]
        condition_true = _window_true(values, rule.threshold, rule.sustained)
        current = values[-1] if values else None

        active = await _existing_active_alert(session, device_id_ref, rule_key)

        if active is None:
            if not condition_true:
                continue
            alert = Alert(
                device_id_ref=device_id_ref,
                rule_key=rule_key,
                severity=rule.severity,
                status=AlertStatus.OPEN,
                description=_describe_trigger(rule_key, rule.threshold, current),
            )
            session.add(alert)
            await session.flush()
            created.append(alert)
        else:
            # Auto-close path: whole window must be *below* threshold-hysteresis.
            cleared = _window_cleared(values, rule)
            if cleared:
                await _close_single(session, active)
                closed.append(active)

    sensor_created, sensor_closed = await _check_sensor_malfunction(
        session, device_id_ref, rule_map.get("sensor_malfunction")
    )
    created.extend(sensor_created)
    closed.extend(sensor_closed)

    return EvaluatedAlert(created, closed)


def _window_cleared(values: list[float | None], rule: AlertRule) -> bool:
    """Whole sustained window must be at/below threshold minus hysteresis."""
    threshold_clear = rule.threshold - rule.hysteresis
    if len(values) < rule.sustained:
        return False
    return all(v is not None and v <= threshold_clear for v in values[-rule.sustained:])


def _describe_trigger(rule_key: str, threshold: float, current: float | None) -> str:
    if rule_key == "temp_high":
        return (
            f"Temperature {current:.1f}\u00b0C sustained above {threshold:.1f}\u00b0C."
        )
    if rule_key == "humidity_high":
        return f"Relative humidity {current:.1f}% sustained above {threshold:.0f}%."
    if rule_key == "mq2_threshold":
        return (
            f"Gas/smoke indication: MQ-2 raw reading {current:.0f} sustained above "
            f"threshold {threshold:.0f} (preliminary indication — not a calibrated "
            "measurement, not a certified safety alarm)."
        )
    if rule_key == "water_detected":
        return "Water presence detected by the water sensor (sustained)."
    return f"Alert rule '{rule_key}' triggered."


async def _check_sensor_malfunction(
    session: AsyncSession, device_id_ref: int, rule: AlertRule | None
) -> tuple[list[Alert], list[Alert]]:
    created: list[Alert] = []
    closed: list[Alert] = []
    if rule is None:
        return created, closed

    window = await _recent_readings(session, device_id_ref, max(rule.sustained, 1))
    if len(window) < rule.sustained:
        return created, closed

    active = await _existing_active_alert(session, device_id_ref, "sensor_malfunction")
    monitored = ("temperature", "humidity", "mq2", "water")
    broken: list[str] = []
    for sensor in monitored:
        validity_field = VALIDITY_FIELD[sensor]
        if window and all(not getattr(w, validity_field, False) for w in window):
            broken.append(sensor)

    if broken and active is None:
        alert = Alert(
            device_id_ref=device_id_ref,
            rule_key="sensor_malfunction",
            severity=rule.severity,
            status=AlertStatus.OPEN,
            description=_describe_sensor_malfunction(broken, rule.sustained),
        )
        session.add(alert)
        await session.flush()
        created.append(alert)
    elif not broken and active is not None:
        await _close_single(session, active)
        closed.append(active)

    return created, closed


def _describe_sensor_malfunction(broken_sensors: list[str], sustained: int) -> str:
    names = ", ".join(SENSOR_RULE_TEXT.get(s, s) for s in broken_sensors)
    return f"Sensor malfunction: no valid data from {names} in the last {sustained} readings."


async def _close_single(session: AsyncSession, alert: Alert) -> None:
    alert.status = AlertStatus.CLOSED
    alert.closed_at = utcnow()
    await session.flush()


async def mark_offline(session: AsyncSession, device_id_ref: int) -> Alert | None:
    """Raise a device_offline alert unless one is already active."""
    rule = (
        await session.execute(select(AlertRule).where(AlertRule.rule_key == "device_offline"))
    ).scalar_one_or_none()
    if rule is None or not rule.enabled:
        return None
    active = await _existing_active_alert(session, device_id_ref, "device_offline")
    if active is not None:
        return None
    alert = Alert(
        device_id_ref=device_id_ref,
        rule_key="device_offline",
        severity=rule.severity,
        status=AlertStatus.OPEN,
        description=(
            "Device has not reported telemetry within the freshness timeout — "
            "marked offline."
        ),
    )
    session.add(alert)
    await session.flush()
    logger.info("device_offline raised", extra={"device_id_ref": device_id_ref})
    return alert


async def resolve_offline(session: AsyncSession, device_id_ref: int) -> Alert | None:
    result = await session.execute(
        select(Alert).where(
            Alert.device_id_ref == device_id_ref,
            Alert.rule_key == "device_offline",
            Alert.status.in_((AlertStatus.OPEN, AlertStatus.ACKNOWLEDGED)),
        )
    )
    alerts = list(result.scalars())
    if not alerts:
        return None
    for alert in alerts:
        alert.status = AlertStatus.CLOSED
        alert.closed_at = utcnow()
    await session.flush()
    return alerts[0]


__all__ = [
    "EvaluatedAlert",
    "evaluate_reading",
    "mark_offline",
    "resolve_offline",
    "AlertSeverity",
]

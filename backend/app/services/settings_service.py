from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ApiError
from app.models import AlertRule, Setting
from app.schemas.alert import AlertRuleUpdate, FreshnessUpdate

FRESHNESS_KEY = "device_freshness"

DEFAULT_RULES: list[AlertRule] = []


def default_rule_rows() -> list[AlertRule]:
    s = get_settings()
    return [
        AlertRule(rule_key="temp_high", threshold=s.alert_temp_high_c, hysteresis=s.alert_temp_high_hysteresis_c, sustained=s.alert_sustained_readings, severity="critical", enabled=True),
        AlertRule(rule_key="humidity_high", threshold=s.alert_humidity_high_pct, hysteresis=s.alert_humidity_high_hysteresis_pct, sustained=s.alert_sustained_readings, severity="info", enabled=True),
        AlertRule(rule_key="mq2_threshold", threshold=float(s.alert_mq2_threshold), hysteresis=float(s.alert_mq2_hysteresis), sustained=s.alert_sustained_readings, severity="critical", enabled=True),
        AlertRule(rule_key="water_detected", threshold=0.0, hysteresis=0.0, sustained=s.alert_sustained_readings, severity="warning", enabled=True),
        AlertRule(rule_key="sensor_malfunction", threshold=0.0, hysteresis=0.0, sustained=s.alert_sustained_readings, severity="warning", enabled=True),
        AlertRule(rule_key="device_offline", threshold=0.0, hysteresis=0.0, sustained=1, severity="warning", enabled=True),
    ]


async def seed_defaults(session: AsyncSession) -> None:
    """Insert defaults missing from the DB (idempotent — safe on every boot/seed)."""
    session.add_all(default_rule_rows())
    session.add(
        Setting(
            key=FRESHNESS_KEY,
            value={"device_freshness_timeout_seconds": get_settings().device_freshness_timeout_seconds},
        )
    )
    await session.commit()


async def list_rules(session: AsyncSession) -> list[AlertRule]:
    result = await session.execute(select(AlertRule).order_by(AlertRule.rule_key))
    return list(result.scalars())


async def update_rule(session: AsyncSession, rule_key: str, patch: AlertRuleUpdate) -> AlertRule:
    result = await session.execute(select(AlertRule).where(AlertRule.rule_key == rule_key))
    rule = result.scalar_one_or_none()
    if rule is None:
        raise ApiError("RULE_NOT_FOUND", f"Unknown alert rule '{rule_key}'.", 404)
    data = patch.model_dump(exclude_none=True)
    if "severity" in data and data["severity"] not in ("info", "warning", "critical"):
        raise ApiError("VALIDATION_ERROR", "Invalid severity value.", 422)
    for field, value in data.items():
        setattr(rule, field, value)
    await session.commit()
    await session.refresh(rule)
    return rule


async def get_freshness_timeout(session: AsyncSession) -> int:
    result = await session.execute(select(Setting).where(Setting.key == FRESHNESS_KEY))
    setting = result.scalar_one_or_none()
    fallback = get_settings().device_freshness_timeout_seconds
    if setting is None:
        return fallback
    return int(setting.value.get("device_freshness_timeout_seconds", fallback))


async def update_freshness_timeout(session: AsyncSession, patch: FreshnessUpdate) -> int:
    current = await get_freshness_timeout(session)
    value = patch.device_freshness_timeout_seconds
    if value is None:
        return current
    result = await session.execute(
        update(Setting).where(Setting.key == FRESHNESS_KEY).values(
            value={"device_freshness_timeout_seconds": value}
        )
    )
    if result.rowcount == 0:
        session.add(
            Setting(
                key=FRESHNESS_KEY,
                value={"device_freshness_timeout_seconds": value},
                updated_at=datetime.now(UTC),
            )
        )
    await session.commit()
    return value

from fastapi import APIRouter, Depends

from app.api.deps import AdminUser, DbSession
from app.schemas.alert import AlertRuleOut, FreshnessUpdate, SettingsIn, SettingsOut
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


def _rule_out(rule) -> AlertRuleOut:
    return AlertRuleOut(
        rule_key=rule.rule_key,
        threshold=rule.threshold,
        hysteresis=rule.hysteresis,
        sustained=rule.sustained,
        severity=rule.severity,
        enabled=rule.enabled,
    )


@router.get("", response_model=SettingsOut)
async def get_settings(_: AdminUser, session: DbSession) -> SettingsOut:
    rules = await settings_service.list_rules(session)
    freshness = await settings_service.get_freshness_timeout(session)
    return SettingsOut(
        alert_rules=[_rule_out(r) for r in rules],
        device_freshness_timeout_seconds=freshness,
    )


@router.patch("", response_model=SettingsOut)
async def patch_settings(payload: SettingsIn, _: AdminUser, session: DbSession) -> SettingsOut:
    rule_patch = payload.model_dump(exclude_none=True, exclude={"rule_key", "device_freshness_timeout_seconds"})
    if payload.rule_key and rule_patch:
        from app.schemas.alert import AlertRuleUpdate

        await settings_service.update_rule(session, payload.rule_key, AlertRuleUpdate(**rule_patch))
    if payload.device_freshness_timeout_seconds is not None:
        await settings_service.update_freshness_timeout(
            session, FreshnessUpdate(device_freshness_timeout_seconds=payload.device_freshness_timeout_seconds)
        )
    return await get_settings(_, session)

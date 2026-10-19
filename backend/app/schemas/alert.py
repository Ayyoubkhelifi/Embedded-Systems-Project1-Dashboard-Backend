from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    rule_key: str
    severity: str
    description: str
    status: str
    created_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: int | None = None
    closed_at: datetime | None = None


class AlertList(BaseModel):
    items: list[AlertOut]
    total: int


class AlertAckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(pattern="^(acknowledged)$")


class AlertRuleOut(BaseModel):
    rule_key: str
    threshold: float
    hysteresis: float
    sustained: int
    severity: str
    enabled: bool


class AlertRuleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    threshold: float | None = None
    hysteresis: float | None = Field(default=None, ge=0)
    sustained: int | None = Field(default=None, ge=1, le=100)
    severity: str | None = Field(default=None, pattern="^(info|warning|critical)$")
    enabled: bool | None = None


class FreshnessUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_freshness_timeout_seconds: int | None = Field(default=None, ge=60, le=86400)


class SettingsOut(BaseModel):
    alert_rules: list[AlertRuleOut]
    device_freshness_timeout_seconds: int


class SettingsIn(AlertRuleUpdate):
    """PATCH settings: optionally patch one rule inline, or freshness only.

    rule_key must be supplied when any rule field is non-null.
    """

    model_config = ConfigDict(extra="forbid")

    rule_key: str | None = None

    @model_validator(mode="after")
    def _check(self) -> "SettingsIn":
        self.rule_key = self.rule_key or None
        rule_fields = ("threshold", "hysteresis", "sustained", "severity", "enabled")
        payload = self.model_dump(exclude_none=True)
        if any(k in rule_fields for k in payload) and not self.rule_key:
            raise ValueError("rule_key is required when patching an alert rule")
        return self

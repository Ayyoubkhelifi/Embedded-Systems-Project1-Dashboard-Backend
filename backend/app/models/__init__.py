"""Model registry — import all models so Base.metadata sees every table."""
from app.models.alert import Alert, AlertRule, AlertSeverity, AlertStatus, Setting
from app.models.device import Device, Gateway, SensorReading
from app.models.user import User, UserRole

__all__ = [
    "Alert",
    "AlertRule",
    "AlertSeverity",
    "AlertStatus",
    "Setting",
    "Device",
    "Gateway",
    "SensorReading",
    "User",
    "UserRole",
]

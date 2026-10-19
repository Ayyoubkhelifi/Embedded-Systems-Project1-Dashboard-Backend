from datetime import datetime

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, intpk, json_column, utcnow


class AlertSeverity:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"

    @classmethod
    def values(cls) -> list[str]:
        return [cls.INFO, cls.WARNING, cls.CRITICAL]


class AlertStatus:
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    CLOSED = "closed"

    @classmethod
    def values(cls) -> list[str]:
        return [cls.OPEN, cls.ACKNOWLEDGED, cls.CLOSED]


class Alert(Base):
    """Raised condition for a device. History preserved via closed alerts."""

    __tablename__ = "alerts"

    __table_args__ = (
        Index("ix_alerts_device_status", "device_id_ref", "status"),
        Index("ix_alerts_created_at", "created_at"),
        Index("ix_alerts_rule_status", "rule_key", "status"),
    )

    id: Mapped[intpk]

    device_id_ref: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=AlertSeverity.WARNING)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=AlertStatus.OPEN, index=True)

    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    acknowledged_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    device = relationship("Device")
    ack_user = relationship("User")


class AlertRule(Base):
    """Configurable threshold rule with hysteresis + sustained-reading windows."""

    __tablename__ = "alert_rules"

    rule_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    hysteresis: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    sustained: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default=AlertSeverity.WARNING)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Setting(Base):
    """Typed key/value store for dashboard-level settings (freshness timeout etc.)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(json_column(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

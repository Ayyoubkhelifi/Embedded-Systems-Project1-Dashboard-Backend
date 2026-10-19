from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UTCDateTime, intpk, utcnow


class Gateway(Base):
    """Registered LoRa gateway with an ingest credential (hashed API key)."""

    __tablename__ = "gateways"

    id: Mapped[intpk]
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    gateway_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key_fingerprint: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[intpk]
    device_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    device_type: Mapped[str] = mapped_column(String(64), nullable=False, default="esp32_env_node")
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    last_rssi: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_snr: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="offline", index=True)

    readings: Mapped[list["SensorReading"]] = relationship(
        back_populates="device",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="SensorReading.gateway_time.desc()",
    )


class SensorReading(Base):
    """One ingested telemetry packet (idempotent via unique (device_id, packet_seq))."""

    __tablename__ = "sensor_readings"

    __table_args__ = (
        UniqueConstraint("device_id_ref", "packet_seq", name="uq_readings_device_seq"),
        Index("ix_readings_device_time", "device_id_ref", "gateway_time"),
        Index("ix_readings_gateway_time", "gateway_time"),
    )

    id: Mapped[intpk]
    device_id_ref: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    packet_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Values; None when the corresponding sensor validity flag was false.
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    mq2_raw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    water_raw: Mapped[int | None] = mapped_column(Integer, nullable=True)
    battery_mv: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Validity reported by the node.
    temp_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    hum_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mq2_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    water_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    battery_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Derived states (server-side evaluation).
    gas_alarm: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    water_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Radio link quality, assigned by the gateway at reception.
    rssi: Mapped[float | None] = mapped_column(Float, nullable=True)
    snr: Mapped[float | None] = mapped_column(Float, nullable=True)
    gateway_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    gateway_time: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, nullable=False, index=True
    )
    device_time: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    device: Mapped[Device] = relationship(back_populates="readings")

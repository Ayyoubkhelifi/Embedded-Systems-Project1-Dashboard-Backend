from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.telemetry import TelemetryOut


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: int = Field(ge=1, le=4294967295)
    name: str = Field(min_length=1, max_length=128)
    device_type: str = Field(default="esp32_env_node", max_length=64)
    location: str | None = Field(default=None, max_length=255)


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    device_type: str | None = Field(default=None, max_length=64)
    location: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None


class DeviceOut(BaseModel):
    """Inventory row: device identity + liveness + snapshot of latest reading."""

    model_config = ConfigDict(from_attributes=True)

    device_id: int
    name: str
    device_type: str
    location: str | None
    registered_at: datetime
    last_seen_at: datetime | None = None
    last_seq: int | None = None
    last_rssi: float | None = None
    last_snr: float | None = None
    status: str
    is_active: bool


class DeviceDetail(DeviceOut):
    latest_reading: TelemetryOut | None = None


class DeviceList(BaseModel):
    items: list[DeviceOut]
    total: int


class DeviceDetailList(BaseModel):
    items: list[DeviceDetail]
    total: int

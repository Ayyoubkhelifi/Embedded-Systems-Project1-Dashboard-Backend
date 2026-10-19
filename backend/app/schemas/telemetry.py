from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

DEVICE_ID_MAX = 4294967295  # uint32
SEQ_MAX = 4294967295  # uint32


class TelemetryFlags(BaseModel):
    """Sensor validity + message semantics flags, exactly as broadcast on LoRa."""

    model_config = ConfigDict(extra="forbid")

    temp: bool = False
    hum: bool = False
    mq2: bool = False
    water: bool = False
    water_detected: bool = False
    battery: bool = False
    ack_requested: bool = False
    simulated: bool = False


class TelemetryIn(BaseModel):
    """Validated gateway → backend payload for POST /api/v1/telemetry."""

    model_config = ConfigDict(extra="forbid")

    device_id: int = Field(ge=1, le=DEVICE_ID_MAX)
    seq: int = Field(ge=0, le=SEQ_MAX)

    flags: TelemetryFlags = TelemetryFlags()

    # Sensor values; None where the matching flag is False. Bounded to plausible
    # sensor physics: guard against corrupted-but-HMAC-valid radio payloads.
    temperature_c: float | None = Field(default=None, ge=-60, le=95)
    humidity_pct: float | None = Field(default=None, ge=0, le=100)
    mq2_raw: int | None = Field(default=None, ge=0, le=4095)
    water_raw: int | None = Field(default=None, ge=0, le=4095)
    battery_mv: int | None = Field(default=None, ge=0, le=65535)

    # Radio link metadata, captured by the gateway.
    rssi: float | None = Field(default=None, ge=-200, le=20)
    snr: float | None = Field(default=None, ge=-50, le=50)
    gateway_id: str = Field(default="", max_length=64)

    # Authoritative reception time (UTC) — falls back to server clock if absent.
    gateway_time: datetime | None = None

    @field_validator("gateway_id", mode="before")
    @classmethod
    def _strip_gateway_id(cls, v: object) -> object:
        return v.strip() if isinstance(v, str) else v


class TelemetryOut(BaseModel):
    """Reading as returned by history/latest endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    device_id: int
    packet_seq: int
    temperature_c: float | None = None
    humidity_pct: float | None = None
    mq2_raw: int | None = None
    water_raw: int | None = None
    battery_mv: int | None = None
    temp_valid: bool
    hum_valid: bool
    mq2_valid: bool
    water_valid: bool
    battery_valid: bool
    gas_alarm: bool
    water_detected: bool
    simulated: bool
    rssi: float | None = None
    snr: float | None = None
    gateway_id: str | None = None
    gateway_time: datetime
    device_time: datetime | None = None


class IngestResult(BaseModel):
    """Response for POST /telemetry — explicit about idempotent duplicates."""

    stored: bool
    duplicate: bool
    reading_id: int | None = None
    alerts_created: list[int] = Field(default_factory=list)
    alerts_closed: list[int] = Field(default_factory=list)

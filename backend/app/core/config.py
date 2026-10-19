from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    app_name: str = "ESS Telemetry API"
    version: str = "1.0.0"
    env: str = Field(default="development", pattern="^(development|testing|production)$")
    log_level: str = "INFO"

    # Security
    secret_jwt_key: str = "change-me-to-a-long-random-secret"
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    session_cookie_name: str = "ess_session"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"

    # Database
    database_url: str = "sqlite+aiosqlite:///./ess.db"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]

    # Limits
    rate_limit_general_per_minute: int = 120
    rate_limit_ingest_per_minute: int = 600
    rate_limit_ws_max_connections: int = 50
    max_request_body_bytes: int = 65536
    max_history_range_days: int = 90
    default_page_limit: int = 50
    max_page_limit: int = 500

    # Devices / alerts
    device_freshness_timeout_seconds: int = 900
    offline_check_interval_seconds: int = 60
    data_retention_days: int = 90
    alert_temp_high_c: float = 35.0
    alert_temp_high_hysteresis_c: float = 2.0
    alert_humidity_high_pct: float = 85.0
    alert_humidity_high_hysteresis_pct: float = 5.0
    alert_mq2_threshold: int = 800
    alert_mq2_hysteresis: int = 100
    alert_water_threshold: int = 0  # 0 => rely on the device's boolean water state
    alert_sustained_readings: int = 2

    # Seed bootstrap (first admin + gateway credential; dev seed script)
    admin_username: str = "admin@ess.local"
    admin_password: str = "change-me-strong-password"
    gateway_api_key: str = "change-me-gateway-key"
    gateway_id: str = "gw-1"

    # Demo features
    simulate_ingest_disabled_in_production: bool = True

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_testing(self) -> bool:
        return self.env == "testing"


@lru_cache
def get_settings() -> Settings:
    return Settings()

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    backend_url: str = Field(default="http://127.0.0.1:8000", description="Backend base URL; use https:// in remote deployments")
    gateway_api_key: str = "change-me-gateway-key"
    gateway_id: str = "gw-1"
    gateway_device_id: int = 1

    # Simulated node fleet (development mode with no physical hardware)
    simulate: bool = False
    simulate_device_ids: str = "101,102"
    simulate_interval_seconds: float = 5.0
    simulate_fault_rate: float = 0.05  # fraction of readings with a dead sensor
    simulate_water_rate: float = 0.1

    # Radio (SX127x via SPI); frequency must obey local regulations
    lora_frequency_mhz: float = 868.10
    lora_spreading_factor: int = 7
    lora_bandwidth_khz: int = 125
    lora_coding_rate: int = 5
    lora_tx_power_dbm: int = 14
    lora_spi_bus: int = 0
    lora_spi_cs: int = 0
    lora_dio0_gpio: int = 17
    lora_rst_gpio: int = 22

    # Node HMAC keys: "device_id:hexkey,device_id:hexkey"
    node_keys: str = "101:3f2a...deadbeef,102:9c1b...cafebabe"

    # Buffering / forwarding
    buffer_db_path: str = "~/.ess-gateway/buffer.sqlite3"
    poll_interval_seconds: float = 0.5
    flush_interval_seconds: float = 5.0
    retry_max: int = 6
    retry_backoff_base: float = 1.5
    retry_backoff_max: float = 60.0
    tls_verify: bool = True
    backend_timeout_seconds: float = 10.0

    # Health
    health_port: int = 8080

    @property
    def node_key_map(self) -> dict[int, bytes]:
        out: dict[int, bytes] = {}
        for chunk in self.node_keys.split(","):
            chunk = chunk.strip()
            if not chunk or ":" not in chunk:
                continue
            dev, hexkey = chunk.split(":", 1)
            try:
                out[int(dev)] = bytes.fromhex(hexkey)
            except ValueError:
                continue
        return out


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()

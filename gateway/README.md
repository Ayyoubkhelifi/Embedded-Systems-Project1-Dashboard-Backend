# ESS Gateway (Raspberry Pi)

Receives LoRa packets from ESP32 sensor nodes via an SX1276/SX1278 radio,
validates them (CRC-16 + per-device HMAC-SHA256), dedups by sequence number,
buffers them durably in SQLite, and forwards them to the backend over HTTPS
with retries and exponential backoff.

## Modes

| Mode        | Flag        | Use                                                       |
|-------------|-------------|-----------------------------------------------------------|
| Hardware RX | (default)   | SX127x over SPI on the Raspberry Pi                       |
| Simulator   | `--simulate`| Faux node fleet, no hardware — dev laptops, CI            |

Simulated packets carry the SIMULATED flag (bit 7) and the backend rejects
them in production deployments.

## Configuration (environment or gateway/.env)

| Variable                   | Default                          | Notes                                  |
|----------------------------|----------------------------------|----------------------------------------|
| `BACKEND_URL`              | `http://127.0.0.1:8000`          | Use `https://` remotely                |
| `GATEWAY_API_KEY`          | `change-me-gateway-key`          | Must match backend `GATEWAY_API_KEY`   |
| `GATEWAY_ID`               | `gw-1`                           | Free-form gateway identifier           |
| `NODE_KEYS`                | `101:hexkey,102:hexkey`          | Per-node HMAC keys (32 bytes each)     |
| `GATEWAY_BUFFER_DB`        | `~/.ess-gateway/buffer.sqlite3`  | Durable dedup + send buffer            |
| `SIMULATE`                 | `false`                          | Set true or use `--simulate`           |
| `SIMULATE_DEVICE_IDS`      | `101,102`                        |                                        |
| `SIMULATE_INTERVAL_SECONDS`| `5.0`                            |                                        |
| `LORA_FREQUENCY_MHZ`       | `868.10`                         | Must obey local ISM regulations        |
| `LORA_SPREADING_FACTOR`    | `7`                              |                                        |
| `LORA_BANDWIDTH_KHZ`       | `125`                            |                                        |
| `TLS_VERIFY`               | `true`                           | Disable only for self-signed dev certs |
| `RETRY_MAX`                | `6`                              | Per-packet delivery attempts           |

## Quick start (simulator)

```bash
cd gateway
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m gateway_pkg.main --simulate --check   # connectivity self-test
.venv/bin/python -m gateway_pkg.main --simulate           # run
```

The `--check` command verifies node key parsing and backend reachability, then
exits 0/1 — useful under systemd (`ExecStartPre`).

## Raspberry Pi hardware setup

1. **Enable SPI**: `sudo raspi-config` → Interface Options → SPI → enable.
2. **Wire the SX127x module** (see `docs/hardware.md` for the full pin map):

   | SX127x pin | Raspberry Pi (BCM) |
   |------------|--------------------|
   | VCC 3.3V   | 3V3 (never 5V!)    |
   | GND        | GND                |
   | MOSI       | GPIO 10 (SPI0 MOSI)|
   | MISO       | GPIO 9  (SPI0 MISO)|
   | SCK        | GPIO 11 (SPI0 SCLK)|
   | NSS/CS     | GPIO 8  (CE0)      |
   | DIO0       | GPIO 17            |
   | RST        | GPIO 22            |

3. **Install hardware deps**: `pip install -r requirements-lora.txt`
   (spidev + RPi.GPIO build only on Raspberry Pi OS).
4. **Match frequencies**: the ESP32 firmware (`firmware/esp32`) and the
   gateway must agree on frequency/SF/BW/CR, and each node's HMAC key must
   be provisioned in `NODE_KEYS` on the gateway and flashed into the node.

## Run as a service (systemd)

```ini
[Unit]
Description=ESS LoRa gateway
After=network-online.target

[Service]
User=ess
WorkingDirectory=/opt/ess/gateway
EnvironmentFile=/opt/ess/gateway/.env
ExecStart=/opt/ess/gateway/.venv/bin/python -m gateway_pkg.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Behavior notes

- **Dedup**: strictly-increasing seq per device with 32-bit wrap handling,
  persisted in SQLite so restarts don't re-forward old packets.
- **Buffer**: rows are removed only after the backend returns 2xx. Network
  outages retain and re-send in order; definitive 4xx rejections are dropped.
- **Backoff**: exponential (base 1.5 s, capped at 60 s) with jitter, so a
  fleet of gateways doesn't hammer a recovering backend in sync.

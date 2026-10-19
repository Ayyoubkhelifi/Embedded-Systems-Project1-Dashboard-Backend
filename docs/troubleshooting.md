# Troubleshooting

## Node / radio

| Symptom | Diagnosis |
|---------|-----------|
| node logs "SX127x init failed" | wiring (NSS/DIO/RST), `SPI.begin` pins, wrong radio model constant (SX1276 vs SX1278). Check VCC = 3.3 V. |
| `status=NoAck` constantly | gateway offline, frequency/SF/BW mismatch, wrong key? (NoAck on garbage CRC is expected), antenna unplugged |
| readings invalid on some sensors (`temp_valid=false`) | DHT11 not connected/failed; backend raises `sensor_malfunction` after 2 h streak |
| MQ-2 value stuck near 0 or 4095 | warm-up (first 30 s ignored — correct), missing 5 V heater, ADC attenuation |
| water flag never on | analog probe dry-threshold too low (`water_read_analog` < 2500 reference) or float switch pin wrong |
| battery `—` in dashboard | divider missing (no resistor chain), GP pin wrong, or value < 2500 mV guard |

## Gateway

| Symptom | Diagnosis |
|---------|-----------|
| `--check` exits 1 saying backend unreachable | backend not running, `BACKEND_URL` wrong, CORS irrelevant here (server-to-server), TLS cert problem (`TLS_VERIFY` only for self-signed dev CA) |
| "no node key configured for device N" | `NODE_KEYS` missing that id, or the hex is bad |
| packets rejected (`crc`/`hmac`) | node key mismatch with gateway `NODE_KEYS`, RF noise (3% simulator corruption is normal in `--simulate`), wrong-antenna CRC |
| "duplicate dropped" flood | your gateway replayed the same packets (SG normal after buffer restore; is_new/ring-dedup catches) |
| buffer keeps growing | backend down; flush stops on first failure and drags ordered queue. Verify backend `POST /api/v1/telemetry` works manually w/ gateway key curl emulation |
| sqlite "database is locked" | another process holding it? only one gateway process per DB path |
| Radio RX silent | SPI/GPIO pins per docs/hardware.md (Pi: SPI0 DIO0=17 RST=22), `spidev` not enabled (`raspi-config`) |

## Backend

| Symptom | Diagnosis |
|---------|-----------|
| startup fails: `SECRET_JWT_KEY` error | env file not loaded (systemd EnvironmentFile, compose env_file) |
| login returns `RATE_LIMITED` | 10 logins/min per IP; wait or relax `RATE_LIMIT_LOGIN_PER_MINUTE` for load tests |
| `PAYLOAD_TOO_LARGE` | body > 64 KiB — real bug in the gateway (all telemetry ≤ 1 KiB), check something proxies literal bodies |
| DEVICE_NOT_REGISTERED at ingest | register device in dashboard first (`/devices`, operator+) |
| readings recorded but no WS events | dashboard token expired (15 min TTL) → the Live page shows "Session expired" and reconnect after relogin |
| `TIME_RANGE_TOO_LARGE` | history query beyond 90 days — use `MAX_HISTORY_RANGE_DAYS` env to widen deliberately |
| Alembic stuck / version table bad state | inspect `alembic_version`; hand-fix to `"0001"` after a restore-from-snapshot mismatch |

## Dashboard

| Symptom | Diagnosis |
|---------|-----------|
| Live shows "Session expired" instantly | token absent/expired — sign in again; WS is per-session by design (no persistent token storage) |
| charts empty but overview shows data | 24 h-history window filtered to your device; widen the range tab |
| "Cannot reach the ESS backend" | `NEXT_PUBLIC_API_BASE_URL` unreachable from the browser (VPN/DNS/port) — check <url>/api/v1/health directly |
| settings PATCH 403 | must be admin; operator edit is not allowed |
| device stock shows `invalid` values | packet flag off (`temp_valid=false`) — conveyed deliberately rather than erroring the UI |

## Packet debugging tools

```bash
# watch what the gateway sees/decodes (logs)
python -m gateway_pkg.main --simulate --log-level DEBUG

# enc/dec roundtrip standalone
python - <<'PY'
from gateway_pkg.protocol import TelemetryPacket, Flags, encode_packet, decode_packet
p = TelemetryPacket(device_id=101, seq=1, flags=Flags(temp=True), temperature_c=23.4)
f = encode_packet(p, bytes.fromhex("00"*16))
print(f.hex(), decode_packet(f, lambda d: bytes.fromhex("00"*16)))
PY
```

Firmware serial logs (115200 8N1) show `sent seq=… status=…` per try; the
gateway prints `stored/duplicate/rejected:<name>` per received frame.

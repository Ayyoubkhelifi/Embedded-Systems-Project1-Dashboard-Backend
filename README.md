# ESS — Environmental Sensing System

LoRa-telemetered environmental monitoring: ESP32 sensor nodes → Raspberry Pi
LoRa gateway → FastAPI/PostgreSQL backend → Next.js dashboard.

```
ESP32 (DHT11, MQ-2, water, battery)
   │  32-byte signed LoRa frames (crc16 + truncated HMAC-SHA256)
   ▼
Raspberry Pi gateway (sx127x/SPI)
   │  HTTPS POST /api/v1/telemetry (gateway key, retries + durable SQLite buffer)
   ▼
FastAPI backend ── rule engine ── WebSocket fan-out ── REST history/latest
   ▼
Next.js dashboard (login, overview KPIs, live feed, history charts,
                   device inventory, alert ack lifecycle, admin settings)
```

## Quick start with docker compose

```bash
cp .env.example .env            # set SECRET_JWT_KEY, GATEWAY_API_KEY, ADMIN_PASSWORD, CORS_ORIGINS
docker compose up -d --build    # postgres + backend + frontend + gateway(simulator)
open http://localhost:3000      # login with ADMIN_USERNAME/ADMIN_PASSWORD
```

Without Docker, see `docs/deployment.md` (native processes + systemd).

## Repo map

| Path | What lives here |
|------|-----------------|
| `firmware/esp32/` | Arduino node sketch (`ess_node`) + `ess_packet` codec library |
| `gateway/` | Pi gateway (simulator mode works on any machine) + tests |
| `backend/` | FastAPI app, Alembic migrations, pytest suite |
| `frontend/` | Next.js 15 dashboard (App Router, Recharts, WS) |
| `docs/` | architecture, hardware, API, deployment, backups, threat model |
| `.env.example` | every env var (backend/gateway/frontend) with sane defaults |

## What each environment area provides

- **Fleet + sensors per node**: DHT11 (temp/humidity), MQ-2 (gas, RAW counts —
  explicitly not a calibrated ppm reading, "not a certified safety alarm"),
  digital water probe, battery monitor. Sensor validity flags ride in every
  frame; absence/broken → `sensor_malfunction` alert after 2 h.
- **Rules and alerting**: threshold + hysteresis + sustained-window config per
  rule (default: temp 35 °C critical, humidity 85 %, MQ-2 800 raw critical,
  water warning, sensor_malfunction, device_offline). Alerts are deduped per
  (device, rule) and go open → acknowledged → closed with full audit trail.
- **At-least-once delivery**: gateway buffers in SQLite, orders retries with
  jittered backoff, drops only on definitive 4xx; backend dedups any replay
  (`(device_id, packet_seq)` unique) and duplicates surface as 200 responses.
- **Security**: per-node HMAC keys node↔gateway, gateway API key with bcrypt
  at the backend, BCrypt(12) user passwords, samesite httpOnly cookie
  sessions, strict input validation (`extra=forbid`, bounded values), rate
  limits on login/ingest, simulated telemetry rejected in production.
- **Deploy choices**: compose now; native/systemd docs included. No cloud
  dependency in the data path.

## Local development (no hardware)

Any machine can run the whole stack in **simulate mode**:

```bash
# backend
cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.db.seed
.venv/bin/uvicorn app.main:app --reload

# gateway (simulated ESP32 fleet — no radio required)
cd gateway && .venv/bin/python -m gateway_pkg.main --simulate

# frontend
cd frontend && cp .env.local.example .env.local && npm run dev
```

Tests:

```bash
cd backend && .venv/bin/pytest            # 34 backend tests
cd gateway && .venv/bin/python -m pytest  # 33 gateway tests
cd frontend && npm run typecheck && npm run build
```

The dashboard also has a browser-only demo mode (`NEXT_PUBLIC_DEMO_MODE=true`)
with an in-memory simulated fleet — handy for UI work on the road.

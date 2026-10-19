# Architecture

## Topology

```
 ┌─────────────┐   LoRa 433/868            ┌──────────────┐  HTTPS   ┌──────────────┐
 │ ESP32 nodes  │ ──── 32-byte signed ───► │ Raspberry Pi │ ──POST──► │ FastAPI      │
 │ DHT11/MQ2/~  │ ◄──── 12-byte ACK ─────  │ ESS gateway  │  +retry  │ backend      │
 └─────────────┘                           └──────────────┘           └──────┬───────┘
     fire-and-forget                           SQLite buffer               │ SQL (psycopg2)
     ACK + retry on alert                      + dedup seq                  ▼
                                                               ┌──────────────────────┐
                     MQTT? no — LoRa only                       │ PostgreSQL           │
                                                               │ users/devices/       │
  ┌──────────────┐        HTTPS/WSS                             │ readings/alerts/     │
  │ Next.js      │ ◄───────────────────────────────────────────  │ settings/gateways    │
  │ dashboard    │                                              └──────────────────────┘
  └──────────────┘    cookie auth for REST, token query for WS
```

## Monorepo layout

| Path            | Role |
|-----------------|------|
| `firmware/esp32` | Arduino node sketch + `ess_packet` library (encoder/CRC/HMAC) |
| `gateway/`       | Pi receiver: validates (crc16 + per-node HMAC), dedups, buffers, forwards |
| `backend/`       | FastAPI: ingestion, rule engine, REST + WebSocket, Alembic migrations |
| `frontend/`      | Next.js 15 dashboard (REST + WSS) |
| `docs/`          | This pack |

## Ingestion pipeline (end-to-end idempotency)

1. Node builds 32 bytes: header E5 11 → ids/seq/flags/values → CRC-16 → 8-byte truncated HMAC.
2. Gateway validates CRC and HMAC (per-node 16-byte keys in `NODE_KEYS`), checks
   `seq` strictly increases (ring-window wrap-aware dedup) and buffers in SQLite
   **before** any network activity. Rows are removed only after a 2xx response.
3. Backend `POST /api/v1/telemetry` (gateway key header): validates payload
   bounds (pydantic `extra=forbid`), rejects duplicate `(device_id, packet_seq)`
   with 200 duplicate, persists reading, runs the alert rule engine, then
   broadcasts `telemetry/alert/alert_closed/device_status` over WebSocket.

## Alert engine

- Rule table seeded from env: `threshold`, `hysteresis`, `sustained` (window N),
  `severity`, `enabled`.
- Raise when the last N readings all exceed threshold; close when the last N
  are all ≤ threshold − hysteresis (debounce both directions).
- Dedup: one open/acknowledged row per (device, rule_key) → re-raise ignored.
- Special rules: `water_detected` (flag-based), `sensor_malfunction`
  (invalid-flag streak ≥ 2 h), `device_offline` (freshness monitor task).

## Auth model

| Principal      | Credential | Storage |
|----------------|-----------|---------|
| Dashboard user | BCrypt(12) password → JWT (15 min) | `httpOnly` `ess_session` cookie |
| Gateway        | `ess_gw_...` API key | bcrypt hash + sha256 fingerprint in DB |
| Node           | 16-byte HMAC key | env provisioned on gateway; flashed on node |

WS auth: short-lived JWT passed as `?token=` (cookie can't ride a WS upgrade).
Rate limiting: in-memory sliding window on login/ingest + global; payload cap.

## Data model (system-table tier)

`devices` (lora id, name, status, last_seq/seen, rssi) — `sensor_readings`
(1:many, unique (device_id_ref, packet_seq), flag columns per sensor) —
`alerts` (rule_key, severity, ack lifecycle) — `alert_rules` — `settings`
(kv, e.g. freshness seconds) — `gateways` (key hash/fingerprint) — `users`.

## Design decisions

- **MQ-2 stays raw.** No fabricated ppm math — thresholds are honest raw ADC
  counts, descriptions carry a "not a certified safety alarm" caveat.
- **Gateway is the clock.** Nodes have no time source; gateway_time is
  authoritative (+ SNR/RSSI link metadata comes with the packet).
- **Duplicate-tolerant retries.** Uplinks retransmit on lost ACK; every layer
  (gateway ring dedup + backend unique index) coalesces them to one row.
- **No cloud dependency.** Bit → radio → gateway → LAN. The dashboard is the
  only end-user surface; TLS terminates at the reverse proxy.

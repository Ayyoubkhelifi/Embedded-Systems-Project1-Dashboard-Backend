# API Reference

Base URL: `http://<host>:8000/api/v1` (dashboard origin env
`NEXT_PUBLIC_API_BASE_URL`). Dashboard requests use the httpOnly
`ess_session` cookie; gateways use `X-Gateway-Key`.

Error envelope (all non-2xx):
```json
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "details": {} } }
```
Codes: `UNAUTHORIZED TOKEN_EXPIRED FORBIDDEN NOT_FOUND CONFLICT RATE_LIMITED
PAYLOAD_TOO_LARGE BAD_CREDENTIALS ACCOUNT_DISABLED USERNAME_TAKEN
SELF_LOCKOUT_FORBIDDEN DEVICE_NOT_REGISTERED DEVICE_INACTIVE DEVICE_ID_TAKEN
DEVICE_NOT_FOUND ALERT_NOT_FOUND ALERT_ALREADY_CLOSED RULE_NOT_FOUND
INVALID_TIME_RANGE TIME_RANGE_TOO_LARGE INVALID_PAGINATION SIMULATED_TELEMETRY_REJECTED DATABASE_ERROR INTERNAL_ERROR`.

## Health
`GET /health` → `{"ok": true}` (or details when degraded).

## Auth
| Method | Path | Role | Notes |
|--------|------|------|-------|
| POST | `/auth/login` | — | body `{username, password}` → `{access_token, user}`; sets cookie. No TLS? set `COOKIE_SECURE=true` in prod. |
| POST | `/auth/logout` | user | clears cookie |
| GET | `/auth/me` | viewer+ | current user |
| GET | `/auth/users` | admin | list |
| POST | `/auth/users` | admin | create `{username,password,role}` |
| PATCH | `/auth/users/{id}` | admin | partial update; self-lockout guard |
| DELETE | `/auth/users/{id}` | admin | soft-disable |

## Telemetry
| Method | Path | Role | Query/Body |
|---|---|---|---|
| POST | `/telemetry` | **gateway key** | `TelemetryIn`: `{device_id, seq, flags{temp,hum,mq2,water,water_detected,battery,ack_requested,simulated}, temperature_c?, humidity_pct?, mq2_raw?, water_raw?, battery_mv?, rssi?, snr?, gateway_id?, gateway_time?}` — `extra=forbid`. Returns 201 `{stored:true,…}` or 200 `{stored:false, duplicate:true}`. |
| GET | `/telemetry/latest` | viewer+ | `?limit&device_id` newest first |
| GET | `/telemetry/history` | viewer+ | `?device_id&start&end&limit&offset&order` (≤ 90-day window) |

`TelemetryOut` adds validity booleans (`temp_valid …`), `gas_alarm`,
`water_detected`, `simulated`, link metadata (`rssi`, `snr`, gateway ids).

## Devices
| Method | Path | Role |
|---|---|---|
| GET | `/devices` | viewer+ (`items[]` + total) |
| POST | `/devices` | operator+ `{device_id,name,device_type?,location?}` |
| GET | `/devices/{device_id}` | viewer+ (with `latest_reading`) |
| PATCH | `/devices/{device_id}` | operator+ `{name?,device_type?,location?,is_active?}` |
| DELETE | `/devices/{device_id}` | operator+ → marks inactive |

## Alerts
| Method | Path | Role | Notes |
|---|---|---|---|
| GET | `/alerts` | viewer+ | `?status&device_id&rule_key&severity&limit&offset` |
| GET | `/alerts/{id}` | viewer+ | |
| PATCH | `/alerts/{id}` | operator+ | `{status:"acknowledged"}`; closed → 409 `ALERT_ALREADY_CLOSED` |

## Settings (admin)
| Method | Path | Body |
|---|---|---|
| GET | `/settings` | — (`{alert_rules[], device_freshness_timeout_seconds}`) |
| PATCH | `/settings` | freshness only `{device_freshness_timeout_seconds}`; or rule patch `{rule_key, threshold?, hysteresis?, sustained?, severity?, enabled?}` (rule_key required with any rule field) |

## WebSocket
`GET /api/v1/ws/telemetry?token=<access_token>`

Messages **server → client**: `{"type": "hello", ...}` then `telemetry`,
`alert`, `alert_closed`, `device_status`, `heartbeat` events with `{"type", "data"}` shape.
Client → server: literal `ping` text (→ `pong`), close via `close` or TCP close.
Close codes: `4401` bad/expired token, `4429` too many connections.

## Rate limits (defaults)
| Bucket | Policy |
|--------|--------|
| ingest | 300/min per gateway key |
| login | 10/min per IP |
| global | 600/min per IP |
| body | 64 KiB cap |
Exceeding → 429 `RATE_LIMITED` envelope.

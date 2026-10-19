# Threat Model

## Assets

| # | Asset | Why it matters |
|---|-------|----------------|
| 1 | Node HMAC keys | forging = spoofing real sensor events (false/missing alarms) |
| 2 | Gateway API key | lets an attacker POST fake telemetry to the backend |
| 3 | User sessions (JWTs) | dashboard takeover via cookie theft/CSRF |
| 4 | Password hashes | BCrypt(12), offline cracking resistance |
| 5 | Telemetry DB | long-history sensor data + audit trail of acks |

## Trust boundaries

```
[air waves] ⇆ [gateway] ⇆ [backend] ⇆ [dashboard] ⇆ [user]
 att&ck:      local tamper,   LAN mitm,     XSS/CSRF/at guess
 jam / replay / bit-flip     key leakage
```

The most-exposed surface is the **radio**: any listener can hear every packet,
bit-flip, replay, or jam. The rest of the chain is HTTPS inside a LAN.

## Adversaries and defenses

### A1 — Radio replay
*Attack*: record a "gas readings are normal" frame, re-live it during a fire
(and vice versa).
*Defense*: monotonic `seq` per node enforced by the gateway's ring-window dedup
(persisted in SQLite across restarts) + the backend's unique
`(device_id, packet_seq)` index. A replayed frame is a no-op.

### A2 — Bit-flip / message forgery (HMAC-spoof)
*Defense*: payload carries CRC-16 (accidental corruption) **and** an 8-byte
truncated HMAC-SHA256 (deliberate tampering). The key is 16 bytes, shared
node↔gateway only; the backend never sees it. 2^-64 forgery odds per packet
attempt are below any realistic attack budget, and replay alone buys nothing.

### A3 — Radio jamming / denial
*Defense*: node keeps sensing; gateway logs a `device_offline` alert from the
freshness monitor. Note honestly: LoRa is inherently jam-able; the design goal
is detectable silence, not covert retransmission.

### A4 — Gateway compromise (local attacker)
*Defense*: minimal attack surface (no inbound network listener needed unless
health check enabled; systemd hardening recommended in deployment.md). Gateway
leaks at most the node keys it stores in env, rate of blast radius to the
backend is capped by the backend's own device registry (unknown id → reject).

### A5 — Wrong auth / session theft (dashboard)
*Defense*: samesite=lax httpOnly cookies (XSS-proof token theft),
15-minute JWT TTL, BCrypt(12) hashing, constant-time-equal login responses,
account disable flow. The admin can't demote/disable *themselves*
(`SELF_LOCKOUT_FORBIDDEN`), and DELETE users is a soft delete preserving
alert audit chains.

### A6 — CSRF
*Defense*: state-changing requests are JSON-only (`Content-Type
application/json` triggers a preflight cross-origin); cookies had
`samesite=lax` (default for local dev is same-site only).

### A7 — Ingest abuse (backend)
*Defense*: gateway-key bcrypt check on every ingest, sliding-window rate
limits (ingest + login + global), 64 KiB request body cap, and pydantic
`extra=forbid` with strict bound checking — a malformed or junk packet can never
bloat the DB or wedge the rule engine. SIMULATED-flag telemetry is rejected
in production.

### A8 — Stat tampering / webhook confusion
*Defense*: no inbound listeners on nodes; there is nothing to remotely pwn in
the ESP32 itself: it has no wifi and only responds on radio to the single
immutable gateway's ACK (CRC-protected and *gateway-signed? no —* the ACK is
CRC-validated but not MACed: acceptable because an ACK consumed either a
do-nothing outcome (retransmit) or skipped a retry — worst case: one missed
retry. Documented trade-off.)

### A9 — Deployment mistakes
*Defense*: secrets come only from env/.env files (git-ignored); backend refuses
to start without `SECRET_JWT_KEY`; cookies turn `secure` in production env;
SQL is exclusively parameterized by SQLAlchemy; error envelopes never expose
stack traces or schema; log captures are rate-limited and body-capped.

## Out of scope / honest limitations

- LoRa physical jamming can silence nodes (monitored by freshness).
- Option to send security anomalies truly apart from ordinary operation:
  alert descriptions include rule thresholds and are broadcast live to the
  dashboard but are NOT cryptographically signed for post-mortem forensics
  beyond the normal application DB records.
- Gateway SQL buffer on SD card can be corrupted by power loss on old cards
  (mitigated by WAL journal; backups restore the pipeline, see backup doc).

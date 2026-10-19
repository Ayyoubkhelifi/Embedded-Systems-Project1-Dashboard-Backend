# ESS Telemetry Packet Format (`v1`)

Single source of truth for the on-air packet format, implemented independently by:

- ESP32 firmware: `firmware/esp32/lib/ess_packet/`
- Raspberry Pi gateway decoder: `gateway/gateway_pkg/protocol.py`
- Gateway simulator / backend test fixtures

All multi-byte integers are **little-endian**. Time values are never broadcast by
end devices; the gateway assigns a reception timestamp in **UTC** and that value
is authoritative for the backend.

## Data packet — Telemetry uplink (`type=0x01`), 32 bytes

| Off | Len | Field          | Encoding |
|----:|----:|----------------|----------|
| 0   | 1   | magic          | `0xE5` |
| 1   | 1   | version + type | nibble `type<<4 | version` = `0x11` for `v1/type=T1` |
| 2   | 4   | device_id      | `uint32` |
| 6   | 4   | seq            | `uint32`, monotonically increasing (wraps at 2^32) |
| 10  | 2   | flags          | see below |
| 12  | 2   | temperature    | `int16` = °C × 100 (range −327.68…327.67 °C) |
| 14  | 2   | humidity       | `uint16` = %RH × 100 (0…655.35) |
| 16  | 2   | mq2_raw        | `uint16` ADC counts (0…4095 typical, `4.096` SR) |
| 18  | 2   | water_raw      | `uint16` ADC counts 0…4095, `0xFFFF` = N/A |
| 20  | 2   | battery_mv     | `uint16` millivolts, `0xFFFF` = N/A |
| 22  | 2   | crc16          | CRC-16/CCITT-FALSE over bytes 0…21, little-endian |
| 24  | 8   | hmac           | HMAC-SHA256(key, bytes 0…23), first 8 bytes |

### Flags (bitfield, LSB first)

| Bit | Meaning |
|----:|---------|
| 0   | `temp_valid` |
| 1   | `hum_valid` |
| 2   | `mq2_valid` |
| 3   | `water_valid` |
| 4   | `water_detected` (current boolean state, valid only if bit 3 set) |
| 5   | `battery_valid` |
| 6   | `ack_requested` (gateway must transmit an ACK for this packet) |
| 7   | `simulated` (reading came from gateway simulator — never real hardware) |

### Integrity & authentication

`hmac = HMAC-SHA256(shared_key, packet[0:24])[0:8]`.

- The **CRC-16** lets the gateway cheaply reject corrupted frames (RFI) before
  spending time on HMAC verification.
- The **HMAC** authenticates the *pair* — a receiver holding the shared secret
  can verify a node's identity and that no in-flight bits were flipped.
- The shared key is provisioned **per device** and lives only in firmware
  compile-time config (or NVS) and gateway/backend config/DB — never in
  source control.
- See `docs/threat-model.md` for what this does *not* defend against (replay,
  compromised nodes) and why it is still appropriate for this system's risk
  profile.

Cleartext caveat: payload is **not encrypted** — packet contents are readable at
the RF layer. Keep the key secret for authentication, document the environment
if data confidentiality matters, and review `docs/threat-model.md` before
deploying (LoRaWAN's full AES-CTR + CMAC is out of scope for this pilot).

## Ack packet — downlink (`type=0x02`), 12 bytes

| Off | Len | Field     | Encoding |
|----:|----:|-----------|----------|
| 0   | 1   | magic     | `0xE5` |
| 1   | 1   | type/ver  | `0x21` for `v1/type=A2` |
| 2   | 4   | device_id | `uint32` |
| 6   | 4   | seq       | `uint32` — the sequence being acknowledged |
| 10  | 2   | crc16     | CRC-16/CCITT-FALSE over bytes 0…9, little-endian |

RadioLink duty cycle / regulatory note: ESP32 nodes *do not* transmit ACKs;
only the gateway does, at low frequency (≤ `ack_requested` packets received).
See `firmware/esp32/README.md` for regional limits.

## CRC-16/CCITT-FALSE

Polynomial `0x1021`, init `0xFFFF`, no reflection, no final XOR:

```python
def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc
```

## Message shape after decode (gateway → backend JSON)

The gateway forwards a validated JSON body to `POST /api/v1/telemetry`. The
transmission format is an implementation detail of the radio hop; the backend
owns the canonical JSON schema (`backend/app/schemas/telemetry.py`):

```json
{
  "device_id": 42,
  "seq": 12345,
  "flags": {
    "temp": true, "hum": true, "mq2": true,
    "water": true, "water_detected": false,
    "battery": true, "ack_requested": false, "simulated": false
  },
  "temperature_c": 23.45,
  "humidity_pct": 55.20,
  "mq2_raw": 312,
  "water_raw": 0,
  "battery_mv": 3820,
  "rssi": -78, "snr": 9.5,
  "gateway_id": "gw-1",
  "gateway_time": "2026-01-15T12:30:05.123Z"
}
```

Validation rules:
- `crc16` is checked first (cheaply rejects RF-corrupted frames); only then is `hmac` verified.
- `device_id != 0`.
- `seq` must be greater than the most recent `seq` for that device (strict
  duplicate rejection at the gateway over a sliding dedup window). The backend
  additionally enforces idempotency via a unique `(device_id, seq)` DB
  constraint, so gateway retries never duplicate rows.
- Sensor values are always carried through even when validity flags are false —
  the flags tell backend and dashboard which sensors to trust (see the
  sensor-malfunction alert rule).

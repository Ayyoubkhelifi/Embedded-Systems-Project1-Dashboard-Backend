# ESP32 Sensor Node Firmware

LoRa node for the ESS environmental monitoring system: DHT11 + MQ-2 + water
probe + battery monitor → signed 32-byte LoRa uplink → optional gateway ACK
with retry. See `../../../docs/packet-format.md` for the on-air format.

```
firmware/esp32/
├── ess_node/          Arduino sketch (src)
│   ├── ess_node.ino   main loop: sample → encode → send(+ACK) → schedule
│   ├── config.h       per-node provisioning (id, key, radio, thresholds)
│   ├── sensors.{h,cpp}  hardware sampling with per-sensor validity flags
│   └── radio_link.{h,cpp} RadioLib SX127x driver + ACK/retry state machine
└── lib/ess_packet/    self-contained Arduino library (packet codec incl.
                        CRC-16/CCITT-FALSE + truncated HMAC-SHA256 via mbedtls)
```

## Requirements

- Any ESP32 dev board (WROOM-32/WROVER/ttyDevKitV1) — tested with Arduino core 3.x.
- Arduino libraries (Library Manager → install):
  - `RadioLib` (SX1276/SX1278 driver)
  - `DHT sensor library` (Adafruit) with its `Adafruit Unified Sensor` dependency.
- SX1276/SX1278 LoRa module on SPI, wired per below.

## Wiring (overview; full pin maps in docs/hardware.md)

| Signal | ESP32 | Notes |
|--------|-------|-------|
| SX127x NSS (CS) | GPIO 18 | 3.3 V logic — never 5 V |
| SX127x DIO0 | GPIO 26 | TX/RX done IRQ |
| SX127x DIO1 | GPIO 33 | receive IRQ (RadioLib) |
| SX127x RST | GPIO 23 | |
| SX127x MOSI/MISO/SCK/SCK | VSPI (23/19/18...) | default SPI pins |
| DHT11 DATA | GPIO 4 | 10 kΩ pull-up to 3.3 V |
| MQ-2 A0 | GPIO 34 | ADC1, input-only |
| Water probe | GPIO 35 (analog) or GPIO 16 (float switch) | |
| Battery divider | GPIO 32 | 100k/100k VBAT divider |

## Config per device (ess_node/config.h)

1. `NODE_DEVICE_ID` — uint32 id, matches the backend `devices.device_id`.
2. `NODE_KEY_HEX` — 32-hex-char (16-byte) HMAC key. Provision the SAME key
   into the gateway `NODE_KEYS` env: `101:<hex>`.
   Generate a fresh key with:
   `python -c "import secrets; print(secrets.token_hex(16))"`
3. Radio params must match the gateway: `RADIO_FREQ_MHZ/SF/BW/CR/SYNC_WORD`.

## Build & flash

```bash
# Arduino IDE: select the ess_node sketch, board "ESP32 Dev Module".
# or Arduino CLI:
arduino-cli lib install RadioLib "DHT sensor library"
arduino-cli compile --fqbn esp32:esp32:esp32 firmware/esp32/ess_node
arduino-cli upload -p <COM|/dev/ttyUSB0> --fqbn esp32:esp32:esp32 firmware/esp32/ess_node
```

Open the serial monitor at 115200 baud for logs. A readback like
`node 101 online (key ok, radio ok)` plus periodic `sent seq=… status=…`
lines confirm healthy operation (status 0 = acked, -4 = NoAck → check gateway).

## Simulated bring-up (no LoRa hardware)

Uncomment `#define SIMULATED_NODE` in `config.h` to compile with the
loopback radio. The packet SIMULATED flag is set; gateways mark those
readings `simulated` and the backend rejects them in production.

## Reliability notes

- Fire-and-size uplinks every `SEND_INTERVAL_MS`; alerted readings require
  ACK (`FLAG_ACK_REQUESTED`) and retry `ACK_RETRIES` with jittered backoff.
- `seq` lives in NVS (`Preferences`) so identifiers never repeat across
  reboots — replay protection at the gateway depends on monotonic seq.
- No WiFi on this node: the radio is the only network interface (increases
  tamper resistance; there is nothing to remotely pwn on the node).

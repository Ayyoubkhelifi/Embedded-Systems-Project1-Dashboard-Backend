# Hardware Guide

## Node (ESP32 + sensors)

### Wiring

| Signal | ESP32 pin | Peripheral |
|--------|-----------|-----------|
| SX127x MOSI/SO | GPIO 23 | VSPI |
| SX127x MISO/SI | GPIO 19 | |
| SX127x SCK | GPIO 18 | |
| SX127x NSS/CS | GPIO 5 | 3.3 V logic only |
| SX127x DIO0 | GPIO 26 | TX/RX done |
| SX127x RST | GPIO 14 | |
| DHT11 DATA | GPIO 4 | 10 kΩ pull-up to 3.3 V |
| MQ-2 analog out | GPIO 34 (ADC1) | never power MQ-2 from a GPIO |
| Water probe analog | GPIO 35 (ADC1) | |
| Water float switch | GPIO 16, INPUT_PULLUP | optional build |
| Battery divider | GPIO 32 | 100 kΩ / 100 kΩ to GND |

```
                 ┌──────────────┐
   VCC ──────────┤ SX127x       │
   GND ──────────┤  Lora module │
 GPIO23 (MOSI)───┤              │
 GPIO19 (MISO)───┤              │
 GPIO18 (SCK) ───┤              │
 GPIO5  (NSS/CS)─┤              │
 GPIO26 (DIO0)───┤              │
 GPIO14 (RST) ───┤              │
                 └──────────────┘
```

Notes:

- **Never 5 V** on SX127x or DHT11 logic pins. Level-shift only if the
  module is a 5 V breakout.
- MQ-2 needs a **1–2 min burn-in** after first power (the firmware skips
  sampling for `MQ2_WARMUP_MS` = 30 s to avoid PK ramps).
- All three ADC pins are ADC1 channels — safe with WiFi (unused here).

### Bill of materials (per node)

| Item | Notes |
|------|-------|
| ESP32 DevKit board | WROOM-32 recommended |
| E32/SX1276/SX1278 module | 868 MHz for EU/IND; 915 MHz US; 433 MHz CN |
| DHT11 breakout | hum/temperature ±2 °C class |
| MQ-2 sensor + breakout | analog A0; needs 5 V heater |
| Soil/water probe or float switch | analog preferred |
| Li-Ion 18650 + BMS/TP4056 or 5 V PSU | battery path optional |

## Gateway (Raspberry Pi + SX127x)

| SX127x | Raspberry Pi (BCM) |
|--------|--------------------|
| VCC 3V3 | 3V3 |
| GND | any GND |
| MOSI | GPIO 10 (SPI0 MOSI) |
| MISO | GPIO 9 (SPI0 MISO) |
| SCK | GPIO 11 (SPI0 SCLK) |
| NSS/CS | GPIO 8 (CE0) |
| DIO0 | GPIO 17 |
| RST | GPIO 22 |

Enable SPI (`sudo raspi-config` → Interface Options → SPI), install the
hardware extras (`gateway/requirements-lora.txt`), then run the gateway as
a systemd unit (see `deployment.md`).

> The gateway and every node must agree on frequency band. **Regulatory**
> limits (duty cycle / EIRP) differ per region — EU868 defaults put TX at
> 14 dBm mono duty-cycled; keep the default 30 s uplink interval (≈ 0.7 %
> duty cycle) or reduce.sf to lower airtime.

## Radio configuration matrix

| Param | Node (`config.h`) | Gateway (`GATEWAY_*/LORA_*` env) |
|-------|-------------------|----------------------------------|
| Frequency | 868.10 MHz | 868.10 MHz |
| SF / BW / CR | 7 / 125 kHz / 5 | 7 / 125 kHz / 5 |
| Sync word | 0x12 | 0x12 |
| TX power | 14 dBm | (RX only) |

## Provisioning workflow (per new node)

1. Generate: `python -c "import secrets; print(secrets.token_hex(16))"`.
2. Bake it + a fresh `NODE_DEVICE_ID` into `ess_node/config.h` and flash.
3. Add the pair to the gateway: `NODE_KEYS="<id>:<hex>,..."`
4. Register the id inside the dashboard → devices (admin/operator) so the
   backend accepts packets — ingestion rejects unknown/inactive devices
   (`DEVICE_NOT_REGISTERED`/`DEVICE_INACTIVE`).

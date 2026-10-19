/**
 * ess/config.h — per-node provisioning. Flash DIFFERENT values per device.
 *
 * SECURITY: NODE_KEY is a per-node HMAC secret. Seed it into the gateway's
 * NODE_KEYS env (`gpio: NODE_KEYS="101:<hex>,..."`) with the same byte value.
 * Generate with: python -c "import secrets; print(secrets.token_hex(16))"
 */
#pragma once

// ==== Identity ====
#define NODE_DEVICE_ID 101u           // uint32 LoRa id; matches backend devices row
#define NODE_KEY_HEX "00ff11ee22dd33cc44bb55aa66998877"  // 16 bytes hex

// ==== Radio (must match gateway LORA_* settings) ====
// EU868 ISM defaults. CHECK LOCAL REGULATIONS (duty cycle limits etc.).
#define RADIO_FREQ_MHZ 868.10f
#define RADIO_SF 7        // spreading factor 7..12
#define RADIO_BW_KHZ 125  // 125 / 250 kHz
#define RADIO_CR 5        // coding rate 5
#define RADIO_TX_DBM 14   // 2..20 (EU868 max commonly 14 dBm ERP)
#define RADIO_SYNC_WORD 0x12

// ==== Timings ====
#define SEND_INTERVAL_MS 30000ul    // uplink period
#define ACK_TIMEOUT_MS 1500         // window for gateway ACK
#define ACK_RETRIES 3               // total attempts (1 + retries)
#define RETRY_BACKOFF_MS 800        // per retry step (approx, with jitter)

// ==== Alert thresholds (drives ACK_REQUESTED so operator sees urgency) ====
#define TEMP_ALERT_C 35.0f
#define MQ2_ALERT_RAW 800
#define BATTERY_LOW_MV 3500

// ==== Calibration ====
// DHT11 humidity/temperature hardware calibration offset (rarely needed)
#define DHT_TEMP_OFFSET_C 0.0f
// MQ-2 burn-in: ADC warm-up read is skipped for this many ms after boot
#define MQ2_WARMUP_MS 30000

// ==== Simulated mode (CI/hardware-free bring-up) ====
// #define SIMULATED_NODE 1  // uncomment to send SIM-flagged synthetic values

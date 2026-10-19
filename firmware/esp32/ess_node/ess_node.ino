/**
 * ess_node.ino — ESP32 environmental sensor node.
 *
 * Sample (DHT11 + MQ-2 + water probe + battery) -> signed 32-byte LoRa frame
 * -> optional ACK -> sleep until next period. Duplicate-tolerant end-to-end:
 * retransmits are deduplicated by (device_id, seq) at the gateway/backend.
 *
 * Libraries (Arduino Library Manager), see firmware/esp32/README.md:
 *   RadioLib, DHT sensor library (Adafruit), Adafruit Unified Sensor
 */

#include "config.h"
#include "sensors.h"
#include "radio_link.h"
#include "ess_packet.h"

#include <Arduino.h>
#include <Preferences.h>
#include "esp_random.h"

#ifndef LED_BUILTIN
#define LED_BUILTIN 2  // common ESP32 dev-board on-board LED pin
#endif

namespace {

uint8_t NODE_KEY[ess::ESS_KEY_LEN];
uint32_t seq_next = 0;
bool radio_ready = false;
Preferences prefs;

bool hex_pair(char a, char b, uint8_t& out) {
  const auto nib = [](char c) -> int {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
  };
  const int hi = nib(a), lo = nib(b);
  if (hi < 0 || lo < 0) return false;
  out = (uint8_t)((hi << 4) | lo);
  return true;
}

bool parse_node_key_hex() {
  const char* hex = NODE_KEY_HEX;
  if (strlen(hex) != 2 * ess::ESS_KEY_LEN) {
    log_e("NODE_KEY_HEX must be 32 hex chars");
    return false;
  }
  for (size_t i = 0; i < ess::ESS_KEY_LEN; ++i) {
    const char a = hex[2 * i], b = hex[2 * i + 1];
    uint8_t byte;
    if (!hex_pair(a, b, byte)) return false;
    NODE_KEY[i] = byte;
  }
  return true;
}

void load_seq_from_nvs() {
  // Non-volatile seq persistence: survives power loss so identifiers never
  // repeat (a repeated seq would collide with the backend dedup window).
  prefs.begin("ess", false);
  seq_next = prefs.getUInt("seq", 0u);
}

void store_seq(uint32_t v) { prefs.putUInt("seq", v); }

ess::TelemetryPacket build_packet(const sensors::Sample& s) {
  ess::TelemetryPacket p;
  p.device_id = NODE_DEVICE_ID;
  p.seq = seq_next;
  uint16_t flags = 0;
  if (s.temp_valid) {
    p.temp_c100 = (int16_t)lroundf(s.temp_c * 100.0f);
    flags |= ess::FLAG_TEMP;
  }
  if (s.hum_valid) {
    p.hum_p100 = (uint16_t)lroundf(s.humidity_pct * 100.0f);
    flags |= ess::FLAG_HUM;
  }
  if (s.mq2_valid) {
    p.mq2_raw = s.mq2_raw;
    flags |= ess::FLAG_MQ2;
    if (s.mq2_raw >= MQ2_ALERT_RAW) flags |= ess::FLAG_ACK_REQUESTED;
  }
  if (s.water_valid) {
    p.water_raw = s.water_raw;
    flags |= ess::FLAG_WATER;
    if (s.water_detected) {
      flags |= ess::FLAG_WATER_DETECTED;
      flags |= ess::FLAG_ACK_REQUESTED;
    }
  }
  if (s.battery_valid) {
    p.battery_mv = s.battery_mv;
    flags |= ess::FLAG_BATTERY;
  }
#ifdef SIMULATED_NODE
  flags |= ess::FLAG_SIMULATED;
#endif
  p.flags = flags;
  return p;
}

void log_battery_flatline(const ess::TelemetryPacket& p) {
  if (p.battery_mv != 0xFFFF && p.battery_mv < BATTERY_LOW_MV) {
    log_w("battery low: %u mV", p.battery_mv);
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(200);
  if (!parse_node_key_hex()) {
    log_e("refusing to boot without a valid NODE_KEY_HEX");
    // Blink SOS: security failure must not silently broadcast unsigned junk.
    pinMode(LED_BUILTIN, OUTPUT);
    for (;;) {
      digitalWrite(LED_BUILTIN, HIGH); delay(80);
      digitalWrite(LED_BUILTIN, LOW); delay(80);
      digitalWrite(LED_BUILTIN, HIGH); delay(80);
      digitalWrite(LED_BUILTIN, LOW); delay(400);
    }
  }
  load_seq_from_nvs();
  sensors::begin();
  radio_ready = radiolink::begin(NODE_DEVICE_ID);
  if (!radio_ready) {
    log_e("SX127x init failed — check wiring/NSS/DIO pins");
  }
  log_i("node %u online (key ok, radio %s)", NODE_DEVICE_ID, radio_ready ? "ok" : "FAULT");
}

void loop() {
  static uint32_t next_send = millis() + 3000;  // small startup grace period
  const uint32_t now = millis();

  if ((int32_t)(now - next_send) < 0) {
    delay(20);
    return;
  }

  const sensors::Sample s = sensors::read_all();
  ess::TelemetryPacket p = build_packet(s);

#ifdef SIMULATED_NODE
  // Synthetic values so CI/bring-up exercises the full path.
  p.temp_c100 = 2300 + (int16_t)((esp_random() % 300) - 150);
  p.hum_p100 = 4000 + (uint16_t)(esp_random() % 150);
  p.mq2_raw = (uint16_t)(200 + (esp_random() % 250));
  p.water_raw = 30 + (uint16_t)(esp_random() % 40);
  p.flags |= ess::FLAG_TEMP | ess::FLAG_HUM | ess::FLAG_MQ2 | ess::FLAG_WATER;
#endif

  radiolink::Status st = radiolink::send_with_ack(p, NODE_KEY);
  // seq strictly increases; NVS write coalesced to avoid flash wear.
  store_seq(p.seq + 1);
  seq_next += 1;

  int link_rssi = 0;
  float link_snr = 0.0f;
  radiolink::last_link(&link_rssi, &link_snr);
  log_i("sent seq=%u status=%d T=%.1f H=%.1f MQ2=%u W=%u B=%u RSSI=%d SNR=%.1f",
        (unsigned)p.seq, (int)st,
        (p.flags & ess::FLAG_TEMP) ? p.temp_c100 / 100.0f : -99.0f,
        (p.flags & ess::FLAG_HUM) ? p.hum_p100 / 100.0f : -1.0f,
        (unsigned)p.mq2_raw, (unsigned)p.water_raw, (unsigned)p.battery_mv,
        link_rssi, link_snr);
  log_battery_flatline(p);

  next_send = now + SEND_INTERVAL_MS;
}

#include "sensors.h"
#include "config.h"
#include <DHT.h>
#include "esp_system.h"

namespace {

struct Pins {
  // SX1276 (RadioLink) pins live in radio_link.h/config.h; sensor pins here:
  static constexpr uint8_t DHT_PIN = 4;
  static constexpr uint8_t MQ2_ADC = 34;   // ADC1_CH6, input-only, no WiFi conflict
  static constexpr uint8_t WATER_ADC = 35; // ADC1_CH7 analog probe
  static constexpr uint8_t WATER_DIG = 16; // float switch alternative (INPUT_PULLUP)
  static constexpr uint8_t BATT_ADC = 32;  // divider: VBAT -- 100k -- ADC -- 100k -- GND
};

DHT dht(Pins::DHT_PIN, DHT11);
bool water_use_analog = true;
uint8_t key[16] = {0};  // seeds RNG from key material at boot (non-critical use)

uint16_t read_mq2() {
  // Multi-sample median for a sticky analog front-end.
  uint16_t s[5];
  for (uint8_t i = 0; i < 5; ++i) {
    s[i] = (uint16_t)analogRead(Pins::MQ2_ADC);
    delay(2);
  }
  for (uint8_t i = 1; i < 5; ++i) {  // insertion sort (5 elements)
    uint16_t v = s[i];
    int j = i - 1;
    while (j >= 0 && s[j] > v) { s[j + 1] = s[j]; --j; }
    s[j + 1] = v;
  }
  return s[2];
}

uint16_t read_battery_mv() {
  // 100k/100k divider: mv at ADC * 2 = battery voltage.
  uint32_t acc = 0;
  for (uint8_t i = 0; i < 8; ++i) { acc += analogRead(Pins::BATT_ADC); delay(1); }
  return (uint16_t)((acc / 8) * 3300 / 4095 * 2);
}

bool water_read_analog() {
  uint16_t raw = (uint16_t)analogRead(Pins::WATER_ADC);
  // Probe wet => significant drop below reference (tune per probe).
  return raw < 2500;
}

bool water_read_digital() {
  // Float switch with pull-up: LOW when wet.
  return digitalRead(Pins::WATER_DIG) == LOW;
}

}  // namespace

namespace sensors {

void begin() {
  analogReadResolution(12);
  analogSetPinAttenuation(Pins::MQ2_ADC, ADC_11db);   // ~0..3.3V
  analogSetPinAttenuation(Pins::WATER_ADC, ADC_11db);
  analogSetPinAttenuation(Pins::BATT_ADC, ADC_11db);
  pinMode(Pins::WATER_DIG, INPUT_PULLUP);
  water_use_analog = true;  // flip to false if the build uses a float switch
  dht.begin();
  delay(1200);              // DHT11 stabilisation window
  // Mix the per-node key into the PRNG so backoff jitter differs per node.
  esp_random();
  for (int i = 0; i < 16; ++i) key[i] = (uint8_t)(esp_random() ^ key[i]);
}

Sample read_all() {
  Sample s{};
  const float t = dht.readTemperature() + DHT_TEMP_OFFSET_C;
  const float h = dht.readHumidity();
  if (!isnan(t) && t > -40.0f && t < 80.0f) { s.temp_valid = true; s.temp_c = t; }
  if (!isnan(h) && h >= 0.0f && h <= 100.0f) { s.hum_valid = true; s.humidity_pct = h; }

  const uint32_t since_boot = millis();
  if (since_boot >= MQ2_WARMUP_MS) {
    s.mq2_raw = read_mq2();
    s.mq2_valid = true;
  }

  if (water_use_analog) {
    s.water_raw = (uint16_t)analogRead(Pins::WATER_ADC);
    s.water_valid = true;
    s.water_detected = water_read_analog();
  } else {
    s.water_detected = water_read_digital();
    s.water_valid = s.water_detected;  // digital: raw unavailable (0xFFFF)
  }

  s.battery_mv = read_battery_mv();
  s.battery_valid = s.battery_mv >= 2500;  // divider sanity
  return s;
}

}  // namespace sensors

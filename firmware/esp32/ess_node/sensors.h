/**
 * sensors.h — DHT11 temperature/humidity, MQ-2 combustible gas (raw ADC),
 * analog water probe, battery monitor.
 *
 * All sensors are FAIL-OPEN: an absent or broken sensor leaves its validity
 * flag false in the packet (SENSOR MALFUNCTION is then raised by the backend
 * rule engine). Water detection may be implemented with an analog probe
 * (WATER_SENSOR_ANALOG=1) or a float switch on a digital pin.
 */
#pragma once

#include <stdint.h>

namespace sensors {

struct Sample {
  bool temp_valid;   float temp_c;      // degC
  bool hum_valid;    float humidity_pct;
  bool mq2_valid;    uint16_t mq2_raw;  // raw ADC 0..4095 (12-bit)
  bool water_valid;  uint16_t water_raw;
  bool water_detected;
  bool battery_valid; uint16_t battery_mv;
};

/** One-shot synchronous sampling; call no faster than the DHT 1 Hz minimum. */
Sample read_all();

/** Call once from setup(): warms hardware, primes ADC, seeds RNG. */
void begin();

}  // namespace sensors

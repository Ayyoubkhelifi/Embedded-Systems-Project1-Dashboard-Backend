// ESS LoRa packet format v1 (docs/packet-format.md).
// Uplink: 0xE5 0x11 | device_id u32LE | seq u32LE | flags u16LE |
//         temp i16LE (degC*100) | hum u16LE (pct*100) | mq2 u16LE |
//         water u16LE (0xFFFF none) | battery u16LE (0xFFFF none) |
//         crc16 ccitt-false u16LE | hmac_sha256(msg[0..23], key)[0..7]
// Total 32 bytes. Downlink ACK: 0xE5 0x21 | device_id u32LE | seq u32LE | crc16 u16LE = 12 bytes.
#ifndef ESS_PACKET_H
#define ESS_PACKET_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define ESS_PACKET_VERSION 0x1
#define ESS_MAGIC 0xE5
#define ESS_HDR_DATA 0x11   // first/header pair on the wire: E5 11
#define ESS_HDR_ACK 0x21    // on the wire: E5 21
#define ESS_DATA_LEN 32
#define ESS_ACK_LEN 12
#define ESS_KEY_LEN 16

namespace ess {

enum : uint16_t {
  FLAG_TEMP = 1u << 0,
  FLAG_HUM = 1u << 1,
  FLAG_MQ2 = 1u << 2,
  FLAG_WATER = 1u << 3,
  FLAG_WATER_DETECTED = 1u << 4,
  FLAG_BATTERY = 1u << 5,
  FLAG_ACK_REQUESTED = 1u << 6,
  FLAG_SIMULATED = 1u << 7,
};

// Lightweight packet view. Values are raw units as documented.
struct TelemetryPacket {
  uint32_t device_id = 0;
  uint32_t seq = 0;
  uint16_t flags = 0;
  int16_t temp_c100 = 0;       // degrees * 100
  uint16_t hum_p100 = 0;       // percent * 100
  uint16_t mq2_raw = 0;        // 0..4095
  uint16_t water_raw = 0xFFFF; // 0xFFFF => not available
  uint16_t battery_mv = 0xFFFF;

  inline void setFlag(uint16_t mask, bool on) {
    if (on) flags |= mask; else flags &= (uint16_t)~mask;
  }
};

// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF).
uint16_t crc16(uint16_t crc, const uint8_t* data, size_t len);
uint16_t crc16(const uint8_t* data, size_t len);

// Encodes into buf[ESS_DATA_LEN] using key[ESS_KEY_LEN]; returns frame length (32).
size_t encode_telemetry(const TelemetryPacket& packet, const uint8_t key[ESS_KEY_LEN], uint8_t buf[ESS_DATA_LEN]);

// Encodes ACK downlink (12 bytes).
size_t encode_ack(uint32_t device_id, uint32_t seq, uint8_t buf[ESS_ACK_LEN]);

// Validates a frame against the given key (crc + hmac). Returns:
//   1  if valid data frame (packet reference filled)
//   0  if crc or format broken
//  -1  if hmac mismatch (garbled or wrong key)
//  -2  if not a data frame for us (magic/type mismatch or length wrong)
int decode_telemetry(const uint8_t* frame, size_t len, const uint8_t key[ESS_KEY_LEN], TelemetryPacket* out);

}  // namespace ess

#endif  // ESS_PACKET_H

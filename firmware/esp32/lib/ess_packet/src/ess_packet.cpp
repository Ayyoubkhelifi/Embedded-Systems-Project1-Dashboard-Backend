#include "ess_packet.h"

// ESP32 Arduino cores ship mbedtls (ROM or esp32-hal). We use mbedtls SHA256.
#include "mbedtls/sha256.h"

#include <Arduino.h>

namespace ess {

uint16_t crc16(const uint8_t* data, size_t len) {
  return crc16(0xFFFF, data, len);
}

uint16_t crc16(uint16_t crc, const uint8_t* data, size_t len) {
  for (size_t i = 0; i < len; ++i) {
    crc ^= (uint16_t)data[i] << 8;
    for (uint8_t b = 0; b < 8; ++b) {
      crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
    }
  }
  return crc;
}

// Little-endian helpers (ESP32 is little-endian; direct casts would work but
// keep the encoder explicit and portable).
static inline void put_u16(uint8_t* p, uint16_t v) {
  p[0] = (uint8_t)(v & 0xFF);
  p[1] = (uint8_t)(v >> 8);
}
static inline uint16_t get_u16(const uint8_t* p) {
  return (uint16_t)(p[0] | (p[1] << 8));
}
static inline void put_u32(uint8_t* p, uint32_t v) {
  p[0] = (uint8_t)(v & 0xFF);
  p[1] = (uint8_t)((v >> 8) & 0xFF);
  p[2] = (uint8_t)((v >> 16) & 0xFF);
  p[3] = (uint8_t)((v >> 24) & 0xFF);
}
static inline uint32_t get_u32(const uint8_t* p) {
  return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static void hmac_sha256_trunc8(const uint8_t* key, size_t keylen,
                               const uint8_t* msg, size_t msglen,
                               uint8_t out[8]) {
  // HMAC-SHA256 with a 32-byte-block key, truncated to 8 bytes. The key is
  // 16 bytes (<= block size) so no extra hashing of the key is needed.
  const size_t block = 64;
  uint8_t k0[block];
  memset(k0, 0, block);
  memcpy(k0, key, keylen <= block ? keylen : block);

  uint8_t ipad[block], opad[block];
  for (size_t i = 0; i < block; ++i) {
    ipad[i] = k0[i] ^ 0x36;
    opad[i] = k0[i] ^ 0x5c;
  }

  uint8_t inner[32];
  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0);
  mbedtls_sha256_update(&ctx, ipad, block);
  mbedtls_sha256_update(&ctx, msg, msglen);
  mbedtls_sha256_finish(&ctx, inner);
  mbedtls_sha256_free(&ctx);
  memset(&ctx, 0, sizeof(ctx));

  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0);
  mbedtls_sha256_update(&ctx, opad, block);
  mbedtls_sha256_update(&ctx, inner, 32);
  uint8_t mac[32];
  mbedtls_sha256_finish(&ctx, mac);
  mbedtls_sha256_free(&ctx);
  memset(&ctx, 0, sizeof(ctx));

  memcpy(out, mac, 8);
}

size_t encode_telemetry(const TelemetryPacket& packet, const uint8_t key[ESS_KEY_LEN], uint8_t buf[ESS_DATA_LEN]) {
  memset(buf, 0, ESS_DATA_LEN);
  buf[0] = ESS_MAGIC;
  buf[1] = ESS_HDR_DATA;                             // type/version
  put_u32(buf + 2, packet.device_id);
  put_u32(buf + 6, packet.seq);
  put_u16(buf + 10, packet.flags);
  put_u16(buf + 12, (uint16_t)(int16_t)packet.temp_c100);
  put_u16(buf + 14, packet.hum_p100);
  put_u16(buf + 16, packet.mq2_raw);
  put_u16(buf + 18, packet.water_raw);
  put_u16(buf + 20, packet.battery_mv);
  put_u16(buf + 22, crc16(buf, 22));

  // HMAC over the signed region: bytes 0..23 inclusive (22-byte payload + crc16).
  uint8_t mac[8];
  hmac_sha256_trunc8(key, ESS_KEY_LEN, buf, 24, mac);
  memcpy(buf + 24, mac, 8);
  return ESS_DATA_LEN;
}

size_t encode_ack(uint32_t device_id, uint32_t seq, uint8_t buf[ESS_ACK_LEN]) {
  buf[0] = ESS_MAGIC;
  buf[1] = ESS_HDR_ACK;
  put_u32(buf + 2, device_id);
  put_u32(buf + 6, seq);
  put_u16(buf + 10, crc16(buf, 10));
  return ESS_ACK_LEN;
}

int decode_telemetry(const uint8_t* frame, size_t len, const uint8_t key[ESS_KEY_LEN], TelemetryPacket* out) {
  if (frame == nullptr || len != ESS_DATA_LEN) return -2;
  if (frame[0] != ESS_MAGIC || frame[1] != ESS_HDR_DATA) return -2;

  uint16_t crc = get_u16(frame + 22);
  if (crc16(frame, 22) != crc) return 0;

  uint8_t expect[8];
  hmac_sha256_trunc8(key, ESS_KEY_LEN, frame, 24, expect);
  if (memcmp(expect, frame + 24, 8) != 0) return -1;

  if (out) {
    out->device_id = get_u32(frame + 2);
    out->seq = get_u32(frame + 6);
    out->flags = get_u16(frame + 10);
    out->temp_c100 = (int16_t)get_u16(frame + 12);
    out->hum_p100 = get_u16(frame + 14);
    out->mq2_raw = get_u16(frame + 16);
    out->water_raw = get_u16(frame + 18);
    out->battery_mv = get_u16(frame + 20);
  }
  return 1;
}

}  // namespace ess

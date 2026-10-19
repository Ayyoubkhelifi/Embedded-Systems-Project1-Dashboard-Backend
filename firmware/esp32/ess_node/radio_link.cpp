#include "radio_link.h"
#include "config.h"
#include <SPI.h>
#include <RadioLib.h>
#include "esp_random.h"

namespace radiolink {

namespace {

SX1276 radio;

volatile bool flag_dio0 = false;
volatile bool flag_dio1 = false;

#if defined(ARDUINO_ARCH_ESP32)
IRAM_ATTR
#endif
void isr_dio0() { flag_dio0 = true; }

#if defined(ARDUINO_ARCH_ESP32)
IRAM_ATTR
#endif
void isr_dio1() { flag_dio1 = true; }

int last_rssi = 0;
float last_snr = 0.0f;
bool simulated = false;

bool start_lora() {
  // Standard ESP32 wiring (see docs/hardware.md): NSS=18, DIO0=26, DIO1=33, RST=23.
  const int state = radio.begin(
      RADIO_FREQ_MHZ, RADIO_BW_KHZ, (RADIO_SF > 6 ? RADIO_SF : 7),
      (RADIO_CR == 5 ? 5 : RADIO_CR), RADIO_SYNC_WORD, RADIO_TX_DBM, 8, 0, false);
  if (state != RADIOLIB_ERR_NONE) return false;

  radio.setDio0Action(isr_dio0, RISING);
  radio.setDio1Action(isr_dio1, RISING);

  // 32-byte airtime packets; LoRa CRC adds nothing on top of crc16+hmac.
  radio.setCurrentLimit(100);
  radio.setPreambleLength(8);
  radio.setCRC(false);

  return (radio.startReceive() == RADIOLIB_ERR_NONE);
}

// ACK: E5 21 | device_id u32LE | seq u32LE | crc16 u16LE (12 bytes)
bool parse_ack(const uint8_t* ack, size_t len, uint32_t expect_device, uint32_t expect_seq) {
  if (len != ESS_ACK_LEN) return false;
  if (ack[0] != ESS_MAGIC || ack[1] != ESS_HDR_ACK) return false;
  const uint16_t crc_rx = (uint16_t)(ack[10] | (ack[11] << 8));
  if (ess::crc16(ack, 10) != crc_rx) return false;
  const uint32_t dev = (uint32_t)ack[2] | ((uint32_t)ack[3] << 8) |
                       ((uint32_t)ack[4] << 16) | ((uint32_t)ack[5] << 24);
  const uint32_t seq = (uint32_t)ack[6] | ((uint32_t)ack[7] << 8) |
                       ((uint32_t)ack[8] << 16) | ((uint32_t)ack[9] << 24);
  return dev == expect_device && seq == expect_seq;
}

uint32_t rng_word() { return (uint32_t)esp_random(); }

}  // namespace

bool begin(uint32_t) {
#ifdef SIMULATED_NODE
  simulated = true;
#endif
  if (simulated) {
    simulated = true;
    return true;
  }
  return start_lora();
}

bool is_simulated() { return simulated; }

void last_link(int* rssi_dbm, float* snr_db) {
  if (rssi_dbm) *rssi_dbm = last_rssi;
  if (snr_db) *snr_db = last_snr;
}

Status send_with_ack(const ess::TelemetryPacket& packet, const uint8_t key[ESS_KEY_LEN]) {
  uint8_t frame[ESS_DATA_LEN];
  ess::encode_telemetry(packet, key, frame);
  if (frame[0] != ESS_MAGIC) return Status::EncodeError;

  if (simulated) {
    // Loopback: pretend an ACK came back immediately.
    return Status::Ok;
  }

  for (uint8_t attempt = 0; attempt <= ACK_RETRIES; ++attempt) {
    if (attempt > 0) {
      // Exponential-ish jittered backoff keeps nodes slightly out of phase.
      uint32_t ms = RETRY_BACKOFF_MS * (1u << (attempt - 1));
      ms = (ms * 3) / 4 + (rng_word() % (RETRY_BACKOFF_MS / 2));
      delay(ms);
    }

    radio.standby();
    if (radio.transmit(frame, ESS_DATA_LEN) != RADIOLIB_ERR_NONE) return Status::SendTimeout;

    if (!(packet.flags & ess::FLAG_ACK_REQUESTED)) {
      // Fire-and-forget: gateway dedups by (device_id, seq) anyway.
      if (radio.startReceive() != RADIOLIB_ERR_NONE) return Status::RadioInitFailed;
      continue;
    }

    const uint32_t t0 = millis();
    while (millis() - t0 < ACK_TIMEOUT_MS) {
      uint8_t ack[ESS_ACK_LEN];
      const int n = radio.readData(ack, sizeof(ack));
      if (n == (int)sizeof(ack) && parse_ack(ack, sizeof(ack), packet.device_id, packet.seq)) {
        last_rssi = radio.getRSSI();
        last_snr = radio.getSNR();
        radio.startReceive();
        return Status::Ok;
      }
    }
  }
  radio.startReceive();
  return Status::NoAck;
}

}  // namespace radiolink

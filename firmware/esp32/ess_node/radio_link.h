/**
 * radio_link.h — SX1276/SX1278 LoRa link with ACK + retry.
 *
 * Modes:
 *  - RadioLib (SX1276 class) is the default radio driver.
 *  - SIMULATED_RADIO=1 swaps in a loopback "radio" that only requires the
 *    ess_packet encoder, letting CI verify the retry/ACK logic without hw.
 *
 * Error domain: send_with_ack() returns true strictly when an ACK matching
 * (device_id, seq) was received within the window. Uplinks are FIRE-AND-FORGET
 * otherwise — the gateway's SQLite buffer + backend dedup tolerate retransmits,
 * so a duplicate does NOT duplicate data.
 */
#pragma once

#include <stdint.h>
#include "ess_packet.h"

namespace radiolink {

enum class Status : uint8_t {
  Ok = 0,
  RadioInitFailed,
  EncodeError,
  SendTimeout,
  NoAck,
};

/** Bring up the radio; call once from setup(). false on hardware failure. */
bool begin(uint32_t device_id);

/** True when the radio was passed SIMULATED_NODE compile flag. */
bool is_simulated();

/** Blocking send + wait for ACK. Returns Ok only on ACKed transmission. */
Status send_with_ack(const ess::TelemetryPacket& packet, const uint8_t key[ESS_KEY_LEN]);

/** Fetch best-effort diagnostics (last rssi/snr from the ACK exchange). */
void last_link(int* rssi_dbm, float* snr_db);

}  // namespace radiolink

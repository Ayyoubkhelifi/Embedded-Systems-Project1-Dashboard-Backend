"""ESS packet codec — mirrors docs/packet-format.md byte-for-byte.

Uplink data packet v1 (32 bytes):
  [0:2]  header `0xE511` (magic + type/ver)
  [2:6]  device_id  u32le
  [6:10] seq        u32le
  [10:12] flags     u16le
  [12:14] temp      i16le (°C × 100)
  [14:16] humidity  u16le (%RH × 100)
  [16:18] mq2_raw   u16le
  [18:20] water_raw u16le (0xFFFF = N/A)
  [20:22] battery_mv u16le (0xFFFF = N/A)
  [22:24] crc16     u16le (CRC-16/CCITT-FALSE of bytes 0..21)
  [24:32] hmac      HMAC-SHA256(key, bytes 0..23), first 8 bytes

Downlink ACK v1 (12 bytes):
  [0:2] header `0xE521` | [2:6] device_id | [6:10] seq | [10:12] crc16
"""
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import struct
from dataclasses import dataclass, field

MAGIC = 0xE5
PACKET_VERSION = 0x1
TYPE_DATA = 0x1
TYPE_ACK = 0x2
# Little-endian uint16 on the wire yields byte0=MAGIC, byte1=type<<4|version.
HDR_DATA = MAGIC | ((TYPE_DATA << 4 | PACKET_VERSION) << 8)  # 0x11E5 → E5 11
HDR_ACK = MAGIC | ((TYPE_ACK << 4 | PACKET_VERSION) << 8)  # 0x21E5 → E5 21

SIGNED_LEN = 24  # header..battery (crc+hmac live after)
DATA_PACKET_LEN = 32
ACK_PACKET_LEN = 12

FLAG_TEMP = 1 << 0
FLAG_HUM = 1 << 1
FLAG_MQ2 = 1 << 2
FLAG_WATER = 1 << 3
FLAG_WATER_DETECTED = 1 << 4
FLAG_BATTERY = 1 << 5
FLAG_ACK_REQ = 1 << 6
FLAG_SIMULATED = 1 << 7

NA16 = 0xFFFF

_DATA_FMT = "<HIIHHHHHH"  # header, device_id, seq, flags, temp, hum, mq2, water, battery
_ACK_FMT = "<HII"


class PacketError(ValueError):
    """Raised for any malformed/invalid packet (length, magic, CRC, or HMAC)."""


def crc16_ccitt_false(data: bytes, crc: int = 0xFFFF) -> int:
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


@dataclass
class Flags:
    temp: bool = False
    hum: bool = False
    mq2: bool = False
    water: bool = False
    water_detected: bool = False
    battery: bool = False
    ack_requested: bool = False
    simulated: bool = False

    def to_int(self) -> int:
        v = 0
        for bit, present in enumerate(
            (self.temp, self.hum, self.mq2, self.water, self.water_detected, self.battery, self.ack_requested, self.simulated)
        ):
            if present:
                v |= 1 << bit
        return v

    @classmethod
    def from_int(cls, raw: int) -> Flags:
        return cls(
            temp=bool(raw & FLAG_TEMP),
            hum=bool(raw & FLAG_HUM),
            mq2=bool(raw & FLAG_MQ2),
            water=bool(raw & FLAG_WATER),
            water_detected=bool(raw & FLAG_WATER_DETECTED),
            battery=bool(raw & FLAG_BATTERY),
            ack_requested=bool(raw & FLAG_ACK_REQ),
            simulated=bool(raw & FLAG_SIMULATED),
        )

    def as_bool_dict(self) -> dict[str, bool]:
        return {
            "temp": self.temp,
            "hum": self.hum,
            "mq2": self.mq2,
            "water": self.water,
            "water_detected": self.water_detected,
            "battery": self.battery,
            "ack_requested": self.ack_requested,
            "simulated": self.simulated,
        }


@dataclass
class TelemetryPacket:
    device_id: int
    seq: int
    flags: Flags = field(default_factory=Flags)
    temperature_c: float = 0.0
    humidity_pct: float = 0.0
    mq2_raw: int = 0
    water_raw: int = 0
    battery_mv: int = 0

    def to_ingest_payload(self, rssi: float | None, snr: float | None, gateway_id: str, gateway_time: str) -> dict:
        return {
            "device_id": self.device_id,
            "seq": self.seq,
            "flags": self.flags.as_bool_dict(),
            "temperature_c": self.temperature_c if self.flags.temp else None,
            "humidity_pct": self.humidity_pct if self.flags.hum else None,
            "mq2_raw": self.mq2_raw if self.flags.mq2 else None,
            "water_raw": self.water_raw if self.flags.water else None,
            "battery_mv": self.battery_mv if self.flags.battery else None,
            "rssi": rssi,
            "snr": snr,
            "gateway_id": gateway_id,
            "gateway_time": gateway_time,
        }


def encode_packet(packet: TelemetryPacket, key: bytes, seq: int | None = None) -> bytes:
    """Serialize + CRC-16 + HMAC-SHA256(truncated)."""
    dev = packet.device_id
    if not 1 <= dev <= 0xFFFFFFFF:
        raise PacketError("device_id out of range")
    n = packet.seq if seq is None else seq
    if not 0 <= n <= 0xFFFFFFFF:
        raise PacketError("seq out of range")

    temp_i = int(round(max(-327.68, min(327.67, packet.temperature_c)) * 100)) & 0xFFFF
    hum_i = int(round(max(0.0, min(655.35, packet.humidity_pct)) * 100)) & 0xFFFF
    mq2_i = packet.mq2_raw & 0xFFFF
    water_i = (packet.water_raw & 0xFFFF) if packet.flags.water else NA16
    batt_i = (packet.battery_mv & 0xFFFF) if packet.flags.battery else NA16

    body = struct.pack(
        _DATA_FMT,
        HDR_DATA,
        dev,
        n,
        packet.flags.to_int() & 0xFFFF,
        temp_i,
        hum_i,
        mq2_i,
        water_i,
        batt_i,
    )
    crc = crc16_ccitt_false(body)
    full = body + struct.pack("<H", crc)  # 24 bytes signed region
    mac = hmac_mod.new(key, full, hashlib.sha256).digest()[:8]
    return full + mac  # 32 bytes on the wire


def decode_packet(frame: bytes, key_for) -> TelemetryPacket:
    """Validate CRC then HMAC, then decode.

    `key_for(device_id)` must return that node's HMAC key or None (unknown node).
    Raises PacketError on any rejection.
    """
    if len(frame) != DATA_PACKET_LEN:
        raise PacketError(f"bad length {len(frame)}")
    hdr = struct.unpack_from("<H", frame, 0)[0]
    if hdr != HDR_DATA:
        raise PacketError(f"bad header {hdr:#06x}")

    crc_received = struct.unpack_from("<H", frame, 22)[0]
    if crc16_ccitt_false(frame[:22]) != crc_received:
        raise PacketError("crc mismatch")

    device_id, seq, flags_word = struct.unpack_from("<IIH", frame, 2)
    key = key_for(device_id)
    if key is None:
        raise PacketError("unknown device")
    mac_expected = hmac_mod.new(key, frame[:SIGNED_LEN], hashlib.sha256).digest()[:8]
    if not hmac_mod.compare_digest(frame[24:32], mac_expected):
        raise PacketError("hmac mismatch")

    (_, _, _, _, temp_i, hum_i, mq2_i, water_i, batt_i) = struct.unpack(_DATA_FMT, frame[:22])
    flags = Flags.from_int(flags_word)
    return TelemetryPacket(
        device_id=device_id,
        seq=seq,
        flags=flags,
        temperature_c=(temp_i - 0x10000 if temp_i & 0x8000 else temp_i) / 100.0 if flags.temp else 0.0,
        humidity_pct=(hum_i / 100.0 if flags.hum else 0.0),
        mq2_raw=mq2_i if flags.mq2 else 0,
        water_raw=(water_i if water_i != NA16 else 0) if flags.water else 0,
        battery_mv=(batt_i if batt_i != NA16 else 0) if flags.battery else 0,
    )


def encode_ack(device_id: int, seq: int) -> bytes:
    body = struct.pack(_ACK_FMT, HDR_ACK, device_id & 0xFFFFFFFF, seq & 0xFFFFFFFF)
    crc = crc16_ccitt_false(body)
    return body + struct.pack("<H", crc)  # 12 bytes


def decode_ack(frame: bytes) -> tuple[int, int]:
    if len(frame) != ACK_PACKET_LEN:
        raise PacketError("bad ack length")
    hdr, dev, seq = struct.unpack(_ACK_FMT, frame[:10])
    if hdr != HDR_ACK:
        raise PacketError("bad ack header")
    (crc,) = struct.unpack_from("<H", frame, 10)
    if crc16_ccitt_false(frame[:10]) != crc:
        raise PacketError("bad ack crc")
    return dev, seq

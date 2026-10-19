import pytest

from gateway_pkg.protocol import (
    ACK_PACKET_LEN,
    DATA_PACKET_LEN,
    HDR_ACK,
    HDR_DATA,
    Flags,
    PacketError,
    TelemetryPacket,
    crc16_ccitt_false,
    decode_ack,
    decode_packet,
    encode_ack,
    encode_packet,
)

KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
NODE_ID = 101


def make_packet(seq=1, key=KEY, **kw) -> bytes:
    packet = TelemetryPacket(
        device_id=NODE_ID,
        seq=seq,
        flags=Flags(temp=True, hum=True, mq2=True, water=True, battery=False),
        temperature_c=kw.get("temperature_c", 23.5),
        humidity_pct=50.0,
        mq2_raw=kw.get("mq2_raw", 300),
        water_raw=42,
        battery_mv=0,
    )
    return encode_packet(packet, key)


def test_crc_reference_vector():
    assert crc16_ccitt_false(b"123456789") == 0x29B1


def test_roundtrip_all_fields():
    frame = make_packet(seq=12345, temperature_c=-4.25)
    packet = decode_packet(frame, lambda d: KEY)
    assert packet.device_id == NODE_ID
    assert packet.seq == 12345
    assert packet.flags.temp and packet.flags.hum and packet.flags.mq2 and packet.flags.water
    assert packet.temperature_c == pytest.approx(-4.25)
    assert packet.humidity_pct == pytest.approx(50.0)
    assert packet.mq2_raw == 300
    assert packet.water_raw == 42
    assert packet.battery_mv == 0
    assert not packet.flags.battery


def test_frame_length_and_header():
    frame = make_packet()
    assert len(frame) == DATA_PACKET_LEN == 32
    assert frame[0] == 0xE5
    assert frame[1] == 0x11
    ack = encode_ack(NODE_ID, 7)
    assert len(ack) == ACK_PACKET_LEN == 12
    assert ack[0] == 0xE5
    assert ack[1] == 0x21
    assert decode_ack(ack) == (NODE_ID, 7)


def test_simulated_flag_roundtrip():
    packet = TelemetryPacket(
        device_id=NODE_ID, seq=1, flags=Flags(temp=True, simulated=True), temperature_c=20.0
    )
    frame = encode_packet(packet, KEY)
    decoded = decode_packet(frame, lambda d: KEY)
    assert decoded.flags.simulated is True


def test_tampered_crc_rejected():
    frame = bytearray(make_packet())
    frame[22] ^= 0xFF  # corrupt crc field itself
    with pytest.raises(PacketError, match="crc"):
        decode_packet(bytes(frame), lambda d: KEY)


def test_tampered_payload_rejected():
    frame = bytearray(make_packet())
    frame[12] ^= 0x01  # flip temperature bit
    with pytest.raises(PacketError, match="crc"):
        decode_packet(bytes(frame), lambda d: KEY)


def test_wrong_key_rejected():
    frame = make_packet()
    wrong_key = bytes.fromhex("deadbeef" * 4)
    with pytest.raises(PacketError, match="hmac"):
        decode_packet(frame, lambda d: wrong_key)


def test_unknown_device_rejected():
    frame = make_packet()
    with pytest.raises(PacketError, match="unknown device"):
        decode_packet(frame, lambda d: None)


def test_bad_length_rejected():
    with pytest.raises(PacketError, match="bad length"):
        decode_packet(b"\x01" * 31, lambda d: KEY)


def test_ack_tamper_rejected():
    ack = bytearray(encode_ack(NODE_ID, 5))
    ack[2] ^= 0xFF
    with pytest.raises(PacketError, match="crc"):
        decode_ack(bytes(ack))


def test_seq_boundaries():
    packet = TelemetryPacket(device_id=NODE_ID, seq=0, flags=Flags(temp=True))
    frame = encode_packet(packet, KEY)
    assert decode_packet(frame, lambda d: KEY).seq == 0
    packet.seq = 0xFFFFFFFF
    frame = encode_packet(packet, KEY)
    assert decode_packet(frame, lambda d: KEY).seq == 0xFFFFFFFF
    with pytest.raises(PacketError):
        encode_packet(TelemetryPacket(device_id=NODE_ID, seq=1 << 32, flags=Flags()), KEY)

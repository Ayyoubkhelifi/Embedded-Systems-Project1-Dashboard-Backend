import pytest

from gateway_pkg.config import GatewaySettings
from gateway_pkg.radio import SimulatedRadio, build_radio

KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
NODE_ID = 101


class SimSettings:
    simulate = True
    simulate_device_ids = f"{NODE_ID},102"
    simulate_interval_seconds = 0.001
    simulate_fault_rate = 0.0
    simulate_water_rate = 0.0
    node_key_map = {NODE_ID: KEY, 102: bytes.fromhex("ddccbbaa" * 4)}
    lora_frequency_mhz = 868.1
    lora_spreading_factor = 7
    lora_bandwidth_khz = 125
    lora_coding_rate = 5
    lora_tx_power_dbm = 14
    lora_spi_bus = 0
    lora_spi_cs = 0
    lora_dio0_gpio = 17
    lora_rst_gpio = 22


def test_build_radio_simulator():
    radio = build_radio(SimSettings())
    assert isinstance(radio, SimulatedRadio)
    radio.close()


def test_simulator_produces_valid_frames():
    radio = SimulatedRadio(
        device_ids=[NODE_ID],
        key_for=lambda d: KEY,
        interval_seconds=0.0,
        fault_rate=0.0,
        water_rate=0.0,
        corrupt_rate=0.0,
    )
    got = radio.recv(timeout=1.0)
    assert got is not None
    frame, rssi, snr = got
    assert len(frame) == 32
    from gateway_pkg.protocol import decode_packet

    packet = decode_packet(frame, lambda d: KEY)
    assert packet.device_id == NODE_ID
    assert packet.flags.simulated is True
    radio.close()


def test_simulator_seq_increases():
    radio = SimulatedRadio(
        device_ids=[NODE_ID],
        key_for=lambda d: KEY,
        interval_seconds=0.0,
        corrupt_rate=0.0,
    )
    frames = [radio.recv(timeout=1.0)[0] for _ in range(4)]
    from gateway_pkg.protocol import decode_packet

    seqs = [decode_packet(f, lambda d: KEY).seq for f in frames]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == 4
    radio.close()


def test_simulator_without_keys_raises_on_compose():
    radio = SimulatedRadio(device_ids=[NODE_ID], key_for=lambda d: None, interval_seconds=0.0)
    with pytest.raises(KeyError):
        radio.recv(timeout=1.0)
    radio.close()

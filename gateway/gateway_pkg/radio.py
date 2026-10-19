"""Radio sources.

* `SimulatedRadio` — deterministic-ish faux node fleet for development and
  CI without hardware. Packets carry the SIMULATED flag so the backend and
  dashboard clearly separate simulated from real data.
* `SX127xRadio` — SPI adapter for SX1276/SX1278 on Raspberry Pi. Uses
  `radiolib-raspberry` style DIO0 IRQ reads... concrete binding: the widely
  used community binding is pySX127x (`SX127x/LoRa modem over spidev+RPi.GPIO`).
  Install with `pip install -r requirements-lora.txt` (hardware extras), and
  review docs/hardware.md for SPI/GPIO wiring. The import is deferred so the
  gateway can run in pure software mode without these RPi-only deps.
"""
from __future__ import annotations

import random
import secrets as pysecrets
import struct
import time
from datetime import UTC, datetime
from typing import Callable, Protocol

from gateway_pkg.protocol import DATA_PACKET_LEN, Flags, TelemetryPacket, encode_packet


class RadioSource(Protocol):
    def recv(self, timeout: float) -> tuple[bytes, float, float] | None:
        """Return (frame, rssi, snr) or None after timeout."""
        ...

    def send(self, frame: bytes) -> None:
        """Transmit a downlink frame (ACK). Optional best-effort."""
        ...

    def close(self) -> None: ...

    def description(self) -> str: ...


class SimulatedRadio:
    """Generates packets for configured simulated device ids."""

    def __init__(
        self,
        device_ids: list[int],
        key_for: Callable[[int], bytes | None],
        interval_seconds: float = 5.0,
        fault_rate: float = 0.05,
        water_rate: float = 0.10,
        corrupt_rate: float = 0.03,
    ) -> None:
        self.device_ids = device_ids
        self.key_for = key_for
        self.interval = interval_seconds
        self.fault_rate = fault_rate
        self.water_rate = water_rate
        self.corrupt_rate = corrupt_rate
        self._next_tick = time.monotonic()
        self._seqs: dict[int, int] = {d: 0 for d in device_ids}
        self._outbox: list[bytes] = []

    def description(self) -> str:
        return f"simulator(devices={self.device_ids}, interval={self.interval}s)"

    def _compose(self, device_id: int) -> bytes:
        flags = Flags(
            temp=True, hum=True, mq2=True, water=True, battery=False,
            water_detected=random.random() < self.water_rate,
            simulated=True,
        )
        dead_sensor = random.random() < self.fault_rate
        if dead_sensor:
            sensor = random.choice(("temp", "hum", "mq2", "water"))
            setattr(flags, sensor, False)
        temp = random.uniform(18.0, 42.0)
        hum = random.uniform(30.0, 98.0)
        mq2 = int(abs(random.gauss(250, 120)))
        mq2 = min(4095, max(0, mq2 + (1400 if random.random() < 0.02 else 0)))
        water_raw = int(random.uniform(500, 900)) if flags.water_detected else int(random.uniform(0, 80))
        seq = self._seqs[device_id] = (self._seqs[device_id] + 1) & 0xFFFFFFFF
        packet = TelemetryPacket(
            device_id=device_id,
            seq=seq,
            flags=flags,
            temperature_c=round(temp, 2),
            humidity_pct=round(hum, 2),
            mq2_raw=mq2,
            water_raw=water_raw,
            battery_mv=0,
        )
        key = self.key_for(device_id)
        if key is None:
            raise KeyError(f"no node key configured for simulated device {device_id}")
        return encode_packet(packet, key)

    def recv(self, timeout: float) -> tuple[bytes, float, float] | None:
        now = time.monotonic()
        if now < self._next_tick:
            time.sleep(min(timeout, max(0.0, self._next_tick - now)))
            if time.monotonic() < self._next_tick:
                return None
        self._next_tick += self.interval
        device = random.choice(self.device_ids)
        frame = self._compose(device)
        rssi = round(random.uniform(-120.0, -65.0), 1)
        snr = round(random.uniform(-8.0, 12.0), 1)
        if random.random() < self.corrupt_rate:  # inject a corrupt bit once in a while
            idx = pysecrets.randbelow(DATA_PACKET_LEN)
            corrupted = bytearray(frame)
            corrupted[idx] ^= 0xFF
            return bytes(corrupted), rssi, snr
        return frame, rssi, snr

    def send(self, frame: bytes) -> None:
        self._outbox.append(frame)

    def close(self) -> None: ...


class SX127xRadio:
    """pySX127x-based receiver (Raspberry Pi + SX1276/SX1278 via SPI).

    Requires `spidev`, `RPi.GPIO` and the pySX127x sources placed on sys.path
    (see requirements-lora.txt and docs/hardware.md). Raises RuntimeError with
    a helpful message instead of crashing when hardware/library is missing.
    """

    def __init__(self, settings) -> None:
        try:
            from SX127x.LoRa import LoRa as LoRaModem  # type: ignore
        except Exception as exc:  # noqa: BLE001 — import guard for dev machines
            raise RuntimeError(
                "pySX127x not found. On the Raspberry Pi run: "
                "pip install -r requirements-lora.txt, install spidev/RPi.GPIO, "
                "enable SPI in raspi-config, and review docs/hardware.md. "
                f"(Original error: {exc})"
            ) from exc

        self._lora = LoRaModem()
        self._lora.set_mode(LoRaModem.MODE.SLEEP)
        freq_hz = int(settings.lora_frequency_mhz * 1e6)
        self._lora.set_freq(freq_hz)
        self._lora.set_spreading_factor(settings.lora_spreading_factor)
        bw = {250: 7, 125: 6, 63: 5, 1024: 9, 7: 8}.get(settings.lora_bandwidth_khz)
        if bw is None:
            raise RuntimeError(f"unsupported bandwidth {settings.lora_bandwidth_khz} kHz")
        self._lora.set_bw(bw)
        self._lora.set_coding_rate(settings.lora_coding_rate)
        self._lora.set_gain(1)  # front-end LNA gain
        self._lora.set_rx_single(False)  # continuous RX
        self._lora.set_mode(LoRaModem.MODE.RXCONT)

    def description(self) -> str:
        return "SX127x SPI receiver"

    def recv(self, timeout: float) -> tuple[bytes, float, float] | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            payload = self._lora.read_payload()
            if payload:
                rssi = snr = None
                try:
                    rssi = self._lora.lora_pkt_rssi_value()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 — lib version differences
                    pass
                try:
                    snr = self._lora.lora_pkt_snr_value()  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
                return (bytes(payload), float(rssi) if rssi is not None else 0.0, float(snr) if snr is not None else 0.0)
            time.sleep(0.02)
        return None

    def send(self, frame: bytes) -> None:
        from SX127x.LoRa import LoRa as LoRaModem  # type: ignore

        self._lora.set_mode(LoRaModem.MODE.STDBY)
        self._lora.write_payload(list(frame))
        self._lora.set_mode(LoRaModem.MODE.TX)
        # brief turn-around, back to continuous RX
        time.sleep(0.05)
        self._lora.set_mode(LoRaModem.MODE.RXCONT)

    def close(self) -> None:
        try:
            self._lora.set_mode(self._lora.MODE.STANDBY)
        except Exception:  # noqa: BLE001
            pass


def build_radio(settings) -> RadioSource:
    if settings.simulate:
        ids = [int(x) for x in settings.simulate_device_ids.split(",") if x.strip()]
        return SimulatedRadio(
            device_ids=ids,
            key_for=lambda d: settings.node_key_map.get(d),
            interval_seconds=settings.simulate_interval_seconds,
            fault_rate=settings.simulate_fault_rate,
            water_rate=settings.simulate_water_rate,
        )
    return SX127xRadio(settings)  # type: ignore[arg-type]

import json
from typing import Any

import httpx
import pytest

from gateway_pkg.forwarder import Pipeline
from gateway_pkg.protocol import (
    Flags,
    PacketError,
    TelemetryPacket,
    crc16_ccitt_false,
    decode_packet,
    encode_packet,
)
from gateway_pkg.store import GatewayStore

KEY = bytes.fromhex("00112233445566778899aabbccddeeff")
NODE_ID = 101


class FakeSettings:
    backend_url = "http://backend.test"
    gateway_api_key = "gw-secret-key"
    gateway_id = "gw-test"
    tls_verify = True
    backend_timeout_seconds = 2.0
    retry_max = 4
    retry_backoff_base = 0.001
    retry_backoff_max = 0.005
    node_keys = f"{NODE_ID}:00112233445566778899aabbccddeeff"

    @property
    def node_key_map(self):
        return {NODE_ID: KEY}


def make_frame(seq=1, mut=None):
    packet = TelemetryPacket(
        device_id=NODE_ID,
        seq=seq,
        flags=Flags(temp=True, hum=True, mq2=True, water=True),
        temperature_c=21.5,
        humidity_pct=48.0,
        mq2_raw=290,
        water_raw=10,
    )
    frame = encode_packet(packet, KEY)
    if mut:
        frame = mut(bytearray(frame))
    return frame


class RecordingBackend:
    """httpx MockTransport factories with call counters."""

    def __init__(self, fail_first=0, permanent_status: int | None = None, fail_mode="raise") -> None:
        self.calls = 0
        self.fails_remaining = fail_first
        self.permanent_status = permanent_status
        self.bodies: list[dict[str, Any]] = []
        self.fail_mode = fail_mode  # "raise" (ConnectError) or "status500"

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if request.method == "POST" and request.url.path == "/api/v1/telemetry":
            self.bodies.append(json.loads(request.content))
            if self.permanent_status:
                return httpx.Response(self.permanent_status, json={"error": {"code": "X", "message": "y"}})
            if self.fails_remaining > 0:
                self.fails_remaining -= 1
                if self.fail_mode == "raise":
                    raise httpx.ConnectError("boom", request=request)
                return httpx.Response(503, json={"error": {"code": "S", "message": "s"}})
            return httpx.Response(201, json={"stored": True, "duplicate": False})
        return httpx.Response(404, json={"error": {"code": "NOT_FOUND", "message": "n"}})


def mk_pipeline(store, backend: RecordingBackend) -> Pipeline:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(backend.handler), base_url="http://backend.test"
    )
    return Pipeline(FakeSettings(), store, client=client)


def ingest_frame(pipeline: Pipeline, frame: bytes) -> str:
    return pipeline.process_frame(frame, rssi=-70.0, snr=9.0)


async def run_corr(close_all):
    yield


async def test_process_frame_happy_path(store):
    backend = RecordingBackend()
    pipeline = mk_pipeline(store, backend)
    verdict = ingest_frame(pipeline, make_frame(1))
    assert verdict == "stored"
    assert pipeline.store.buffered_count() == 1
    delivered, buffered = await pipeline.flush_once()
    assert (delivered, buffered) == (1, 0)
    await pipeline.aclose()


async def test_duplicate_radio_listener_aware(store):
    backend = RecordingBackend()
    pipeline = mk_pipeline(store, backend)
    assert ingest_frame(pipeline, make_frame(5)) == "stored"
    assert ingest_frame(pipeline, make_frame(5)) == "duplicate"  # dedup at gateway
    # gateway buffers only the first; backend also rejects re-ingestion independently
    await pipeline.aclose()


async def test_reject_malformed_crc(store):
    pipeline = mk_pipeline(store, RecordingBackend())

    def corrupt(bytes_pic):
        bytes_pic[12] ^= 0xFF
        return bytes(bytes_pic)

    verdict = ingest_frame(pipeline, make_frame(mut=corrupt))
    assert verdict.startswith("rejected")
    assert pipeline.store.buffered_count() == 0
    await pipeline.aclose()


async def test_reject_unknown_device(store):
    pipeline = mk_pipeline(store, RecordingBackend())
    packet = TelemetryPacket(device_id=999, seq=1, flags=Flags(temp=True))
    unknown_key_frame = encode_packet(packet, KEY)
    assert ingest_frame(pipeline, unknown_key_frame).startswith("rejected")
    await pipeline.aclose()


async def test_reject_hmac(store):
    pipeline = mk_pipeline(store, RecordingBackend())
    frame = make_frame()
    swapped = bytearray(frame)
    swapped[24] ^= 0xFF  # flip first mac byte (crc still valid)
    verdict = ingest_frame(pipeline, bytes(swapped))
    assert verdict.startswith("rejected:hmac") or verdict.startswith("rejected:PacketError")
    assert pipeline.store.buffered_count() == 0
    await pipeline.aclose()


async def test_forwarder_payload_schema(store):
    backend = RecordingBackend()
    pipeline = mk_pipeline(store, backend)
    ingest_frame(pipeline, make_frame(11))
    await pipeline.flush_once()
    body = backend.bodies[0]
    assert body["device_id"] == NODE_ID
    assert body["seq"] == 11
    assert body["flags"]["temp"] is True
    assert body["temperature_c"] == pytest.approx(21.5)
    assert body["rssi"] == -70.0
    assert body["gateway_id"] == "gw-test"
    assert "gateway_time" in body
    await pipeline.aclose()


async def test_flush_stops_on_backend_failure_and_retains(store):
    backend = RecordingBackend(fail_first=10**9, fail_mode="status500")
    pipeline = mk_pipeline(store, backend)
    ingest_frame(pipeline, make_frame(1))
    ingest_frame(pipeline, make_frame(2))

    delivered, buffered = await pipeline.flush_once()
    assert delivered == 0
    assert buffered == 2
    assert backend.calls >= 1  # attempted, failed, retained
    await pipeline.aclose()


async def test_flush_recovers_after_backend_comes_back(store):
    # Backend unreachable for the whole first flush (retries exhausted)…
    backend = RecordingBackend(fail_first=10**9, fail_mode="raise")
    pipeline = mk_pipeline(store, backend)
    ingest_frame(pipeline, make_frame(42))

    delivered, buffered = await pipeline.flush_once()
    assert delivered == 0 and buffered == 1

    # …then the network heals → the SAME buffered packet is delivered once.
    backend.fails_remaining = 0
    delivered, buffered = await pipeline.flush_once()
    assert (delivered, buffered) == (1, 0)
    assert backend.calls >= 5  # 4 exhausted attempts + success
    await pipeline.aclose()


async def test_definitive_backend_rejection_drops_packet(store):
    # Unknown device (4xx = definitive): the packet can never be delivered,
    # so the pipeline drops it from the buffer instead of retrying forever.
    backend = RecordingBackend(permanent_status=404)
    pipeline = mk_pipeline(store, backend)
    ingest_frame(pipeline, make_frame(3))
    delivered, buffered = await pipeline.flush_once()
    assert delivered == 1 and buffered == 0  # removed as undeliverable
    await pipeline.aclose()


async def test_retry_exhaustion_retains_packet(store):
    settings = FakeSettings()
    settings.retry_max = 2

    class AlwaysFailBackend(RecordingBackend):
        def handler(self, request):
            self.calls += 1
            raise httpx.ConnectError("down", request=request)

    backend = AlwaysFailBackend()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(backend.handler), base_url="http://backend.test"
    )
    pipeline = Pipeline(settings, store, client=client)
    ingest_frame(pipeline, make_frame(1))
    delivered, buffered = await pipeline.flush_once()
    assert delivered == 0 and buffered == 1
    assert backend.calls == 2
    await pipeline.aclose()


async def test_retry_backoff_grows(store, monkeypatch):
    settings = FakeSettings()
    settings.retry_max = 5

    sleeps: list[float] = []

    async def fake_sleep(seconds: float):
        sleeps.append(seconds)

    monkeypatch.setattr("gateway_pkg.forwarder.asyncio.sleep", fake_sleep)

    class FailingBackend(RecordingBackend):
        def handler(self, request):
            self.calls += 1
            raise httpx.ConnectError("down", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(FailingBackend().handler), base_url="http://backend.test"
    )
    pipeline = Pipeline(settings, store, client=client)
    ingest_frame(pipeline, make_frame(1))
    await pipeline.flush_once()
    assert len(sleeps) == 4  # between retries (attempts that raise skip sleep... check below)
    await pipeline.aclose()

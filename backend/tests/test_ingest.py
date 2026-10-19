from datetime import UTC, datetime, timedelta

from tests.conftest import (
    TEST_GATEWAY_KEY,
    auth_headers,
    gateway_headers,
    login_and_get_token,
    current_sessionmaker,
)
from app.models import Device

API = "/api/v1"


def payload(**overrides):
    base = {
        "device_id": 42,
        "seq": 100,
        "flags": {"temp": True, "hum": True, "mq2": True, "water": True},
        "temperature_c": 22.5,
        "humidity_pct": 55.1,
        "mq2_raw": 210,
        "water_raw": 12,
        "rssi": -82.0,
        "snr": 9.5,
        "gateway_id": "gw-1",
        "gateway_time": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return base


def flagless(**overrides):
    base = {
        "device_id": 42,
        "seq": 100,
        "flags": {},
        "rssi": -80.0,
        "gateway_time": datetime.now(UTC).isoformat(),
    }
    base.update(overrides)
    return base


async def _seed_device(device_id=42, name="Node 42"):
    sm = current_sessionmaker()
    async with sm() as session:
        session.add(Device(device_id=device_id, name=name))
        await session.commit()



def _strictly_invalid_bodies():
    """Full request bodies that must each be rejected with 422."""
    return [
        ({}, "empty body"),
        ({"seq": 1}, "missing device_id"),
        ({"device_id": 42}, "missing seq"),
        ({"device_id": 0, "seq": 1}, "zero device id"),
        ({"device_id": 42, "seq": -1}, "negative seq"),
        (
            {"device_id": 42, "seq": 1, "flags": {"temp": True}, "temperature_c": 999.0},
            "impossible temperature",
        ),
    ]


async def test_malformed_payloads(client, test_db):
    await _seed_device()
    h = gateway_headers()
    for body, name in _strictly_invalid_bodies():
        resp = await client.post(f"{API}/telemetry", json=body, headers=h)
        assert resp.status_code == 422, f"{name}: {resp.status_code} {resp.text}"
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_extra_fields_rejected(client, test_db):
    await _seed_device()
    p = payload()
    p["surprise_extra_key"] = 1
    resp = await client.post(f"{API}/telemetry", json=p, headers=gateway_headers())
    assert resp.status_code == 422


async def test_value_bounds_reject_impossible_readings(client, test_db):
    await _seed_device()
    resp = await client.post(
        f"{API}/telemetry",
        json=payload(temperature_c=999.0),
        headers=gateway_headers(),
    )
    assert resp.status_code == 422

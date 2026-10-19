from datetime import UTC, datetime, timedelta

from datetime import UTC, datetime, timedelta

from tests.conftest import auth_headers, gateway_headers, login_and_get_token, current_sessionmaker
from app.models import Device, SensorReading

API = "/api/v1"


async def seed_readings():
    sm = current_sessionmaker()
    now = datetime.now(UTC)
    async with sm() as session:
        d1 = Device(device_id=10, name="D10")
        d2 = Device(device_id=11, name="D11")
        session.add_all([d1, d2])
        await session.flush()
        readings = []
        for i in range(6):
            readings.append(
                SensorReading(
                    device_id_ref=d1.id,
                    packet_seq=i,
                    temperature_c=20.0 + i,
                    temp_valid=True,
                    gateway_time=now - timedelta(hours=5 - i),
                )
            )
        readings.append(
            SensorReading(device_id_ref=d2.id, packet_seq=1, temperature_c=30.0, temp_valid=True, gateway_time=now)
        )
        session.add_all(readings)
        await session.commit()
    return now


async def test_history_default_window(client, test_db):
    await seed_readings()
    token = await login_and_get_token(client)
    resp = await client.get(f"{API}/telemetry/history", headers=auth_headers(token))
    assert resp.status_code == 200
    items = resp.json()
    # d10 has 6 readings (newest within default 24h window), d2 has 1 recent row.
    assert len(items) == 7
    assert all(isinstance(r, dict) for r in items)


async def test_history_device_filter(client, test_db):
    await seed_readings()
    token = await login_and_get_token(client)
    resp = await client.get(
        f"{API}/telemetry/history?device_id=10", headers=auth_headers(token)
    )
    assert all(r["device_id"] == 10 for r in resp.json())
    assert len(resp.json()) == 6


def zulu(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


async def test_history_time_range(client, test_db):
    now = await seed_readings()
    token = await login_and_get_token(client)
    # readings exist at now-5h .. now; window covers now-6h .. now-2.5h (drift-safe)
    start = zulu(now - timedelta(hours=6))
    end = zulu(now - timedelta(hours=2, minutes=30))
    resp = await client.get(
        f"{API}/telemetry/history?start={start}&end={end}", headers=auth_headers(token)
    )
    resp.raise_for_status()
    temps = [r["temperature_c"] for r in resp.json()]
    assert temps == [22.0, 21.0, 20.0]


async def test_history_invalid_range(client, test_db):
    token = await login_and_get_token(client)
    resp = await client.get(
        f"{API}/telemetry/history?start=2026-01-02T00:00:00Z&end=2026-01-01T00:00:00Z",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "INVALID_TIME_RANGE"


async def test_history_range_too_large(client, test_db):
    token = await login_and_get_token(client)
    resp = await client.get(
        f"{API}/telemetry/history?start=2020-01-01T00:00:00Z",
        headers=auth_headers(token),
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "TIME_RANGE_TOO_LARGE"


async def test_history_pagination(client, test_db):
    await seed_readings()
    token = await login_and_get_token(client)
    page = await client.get(
        f"{API}/telemetry/history?device_id=10&limit=2&offset=0&order=asc",
        headers=auth_headers(token),
    )
    temps = [r["temperature_c"] for r in page.json()]
    assert temps == [20.0, 21.0]
    page2 = await client.get(
        f"{API}/telemetry/history?device_id=10&limit=2&offset=2&order=asc",
        headers=auth_headers(token),
    )
    assert [r["temperature_c"] for r in page2.json()] == [22.0, 23.0]


async def test_latest(client, test_db):
    await seed_readings()
    token = await login_and_get_token(client)
    resp = await client.get(f"{API}/telemetry/latest?limit=3", headers=auth_headers(token))
    items = resp.json()
    assert len(items) == 3
    assert items[0]["device_id"] == 11  # most recent overall

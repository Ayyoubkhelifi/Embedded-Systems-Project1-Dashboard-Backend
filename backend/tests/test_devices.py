from datetime import UTC, datetime, timedelta

from tests.conftest import auth_headers, login_and_get_token, current_sessionmaker
from app.models import Device, SensorReading

API = "/api/v1"


async def test_register_list_detail(client, test_db):
    token = await login_and_get_token(client)
    h = auth_headers(token)

    created = await client.post(
        f"{API}/devices", headers=h, json={"device_id": 7, "name": "CLI-7", "location": "attic"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["device_id"] == 7

    dupe = await client.post(
        f"{API}/devices", headers=h, json={"device_id": 7, "name": "Again"}
    )
    assert dupe.status_code == 409
    assert dupe.json()["error"]["code"] == "DEVICE_ID_TAKEN"

    listed = await client.get(f"{API}/devices", headers=h)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    assert any(d["device_id"] == 7 for d in listed.json()["items"])

    detail = await client.get(f"{API}/devices/7", headers=h)
    assert detail.status_code == 200
    assert detail.json()["name"] == "CLI-7"

    missing = await client.get(f"{API}/devices/999", headers=h)
    assert missing.status_code == 404


async def test_register_requires_admin(client, test_db):
    from app.core.security import hash_password
    from app.models import User

    sm = current_sessionmaker()
    async with sm() as session:
        session.add(
            User(username="v3@test.local", password_hash=hash_password("viewpass1234"), role="viewer")
        )
        await session.commit()
    vtoken = await login_and_get_token(client, "v3@test.local", "viewpass1234")
    resp = await client.post(
        f"{API}/devices", headers=auth_headers(vtoken), json={"device_id": 8, "name": "x"}
    )
    assert resp.status_code == 403


async def test_device_latest_reading_included(client, test_db):
    token = await login_and_get_token(client)
    h = auth_headers(token)
    await client.post(f"{API}/devices", headers=h, json={"device_id": 5, "name": "N5"})

    from tests.conftest import gateway_headers

    rng = gateway_headers()
    await client.post(
        f"{API}/telemetry",
        json={
            "device_id": 5,
            "seq": 1,
            "flags": {"temp": True},
            "temperature_c": 26.2,
            "rssi": -70,
            "snr": 8.0,
        },
        headers=rng,
    )

    listed = await client.get(f"{API}/devices", headers=h)
    device_row = next(d for d in listed.json()["items"] if d["device_id"] == 5)
    assert device_row["status"] == "online"
    assert device_row["last_rssi"] == -70
    assert device_row["latest_reading"]["temperature_c"] == 26.2

    detail = await client.get(f"{API}/devices/5", headers=h)
    assert detail.json()["latest_reading"]["packet_seq"] == 1


async def test_online_offline_filtering(client, test_db):
    from datetime import datetime, timedelta

    sm = current_sessionmaker()
    async with sm() as session:
        session.add_all(
            [
                Device(device_id=1, name="Online", status="online", last_seen_at=datetime.now(UTC)),
                Device(device_id=2, name="Offline", status="offline"),
            ]
        )
        await session.commit()

    token = await login_and_get_token(client)
    online = await client.get(f"{API}/devices?status=online", headers=auth_headers(token))
    assert {d["device_id"] for d in online.json()["items"]} == {1}
    offline = await client.get(f"{API}/devices?status=offline", headers=auth_headers(token))
    assert {d["device_id"] for d in offline.json()["items"]} == {2}

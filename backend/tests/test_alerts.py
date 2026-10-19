from datetime import UTC, datetime, timedelta

from tests.conftest import (
    auth_headers,
    gateway_headers,
    login_and_get_token,
    current_sessionmaker,
)
from app.models import Device

API = "/api/v1"


def payload(seq, **kwargs):
    base = {
        "device_id": 42,
        "seq": seq,
        "flags": {"temp": True, "hum": True, "mq2": True, "water": True},
        "temperature_c": kwargs.get("temperature_c", 25.0),
        "humidity_pct": kwargs.get("humidity_pct", 50.0),
        "mq2_raw": kwargs.get("mq2_raw", 100),
        "water_raw": kwargs.get("water_raw", 0),
        "gateway_time": kwargs.get("gateway_time", datetime.now(UTC).isoformat()),
    }
    return base


async def seed_device(device_id=42):
    sm = current_sessionmaker()
    async with sm() as session:
        session.add(Device(device_id=device_id, name="Alert node"))
        await session.commit()


async def _get_open_alerts(client, token, device_id=42):
    resp = await client.get(
        f"{API}/alerts?device_id={device_id}&status=open", headers=auth_headers(token)
    )
    return resp.json()


async def test_temp_alert_requires_sustained_readings(client, test_db):
    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()

    r1 = await client.post(f"{API}/telemetry", json=payload(1, temperature_c=40.0), headers=h)
    assert r1.status_code == 201
    alerts = (await _get_open_alerts(client, token))["items"]
    assert alerts == []  # sustained window = 2, first spike alone must not fire

    r2 = await client.post(f"{API}/telemetry", json=payload(2, temperature_c=41.0), headers=h)
    assert r2.status_code == 201
    alerts = (await _get_open_alerts(client, token))["items"]
    assert len(alerts) == 1
    assert alerts[0]["rule_key"] == "temp_high"
    assert alerts[0]["severity"] == "critical"


async def test_no_duplicate_alert_while_condition_active(client, test_db):
    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()
    for seq in (1, 2, 3, 4):
        await client.post(
            f"{API}/telemetry", json=payload(seq, temperature_c=38.0 + seq), headers=h
        )
    alerts = (await _get_open_alerts(client, token))["items"]
    assert len(alerts) == 1  # one alert, still active after 4 hot readings


async def test_alert_closes_after_hysteresis(client, test_db):
    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()
    threshold = 35.0
    hysteresis = 2.0
    # fire
    await client.post(f"{API}/telemetry", json=payload(1, temperature_c=36.5), headers=h)
    await client.post(f"{API}/telemetry", json=payload(2, temperature_c=37.0), headers=h)
    opened = await client.get(f"{API}/alerts?status=open", headers=auth_headers(token))
    alerts = opened.json()["items"]
    assert len(alerts) == 1

    # inside hysteresis band (34.5 > 35-2): alert must remain open
    await client.post(f"{API}/telemetry", json=payload(3, temperature_c=34.5), headers=h)
    opened = await client.get(f"{API}/alerts?status=open", headers=auth_headers(token))
    open_alerts = opened.json()["items"]
    assert len(open_alerts) == 1

    # fully cleared: two consecutive readings below threshold - hysteresis
    await client.post(f"{API}/telemetry", json=payload(4, temperature_c=30.0), headers=h)
    await client.post(f"{API}/telemetry", json=payload(5, temperature_c=29.0), headers=h)
    opened = await client.get(f"{API}/alerts?status=open", headers=auth_headers(token))
    open_alerts = opened.json()["items"]
    assert open_alerts == []
    closed_resp = await client.get(f"{API}/alerts?status=closed", headers=auth_headers(token))
    closed = closed_resp.json()["items"]
    assert any(a["rule_key"] == "temp_high" for a in closed)


async def test_acknowledge_alert(client, test_db):
    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()
    await client.post(f"{API}/telemetry", json=payload(1, temperature_c=37.0), headers=h)
    await client.post(f"{API}/telemetry", json=payload(2, temperature_c=37.5), headers=h)

    open_alerts = (await _get_open_alerts(client, token))["items"]
    alert_id = open_alerts[0]["id"]
    acked = await client.patch(
        f"{API}/alerts/{alert_id}", headers=auth_headers(token), json={"status": "acknowledged"}
    )
    assert acked.status_code == 200
    assert acked.json()["status"] == "acknowledged"
    assert acked.json()["acknowledged_at"] is not None

    # acknowledging a closed alert -> 409
    closed_id = None
    all_resp = await client.get(f"{API}/alerts", headers=auth_headers(token))
    all_alerts = all_resp.json()["items"]
    for a in all_alerts:
        if a["status"] == "closed":
            closed_id = a["id"]
    if closed_id:
        resp = await client.patch(
            f"{API}/alerts/{closed_id}", headers=auth_headers(token), json={"status": "acknowledged"}
        )
        assert resp.status_code == 409


async def test_operator_can_ack_but_not_viewer(client, test_db):
    from app.core.security import hash_password
    from app.models import User

    sm = current_sessionmaker()
    async with sm() as session:
        session.add(
            User(
                username="view2@test.local",
                password_hash=hash_password("viewpass1234"),
                role="viewer",
            )
        )
        await session.commit()

    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()
    await client.post(f"{API}/telemetry", json=payload(1, temperature_c=37.0), headers=h)
    await client.post(f"{API}/telemetry", json=payload(2, temperature_c=37.5), headers=h)
    alert_id = (await _get_open_alerts(client, token))["items"][0]["id"]

    viewer_token = await login_and_get_token(client, "view2@test.local", "viewpass1234")
    resp = await client.patch(
        f"{API}/alerts/{alert_id}",
        headers=auth_headers(viewer_token),
        json={"status": "acknowledged"},
    )
    assert resp.status_code == 403


async def test_mq2_threshold_alert_preliminary_label(client, test_db):
    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()
    await client.post(f"{API}/telemetry", json=payload(1, mq2_raw=900), headers=h)
    await client.post(f"{API}/telemetry", json=payload(2, mq2_raw=950), headers=h)
    alerts = (await _get_open_alerts(client, token))["items"]
    mq2 = [a for a in alerts if a["rule_key"] == "mq2_threshold"]
    assert len(mq2) == 1
    assert "preliminary" in mq2[0]["description"].lower()
    assert "not a certified" in mq2[0]["description"].lower()


async def test_water_detection_alert(client, test_db):
    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()
    base = payload(1, water_raw=600)
    base["flags"] = dict(base["flags"], water_detected=True)
    r1 = await client.post(f"{API}/telemetry", json=base, headers=h)
    assert r1.status_code == 201, r1.text
    base2 = payload(2, water_raw=700)
    base2["flags"] = dict(base2["flags"], water_detected=True)
    r2 = await client.post(f"{API}/telemetry", json=base2, headers=h)
    assert r2.status_code == 201

    alerts = (await _get_open_alerts(client, token))["items"]
    assert any(a["rule_key"] == "water_detected" for a in alerts), alerts


async def test_sensor_malfunction_alert(client, test_db):
    await seed_device()
    token = await login_and_get_token(client)
    h = gateway_headers()
    # two consecutive readings with invalid temp flag
    bad1 = payload(1)
    bad1["flags"]["temp"] = False
    bad1["temperature_c"] = None
    bad2 = dict(bad1, seq=2)
    await client.post(f"{API}/telemetry", json=bad1, headers=h)
    await client.post(f"{API}/telemetry", json=bad2, headers=h)

    alerts = (await _get_open_alerts(client, token))["items"]
    malfunction = [a for a in alerts if a["rule_key"] == "sensor_malfunction"]
    assert len(malfunction) == 1
    assert "temperature (DHT11)" in malfunction[0]["description"]


async def test_device_offline_alert_flow(client, test_db):
    await seed_device()
    sm = current_sessionmaker()
    # go stale: backdate last_seen beyond freshness timeout
    async with sm() as session:
        from sqlalchemy import select

        device = (await session.execute(select(Device).where(Device.device_id == 42))).scalar_one()
        device.last_seen_at = datetime.now(UTC) - timedelta(seconds=3600)
        device.status = "online"
        await session.commit()

    offline_created, came_back = await _run_scan()
    assert offline_created, "offline alert should be raised"

    token = await login_and_get_token(client)
    opened = await client.get(f"{API}/alerts?status=open", headers=auth_headers(token))
    open_alerts = opened.json()["items"]
    off = [a for a in open_alerts if a["rule_key"] == "device_offline"]
    assert len(off) == 1

    # device reports again -> alert auto-closes, duplicate prevented
    fresh_resp = await client.post(
        f"{API}/telemetry", json=payload(9), headers=gateway_headers()
    )
    assert fresh_resp.status_code == 201
    opened = await client.get(f"{API}/alerts?status=open", headers=auth_headers(token))
    open_alerts = opened.json()["items"]
    assert not any(a["rule_key"] == "device_offline" for a in open_alerts)


async def _run_scan():
    from app.services.offline import check_device_freshness_once

    return await check_device_freshness_once()

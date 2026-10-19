"""WebSocket realtime tests (sync TestClient portal, single-loop DB access)."""
from starlette.testclient import TestClient

from app.main import app
from tests.conftest import TEST_ADMIN_PASS, TEST_ADMIN_USER, gateway_headers

API = "/api/v1"


def _payload(seq, device_id=42):
    from datetime import UTC, datetime

    return {
        "device_id": device_id,
        "seq": seq,
        "flags": {"temp": True},
        "temperature_c": 21.0 + seq,
        "gateway_time": datetime.now(UTC).isoformat(),
    }


def test_ws_rejects_bad_token():
    with TestClient(app) as tc:
        opened = False
        try:
            with tc.websocket_connect(f"{API}/ws/telemetry?token=not-a-token") as ws:
                opened = True
                ws.receive_text()
        except Exception:
            pass
        assert not opened, "connection must be closed on auth failure"


def test_ws_receives_telemetry_alert_events(test_db):
    with TestClient(app) as tc:  # runs lifespan (skips background tasks in testing)
        login = tc.post(
            f"{API}/auth/login",
            json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS},
        )
        token = login.json()["access_token"]
        assert login.status_code == 200

        reg = tc.post(
            f"{API}/devices",
            headers={"Authorization": f"Bearer {token}"},
            json={"device_id": 42, "name": "WS node"},
        )
        assert reg.status_code == 201, reg.text

        with tc.websocket_connect(f"{API}/ws/telemetry?token={token}") as ws:
            hello = ws.receive_json()
            assert hello["type"] == "hello"
            assert hello["data"]["user"] == TEST_ADMIN_USER

            ws.send_text("ping")
            assert '"pong"' in ws.receive_text()

            resp = tc.post(
                f"{API}/telemetry",
                json=_payload(1),
                headers=gateway_headers(),
            )
            assert resp.status_code == 201, resp.text

            event = ws.receive_json()
            assert event["type"] == "telemetry"
            assert event["data"]["device_id"] == 42
            assert event["data"]["temperature_c"] == 22.0

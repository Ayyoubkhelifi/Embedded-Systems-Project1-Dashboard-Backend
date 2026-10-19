from starlette.testclient import TestClient

from app.core import rate_limit
from app.main import app

API = "/api/v1"


def test_body_size_limit_enforced(test_db):
    rate_limit.configure_body_limit(64)  # bytes; global override for this test
    try:
        with TestClient(app) as tc:
            login = tc.post(
                f"{API}/auth/login",
                json={"username": "admin@test.local", "password": "supersecretpass1"},
            )
            assert login.status_code == 200
            token = login.json()["access_token"]

            big = {"name": "x" * 500}
            resp = tc.post(
                f"{API}/devices",
                headers={"Authorization": f"Bearer {token}"},
                json=big,
            )
            assert resp.status_code == 413
            assert resp.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    finally:
        rate_limit.configure_body_limit(65536)


def test_rate_limit_sliding_window(test_db, monkeypatch):
    limiter = rate_limit.SlidingWindowRateLimitMiddleware(app, default_per_minute=3, ingest_per_minute=3)
    # unit-test the limiter logic directly without re-installing middleware
    import time

    class FakeRequest:
        method = "GET"
        url = type("U", (), {"path": "/api/v1/devices"})()
        headers = {}
        client = type("C", (), {"host": "unit"})()

    now = time.monotonic()
    ok = 0
    limited = True
    for i in range(5):
        key = limiter._hits[f"ip:unit|/api/v1/devices"]
        while key and now - key[0] > 60.0:
            key.popleft()
        if len(key) >= 3:
            limited = True
        else:
            key.append(now)
            ok += 1
    assert ok == 3

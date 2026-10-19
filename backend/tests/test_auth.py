from tests.conftest import TEST_ADMIN_PASS, TEST_ADMIN_USER, auth_headers, login_and_get_token
from tests.conftest import gateway_headers as gw

API = "/api/v1"


async def test_health_ok(client):
    resp = await client.get(f"{API}/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "connected"


# ---- Authentication ----


async def test_login_wrong_password(client):
    resp = await client.post(
        f"{API}/auth/login", json={"username": TEST_ADMIN_USER, "password": "wrongpass123"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "BAD_CREDENTIALS"


async def test_login_unknown_user(client):
    resp = await client.post(
        f"{API}/auth/login", json={"username": "ghost@x.y", "password": "whatever-pass"}
    )
    assert resp.status_code == 401


async def test_me_requires_auth(client):
    resp = await client.get(f"{API}/auth/me")
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


async def test_login_sets_cookie_and_me(client):
    resp = await client.post(
        f"{API}/auth/login",
        json={"username": TEST_ADMIN_USER, "password": TEST_ADMIN_PASS},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
    assert "ess_session" in resp.cookies

    me = await client.get(f"{API}/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == TEST_ADMIN_USER


# ---- RBAC ----


async def test_viewer_cannot_register_device(client):
    from tests.conftest import TEST_GATEWAY_KEY, current_sessionmaker
    from app.core.security import hash_password
    from app.models import User

    sm = current_sessionmaker()
    async with sm() as session:
        session.add(
            User(
                username="viewer@test.local",
                password_hash=hash_password("viewerpass123"),
                role="viewer",
            )
        )
        await session.commit()

    viewer_token = await login_and_get_token(client, "viewer@test.local", "viewerpass123")
    resp = await client.post(
        f"{API}/devices",
        headers=auth_headers(viewer_token) | gw(),
        json={"device_id": 900, "name": "Nope"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


async def test_admin_can_create_and_delete_user(client):
    token = await login_and_get_token(client)
    h = auth_headers(token)
    created = await client.post(
        f"{API}/auth/users",
        headers=h,
        json={"username": "oper1@test.local", "password": "operpass1234", "role": "operator"},
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]

    listed = await client.get(f"{API}/auth/users", headers=h)
    assert listed.status_code == 200
    assert any(u["username"] == "oper1@test.local" for u in listed.json()["items"])

    patched = await client.patch(
        f"{API}/auth/users/{uid}", headers=h, json={"is_active": False}
    )
    assert patched.status_code == 200
    assert patched.json()["is_active"] is False

    deactivated_login = await client.post(
        f"{API}/auth/login",
        json={"username": "oper1@test.local", "password": "operpass1234"},
    )
    assert deactivated_login.status_code == 403

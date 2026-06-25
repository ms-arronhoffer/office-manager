import pytest
from tests.conftest import auth_headers


@pytest.mark.asyncio
async def test_login_success(client, admin_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "admin123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_invalid_password(client, admin_user):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "admin@test.com",
        "password": "wrong",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_user(client):
    resp = await client.post("/api/v1/auth/login", json={
        "email": "nobody@test.com",
        "password": "whatever",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client, admin_user):
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(admin_user))
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["role"] == "admin"

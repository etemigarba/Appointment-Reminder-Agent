"""C6: Google OAuth authorize/callback (FR-17) and worker sync cycle."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm_client import FakeLLMClient
from app.api.google_oauth import GoogleConfigError, _make_state, get_google_config
from app.main import create_app
from app.models.entities import Tenant


@pytest.fixture()
def client(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'oauth.db'}", llm_client=FakeLLMClient())
    with TestClient(app) as c:
        yield c


def _register(client, email="g@spa.example"):
    response = client.post(
        "/api/auth/register",
        json={"email": email, "password": "password123"},
    )
    return response.json()["access_token"]


def test_authorize_requires_config(monkeypatch, client):
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "APP_PUBLIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    token = _register(client)

    response = client.get("/api/google/authorize", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503


def test_authorize_returns_google_url_with_params(monkeypatch, client):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec-456")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.com")
    token = _register(client)

    response = client.get("/api/google/authorize", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    url = response.json()["authorize_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=cid-123" in url
    assert "redirect_uri=https%3A%2F%2Fapp.example.com%2Fapi%2Fgoogle%2Fcallback" in url
    assert "access_type=offline" in url
    assert "scope=" in url and "calendar.readonly" in url.replace("%2F", "/")


def test_callback_exchanges_code_and_stores_token(monkeypatch, client):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid-123")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec-456")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.com")

    token = _register(client)
    # resolve tenant id from /api/settings payload shape (email lookup via state instead):
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=client.app.state.engine, expire_on_commit=False)
    with factory() as session:
        tenant = session.scalars(select(Tenant)).one()
        tenant_id = tenant.id

    captured = {}

    def fake_exchange(code, client_id, client_secret, redirect_uri):
        captured.update(
            code=code, client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
        )
        return {"refresh_token": "rt-abc", "access_token": "at"}

    monkeypatch.setattr("app.api.google_oauth.exchange_code", fake_exchange)
    state = _make_state(tenant_id)

    response = client.get("/api/google/callback", params={"code": "auth-code", "state": state})

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured == {
        "code": "auth-code",
        "client_id": "cid-123",
        "client_secret": "sec-456",
        "redirect_uri": "https://app.example.com/api/google/callback",
    }
    with factory() as session:
        refreshed = session.get(Tenant, tenant_id)
        assert refreshed.google_refresh_token == "rt-abc"
        assert refreshed.google_calendar_id == "primary"


def test_callback_rejects_bad_state(client):
    response = client.get("/api/google/callback", params={"code": "c", "state": "garbage"})
    assert response.status_code == 400


def test_get_google_config_raises_without_env(monkeypatch):
    for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "APP_PUBLIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(GoogleConfigError):
        get_google_config()
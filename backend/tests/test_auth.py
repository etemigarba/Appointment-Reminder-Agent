"""Auth flows: register, login, guard enforcement, tenant isolation (C4/C5)."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agents.llm_client import FakeLLMClient
from app.main import create_app
from tests.conftest import make_appointment


@pytest.fixture()
def client(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'auth.db'}", llm_client=FakeLLMClient())
    with TestClient(app) as c:
        yield c


def _register(client, email="owner@spa.example", password="password123"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_returns_token(client):
    response = _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 20


def test_duplicate_email_conflict(client):
    assert _register(client).status_code == 201
    assert _register(client).status_code == 409


def test_short_password_rejected(client):
    response = _register(client, password="short")

    assert response.status_code == 422


def test_login_success_and_wrong_password(client):
    _register(client)

    good = client.post(
        "/api/auth/login", json={"email": "owner@spa.example", "password": "password123"}
    )
    bad = client.post(
        "/api/auth/login", json={"email": "owner@spa.example", "password": "wrong-password"}
    )

    assert good.status_code == 200
    assert "access_token" in good.json()
    assert bad.status_code == 401


def test_guarded_endpoint_requires_token(client):
    response = client.get("/api/settings")

    assert response.status_code == 401


def test_garbage_token_rejected(client):
    response = client.get("/api/settings", headers=_auth("not-a-real-token"))

    assert response.status_code == 401


def test_settings_roundtrip_and_persist(client):
    token = _register(client).json()["access_token"]

    patched = client.patch(
        "/api/settings",
        headers=_auth(token),
        json={
            "approval_mode": False,
            "reminder_offsets_minutes": [-1440, -120, -30],
            "reminder_template": "Hi {name}, see you {date} {time} — {business}",
            "timezone": "Europe/London",
        },
    )
    fetched = client.get("/api/settings", headers=_auth(token))

    assert patched.status_code == 200
    assert patched.json()["approval_mode"] is False
    assert fetched.json()["reminder_offsets_minutes"] == [-1440, -120, -30]
    assert fetched.json()["reminder_template"] == "Hi {name}, see you {date} {time} — {business}"
    assert fetched.json()["timezone"] == "Europe/London"


def test_invalid_timezone_rejected(client):
    token = _register(client).json()["access_token"]

    response = client.patch(
        "/api/settings",
        headers=_auth(token),
        json={"timezone": "Mars/Olympus"},
    )

    assert response.status_code == 422


def test_invalid_offsets_rejected(client):
    token = _register(client).json()["access_token"]

    response = client.patch(
        "/api/settings",
        headers=_auth(token),
        json={"reminder_offsets_minutes": [60]},
    )

    assert response.status_code == 422


def test_tenant_isolation_across_endpoints(client):
    token_a = _register(client, email="a@spa.example").json()["access_token"]
    # tenant B gets seeded data directly through the same DB
    token_b = _register(client, email="b@spa.example").json()["access_token"]
    engine = client.app.state.engine
    from sqlalchemy.orm import sessionmaker

    from app.models.entities import Customer, Tenant
    from tests.conftest import make_appointment

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        tenant_b = session.query(Tenant).filter_by(email="b@spa.example").one()
        customer_b = Customer(tenant_id=tenant_b.id, name="B cust", phone="+15550001234")
        session.add(customer_b)
        session.flush()
        make_appointment(
            session,
            tenant_b,
            customer_b,
            start_at=datetime.now(UTC) + timedelta(days=1),
            google_event_id="evt_b",
        )
        conversation_b_id = None
        from app.models.entities import Conversation

        convo = Conversation(tenant_id=tenant_b.id, customer_id=customer_b.id, channel="sms")
        session.add(convo)
        session.commit()
        conversation_b_id = convo.id

    # Tenant A must not see tenant B's data
    appts_a = client.get("/api/appointments", headers=_auth(token_a)).json()
    assert all(a["id"] != "evt_b" for a in appts_a)

    convos_a = client.get("/api/conversations", headers=_auth(token_a)).json()
    assert all(c["id"] != conversation_b_id for c in convos_a)

    leak = client.get(f"/api/conversations/{conversation_b_id}/messages", headers=_auth(token_a))
    assert leak.status_code == 404

    _ = token_b

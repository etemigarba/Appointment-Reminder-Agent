"""C4: Stripe billing — checkout params, webhook signatures, status updates."""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.agents.llm_client import FakeLLMClient
from app.api.billing import verify_stripe_signature
from app.main import create_app
from app.models.entities import Tenant

PASSWORD = "password123"


@pytest.fixture()
def billing_client(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'billing.db'}", llm_client=FakeLLMClient())
    with TestClient(app) as c:
        yield c


def _register(client, email="bill@spa.example"):
    return client.post(
        "/api/auth/register", json={"email": email, "password": PASSWORD}
    ).json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _signed(payload: bytes, secret: str, ts: int | None = None) -> str:
    t = ts or int(time.time())
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


def test_webhook_signature_verification():
    secret = "whsec_123"
    payload = b'{"type": "checkout.session.completed"}'
    header = _signed(payload, secret)

    assert verify_stripe_signature(payload, header, secret) is True
    assert verify_stripe_signature(b"tampered", header, secret) is False
    assert verify_stripe_signature(payload, "t=abc,v1=deadbeef", secret) is False
    # stale timestamp beyond tolerance
    stale = _signed(payload, secret, ts=int(time.time()) - 4000)
    assert verify_stripe_signature(payload, stale, secret) is False


def test_checkout_requires_config(monkeypatch, billing_client):
    for var in ("STRIPE_SECRET_KEY", "STRIPE_PRICE_ID", "APP_PUBLIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    token = _register(billing_client)

    response = billing_client.post("/api/billing/checkout", headers=_auth(token))

    assert response.status_code == 503


def test_checkout_creates_session_and_customer(monkeypatch, billing_client):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_pro")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.com")

    captured = {}

    def fake_ensure(self, tenant_id, email, existing_customer_id):
        captured["tenant_id"] = tenant_id
        captured["email"] = email
        return "cus_new"

    def fake_checkout(self, *, customer_id, price_id, success_url, cancel_url):
        captured.update(customer=customer_id, price=price_id,
                        success=success_url, cancel=cancel_url)
        return {"url": "https://checkout.stripe.com/session1"}

    monkeypatch.setattr("app.billing.stripe_client.StripeClient.ensure_customer", fake_ensure)
    monkeypatch.setattr(
        "app.billing.stripe_client.StripeClient.create_checkout_session", fake_checkout
    )

    token = _register(billing_client)
    response = billing_client.post("/api/billing/checkout", headers=_auth(token))

    assert response.status_code == 200
    assert response.json()["checkout_url"] == "https://checkout.stripe.com/session1"
    assert captured["customer"] == "cus_new"
    assert captured["price"] == "price_pro"
    assert captured["success"].startswith("https://app.example.com/settings")

    session = sessionmaker(bind=billing_client.app.state.engine, expire_on_commit=False)()
    tenant = session.query(Tenant).filter_by(email="bill@spa.example").one()
    assert tenant.stripe_customer_id == "cus_new"
    session.close()


def test_webhook_marks_subscription_active(monkeypatch, billing_client):
    secret = "whsec_sig"
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_123")
    monkeypatch.setenv("STRIPE_PRICE_ID", "price_pro")
    monkeypatch.setenv("APP_PUBLIC_BASE_URL", "https://app.example.com")

    token = _register(billing_client)
    factory = sessionmaker(bind=billing_client.app.state.engine, expire_on_commit=False)
    with factory() as session:
        tenant = session.query(Tenant).filter_by(email="bill@spa.example").one()
        tenant_id = tenant.id

    event = {
        "type": "checkout.session.completed",
        "data": {"object": {"metadata": {"tenant_id": tenant_id}}},
    }
    payload = json.dumps(event).encode()
    header = _signed(payload, secret)

    response = billing_client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": header}
    )

    assert response.status_code == 200
    with factory() as session:
        updated = session.get(Tenant, tenant_id)
        assert updated.subscription_status == "active"
        assert updated.plan == "pro"

    # bad signature rejected
    bad = billing_client.post(
        "/webhooks/stripe",
        content=payload,
        headers={"Stripe-Signature": "t=1,v1=bad"},
    )
    assert bad.status_code == 400


def test_subscription_deleted_cancels(monkeypatch, billing_client):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_x")
    token = _register(billing_client)
    factory = sessionmaker(bind=billing_client.app.state.engine, expire_on_commit=False)
    with factory() as session:
        tenant_id = session.query(Tenant).filter_by(email="bill@spa.example").one().id

    event = {
        "type": "customer.subscription.deleted",
        "data": {"object": {"metadata": {"tenant_id": tenant_id}, "status": "canceled"}},
    }
    payload = json.dumps(event).encode()
    header = _signed(payload, "whsec_x")

    response = billing_client.post(
        "/webhooks/stripe", content=payload, headers={"Stripe-Signature": header}
    )

    assert response.status_code == 200
    with factory() as session:
        assert session.get(Tenant, tenant_id).subscription_status == "canceled"

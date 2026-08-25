"""C5: native Meta WhatsApp — sender payload, webhook verify, inbound flow."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm_client import AssistantTurn, FakeLLMClient
from app.channels.meta_whatsapp import MetaWhatsAppSender
from app.main import create_app
from app.models.entities import Customer
from tests.conftest import make_appointment

TENANT_NUMBER = "+15550002222"
CUSTOMER_PHONE = "+15559876543"


def test_meta_sender_posts_correct_payload():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"messages": [{"id": "wamid.X"}]})

    sender = MetaWhatsAppSender("meta-token", "PHONE_ID_1", transport=httpx.MockTransport(handler))

    result = sender.send(to="+15551234567", body="Reminder!")

    assert result.ok is True
    assert result.provider_message_id == "wamid.X"
    request = captured[0]
    assert "/PHONE_ID_1/messages" in str(request.url)
    assert request.headers["Authorization"] == "Bearer meta-token"
    body = json.loads(request.content)
    assert body["messaging_product"] == "whatsapp"
    assert body["to"] == "+15551234567"
    assert body["type"] == "text"

import json  # noqa: E402


def test_whatsapp_webhook_verification(monkeypatch, tmp_path):
    monkeypatch.setenv("META_WEBHOOK_VERIFY_TOKEN", "verify-me")
    app = create_app(database_url=f"sqlite:///{tmp_path / 'wa.db'}", llm_client=FakeLLMClient())
    with TestClient(app) as client:
        ok = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "CHALLENGE123"},
        )
        bad = client.get(
            "/webhooks/whatsapp",
            params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "X"},
        )

    assert ok.status_code == 200
    assert ok.text == "CHALLENGE123"
    assert bad.status_code == 403


def test_whatsapp_inbound_routes_into_conversation_pipeline(monkeypatch, tmp_path):
    from app.agents.llm_client import ToolCall

    monkeypatch.setenv("META_DISPLAY_NUMBER", TENANT_NUMBER)
    app = create_app(database_url=f"sqlite:///{tmp_path / 'wa2.db'}", llm_client=None)

    with TestClient(app) as client:
        factory = app.state.session_factory
        session = factory()
        from app.models.entities import Tenant

        tenant = Tenant(name="WA Biz", email="wa@spa.example", password_hash="x",
                        twilio_number=TENANT_NUMBER)
        session.add(tenant)
        session.flush()
        customer = Customer(tenant_id=tenant.id, name="Wendy", phone=CUSTOMER_PHONE)
        session.add(customer)
        session.flush()
        appointment = make_appointment(
            session, tenant, customer,
            start_at=datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=2),
            google_event_id="evt_wa",
        )
        session.commit()

        # inject a scripted LLM now that we know the appointment id
        scripted = FakeLLMClient([
            AssistantTurn(tool_calls=[ToolCall(id="c1", name="confirm_appointment",
                                               arguments={"appointment_id": appointment.id,
                                                          "confirmed_by_customer": True})]),
            AssistantTurn(content="You're confirmed!"),
        ])
        app.state.llm_client = scripted
        session.close()

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{"profile": {"name": "Wendy"}, "wa_id": CUSTOMER_PHONE.lstrip("+")}],
                        "messages": [{
                            "type": "text",
                            "from": CUSTOMER_PHONE,
                            "text": {"body": f"please confirm {appointment.id}"},
                        }],
                    }
                }]
            }]
        }

        response = client.post("/webhooks/whatsapp", json=payload)

        assert response.status_code == 200
        session = factory()
        from app.models.entities import Appointment

        updated = session.get(Appointment, appointment.id)
        assert updated.status == "confirmed"
        session.close()


def test_whatsapp_stop_opts_out_without_llm(monkeypatch, tmp_path):
    monkeypatch.setenv("META_DISPLAY_NUMBER", TENANT_NUMBER)
    fake_llm = FakeLLMClient([])
    app = create_app(database_url=f"sqlite:///{tmp_path / 'wa3.db'}", llm_client=fake_llm)

    with TestClient(app) as client:
        factory = app.state.session_factory
        session = factory()
        from app.models.entities import Tenant

        tenant = Tenant(name="WA Biz", email="wa2@spa.example", password_hash="x",
                        twilio_number=TENANT_NUMBER)
        session.add(tenant)
        session.flush()
        customer = Customer(tenant_id=tenant.id, name="Sam", phone=CUSTOMER_PHONE)
        session.add(customer)
        session.commit()
        customer_id = customer.id
        session.close()

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{"type": "text", "from": CUSTOMER_PHONE,
                                      "text": {"body": "STOP"}}],
                    }
                }]
            }]
        }
        response = client.post("/webhooks/whatsapp", json=payload)

        assert response.status_code == 200
        assert fake_llm.call_count == 0
        session = factory()
        opted = session.get(Customer, customer_id)
        assert opted.opted_out is True
        session.close()

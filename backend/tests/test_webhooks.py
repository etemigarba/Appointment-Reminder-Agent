"""C6: webhook e2e with scripted FakeLLM; C4: STOP handled before any LLM call."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm_client import AssistantTurn, FakeLLMClient, ToolCall
from app.main import create_app
from app.models.entities import (
    Appointment,
    ConsentRecord,
    Conversation,
    Customer,
    Message,
    Tenant,
)
from tests.conftest import make_appointment

TENANT_NUMBER = "+15550001111"
CUSTOMER_PHONE = "+15551234567"


@pytest.fixture()
def wired(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'webhook.db'}"
    fake_llm = FakeLLMClient()
    app = create_app(database_url=database_url, llm_client=fake_llm)

    with TestClient(app) as client:
        factory = app.state.session_factory
        session = factory()
        tenant = Tenant(
            name="Test Salon",
            email="owner@test.example",
            password_hash="x",
            twilio_number=TENANT_NUMBER,
            approval_mode=False,
        )
        session.add(tenant)
        session.flush()
        customer = Customer(tenant_id=tenant.id, name="Jane", phone=CUSTOMER_PHONE)
        session.add(customer)
        session.flush()
        appointment = make_appointment(
            session,
            tenant,
            customer,
            start_at=datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=2),
            google_event_id="evt_e2e",
        )
        session.commit()
        ids = {"tenant": tenant.id, "customer": customer.id, "appointment": appointment.id}
        session.close()

        yield client, factory, fake_llm, ids


def _post(client: TestClient, body: str):
    return client.post(
        "/webhooks/twilio",
        data={"From": CUSTOMER_PHONE, "To": TENANT_NUMBER, "Body": body},
    )


def test_inbound_message_runs_agent_and_mutates(wired):
    client, factory, fake_llm, ids = wired
    fake_llm.load_script(
        [
            AssistantTurn(
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        name="confirm_appointment",
                        arguments={
                            "appointment_id": ids["appointment"],
                            "confirmed_by_customer": True,
                        },
                    )
                ]
            ),
            AssistantTurn(content="Great — you're confirmed. See you then!"),
        ]
    )

    response = _post(client, "yes please confirm my booking")

    assert response.status_code == 200
    session = factory()
    try:
        appointment = session.get(Appointment, ids["appointment"])
        assert appointment.status == "confirmed"

        conversation = session.scalars(select(Conversation)).one()
        assert conversation.status == "open"
        messages = session.scalars(select(Message)).all()
        assert [m.direction for m in messages] == ["inbound", "outbound"]
        assert "confirmed" in messages[-1].body
        assert fake_llm.call_count >= 1
    finally:
        session.close()


def test_unknown_tenant_number_returns_404(wired):
    client, _, _, _ = wired

    response = client.post(
        "/webhooks/twilio",
        data={"From": CUSTOMER_PHONE, "To": "+19999999999", "Body": "hello"},
    )

    assert response.status_code == 404


def test_stop_opts_out_before_any_llm_call(wired):
    client, factory, fake_llm, ids = wired
    fake_llm.load_script([])  # any LLM call would fail the assertion below

    response = _post(client, "STOP")

    assert response.status_code == 200
    assert fake_llm.call_count == 0
    session = factory()
    try:
        customer = session.get(Customer, ids["customer"])
        assert customer.opted_out is True
        consents = session.scalars(select(ConsentRecord)).all()
        assert len(consents) == 1
        assert consents[0].granted is False
        outbound = session.scalars(
            select(Message).where(Message.direction == "outbound")
        ).all()
        assert len(outbound) == 1
        assert "unsubscribed" in outbound[0].body.lower()
    finally:
        session.close()

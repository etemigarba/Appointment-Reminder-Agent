"""C6/C7: approval queue now token-guarded and tenant-scoped."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.agents.llm_client import FakeLLMClient
from app.main import create_app
from tests.conftest import make_appointment

PASSWORD = "password123"


@pytest.fixture()
def approval_setup(tmp_path):
    app = create_app(database_url=f"sqlite:///{tmp_path / 'admin.db'}", llm_client=FakeLLMClient())

    with TestClient(app) as client:
        factory = app.state.session_factory
        session = factory()
        from app.core.security import hash_password

        from app.models.entities import Customer, Tenant

        tenant = Tenant(
            name="Approval Co",
            email="owner@approval.example",
            password_hash=hash_password(PASSWORD),
            approval_mode=True,
        )
        session.add(tenant)
        session.flush()
        customer = Customer(tenant_id=tenant.id, name="Jane", phone="+15550009999")
        session.add(customer)
        session.flush()
        start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=2)
        appointment = make_appointment(session, tenant, customer, start_at=start)
        session.commit()
        yield client, factory, tenant, customer, appointment
        session.close()


def _login(client) -> dict[str, str]:
    response = client.post(
        "/api/auth/login", json={"email": "owner@approval.example", "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _queue_reschedule(session, tenant, customer, appointment, new_start) -> str:
    from app.agents.tools import ToolContext, propose_reschedule

    result = propose_reschedule(
        ToolContext(session=session, tenant=session.get(type(tenant), tenant.id), customer=customer),
        appointment.id,
        new_start.isoformat(),
        confirmed_by_customer=True,
    )
    assert result["queued_for_approval"] is True
    return result["action_id"]


def test_actions_require_token(approval_setup):
    client, _, _, _, _ = approval_setup

    assert client.get("/api/pending-actions").status_code == 401
    assert client.post("/api/pending-actions/x/approve").status_code == 401
    assert client.post("/api/pending-actions/x/reject").status_code == 401


def test_approve_applies_reschedule(approval_setup):
    client, factory, tenant, customer, appointment = approval_setup
    headers = _login(client)
    original_start = appointment.start_at
    new_start = (original_start + timedelta(days=3)).replace(hour=14)

    session = factory()
    action_id = _queue_reschedule(session, tenant, customer, appointment, new_start)
    session.close()

    listed = client.get("/api/pending-actions", headers=headers)
    assert listed.status_code == 200
    assert [a["id"] for a in listed.json()] == [action_id]

    approved = client.post(f"/api/pending-actions/{action_id}/approve", headers=headers)

    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    session = factory()
    try:
        moved = session.get(type(appointment), appointment.id)
        assert moved.start_at == new_start
        assert moved.status == "rescheduled"
    finally:
        session.close()


def test_reject_leaves_untouched_and_conflicts(approval_setup):
    client, factory, tenant, customer, appointment = approval_setup
    headers = _login(client)
    original_start = appointment.start_at

    session = factory()
    action_id = _queue_reschedule(
        session,
        tenant,
        customer,
        appointment,
        appointment.start_at + timedelta(days=3),
    )
    session.close()

    rejected = client.post(f"/api/pending-actions/{action_id}/reject", headers=headers)
    conflict = client.post(f"/api/pending-actions/{action_id}/approve", headers=headers)

    assert rejected.status_code == 200
    assert conflict.status_code == 409
    session = factory()
    try:
        untouched = session.get(type(appointment), appointment.id)
        assert untouched.start_at == original_start
    finally:
        session.close()

"""C5/C7: agent tool semantics — guardrails, approval vs auto modes."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.agents.tools import (
    ToolContext,
    cancel_appointment,
    confirm_appointment,
    propose_reschedule,
)
from app.models.entities import (
    PendingAction,
    PendingActionStatus,
    PendingActionType,
    ReminderJob,
)
from app.scheduler.reminder_service import generate_reminder_jobs
from tests.conftest import make_appointment


def _ctx(db_session, tenant, customer):
    return ToolContext(session=db_session, tenant=tenant, customer=customer)


def test_mutation_without_confirmation_is_refused(db_session, tenant, customer):
    appointment = make_appointment(
        db_session, tenant, customer, start_at=datetime.now(UTC) + timedelta(days=2)
    )

    result = cancel_appointment(_ctx(db_session, tenant, customer), appointment.id)

    assert result["error"].startswith("REFUSED_CANCEL")
    db_session.refresh(appointment)
    assert appointment.status == "scheduled"
    assert db_session.scalars(select(PendingAction)).all() == []


def test_confirm_appointment_sets_status(db_session, tenant, customer):
    appointment = make_appointment(
        db_session, tenant, customer, start_at=datetime.now(UTC) + timedelta(days=2)
    )

    result = confirm_appointment(
        _ctx(db_session, tenant, customer), appointment.id, confirmed_by_customer=True
    )

    assert result["ok"] is True
    db_session.refresh(appointment)
    assert appointment.status == "confirmed"


def test_approval_mode_queues_action_without_mutating(db_session, tenant, customer):
    start = datetime.now(UTC) + timedelta(days=2)
    appointment = make_appointment(db_session, tenant, customer, start_at=start)

    new_start = start + timedelta(days=3)
    result = propose_reschedule(
        _ctx(db_session, tenant, customer),
        appointment.id,
        new_start.isoformat(),
        confirmed_by_customer=True,
    )

    assert result["queued_for_approval"] is True
    action = db_session.scalars(select(PendingAction)).one()
    assert action.action_type == PendingActionType.RESCHEDULE.value
    assert action.status == PendingActionStatus.PENDING.value
    db_session.refresh(appointment)
    assert appointment.start_at == start  # untouched until owner approves


def test_auto_mode_applies_and_regenerates_reminders(db_session, tenant, customer):
    tenant.approval_mode = False
    db_session.commit()
    start = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(days=2)
    appointment = make_appointment(db_session, tenant, customer, start_at=start)
    generate_reminder_jobs(db_session)
    old_job_ids = {
        j.id for j in db_session.scalars(select(ReminderJob)).all()
    }

    new_start = (start + timedelta(days=3)).replace(hour=14)
    result = propose_reschedule(
        _ctx(db_session, tenant, customer),
        appointment.id,
        new_start.isoformat(),
        confirmed_by_customer=True,
    )

    assert result.get("rescheduled_to") == new_start.isoformat()
    db_session.refresh(appointment)
    assert appointment.start_at == new_start
    assert appointment.status == "rescheduled"
    jobs = db_session.scalars(select(ReminderJob)).all()
    # stale pending jobs are removed, replaced by jobs timed against the new start
    assert all(j.id not in old_job_ids for j in jobs)
    assert {j.offset_minutes for j in jobs} == {-1440, -120}
    for job in jobs:
        assert job.due_at == new_start + timedelta(minutes=job.offset_minutes)


def test_cannot_touch_another_customers_appointment(db_session, tenant, customer):
    other = make_appointment(
        db_session,
        tenant,
        None,
        start_at=datetime.now(UTC) + timedelta(days=2),
        google_event_id="evt_other",
    )

    result = confirm_appointment(
        _ctx(db_session, tenant, customer), other.id, confirmed_by_customer=True
    )

    assert "error" in result
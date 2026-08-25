"""C5: reminder computation correctness + idempotency (PRD FR-8)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, func

from app.models.entities import ReminderJob, ReminderJobStatus
from app.scheduler.reminder_service import claim_due_jobs, generate_reminder_jobs
from tests.conftest import make_appointment

NOW = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _count(session):
    return session.scalar(select(func.count()).select_from(ReminderJob))


def test_jobs_generated_for_upcoming_appointment(db_session, tenant, customer):
    start = NOW + timedelta(hours=25)
    make_appointment(db_session, tenant, customer, start_at=start)

    created = generate_reminder_jobs(db_session, now=NOW)

    offsets = sorted(job.offset_minutes for job in created)
    assert offsets == [-1440, -120]
    for job in created:
        assert job.due_at == start + timedelta(minutes=job.offset_minutes)
        assert job.status == ReminderJobStatus.PENDING.value


def test_past_offset_not_generated_for_soon_appointment(db_session, tenant, customer):
    make_appointment(db_session, tenant, customer, start_at=NOW + timedelta(hours=3))

    created = generate_reminder_jobs(db_session, now=NOW)

    assert [job.offset_minutes for job in created] == [-120]


def test_generation_is_idempotent(db_session, tenant, customer):
    make_appointment(db_session, tenant, customer, start_at=NOW + timedelta(hours=25))

    first = generate_reminder_jobs(db_session, now=NOW)
    second = generate_reminder_jobs(db_session, now=NOW)

    assert len(first) == 2
    assert second == []
    assert _count(db_session) == 2


def test_cancelled_and_past_appointments_skipped(db_session, tenant, customer):
    make_appointment(
        db_session, tenant, customer, start_at=NOW + timedelta(hours=25), status="cancelled"
    )
    make_appointment(db_session, tenant, customer, start_at=NOW - timedelta(hours=1),
                     google_event_id="evt_past")

    generate_reminder_jobs(db_session, now=NOW)

    assert _count(db_session) == 0


def test_claim_due_jobs_only_returns_due_pending(db_session, tenant, customer):
    appointment = make_appointment(
        db_session, tenant, customer, start_at=NOW + timedelta(hours=25)
    )
    generate_reminder_jobs(db_session, now=NOW)

    due_now = claim_due_jobs(db_session, now=NOW)
    assert due_now == []

    job = db_session.scalar(select(ReminderJob).where(ReminderJob.appointment_id == appointment.id))
    job.due_at = NOW - timedelta(minutes=1)
    db_session.commit()

    due_later = claim_due_jobs(db_session, now=NOW)
    assert [j.id for j in due_later] == [job.id]

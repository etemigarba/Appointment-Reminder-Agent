"""Reminder job generation and dispatch cycle (PRD FR-5, FR-8).

Generation is idempotent: a (appointment_id, offset_minutes) pair exists at
most once, enforced by a unique constraint and an existence check before
insert. Past-due offsets are never generated for future appointments.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Appointment, AppointmentStatus, ReminderJob, ReminderJobStatus, utcnow

DEFAULT_OFFSETS_MINUTES: tuple[int, ...] = (-1440, -120)
REMINDER_ELIGIBLE_STATUSES = (
    AppointmentStatus.SCHEDULED.value,
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.RESCHEDULED.value,
)


def generate_reminder_jobs(
    session: Session,
    *,
    offsets_minutes: tuple[int, ...] = DEFAULT_OFFSETS_MINUTES,
    horizon_hours: int = 168,
    now: datetime | None = None,
) -> list[ReminderJob]:
    now = now or utcnow()
    horizon_end = now + timedelta(hours=horizon_hours)

    appointments = session.scalars(
        select(Appointment).where(
            Appointment.status.in_(REMINDER_ELIGIBLE_STATUSES),
            Appointment.start_at >= now,
            Appointment.start_at < horizon_end,
        )
    ).all()

    created: list[ReminderJob] = []
    for appointment in appointments:
        existing = set(
            session.scalars(
                select(ReminderJob.offset_minutes).where(
                    ReminderJob.appointment_id == appointment.id,
                    ReminderJob.status != ReminderJobStatus.CANCELLED.value,
                )
            ).all()
        )
        for offset in offsets_minutes:
            if offset in existing or offset >= 0:
                continue
            due_at = appointment.start_at + timedelta(minutes=offset)
            if due_at < now:
                continue
            job = ReminderJob(
                appointment_id=appointment.id,
                offset_minutes=offset,
                due_at=due_at,
                status=ReminderJobStatus.PENDING.value,
            )
            session.add(job)
            created.append(job)

    session.commit()
    return created


def claim_due_jobs(session: Session, *, now: datetime | None = None) -> list[ReminderJob]:
    now = now or utcnow()
    return list(
        session.scalars(
            select(ReminderJob).where(
                ReminderJob.status == ReminderJobStatus.PENDING.value,
                ReminderJob.due_at <= now,
            )
        ).all()
    )


def mark_sent(job: ReminderJob, *, now: datetime | None = None) -> None:
    job.status = ReminderJobStatus.SENT.value
    job.sent_at = now or utcnow()


def cancel_jobs_for_appointment(session: Session, appointment_id: str) -> None:
    jobs = session.scalars(
        select(ReminderJob).where(
            ReminderJob.appointment_id == appointment_id,
            ReminderJob.status == ReminderJobStatus.PENDING.value,
        )
    ).all()
    for job in jobs:
        job.status = ReminderJobStatus.CANCELLED.value
    session.commit()


def delete_pending_jobs(session: Session, appointment_id: str) -> None:
    """Remove undelivered jobs so new offsets can be generated after a move.

    Pending jobs are operational state, not audit records; deleting them keeps
    the (appointment_id, offset_minutes) uniqueness guarantee intact.
    """
    from sqlalchemy import delete

    session.execute(
        delete(ReminderJob).where(
            ReminderJob.appointment_id == appointment_id,
            ReminderJob.status == ReminderJobStatus.PENDING.value,
        )
    )
    session.commit()

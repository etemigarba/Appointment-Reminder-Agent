"""Free-slot search derived from locally synced appointments.

Business hours are evaluated in UTC in this phase; per-timezone working
hours arrive with the dashboard (Phase 3).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Appointment, AppointmentStatus

DEFAULT_BUSINESS_START = time(9, 0)
DEFAULT_BUSINESS_END = time(17, 0)
GRID_MINUTES = 30
BUSY_STATUSES = (
    AppointmentStatus.SCHEDULED.value,
    AppointmentStatus.CONFIRMED.value,
    AppointmentStatus.RESCHEDULED.value,
)


def find_free_slots(
    session: Session,
    *,
    tenant_id: str,
    day: date,
    duration_minutes: int = 60,
    business_start: time = DEFAULT_BUSINESS_START,
    business_end: time = DEFAULT_BUSINESS_END,
    grid_minutes: int = GRID_MINUTES,
    exclude_appointment_id: str | None = None,
    exclude_appointment_customer: str | None = None,
) -> list[datetime]:
    window_start = datetime.combine(day, business_start, tzinfo=_utc())
    window_end = datetime.combine(day, business_end, tzinfo=_utc())

    busy = [
        (a.start_at, a.end_at or a.start_at + timedelta(hours=1))
        for a in session.scalars(
            select(Appointment).where(
                Appointment.tenant_id == tenant_id,
                Appointment.status.in_(BUSY_STATUSES),
                Appointment.start_at < window_end + timedelta(days=1),
            )
        ).all()
        if a.id != exclude_appointment_id and a.customer_id != exclude_appointment_customer
    ]
    busy = sorted((max(s, window_start), min(e, window_end)) for s, e in busy if e > window_start and s < window_end)

    slots: list[datetime] = []
    cursor = window_start
    step = timedelta(minutes=grid_minutes)
    duration = timedelta(minutes=duration_minutes)
    for b_start, b_end in busy + [(window_end, window_end)]:
        free_until = min(b_start, window_end)
        candidate = cursor
        while candidate + duration <= free_until:
            slots.append(candidate)
            candidate += step
        cursor = max(cursor, b_end)
    return slots


def overlaps_existing(
    session: Session,
    tenant_id: str,
    start: datetime,
    exclude_appointment_id: str | None = None,
    duration: timedelta = timedelta(hours=1),
) -> bool:
    end = start + duration
    candidates = session.scalars(
        select(Appointment).where(
            Appointment.tenant_id == tenant_id,
            Appointment.status.in_(BUSY_STATUSES),
            Appointment.start_at < end,
        )
    ).all()
    for a in candidates:
        if a.id == exclude_appointment_id:
            continue
        a_end = a.end_at or a.start_at + duration
        if a_end > start:
            return True
    return False


def _utc():
    from datetime import UTC

    return UTC

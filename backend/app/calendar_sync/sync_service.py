"""Sync provider events into Appointment rows (PRD FR-2/FR-4).

Consumes NormalizedEvent objects from any calendar provider. Upserts by
(tenant_id, google_event_id) — the column name is historical; it stores the
provider's event id for every provider.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calendar_sync.client import SyncResult
from app.calendar_sync.normalize import NormalizedEvent
from app.models.entities import Appointment, AppointmentStatus, Customer

_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return digits[-10:] if len(digits) > 10 else digits


def sync_appointments(
    session: Session,
    client,
    *,
    tenant_id: str,
    time_min: datetime,
    time_max: datetime,
) -> SyncResult:
    result = SyncResult()
    for event in client.list_events(time_min, time_max):
        if event.start_dt is None:
            result.skipped += 1
            continue

        appointment = session.scalar(
            select(Appointment).where(
                Appointment.tenant_id == tenant_id,
                Appointment.google_event_id == event.id,
            )
        )
        if appointment is None:
            appointment = Appointment(
                tenant_id=tenant_id,
                google_event_id=event.id,
                status=AppointmentStatus.SCHEDULED.value,
                customer_id=_match_customer(session, tenant_id, event),
            )
            result.created += 1
        else:
            result.updated += 1

        appointment.title = event.title
        appointment.start_at = event.start_dt
        appointment.end_at = event.end_dt
        session.add(appointment)

    session.commit()
    return result


def _match_customer(session: Session, tenant_id: str, event: NormalizedEvent) -> str | None:
    for email in (e.strip().lower() for e in event.attendee_emails):
        customer = session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                func.lower(Customer.email) == email,
            )
        )
        if customer is not None:
            return customer.id

    haystack = " ".join(filter(None, [event.title, *event.attendee_emails]))
    for match in _PHONE_RE.findall(haystack):
        normalized = normalize_phone(match)
        customers = session.scalars(select(Customer).where(Customer.tenant_id == tenant_id)).all()
        for customer in customers:
            if customer.phone and normalize_phone(customer.phone) == normalized:
                return customer.id
    return None


_ = NormalizedEvent  # re-export parity

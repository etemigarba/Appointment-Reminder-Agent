"""Sync Google Calendar events into Appointment rows (PRD FR-2/FR-4).

Upserts by (tenant_id, google_event_id); matches a Customer by attendee
email or phone number found in the event summary/description.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.calendar_sync.client import GoogleCalendarClient, SyncResult
from app.models.entities import Appointment, AppointmentStatus, Customer

_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    return digits[-10:] if len(digits) > 10 else digits


def sync_appointments(
    session: Session,
    client: GoogleCalendarClient,
    *,
    tenant_id: str,
    time_min: datetime,
    time_max: datetime,
) -> SyncResult:
    result = SyncResult()
    for event in client.list_events(time_min, time_max):
        start_raw = (event.get("start") or {}).get("dateTime")
        if not start_raw:
            result.skipped += 1
            continue
        end_raw = (event.get("end") or {}).get("dateTime")

        appointment = session.scalar(
            select(Appointment).where(
                Appointment.tenant_id == tenant_id,
                Appointment.google_event_id == event["id"],
            )
        )
        if appointment is None:
            appointment = Appointment(
                tenant_id=tenant_id,
                google_event_id=event["id"],
                status=AppointmentStatus.SCHEDULED.value,
                customer_id=_match_customer(session, tenant_id, event),
            )
            result.created += 1
        else:
            result.updated += 1

        appointment.title = event.get("summary") or ""
        appointment.start_at = datetime.fromisoformat(start_raw)
        appointment.end_at = datetime.fromisoformat(end_raw) if end_raw else None
        session.add(appointment)

    session.commit()
    return result


def _match_customer(session: Session, tenant_id: str, event: dict[str, Any]) -> str | None:
    attendee_emails = [
        (a.get("email") or "").strip().lower() for a in event.get("attendees", []) if a.get("email")
    ]
    for email in attendee_emails:
        customer = session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant_id,
                func.lower(Customer.email) == email,
            )
        )
        if customer is not None:
            return customer.id

    haystack = " ".join(
        filter(None, [event.get("summary"), event.get("description"), *attendee_emails])
    )
    for match in _PHONE_RE.findall(haystack):
        normalized = normalize_phone(match)
        customers = session.scalars(select(Customer).where(Customer.tenant_id == tenant_id)).all()
        for customer in customers:
            if customer.phone and normalize_phone(customer.phone) == normalized:
                return customer.id
    return None

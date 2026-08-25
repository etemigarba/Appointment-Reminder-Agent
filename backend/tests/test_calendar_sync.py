"""C6: calendar sync maps provider payloads to Appointment rows (FR-2/FR-4)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.calendar_sync.client import FakeGoogleCalendarClient
from app.calendar_sync.normalize import NormalizedEvent
from app.calendar_sync.sync_service import normalize_phone, sync_appointments
from app.models.entities import Appointment

BASE = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _event(event_id, title="Cut & color", start=None, emails=None):
    start = start or BASE + timedelta(hours=2)
    return NormalizedEvent(
        id=event_id,
        title=title,
        start=start.isoformat(),
        end=(start + timedelta(hours=1)).isoformat(),
        attendee_emails=tuple(emails or []),
    )


def test_sync_creates_appointments_with_customer_match(db_session, tenant, customer):
    client = FakeGoogleCalendarClient([
        _event("evt_a", emails=[customer.email]),
        _event("evt_b", title="Call Jane +1 555 123 4567"),
    ])

    result = sync_appointments(
        db_session,
        client,
        tenant_id=tenant.id,
        time_min=BASE,
        time_max=BASE + timedelta(days=7),
    )

    assert (result.created, result.updated, result.skipped) == (2, 0, 0)
    appointments = db_session.scalars(select(Appointment)).all()
    by_event = {a.google_event_id: a for a in appointments}

    matched_email = by_event["evt_a"]
    assert matched_email.customer_id == customer.id
    assert matched_email.title == "Cut & color"
    assert matched_email.start_at == BASE + timedelta(hours=2)
    assert matched_email.end_at == BASE + timedelta(hours=3)

    matched_phone = by_event["evt_b"]
    assert matched_phone.customer_id == customer.id


def test_resync_updates_without_duplicates(db_session, tenant, customer):
    client = FakeGoogleCalendarClient([_event("evt_a", title="Old title")])
    kwargs = dict(tenant_id=tenant.id, time_min=BASE, time_max=BASE + timedelta(days=7))

    sync_appointments(db_session, client, **kwargs)
    client.events[0] = _event("evt_a", title="New title")
    result = sync_appointments(db_session, client, **kwargs)

    assert result.created == 0
    assert result.updated == 1
    count = db_session.scalar(select(func.count()).select_from(Appointment))
    assert count == 1
    assert db_session.scalars(select(Appointment)).one().title == "New title"


def test_unparseable_start_is_skipped(db_session, tenant):
    class StubClient:
        def list_events(self, time_min, time_max):
            return [NormalizedEvent(id="evt_bad", title="Broken", start="not-a-date", end=None)]

    result = sync_appointments(
        db_session,
        StubClient(),
        tenant_id=tenant.id,
        time_min=BASE,
        time_max=BASE + timedelta(days=7),
    )

    assert (result.created, result.skipped) == (0, 1)


def test_normalize_phone():
    assert normalize_phone("+1 (555) 123-4567") == "5551234567"
    assert normalize_phone("5551234567") == "5551234567"
    assert normalize_phone("44 20 7946 0958") == "2079460958"

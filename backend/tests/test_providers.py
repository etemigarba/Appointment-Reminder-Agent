"""C6/C7: Outlook + Calendly providers, factory dispatch, outlook sync e2e."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
from sqlalchemy import select

from app.calendar_sync.calendly import CalendlyClient
from app.calendar_sync.client import FakeGoogleCalendarClient
from app.calendar_sync.normalize import NormalizedEvent
from app.calendar_sync.outlook import OutlookGraphClient
from app.calendar_sync.provider_factory import build_provider_client
from app.calendar_sync.sync_service import sync_appointments
from app.models.entities import Appointment
from tests.conftest import make_appointment

BASE = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


def _outlook_transport(payload: dict) -> httpx.MockTransport:
    return httpx.MockTransport(lambda r: httpx.Response(200, json=payload))


def test_outlook_client_normalizes_graph_payload():
    graph_payload = {
        "value": [
            {
                "id": "graph-1",
                "subject": "Consultation",
                "start": {"dateTime": BASE.isoformat()},
                "end": {"dateTime": (BASE + timedelta(hours=1)).isoformat()},
                "attendees": [
                    {"emailAddress": {"address": "jane@example.com"}},
                    {"emailAddress": {"address": ""}},
                ],
            },
            {"id": "no-datetime", "subject": "bad"},
        ]
    }
    client = OutlookGraphClient("token", transport=_outlook_transport(graph_payload))

    events = client.list_events(BASE, BASE + timedelta(days=7))

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, NormalizedEvent)
    assert event.id == "graph-1"
    assert event.title == "Consultation"
    assert event.attendee_emails == ("jane@example.com",)


def test_calendly_client_maps_events_and_invitees():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/scheduled_events"):
            return httpx.Response(200, json={
                "collection": [{
                    "uri": "https://api.calendly.com/scheduled_events/EV1",
                    "name": "15 Minute Meeting",
                    "start_time": BASE.isoformat(),
                    "end_time": (BASE + timedelta(minutes=15)).isoformat(),
                }],
                "pagination": {},
            })
        if request.url.path.endswith("/invitees"):
            return httpx.Response(200, json={"collection": [{"email": "k@example.com"}]})
        return httpx.Response(404)

    client = CalendlyClient("pat-token", transport=httpx.MockTransport(handler))

    events = client.list_events(BASE, BASE + timedelta(days=7))

    assert len(events) == 1
    assert events[0].id == "EV1"
    assert events[0].title == "15 Minute Meeting"
    assert events[0].attendee_emails == ("k@example.com",)


def test_factory_dispatches_by_provider():
    # google without refresh token -> None
    assert build_provider_client(SimpleNamespace(
        calendar_provider="google", provider_config=None,
        google_refresh_token=None, google_calendar_id=None,
    )) is None

    # calendly with token -> CalendlyClient
    client = build_provider_client(SimpleNamespace(
        calendar_provider="calendly", provider_config='{"api_token":"tok"}',
    ))
    assert type(client).__name__ == "CalendlyClient"

    # calendly without token -> None
    assert build_provider_client(SimpleNamespace(
        calendar_provider="calendly", provider_config="{}",
    )) is None

    # unknown provider -> None
    assert build_provider_client(SimpleNamespace(
        calendar_provider="icloud", provider_config=None,
        google_refresh_token=None, google_calendar_id=None,
    )) is None


def test_outlook_sync_end_to_end(db_session, tenant, customer):
    """C7: normalized outlook payload lands in Appointment rows with customer match."""
    outlook_client = OutlookGraphClient("fake", transport=_outlook_transport({
        "value": [{
            "id": "g-outlook-1",
            "subject": "Fence quote visit",
            "start": {"dateTime": BASE.isoformat()},
            "end": {"dateTime": (BASE + timedelta(hours=1)).isoformat()},
            "attendees": [{"emailAddress": {"address": customer.email}}],
        }]
    }))

    result = sync_appointments(
        db_session, outlook_client,
        tenant_id=tenant.id, time_min=BASE, time_max=BASE + timedelta(days=7),
    )

    assert result.created == 1
    appointment = db_session.scalars(select(Appointment)).one()
    assert appointment.google_event_id == "g-outlook-1"
    assert appointment.customer_id == customer.id
    assert appointment.start_at == BASE


def test_google_normalized_fixture_still_syncs(db_session, tenant, customer):
    """Regression guard: normalized fake flows through sync as before."""
    client = FakeGoogleCalendarClient([
        NormalizedEvent(id="n1", title="Cut",
                        start=(BASE + timedelta(hours=2)).isoformat(),
                        end=(BASE + timedelta(hours=3)).isoformat(),
                        attendee_emails=[customer.email]),
    ])

    result = sync_appointments(db_session, client, tenant_id=tenant.id,
                               time_min=BASE - timedelta(days=1),
                               time_max=BASE + timedelta(days=7))

    assert result.created == 1
    appointment = db_session.scalars(select(Appointment)).first()
    assert appointment.customer_id == customer.id


def test_existing_calendar_fixture_still_works(db_session, tenant, customer):
    """The Phase-1 make_appointment helper remains usable for calendar tests."""
    appointment = make_appointment(db_session, tenant, customer, start_at=BASE)
    assert appointment.status == "scheduled"


_ = Appointment  # parity

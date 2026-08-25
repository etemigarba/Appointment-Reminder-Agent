"""Calendar provider abstraction.

All providers (Google, Outlook, Calendly) implement the CalendarProvider
protocol and return NormalizedEvent objects. The Google REST client imports
google-api-python-client lazily; tests use in-memory fakes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from app.calendar_sync.normalize import NormalizedEvent


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0


class CalendarProvider(Protocol):
    def list_events(self, time_min: datetime, time_max: datetime) -> list[NormalizedEvent]:
        """Return events starting in [time_min, time_max), normalized."""
        ...


# Backwards-compatible alias — google was the first provider.
GoogleCalendarClient = CalendarProvider


class FakeGoogleCalendarClient:
    """In-memory client used by the test suite (no credentials needed).

    Accepts NormalizedEvent instances or dicts in normalized shape.
    """

    def __init__(self, events: list[NormalizedEvent | dict] | None = None) -> None:
        self.events: list[NormalizedEvent] = [
            e if isinstance(e, NormalizedEvent) else NormalizedEvent(**e) for e in (events or [])
        ]

    def list_events(self, time_min: datetime, time_max: datetime) -> list[NormalizedEvent]:
        return [e for e in self.events if e.start_dt and time_min <= e.start_dt < time_max]


class GoogleCalendarRestClient:
    """Thin wrapper over google-api-python-client; requires the `google` extra.

    Translates Google API v3 payloads into NormalizedEvent.
    """

    def __init__(self, credentials: Any, calendar_id: str = "primary") -> None:
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:  # pragma: no cover - exercised only without extra
            raise RuntimeError(
                "google-api-python-client is not installed. "
                "Install with: pip install 'appointment-agent-backend[google]'"
            ) from exc
        self._service = build("calendar", "v3", credentials=credentials)
        self.calendar_id = calendar_id

    def list_events(self, time_min: datetime, time_max: datetime) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        page_token: str | None = None
        while True:
            response = (
                self._service.events()
                .list(
                    calendarId=self.calendar_id,
                    timeMin=time_min.isoformat(),
                    timeMax=time_max.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                )
                .execute()
            )
            for item in response.get("items", []):
                event = _normalize_google_event(item)
                if event is not None:
                    events.append(event)
            page_token = response.get("nextPageToken")
            if not page_token:
                return events


def _normalize_google_event(item: dict[str, Any]) -> NormalizedEvent | None:
    start_raw = (item.get("start") or {}).get("dateTime")
    if not start_raw:
        return None  # all-day events are skipped by normalization
    end_raw = (item.get("end") or {}).get("dateTime")
    attendees = tuple(
        a["email"]
        for a in item.get("attendees", [])
        if isinstance(a, dict) and a.get("email")
    )
    return NormalizedEvent(
        id=item["id"],
        title=item.get("summary") or "",
        start=start_raw,
        end=end_raw,
        attendee_emails=attendees,
    )


def normalize_google_date_guard(event: dict[str, Any]) -> bool:
    """Retained helper: True when a raw google payload is an all-day event."""
    return (event.get("start") or {}).get("date") is not None

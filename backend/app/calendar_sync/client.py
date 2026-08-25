"""Google Calendar client abstraction.

The real REST client imports google-api-python-client lazily so the core
install stays light; tests use in-memory fakes against the same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    skipped: int = 0


class GoogleCalendarClient(Protocol):
    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        """Return Google Calendar API v3 event resources in [time_min, time_max)."""
        ...


class FakeGoogleCalendarClient:
    """In-memory client used by the test suite (no credentials needed)."""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.events: list[dict[str, Any]] = events or []

    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        selected: list[dict[str, Any]] = []
        for event in self.events:
            raw = (event.get("start") or {}).get("dateTime")
            if raw is not None:
                if time_min <= _parse_start(event) < time_max:
                    selected.append(event)
            elif (event.get("start") or {}).get("date") is not None:
                # All-day events are returned by the real API too; the sync
                # service decides whether to skip them.
                if _event_date_in_range(event, time_min, time_max):
                    selected.append(event)
        return selected


def _event_date_in_range(event: dict[str, Any], time_min: datetime, time_max: datetime) -> bool:
    raw = event["start"]["date"]
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return False
    return time_min.date() <= day < time_max.date()


class GoogleCalendarRestClient:
    """Thin wrapper over google-api-python-client; requires the `google` extra."""

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

    def list_events(self, time_min: datetime, time_max: datetime) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
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
            events.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return events


def _parse_start(event: dict[str, Any]) -> datetime | None:
    raw = (event.get("start") or {}).get("dateTime")
    if not raw:
        return None
    return datetime.fromisoformat(raw)

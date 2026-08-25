"""Calendly provider — personal-access-token based.

Reads scheduled_events in a window, then fetches invitees per event for
attendee email matching. Pagination follows Calendly's pageToken protocol.
"""

from __future__ import annotations

from datetime import datetime

import httpx

from app.calendar_sync.normalize import NormalizedEvent

CALENDLY_API_BASE = "https://api.calendly.com"


class CalendlyClient:
    def __init__(self, api_token: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=CALENDLY_API_BASE,
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10.0,
            transport=transport,
        )

    def list_events(self, time_min: datetime, time_max: datetime) -> list[NormalizedEvent]:
        events: list[NormalizedEvent] = []
        page_token: str | None = None
        while True:
            params: dict[str, str] = {
                "min_start_time": time_min.isoformat(),
                "max_start_time": time_max.isoformat(),
                "status": "active",
                "sort": "start_time:asc",
            }
            if page_token:
                params["page_token"] = page_token
            response = self._client.get("/scheduled_events", params=params)
            response.raise_for_status()
            payload = response.json()

            for item in payload.get("collection", []):
                start_raw = item.get("start_time")
                if not start_raw:
                    continue
                emails = self._invitee_emails(item["uri"])
                events.append(
                    NormalizedEvent(
                        id=item["uri"].rsplit("/", 1)[-1],
                        title=item.get("name") or "",
                        start=start_raw,
                        end=item.get("end_time"),
                        attendee_emails=emails,
                    )
                )

            page_token = payload.get("pagination", {}).get("next_page_token")
            if not page_token:
                return events

    def _invitee_emails(self, event_uri: str) -> tuple[str, ...]:
        try:
            response = self._client.get(f"{event_uri}/invitees", params={"count": 100})
            response.raise_for_status()
        except httpx.HTTPError:
            return ()
        return tuple(
            invitee.get("email", "")
            for invitee in response.json().get("collection", [])
            if invitee.get("email")
        )

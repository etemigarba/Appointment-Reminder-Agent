"""Outlook (Microsoft Graph) calendar provider.

OAuth against login.microsoftonline.com; events read from Graph
/v1.0/me/calendarview. Token exchange is injectable for tests.
"""

from __future__ import annotations

import os
import urllib.parse
from datetime import datetime

import httpx

from app.calendar_sync.normalize import NormalizedEvent

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
AUTHORIZE_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_SCOPE = "offline_access https://graph.microsoft.com/calendars.readwrite"


def get_outlook_config() -> tuple[str, str, str]:
    client_id = os.environ.get("OUTLOOK_CLIENT_ID", "")
    client_secret = os.environ.get("OUTLOOK_CLIENT_SECRET", "")
    base_url = os.environ.get("APP_PUBLIC_BASE_URL", "").rstrip("/")
    if not (client_id and client_secret and base_url):
        raise RuntimeError(
            "OUTLOOK_CLIENT_ID, OUTLOOK_CLIENT_SECRET and APP_PUBLIC_BASE_URL must be set"
        )
    return client_id, client_secret, base_url


def build_authorize_url(state: str) -> str:
    client_id, _, base_url = get_outlook_config()
    params = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": f"{base_url}/api/outlook/callback",
            "scope": GRAPH_SCOPE,
            "response_mode": "query",
            "state": state,
        }
    )
    return f"{AUTHORIZE_URL}?{params}"


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    response = httpx.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return response.json()


class OutlookGraphClient:
    """Reads the tenant's default calendar via Microsoft Graph."""

    def __init__(self, access_token: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._client = httpx.Client(
            base_url=GRAPH_API_BASE,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10.0,
            transport=transport,
        )

    def list_events(self, time_min: datetime, time_max: datetime) -> list[NormalizedEvent]:
        response = self._client.get(
            "/me/calendarview",
            params={
                "startDateTime": time_min.isoformat(),
                "endDateTime": time_max.isoformat(),
                "$top": 100,
            },
        )
        response.raise_for_status()
        events: list[NormalizedEvent] = []
        for item in response.json().get("value", []):
            start_raw = (item.get("start") or {}).get("dateTime")
            if not start_raw:
                continue
            end_raw = (item.get("end") or {}).get("dateTime")
            attendees = tuple(
                a["emailAddress"]["address"]
                for a in item.get("attendees", [])
                if isinstance(a, dict) and a.get("emailAddress", {}).get("address")
            )
            events.append(
                NormalizedEvent(
                    id=item["id"],
                    title=item.get("subject") or "",
                    start=start_raw,
                    end=end_raw,
                    attendee_emails=attendees,
                )
            )
        return events

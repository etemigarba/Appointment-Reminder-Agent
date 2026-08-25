"""Provider factory: build the right calendar client for a tenant."""

from __future__ import annotations

import json
import os


def build_provider_client(tenant):
    """Instantiate the calendar client matching tenant.calendar_provider.

    Returns None when the tenant has no usable credentials.
    """
    provider = (tenant.calendar_provider or "google").lower()
    config = {}
    if tenant.provider_config:
        try:
            config = json.loads(tenant.provider_config)
        except (TypeError, ValueError):
            config = {}

    if provider == "google":
        return _google_client(tenant)
    if provider == "outlook":
        return _outlook_client(tenant, config)
    if provider == "calendly":
        return _calendly_client(config)
    return None


def _google_client(tenant):
    if not tenant.google_refresh_token:
        return None
    from google.oauth2.credentials import Credentials  # requires [google] extra

    from app.calendar_sync.client import GoogleCalendarRestClient

    credentials = Credentials(
        token=None,
        refresh_token=tenant.google_refresh_token,
        client_id=os.environ.get("GOOGLE_CLIENT_ID"),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
    )
    return GoogleCalendarRestClient(credentials, calendar_id=tenant.google_calendar_id or "primary")


def _outlook_client(tenant, config: dict):
    refresh_token = config.get("refresh_token")
    if not refresh_token:
        return None
    from app.calendar_sync.outlook import OutlookGraphClient, TOKEN_URL, get_outlook_config
    import httpx

    client_id, client_secret, _ = get_outlook_config()
    response = httpx.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
        timeout=10.0,
    )
    response.raise_for_status()
    return OutlookGraphClient(response.json()["access_token"])


def _calendly_client(config: dict):
    api_token = config.get("api_token")
    if not api_token:
        return None
    from app.calendar_sync.calendly import CalendlyClient

    return CalendlyClient(api_token)

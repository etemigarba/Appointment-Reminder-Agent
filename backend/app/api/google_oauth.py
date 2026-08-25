"""Google Calendar OAuth connect flow (PRD FR-17).

Authorize URL is built from GOOGLE_CLIENT_ID / APP_PUBLIC_BASE_URL; the
callback exchanges the code (injectable `_exchange_code` for tests) and
persists the refresh token on the tenant.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import httpx
import jwt as pyjwt
from fastapi import APIRouter, HTTPException

from app.core.deps import CurrentTenant, DbSession
from app.core.security import get_jwt_secret
from app.models.entities import Tenant

router = APIRouter(prefix="/api/google")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
STATE_TTL_MINUTES = 10


class GoogleConfigError(RuntimeError):
    pass


def get_google_config() -> tuple[str, str, str]:
    client_id = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    base_url = os.environ.get("APP_PUBLIC_BASE_URL", "").rstrip("/")
    if not (client_id and client_secret and base_url):
        raise GoogleConfigError(
            "GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and APP_PUBLIC_BASE_URL must be set"
        )
    return client_id, client_secret, base_url


def _redirect_uri(base_url: str) -> str:
    return f"{base_url}/api/google/callback"


def _make_state(tenant_id: str) -> str:
    now = datetime.now(UTC)
    return pyjwt.encode(
        {"sub": tenant_id, "exp": int((now + timedelta(minutes=STATE_TTL_MINUTES)).timestamp())},
        get_jwt_secret(),
        algorithm="HS256",
    )


def _read_state(state: str) -> str:
    try:
        payload = pyjwt.decode(state, get_jwt_secret(), algorithms=["HS256"])
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc
    return str(payload.get("sub", ""))


@router.get("/authorize")
def authorize(tenant: CurrentTenant):
    try:
        client_id, _, base_url = get_google_config()
    except GoogleConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    from urllib.parse import urlencode

    params = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": _redirect_uri(base_url),
            "response_type": "code",
            "scope": CALENDAR_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": _make_state(tenant.id),
        }
    )
    return {"authorize_url": f"{GOOGLE_AUTH_URL}?{params}"}


def exchange_code(
    code: str, client_id: str, client_secret: str, redirect_uri: str
) -> dict:
    """Exchange an authorization code for tokens (monkeypatched in tests)."""
    response = httpx.post(
        GOOGLE_TOKEN_URL,
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


@router.get("/callback")
def callback(code: str, state: str, session: DbSession):
    tenant_id = _read_state(state)
    try:
        client_id, client_secret, base_url = get_google_config()
    except GoogleConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    tokens = exchange_code(code, client_id, client_secret, _redirect_uri(base_url))
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="No refresh token returned; re-consent required")

    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Unknown tenant")
    tenant.google_refresh_token = refresh_token
    if tenant.google_calendar_id is None:
        tenant.google_calendar_id = "primary"
    session.commit()
    return {"ok": True}

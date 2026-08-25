"""Outlook (Microsoft Graph) OAuth connect flow — mirrors the Google flow."""

from __future__ import annotations

import json

import jwt as pyjwt
from fastapi import APIRouter, HTTPException

from app.calendar_sync.outlook import (
    build_authorize_url,
    exchange_code,
    get_outlook_config,
)
from app.core.deps import CurrentTenant, DbSession
from app.core.security import get_jwt_secret
from app.models.entities import Tenant

router = APIRouter(prefix="/api/outlook")


@router.get("/authorize")
def authorize(tenant: CurrentTenant):
    try:
        get_outlook_config()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    state = pyjwt.encode(
        {"sub": tenant.id, "provider": "outlook"},
        get_jwt_secret(),
        algorithm="HS256",
    )
    return {"authorize_url": build_authorize_url(state)}


@router.get("/callback")
def callback(code: str, state: str, session: DbSession):
    try:
        payload = pyjwt.decode(state, get_jwt_secret(), algorithms=["HS256"])
    except pyjwt.PyJWTError as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from exc
    if payload.get("provider") != "outlook":
        raise HTTPException(status_code=400, detail="Provider mismatch")

    tenant = session.get(Tenant, str(payload.get("sub", "")))
    if tenant is None:
        raise HTTPException(status_code=404, detail="Unknown tenant")

    try:
        client_id, client_secret, base_url = get_outlook_config()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    tokens = exchange_code(code, client_id, client_secret, f"{base_url}/api/outlook/callback")
    config = {}
    if tenant.provider_config:
        try:
            config = json.loads(tenant.provider_config)
        except (TypeError, ValueError):
            config = {}
    config["refresh_token"] = tokens.get("refresh_token", "")
    tenant.provider_config = json.dumps(config)
    tenant.calendar_provider = "outlook"
    session.commit()
    return {"ok": True}

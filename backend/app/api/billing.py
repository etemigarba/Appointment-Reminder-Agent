"""Stripe subscription billing API (PRD §7).

Checkout/portal require a tenant JWT; the webhook verifies Stripe's
HMAC-SHA256 signature (t + v1 scheme) using stdlib only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time

from fastapi import APIRouter, HTTPException, Request, Response

from app.billing.stripe_client import StripeClient
from app.core.deps import CurrentTenant, DbSession
from app.models.entities import Tenant

router = APIRouter(prefix="/api/billing")
webhook_router = APIRouter()

WEBHOOK_TOLERANCE_SECONDS = 300


def get_stripe_client() -> StripeClient:
    secret = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret:
        raise HTTPException(status_code=503, detail="Stripe is not configured")
    return StripeClient(secret)


def _env(name: str) -> str:
    return os.environ.get(name, "")


# --- signature verification -------------------------------------------------


def verify_stripe_signature(payload: bytes, header: str, secret: str) -> bool:
    """Validate Stripe-Signature: 't=<ts>,v1=<hex>' over '<ts>.<payload>'."""
    parts = dict(
        piece.split("=", 1) for piece in header.split(",") if "=" in piece
    )
    timestamp = parts.get("t", "")
    signatures = [v for k, v in parts.items() if k == "v1"]
    if not timestamp or not signatures:
        return False
    try:
        if abs(time.time() - int(timestamp)) > WEBHOOK_TOLERANCE_SECONDS:
            return False
    except ValueError:
        return False
    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return any(hmac.compare_digest(expected, provided) for provided in signatures)


# --- authenticated endpoints -------------------------------------------------


def _require_config():
    if not _env("STRIPE_SECRET_KEY") or not _env("STRIPE_PRICE_ID"):
        raise HTTPException(status_code=503, detail="Billing is not configured")


@router.post("/checkout")
def create_checkout(tenant: CurrentTenant, session: DbSession):
    _require_config()
    base_url = _env("APP_PUBLIC_BASE_URL").rstrip("/")
    if not base_url:
        raise HTTPException(status_code=503, detail="APP_PUBLIC_BASE_URL must be set")

    stripe = get_stripe_client()
    customer_id = stripe.ensure_customer(
        tenant_id=tenant.id, email=tenant.email, existing_customer_id=tenant.stripe_customer_id
    )
    tenant.stripe_customer_id = customer_id
    session.commit()

    checkout = stripe.create_checkout_session(
        customer_id=customer_id,
        price_id=_env("STRIPE_PRICE_ID"),
        success_url=f"{base_url}/settings?billing=success",
        cancel_url=f"{base_url}/settings?billing=cancelled",
    )
    return {"checkout_url": checkout["url"]}


@router.post("/portal")
def create_portal_session(tenant: CurrentTenant):
    _require_config()
    if not tenant.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing profile yet — subscribe first")
    base_url = _env("APP_PUBLIC_BASE_URL").rstrip("/")
    stripe = get_stripe_client()
    portal = stripe.create_portal_session(
        customer_id=tenant.stripe_customer_id,
        return_url=f"{base_url}/settings",
    )
    return {"portal_url": portal["url"]}


# --- webhook ------------------------------------------------------------------


def apply_subscription_event(session, tenant_id: str, status: str, plan: str | None) -> None:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        return
    tenant.subscription_status = status
    if plan is not None:
        tenant.plan = plan


@webhook_router.post("/webhooks/stripe", include_in_schema=False)
async def stripe_webhook(request: Request) -> Response:
    payload = await request.body()
    signature_header = request.headers.get("Stripe-Signature", "")
    secret = _env("STRIPE_WEBHOOK_SECRET")
    if not secret or not verify_stripe_signature(payload, signature_header, secret):
        return Response(status_code=400)

    event = json.loads(payload)
    event_type = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    metadata = obj.get("metadata") or {}
    tenant_id = metadata.get("tenant_id")

    session_factory = request.app.state.session_factory
    with session_factory() as db:
        if event_type == "checkout.session.completed":
            if tenant_id:
                apply_subscription_event(db, tenant_id, "active", "pro")
        elif event_type == "customer.subscription.updated":
            if tenant_id:
                apply_subscription_event(db, tenant_id, obj.get("status", "active"), None)
        elif event_type == "customer.subscription.deleted":
            if tenant_id:
                apply_subscription_event(db, tenant_id, "canceled", "none")
        db.commit()

    return Response(status_code=200)

"""Inbound messaging webhooks (Twilio SMS/WhatsApp).

Signature validation follows the Twilio spec (HMAC-SHA1 over URL + sorted
params) using only the stdlib; it activates when TWILIO_AUTH_TOKEN is set.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import Response
from sqlalchemy import select

from app.agents.agent import handle_inbound_message
from app.agents.llm_client import DeepSeekClient, LLMClient
from app.core.db import session_scope
from app.models.entities import Channel, Customer, Tenant

logger = logging.getLogger(__name__)

router = APIRouter()


def compute_twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    data = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
    digest = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def signature_valid(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    return hmac.compare_digest(compute_twilio_signature(auth_token, url, params), signature)


@router.post("/webhooks/twilio")
async def twilio_inbound(request: Request) -> Response:
    form = dict(await request.form())
    from_number = form.get("From", "")
    to_number = form.get("To", "")
    body = form.get("Body", "")

    auth_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if auth_token:
        signature = request.headers.get("X-Twilio-Signature", "")
        if not signature_valid(auth_token, str(request.url), form, signature):
            logger.warning("Invalid Twilio signature for message to %s", to_number)
            return Response(status_code=403)

    session_factory = request.app.state.session_factory
    llm: LLMClient | None = getattr(request.app.state, "llm_client", None)
    if llm is None:
        try:
            llm = DeepSeekClient()
        except RuntimeError:
            logger.error("No LLM client configured; cannot process inbound message")
            return Response(status_code=503)

    with session_scope(session_factory) as session:
        tenant = session.scalar(select(Tenant).where(Tenant.twilio_number == to_number))
        if tenant is None:
            logger.warning("No tenant bound to Twilio number %s", to_number)
            return Response(status_code=404)
        customer = session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant.id,
                Customer.phone == from_number,
            )
        )
        if customer is None:
            customer = Customer(
                tenant_id=tenant.id,
                phone=from_number,
                name=form.get("ProfileName", "") or "",
            )
            session.add(customer)
            session.flush()

        channel = Channel.WHATSAPP.value if to_number.startswith("whatsapp:") else Channel.SMS.value
        customer.phone = from_number.removeprefix("whatsapp:") or customer.phone
        handle_inbound_message(
            session,
            llm,
            tenant=tenant,
            customer=customer,
            channel=channel,
            body=body,
        )

    return Response(status_code=200)

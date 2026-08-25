"""Real outbound channel senders: Twilio (SMS/WhatsApp) and Resend (Email).

All senders are thin HTTP adapters over httpx and are fully mockable in
tests via httpx.MockTransport or by injecting a transport.
"""

from __future__ import annotations

import base64
import os

import httpx

from app.channels.base import SendResult

TWILIO_API_BASE = "https://api.twilio.com/2010-04-01"
RESEND_API_URL = "https://api.resend.com/emails"
DEFAULT_TIMEOUT_SECONDS = 10.0


def _whatsapp_address(phone: str) -> str:
    return phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"


class TwilioSender:
    """Sends SMS or WhatsApp messages through the Twilio REST API."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        *,
        channel: str = "sms",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.channel_name = channel
        credentials = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()
        headers = {"Authorization": f"Basic {credentials}"}
        self._client = httpx.Client(
            base_url=TWILIO_API_BASE, headers=headers, timeout=DEFAULT_TIMEOUT_SECONDS, transport=transport
        )

    def send(self, *, to: str, body: str) -> SendResult:
        to_address = _whatsapp_address(to) if self.channel_name == "whatsapp" else to
        response = self._client.post(
            f"/Accounts/{self.account_sid}/Messages.json",
            data={"From": _whatsapp_address(self.from_number) if self.channel_name == "whatsapp" else self.from_number, "To": to_address, "Body": body},
        )
        if response.status_code >= 400:
            return SendResult(ok=False, error=f"twilio_{response.status_code}: {response.text[:200]}")
        return SendResult(ok=True, provider_message_id=response.json().get("sid"))


class ResendEmailSender:
    """Sends transactional email through the Resend HTTP API."""

    def __init__(self, api_key: str, from_address: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self.from_address = from_address
        self.channel_name = "email"
        self._client = httpx.Client(
            base_url=RESEND_API_URL.rsplit("/emails", 1)[0],
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=DEFAULT_TIMEOUT_SECONDS,
            transport=transport,
        )
        self._path = "/emails"

    def send(self, *, to: str, body: str) -> SendResult:
        response = self._client.post(
            self._path,
            json={
                "from": self.from_address,
                "to": [to],
                "subject": "Your appointment reminder",
                "text": body,
            },
        )
        if response.status_code >= 400:
            return SendResult(ok=False, error=f"resend_{response.status_code}: {response.text[:200]}")
        return SendResult(ok=True, provider_message_id=response.json().get("id"))


def build_adapters() -> dict[str, object]:
    """Build channel adapters from environment; fall back to stubs when unconfigured.

    Never raises for missing credentials — dev/test environments keep working.
    """
    from app.channels.stubs import LoggingStubAdapter

    twilio_sid = os.environ.get("TWILIO_ACCOUNT_SID", "")
    twilio_token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    sms_from = os.environ.get("TWILIO_SMS_FROM", "")
    whatsapp_from = os.environ.get("TWILIO_WHATSAPP_FROM", "")

    adapters: dict[str, object] = {}
    if twilio_sid and twilio_token and sms_from:
        adapters["sms"] = TwilioSender(twilio_sid, twilio_token, sms_from, channel="sms")
    else:
        adapters["sms"] = LoggingStubAdapter()

    if twilio_sid and twilio_token and whatsapp_from:
        adapters["whatsapp"] = TwilioSender(twilio_sid, twilio_token, whatsapp_from, channel="whatsapp")
    else:
        adapters["whatsapp"] = LoggingStubAdapter()

    resend_key = os.environ.get("RESEND_API_KEY", "")
    resend_from = os.environ.get("RESEND_FROM", "")
    if resend_key and resend_from:
        adapters["email"] = ResendEmailSender(resend_key, resend_from)
    else:
        adapters["email"] = LoggingStubAdapter()

    meta_token = os.environ.get("META_WHATSAPP_TOKEN", "")
    meta_phone_id = os.environ.get("META_PHONE_NUMBER_ID", "")
    if meta_token and meta_phone_id:
        # Native Meta WhatsApp takes precedence over Twilio-hosted WhatsApp.
        from app.channels.meta_whatsapp import MetaWhatsAppSender

        adapters["whatsapp"] = MetaWhatsAppSender(meta_token, meta_phone_id)

    return adapters

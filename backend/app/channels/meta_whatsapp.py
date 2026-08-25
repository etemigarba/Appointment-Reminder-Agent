"""Meta WhatsApp Cloud API sender (native, PRD §7)."""

from __future__ import annotations

import httpx

from app.channels.base import SendResult

GRAPH_API_BASE = "https://graph.facebook.com/v20.0"
DEFAULT_TIMEOUT_SECONDS = 10.0


class MetaWhatsAppSender:
    """Sends WhatsApp messages via the Meta Cloud API.

    `to` numbers are stored bare (+1555...); the API expects them without
    the whatsapp: prefix.
    """

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.phone_number_id = phone_number_id
        self.channel_name = "whatsapp"
        self._client = httpx.Client(
            base_url=GRAPH_API_BASE,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
            transport=transport,
        )

    def send(self, *, to: str, body: str) -> SendResult:
        to_number = to.removeprefix("whatsapp:")
        response = self._client.post(
            f"/{self.phone_number_id}/messages",
            json={
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "text",
                "text": {"body": body},
            },
        )
        if response.status_code >= 400:
            return SendResult(
                ok=False, error=f"meta_whatsapp_{response.status_code}: {response.text[:200]}"
            )
        message = (response.json().get("messages") or [{}])[0]
        return SendResult(ok=True, provider_message_id=message.get("id"))

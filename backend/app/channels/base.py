"""Channel adapter protocol shared by SMS / Email / WhatsApp senders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SendResult:
    ok: bool
    provider_message_id: str | None = None
    error: str | None = None


class ChannelAdapter(Protocol):
    def send(self, *, to: str, body: str) -> SendResult:
        """Deliver `body` to `to` (phone number or email address)."""
        ...

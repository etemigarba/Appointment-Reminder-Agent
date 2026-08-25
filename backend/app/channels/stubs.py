"""Stub channel adapters — real Twilio/Resend implementations arrive in Phase 2/4.

Stubs log the message and report success so the dispatch cycle can be
exercised end-to-end without external credentials.
"""

from __future__ import annotations

import logging

from app.channels.base import SendResult

logger = logging.getLogger(__name__)


class LoggingStubAdapter:
    channel_name = "stub"

    def send(self, *, to: str, body: str) -> SendResult:
        logger.info("[%s] to=%s body=%r", self.channel_name, to, body)
        return SendResult(ok=True, provider_message_id=f"stub-{self.channel_name}-{abs(hash((to, body))) % 10**10}")

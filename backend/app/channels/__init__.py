"""Outbound messaging channel adapters."""

from app.channels.base import ChannelAdapter, SendResult
from app.channels.stubs import LoggingStubAdapter

__all__ = ["ChannelAdapter", "LoggingStubAdapter", "SendResult"]

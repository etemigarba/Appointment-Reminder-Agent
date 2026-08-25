"""Conversational agent package (DeepSeek-backed, mockable)."""

from app.agents.llm_client import AssistantTurn, DeepSeekClient, FakeLLMClient, LLMClient, ToolCall
from app.agents.agent import handle_inbound_message, is_stop_message
from app.agents.tools import TOOLS_SCHEMA, TOOL_HANDLERS, ToolContext, apply_cancel, apply_reschedule

__all__ = [
    "AssistantTurn",
    "DeepSeekClient",
    "FakeLLMClient",
    "LLMClient",
    "TOOL_HANDLERS",
    "TOOLS_SCHEMA",
    "ToolCall",
    "ToolContext",
    "apply_cancel",
    "apply_reschedule",
    "handle_inbound_message",
    "is_stop_message",
]

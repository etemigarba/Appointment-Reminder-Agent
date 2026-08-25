"""Inbound message orchestration: STOP handling, agent tool loop, persistence."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.llm_client import LLMClient
from app.agents.prompts import SYSTEM_PROMPT
from app.agents.tools import TOOLS_SCHEMA, TOOL_HANDLERS, ToolContext
from app.models.entities import (
    Channel,
    ConsentRecord,
    Conversation,
    ConversationStatus,
    Customer,
    Message,
    MessageDirection,
    utcnow,
)

logger = logging.getLogger(__name__)

STOP_KEYWORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL MESSAGES", "END", "QUIT"}
MAX_TOOL_ROUNDS = 5


def is_stop_message(body: str) -> bool:
    return body.strip().upper() in STOP_KEYWORDS


def handle_inbound_message(
    session: Session,
    llm: LLMClient,
    *,
    tenant,
    customer: Customer,
    channel: str,
    body: str,
) -> str:
    """Process one inbound customer message; returns the outbound reply text."""
    conversation = _get_or_create_conversation(session, tenant=tenant, customer=customer, channel=channel)

    session.add(
        Message(
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND.value,
            channel=channel,
            body=body,
        )
    )

    if channel in (Channel.SMS.value, Channel.WHATSAPP.value) and is_stop_message(body):
        customer.opted_out = True
        session.add(
            ConsentRecord(customer_id=customer.id, channel=channel, granted=False)
        )
        reply = "You have been unsubscribed and will receive no further messages."
        session.add(_outbound(conversation.id, channel, reply))
        session.commit()
        return reply

    history = _recent_history(session, conversation.id)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(business_name=tenant.name)},
        *history,
        {"role": "user", "content": body},
    ]

    ctx = ToolContext(session=session, tenant=tenant, customer=customer, conversation=conversation)

    for _ in range(MAX_TOOL_ROUNDS):
        turn = llm.chat(messages, TOOLS_SCHEMA)
        if not turn.tool_calls:
            reply = turn.content or ""
            break
        messages.append(
            {
                "role": "assistant",
                "content": turn.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in turn.tool_calls
                ],
            }
        )
        for tc in turn.tool_calls:
            result = _execute_tool(ctx, tc.name, tc.arguments)
            messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)}
            )
    else:
        reply = (
            "Sorry — I couldn't complete that. Your request has been flagged "
            "for the team to follow up personally."
        )
        logger.warning("Agent hit tool-round limit for conversation %s", conversation.id)

    session.add(_outbound(conversation.id, channel, reply))
    session.commit()
    return reply


def _execute_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return {"error": f"Unknown tool {name!r}"}
    try:
        return handler(ctx, **arguments)
    except TypeError as exc:
        logger.warning("Tool %s called with bad arguments: %s", name, exc)
        return {"error": f"Invalid arguments for {name}: {exc}"}


def _get_or_create_conversation(session: Session, *, tenant, customer: Customer, channel: str) -> Conversation:
    conversation = session.scalar(
        select(Conversation).where(
            Conversation.tenant_id == tenant.id,
            Conversation.customer_id == customer.id,
            Conversation.channel == channel,
            Conversation.status == ConversationStatus.OPEN.value,
        )
    )
    if conversation is None:
        conversation = Conversation(tenant_id=tenant.id, customer_id=customer.id, channel=channel)
        session.add(conversation)
        session.flush()
    return conversation


def _outbound(conversation_id: str, channel: str, body: str) -> Message:
    return Message(
        conversation_id=conversation_id,
        direction=MessageDirection.OUTBOUND.value,
        channel=channel,
        body=body,
    )


def _recent_history(session: Session, conversation_id: str, limit: int = 10) -> list[dict[str, str]]:
    messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    role_map = {MessageDirection.INBOUND.value: "user", MessageDirection.OUTBOUND.value: "assistant"}
    return [{"role": role_map[m.direction], "content": m.body} for m in reversed(messages)]

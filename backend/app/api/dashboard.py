"""Tenant dashboard API: settings, appointments, conversations."""

from __future__ import annotations

import json
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.channels.templates import MAX_TEMPLATE_LENGTH
from app.core.deps import CurrentTenant, DbSession
from app.models.entities import (
    Appointment,
    Conversation,
    Customer,
    Message,
)

router = APIRouter(prefix="/api")


class SettingsIn(BaseModel):
    approval_mode: bool | None = None
    reminder_offsets_minutes: list[int] | None = None
    reminder_template: str | None = Field(default=None, max_length=MAX_TEMPLATE_LENGTH)
    timezone: str | None = None
    calendar_provider: str | None = None


class SettingsOut(BaseModel):
    name: str
    email: str
    approval_mode: bool
    reminder_offsets_minutes: list[int]
    reminder_template: str | None
    timezone: str
    twilio_number: str | None
    google_connected: bool
    calendar_provider: str
    plan: str
    subscription_status: str


class AppointmentOut(BaseModel):
    id: str
    title: str
    start_at: str
    end_at: str | None
    status: str
    customer_name: str | None = None


class ConversationOut(BaseModel):
    id: str
    customer_name: str | None
    channel: str
    status: str


class MessageOut(BaseModel):
    id: str
    direction: str
    body: str
    created_at: str


@router.get("/settings", response_model=SettingsOut)
def get_settings(tenant: CurrentTenant):
    return _settings_out(tenant)


def _settings_out(tenant) -> SettingsOut:
    return SettingsOut(
        name=tenant.name,
        email=tenant.email,
        approval_mode=tenant.approval_mode,
        reminder_offsets_minutes=tenant.reminder_offsets_minutes or [-1440, -120],
        reminder_template=tenant.reminder_template,
        timezone=tenant.timezone or "UTC",
        twilio_number=tenant.twilio_number,
        google_connected=bool(tenant.google_refresh_token),
        calendar_provider=tenant.calendar_provider or "google",
        plan=tenant.plan or "none",
        subscription_status=tenant.subscription_status or "none",
    )


@router.patch("/settings", response_model=SettingsOut)
def patch_settings(payload: SettingsIn, tenant: CurrentTenant, session: DbSession):
    if payload.approval_mode is not None:
        tenant.approval_mode = payload.approval_mode
    if payload.reminder_offsets_minutes is not None:
        offsets = [int(o) for o in payload.reminder_offsets_minutes]
        if not offsets or any(o >= 0 for o in offsets):
            raise HTTPException(status_code=422, detail="Offsets must be negative minutes before start")
        tenant.reminder_offsets_minutes = offsets
    if payload.reminder_template is not None:
        tenant.reminder_template = payload.reminder_template.strip() or None
    if payload.timezone is not None:
        try:
            ZoneInfo(payload.timezone)
        except Exception as exc:
            raise HTTPException(status_code=422, detail="Unknown IANA timezone") from exc
        tenant.timezone = payload.timezone
    if payload.calendar_provider is not None:
        provider = payload.calendar_provider.lower()
        if provider not in ("google", "outlook", "calendly"):
            raise HTTPException(status_code=422, detail="Unsupported calendar provider")
        tenant.calendar_provider = provider
    session.commit()
    return _settings_out(tenant)


class CalendlyTokenIn(BaseModel):
    api_token: str


@router.post("/calendars/calendly")
def set_calendly_token(payload: CalendlyTokenIn, tenant: CurrentTenant, session: DbSession):
    """Store a Calendly personal access token for the sync worker."""
    config = {}
    if tenant.provider_config:
        try:
            config = json.loads(tenant.provider_config)
        except (TypeError, ValueError):
            config = {}
    config["api_token"] = payload.api_token
    tenant.provider_config = json.dumps(config)
    tenant.calendar_provider = "calendly"
    session.commit()
    return {"ok": True}


@router.get("/appointments", response_model=list[AppointmentOut])
def list_appointments(tenant: CurrentTenant, session: DbSession):
    appointments = session.scalars(
        select(Appointment)
        .where(Appointment.tenant_id == tenant.id)
        .order_by(Appointment.start_at.desc())
        .limit(200)
    ).all()
    customer_ids = {a.customer_id for a in appointments if a.customer_id}
    customers = {
        c.id: c.name for c in session.scalars(select(Customer).where(Customer.id.in_(customer_ids))).all()
    } if customer_ids else {}
    return [
        AppointmentOut(
            id=a.id,
            title=a.title,
            start_at=a.start_at.isoformat(),
            end_at=a.end_at.isoformat() if a.end_at else None,
            status=a.status,
            customer_name=customers.get(a.customer_id),
        )
        for a in appointments
    ]


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(tenant: CurrentTenant, session: DbSession):
    rows = session.execute(
        select(Conversation, Customer)
        .join(Customer, Conversation.customer_id == Customer.id)
        .where(Conversation.tenant_id == tenant.id)
        .order_by(Conversation.created_at.desc())
        .limit(100)
    ).all()
    return [
        ConversationOut(
            id=conversation.id,
            customer_name=customer.name,
            channel=conversation.channel,
            status=conversation.status,
        )
        for conversation, customer in rows
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: str, tenant: CurrentTenant, session: DbSession):
    conversation = session.get(Conversation, conversation_id)
    if conversation is None or conversation.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .limit(500)
    ).all()
    return [
        MessageOut(id=m.id, direction=m.direction, body=m.body, created_at=m.created_at.isoformat())
        for m in messages
    ]

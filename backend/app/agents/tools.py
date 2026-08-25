"""Agent tool implementations.

Guardrails are enforced in code: every mutation tool requires an explicit
``confirmed_by_customer=True`` argument, and slot proposals are validated
against the calendar before being accepted (PRD FR-13).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.calendar_sync.slots import find_free_slots, overlaps_existing
from app.models.entities import (
    Appointment,
    AppointmentStatus,
    Conversation,
    Customer,
    PendingAction,
    PendingActionStatus,
    PendingActionType,
    Tenant,
    utcnow,
)
from app.scheduler.reminder_service import delete_pending_jobs, generate_reminder_jobs

MAX_LISTED_APPOINTMENTS = 5


@dataclass
class ToolContext:
    session: Session
    tenant: Tenant
    customer: Customer
    conversation: Conversation | None = None

    @property
    def approval_mode(self) -> bool:
        return self.tenant.approval_mode


def _refusal(action: str) -> dict[str, Any]:
    return {
        "error": f"REFUSED_{action.upper()}: the customer has not explicitly confirmed this "
        "action yet. Ask them to confirm clearly, then retry with confirmed_by_customer=true."
    }


def _upcoming_appointments(ctx: ToolContext) -> list[Appointment]:
    now = utcnow()
    appointments = ctx.session.scalars(
        select(Appointment).where(
            Appointment.tenant_id == ctx.tenant.id,
            Appointment.customer_id == ctx.customer.id,
            Appointment.start_at >= now - timedelta(hours=2),
            Appointment.status.in_([AppointmentStatus.SCHEDULED.value, AppointmentStatus.CONFIRMED.value]),
        )
    ).all()
    return sorted(appointments, key=lambda a: a.start_at)[:MAX_LISTED_APPOINTMENTS]


def _get_own_appointment(ctx: ToolContext, appointment_id: str) -> Appointment | None:
    return ctx.session.scalar(
        select(Appointment).where(
            Appointment.id == appointment_id,
            Appointment.customer_id == ctx.customer.id,
            Appointment.tenant_id == ctx.tenant.id,
        )
    )


def get_my_appointments(ctx: ToolContext) -> dict[str, Any]:
    appointments = _upcoming_appointments(ctx)
    if not appointments:
        return {"appointments": []}
    return {
        "appointments": [
            {
                "id": a.id,
                "title": a.title,
                "start": a.start_at.isoformat(),
                "status": a.status,
            }
            for a in appointments
        ]
    }


def find_slots(ctx: ToolContext, day: str) -> dict[str, Any]:
    try:
        target_date = date_from_iso(day)
    except ValueError:
        return {"error": f"Invalid date {day!r}; use YYYY-MM-DD."}
    slots = find_free_slots(
        ctx.session,
        tenant_id=ctx.tenant.id,
        day=target_date,
    )
    return {"day": day, "available_starts": [s.isoformat() for s in slots]}


def confirm_appointment(
    ctx: ToolContext, appointment_id: str, confirmed_by_customer: bool = False
) -> dict[str, Any]:
    if not confirmed_by_customer:
        return _refusal("confirm")
    appointment = _get_own_appointment(ctx, appointment_id)
    if appointment is None:
        return {"error": "No such upcoming appointment for this customer."}
    appointment.status = AppointmentStatus.CONFIRMED.value
    ctx.session.commit()
    return {"ok": True, "appointment_id": appointment.id, "status": appointment.status}


def cancel_appointment(
    ctx: ToolContext, appointment_id: str, confirmed_by_customer: bool = False
) -> dict[str, Any]:
    if not confirmed_by_customer:
        return _refusal("cancel")
    appointment = _get_own_appointment(ctx, appointment_id)
    if appointment is None:
        return {"error": "No such upcoming appointment for this customer."}

    if ctx.approval_mode:
        action = PendingAction(
            tenant_id=ctx.tenant.id,
            appointment_id=appointment.id,
            action_type=PendingActionType.CANCEL.value,
            payload={"requested_by": ctx.customer.id},
        )
        ctx.session.add(action)
        ctx.session.commit()
        return {"ok": True, "queued_for_approval": True, "action_id": action.id}

    apply_cancel(ctx.session, action_payload={}, appointment=appointment)
    return {"ok": True, "cancelled": True}


def propose_reschedule(
    ctx: ToolContext,
    appointment_id: str,
    new_start: str,
    confirmed_by_customer: bool = False,
) -> dict[str, Any]:
    if not confirmed_by_customer:
        return _refusal("reschedule")
    appointment = _get_own_appointment(ctx, appointment_id)
    if appointment is None:
        return {"error": "No such upcoming appointment for this customer."}
    try:
        new_start_dt = datetime.fromisoformat(new_start)
    except ValueError:
        return {"error": f"Invalid datetime {new_start!r}; use ISO-8601."}
    if new_start_dt.tzinfo is None:
        new_start_dt = new_start_dt.replace(tzinfo=UTC)
    if overlaps_existing(ctx.session, ctx.tenant.id, new_start_dt, appointment.id):
        return {"error": "That time is no longer available; offer another slot."}

    if ctx.approval_mode:
        action = PendingAction(
            tenant_id=ctx.tenant.id,
            appointment_id=appointment.id,
            action_type=PendingActionType.RESCHEDULE.value,
            payload={"new_start": new_start_dt.isoformat(), "requested_by": ctx.customer.id},
        )
        ctx.session.add(action)
        ctx.session.commit()
        return {"ok": True, "queued_for_approval": True, "action_id": action.id}

    apply_reschedule(ctx.session, new_start=new_start_dt, appointment=appointment,
                     offsets_minutes=_tenant_offsets(ctx.tenant))
    return {"ok": True, "rescheduled_to": new_start_dt.isoformat()}


def _tenant_offsets(tenant: Tenant) -> tuple[int, ...]:
    raw = tenant.reminder_offsets_minutes or [-1440, -120]
    return tuple(int(o) for o in raw)


def escalate_to_owner(ctx: ToolContext, reason: str) -> dict[str, Any]:
    return {"ok": True, "escalated": True, "reason": reason[:200]}


def apply_cancel(session: Session, *, action_payload: dict[str, Any], appointment: Appointment) -> None:
    appointment.status = AppointmentStatus.CANCELLED.value
    cancel_jobs_for_appointment(session, appointment.id)


def apply_reschedule(
    session: Session,
    *,
    new_start: datetime,
    appointment: Appointment,
    offsets_minutes: tuple[int, ...],
) -> None:
    duration = (
        appointment.end_at - appointment.start_at
        if appointment.end_at
        else timedelta(hours=1)
    )
    appointment.start_at = new_start
    appointment.end_at = new_start + duration
    appointment.status = AppointmentStatus.RESCHEDULED.value
    delete_pending_jobs(session, appointment.id)
    generate_reminder_jobs(session, offsets_minutes=offsets_minutes, horizon_hours=24 * 30)


def date_from_iso(raw: str):
    from datetime import date

    return date.fromisoformat(raw)


TOOL_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_my_appointments": get_my_appointments,
    "find_free_slots": find_slots,
    "confirm_appointment": confirm_appointment,
    "cancel_appointment": cancel_appointment,
    "propose_reschedule": propose_reschedule,
    "escalate_to_owner": escalate_to_owner,
}

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_my_appointments",
            "description": "List the customer's upcoming appointments.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_free_slots",
            "description": "List free appointment start times for a given day.",
            "parameters": {
                "type": "object",
                "properties": {"day": {"type": "string", "description": "YYYY-MM-DD"}},
                "required": ["day"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm_appointment",
            "description": "Mark one of the customer's appointments as confirmed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "confirmed_by_customer": {"type": "boolean"},
                },
                "required": ["appointment_id", "confirmed_by_customer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel one of the customer's appointments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "confirmed_by_customer": {"type": "boolean"},
                },
                "required": ["appointment_id", "confirmed_by_customer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_reschedule",
            "description": "Move one of the customer's appointments to a new start time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "appointment_id": {"type": "string"},
                    "new_start": {"type": "string", "description": "ISO-8601 datetime"},
                    "confirmed_by_customer": {"type": "boolean"},
                },
                "required": ["appointment_id", "new_start", "confirmed_by_customer"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_owner",
            "description": "Hand the conversation to the business owner.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string"}},
                "required": ["reason"],
            },
        },
    },
]

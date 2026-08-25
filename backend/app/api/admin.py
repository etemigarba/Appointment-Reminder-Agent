"""Owner-facing pending-action (approval queue) endpoints.

All routes require a valid tenant JWT; tenant identity comes from the token.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.core.deps import CurrentTenant, DbSession
from app.agents.tools import apply_cancel, apply_reschedule
from app.models.entities import (
    Appointment,
    PendingAction,
    PendingActionStatus,
    PendingActionType,
    utcnow,
)

router = APIRouter(prefix="/api")


def _get_action_or_404(session, action_id: str, tenant_id: str) -> PendingAction:
    action = session.get(PendingAction, action_id)
    if action is None or action.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="PendingAction not found")
    return action


class ActionOut(BaseModel):
    id: str
    appointment_id: str
    action_type: str
    payload: dict
    status: str


def _serialize(action: PendingAction) -> ActionOut:
    return ActionOut(
        id=action.id,
        appointment_id=action.appointment_id,
        action_type=action.action_type,
        payload=action.payload,
        status=action.status,
    )


@router.get("/pending-actions", response_model=list[ActionOut])
def list_pending_actions(tenant: CurrentTenant, session: DbSession):
    actions = session.scalars(
        select(PendingAction)
        .where(PendingAction.tenant_id == tenant.id)
        .order_by(PendingAction.created_at.desc())
    ).all()
    return [_serialize(a) for a in actions]


@router.post("/pending-actions/{action_id}/approve", response_model=ActionOut)
def approve_action(action_id: str, tenant: CurrentTenant, session: DbSession):
    action = _get_action_or_404(session, action_id, tenant.id)
    if action.status != PendingActionStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"Action already {action.status}")
    appointment = session.get(Appointment, action.appointment_id)
    if appointment is None:
        raise HTTPException(status_code=404, detail="Appointment not found")

    if action.action_type == PendingActionType.CANCEL.value:
        apply_cancel(session, action_payload=action.payload, appointment=appointment)
    elif action.action_type == PendingActionType.RESCHEDULE.value:
        new_start = datetime.fromisoformat(action.payload["new_start"])
        apply_reschedule(
            session,
            new_start=new_start,
            appointment=appointment,
            offsets_minutes=_tenant_offsets(tenant),
        )
    else:
        raise HTTPException(status_code=400, detail="Unknown action type")

    action.status = PendingActionStatus.APPROVED.value
    action.decided_at = utcnow()
    session.commit()
    return _serialize(action)


@router.post("/pending-actions/{action_id}/reject", response_model=ActionOut)
def reject_action(action_id: str, tenant: CurrentTenant, session: DbSession):
    action = _get_action_or_404(session, action_id, tenant.id)
    if action.status != PendingActionStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"Action already {action.status}")
    action.status = PendingActionStatus.REJECTED.value
    action.decided_at = utcnow()
    session.commit()
    return _serialize(action)


def _tenant_offsets(tenant):
    raw = tenant.reminder_offsets_minutes or [-1440, -120]
    return tuple(int(o) for o in raw)

"""APScheduler wiring for the reminder dispatch cycle."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import sessionmaker

from app.channels.base import ChannelAdapter, SendResult
from app.models.entities import Conversation, Customer, Message, MessageDirection
from app.scheduler.reminder_service import claim_due_jobs, generate_reminder_jobs, mark_sent

logger = logging.getLogger(__name__)


def run_dispatch_cycle(
    session_factory: sessionmaker,
    adapters: dict[str, ChannelAdapter],
    *,
    offsets_minutes: tuple[int, ...],
    horizon_hours: int,
) -> int:
    """Generate any new reminder jobs, then send every due one. Returns sends made."""
    with session_factory() as session:
        generate_reminder_jobs(session, offsets_minutes=offsets_minutes, horizon_hours=horizon_hours)
        due = claim_due_jobs(session)
        sent = 0
        for job in due:
            appointment = job.appointment
            customer = appointment.customer_id and session.get(Customer, appointment.customer_id)
            if customer is None or customer.opted_out:
                job.status = "cancelled"
                continue
            adapter = _pick_adapter(adapters, customer.preferred_channel)
            if adapter is None:
                logger.warning("No channel adapter bound; skipping job %s", job.id)
                continue
            to = customer.phone or customer.email or ""
            result = adapter.send(to=to, body=_render(job))
            if result.ok:
                mark_sent(job)
                _log_message(session, appointment.tenant_id, customer.id, appointment.id, customer.preferred_channel, result)
                sent += 1
            else:
                job.status = "failed"
        session.commit()
        return sent


FALLBACK_ORDER = ("sms", "whatsapp", "email")


def _pick_adapter(adapters: dict, preferred: str):
    for channel in (preferred, *FALLBACK_ORDER):
        adapter = adapters.get(channel)
        if adapter is not None:
            return adapter
    return None


def _render(job) -> str:
    start_local = job.appointment.start_at.strftime("%Y-%m-%d %H:%M UTC")
    return f"Reminder: '{job.appointment.title}' on {start_local}. Reply STOP to opt out."


def _log_message(session, tenant_id, customer_id, appointment_id, channel: str, result: SendResult) -> None:
    conversation = Conversation(
        tenant_id=tenant_id, customer_id=customer_id, appointment_id=appointment_id, channel=channel
    )
    session.add(conversation)
    session.flush()
    session.add(
        Message(
            conversation_id=conversation.id,
            direction=MessageDirection.OUTBOUND.value,
            channel="sms",
            body=result.provider_message_id or "",
        )
    )


def build_scheduler(
    session_factory: sessionmaker,
    adapters: dict[str, ChannelAdapter],
    *,
    interval_seconds: int,
    offsets_minutes: tuple[int, ...],
    horizon_hours: int,
) -> BlockingScheduler:
    scheduler = BlockingScheduler()

    def tick() -> None:
        try:
            run_dispatch_cycle(
                session_factory,
                adapters,
                offsets_minutes=offsets_minutes,
                horizon_hours=horizon_hours,
            )
        except Exception:
            logger.exception("Dispatch cycle failed")

    scheduler.add_job(
        tick, "interval", seconds=interval_seconds, id="reminder-dispatch", max_instances=1
    )
    return scheduler


def make_noop_adapters() -> dict[str, ChannelAdapter]:
    from app.channels.stubs import LoggingStubAdapter

    return {"sms": LoggingStubAdapter(), "email": LoggingStubAdapter(), "whatsapp": LoggingStubAdapter()}

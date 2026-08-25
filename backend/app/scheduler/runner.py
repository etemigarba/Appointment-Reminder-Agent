"""APScheduler wiring for the reminder dispatch cycle."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import sessionmaker

from app.channels.base import ChannelAdapter, SendResult
from app.channels.templates import render_reminder
from app.models.entities import Conversation, Customer, Message, MessageDirection, Tenant
from app.scheduler.reminder_service import claim_due_jobs, generate_reminder_jobs, mark_sent

logger = logging.getLogger(__name__)

SEND_WINDOW_START_HOUR = 8  # 08:00 local inclusive (PRD FR-16)
SEND_WINDOW_END_HOUR = 21   # exclusive — last permitted send ends 21:00


def is_within_send_window(now_utc: datetime, timezone_name: str) -> bool:
    """True when customer-local time falls in [08:00, 21:00). Unknown tz → UTC."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=dt_timezone.utc)
    try:
        tz = ZoneInfo(timezone_name or "UTC")
    except Exception:
        tz = dt_timezone.utc
    local = now_utc.astimezone(tz)
    return SEND_WINDOW_START_HOUR <= local.hour < SEND_WINDOW_END_HOUR


def run_dispatch_cycle(
    session_factory: sessionmaker,
    adapters: dict[str, ChannelAdapter],
    *,
    offsets_minutes: tuple[int, ...],
    horizon_hours: int,
    now: datetime | None = None,
) -> int:
    """Generate any new reminder jobs, then send every due one. Returns sends made.

    Jobs whose customer-local time is outside the send window stay PENDING
    (held, not failed) and are retried on a later tick (PRD FR-16).
    """
    now = now or datetime.now(dt_timezone.utc)
    with session_factory() as session:
        generate_reminder_jobs(
            session, offsets_minutes=offsets_minutes, horizon_hours=horizon_hours, now=now
        )
        due = claim_due_jobs(session, now=now)
        sent = 0
        for job in due:
            appointment = job.appointment
            tenant = appointment.tenant_id and session.get(Tenant, appointment.tenant_id)
            customer = appointment.customer_id and session.get(Customer, appointment.customer_id)
            if customer is None or customer.opted_out:
                job.status = "cancelled"
                continue
            if not is_within_send_window(now, getattr(tenant, "timezone", "UTC")):
                continue  # hold as PENDING; retried next tick inside the window
            adapter = _pick_adapter(adapters, customer.preferred_channel)
            if adapter is None:
                logger.warning("No channel adapter bound; skipping job %s", job.id)
                continue
            to = customer.phone or customer.email or ""
            body = render_reminder(
                template=getattr(tenant, "reminder_template", None),
                business_name=getattr(tenant, "name", ""),
                customer_name=customer.name,
                appointment_title=appointment.title,
                start_at_utc=appointment.start_at,
            )
            result = adapter.send(to=to, body=body)
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


SYNC_INTERVAL_SECONDS = 300  # PRD FR-2: poll at most every 5 minutes


def run_sync_cycle(session_factory: sessionmaker, client_factory=None, *, now=None) -> int:
    """Sync Google Calendar events for every tenant with a stored refresh token.

    `client_factory(tenant) -> GoogleCalendarClient` is injectable for tests.
    Tenants without tokens are skipped; per-tenant failures are logged, not fatal.
    Returns the number of tenants synced successfully.
    """
    from datetime import UTC, datetime as dt, timedelta

    from sqlalchemy import select

    from app.calendar_sync.client import GoogleCalendarRestClient
    from app.calendar_sync.sync_service import sync_appointments

    now = now or dt.now(dt_timezone.utc)
    synced = 0
    with session_factory() as session:
        tenants = session.scalars(
            select(Tenant).where(Tenant.google_refresh_token.is_not(None))
        ).all()
        for tenant in tenants:
            try:
                if client_factory is not None:
                    client = client_factory(tenant)
                else:
                    try:
                        from google.oauth2.credentials import Credentials

                        credentials = Credentials(
                            token=None,
                            refresh_token=tenant.google_refresh_token,
                            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
                            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
                            token_uri="https://oauth2.googleapis.com/token",
                        )
                    except ImportError:
                        logger.warning("google extra not installed; skipping live sync")
                        break
                    client = GoogleCalendarRestClient(
                        credentials, calendar_id=tenant.google_calendar_id or "primary"
                    )
                sync_appointments(
                    session,
                    client,
                    tenant_id=tenant.id,
                    time_min=now,
                    time_max=now + timedelta(days=30),
                )
                synced += 1
            except Exception:
                logger.exception("Calendar sync failed for tenant %s", tenant.id)
        return synced

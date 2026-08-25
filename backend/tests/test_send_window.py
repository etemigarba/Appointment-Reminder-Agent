"""C5: send-window enforcement (FR-16) — held jobs stay PENDING, never fail."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.models.entities import ReminderJob, ReminderJobStatus
from app.scheduler.runner import is_within_send_window, run_dispatch_cycle
from tests.conftest import make_appointment


class RecordingAdapter:
    def __init__(self):
        self.sent = []

    def send(self, *, to: str, body: str):
        self.sent.append((to, body))
        from app.channels.base import SendResult

        return SendResult(ok=True, provider_message_id="x")


def _run(db_session, tenant, adapters, now):
    return run_dispatch_cycle(
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        adapters,
        offsets_minutes=(-1440, -120),
        horizon_hours=168,
        now=now,
    )


def test_window_boundaries():
    utc_noon = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)  # 12:00 UTC
    assert is_within_send_window(utc_noon, "UTC") is True
    assert is_within_send_window(datetime(2026, 9, 3, 8, 0, tzinfo=UTC), "UTC") is True
    assert is_within_send_window(datetime(2026, 9, 3, 21, 0, tzinfo=UTC), "UTC") is False
    assert is_within_send_window(datetime(2026, 9, 3, 7, 59, tzinfo=UTC), "UTC") is False
    # tenant in Europe/London (UTC+1): 07:30 UTC == 08:30 local → allowed
    assert is_within_send_window(datetime(2026, 9, 3, 7, 30, tzinfo=UTC), "Europe/London") is True
    # unknown timezone falls back to UTC rules
    assert is_within_send_window(utc_noon, "Not/AZone") is True
    assert is_within_send_window(datetime(2026, 9, 3, 5, 0, tzinfo=UTC), "Not/AZone") is False


def test_outside_window_job_held_pending_and_sent_later(db_session, tenant, customer):
    tenant.timezone = "UTC"
    db_session.commit()
    # appointment starts at 10:00 on Sep 4; its T-120min reminder is due 08:00 same day (in window)
    start = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    make_appointment(db_session, tenant, customer, start_at=start)

    adapter = RecordingAdapter()
    now_night = datetime(2026, 9, 4, 2, 0, tzinfo=UTC)  # job not due yet anyway
    _run(db_session, tenant, {"sms": adapter}, now_night)

    # force a job due during the night window (02:30 local — outside 08-21)
    job = db_session.scalars(select(ReminderJob)).first()
    job.due_at = datetime(2026, 9, 4, 2, 30, tzinfo=UTC)
    job.status = ReminderJobStatus.PENDING.value
    db_session.commit()

    sent_night = run_dispatch_cycle(
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        {"sms": adapter},
        offsets_minutes=(-1440, -120),
        horizon_hours=168,
        now=datetime(2026, 9, 4, 2, 31, tzinfo=UTC),
    )
    assert sent_night == 0
    assert adapter.sent == []
    db_session.refresh(job)
    assert job.status == ReminderJobStatus.PENDING.value  # held, not failed/cancelled

    sent_morning = run_dispatch_cycle(
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        {"sms": adapter},
        offsets_minutes=(-1440, -120),
        horizon_hours=168,
        now=datetime(2026, 9, 4, 8, 1, tzinfo=UTC),
    )
    # only the held job exists (-1440 was stale beyond grace and never generated);
    # it becomes sendable once inside the window
    assert sent_morning == 1
    assert len(adapter.sent) == 1
    db_session.refresh(job)
    assert job.status == ReminderJobStatus.SENT.value


def test_template_flows_through_dispatch(db_session, tenant, customer):
    tenant.reminder_template = "Hi {name} — {title} at {time}. — {business}"
    tenant.timezone = "UTC"
    db_session.commit()
    start = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    make_appointment(db_session, tenant, customer, start_at=start)

    adapter = RecordingAdapter()
    _run(db_session, tenant, {"sms": adapter}, datetime(2026, 9, 4, 8, 5, tzinfo=UTC))

    assert len(adapter.sent) == 1
    body = adapter.sent[0][1]
    assert body == "Hi Jane Doe — Haircut at 10:00. — Test Salon"
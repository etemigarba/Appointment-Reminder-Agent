"""C4: channel senders + opted-out suppression in the dispatch cycle."""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.orm import sessionmaker

from app.channels.senders import ResendEmailSender, TwilioSender, build_adapters
from app.scheduler.reminder_service import generate_reminder_jobs
from app.scheduler.runner import run_dispatch_cycle
from tests.conftest import make_appointment

NOW = datetime.now(UTC)


def _twilio_transport(captured: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(201, json={"sid": "SM123"})

    return httpx.MockTransport(handler)


def test_twilio_sms_posts_correct_payload():
    captured: list[httpx.Request] = []
    sender = TwilioSender(
        "AC123", "token", "+15550007777", channel="sms", transport=_twilio_transport(captured)
    )

    result = sender.send(to="+15551234567", body="Reminder!")

    assert result.ok is True
    assert result.provider_message_id == "SM123"
    request = captured[0]
    assert f"/Accounts/AC123/Messages.json" in str(request.url)
    body = request.content.decode()
    assert "From=%2B15550007777" in body  # url-encoded +
    assert "To=%2B15551234567" in body
    assert "Body=Reminder%21" in body


def test_twilio_whatsapp_prefixes_addresses():
    captured: list[httpx.Request] = []
    sender = TwilioSender(
        "AC123", "token", "+15550007777", channel="whatsapp", transport=_twilio_transport(captured)
    )

    sender.send(to="whatsapp:+15551234567", body="hi")

    body = captured[0].content.decode()
    assert "From=whatsapp%3A%2B15550007777" in body
    assert "To=whatsapp%3A%2B15551234567" in body


def test_twilio_error_returns_failed_result():
    sender = TwilioSender(
        "AC123",
        "token",
        "+15550007777",
        transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"message": "bad number"})),
    )

    result = sender.send(to="+15551234567", body="x")

    assert result.ok is False
    assert result.error.startswith("twilio_400")


def test_resend_email_payload_and_auth():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"id": "em-1"})

    sender = ResendEmailSender("re_key_123", "reminders@biz.example", transport=httpx.MockTransport(handler))

    result = sender.send(to="jane@example.com", body="See you soon")

    assert result.ok is True
    assert result.provider_message_id == "em-1"
    request = captured[0]
    assert request.url.path.endswith("/emails")
    assert request.headers["Authorization"] == "Bearer re_key_123"
    assert b'"to":["jane@example.com"]' in request.content


def test_opted_out_customer_generates_zero_http_calls(db_session, tenant, customer):
    customer.opted_out = True
    customer.preferred_channel = "sms"
    db_session.commit()
    make_appointment(
        db_session,
        tenant,
        customer,
        start_at=NOW.replace(second=0, microsecond=0) + timedelta(hours=1, days=2),
    )
    generate_reminder_jobs(db_session)

    calls: list[httpx.Request] = []
    adapters = {
        "sms": TwilioSender("AC1", "t", "+1000", transport=_twilio_transport(calls)),
        "whatsapp": TwilioSender("AC1", "t", "+1000", channel="whatsapp", transport=_twilio_transport(calls)),
        "email": ResendEmailSender("k", "f@b.example", transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"id": "e"}))),
    }

    sent = run_dispatch_cycle(
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False),
        adapters,
        offsets_minutes=(-1440, -120),
        horizon_hours=168,
    )

    assert sent == 0
    assert calls == []


def test_build_adapters_falls_back_to_stubs_without_env(monkeypatch):
    for var in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_SMS_FROM", "TWILIO_WHATSAPP_FROM", "RESEND_API_KEY", "RESEND_FROM"):
        monkeypatch.delenv(var, raising=False)

    adapters = build_adapters()

    assert set(adapters) == {"sms", "whatsapp", "email"}
    for adapter in adapters.values():
        assert type(adapter).__name__ == "LoggingStubAdapter"

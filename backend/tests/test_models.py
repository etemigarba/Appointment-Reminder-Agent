"""Basic persistence round-trips over the core data model."""

from app.models.entities import (
    Channel,
    ConsentRecord,
    Conversation,
    Message,
    MessageDirection,
    PendingAction,
    PendingActionType,
    ReminderJob,
)


def test_tenant_customer_consent_roundtrip(db_session, tenant, customer):
    from tests.conftest import make_appointment

    from datetime import UTC, datetime, timedelta

    appointment = make_appointment(
        db_session, tenant, customer, start_at=datetime.now(UTC) + timedelta(hours=48)
    )
    consent = ConsentRecord(customer_id=customer.id, channel=Channel.SMS.value, granted=True)
    conversation = Conversation(
        tenant_id=tenant.id, customer_id=customer.id, channel="sms"
    )
    db_session.add_all([consent, conversation])
    db_session.commit()
    message = Message(
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND.value,
        channel="sms",
        body="confirm",
    )
    action = PendingAction(
        tenant_id=tenant.id,
        appointment_id=appointment.id,
        action_type=PendingActionType.RESCHEDULE.value,
        payload={"proposed_start": "2026-09-01T15:00:00+00:00"},
    )
    db_session.add_all([message, action])
    db_session.commit()

    db_session.refresh(consent)
    assert consent.granted is True
    assert message.conversation_id == conversation.id
    assert action.payload["proposed_start"].endswith("+00:00")


def test_duplicate_reminder_offset_rejected_by_constraint(db_session, tenant, customer):
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import exc as sa_exc

    from app.scheduler.reminder_service import generate_reminder_jobs
    from tests.conftest import make_appointment

    start = datetime.now(UTC) + timedelta(hours=48)
    appointment = make_appointment(db_session, tenant, customer, start_at=start)
    generate_reminder_jobs(db_session)

    duplicate = ReminderJob(
        appointment_id=appointment.id,
        offset_minutes=-120,
        due_at=start + timedelta(minutes=-120),
    )
    db_session.add(duplicate)
    try:
        db_session.commit()
        raised = False
    except sa_exc.IntegrityError:
        raised = True
        db_session.rollback()
    assert raised, "unique constraint on (appointment_id, offset_minutes) should fire"

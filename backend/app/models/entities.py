"""SQLAlchemy 2.0 entity definitions (PRD.MD section 6 data model).

All datetimes are timezone-aware UTC. Status enums use non-native
VARCHAR + CHECK constraints for portability across SQLite and PostgreSQL.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """DateTime column that always binds and returns timezone-aware UTC values.

    SQLite drops tzinfo; this decorator restores it so comparisons never mix
    offset-naive and offset-aware datetimes.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class AppointmentStatus(str, enum.Enum):
    SCHEDULED = "scheduled"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    RESCHEDULED = "rescheduled"


class ReminderJobStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConversationStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class MessageDirection(str, enum.Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class PendingActionType(str, enum.Enum):
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"


class PendingActionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Channel(str, enum.Enum):
    SMS = "sms"
    EMAIL = "email"
    WHATSAPP = "whatsapp"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    approval_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    reminder_offsets_minutes: Mapped[list[int]] = mapped_column(JSON, default=lambda: [-1440, -120])
    reminder_template: Mapped[str | None] = mapped_column(Text, default=None)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    google_refresh_token: Mapped[str | None] = mapped_column(String(500), default=None)
    google_calendar_id: Mapped[str | None] = mapped_column(String(320), default=None)
    twilio_number: Mapped[str | None] = mapped_column(String(32), unique=True, default=None)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    customers: Mapped[list[Customer]] = relationship(back_populates="tenant")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(32), default=None, index=True)
    email: Mapped[str | None] = mapped_column(String(320), default=None, index=True)
    preferred_channel: Mapped[str] = mapped_column(String(16), default=Channel.SMS.value)
    opted_out: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    tenant: Mapped[Tenant] = relationship(back_populates="customers")
    consents: Mapped[list[ConsentRecord]] = relationship(back_populates="customer")

    __table_args__ = (CheckConstraint("phone IS NOT NULL OR email IS NOT NULL", name="ck_customer_contact"),)


class ConsentRecord(Base):
    __tablename__ = "consent_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    channel: Mapped[Channel] = mapped_column(String(16))
    granted: Mapped[bool]
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)

    customer: Mapped[Customer] = relationship(back_populates="consents")


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[str | None] = mapped_column(ForeignKey("customers.id"), default=None)
    google_event_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500), default="")
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    status: Mapped[AppointmentStatus] = mapped_column(
        String(20), default=AppointmentStatus.SCHEDULED.value
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())

    reminders: Mapped[list[ReminderJob]] = relationship(back_populates="appointment")

    __table_args__ = (UniqueConstraint("tenant_id", "google_event_id", name="uq_appointment_event"),)


class ReminderJob(Base):
    """Idempotent per (appointment_id, offset_minutes) — PRD FR-8."""

    __tablename__ = "reminder_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"), index=True)
    offset_minutes: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[ReminderJobStatus] = mapped_column(
        String(16), default=ReminderJobStatus.PENDING.value
    )
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)

    appointment: Mapped[Appointment] = relationship(back_populates="reminders")

    __table_args__ = (
        UniqueConstraint("appointment_id", "offset_minutes", name="uq_reminder_offset"),
        CheckConstraint("offset_minutes < 0", name="ck_reminder_before_start"),
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), default=None)
    channel: Mapped[Channel] = mapped_column(String(16))
    status: Mapped[ConversationStatus] = mapped_column(
        String(12), default=ConversationStatus.OPEN.value
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[MessageDirection] = mapped_column(String(8))
    channel: Mapped[Channel] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())


class PendingAction(Base):
    """Owner-approval queue entry (PRD FR-12 approval mode)."""

    __tablename__ = "pending_actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"))
    action_type: Mapped[PendingActionType] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[PendingActionStatus] = mapped_column(
        String(12), default=PendingActionStatus.PENDING.value
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)


__all__ = [
    "Appointment",
    "AppointmentStatus",
    "Base",
    "Channel",
    "ConsentRecord",
    "Conversation",
    "ConversationStatus",
    "Customer",
    "Message",
    "MessageDirection",
    "PendingAction",
    "PendingActionStatus",
    "PendingActionType",
    "ReminderJob",
    "ReminderJobStatus",
    "Tenant",
    "utcnow",
]

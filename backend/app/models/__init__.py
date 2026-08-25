"""Data model package. Import entities here so `app.models` exposes the full schema."""

from app.core.db import make_engine, make_session_factory, session_scope  # noqa: F401
from app.models.entities import (  # noqa: F401
    Appointment,
    AppointmentStatus,
    Base,
    Channel,
    ConsentRecord,
    Conversation,
    ConversationStatus,
    Customer,
    Message,
    MessageDirection,
    PendingAction,
    PendingActionStatus,
    PendingActionType,
    ReminderJob,
    ReminderJobStatus,
    Tenant,
)

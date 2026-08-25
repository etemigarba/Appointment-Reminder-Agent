"""Shared fixtures: in-memory SQLite session per test."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.entities import (
    Appointment,
    AppointmentStatus,
    Base,
    Customer,
    Tenant,
)


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = factory()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def tenant(db_session: Session) -> Tenant:
    obj = Tenant(name="Test Salon", email="owner@test.example", password_hash="x")
    db_session.add(obj)
    db_session.commit()
    return obj


@pytest.fixture()
def customer(db_session: Session, tenant: Tenant) -> Customer:
    obj = Customer(tenant_id=tenant.id, name="Jane Doe", phone="+15551234567", email="jane@example.com")
    db_session.add(obj)
    db_session.commit()
    return obj


def make_appointment(
    db_session: Session,
    tenant: Tenant,
    customer: Customer | None,
    *,
    start_at,
    google_event_id: str = "evt_1",
    status: str = AppointmentStatus.SCHEDULED.value,
    title: str = "Haircut",
) -> Appointment:
    obj = Appointment(
        tenant_id=tenant.id,
        customer_id=customer.id if customer else None,
        google_event_id=google_event_id,
        title=title,
        start_at=start_at,
        status=status,
    )
    db_session.add(obj)
    db_session.commit()
    return obj

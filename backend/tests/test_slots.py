"""C8: free-slot finder — busy blocks excluded, working hours respected."""

from datetime import UTC, date, datetime

from app.calendar_sync.slots import find_free_slots, overlaps_existing
from tests.conftest import make_appointment

DAY = date(2026, 9, 2)  # Wednesday


def _at(hour, minute=0):
    return datetime(2026, 9, 2, hour, minute, tzinfo=UTC)


def test_busy_block_excluded_and_bounds_respected(db_session, tenant, customer):
    make_appointment(db_session, tenant, customer, start_at=_at(10), google_event_id="busy_1")

    slots = find_free_slots(db_session, tenant_id=tenant.id, day=DAY)

    assert slots[0] == _at(9)
    assert _at(10) not in slots
    assert _at(10, 30) not in slots
    assert _at(11) in slots
    assert slots[-1] == _at(16)  # last start where start+60min <= 17:00
    # every slot is grid-aligned and inside business hours
    for slot in slots:
        assert slot.minute in (0, 30)
        assert _at(9) <= slot < _at(17)


def test_overlapping_proposals_detected(db_session, tenant, customer):
    make_appointment(db_session, tenant, customer, start_at=_at(10), google_event_id="busy_1")

    assert overlaps_existing(db_session, tenant.id, _at(10, 30))
    assert overlaps_existing(
        db_session, tenant.id, _at(9, 30), exclude_appointment_id="some_other_id"
    )
    assert not overlaps_existing(db_session, tenant.id, _at(14))


def test_cancelled_appointments_do_not_block_slots(db_session, tenant, customer):
    make_appointment(
        db_session,
        tenant,
        customer,
        start_at=_at(10),
        status="cancelled",
        google_event_id="gone",
    )

    slots = find_free_slots(db_session, tenant_id=tenant.id, day=DAY)

    assert _at(10) in slots


def test_duration_must_fit_window(db_session, tenant):
    slots = find_free_slots(db_session, tenant_id=tenant.id, day=DAY, duration_minutes=90)

    assert slots[-1] == _at(15, 30)

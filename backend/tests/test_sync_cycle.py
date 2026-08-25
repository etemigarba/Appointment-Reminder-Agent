"""Worker sync cycle: tenants with tokens get synced, failures isolated (FR-2)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.scheduler.runner import run_sync_cycle
from app.models.entities import Tenant


class FakeClient:
    def __init__(self):
        self.calls = []

    def list_events(self, time_min, time_max):
        self.calls.append((time_min, time_max))
        return []


def test_sync_cycle_skips_tenants_without_tokens_and_syncs_connected(db_session):
    connected = Tenant(name="Connected", email="c@s.example", password_hash="x",
                       google_refresh_token="rt-1")
    disconnected = Tenant(name="Offline", email="o@s.example", password_hash="x")
    db_session.add_all([connected, disconnected])
    db_session.commit()

    clients = {}

    def client_factory(tenant):
        clients[tenant.id] = FakeClient()
        return clients[tenant.id]

    factory = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    synced = run_sync_cycle(factory, client_factory)

    assert synced == 1
    assert len(clients) == 1
    assert connected.id in clients
    # 30-day look-ahead window per PRD FR-2
    time_min, time_max = clients[connected.id].calls[0]
    assert time_max - time_min == timedelta(days=30)


def test_sync_cycle_isolates_per_tenant_failures(db_session):
    good = Tenant(name="Good", email="g2@s.example", password_hash="x",
                  google_refresh_token="rt-2")
    bad = Tenant(name="Bad", email="b2@s.example", password_hash="x",
                 google_refresh_token="rt-broken")
    db_session.add_all([good, bad])
    db_session.commit()

    def client_factory(tenant):
        if tenant.id == bad.id:
            raise RuntimeError("token expired")
        return FakeClient()

    synced = run_sync_cycle(
        sessionmaker(bind=db_session.get_bind(), expire_on_commit=False), client_factory
    )

    assert synced == 1  # the failing tenant did not abort the loop


_ = select  # parity guard

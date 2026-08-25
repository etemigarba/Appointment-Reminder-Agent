"""Reminder worker entrypoint: runs the dispatch cycle on a schedule.

Usage (container/production):  python -m app.worker
"""

from __future__ import annotations

import logging

from app.channels.senders import build_adapters
from app.core.config import get_settings
from app.core.db import make_engine, make_session_factory
from app.scheduler.runner import build_scheduler


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    engine = make_engine()
    factory = make_session_factory(engine)
    adapters = build_adapters()
    scheduler = build_scheduler(
        factory,
        adapters,
        interval_seconds=settings.dispatch_interval_seconds,
        offsets_minutes=(-1440, -120),
        horizon_hours=settings.reminder_horizon_hours,
    )
    logging.getLogger(__name__).info("Reminder worker started (interval=%ss)", settings.dispatch_interval_seconds)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()

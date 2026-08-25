"""Normalized calendar event shape shared by all providers (Google/Outlook/Calendly).

Providers translate their native payloads into this shape; the sync service
and slot finder consume only this.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class NormalizedEvent:
    id: str
    title: str
    start: str  # ISO-8601 with offset
    end: str | None
    attendee_emails: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["attendee_emails"] = list(d["attendee_emails"])
        return d

    @property
    def start_dt(self) -> datetime | None:
        return _parse(self.start)

    @property
    def end_dt(self) -> datetime | None:
        return _parse(self.end) if self.end else None


def _parse(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt

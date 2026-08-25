"""Reminder template rendering with tenant variables (PRD FR-7).

Supported variables: {name}, {date}, {time}, {business}, {title}.
Unknown placeholders are left untouched; rendering never raises.
"""

from __future__ import annotations

import re
from datetime import datetime

DEFAULT_TEMPLATE = "Reminder: '{title}' on {date} at {time}. — {business}. Reply STOP to opt out."

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")

MAX_TEMPLATE_LENGTH = 500


def render_reminder(
    *,
    template: str | None,
    business_name: str,
    customer_name: str | None,
    appointment_title: str,
    start_at_utc: datetime,
) -> str:
    chosen = (template or "").strip() or DEFAULT_TEMPLATE
    values = {
        "name": customer_name or "there",
        "business": business_name,
        "title": appointment_title or "your appointment",
        "date": start_at_utc.strftime("%Y-%m-%d"),
        "time": start_at_utc.strftime("%H:%M"),
    }
    return _PLACEHOLDER_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), chosen)

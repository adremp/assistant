"""Timezone utilities."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo


def to_tzinfo(tz_name: str | None):
    """Convert IANA timezone or offset string (+HH:MM) to tzinfo."""
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except Exception:
        pass
    if len(tz_name) == 6 and tz_name[0] in "+-" and tz_name[3] == ":":
        try:
            hours = int(tz_name[1:3])
            minutes = int(tz_name[4:6])
            delta = timedelta(hours=hours, minutes=minutes)
            if tz_name[0] == "-":
                delta = -delta
            return timezone(delta)
        except Exception:
            return None
    return None

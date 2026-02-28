"""Centralized date/time formatting functions.

All display-related formatting goes through this module. DB storage and API
responses always use raw UTC ISO 8601 strings — these helpers are only for
server-rendered HTML and chart labels.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo


# ── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_DISPLAY = {
    "date_format": "YYYY-MM-DD",
    "time_format": "24h",
    "week_start": "monday",
    "timezone": "UTC",
}


# ── Timezone conversion ────────────────────────────────────────────────────


def convert_tz(iso_str: str, tz_name: str) -> datetime:
    """Parse an ISO 8601 string (assumed UTC) and convert to *tz_name*."""
    dt = datetime.fromisoformat(iso_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(tz_name))


def get_tz_offset_hours(tz_name: str) -> float:
    """Return the current UTC offset for *tz_name* in fractional hours.

    Used to build SQLite ``datetime(col, '+N hours')`` modifiers.
    """
    now = datetime.now(timezone.utc)
    offset = now.astimezone(ZoneInfo(tz_name)).utcoffset()
    if offset is None:
        return 0.0
    return offset.total_seconds() / 3600


# ── Date formatting ────────────────────────────────────────────────────────


def _to_dt(iso_str: str, settings: dict) -> datetime:
    tz_name = settings.get("timezone", "UTC")
    return convert_tz(iso_str, tz_name)


def format_date(iso_str: str, settings: dict) -> str:
    """Full date: ``2026-02-28`` / ``28/02/2026`` / ``02/28/2026``."""
    if not iso_str:
        return ""
    dt = _to_dt(iso_str, settings)
    fmt = settings.get("date_format", "YYYY-MM-DD")
    if fmt == "DD/MM/YYYY":
        return dt.strftime("%d/%m/%Y")
    if fmt == "MM/DD/YYYY":
        return dt.strftime("%m/%d/%Y")
    return dt.strftime("%Y-%m-%d")


def format_date_short(iso_str: str, settings: dict) -> str:
    """Short date for chart labels: ``02-28`` / ``28/02`` / ``02/28``."""
    if not iso_str:
        return ""
    dt = _to_dt(iso_str, settings)
    fmt = settings.get("date_format", "YYYY-MM-DD")
    if fmt == "DD/MM/YYYY":
        return dt.strftime("%d/%m")
    if fmt == "MM/DD/YYYY":
        return dt.strftime("%m/%d")
    return dt.strftime("%m-%d")


# ── Time formatting ─────────────────────────────────────────────────────────


def format_time(iso_str: str, settings: dict) -> str:
    """Time only: ``14:30`` or ``2:30 PM``."""
    if not iso_str:
        return ""
    dt = _to_dt(iso_str, settings)
    if settings.get("time_format") == "12h":
        return dt.strftime("%-I:%M %p")
    return dt.strftime("%H:%M")


def format_datetime(iso_str: str, settings: dict) -> str:
    """Date + time combined."""
    if not iso_str:
        return ""
    return f"{format_date(iso_str, settings)} {format_time(iso_str, settings)}"


def format_last_seen(iso_str: str, settings: dict) -> str:
    """Friendly last-seen: ``Feb 28, 2026 14:30``."""
    if not iso_str:
        return "Never"
    dt = _to_dt(iso_str, settings)
    if settings.get("time_format") == "12h":
        return dt.strftime("%b %d, %Y %-I:%M %p")
    return dt.strftime("%b %d, %Y %H:%M")


# ── Day-of-week helpers ─────────────────────────────────────────────────────

_DOW_LABELS_MON = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
_DOW_LABELS_SUN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

_DOW_SHORT_MON = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_DOW_SHORT_SUN = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]


def get_dow_labels(settings: dict, short: bool = False) -> list[str]:
    """Ordered day-of-week labels starting from the configured week start."""
    monday = settings.get("week_start", "monday") == "monday"
    if short:
        return list(_DOW_SHORT_MON if monday else _DOW_SHORT_SUN)
    return list(_DOW_LABELS_MON if monday else _DOW_LABELS_SUN)


def get_dow_order(settings: dict) -> list[int]:
    """SQLite ``strftime('%w')`` indices (0=Sun) in display order.

    Monday start → [1,2,3,4,5,6,0]
    Sunday start → [0,1,2,3,4,5,6]
    """
    if settings.get("week_start", "monday") == "monday":
        return [1, 2, 3, 4, 5, 6, 0]
    return [0, 1, 2, 3, 4, 5, 6]


# ── Hour label ──────────────────────────────────────────────────────────────


def get_hour_label(hour: int, settings: dict) -> str:
    """Label for a given hour (0-23): ``14:00`` or ``2PM``."""
    if settings.get("time_format") == "12h":
        if hour == 0:
            return "12AM"
        if hour < 12:
            return f"{hour}AM"
        if hour == 12:
            return "12PM"
        return f"{hour - 12}PM"
    return f"{hour:02d}:00"


# ── Curated timezone list ──────────────────────────────────────────────────

COMMON_TIMEZONES = [
    "UTC",
    "US/Eastern",
    "US/Central",
    "US/Mountain",
    "US/Pacific",
    "US/Alaska",
    "US/Hawaii",
    "Canada/Atlantic",
    "America/Mexico_City",
    "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Moscow",
    "Europe/Istanbul",
    "Africa/Cairo",
    "Africa/Johannesburg",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Bangkok",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Australia/Sydney",
    "Australia/Perth",
    "Pacific/Auckland",
    "Pacific/Honolulu",
]

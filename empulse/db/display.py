"""Display settings DB operations (singleton row, id=1)."""

from __future__ import annotations

import aiosqlite

from empulse.formatting import DEFAULT_DISPLAY

VALID_DATE_FORMATS = {"YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY"}
VALID_TIME_FORMATS = {"24h", "12h"}
VALID_WEEK_STARTS = {"monday", "sunday"}


async def get_display_settings(db: aiosqlite.Connection) -> dict:
    """Return current display settings, falling back to defaults."""
    cursor = await db.execute("SELECT * FROM display_settings WHERE id = 1")
    row = await cursor.fetchone()
    if row:
        return {
            "date_format": row["date_format"],
            "time_format": row["time_format"],
            "week_start": row["week_start"],
            "timezone": row["timezone"],
        }
    return dict(DEFAULT_DISPLAY)


async def save_display_settings(db: aiosqlite.Connection, data: dict) -> dict:
    """Validate and upsert display settings. Returns the saved settings."""
    date_format = data.get("date_format", DEFAULT_DISPLAY["date_format"])
    time_format = data.get("time_format", DEFAULT_DISPLAY["time_format"])
    week_start = data.get("week_start", DEFAULT_DISPLAY["week_start"])
    tz = data.get("timezone", DEFAULT_DISPLAY["timezone"])

    if date_format not in VALID_DATE_FORMATS:
        date_format = DEFAULT_DISPLAY["date_format"]
    if time_format not in VALID_TIME_FORMATS:
        time_format = DEFAULT_DISPLAY["time_format"]
    if week_start not in VALID_WEEK_STARTS:
        week_start = DEFAULT_DISPLAY["week_start"]

    # Validate timezone
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, KeyError):
        tz = DEFAULT_DISPLAY["timezone"]

    await db.execute(
        """INSERT INTO display_settings (id, date_format, time_format, week_start, timezone)
           VALUES (1, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               date_format = excluded.date_format,
               time_format = excluded.time_format,
               week_start = excluded.week_start,
               timezone = excluded.timezone""",
        [date_format, time_format, week_start, tz],
    )
    await db.commit()

    return {
        "date_format": date_format,
        "time_format": time_format,
        "week_start": week_start,
        "timezone": tz,
    }

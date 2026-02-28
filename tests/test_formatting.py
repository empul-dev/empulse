"""Tests for empulse.formatting — all pure functions, no DB needed."""

import pytest
from empulse.formatting import (
    convert_tz,
    format_date,
    format_date_short,
    format_time,
    format_datetime,
    format_last_seen,
    get_dow_labels,
    get_dow_order,
    get_hour_label,
    get_tz_offset_hours,
)


# ── Timezone conversion ────────────────────────────────────────────────────


def test_convert_tz_utc():
    dt = convert_tz("2026-02-28T14:30:00", "UTC")
    assert dt.hour == 14
    assert dt.minute == 30


def test_convert_tz_eastern():
    dt = convert_tz("2026-02-28T14:30:00", "US/Eastern")
    assert dt.hour == 9  # EST = UTC-5


def test_convert_tz_tokyo():
    dt = convert_tz("2026-02-28T14:30:00", "Asia/Tokyo")
    assert dt.hour == 23  # JST = UTC+9


def test_convert_tz_date_rollover():
    """UTC midnight should roll back to previous day in US/Eastern."""
    dt = convert_tz("2026-03-01T00:00:00", "US/Eastern")
    assert dt.day == 28
    assert dt.month == 2


# ── Date formatting ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("YYYY-MM-DD", "2026-02-28"),
        ("DD/MM/YYYY", "28/02/2026"),
        ("MM/DD/YYYY", "02/28/2026"),
    ],
)
def test_format_date(fmt, expected):
    settings = {"date_format": fmt, "time_format": "24h", "timezone": "UTC"}
    assert format_date("2026-02-28T14:30:00", settings) == expected


def test_format_date_empty():
    assert format_date("", {"timezone": "UTC"}) == ""


@pytest.mark.parametrize(
    "fmt,expected",
    [
        ("YYYY-MM-DD", "02-28"),
        ("DD/MM/YYYY", "28/02"),
        ("MM/DD/YYYY", "02/28"),
    ],
)
def test_format_date_short(fmt, expected):
    settings = {"date_format": fmt, "time_format": "24h", "timezone": "UTC"}
    assert format_date_short("2026-02-28T14:30:00", settings) == expected


# ── Time formatting ─────────────────────────────────────────────────────────


def test_format_time_24h():
    settings = {"time_format": "24h", "timezone": "UTC"}
    assert format_time("2026-02-28T14:30:00", settings) == "14:30"


def test_format_time_12h():
    settings = {"time_format": "12h", "timezone": "UTC"}
    result = format_time("2026-02-28T14:30:00", settings)
    assert "2:30 PM" in result or "2:30 pm" in result.lower()


def test_format_time_midnight_12h():
    settings = {"time_format": "12h", "timezone": "UTC"}
    result = format_time("2026-02-28T00:00:00", settings)
    assert "12:00 AM" in result or "12:00 am" in result.lower()


def test_format_time_empty():
    assert format_time("", {"timezone": "UTC"}) == ""


# ── Datetime formatting ────────────────────────────────────────────────────


def test_format_datetime_24h():
    settings = {"date_format": "YYYY-MM-DD", "time_format": "24h", "timezone": "UTC"}
    assert format_datetime("2026-02-28T14:30:00", settings) == "2026-02-28 14:30"


def test_format_datetime_with_tz():
    settings = {"date_format": "DD/MM/YYYY", "time_format": "12h", "timezone": "US/Eastern"}
    result = format_datetime("2026-02-28T14:30:00", settings)
    assert "28/02/2026" in result
    assert "9:30 AM" in result or "9:30 am" in result.lower()


# ── Last seen ──────────────────────────────────────────────────────────────


def test_format_last_seen_24h():
    settings = {"time_format": "24h", "timezone": "UTC"}
    result = format_last_seen("2026-02-28T14:30:00", settings)
    assert "Feb 28, 2026" in result
    assert "14:30" in result


def test_format_last_seen_never():
    settings = {"timezone": "UTC"}
    assert format_last_seen("", settings) == "Never"
    assert format_last_seen(None, settings) == "Never"


# ── Day-of-week helpers ─────────────────────────────────────────────────────


def test_dow_labels_monday():
    labels = get_dow_labels({"week_start": "monday"})
    assert labels[0] == "Mon"
    assert labels[6] == "Sun"


def test_dow_labels_sunday():
    labels = get_dow_labels({"week_start": "sunday"})
    assert labels[0] == "Sun"
    assert labels[6] == "Sat"


def test_dow_labels_short():
    labels = get_dow_labels({"week_start": "monday"}, short=True)
    assert labels[0] == "Mo"
    assert len(labels) == 7


def test_dow_order_monday():
    order = get_dow_order({"week_start": "monday"})
    assert order == [1, 2, 3, 4, 5, 6, 0]


def test_dow_order_sunday():
    order = get_dow_order({"week_start": "sunday"})
    assert order == [0, 1, 2, 3, 4, 5, 6]


# ── Hour label ──────────────────────────────────────────────────────────────


def test_hour_label_24h():
    settings = {"time_format": "24h"}
    assert get_hour_label(0, settings) == "00:00"
    assert get_hour_label(14, settings) == "14:00"
    assert get_hour_label(23, settings) == "23:00"


def test_hour_label_12h():
    settings = {"time_format": "12h"}
    assert get_hour_label(0, settings) == "12AM"
    assert get_hour_label(1, settings) == "1AM"
    assert get_hour_label(12, settings) == "12PM"
    assert get_hour_label(13, settings) == "1PM"
    assert get_hour_label(23, settings) == "11PM"


# ── Timezone offset ────────────────────────────────────────────────────────


def test_tz_offset_utc():
    assert get_tz_offset_hours("UTC") == 0.0


def test_tz_offset_nonzero():
    offset = get_tz_offset_hours("Asia/Kolkata")
    assert offset == 5.5

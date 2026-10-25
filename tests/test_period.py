from datetime import date, datetime, timezone

import aiosqlite

from empulse.period import MAX_DAYS, Period, register_sql_functions

NOON = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)


def test_days_are_clamped():
    assert Period.last(0, now=NOON).days == 1
    assert Period.last(-5, now=NOON).days == 1
    assert Period.last(99999, now=NOON).days == MAX_DAYS == 365


def test_day_keys_end_on_today_and_count_days():
    p = Period.last(3, "UTC", now=NOON)
    assert p.day_keys() == ["2026-10-23", "2026-10-24", "2026-10-25"]


def test_today_is_taken_in_the_display_timezone():
    late = datetime(2026, 10, 25, 23, 30, tzinfo=timezone.utc)
    assert Period.last(1, "Europe/Berlin", now=late).last_day == date(2026, 10, 26)
    assert Period.last(1, "America/Los_Angeles", now=late).last_day == date(
        2026, 10, 25
    )


def test_bounds_are_local_midnights_across_dst():
    # Berlin leaves CEST (+2) for CET (+1) on 2026-10-25, so these two local
    # days are 49 hours long.
    p = Period.last(2, "Europe/Berlin", now=NOON)
    assert p.bounds == ("2026-10-23T22:00:00", "2026-10-25T23:00:00")


def test_utc_bounds():
    assert Period.last(1, "UTC", now=NOON).bounds == (
        "2026-10-25T00:00:00",
        "2026-10-26T00:00:00",
    )


def test_previous_period_ends_where_period_begins():
    p = Period.last(7, "Europe/Berlin", now=NOON)
    prev = p.previous()
    assert prev.days == 7
    assert prev.tz == p.tz
    assert prev.bounds[1] == p.bounds[0]
    assert prev.day_keys()[-1] == "2026-10-18"


def test_fill_days_zero_fills_missing_dates():
    p = Period.last(3, "UTC", now=NOON)
    rows = [{"date": "2026-10-24", "plays": 2, "total_duration": 50}]
    assert p.fill_days(rows, plays=0, total_duration=0) == [
        {"date": "2026-10-23", "plays": 0, "total_duration": 0},
        {"date": "2026-10-24", "plays": 2, "total_duration": 50},
        {"date": "2026-10-25", "plays": 0, "total_duration": 0},
    ]


def test_fill_days_drops_rows_outside_the_period():
    p = Period.last(1, "UTC", now=NOON)
    rows = [{"date": "2026-10-20", "plays": 9}]
    assert p.fill_days(rows, plays=0) == [{"date": "2026-10-25", "plays": 0}]


def test_fill_days_by_category_fills_every_date_and_category():
    p = Period.last(2, "UTC", now=NOON)
    rows = [
        {"date": "2026-10-24", "item_type": "Movie", "plays": 1},
        {"date": "2026-10-25", "item_type": "Episode", "plays": 3},
    ]
    assert p.fill_days(rows, by="item_type", plays=0) == [
        {"date": "2026-10-24", "item_type": "Episode", "plays": 0},
        {"date": "2026-10-24", "item_type": "Movie", "plays": 1},
        {"date": "2026-10-25", "item_type": "Episode", "plays": 3},
        {"date": "2026-10-25", "item_type": "Movie", "plays": 0},
    ]


async def _sql(expr: str, *params):
    async with aiosqlite.connect(":memory:") as conn:
        await register_sql_functions(conn)
        cursor = await conn.execute(f"SELECT {expr}", params)
        return (await cursor.fetchone())[0]


async def test_local_date_crosses_midnight_in_display_timezone():
    assert (
        await _sql("local_date(?, ?)", "2026-10-24T22:30:00+00:00", "Europe/Berlin")
        == "2026-10-25"
    )
    assert (
        await _sql("local_date(?, ?)", "2026-10-24T22:30:00+00:00", "UTC")
        == "2026-10-24"
    )


async def test_local_hour_uses_the_offset_of_each_row():
    # One offset for all rows (the old behaviour) can't get both right.
    assert (
        await _sql("local_hour(?, ?)", "2026-07-01T12:00:00+00:00", "Europe/Berlin")
        == 14
    )
    assert (
        await _sql("local_hour(?, ?)", "2026-12-01T12:00:00+00:00", "Europe/Berlin")
        == 13
    )


async def test_local_dow_is_zero_for_sunday():
    assert await _sql("local_dow(?, ?)", "2026-10-25T12:00:00+00:00", "UTC") == 0
    assert (
        await _sql("local_dow(?, ?)", "2026-10-25T23:30:00+00:00", "Europe/Berlin") == 1
    )


async def test_local_month():
    assert (
        await _sql("local_month(?, ?)", "2026-10-31T23:30:00+00:00", "Europe/Berlin")
        == "2026-11"
    )


async def test_naive_timestamps_are_utc_and_null_stays_null():
    assert await _sql("local_hour(?, ?)", "2026-12-01T12:00:00", "Europe/Berlin") == 13
    assert await _sql("local_date(NULL, ?)", "UTC") is None

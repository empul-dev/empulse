"""Concurrent Streams chart: daily peak of simultaneous streams via sweep line."""

from datetime import datetime, timedelta, timezone

from empulse.db import history as history_db, stats as stats_db
from empulse.period import Period
from tests.test_web import client  # noqa: F401  (fixture)

NOON = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
BERLIN = "Europe/Berlin"

_n = 0


async def stream(db, started_at: str, stopped_at: str, method: str = "DirectPlay"):
    global _n
    _n += 1
    await history_db.insert_history(
        db,
        {
            "session_key": f"c{_n}",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "i1",
            "item_name": "Film",
            "item_type": "Movie",
            "started_at": started_at,
            "stopped_at": stopped_at,
            "duration_seconds": 3600,
            "play_method": method,
        },
    )


def peaks(rows):
    return [(r["date"], r["peak"], r["peak_transcode"]) for r in rows]


async def test_overlapping_vs_back_to_back(db):
    # Back-to-back on the 23rd: stop == start is not concurrent.
    await stream(db, "2026-10-23T10:00:00+00:00", "2026-10-23T11:00:00+00:00")
    await stream(db, "2026-10-23T11:00:00+00:00", "2026-10-23T12:00:00+00:00")
    # Overlapping on the 24th.
    await stream(db, "2026-10-24T10:00:00+00:00", "2026-10-24T12:00:00+00:00")
    await stream(db, "2026-10-24T11:00:00+00:00", "2026-10-24T13:00:00+00:00")

    rows = await stats_db.get_concurrent_streams(db, Period.last(3, "UTC", now=NOON))

    assert peaks(rows) == [
        ("2026-10-23", 1, 0),
        ("2026-10-24", 2, 0),
        ("2026-10-25", 0, 0),  # zero-filled
    ]


async def test_stream_across_local_midnight_counts_both_days(db):
    # Berlin (UTC+2 on the 23rd): 23:30 on the 23rd → 01:00 on the 24th.
    await stream(db, "2026-10-23T21:30:00+00:00", "2026-10-23T23:00:00+00:00")
    # Overlaps it after local midnight on the 24th.
    await stream(db, "2026-10-23T22:30:00+00:00", "2026-10-23T22:45:00+00:00")

    rows = await stats_db.get_concurrent_streams(db, Period.last(3, BERLIN, now=NOON))

    assert peaks(rows) == [
        ("2026-10-23", 1, 0),
        ("2026-10-24", 2, 0),
        ("2026-10-25", 0, 0),
    ]


async def test_stream_started_before_period_counts_on_first_day(db):
    await stream(
        db, "2026-10-22T20:00:00+00:00", "2026-10-23T01:00:00+00:00", "Transcode"
    )

    rows = await stats_db.get_concurrent_streams(db, Period.last(3, "UTC", now=NOON))

    assert peaks(rows)[0] == ("2026-10-23", 1, 1)


async def test_transcodes_counted_at_peak(db):
    # An early lone transcode, then a later peak of 3 with one transcode.
    await stream(
        db, "2026-10-25T01:00:00+00:00", "2026-10-25T02:00:00+00:00", "Transcode"
    )
    await stream(
        db, "2026-10-25T05:00:00+00:00", "2026-10-25T08:00:00+00:00", "Transcode"
    )
    await stream(db, "2026-10-25T05:30:00+00:00", "2026-10-25T08:00:00+00:00")
    await stream(
        db, "2026-10-25T06:00:00+00:00", "2026-10-25T07:00:00+00:00", "DirectStream"
    )

    rows = await stats_db.get_concurrent_streams(db, Period.last(1, "UTC", now=NOON))

    assert peaks(rows) == [("2026-10-25", 3, 1)]


async def test_false_starts_ignored(db):
    await history_db.insert_history(
        db,
        {
            "session_key": "false-start",
            "user_id": "u1",
            "item_id": "i1",
            "started_at": "2026-10-25T05:00:00+00:00",
            "stopped_at": "2026-10-25T05:01:00+00:00",
            "duration_seconds": 60,
        },
    )

    rows = await stats_db.get_concurrent_streams(db, Period.last(1, "UTC", now=NOON))

    assert peaks(rows) == [("2026-10-25", 0, 0)]


async def test_endpoint_returns_json(client):  # noqa: F811
    db = client._test_db
    now = datetime.now(timezone.utc).replace(microsecond=0)
    await stream(db, (now - timedelta(hours=1)).isoformat(), now.isoformat())

    r = await client.get("/api/charts/concurrent-streams?days=7")

    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 7
    assert set(rows[0]) == {"date", "peak", "peak_transcode"}
    assert max(row["peak"] for row in rows) == 1

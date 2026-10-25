"""Stats queries against a Period: local-day grouping, window edges, DST."""

from datetime import datetime, timedelta, timezone

from empulse.db import history as history_db, stats as stats_db
from empulse.period import Period

NOON = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
BERLIN = "Europe/Berlin"


_n = 0


async def play(db, started_at: str, **extra):
    global _n
    _n += 1
    await history_db.insert_history(
        db,
        {
            "session_key": f"s{_n}",
            "user_id": "u1",
            "user_name": "Alice",
            "item_id": "i1",
            "item_name": "Film",
            "item_type": "Movie",
            "started_at": started_at,
            "stopped_at": started_at,
            "duration_seconds": 3600,
            "play_method": "DirectPlay",
            **extra,
        },
    )


async def test_daily_plays_group_by_local_day_and_fill_gaps(db):
    await play(db, "2026-10-23T21:30:00+00:00")  # Berlin 23:30 on the 23rd
    await play(db, "2026-10-23T22:30:00+00:00")  # Berlin 00:30 on the 24th

    rows = await stats_db.get_plays_per_day(db, Period.last(3, BERLIN, now=NOON))

    assert [(r["date"], r["plays"]) for r in rows] == [
        ("2026-10-23", 1),
        ("2026-10-24", 1),
        ("2026-10-25", 0),
    ]


async def test_window_starts_at_local_midnight(db):
    p = Period.last(1, BERLIN, now=NOON)
    start = datetime.fromisoformat(p.bounds[0]).replace(tzinfo=timezone.utc)
    await play(db, (start - timedelta(seconds=1)).isoformat())
    await play(db, start.isoformat())
    await play(db, (start + timedelta(hours=12, microseconds=5)).isoformat())

    top = await stats_db.get_top_users(db, p, limit=10)

    assert top[0]["plays"] == 2


async def test_hour_and_heatmap_use_each_rows_offset_across_dst(db):
    await play(db, "2026-10-24T12:00:00+00:00")  # Sat 14:00 CEST
    await play(db, "2026-10-25T13:00:00+00:00")  # Sun 14:00 CET
    p = Period.last(2, BERLIN, now=datetime(2026, 10, 25, 20, tzinfo=timezone.utc))

    by_hour = await stats_db.get_plays_by_hour(db, p)
    heatmap = await stats_db.get_watch_heatmap(db, p)
    by_dow = await stats_db.get_plays_by_day_of_week(db, p)

    assert [(r["hour"], r["plays"]) for r in by_hour] == [(14, 2)]
    assert [(r["dow"], r["hour"]) for r in heatmap] == [(0, 14), (6, 14)]
    assert [(r["dow"], r["plays"]) for r in by_dow] == [(0, 1), (6, 1)]


async def test_stacked_series_fill_every_date_and_category(db):
    await play(
        db, "2026-10-24T10:00:00+00:00", item_type="Episode", play_method="Transcode"
    )
    await play(db, "2026-10-25T10:00:00+00:00")
    p = Period.last(2, "UTC", now=NOON)

    stacked = await stats_db.get_plays_by_date_stacked(db, p)
    streams = await stats_db.get_plays_by_stream_type(db, p)

    assert [(r["date"], r["item_type"], r["plays"]) for r in stacked] == [
        ("2026-10-24", "Episode", 1),
        ("2026-10-24", "Movie", 0),
        ("2026-10-25", "Episode", 0),
        ("2026-10-25", "Movie", 1),
    ]
    assert len(streams) == 4


async def test_period_comparison_uses_previous_local_days(db):
    await play(db, "2026-10-25T08:00:00+00:00")
    await play(db, "2026-10-24T08:00:00+00:00")
    await play(db, "2026-10-17T08:00:00+00:00")  # previous of last(7) is 10-12..10-18

    result = await stats_db.get_period_comparison(db, Period.last(7, BERLIN, now=NOON))

    assert result["current"]["plays"] == 2
    assert result["previous"]["plays"] == 1


async def test_plays_per_month_uses_local_month(db):
    await play(db, "2026-09-30T22:30:00+00:00")  # Berlin: 1 October

    rows = await stats_db.get_plays_per_month(db, Period.last(60, BERLIN, now=NOON))

    assert [(r["month"], r["plays"]) for r in rows] == [("2026-10", 1)]


async def test_item_stats_fixed_blocks(db):
    now = datetime.now(timezone.utc)
    await play(db, (now - timedelta(hours=1)).isoformat())
    await play(db, (now - timedelta(days=3)).isoformat())
    await play(db, (now - timedelta(days=400)).isoformat())

    stats = await stats_db.get_item_stats(db, "i1", BERLIN)

    assert stats["last_24h"]["plays"] == 1
    assert stats["last_7d"]["plays"] == 2
    assert stats["last_30d"]["plays"] == 2
    assert stats["all_time"]["plays"] == 3

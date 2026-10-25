from datetime import date, datetime, time, timedelta, timezone

import aiosqlite

from empulse.formatting import format_transcode_reason
from empulse.period import Period, _local, _zone


def _safe_order(metric: str) -> str:
    """Return a safe ORDER BY column name for metric queries."""
    return "plays" if metric == "plays" else "total_duration"


# A started_at upper bound later than any stored timestamp.
_OPEN_END = "9999"


async def _totals_by_window(
    db: aiosqlite.Connection,
    column: str,
    value: str,
    tz: str,
    labels: tuple[str, ...],
    select: str,
) -> dict:
    """Totals for rows where *column* = *value*, per fixed window label.

    last_24h is a rolling 24 hours; last_7d/last_30d are Periods; all_time is unbounded.
    *column* and *select* are trusted SQL from this module, never user input.
    """
    now = datetime.now(timezone.utc)
    windows = {
        "last_24h": (
            (now - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"),
            _OPEN_END,
        ),
        "last_7d": Period.last(7, tz, now).bounds,
        "last_30d": Period.last(30, tz, now).bounds,
        "all_time": ("", _OPEN_END),
    }
    result = {}
    for label in labels:
        cursor = await db.execute(
            f"SELECT {select} FROM counted_plays "
            f"WHERE {column} = ? AND started_at >= ? AND started_at < ?",
            [value, *windows[label]],
        )
        result[label] = dict(await cursor.fetchone())
    return result


async def get_total_plays(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM counted_plays")
    row = await cursor.fetchone()
    return row[0]


async def get_total_duration(db: aiosqlite.Connection) -> int:
    cursor = await db.execute(
        "SELECT COALESCE(SUM(duration_seconds), 0) FROM counted_plays"
    )
    row = await cursor.fetchone()
    return row[0]


async def get_top_users(
    db: aiosqlite.Connection, period: Period, limit: int = 5, metric: str = "plays"
) -> list[dict]:
    order = _safe_order(metric)
    cursor = await db.execute(
        f"""SELECT user_id, user_name, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY user_id
           ORDER BY {order} DESC LIMIT ?""",
        [*period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_watched_movies(
    db: aiosqlite.Connection, period: Period, limit: int = 5, metric: str = "plays"
) -> list[dict]:
    order = _safe_order(metric)
    cursor = await db.execute(
        f"""SELECT item_id, item_name, year, COUNT(*) as plays,
                  COUNT(DISTINCT user_id) as users,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE item_type = 'Movie' AND started_at >= ? AND started_at < ?
           GROUP BY item_id
           ORDER BY {order} DESC LIMIT ?""",
        [*period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_popular_movies(
    db: aiosqlite.Connection, period: Period, limit: int = 5
) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_id, item_name, year, COUNT(DISTINCT user_id) as users,
                  COUNT(*) as plays
           FROM counted_plays
           WHERE item_type = 'Movie' AND started_at >= ? AND started_at < ?
           GROUP BY item_id
           ORDER BY users DESC, plays DESC LIMIT ?""",
        [*period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_watched_shows(
    db: aiosqlite.Connection, period: Period, limit: int = 5, metric: str = "plays"
) -> list[dict]:
    order = _safe_order(metric)
    cursor = await db.execute(
        f"""SELECT h.series_name, COUNT(*) as plays,
                  COUNT(DISTINCT user_id) as users,
                  SUM(duration_seconds) as total_duration,
                  COALESCE(
                      (
                          SELECT h2.series_id
                          FROM counted_plays h2
                          WHERE h2.item_type = 'Episode'
                            AND h2.series_name = h.series_name
                            AND NULLIF(h2.series_id, '') IS NOT NULL
                          ORDER BY h2.started_at DESC
                          LIMIT 1
                      ),
                      MIN(h.item_id)
                  ) as poster_id
           FROM counted_plays h
           WHERE h.item_type = 'Episode' AND h.series_name IS NOT NULL
                 AND started_at >= ? AND started_at < ?
           GROUP BY h.series_name
           ORDER BY {order} DESC LIMIT ?""",
        [*period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_popular_shows(
    db: aiosqlite.Connection, period: Period, limit: int = 5
) -> list[dict]:
    cursor = await db.execute(
        """SELECT h.series_name, COUNT(DISTINCT user_id) as users,
                  COUNT(*) as plays,
                  COALESCE(
                      (
                          SELECT h2.series_id
                          FROM counted_plays h2
                          WHERE h2.item_type = 'Episode'
                            AND h2.series_name = h.series_name
                            AND NULLIF(h2.series_id, '') IS NOT NULL
                          ORDER BY h2.started_at DESC
                          LIMIT 1
                      ),
                      MIN(h.item_id)
                  ) as poster_id
           FROM counted_plays h
           WHERE h.item_type = 'Episode' AND h.series_name IS NOT NULL
                 AND started_at >= ? AND started_at < ?
           GROUP BY h.series_name
           ORDER BY users DESC, plays DESC LIMIT ?""",
        [*period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_recently_watched(db: aiosqlite.Connection, limit: int = 5) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_id, item_name, series_name, series_id, season_number, episode_number,
                  item_type, year, user_name, started_at
           FROM counted_plays
           ORDER BY started_at DESC LIMIT ?""",
        [limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_watched_series_keys(db: aiosqlite.Connection) -> dict[str, set[str]]:
    """Return known watched series identifiers from local playback history."""
    cursor = await db.execute(
        """SELECT DISTINCT NULLIF(TRIM(series_id), '') as series_id,
                  NULLIF(TRIM(series_name), '') as series_name
           FROM history
           WHERE item_type = 'Episode'
             AND (NULLIF(TRIM(series_id), '') IS NOT NULL
                  OR NULLIF(TRIM(series_name), '') IS NOT NULL)"""
    )
    rows = await cursor.fetchall()
    series_ids = {row["series_id"] for row in rows if row["series_id"]}
    series_names = {row["series_name"] for row in rows if row["series_name"]}
    return {"series_ids": series_ids, "series_names": series_names}


async def get_watched_item_keys(
    db: aiosqlite.Connection, item_type: str
) -> dict[str, set[str]]:
    """Return watched identifiers for a given history item type."""
    if item_type == "Episode":
        return await get_watched_series_keys(db)

    cursor = await db.execute(
        """SELECT DISTINCT NULLIF(TRIM(item_id), '') as item_id,
                  NULLIF(TRIM(item_name), '') as item_name
           FROM history
           WHERE item_type = ?
             AND (NULLIF(TRIM(item_id), '') IS NOT NULL
                  OR NULLIF(TRIM(item_name), '') IS NOT NULL)""",
        [item_type],
    )
    rows = await cursor.fetchall()
    item_ids = {row["item_id"] for row in rows if row["item_id"]}
    item_names = {row["item_name"] for row in rows if row["item_name"]}
    return {"series_ids": item_ids, "series_names": item_names}


async def get_most_active_platforms(
    db: aiosqlite.Connection, period: Period, limit: int = 5
) -> list[dict]:
    cursor = await db.execute(
        """SELECT client, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY client
           ORDER BY plays DESC LIMIT ?""",
        [*period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_active_libraries(
    db: aiosqlite.Connection, period: Period, limit: int = 5
) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_type, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY item_type
           ORDER BY plays DESC LIMIT ?""",
        [*period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_plays_per_day(db: aiosqlite.Connection, period: Period) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_date(started_at, ?) as date, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY date
           ORDER BY date""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return period.fill_days([dict(r) for r in rows], plays=0, total_duration=0)


async def get_plays_by_type(db: aiosqlite.Connection, period: Period) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_type, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY item_type ORDER BY plays DESC""",
        [*period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_stats(db: aiosqlite.Connection, user_id: str) -> dict:
    cursor = await db.execute(
        """SELECT COUNT(*) as total_plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration,
                  MAX(started_at) as last_play
           FROM counted_plays WHERE user_id = ?""",
        [user_id],
    )
    row = await cursor.fetchone()
    return dict(row)


async def get_item_stats(
    db: aiosqlite.Connection, item_id: str, tz: str = "UTC"
) -> dict:
    """Get play stats for a specific item across time periods."""
    return await _totals_by_window(
        db,
        "item_id",
        item_id,
        tz,
        ("last_24h", "last_7d", "last_30d", "all_time"),
        "COUNT(*) as plays, COALESCE(SUM(duration_seconds), 0) as duration",
    )


async def get_item_user_stats(db: aiosqlite.Connection, item_id: str) -> list[dict]:
    """Get per-user play stats for an item."""
    cursor = await db.execute(
        """SELECT user_id, user_name, COUNT(*) as plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration
           FROM counted_plays WHERE item_id = ?
           GROUP BY user_id ORDER BY plays DESC""",
        [item_id],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_series_stats(
    db: aiosqlite.Connection, series_name: str, tz: str = "UTC"
) -> dict:
    """Get play stats for a series across time periods."""
    return await _totals_by_window(
        db,
        "series_name",
        series_name,
        tz,
        ("last_24h", "last_7d", "last_30d", "all_time"),
        "COUNT(*) as plays, COALESCE(SUM(duration_seconds), 0) as duration",
    )


async def get_series_user_stats(
    db: aiosqlite.Connection, series_name: str
) -> list[dict]:
    """Get per-user play stats for a series."""
    cursor = await db.execute(
        """SELECT user_id, user_name, COUNT(*) as plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration
           FROM counted_plays WHERE series_name = ?
           GROUP BY user_id ORDER BY plays DESC""",
        [series_name],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_plays_per_day(
    db: aiosqlite.Connection, user_id: str, period: Period
) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_date(started_at, ?) as date, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE user_id = ? AND started_at >= ? AND started_at < ?
           GROUP BY date
           ORDER BY date""",
        [period.tz, user_id, *period.bounds],
    )
    rows = await cursor.fetchall()
    return period.fill_days([dict(r) for r in rows], plays=0, total_duration=0)


async def get_user_plays_by_type(
    db: aiosqlite.Connection, user_id: str, period: Period
) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_type, COUNT(*) as plays
           FROM counted_plays
           WHERE user_id = ? AND started_at >= ? AND started_at < ?
           GROUP BY item_type ORDER BY plays DESC""",
        [user_id, *period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_most_watched(
    db: aiosqlite.Connection, user_id: str, period: Period, limit: int = 10
) -> list[dict]:
    cursor = await db.execute(
        """SELECT
               COALESCE(h.series_name, h.item_name) as title,
               COALESCE(
                   (
                       SELECT h2.series_id
                       FROM counted_plays h2
                       WHERE h2.user_id = h.user_id
                         AND h2.item_type = 'Episode'
                         AND h2.series_name = h.series_name
                         AND NULLIF(h2.series_id, '') IS NOT NULL
                       ORDER BY h2.started_at DESC
                       LIMIT 1
                   ),
                   MIN(COALESCE(NULLIF(h.series_id, ''), h.item_id))
               ) as poster_id,
               COUNT(*) as plays,
               SUM(duration_seconds) as total_duration
           FROM counted_plays h
           WHERE h.user_id = ? AND h.started_at >= ? AND started_at < ?
           GROUP BY COALESCE(h.series_name, h.item_name)
           ORDER BY plays DESC LIMIT ?""",
        [user_id, *period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_library_stats(
    db: aiosqlite.Connection, item_type: str, tz: str = "UTC"
) -> dict:
    return await _totals_by_window(
        db,
        "item_type",
        item_type,
        tz,
        ("last_7d", "last_30d", "all_time"),
        "COUNT(*) as plays, COALESCE(SUM(duration_seconds), 0) as duration, "
        "COUNT(DISTINCT user_id) as users",
    )


async def get_library_top_items(
    db: aiosqlite.Connection, item_type: str, period: Period, limit: int = 10
) -> list[dict]:
    if item_type == "Episode":
        cursor = await db.execute(
            """SELECT h.series_name as title,
                      COALESCE(
                          (
                              SELECT h2.series_id
                              FROM counted_plays h2
                              WHERE h2.item_type = 'Episode'
                                AND h2.series_name = h.series_name
                                AND NULLIF(h2.series_id, '') IS NOT NULL
                              ORDER BY h2.started_at DESC
                              LIMIT 1
                          ),
                          MIN(h.item_id)
                      ) as poster_id,
                      COUNT(*) as plays,
                      SUM(duration_seconds) as total_duration,
                      COUNT(DISTINCT user_id) as users
               FROM counted_plays h
               WHERE h.item_type = ? AND h.started_at >= ? AND started_at < ?
               GROUP BY h.series_name
               ORDER BY plays DESC LIMIT ?""",
            [item_type, *period.bounds, limit],
        )
    else:
        cursor = await db.execute(
            """SELECT item_name as title, item_id as poster_id,
                      COUNT(*) as plays,
                      SUM(duration_seconds) as total_duration,
                      COUNT(DISTINCT user_id) as users
               FROM counted_plays
               WHERE item_type = ? AND started_at >= ? AND started_at < ?
               GROUP BY item_id
               ORDER BY plays DESC LIMIT ?""",
            [item_type, *period.bounds, limit],
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_library_top_users(
    db: aiosqlite.Connection, item_type: str, period: Period, limit: int = 10
) -> list[dict]:
    cursor = await db.execute(
        """SELECT user_id, user_name, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE item_type = ? AND started_at >= ? AND started_at < ?
           GROUP BY user_id
           ORDER BY plays DESC LIMIT ?""",
        [item_type, *period.bounds, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_library_plays_per_day(
    db: aiosqlite.Connection, item_type: str, period: Period
) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_date(started_at, ?) as date, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE item_type = ? AND started_at >= ? AND started_at < ?
           GROUP BY date
           ORDER BY date""",
        [period.tz, item_type, *period.bounds],
    )
    rows = await cursor.fetchall()
    return period.fill_days([dict(r) for r in rows], plays=0, total_duration=0)


async def get_plays_by_day_of_week(
    db: aiosqlite.Connection, period: Period
) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_dow(started_at, ?) as dow,
                  COUNT(*) as plays, SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY dow ORDER BY dow""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_plays_by_hour(db: aiosqlite.Connection, period: Period) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_hour(started_at, ?) as hour,
                  COUNT(*) as plays, SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY hour ORDER BY hour""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_plays_per_month(db: aiosqlite.Connection, period: Period) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_month(started_at, ?) as month,
                  COUNT(*) as plays, COALESCE(SUM(duration_seconds), 0) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY month ORDER BY month""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_plays_by_date_stacked(
    db: aiosqlite.Connection, period: Period
) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_date(started_at, ?) as date, item_type,
                  COUNT(*) as plays, SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY date, item_type
           ORDER BY date""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return period.fill_days(
        [dict(r) for r in rows], by="item_type", plays=0, total_duration=0
    )


async def get_plays_by_stream_type(
    db: aiosqlite.Connection, period: Period
) -> list[dict]:
    cursor = await db.execute(
        """SELECT local_date(started_at, ?) as date, play_method,
                  COUNT(*) as plays
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY date, play_method
           ORDER BY date""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return period.fill_days([dict(r) for r in rows], by="play_method", plays=0)


async def get_source_resolution_distribution(
    db: aiosqlite.Connection, period: Period
) -> list[dict]:
    cursor = await db.execute(
        """SELECT
               CASE
                   WHEN json_extract(stream_info, '$.video.height') >= 2160 THEN '4K'
                   WHEN json_extract(stream_info, '$.video.height') >= 1080 THEN '1080p'
                   WHEN json_extract(stream_info, '$.video.height') >= 720 THEN '720p'
                   WHEN json_extract(stream_info, '$.video.height') >= 480 THEN '480p'
                   WHEN json_extract(stream_info, '$.video.height') > 0 THEN 'Other'
                   ELSE 'Unknown'
               END as resolution,
               COUNT(*) as plays
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY resolution
           ORDER BY plays DESC""",
        [*period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_transcode_ratio(db: aiosqlite.Connection, period: Period) -> list[dict]:
    cursor = await db.execute(
        """SELECT play_method, COUNT(*) as plays
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ? AND play_method IS NOT NULL
           GROUP BY play_method ORDER BY plays DESC""",
        [*period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_transcode_reasons_by_client(
    db: aiosqlite.Connection, period: Period, clients: int = 8, reasons: int = 6
) -> dict:
    """Transcoded plays per client split by Emby TranscodeReasons, for a
    stacked bar. A play with several reasons counts once per reason; plays
    with none stored (pre-0.2.8 rows, or Emby gave none) count as "Unknown".
    Reasons beyond the top ``reasons`` overall collapse into "Other"."""
    cursor = await db.execute(
        """WITH t AS (
               SELECT client, stream_info FROM counted_plays
               WHERE started_at >= ? AND started_at < ?
                 AND play_method = 'Transcode' AND client IS NOT NULL
           ), top AS (
               SELECT client, COUNT(*) AS n FROM t
               GROUP BY client ORDER BY n DESC, client LIMIT ?
           )
           SELECT t.client, r.value AS reason, COUNT(*) AS plays
           FROM t JOIN top USING (client)
           LEFT JOIN json_each(
               CASE WHEN json_valid(t.stream_info) THEN t.stream_info END,
               '$.transcode.reasons'
           ) r
           GROUP BY t.client, r.value
           ORDER BY MAX(top.n) DESC, t.client""",
        [*period.bounds, clients],
    )
    rows = await cursor.fetchall()

    client_names = list(dict.fromkeys(r["client"] for r in rows))
    counts: dict[str, dict[str, int]] = {}
    for r in rows:
        label = format_transcode_reason(r["reason"] or "") or "Unknown"
        per = counts.setdefault(label, {})
        per[r["client"]] = per.get(r["client"], 0) + r["plays"]

    # ponytail: "Unknown" is kept as its own bucket, never folded into "Other".
    ranked = sorted(
        (k for k in counts if k != "Unknown"), key=lambda k: (-sum(counts[k].values()), k)
    )
    labels = ranked[:reasons]
    if ranked[reasons:]:
        other: dict[str, int] = {}
        for k in ranked[reasons:]:
            for c, n in counts[k].items():
                other[c] = other.get(c, 0) + n
        counts["Other"] = other
        labels.append("Other")
    if "Unknown" in counts:
        labels.append("Unknown")

    return {
        "clients": client_names,
        "reasons": labels,
        "counts": {k: [counts[k].get(c, 0) for c in client_names] for k in labels},
    }


async def get_top_platforms_with_stream_type(
    db: aiosqlite.Connection, period: Period, limit: int = 10
) -> list[dict]:
    cursor = await db.execute(
        """SELECT client, play_method, COUNT(*) as plays
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ? AND client IS NOT NULL
           GROUP BY client, play_method
           ORDER BY plays DESC""",
        [*period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_top_users_with_stream_type(
    db: aiosqlite.Connection, period: Period, limit: int = 10
) -> list[dict]:
    cursor = await db.execute(
        """SELECT user_id, user_name, play_method, COUNT(*) as plays
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY user_id, play_method
           ORDER BY plays DESC""",
        [*period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_completion_breakdown(
    db: aiosqlite.Connection, period: Period
) -> list[dict]:
    """Breakdown of plays by completion percentage range."""
    cursor = await db.execute(
        """SELECT
               CASE
                   WHEN percent_complete >= 75 THEN '75-100%'
                   WHEN percent_complete >= 50 THEN '50-75%'
                   WHEN percent_complete >= 25 THEN '25-50%'
                   ELSE '0-25%'
               END as range,
               COUNT(*) as plays
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY range
           ORDER BY
               CASE range
                   WHEN '0-25%' THEN 1
                   WHEN '25-50%' THEN 2
                   WHEN '50-75%' THEN 3
                   WHEN '75-100%' THEN 4
               END""",
        [*period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_period_comparison(db: aiosqlite.Connection, period: Period) -> dict:
    """Stats for the period and its previous period."""
    cursor = await db.execute(
        """SELECT COUNT(*) as plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration,
                  COUNT(DISTINCT user_id) as unique_users,
                  COUNT(DISTINCT item_id) as unique_items
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?""",
        [*period.bounds],
    )
    current = dict(await cursor.fetchone())

    cursor = await db.execute(
        """SELECT COUNT(*) as plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration,
                  COUNT(DISTINCT user_id) as unique_users,
                  COUNT(DISTINCT item_id) as unique_items
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?""",
        [*period.previous().bounds],
    )
    previous = dict(await cursor.fetchone())
    return {"current": current, "previous": previous}


async def get_bandwidth_stats(db: aiosqlite.Connection, period: Period) -> list[dict]:
    """Average bitrate per day from stream_info JSON."""
    cursor = await db.execute(
        """SELECT local_date(started_at, ?) as date,
                  AVG(json_extract(stream_info, '$.media.bitrate')) as avg_bitrate,
                  COUNT(*) as plays
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
                 AND json_extract(stream_info, '$.media.bitrate') IS NOT NULL
                 AND json_extract(stream_info, '$.media.bitrate') > 0
           GROUP BY date
           ORDER BY date""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return period.fill_days([dict(r) for r in rows], avg_bitrate=None, plays=0)


async def get_plays_by_location(db: aiosqlite.Connection, period: Period) -> list[dict]:
    """Plays per day by client network (LAN/remote/unknown) plus avg remote bitrate."""
    cursor = await db.execute(
        """SELECT date,
                  SUM(scope = 'lan') as lan,
                  SUM(scope = 'remote') as remote,
                  SUM(scope = 'unknown') as unknown,
                  AVG(CASE WHEN scope = 'remote' AND bitrate > 0 THEN bitrate END)
                      as remote_avg_bitrate
           FROM (SELECT local_date(started_at, ?) as date,
                        ip_scope(ip_address) as scope,
                        json_extract(stream_info, '$.media.bitrate') as bitrate
                 FROM counted_plays
                 WHERE started_at >= ? AND started_at < ?)
           GROUP BY date
           ORDER BY date""",
        [period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return period.fill_days(
        [dict(r) for r in rows], lan=0, remote=0, unknown=0, remote_avg_bitrate=None
    )


async def get_watch_heatmap(db: aiosqlite.Connection, period: Period) -> list[dict]:
    """Play counts grouped by day-of-week and hour for heatmap rendering."""
    cursor = await db.execute(
        """SELECT local_dow(started_at, ?) as dow,
                  local_hour(started_at, ?) as hour,
                  COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM counted_plays
           WHERE started_at >= ? AND started_at < ?
           GROUP BY dow, hour
           ORDER BY dow, hour""",
        [period.tz, period.tz, *period.bounds],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_concurrent_streams(
    db: aiosqlite.Connection, period: Period
) -> list[dict]:
    """Peak simultaneous streams per local day, and how many of those were transcodes.

    Sweep line over start/stop events; a stream spanning midnight counts toward each
    local day it overlaps. A stop at the same instant as a start is not concurrent.
    """
    start, end = period.bounds
    cursor = await db.execute(
        """SELECT started_at, stopped_at, play_method = 'Transcode' as transcode
           FROM counted_plays
           WHERE started_at < ? AND stopped_at > ?""",
        [end, start],
    )
    # Event order at equal instants: stop (0), day boundary (1), start (2).
    events = []
    for r in await cursor.fetchall():
        tc = 1 if r["transcode"] else 0
        events.append((_local(r["started_at"], period.tz), 2, tc))
        events.append((_local(r["stopped_at"], period.tz), 0, tc))
    for day in period.day_keys():
        midnight = datetime.combine(date.fromisoformat(day), time.min, _zone(period.tz))
        events.append((midnight, 1, 0))
    events.sort(key=lambda e: (e[0], e[1]))

    peaks: dict[str, dict] = {}
    active = active_tc = 0
    for at, kind, tc in events:
        if kind == 0:
            active -= 1
            active_tc -= tc
            continue
        if kind == 2:
            active += 1
            active_tc += tc
        day = at.date().isoformat()
        best = peaks.get(day)
        # Among equal peaks, report the moment with the most transcodes.
        if best is None or (active, active_tc) > (best["peak"], best["peak_transcode"]):
            peaks[day] = {"date": day, "peak": active, "peak_transcode": active_tc}
    return period.fill_days(list(peaks.values()), peak=0, peak_transcode=0)

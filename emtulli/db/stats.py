import aiosqlite


async def get_total_plays(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM history")
    row = await cursor.fetchone()
    return row[0]


async def get_total_duration(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COALESCE(SUM(duration_seconds), 0) FROM history")
    row = await cursor.fetchone()
    return row[0]


async def get_top_users(db: aiosqlite.Connection, limit: int = 5, days: int = 30, metric: str = "plays") -> list[dict]:
    order = "plays" if metric == "plays" else "total_duration"
    cursor = await db.execute(
        f"""SELECT user_id, user_name, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE started_at >= datetime('now', ?)
           GROUP BY user_id
           ORDER BY {order} DESC LIMIT ?""",
        [f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_watched_movies(db: aiosqlite.Connection, limit: int = 5, days: int = 30, metric: str = "plays") -> list[dict]:
    order = "plays" if metric == "plays" else "total_duration"
    cursor = await db.execute(
        f"""SELECT item_id, item_name, year, COUNT(*) as plays,
                  COUNT(DISTINCT user_id) as users,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE item_type = 'Movie' AND started_at >= datetime('now', ?)
           GROUP BY item_id
           ORDER BY {order} DESC LIMIT ?""",
        [f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_popular_movies(db: aiosqlite.Connection, limit: int = 5, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_id, item_name, year, COUNT(DISTINCT user_id) as users,
                  COUNT(*) as plays
           FROM history
           WHERE item_type = 'Movie' AND started_at >= datetime('now', ?)
           GROUP BY item_id
           ORDER BY users DESC, plays DESC LIMIT ?""",
        [f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_watched_shows(db: aiosqlite.Connection, limit: int = 5, days: int = 30, metric: str = "plays") -> list[dict]:
    order = "plays" if metric == "plays" else "total_duration"
    cursor = await db.execute(
        f"""SELECT series_name, COUNT(*) as plays,
                  COUNT(DISTINCT user_id) as users,
                  SUM(duration_seconds) as total_duration,
                  COALESCE(series_id, MIN(item_id)) as poster_id
           FROM history
           WHERE item_type = 'Episode' AND series_name IS NOT NULL
                 AND started_at >= datetime('now', ?)
           GROUP BY series_name
           ORDER BY {order} DESC LIMIT ?""",
        [f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_popular_shows(db: aiosqlite.Connection, limit: int = 5, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT series_name, COUNT(DISTINCT user_id) as users,
                  COUNT(*) as plays,
                  COALESCE(series_id, MIN(item_id)) as poster_id
           FROM history
           WHERE item_type = 'Episode' AND series_name IS NOT NULL
                 AND started_at >= datetime('now', ?)
           GROUP BY series_name
           ORDER BY users DESC, plays DESC LIMIT ?""",
        [f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_recently_watched(db: aiosqlite.Connection, limit: int = 5) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_id, item_name, series_name, series_id, season_number, episode_number,
                  item_type, year, user_name, started_at
           FROM history
           ORDER BY started_at DESC LIMIT ?""",
        [limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_active_platforms(db: aiosqlite.Connection, limit: int = 5, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT client, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE started_at >= datetime('now', ?)
           GROUP BY client
           ORDER BY plays DESC LIMIT ?""",
        [f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_active_libraries(db: aiosqlite.Connection, limit: int = 5, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_type, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE started_at >= datetime('now', ?)
           GROUP BY item_type
           ORDER BY plays DESC LIMIT ?""",
        [f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_plays_per_day(db: aiosqlite.Connection, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT DATE(started_at) as date, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE started_at >= datetime('now', ?)
           GROUP BY DATE(started_at)
           ORDER BY date""",
        [f"-{days} days"],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_plays_by_type(db: aiosqlite.Connection, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_type, COUNT(*) as plays
           FROM history
           WHERE started_at >= datetime('now', ?)
           GROUP BY item_type ORDER BY plays DESC""",
        [f"-{days} days"],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_stats(db: aiosqlite.Connection, user_id: str) -> dict:
    cursor = await db.execute(
        """SELECT COUNT(*) as total_plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration,
                  MAX(started_at) as last_play
           FROM history WHERE user_id = ?""",
        [user_id],
    )
    row = await cursor.fetchone()
    return dict(row)


async def get_item_stats(db: aiosqlite.Connection, item_id: str) -> dict:
    """Get play stats for a specific item across time periods."""
    result = {}
    for label, days_expr in [
        ("last_24h", "-1 days"),
        ("last_7d", "-7 days"),
        ("last_30d", "-30 days"),
        ("all_time", "-99999 days"),
    ]:
        cursor = await db.execute(
            """SELECT COUNT(*) as plays, COALESCE(SUM(duration_seconds), 0) as duration
               FROM history WHERE item_id = ? AND started_at >= datetime('now', ?)""",
            [item_id, days_expr],
        )
        row = await cursor.fetchone()
        result[label] = dict(row)
    return result


async def get_item_user_stats(db: aiosqlite.Connection, item_id: str) -> list[dict]:
    """Get per-user play stats for an item."""
    cursor = await db.execute(
        """SELECT user_id, user_name, COUNT(*) as plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration
           FROM history WHERE item_id = ?
           GROUP BY user_id ORDER BY plays DESC""",
        [item_id],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_series_stats(db: aiosqlite.Connection, series_name: str) -> dict:
    """Get play stats for a series across time periods."""
    result = {}
    for label, days_expr in [
        ("last_24h", "-1 days"),
        ("last_7d", "-7 days"),
        ("last_30d", "-30 days"),
        ("all_time", "-99999 days"),
    ]:
        cursor = await db.execute(
            """SELECT COUNT(*) as plays, COALESCE(SUM(duration_seconds), 0) as duration
               FROM history WHERE series_name = ? AND started_at >= datetime('now', ?)""",
            [series_name, days_expr],
        )
        row = await cursor.fetchone()
        result[label] = dict(row)
    return result


async def get_series_user_stats(db: aiosqlite.Connection, series_name: str) -> list[dict]:
    """Get per-user play stats for a series."""
    cursor = await db.execute(
        """SELECT user_id, user_name, COUNT(*) as plays,
                  COALESCE(SUM(duration_seconds), 0) as total_duration
           FROM history WHERE series_name = ?
           GROUP BY user_id ORDER BY plays DESC""",
        [series_name],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_plays_per_day(db: aiosqlite.Connection, user_id: str, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT DATE(started_at) as date, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE user_id = ? AND started_at >= datetime('now', ?)
           GROUP BY DATE(started_at)
           ORDER BY date""",
        [user_id, f"-{days} days"],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_plays_by_type(db: aiosqlite.Connection, user_id: str, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_type, COUNT(*) as plays
           FROM history
           WHERE user_id = ? AND started_at >= datetime('now', ?)
           GROUP BY item_type ORDER BY plays DESC""",
        [user_id, f"-{days} days"],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user_most_watched(db: aiosqlite.Connection, user_id: str, limit: int = 10, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT
               COALESCE(series_name, item_name) as title,
               COALESCE(series_id, item_id) as poster_id,
               item_type,
               COUNT(*) as plays,
               SUM(duration_seconds) as total_duration
           FROM history
           WHERE user_id = ? AND started_at >= datetime('now', ?)
           GROUP BY COALESCE(series_name, item_name)
           ORDER BY plays DESC LIMIT ?""",
        [user_id, f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_library_stats(db: aiosqlite.Connection, item_type: str, days: int = 30) -> dict:
    result = {}
    for label, days_expr in [
        ("last_7d", "-7 days"),
        ("last_30d", "-30 days"),
        ("all_time", "-99999 days"),
    ]:
        cursor = await db.execute(
            """SELECT COUNT(*) as plays,
                      COALESCE(SUM(duration_seconds), 0) as duration,
                      COUNT(DISTINCT user_id) as users
               FROM history WHERE item_type = ? AND started_at >= datetime('now', ?)""",
            [item_type, days_expr],
        )
        row = await cursor.fetchone()
        result[label] = dict(row)
    return result


async def get_library_top_items(db: aiosqlite.Connection, item_type: str, limit: int = 10, days: int = 30) -> list[dict]:
    if item_type == "Episode":
        cursor = await db.execute(
            """SELECT series_name as title,
                      COALESCE(series_id, MIN(item_id)) as poster_id,
                      COUNT(*) as plays,
                      SUM(duration_seconds) as total_duration,
                      COUNT(DISTINCT user_id) as users
               FROM history
               WHERE item_type = ? AND started_at >= datetime('now', ?)
               GROUP BY series_name
               ORDER BY plays DESC LIMIT ?""",
            [item_type, f"-{days} days", limit],
        )
    else:
        cursor = await db.execute(
            """SELECT item_name as title, item_id as poster_id,
                      COUNT(*) as plays,
                      SUM(duration_seconds) as total_duration,
                      COUNT(DISTINCT user_id) as users
               FROM history
               WHERE item_type = ? AND started_at >= datetime('now', ?)
               GROUP BY item_id
               ORDER BY plays DESC LIMIT ?""",
            [item_type, f"-{days} days", limit],
        )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_library_top_users(db: aiosqlite.Connection, item_type: str, limit: int = 10, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT user_id, user_name, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE item_type = ? AND started_at >= datetime('now', ?)
           GROUP BY user_id
           ORDER BY plays DESC LIMIT ?""",
        [item_type, f"-{days} days", limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_library_plays_per_day(db: aiosqlite.Connection, item_type: str, days: int = 30) -> list[dict]:
    cursor = await db.execute(
        """SELECT DATE(started_at) as date, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history
           WHERE item_type = ? AND started_at >= datetime('now', ?)
           GROUP BY DATE(started_at)
           ORDER BY date""",
        [item_type, f"-{days} days"],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_most_played(db: aiosqlite.Connection, limit: int = 10) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_name, series_name, item_type, year, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history GROUP BY item_id
           ORDER BY plays DESC LIMIT ?""",
        [limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]

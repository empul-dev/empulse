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
                  MIN(item_id) as item_id
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
                  MIN(item_id) as item_id
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
        """SELECT item_id, item_name, series_name, season_number, episode_number,
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


async def get_plays_by_type(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute(
        """SELECT item_type, COUNT(*) as plays
           FROM history GROUP BY item_type ORDER BY plays DESC"""
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

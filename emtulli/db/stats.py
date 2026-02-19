import aiosqlite


async def get_total_plays(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COUNT(*) FROM history")
    row = await cursor.fetchone()
    return row[0]


async def get_total_duration(db: aiosqlite.Connection) -> int:
    cursor = await db.execute("SELECT COALESCE(SUM(duration_seconds), 0) FROM history")
    row = await cursor.fetchone()
    return row[0]


async def get_top_users(db: aiosqlite.Connection, limit: int = 10) -> list[dict]:
    cursor = await db.execute(
        """SELECT user_id, user_name, COUNT(*) as plays,
                  SUM(duration_seconds) as total_duration
           FROM history GROUP BY user_id
           ORDER BY plays DESC LIMIT ?""",
        [limit],
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

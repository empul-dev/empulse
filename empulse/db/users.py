import aiosqlite


async def upsert_user(db: aiosqlite.Connection, data: dict):
    await db.execute(
        """INSERT INTO users (emby_user_id, username, is_admin, thumb_url, last_seen)
           VALUES (:emby_user_id, :username, :is_admin, :thumb_url, :last_seen)
           ON CONFLICT(emby_user_id) DO UPDATE SET
             username = excluded.username,
             is_admin = excluded.is_admin,
             thumb_url = excluded.thumb_url,
             last_seen = COALESCE(excluded.last_seen, users.last_seen)""",
        data,
    )
    await db.commit()


async def set_user_enabled(db: aiosqlite.Connection, emby_user_id: str, enabled: bool):
    await db.execute(
        "UPDATE users SET enabled = ? WHERE emby_user_id = ?",
        [1 if enabled else 0, emby_user_id],
    )
    await db.commit()


async def is_user_enabled(db: aiosqlite.Connection, emby_user_id: str) -> bool:
    cursor = await db.execute(
        "SELECT enabled FROM users WHERE emby_user_id = ?", [emby_user_id]
    )
    row = await cursor.fetchone()
    return bool(row and row[0])


async def update_user_stats(db: aiosqlite.Connection, user_id: str, duration: int):
    await db.execute(
        """UPDATE users SET
             total_plays = total_plays + 1,
             total_duration = total_duration + ?,
             last_seen = datetime('now')
           WHERE emby_user_id = ?""",
        [duration, user_id],
    )
    await db.commit()


# Derive total_plays/total_duration from counted_plays (the single source of
# truth) rather than the stored counter columns, which drift and can accumulate
# absurd values (e.g. pre-cap zombie sessions). ponytail: counter columns left
# in place but no longer read.
_USER_SELECT = """
    SELECT u.id, u.emby_user_id, u.username, u.is_admin, u.enabled,
           u.thumb_url, u.last_seen,
           COALESCE(cp.plays, 0) AS total_plays,
           COALESCE(cp.duration, 0) AS total_duration
    FROM users u
    LEFT JOIN (SELECT user_id, COUNT(*) AS plays, SUM(duration_seconds) AS duration
               FROM counted_plays GROUP BY user_id) cp
      ON cp.user_id = u.emby_user_id
"""


USER_SORT_COLUMNS = {
    "user": "u.username COLLATE NOCASE",
    "plays": "total_plays",
    "duration": "total_duration",
    # Normalise: logins store ISO "T…+00:00", playback stores "YYYY-MM-DD HH:MM:SS".
    "last_seen": "datetime(u.last_seen)",
}


async def get_all_users(
    db: aiosqlite.Connection, sort_by: str = "plays", sort_order: str = "desc"
) -> list[dict]:
    col = USER_SORT_COLUMNS.get(sort_by, USER_SORT_COLUMNS["plays"])
    direction = "ASC" if sort_order == "asc" else "DESC"
    cursor = await db.execute(
        _USER_SELECT + f" ORDER BY {col} {direction}, u.username COLLATE NOCASE"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user(db: aiosqlite.Connection, emby_user_id: str) -> dict | None:
    cursor = await db.execute(
        _USER_SELECT + " WHERE u.emby_user_id = ?", [emby_user_id]
    )
    row = await cursor.fetchone()
    return dict(row) if row else None

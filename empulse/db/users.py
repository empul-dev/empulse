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


async def get_all_users(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("SELECT * FROM users ORDER BY total_plays DESC")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_user(db: aiosqlite.Connection, emby_user_id: str) -> dict | None:
    cursor = await db.execute("SELECT * FROM users WHERE emby_user_id = ?", [emby_user_id])
    row = await cursor.fetchone()
    return dict(row) if row else None

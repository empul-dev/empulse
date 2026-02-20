import aiosqlite


HISTORY_COLUMNS = frozenset({
    "session_key", "user_id", "user_name", "client", "device_name",
    "ip_address", "item_id", "item_name", "item_type", "series_name",
    "series_id", "season_number", "episode_number", "year",
    "runtime_ticks", "progress_ticks", "play_method",
    "transcode_video_codec", "transcode_audio_codec",
    "video_decision", "audio_decision", "stream_info",
    "started_at", "stopped_at", "duration_seconds", "paused_seconds",
    "percent_complete", "watched",
})


async def insert_history(db: aiosqlite.Connection, data: dict):
    safe_data = {k: v for k, v in data.items() if k in HISTORY_COLUMNS}
    cols = ", ".join(safe_data.keys())
    placeholders = ", ".join(["?"] * len(safe_data))
    await db.execute(
        f"INSERT INTO history ({cols}) VALUES ({placeholders})",
        list(safe_data.values()),
    )
    await db.commit()


SORTABLE_COLUMNS = {
    "date": "started_at",
    "user": "user_name",
    "title": "item_name",
    "started": "started_at",
    "stopped": "stopped_at",
    "duration": "duration_seconds",
    "play_method": "play_method",
    "player": "device_name",
    "product": "client",
    "ip": "ip_address",
}


async def get_history(
    db: aiosqlite.Connection,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
    item_type: str | None = None,
    play_method: str | None = None,
    search: str | None = None,
    sort_by: str = "date",
    sort_order: str = "desc",
) -> list[dict]:
    query = "SELECT * FROM history WHERE 1=1"
    params: list = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    if item_type:
        query += " AND item_type = ?"
        params.append(item_type)
    if play_method:
        query += " AND play_method = ?"
        params.append(play_method)
    if search:
        query += " AND (item_name LIKE ? OR series_name LIKE ? OR user_name LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])

    col = SORTABLE_COLUMNS.get(sort_by, "started_at")
    direction = "ASC" if sort_order == "asc" else "DESC"
    query += f" ORDER BY {col} {direction} LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor = await db.execute(query, params)
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_history_count(
    db: aiosqlite.Connection,
    user_id: str | None = None,
    item_type: str | None = None,
    play_method: str | None = None,
    search: str | None = None,
) -> int:
    query = "SELECT COUNT(*) FROM history WHERE 1=1"
    params: list = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)
    if item_type:
        query += " AND item_type = ?"
        params.append(item_type)
    if play_method:
        query += " AND play_method = ?"
        params.append(play_method)
    if search:
        query += " AND (item_name LIKE ? OR series_name LIKE ? OR user_name LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term])

    cursor = await db.execute(query, params)
    row = await cursor.fetchone()
    return row[0]


async def find_recent_history(
    db: aiosqlite.Connection, user_id: str, item_id: str, minutes: int = 30
) -> dict | None:
    """Find a recent history record for the same user+item (for session merging)."""
    cursor = await db.execute(
        "SELECT * FROM history WHERE user_id = ? AND item_id = ? "
        "ORDER BY stopped_at DESC LIMIT 1",
        [user_id, item_id],
    )
    row = await cursor.fetchone()
    if not row:
        return None
    record = dict(row)
    # Check if it was stopped recently enough to merge
    from datetime import datetime, timezone, timedelta
    try:
        stopped = datetime.fromisoformat(record["stopped_at"])
        if datetime.now(timezone.utc) - stopped < timedelta(minutes=minutes):
            return record
    except (ValueError, TypeError, KeyError):
        pass
    return None


async def merge_history(db: aiosqlite.Connection, history_id: int, data: dict):
    """Merge a new session into an existing history record (update stop time, accumulate duration/pause)."""
    await db.execute(
        "UPDATE history SET stopped_at = ?, duration_seconds = ?, paused_seconds = ?, "
        "percent_complete = ?, watched = ?, progress_ticks = ?, stream_info = ? WHERE id = ?",
        [
            data["stopped_at"],
            data["duration_seconds"],
            data["paused_seconds"],
            data["percent_complete"],
            data["watched"],
            data.get("progress_ticks", 0),
            data.get("stream_info", "{}"),
            history_id,
        ],
    )
    await db.commit()


async def get_history_by_id(db: aiosqlite.Connection, history_id: int) -> dict | None:
    cursor = await db.execute("SELECT * FROM history WHERE id = ?", [history_id])
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_history_for_user(db: aiosqlite.Connection, user_id: str, limit: int = 50) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM history WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
        [user_id, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]

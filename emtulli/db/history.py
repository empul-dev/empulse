import aiosqlite


async def insert_history(db: aiosqlite.Connection, data: dict):
    cols = ", ".join(data.keys())
    placeholders = ", ".join(["?"] * len(data))
    await db.execute(
        f"INSERT INTO history ({cols}) VALUES ({placeholders})",
        list(data.values()),
    )
    await db.commit()


async def get_history(
    db: aiosqlite.Connection,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
    item_type: str | None = None,
    play_method: str | None = None,
    search: str | None = None,
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

    query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
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


async def get_history_for_user(db: aiosqlite.Connection, user_id: str, limit: int = 50) -> list[dict]:
    cursor = await db.execute(
        "SELECT * FROM history WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
        [user_id, limit],
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]

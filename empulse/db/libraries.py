import aiosqlite


async def upsert_library(db: aiosqlite.Connection, data: dict):
    await db.execute(
        """INSERT INTO libraries (emby_library_id, name, library_type, item_count)
           VALUES (:emby_library_id, :name, :library_type, :item_count)
           ON CONFLICT(emby_library_id) DO UPDATE SET
             name = excluded.name,
             library_type = excluded.library_type,
             item_count = excluded.item_count""",
        data,
    )
    await db.commit()


async def get_all_libraries(db: aiosqlite.Connection) -> list[dict]:
    cursor = await db.execute("SELECT * FROM libraries ORDER BY name")
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def upsert_server_info(db: aiosqlite.Connection, data: dict):
    await db.execute(
        """INSERT INTO server_info (id, server_name, version, local_address, wan_address, os)
           VALUES (1, :server_name, :version, :local_address, :wan_address, :os)
           ON CONFLICT(id) DO UPDATE SET
             server_name = excluded.server_name,
             version = excluded.version,
             local_address = excluded.local_address,
             wan_address = excluded.wan_address,
             os = excluded.os""",
        data,
    )
    await db.commit()


async def get_server_info(db: aiosqlite.Connection) -> dict | None:
    cursor = await db.execute("SELECT * FROM server_info WHERE id = 1")
    row = await cursor.fetchone()
    return dict(row) if row else None

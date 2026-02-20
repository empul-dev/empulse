import aiosqlite
import logging
from pathlib import Path

from empulse.config import settings

logger = logging.getLogger("empulse.db")

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT UNIQUE NOT NULL,
    user_id TEXT,
    user_name TEXT,
    client TEXT,
    device_name TEXT,
    ip_address TEXT,
    item_id TEXT,
    item_name TEXT,
    item_type TEXT,
    series_name TEXT,
    series_id TEXT,
    season_number INTEGER,
    episode_number INTEGER,
    year INTEGER,
    runtime_ticks INTEGER DEFAULT 0,
    progress_ticks INTEGER DEFAULT 0,
    is_paused INTEGER DEFAULT 0,
    play_method TEXT,
    transcode_video_codec TEXT,
    transcode_audio_codec TEXT,
    video_decision TEXT,
    audio_decision TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    state TEXT DEFAULT 'playing'
);

CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT NOT NULL,
    user_id TEXT,
    user_name TEXT,
    client TEXT,
    device_name TEXT,
    ip_address TEXT,
    item_id TEXT,
    item_name TEXT,
    item_type TEXT,
    series_name TEXT,
    series_id TEXT,
    season_number INTEGER,
    episode_number INTEGER,
    year INTEGER,
    runtime_ticks INTEGER DEFAULT 0,
    progress_ticks INTEGER DEFAULT 0,
    play_method TEXT,
    transcode_video_codec TEXT,
    transcode_audio_codec TEXT,
    video_decision TEXT,
    audio_decision TEXT,
    stream_info TEXT DEFAULT '{}',
    started_at TEXT NOT NULL,
    stopped_at TEXT NOT NULL,
    duration_seconds INTEGER DEFAULT 0,
    paused_seconds INTEGER DEFAULT 0,
    percent_complete REAL DEFAULT 0,
    watched INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_history_user_id ON history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_item_id ON history(item_id);
CREATE INDEX IF NOT EXISTS idx_history_started_at ON history(started_at);
CREATE INDEX IF NOT EXISTS idx_history_item_type ON history(item_type);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emby_user_id TEXT UNIQUE NOT NULL,
    username TEXT,
    is_admin INTEGER DEFAULT 0,
    thumb_url TEXT,
    last_seen TEXT,
    total_plays INTEGER DEFAULT 0,
    total_duration INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS libraries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emby_library_id TEXT UNIQUE NOT NULL,
    name TEXT,
    library_type TEXT,
    item_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS server_info (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    server_name TEXT,
    version TEXT,
    local_address TEXT,
    wan_address TEXT,
    os TEXT
);

CREATE TABLE IF NOT EXISTS notification_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    config TEXT NOT NULL DEFAULT '{}',
    triggers TEXT NOT NULL DEFAULT '[]',
    conditions TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ip_locations (
    ip TEXT PRIMARY KEY,
    city TEXT,
    country TEXT,
    latitude REAL DEFAULT 0,
    longitude REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS newsletter_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    enabled INTEGER DEFAULT 0,
    schedule TEXT DEFAULT 'weekly',
    day_of_week INTEGER DEFAULT 0,
    hour INTEGER DEFAULT 9,
    recently_added_days INTEGER DEFAULT 7,
    recently_added_limit INTEGER DEFAULT 20,
    include_stats INTEGER DEFAULT 1,
    smtp_host TEXT,
    smtp_port INTEGER DEFAULT 587,
    smtp_user TEXT,
    smtp_pass TEXT,
    smtp_tls INTEGER DEFAULT 1,
    from_addr TEXT,
    to_addrs TEXT DEFAULT '',
    last_sent TEXT
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id INTEGER,
    event_type TEXT NOT NULL,
    event_summary TEXT,
    status TEXT DEFAULT 'sent',
    error TEXT,
    sent_at TEXT NOT NULL
);
"""


async def init_db():
    global _db
    db_path = Path(settings.db_path)
    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    # Migrations — add columns that may not exist yet
    await _migrate(_db)
    # Clear ephemeral sessions on startup
    await _db.execute("DELETE FROM sessions")
    await _db.commit()
    logger.info(f"Database ready at {db_path}")


async def _migrate(db: aiosqlite.Connection):
    """Add columns that may be missing from older databases."""
    cursor = await db.execute("PRAGMA table_info(history)")
    cols = {row[1] for row in await cursor.fetchall()}
    if "stream_info" not in cols:
        await db.execute("ALTER TABLE history ADD COLUMN stream_info TEXT DEFAULT '{}'")
        logger.info("Migration: added stream_info column to history")
    if "city" not in cols:
        await db.execute("ALTER TABLE history ADD COLUMN city TEXT")
        await db.execute("ALTER TABLE history ADD COLUMN country TEXT")
        await db.execute("ALTER TABLE history ADD COLUMN latitude REAL")
        await db.execute("ALTER TABLE history ADD COLUMN longitude REAL")
        logger.info("Migration: added geo columns to history")
    await db.commit()


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized"
    return _db

import aiosqlite
import logging
from pathlib import Path

from emtulli.config import settings

logger = logging.getLogger("emtulli.db")

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
"""


async def init_db():
    global _db
    db_path = Path(settings.db_path)
    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA busy_timeout=5000")
    await _db.executescript(SCHEMA)
    # Clear ephemeral sessions on startup
    await _db.execute("DELETE FROM sessions")
    await _db.commit()
    logger.info(f"Database ready at {db_path}")


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized"
    return _db

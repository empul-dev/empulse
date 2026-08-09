import aiosqlite
import logging
from pathlib import Path

from empulse.config import settings

logger = logging.getLogger("empulse.db")

_db: aiosqlite.Connection | None = None

# Minimum watched seconds for a history row to count as a real "play". Trivial
# rows (false starts, samples) stay in the history table but are excluded from
# all stat/count queries via the counted_plays view. ponytail: 600s (10 min)
# matches the user's "9-min sample isn't a play"; lower it if short-runtime
# items (music videos, anime shorts) legitimately get dropped from counts.
MIN_PLAY_SECONDS = 600

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
    pause_events TEXT DEFAULT '[]',
    percent_complete REAL DEFAULT 0,
    watched INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_history_user_id ON history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_item_id ON history(item_id);
CREATE INDEX IF NOT EXISTS idx_history_started_at ON history(started_at);
CREATE INDEX IF NOT EXISTS idx_history_item_type ON history(item_type);
CREATE INDEX IF NOT EXISTS idx_history_user_started ON history(user_id, started_at);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emby_user_id TEXT UNIQUE NOT NULL,
    username TEXT,
    is_admin INTEGER DEFAULT 0,
    enabled INTEGER DEFAULT 0,
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

CREATE TABLE IF NOT EXISTS login_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT UNIQUE NOT NULL,
    emby_user_id TEXT,
    username TEXT,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip_address TEXT,
    user_agent TEXT,
    revoked INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_login_sessions_token ON login_sessions(token_hash);

CREATE TABLE IF NOT EXISTS display_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    date_format TEXT DEFAULT 'YYYY-MM-DD',
    time_format TEXT DEFAULT '24h',
    week_start TEXT DEFAULT 'monday',
    timezone TEXT DEFAULT 'UTC'
);
""" + (
    "CREATE VIEW IF NOT EXISTS counted_plays AS "
    f"SELECT * FROM history WHERE duration_seconds >= {MIN_PLAY_SECONDS};\n"
)


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
    """Add columns/tables that may be missing from older databases."""
    cursor = await db.execute("PRAGMA table_info(history)")
    cols = {row[1] for row in await cursor.fetchall()}
    if "stream_info" not in cols:
        await db.execute("ALTER TABLE history ADD COLUMN stream_info TEXT DEFAULT '{}'")
        logger.info("Migration: added stream_info column to history")

    # Add enabled column to users if missing
    cursor = await db.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in await cursor.fetchall()}
    if "enabled" not in user_cols:
        await db.execute("ALTER TABLE users ADD COLUMN enabled INTEGER DEFAULT 0")
        # Auto-enable existing admins
        await db.execute("UPDATE users SET enabled = 1 WHERE is_admin = 1")
        logger.info("Migration: added enabled column to users")

    if "pause_events" not in cols:
        await db.execute(
            "ALTER TABLE history ADD COLUMN pause_events TEXT DEFAULT '[]'"
        )
        logger.info("Migration: added pause_events column to history")

    # Ensure login_sessions table exists (for pre-existing DBs)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS login_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT UNIQUE NOT NULL,
            emby_user_id TEXT,
            username TEXT,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            ip_address TEXT,
            user_agent TEXT,
            revoked INTEGER DEFAULT 0
        )
    """)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_sessions_token ON login_sessions(token_hash)"
    )

    # D-4: composite index for per-user stats queries (the single-column indexes
    # ship in SCHEMA; this one covers WHERE user_id = ? ORDER BY started_at).
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_user_started "
        "ON history(user_id, started_at)"
    )

    # Ensure display_settings table exists (for pre-existing DBs)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS display_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            date_format TEXT DEFAULT 'YYYY-MM-DD',
            time_format TEXT DEFAULT '24h',
            week_start TEXT DEFAULT 'monday',
            timezone TEXT DEFAULT 'UTC'
        )
    """)

    # Recreate the counted_plays view (drop+create so tuning MIN_PLAY_SECONDS
    # takes effect on restart). Stats/count queries read from this; the history
    # table keeps every row so the history page still shows sub-threshold plays.
    await db.execute("DROP VIEW IF EXISTS counted_plays")
    await db.execute(
        "CREATE VIEW counted_plays AS SELECT * FROM history "
        f"WHERE duration_seconds >= {MIN_PLAY_SECONDS}"
    )

    # Cleanup expired login sessions
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    await db.execute("DELETE FROM login_sessions WHERE expires_at < ?", [now])

    await db.commit()

    await _encrypt_legacy_secrets(db)


async def _encrypt_legacy_secrets(db: aiosqlite.Connection):
    """One-time upgrade pass: encrypt any plaintext notification/newsletter
    secrets left over from before secrets were encrypted at rest. Safe to run
    on every boot — encrypt_secret / encrypt_channel_config are idempotent for
    values that are already encrypted."""
    import json as _json

    from empulse.crypto import encrypt_secret
    from empulse.notifications.secrets import (
        CHANNEL_SECRET_FIELDS,
        encrypt_channel_config,
    )

    cursor = await db.execute("SELECT id, channel_type, config FROM notification_channels")
    rows = await cursor.fetchall()
    for row in rows:
        channel_type = row["channel_type"]
        if channel_type not in CHANNEL_SECRET_FIELDS:
            continue
        try:
            config = _json.loads(row["config"] or "{}")
        except (_json.JSONDecodeError, TypeError):
            continue
        if not isinstance(config, dict):
            continue
        encrypted = encrypt_channel_config(channel_type, config)
        if encrypted != config:
            await db.execute(
                "UPDATE notification_channels SET config = ? WHERE id = ?",
                [_json.dumps(encrypted), row["id"]],
            )
            logger.info(f"Migration: encrypted secrets for notification channel {row['id']}")

    cursor = await db.execute("SELECT smtp_pass FROM newsletter_config WHERE id = 1")
    row = await cursor.fetchone()
    if row and row["smtp_pass"]:
        encrypted_pass = encrypt_secret(row["smtp_pass"])
        if encrypted_pass != row["smtp_pass"]:
            await db.execute(
                "UPDATE newsletter_config SET smtp_pass = ? WHERE id = 1", [encrypted_pass]
            )
            logger.info("Migration: encrypted newsletter SMTP password")

    await db.commit()


def get_db() -> aiosqlite.Connection:
    assert _db is not None, "Database not initialized"
    return _db

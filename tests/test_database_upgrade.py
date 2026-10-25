"""Exercise startup migrations on fresh and existing database files."""

import sqlite3

import pytest

from empulse import database

RETIRED_TABLES = {"notification_channels", "notification_log", "newsletter_config"}

# Tables as written by 0.2.19 and earlier releases.
LEGACY_RETIRED_SCHEMA = """
    CREATE TABLE IF NOT EXISTS notification_channels (
        id INTEGER PRIMARY KEY, name TEXT, channel_type TEXT,
        config TEXT, triggers TEXT, conditions TEXT,
        enabled INTEGER, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS notification_log (
        id INTEGER PRIMARY KEY, channel_id INTEGER, event_type TEXT,
        event_summary TEXT, status TEXT, error TEXT, sent_at TEXT
    );
    CREATE TABLE IF NOT EXISTS newsletter_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        enabled INTEGER DEFAULT 0, schedule TEXT DEFAULT 'weekly',
        day_of_week INTEGER DEFAULT 0, hour INTEGER DEFAULT 9,
        recently_added_days INTEGER DEFAULT 7, recently_added_limit INTEGER DEFAULT 20,
        include_stats INTEGER DEFAULT 1, smtp_host TEXT, smtp_port INTEGER DEFAULT 587,
        smtp_user TEXT, smtp_pass TEXT, smtp_tls INTEGER DEFAULT 1,
        from_addr TEXT, to_addrs TEXT DEFAULT '', last_sent TEXT
    );
"""


@pytest.mark.parametrize("legacy", [False, True])
async def test_startup_upgrade_preserves_retained_data(tmp_path, monkeypatch, legacy):
    path = tmp_path / "empulse.db"
    if legacy:
        with sqlite3.connect(path) as db:
            db.executescript(database.SCHEMA)
            db.executescript(LEGACY_RETIRED_SCHEMA)
            db.executescript("""
                INSERT INTO notification_channels (id, name, channel_type, config, created_at)
                    VALUES (1, 'Retired channel', 'ntfy', 'invalid legacy config', '2026-01-01');
                INSERT INTO notification_log (id, channel_id, event_type, sent_at)
                    VALUES (1, 1, 'playback_start', '2026-01-01');
                INSERT INTO newsletter_config (id, enabled, smtp_pass, to_addrs)
                    VALUES (1, 1, 'enc:v1:retired', 'reader@example.com');
                INSERT INTO history
                    (session_key, user_id, started_at, stopped_at, duration_seconds)
                    VALUES ('session', 'user1', '2026-01-01', '2026-01-02', 7200);
                INSERT INTO users (emby_user_id, username, total_plays, total_duration)
                    VALUES ('user1', 'Alice', 1, 7200);
                INSERT INTO libraries (emby_library_id, name, item_count)
                    VALUES ('library1', 'Movies', 42);
            """)

    monkeypatch.setattr(database.settings, "db_path", str(path))
    monkeypatch.setattr(database, "_db", None)
    for _ in range(2):
        await database.init_db()
        db = database.get_db()
        try:
            tables = {row[0] for row in await (await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )).fetchall()}
            assert {"history", "users", "libraries", "login_sessions"} <= tables
            assert not RETIRED_TABLES & tables
            assert (await (await db.execute("PRAGMA integrity_check")).fetchone())[0] == "ok"
            if legacy:
                history = await (await db.execute("SELECT * FROM history")).fetchone()
                assert history["session_key"] == "session"
                assert history["duration_seconds"] == 7200
                user = await (await db.execute("SELECT * FROM users")).fetchone()
                assert (user["username"], user["total_plays"], user["total_duration"]) == (
                    "Alice", 1, 7200,
                )
                library = await (await db.execute("SELECT * FROM libraries")).fetchone()
                assert (library["name"], library["item_count"]) == ("Movies", 42)
        finally:
            await db.close()


@pytest.mark.parametrize("source_release", [None, "0.2.18", "0.2.19"])
async def test_retired_feature_removal_is_backed_up_and_recoverable(
    tmp_path, monkeypatch, source_release,
):
    from empulse.restore import restore_backup

    path = tmp_path / "empulse.db"
    with sqlite3.connect(path) as db:
        db.executescript(database.SCHEMA)
        db.executescript(LEGACY_RETIRED_SCHEMA)
        db.executescript("""
            INSERT INTO notification_channels (id, config) VALUES (1, 'saved channel');
            INSERT INTO notification_log (id, event_type) VALUES (1, 'playback_start');
            INSERT INTO newsletter_config (id, smtp_pass, to_addrs)
                VALUES (1, 'enc:v1:saved', 'reader@example.com');
        """)
        if source_release:
            db.execute("CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO app_metadata VALUES ('release', ?)", [source_release])

    monkeypatch.setattr(database.settings, "db_path", str(path))
    monkeypatch.setattr(database, "get_version", lambda: "0.2.20")
    monkeypatch.setattr(database, "_db", None)
    migrate = database._migrate

    async def broken_migration(db):
        await migrate(db)
        raise RuntimeError("Failure after table removal")

    monkeypatch.setattr(database, "_migrate", broken_migration)
    with pytest.raises(RuntimeError, match="after table removal"):
        await database.init_db()
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT config FROM notification_channels").fetchone() == ("saved channel",)
        assert db.execute("SELECT smtp_pass FROM newsletter_config").fetchone() == ("enc:v1:saved",)

    monkeypatch.setattr(database, "_migrate", migrate)
    try:
        await database.init_db()
        with sqlite3.connect(path) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
            assert not RETIRED_TABLES & tables
    finally:
        await database.close_db()

    backups = list((tmp_path / "backups" / "empulse.db").glob("update-*"))
    assert len(backups) == 1
    restore_backup(backups[0], path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT config FROM notification_channels").fetchone() == ("saved channel",)
        assert db.execute("SELECT event_type FROM notification_log").fetchone() == ("playback_start",)
        assert db.execute("SELECT smtp_pass, to_addrs FROM newsletter_config").fetchone() == (
            "enc:v1:saved", "reader@example.com",
        )
        if source_release:
            assert db.execute("SELECT value FROM app_metadata WHERE key = 'release'").fetchone() == (source_release,)
        else:
            assert db.execute("SELECT name FROM sqlite_master WHERE name = 'app_metadata'").fetchone() is None

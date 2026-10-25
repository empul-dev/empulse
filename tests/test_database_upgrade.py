"""Exercise startup migrations on fresh and existing database files."""

import sqlite3

import pytest

from empulse import database
from empulse.crypto import decrypt_secret, encrypt_secret


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("encrypted", [False, True])
async def test_startup_upgrade_preserves_retained_data(tmp_path, monkeypatch, legacy, encrypted):
    path = tmp_path / "empulse.db"
    password = encrypt_secret("smtp-password") if encrypted else "smtp-password"
    if legacy:
        with sqlite3.connect(path) as db:
            db.executescript(database.SCHEMA)
            db.executescript("""
                CREATE TABLE IF NOT EXISTS notification_channels (
                    id INTEGER PRIMARY KEY, name TEXT, channel_type TEXT,
                    config TEXT, triggers TEXT, conditions TEXT,
                    enabled INTEGER, created_at TEXT
                );
                CREATE TABLE IF NOT EXISTS notification_log (
                    id INTEGER PRIMARY KEY, channel_id INTEGER, event_type TEXT,
                    event_summary TEXT, status TEXT, error TEXT, sent_at TEXT
                );
                INSERT INTO notification_channels (id, name, channel_type, config, created_at)
                    VALUES (1, 'Retired channel', 'ntfy', 'invalid legacy config', '2026-01-01');
                INSERT INTO notification_log (id, channel_id, event_type, sent_at)
                    VALUES (1, 1, 'playback_start', '2026-01-01');
                INSERT INTO history
                    (session_key, user_id, started_at, stopped_at, duration_seconds)
                    VALUES ('session', 'user1', '2026-01-01', '2026-01-02', 7200);
                INSERT INTO users (emby_user_id, username, total_plays, total_duration)
                    VALUES ('user1', 'Alice', 1, 7200);
                INSERT INTO libraries (emby_library_id, name, item_count)
                    VALUES ('library1', 'Movies', 42);
            """)
            db.execute(
                "INSERT INTO newsletter_config "
                "(id, enabled, schedule, hour, smtp_pass, to_addrs, last_sent) "
                "VALUES (1, 1, 'weekly', 9, ?, 'reader@example.com', '2026-01-01')",
                [password],
            )

    monkeypatch.setattr(database.settings, "db_path", str(path))
    monkeypatch.setattr(database, "_db", None)
    stored_password = None
    for _ in range(2):
        await database.init_db()
        db = database.get_db()
        try:
            tables = {row[0] for row in await (await db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )).fetchall()}
            assert {"history", "users", "libraries", "newsletter_config"} <= tables
            assert not {"notification_channels", "notification_log"} & tables
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
                config = await (await db.execute("SELECT * FROM newsletter_config")).fetchone()
                assert (config["enabled"], config["schedule"], config["hour"]) == (1, "weekly", 9)
                assert config["to_addrs"] == "reader@example.com"
                assert config["last_sent"] == "2026-01-01"
                assert config["smtp_pass"].startswith("enc:v1:")
                assert decrypt_secret(config["smtp_pass"]) == "smtp-password"
                if encrypted:
                    assert config["smtp_pass"] == password
                if stored_password is not None:
                    assert config["smtp_pass"] == stored_password
                stored_password = config["smtp_pass"]
        finally:
            await db.close()


@pytest.mark.parametrize("source_release", [None, "0.2.18"])
async def test_notification_removal_is_backed_up_and_recoverable(
    tmp_path, monkeypatch, source_release,
):
    from empulse.restore import restore_backup

    path = tmp_path / "empulse.db"
    with sqlite3.connect(path) as db:
        db.executescript(database.SCHEMA)
        db.executescript("""
            CREATE TABLE notification_channels (id INTEGER PRIMARY KEY, config TEXT);
            INSERT INTO notification_channels VALUES (1, 'saved channel');
            CREATE TABLE notification_log (id INTEGER PRIMARY KEY, event_type TEXT);
            INSERT INTO notification_log VALUES (1, 'playback_start');
        """)
        if source_release:
            db.execute("CREATE TABLE app_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO app_metadata VALUES ('release', ?)", [source_release])

    monkeypatch.setattr(database.settings, "db_path", str(path))
    monkeypatch.setattr(database, "get_version", lambda: "0.2.19")
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

    monkeypatch.setattr(database, "_migrate", migrate)
    try:
        await database.init_db()
        with sqlite3.connect(path) as db:
            assert db.execute(
                "SELECT name FROM sqlite_master WHERE name IN (?, ?)",
                ["notification_channels", "notification_log"],
            ).fetchall() == []
    finally:
        await database.close_db()

    backups = list((tmp_path / "backups" / "empulse.db").glob("update-*"))
    assert len(backups) == 1
    restore_backup(backups[0], path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT config FROM notification_channels").fetchone() == ("saved channel",)
        assert db.execute("SELECT event_type FROM notification_log").fetchone() == ("playback_start",)
        if source_release:
            assert db.execute("SELECT value FROM app_metadata WHERE key = 'release'").fetchone() == (source_release,)
        else:
            assert db.execute("SELECT name FROM sqlite_master WHERE name = 'app_metadata'").fetchone() is None

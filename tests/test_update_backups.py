"""Exercise update backups against on-disk SQLite databases."""

import json
import sqlite3
from pathlib import Path

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet

from empulse import crypto, database


@pytest_asyncio.fixture
async def database_file(tmp_path, monkeypatch):
    path = tmp_path / "empulse.db"
    monkeypatch.setattr(database.settings, "db_path", str(path))
    monkeypatch.setattr(database.settings, "backup_retention", 3)
    monkeypatch.setattr(database.settings, "secret_key", "external-test-secret")
    monkeypatch.setattr(database, "get_version", lambda: "1.0.0")
    monkeypatch.setattr(database, "_db", None)
    yield path
    await database.close_db()


def snapshots(path: Path) -> list[Path]:
    return sorted((path.parent / "backups" / path.name).glob("*/database.sqlite3"))


def create_legacy(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(database.SCHEMA)
        conn.execute("DROP TABLE IF EXISTS app_metadata")
        conn.execute("CREATE TABLE saved_records (value TEXT)")
        conn.execute("INSERT INTO saved_records VALUES ('before update')")


def values(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute("SELECT value FROM saved_records")]


async def test_fresh_database_and_same_release_restart_need_no_backup(database_file):
    await database.init_db()
    await database.close_db()
    await database.init_db()
    assert snapshots(database_file) == []
    with sqlite3.connect(database_file) as conn:
        assert conn.execute(
            "SELECT value FROM app_metadata WHERE key = 'release'"
        ).fetchone() == ("1.0.0",)


async def test_legacy_upgrade_preserves_original_database_once(database_file):
    create_legacy(database_file)
    await database.init_db()
    await database.close_db()
    backup = snapshots(database_file)
    assert len(backup) == 1
    assert values(backup[0]) == ["before update"]
    with sqlite3.connect(backup[0]) as conn:
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'app_metadata'"
            ).fetchone()
            is None
        )
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert json.loads((backup[0].parent / "manifest.json").read_text())
    await database.init_db()
    assert snapshots(database_file) == backup


async def test_changed_release_backs_up_previous_release(database_file, monkeypatch):
    await database.init_db()
    await database.close_db()
    monkeypatch.setattr(database, "get_version", lambda: "1.1.0")
    await database.init_db()
    backup = snapshots(database_file)
    assert len(backup) == 1
    with sqlite3.connect(backup[0]) as conn:
        assert conn.execute(
            "SELECT value FROM app_metadata WHERE key = 'release'"
        ).fetchone() == ("1.0.0",)


async def test_backup_includes_committed_wal_records(database_file):
    create_legacy(database_file)
    source = sqlite3.connect(database_file)
    try:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("PRAGMA wal_autocheckpoint=0")
        source.execute("INSERT INTO saved_records VALUES ('committed in WAL')")
        source.commit()
        assert Path(str(database_file) + "-wal").stat().st_size > 0
        await database.init_db()
        assert values(snapshots(database_file)[0]) == [
            "before update",
            "committed in WAL",
        ]
    finally:
        source.close()


async def test_backup_failure_prevents_any_database_change(database_file):
    create_legacy(database_file)
    original_bytes = database_file.read_bytes()
    (database_file.parent / "backups").write_text("not a directory")
    with pytest.raises((OSError, RuntimeError)):
        await database.init_db()
    assert database_file.read_bytes() == original_bytes
    assert database._db is None


async def test_failed_migration_rolls_back_and_reuses_backup(
    database_file, monkeypatch
):
    create_legacy(database_file)
    original_migrate = database._migrate

    async def broken_migration(conn):
        await original_migrate(conn)
        await conn.execute("DELETE FROM saved_records")
        await conn.execute("CREATE TABLE partial_migration (id INTEGER)")
        raise RuntimeError("migration failed")

    monkeypatch.setattr(database, "_migrate", broken_migration)
    for _ in range(4):
        with pytest.raises(RuntimeError, match="migration failed"):
            await database.init_db()
        assert database._db is None
        assert values(database_file) == ["before update"]
        with sqlite3.connect(database_file) as conn:
            assert (
                conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE name IN ('partial_migration', 'app_metadata')"
                ).fetchall()
                == []
            )
        assert len(snapshots(database_file)) == 1
    monkeypatch.setattr(database, "_migrate", original_migrate)
    await database.init_db()
    assert len(snapshots(database_file)) == 1


async def test_snapshot_contains_key_needed_for_newsletter_password(
    database_file, monkeypatch
):
    create_legacy(database_file)
    secret = "persistent-local-test-secret"
    monkeypatch.setattr(database.settings, "secret_key", secret)
    (database_file.parent / ".empulse_secret").write_text(secret + "\n")
    encrypted = (
        crypto.ENC_PREFIX
        + Fernet(crypto._derive_key(secret)).encrypt(b"smtp-password").decode()
    )
    with sqlite3.connect(database_file) as conn:
        conn.execute(
            "INSERT INTO newsletter_config (id, smtp_pass) VALUES (1, ?)",
            (encrypted,),
        )
    await database.init_db()
    backup = snapshots(database_file)[0]
    saved_key = (backup.parent / ".empulse_secret").read_text().strip()
    with sqlite3.connect(backup) as conn:
        saved_password = conn.execute(
            "SELECT smtp_pass FROM newsletter_config WHERE id = 1"
        ).fetchone()[0]
    assert (
        Fernet(crypto._derive_key(saved_key)).decrypt(
            saved_password.removeprefix(crypto.ENC_PREFIX).encode()
        )
        == b"smtp-password"
    )
    assert backup.stat().st_mode & 0o077 == 0
    assert (backup.parent / ".empulse_secret").stat().st_mode & 0o077 == 0


async def test_external_secret_does_not_back_up_unrelated_key_file(database_file):
    create_legacy(database_file)
    (database_file.parent / ".empulse_secret").write_text("unused-old-key\n")
    await database.init_db()
    assert not (snapshots(database_file)[0].parent / ".empulse_secret").exists()


async def test_retention_keeps_last_three_successful_update_backups(
    database_file, monkeypatch
):
    create_legacy(database_file)
    for version in range(5):
        monkeypatch.setattr(database, "get_version", lambda v=version: f"1.0.{v}")
        await database.init_db()
        await database.close_db()
        with sqlite3.connect(database_file) as conn:
            conn.execute("DELETE FROM saved_records")
            conn.execute("INSERT INTO saved_records VALUES (?)", (str(version),))
    backup = snapshots(database_file)
    assert len(backup) == 3
    assert {tuple(values(path)) for path in backup} == {("1",), ("2",), ("3",)}


async def test_failed_update_does_not_prune_previous_backups(
    database_file, monkeypatch
):
    create_legacy(database_file)
    for version in range(3):
        monkeypatch.setattr(database, "get_version", lambda v=version: f"1.0.{v}")
        await database.init_db()
        await database.close_db()
    previous = snapshots(database_file)
    assert len(previous) == 3
    original_migrate = database._migrate

    async def broken_migration(conn):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(database, "get_version", lambda: "1.0.3")
    monkeypatch.setattr(database, "_migrate", broken_migration)
    with pytest.raises(RuntimeError, match="migration failed"):
        await database.init_db()
    assert all(path.exists() for path in previous)
    assert len(snapshots(database_file)) == 4
    monkeypatch.setattr(database, "_migrate", original_migrate)
    await database.init_db()
    assert len(snapshots(database_file)) == 3


async def test_retry_backs_up_data_written_by_previous_release(
    database_file, monkeypatch
):
    create_legacy(database_file)

    async def broken_migration(conn):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(database, "_migrate", broken_migration)
    with pytest.raises(RuntimeError, match="migration failed"):
        await database.init_db()
    with sqlite3.connect(database_file) as conn:
        conn.execute("INSERT INTO saved_records VALUES ('written after failed update')")
    with pytest.raises(RuntimeError, match="migration failed"):
        await database.init_db()
    assert len(snapshots(database_file)) == 2
    assert any(
        values(path) == ["before update", "written after failed update"]
        for path in snapshots(database_file)
    )


async def test_retry_replaces_corrupt_backup_before_migrating(
    database_file, monkeypatch
):
    create_legacy(database_file)
    original_migrate = database._migrate

    async def broken_migration(conn):
        raise RuntimeError("migration failed")

    monkeypatch.setattr(database, "_migrate", broken_migration)
    with pytest.raises(RuntimeError, match="migration failed"):
        await database.init_db()
    corrupted = snapshots(database_file)[0]
    corrupted.write_bytes(b"broken snapshot")
    monkeypatch.setattr(database, "_migrate", original_migrate)
    await database.init_db()
    valid = [path for path in snapshots(database_file) if path != corrupted]
    assert len(valid) == 1
    assert values(valid[0]) == ["before update"]

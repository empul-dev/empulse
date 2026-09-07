import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from empulse.backups import database_lock
from empulse.restore import main, restore_backup


def make_database(path: Path, value: str) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE history (title TEXT)")
        connection.execute("INSERT INTO history VALUES (?)", (value,))


def read_title(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return connection.execute("SELECT title FROM history").fetchone()[0]


def make_backup(path: Path, secret: str | None = "saved-secret") -> Path:
    path.mkdir()
    make_database(path / "database.sqlite3", "before update")
    manifest = {
        "format": 1,
        "source_version": "0.2.17",
        "target_version": "0.2.18",
        "database_sha256": hashlib.sha256(
            (path / "database.sqlite3").read_bytes()
        ).hexdigest(),
        "secret_source": "file" if secret else "external",
    }
    if secret:
        (path / ".empulse_secret").write_text(secret)
        manifest["secret_sha256"] = hashlib.sha256(secret.encode()).hexdigest()
    (path / "manifest.json").write_text(json.dumps(manifest))
    return path


def test_restore_database_key_and_rescue(tmp_path):
    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    make_database(database, "after update")
    key = tmp_path / ".empulse_secret"
    key.write_text("new-secret")

    rescue = restore_backup(backup, database)

    assert read_title(database) == "before update"
    assert key.read_text() == "saved-secret"
    assert read_title(rescue / database.name) == "after update"
    assert (rescue / key.name).read_text() == "new-secret"
    assert backup.exists()
    assert database.stat().st_mode & 0o777 == 0o600
    assert key.stat().st_mode & 0o777 == 0o600


def test_corrupt_backup_does_not_change_destination(tmp_path):
    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    make_database(database, "current")
    original = database.read_bytes()
    (backup / "database.sqlite3").write_bytes(b"corrupt")

    with pytest.raises((ValueError, RuntimeError)):
        restore_backup(backup, database)

    assert database.read_bytes() == original
    assert not list(tmp_path.glob("empulse.db.before-restore-*"))


def test_restore_preserves_external_secret(tmp_path):
    backup = make_backup(tmp_path / "backup", secret=None)
    database = tmp_path / "empulse.db"
    key = tmp_path / ".empulse_secret"
    key.write_text("keep-this-key")

    restore_backup(backup, database)

    assert read_title(database) == "before update"
    assert key.read_text() == "keep-this-key"


def test_restore_removes_wal_before_database_replacement(tmp_path):
    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    # Simulate a terminated process so SQLite leaves an actual committed WAL.
    script = """
import os, sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
conn.execute("PRAGMA journal_mode=WAL")
conn.execute("CREATE TABLE history (title TEXT)")
conn.execute("INSERT INTO history VALUES ('stale WAL')")
conn.commit()
os._exit(0)
"""
    subprocess.run([sys.executable, "-c", script, str(database)], check=True)
    assert Path(f"{database}-wal").exists()

    rescue = restore_backup(backup, database)

    assert not Path(f"{database}-wal").exists()
    assert not Path(f"{database}-shm").exists()
    assert read_title(database) == "before update"
    # The rescue also retains changes that existed only in the old WAL.
    assert read_title(rescue / database.name) == "stale WAL"


def test_restore_refuses_running_database(tmp_path):
    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    make_database(database, "current")

    with database_lock(database):
        with pytest.raises((OSError, RuntimeError)):
            restore_backup(backup, database)

    assert read_title(database) == "current"


def test_key_replacement_failure_rolls_back_all_files(tmp_path, monkeypatch):
    import empulse.restore as restore

    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    make_database(database, "current")
    key = tmp_path / ".empulse_secret"
    key.write_text("current-key")
    wal = Path(f"{database}-wal")
    shm = Path(f"{database}-shm")
    wal.write_bytes(b"original wal")
    shm.write_bytes(b"original shm")
    journal = Path(f"{database}-journal")
    journal.write_bytes(b"original journal")
    originals = {path: path.read_bytes() for path in (database, key, wal, shm, journal)}
    replace = restore.os.replace

    def fail_key_once(source, target):
        if Path(source).name == ".empulse_secret":
            raise OSError("key write failed")
        return replace(source, target)

    monkeypatch.setattr(restore.os, "replace", fail_key_once)
    with pytest.raises(OSError, match="key write failed"):
        restore_backup(backup, database)

    assert {path: path.read_bytes() for path in originals} == originals
    assert not (tmp_path / ".empulse.db.restore-in-progress").exists()
    assert list(tmp_path.glob("empulse.db.before-restore-*"))


def test_failed_rollback_keeps_startup_guard(tmp_path, monkeypatch):
    import empulse.restore as restore

    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    make_database(database, "current")
    original = database.read_bytes()

    def fail_replace(*args):
        raise OSError("filesystem unavailable")

    monkeypatch.setattr(restore.os, "replace", fail_replace)
    with pytest.raises(RuntimeError, match="Restore and rollback failed"):
        restore_backup(backup, database)

    marker = tmp_path / ".empulse.db.restore-in-progress"
    recovery = json.loads(marker.read_text())
    assert (Path(recovery["rescue_directory"]) / database.name).read_bytes() == original
    with pytest.raises(RuntimeError, match="interrupted restore"):
        restore_backup(backup, database)


def test_cli_success_and_failure(tmp_path, capsys):
    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    assert main(["--db", str(database), str(backup)]) == 0
    assert "Previous files retained" in capsys.readouterr().out
    assert main(["--db", str(database), str(tmp_path / "missing")]) == 1
    assert "Restore failed" in capsys.readouterr().err


def test_cli_import_does_not_load_settings_or_create_key(tmp_path):
    script = """
import sys
import empulse.restore
assert 'empulse.config' not in sys.modules
assert 'empulse.app' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", script], check=True)


def test_cli_rejects_invalid_sqlite_with_matching_checksum(tmp_path, capsys):
    backup = make_backup(tmp_path / "backup")
    damaged = b"not a SQLite database"
    (backup / "database.sqlite3").write_bytes(damaged)
    manifest_path = backup / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["database_sha256"] = hashlib.sha256(damaged).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    database = tmp_path / "empulse.db"
    assert main(["--db", str(database), str(backup)]) == 1
    assert "Restore failed" in capsys.readouterr().err
    assert not database.exists()


def test_restore_rescues_and_removes_old_rollback_journal(tmp_path):
    backup = make_backup(tmp_path / "backup")
    database = tmp_path / "empulse.db"
    make_database(database, "current")
    journal = Path(f"{database}-journal")
    journal.write_bytes(b"old rollback journal")

    rescue = restore_backup(backup, database)

    assert not journal.exists()
    assert (rescue / journal.name).read_bytes() == b"old rollback journal"
    assert read_title(database) == "before update"


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_restore_rejects_backup_with_sidecar(tmp_path, suffix):
    backup = make_backup(tmp_path / "backup")
    (backup / f"database.sqlite3{suffix}").write_bytes(b"unexpected SQLite sidecar")
    database = tmp_path / "empulse.db"
    make_database(database, "current")
    original = database.read_bytes()

    with pytest.raises((ValueError, RuntimeError)):
        restore_backup(backup, database)

    assert database.read_bytes() == original
    assert not list(tmp_path.glob("empulse.db.before-restore-*"))

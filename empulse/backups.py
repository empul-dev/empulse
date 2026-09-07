"""Verified SQLite snapshots for release upgrades and offline recovery."""

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

logger = logging.getLogger("empulse.backups")


async def run_io(function: Callable[..., Any], *args: Any) -> Any:
    """Finish file operations before cancellation can release the database lock."""
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    cancellation = None
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError as exc:
            if task.cancelled():
                raise
            cancellation = exc
        except BaseException:
            if cancellation is not None:
                raise cancellation
            raise
    if cancellation is not None:
        raise cancellation
    return result


@contextmanager
def database_lock(db_path: Path) -> Iterator[None]:
    """Keep cooperating app and restore processes from using the DB together."""
    if str(db_path) == ":memory:":
        yield
        return
    db_path = db_path.resolve()
    lock_path = db_path.with_name(f".{db_path.name}.lock")
    with lock_path.open("a+b") as lock:
        os.chmod(lock_path, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                "Database is in use; stop Empulse before continuing"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def backup_root(db_path: Path) -> Path:
    return db_path.parent / "backups" / db_path.name


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _logical_hash(db: sqlite3.Connection) -> str:
    # Ignore volatile SQLite header/WAL counters when comparing failed retries.
    digest = hashlib.sha256()
    for statement in db.iterdump():
        digest.update(statement.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _read_connection(path: Path, *, immutable: bool = False) -> sqlite3.Connection:
    query = "?mode=ro&immutable=1" if immutable else "?mode=ro"
    return sqlite3.connect(path.resolve().as_uri() + query, uri=True, timeout=5)


def _check_integrity(db: sqlite3.Connection) -> None:
    if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        raise RuntimeError("Database integrity check failed")


def read_release(db_path: Path) -> str | None:
    """Read the release marker without creating or changing the database."""
    db = _read_connection(db_path)
    try:
        table = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_metadata'"
        ).fetchone()
        if table is None:
            return None
        row = db.execute(
            "SELECT value FROM app_metadata WHERE key = 'release'"
        ).fetchone()
        return row[0] if row else None
    finally:
        db.close()


def validate_backup(backup_dir: Path) -> dict:
    """Verify a complete backup before reuse or restoration."""
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    if not isinstance(manifest, dict) or manifest.get("format") != 1:
        raise ValueError("Unsupported backup format")
    if manifest.get("secret_source") not in {"file", "external"}:
        raise ValueError("Invalid backup key metadata")
    snapshot = backup_dir / "database.sqlite3"
    if snapshot.is_symlink() or file_hash(snapshot) != manifest.get("database_sha256"):
        raise ValueError("Backup database checksum mismatch")
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(snapshot) + suffix).exists():
            raise ValueError("Backup contains unexpected SQLite sidecar files")
    db = _read_connection(snapshot, immutable=True)
    try:
        _check_integrity(db)
    finally:
        db.close()
    if manifest["secret_source"] == "file":
        secret = backup_dir / ".empulse_secret"
        if secret.is_symlink() or file_hash(secret) != manifest.get("secret_sha256"):
            raise ValueError("Backup key checksum mismatch")
    return manifest


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def prepare_backup(
    db_path: Path,
    source_version: str | None,
    target_version: str,
    secret_key: str,
) -> Path:
    """Create or reuse a verified pre-upgrade snapshot. Never prune on failure."""
    root = backup_root(db_path)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    # Interrupted attempts leave only staging files; the app holds the DB lock.
    for abandoned in root.glob(".tmp-*"):
        if abandoned.is_dir() and not abandoned.is_symlink():
            shutil.rmtree(abandoned)
    staging = Path(tempfile.mkdtemp(prefix=".tmp-", dir=root))
    try:
        snapshot = staging / "database.sqlite3"
        source = _read_connection(db_path)
        destination = sqlite3.connect(snapshot)
        try:
            source.backup(destination)
            destination.execute("PRAGMA journal_mode=DELETE")
            _check_integrity(destination)
            source_hash = _logical_hash(destination)
        finally:
            destination.close()
            source.close()
        os.chmod(snapshot, 0o600)

        secret_path = db_path.parent / ".empulse_secret"
        secret_source = "external"
        secret_hash = None
        if secret_path.is_file() and secret_path.read_text().strip() == secret_key:
            shutil.copyfile(secret_path, staging / ".empulse_secret")
            os.chmod(staging / ".empulse_secret", 0o600)
            secret_source = "file"
            secret_hash = file_hash(staging / ".empulse_secret")

        # Reuse only an intact snapshot of the same data and file-based key.
        # A previous app may have written new data between failed upgrades.
        for previous in sorted(root.glob("update-*")):
            try:
                metadata = json.loads((previous / "manifest.json").read_text())
                if not isinstance(metadata, dict):
                    continue
                if (
                    metadata.get("target_version") == target_version
                    and metadata.get("source_hash") == source_hash
                    and metadata.get("secret_source") == secret_source
                    and metadata.get("secret_sha256") == secret_hash
                ):
                    validate_backup(previous)
                    logger.info("Reusing verified upgrade backup at %s", previous)
                    return previous
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                # A corrupt backup does not replace today's verified snapshot.
                continue

        metadata = {
            "format": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_version": source_version or "legacy",
            "target_version": target_version,
            "source_hash": source_hash,
            "database_sha256": file_hash(snapshot),
            "secret_source": secret_source,
            "secret_sha256": secret_hash,
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(metadata, indent=2) + "\n")
        os.chmod(manifest_path, 0o600)
        validate_backup(staging)
        for file in staging.iterdir():
            with file.open("rb") as stream:
                os.fsync(stream.fileno())
        _sync_directory(staging)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        final = root / f"update-{stamp}-{uuid.uuid4().hex[:8]}"
        os.replace(staging, final)
        _sync_directory(root)
        logger.info("Verified upgrade backup saved at %s", final)
        return final
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def prune_backups(db_path: Path, retention: int) -> None:
    """Prune only after startup commits, keeping the newest verified snapshots."""
    root = backup_root(db_path)
    candidates = sorted(root.glob("update-*"), reverse=True)
    if len(candidates) <= retention:
        return
    valid = []
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            validate_backup(candidate)
        except (OSError, ValueError, RuntimeError, sqlite3.Error):
            logger.warning("Leaving invalid backup untouched: %s", candidate)
            continue
        valid.append(candidate)
    for expired in valid[max(1, retention) :]:
        shutil.rmtree(expired)
        logger.info("Removed old upgrade backup %s", expired)

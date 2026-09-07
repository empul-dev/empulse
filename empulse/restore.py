"""Restore an update backup while Empulse is stopped.

Run ``python -m empulse.restore --db /app/data/empulse.db BACKUP_DIRECTORY``.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

from empulse.backups import database_lock, validate_backup


def _copy(source: Path, target: Path) -> None:
    with source.open("rb") as reader, target.open("xb") as writer:
        os.chmod(target, 0o600)
        shutil.copyfileobj(reader, writer)
        writer.flush()
        os.fsync(writer.fileno())


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def restore_backup(backup_dir: Path, db_path: Path) -> Path:
    """Restore a verified backup and retain the previous files for recovery."""
    backup_dir = backup_dir.resolve()
    db_path = db_path.absolute()
    if db_path.is_symlink():
        raise ValueError("The database destination must not be a symbolic link")
    db_path = db_path.resolve()
    if not db_path.parent.is_dir():
        raise ValueError("The database destination directory does not exist")
    if db_path.is_relative_to(backup_dir):
        raise ValueError("The database destination must be outside the source backup")
    marker = db_path.with_name(f".{db_path.name}.restore-in-progress")
    with database_lock(db_path):
        if marker.exists():
            raise RuntimeError(
                f"An interrupted restore needs recovery first. See {marker}"
            )
        manifest = validate_backup(backup_dir)
        sidecars = [
            Path(f"{db_path}{suffix}") for suffix in ("-wal", "-shm", "-journal")
        ]
        targets = [db_path, *sidecars]
        restore_key = manifest.get("secret_source") == "file"
        if restore_key:
            targets.append(db_path.parent / ".empulse_secret")
        for target in targets:
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise ValueError(f"Restore destination is not a regular file: {target}")
        with tempfile.TemporaryDirectory(
            prefix=f".{db_path.name}.restore-stage-", dir=db_path.parent
        ) as stage_name:
            stage = Path(stage_name)
            # Validate our own copies too, before changing any existing files.
            for filename in ("database.sqlite3", "manifest.json"):
                _copy(backup_dir / filename, stage / filename)
            if restore_key:
                _copy(backup_dir / ".empulse_secret", stage / ".empulse_secret")
            validate_backup(stage)
            rescue = Path(
                tempfile.mkdtemp(
                    prefix=f"{db_path.name}.before-restore-", dir=db_path.parent
                )
            )
            existing = [target for target in targets if target.exists()]
            try:
                for target in existing:
                    _copy(target, rescue / target.name)
                recovery = {
                    "database": str(db_path),
                    "rescue_directory": str(rescue),
                    "original_files": [target.name for target in existing],
                    "managed_files": [target.name for target in targets],
                }
                with (rescue / "recovery.json").open("x") as stream:
                    json.dump(recovery, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                _sync_directory(rescue)
                with marker.open("x") as stream:
                    os.chmod(marker, 0o600)
                    json.dump(recovery, stream, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                _sync_directory(db_path.parent)
            except BaseException:
                # Existing files have not been touched.
                marker.unlink(missing_ok=True)
                shutil.rmtree(rescue)
                raise
            try:
                for target in sidecars:
                    target.unlink(missing_ok=True)
                os.replace(stage / "database.sqlite3", db_path)
                if restore_key:
                    os.replace(stage / ".empulse_secret", targets[-1])
                _sync_directory(db_path.parent)
            except BaseException:
                try:
                    for target in targets:
                        if target in existing:
                            rollback = stage / f"rollback-{target.name}"
                            _copy(rescue / target.name, rollback)
                            os.replace(rollback, target)
                        else:
                            target.unlink(missing_ok=True)
                    _sync_directory(db_path.parent)
                    marker.unlink()
                    _sync_directory(db_path.parent)
                except BaseException as recovery_error:
                    raise RuntimeError(
                        f"Restore and rollback failed. Keep Empulse stopped. "
                        f"Recover original files using {rescue / 'recovery.json'}. "
                        f"The startup guard is {marker}."
                    ) from recovery_error
                raise
            marker.unlink()
            _sync_directory(db_path.parent)
            return rescue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_directory", type=Path)
    parser.add_argument(
        "--db", required=True, type=Path, help="Stopped Empulse database"
    )
    args = parser.parse_args(argv)
    try:
        rescue = restore_backup(args.backup_directory, args.db)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"Restore failed: {error}", file=sys.stderr)
        return 1
    print(f"Restored {args.db}. Previous files retained in {rescue}.")
    print(
        "Start the matching previous Empulse version. Preserve any external SECRET_KEY."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

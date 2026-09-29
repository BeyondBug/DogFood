"""Restore a complete local portal snapshot while the web service is stopped.

Usage: python -m src.restore /path/to/backup.sqlite3
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .db import database_path


def restore_backup(source: Path, destination: Path | None = None) -> Path | None:
    """Validate a snapshot, preserve the current DB, then atomically replace it."""
    target = destination or database_path()
    if source.resolve() == target.resolve():
        raise ValueError("Backup and active database must be different files")
    if not source.is_file() or source.is_symlink():
        raise ValueError("Backup must be a regular file")
    with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("Backup has broken foreign keys")
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if not 1 <= version <= 10:
            raise ValueError(f"Unsupported database schema version: {version}")
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"users", "events", "projects", "scorecards"}.issubset(tables):
            raise ValueError("Backup is not a BeyondBug portal database")
    target.parent.mkdir(parents=True, exist_ok=True)
    if Path(str(target) + "-wal").exists() or Path(str(target) + "-shm").exists():
        raise RuntimeError("Stop the portal and checkpoint/remove its WAL files before restoring")
    safety = None
    if target.exists():
        safety = target.with_name(target.stem + ".before-restore-" +
                                  datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".sqlite3")
        with closing(sqlite3.connect(target)) as current, closing(sqlite3.connect(safety)) as previous:
            current.backup(previous)
        safety.chmod(0o600)
    descriptor, temporary = tempfile.mkstemp(prefix="portal-restore-", suffix=".sqlite3", dir=target.parent)
    os.close(descriptor)
    try:
        with closing(sqlite3.connect(f"file:{source}?mode=ro", uri=True)) as original, closing(sqlite3.connect(temporary)) as restored:
            original.backup(restored)
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return safety


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a BeyondBug SQLite backup while the portal is stopped")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    safety = restore_backup(args.source)
    print(f"Restored {args.source} to {database_path()}")
    if safety:
        print(f"Previous database preserved at {safety}")


if __name__ == "__main__":
    main()

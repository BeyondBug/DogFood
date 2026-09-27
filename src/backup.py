"""Create a consistent SQLite backup while the portal is running.

Usage: python -m src.backup /data/portal-backup.sqlite3
"""

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from .db import database_path


def write_backup(destination: Path) -> None:
    """Write and verify a consistent SQLite snapshot outside the web assets."""
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with closing(sqlite3.connect(database_path())) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            if target.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                raise RuntimeError("Backup integrity check failed")
        destination.chmod(0o600)
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the BeyondBug SQLite database")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("destination already exists")
    write_backup(args.destination)
    print(f"Backup written to {args.destination}")


if __name__ == "__main__":
    main()

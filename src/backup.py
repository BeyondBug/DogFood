"""Create a consistent SQLite backup while the portal is running.

Usage: python -m src.backup /data/portal-backup.sqlite3
"""

import argparse
import sqlite3
from pathlib import Path

from .db import database_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up the BeyondBug SQLite database")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("destination already exists")
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path()) as source, sqlite3.connect(args.destination) as destination:
        source.backup(destination)
    print(f"Backup written to {args.destination}")


if __name__ == "__main__":
    main()

"""A full portal snapshot can be imported without losing the prior database."""

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.db import connect, initialize
from src.restore import restore_backup


class RestoreTests(unittest.TestCase):
    def test_restore_keeps_safety_copy_and_rejects_unrelated_database(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "portal.sqlite3"
            source = root / "snapshot.sqlite3"
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(target)}):
                initialize()
                with closing(connect()) as db:
                    db.execute("INSERT INTO users(id,email,name,created_at) VALUES('original','old@example.org','Old','2026-09-29T00:00:00Z')")
                    db.commit()
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                with closing(sqlite3.connect(target)) as db, closing(sqlite3.connect(source)) as snapshot:
                    db.backup(snapshot)
                with closing(connect()) as db:
                    db.execute("INSERT INTO users(id,email,name,created_at) VALUES('new','new@example.org','New','2026-09-29T00:00:00Z')")
                    db.commit()
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                Path(str(target) + "-wal").unlink(missing_ok=True)
                Path(str(target) + "-shm").unlink(missing_ok=True)
                safety = restore_backup(source)
                with closing(connect()) as db:
                    users = {row[0] for row in db.execute("SELECT id FROM users")}
                self.assertEqual(users, {"original"})
                self.assertIsNotNone(safety)
                with closing(sqlite3.connect(safety)) as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) FROM users").fetchone()[0], 2)
                unrelated = root / "unrelated.sqlite3"
                with closing(sqlite3.connect(unrelated)) as db:
                    db.execute("CREATE TABLE unrelated(id INTEGER)")
                    db.commit()
                with self.assertRaises(ValueError):
                    restore_backup(unrelated)


if __name__ == "__main__":
    unittest.main()

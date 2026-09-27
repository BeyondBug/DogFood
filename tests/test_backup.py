"""Check that operator backups are usable and never overwrite an existing copy."""

import os
import sqlite3
import stat
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.backup import write_backup


class BackupTests(unittest.TestCase):
    def test_live_snapshot_preserves_data_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite3"
            destination = Path(directory) / "backups" / "snapshot.sqlite3"
            with closing(sqlite3.connect(source)) as db:
                db.execute("CREATE TABLE project (title TEXT NOT NULL)")
                db.execute("INSERT INTO project VALUES ('A real submission')")
                db.commit()
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(source)}):
                write_backup(destination)
                with closing(sqlite3.connect(destination)) as db:
                    self.assertEqual(db.execute("PRAGMA quick_check(1)").fetchone()[0], "ok")
                    self.assertEqual(db.execute("SELECT title FROM project").fetchone()[0],
                                     "A real submission")
                self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
                with self.assertRaises(FileExistsError):
                    write_backup(destination)


if __name__ == "__main__":
    unittest.main()

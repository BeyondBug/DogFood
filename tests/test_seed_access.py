"""The one-command demo is operable and demo access is revoked when disabled."""

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from src.db import connect, initialize
from src.seed import DEMO_ADMIN_ID, DEMO_TOKENS, seed, token_hash


class SeedAccessTests(unittest.TestCase):
    def test_demo_administrator_is_separate_and_revoked_when_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(directory) / "portal.sqlite3"),
                                      "DOGFOOD_FIXTURES_PATH": str(Path(__file__).resolve().parents[1] / "fixtures.json"),
                                      "DOGFOOD_DEMO_MODE": "1"}):
                initialize()
                seed()
                with closing(connect()) as db:
                    self.assertEqual(db.execute("SELECT is_admin FROM users WHERE id=?", (DEMO_ADMIN_ID,)).fetchone()[0], 1)
                    self.assertEqual(db.execute("SELECT is_admin FROM users WHERE id='org_demo'").fetchone()[0], 0)
                    self.assertIsNotNone(db.execute("SELECT 1 FROM sessions WHERE token_hash=?",
                                                    (token_hash(DEMO_TOKENS["organizer"]),)).fetchone())
                with patch.dict(os.environ, {"DOGFOOD_DEMO_MODE": "0"}):
                    seed()
                    with closing(connect()) as db:
                        admin = db.execute("SELECT is_admin,password_hash FROM users WHERE id=?",
                                           (DEMO_ADMIN_ID,)).fetchone()
                        self.assertEqual(admin["is_admin"], 0)
                        self.assertIsNone(admin["password_hash"])
                        self.assertIsNone(db.execute("SELECT 1 FROM sessions WHERE token_hash=?",
                                                     (token_hash(DEMO_TOKENS["organizer"]),)).fetchone())


if __name__ == "__main__":
    unittest.main()

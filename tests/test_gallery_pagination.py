"""A larger event must expose every submitted project through the gallery."""

import os
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

from src.db import connect, initialize
from src.main import gallery


class GalleryPaginationTests(unittest.TestCase):
    def test_project_after_first_page_remains_browsable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"DOGFOOD_DB_PATH": str(Path(temp_dir) / "portal.sqlite3")}):
                initialize()
                with closing(connect()) as db:
                    db.execute(
                        "INSERT INTO events(id,name,description,submissions_close,created_at) VALUES(?,?,?,?,?)",
                        ("evt_many", "Many projects", "", "2030-01-01T00:00:00Z", "2026-09-27T00:00:00Z"),
                    )
                    db.execute("INSERT INTO tracks(id,event_id,name) VALUES(?,?,?)", ("trk_many", "evt_many", "Open"))
                    for index in range(49):
                        team_id = f"tm_{index:02d}"
                        project_id = f"prj_{index:02d}"
                        db.execute(
                            "INSERT INTO teams(id,event_id,name,created_at) VALUES(?,?,?,?)",
                            (team_id, "evt_many", f"Team {index:02d}", "2026-09-27T00:00:00Z"),
                        )
                        db.execute(
                            "INSERT INTO projects(id,event_id,team_id,track_id,title,status,submitted_at,updated_at)"
                            " VALUES(?,?,?,?,?,?,?,?)",
                            (project_id, "evt_many", team_id, "trk_many", f"Project {index:02d}", "submitted",
                             f"2026-09-27T00:{index:02d}:00Z", f"2026-09-27T00:{index:02d}:00Z"),
                        )
                    db.commit()
                request = Request({"type": "http", "method": "GET", "path": "/projects", "headers": []})
                first = gallery(request, event="evt_many", page=1).body.decode()
                second = gallery(request, event="evt_many", page=2).body.decode()
                self.assertIn("Showing 1–48 of 49 projects", first)
                self.assertIn("Showing 49–49 of 49 projects", second)
                self.assertNotIn("Project 00</a>", first)
                self.assertIn("Project 00</a>", second)
                self.assertIn("page=2", first)


if __name__ == "__main__":
    unittest.main()

"""Keep the published API artifact synchronized with the running application."""

import json
import unittest
from pathlib import Path

from src.main import app


class OpenApiArtifactTests(unittest.TestCase):
    def test_committed_spec_matches_application(self):
        artifact = Path(__file__).resolve().parents[1] / "openapi.json"
        self.assertEqual(json.loads(artifact.read_text(encoding="utf-8")), app.openapi())


if __name__ == "__main__":
    unittest.main()

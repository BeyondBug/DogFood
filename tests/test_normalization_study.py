"""The shipped calibration must beat raw means on the fixture's real review graph."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from normalization_study import run  # noqa: E402


class NormalizationStudyTests(unittest.TestCase):
    def test_shipped_penalty_recovers_planted_order_better_than_raw_means(self):
        table = run(trials=40, seed=11, penalties=(0.01, 3.0))
        self.assertLess(table[3.0]["mae"], table["raw"]["mae"])
        self.assertGreater(table[3.0]["tau"], table["raw"]["tau"])
        # Without shrinkage, one-review judges are over-corrected.
        self.assertGreater(table[0.01]["mae"], table[3.0]["mae"])


if __name__ == "__main__":
    unittest.main()

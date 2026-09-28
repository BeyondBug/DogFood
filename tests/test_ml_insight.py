"""Guard the portable inference result against model-export drift."""

import math
import unittest

from src.ml_insight import _artifact, decision_score


class PortableModelTests(unittest.TestCase):
    def test_exported_model_matches_reference_decision(self):
        # Captured from the teammate's joblib artifact with scikit-learn.
        features = {
            "overall_score": 4, "peer_delta": 1.1, "peer_abs_delta": 1.1,
            "project_z_score": 1.3, "judge_z_score": 2,
            "peer_x_judge": 2.2, "unexplained_peer_delta": .8,
            "has_judge_history": 1, "judge_mean_before": 3.4,
            "judge_std_before": .6, "project_peer_std": .5,
            "project_peer_mean": 2.9, "category_spread": 1.5,
            "rubric_completion_ratio": 1,
        }
        self.assertEqual(_artifact()["config"]["model_version"], "judge-anomaly-iforest-v2")
        self.assertEqual(len(_artifact()["trees"]), 300)
        self.assertTrue(math.isclose(decision_score(features), 0.10543315824217725, abs_tol=1e-10))


if __name__ == "__main__":
    unittest.main()

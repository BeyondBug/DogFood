"""Edge cases for judge calibration, independent of HTTP and Docker."""

import math
import unittest

from src.scoring import Review, normalize, review_attention


class ScoringTests(unittest.TestCase):
    def test_constant_judge_is_finite_and_offsets_shrink(self):
        reviews = [
            Review("strict", "a", 2), Review("strict", "b", 2),
            Review("generous", "a", 4), Review("generous", "b", 4),
            Review("constant", "a", 3), Review("constant", "b", 3),
        ]
        result = normalize(reviews)
        self.assertTrue(all(math.isfinite(value) for value in result["offsets"].values()))
        self.assertLess(result["offsets"]["strict"], 0)
        self.assertGreater(result["offsets"]["generous"], 0)
        self.assertEqual(len(result["components"]), 1)

    def test_sparse_judge_has_small_offset(self):
        reviews = [
            Review("steady", "a", 3), Review("steady", "b", 3),
            Review("sparse", "a", 5), Review("strict", "b", 1),
        ]
        result = normalize(reviews, penalty=3)
        self.assertLess(abs(result["offsets"]["sparse"]), 1)
        self.assertLess(abs(result["offsets"]["strict"]), 1)

    def test_disconnected_overlap_is_reported(self):
        result = normalize([Review("one", "a", 4), Review("two", "b", 2)])
        self.assertEqual(len(result["components"]), 2)
        self.assertEqual(result["adjusted"]["a"], 4)
        self.assertEqual(result["adjusted"]["b"], 2)

    def test_attention_uses_only_agreeing_peers(self):
        reviews = [Review("one", "p", 4, "s1"), Review("two", "p", 4, "s2"),
                   Review("three", "p", 1, "s3")]
        result = review_attention(reviews, {})
        self.assertEqual([item["scorecard_id"] for item in result["items"]], ["s3"])
        self.assertEqual(result["items"][0]["peer_count"], 2)
        self.assertEqual(result["items"][0]["peer_median"], 4)

    def test_attention_requires_evidence_and_uses_calibration(self):
        sparse = [Review("one", "p", 5), Review("two", "p", 1)]
        self.assertEqual(review_attention(sparse, {})["items"], [])
        self.assertEqual(review_attention(sparse, {})["limited_evidence_projects"], 1)
        reviews = [Review("strict", "p", 2), Review("two", "p", 4), Review("three", "p", 4)]
        self.assertEqual(review_attention(reviews, {})["items"][0]["judge"], "strict")
        self.assertEqual(review_attention(reviews, {"strict": -1.0})["items"], [])


if __name__ == "__main__":
    unittest.main()

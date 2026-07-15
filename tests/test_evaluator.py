"""Unit tests for src/evaluator.py — run from the repo root:

    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from evaluator import color_histogram, evaluate_prediction  # noqa: E402

EXPECTED = [[1, 2], [3, 4]]


class TestEvaluatePrediction(unittest.TestCase):
    def test_exact_match(self):
        result = evaluate_prediction([[1, 2], [3, 4]], EXPECTED)
        self.assertTrue(result.is_exact_match)
        self.assertTrue(result.same_shape)
        self.assertEqual(result.cell_accuracy, 1.0)
        self.assertEqual(result.n_diff_cells, 0)

    def test_same_shape_partial_match(self):
        result = evaluate_prediction([[1, 2], [3, 9]], EXPECTED)
        self.assertFalse(result.is_exact_match)
        self.assertTrue(result.same_shape)
        self.assertEqual(result.cell_accuracy, 0.75)
        self.assertEqual(result.n_diff_cells, 1)

    def test_shape_mismatch_uses_overlap_and_max_denominator(self):
        # 2x3 vs 2x2: overlap (2x2) matches all 4; denominator max(6, 4) = 6.
        result = evaluate_prediction([[1, 2, 0], [3, 4, 0]], EXPECTED)
        self.assertFalse(result.is_exact_match)
        self.assertFalse(result.same_shape)
        self.assertAlmostEqual(result.cell_accuracy, 4 / 6)
        self.assertEqual(result.n_diff_cells, 2)

    def test_smaller_prediction_penalized_for_missing_area(self):
        # 1x1 vs 2x2: overlap matches 1; denominator max(1, 4) = 4.
        result = evaluate_prediction([[1]], EXPECTED)
        self.assertAlmostEqual(result.cell_accuracy, 0.25)
        self.assertEqual(result.n_diff_cells, 3)

    def test_none_inputs_yield_all_none_metrics(self):
        for predicted, expected in ((None, EXPECTED), ([[1]], None), (None, None)):
            with self.subTest(predicted=predicted, expected=expected):
                result = evaluate_prediction(predicted, expected)
                self.assertIsNone(result.is_exact_match)
                self.assertIsNone(result.same_shape)
                self.assertIsNone(result.cell_accuracy)
                self.assertIsNone(result.n_diff_cells)


class TestColorHistogram(unittest.TestCase):
    def test_counts_by_value(self):
        self.assertEqual(color_histogram([[0, 0], [1, 2]]), {0: 2, 1: 1, 2: 1})

    def test_position_independent(self):
        self.assertEqual(
            color_histogram([[1, 2], [3, 4]]),
            color_histogram([[4, 3], [2, 1]]),
        )


if __name__ == "__main__":
    unittest.main()

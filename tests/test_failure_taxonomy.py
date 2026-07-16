"""
Unit tests for src/failure_taxonomy.py — run from the repo root:

    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from evaluator import evaluate_prediction  # noqa: E402
from failure_taxonomy import (  # noqa: E402
    FAILURE_MODES,
    LEGACY_MODE_RENAMES,
    classify_failure,
)
from grid_parser import (  # noqa: E402
    PARSE_EMPTY,
    PARSE_INVALID_GRID,
    PARSE_NO_JSON,
    PARSE_OK,
)

EXPECTED = [[1, 2], [3, 4]]


def classify(solver_status="ok", parse_status=PARSE_OK, predicted=None,
             expected=EXPECTED, solver_error=None, parse_error=None):
    """Small harness: evaluation is derived exactly as the runner does it."""
    evaluation = evaluate_prediction(predicted, expected)
    return classify_failure(
        solver_status=solver_status,
        parse_status=parse_status,
        evaluation=evaluation,
        predicted_grid=predicted,
        expected_grid=expected,
        solver_error=solver_error,
        parse_error=parse_error,
    )


class TestRuleOrder(unittest.TestCase):
    def test_execution_error_wins_over_everything(self):
        mode, detail = classify(solver_status="error",
                                solver_error="HTTP 500")
        self.assertEqual(mode, "execution_error")
        self.assertEqual(detail, "HTTP 500")

    def test_empty_response(self):
        mode, _ = classify(parse_status=PARSE_EMPTY)
        self.assertEqual(mode, "empty_response")

    def test_parse_error_for_both_parse_failures(self):
        for status in (PARSE_NO_JSON, PARSE_INVALID_GRID):
            with self.subTest(status=status):
                mode, detail = classify(parse_status=status,
                                        parse_error="bad json")
                self.assertEqual(mode, "parse_error")
                self.assertEqual(detail, "bad json")

    def test_no_ground_truth_is_not_classifiable(self):
        mode, detail = classify(predicted=[[1, 2], [3, 4]], expected=None)
        self.assertIsNone(mode)
        self.assertIn("no ground truth", detail)


class TestOutcomeModes(unittest.TestCase):
    def test_exact_match(self):
        mode, detail = classify(predicted=[[1, 2], [3, 4]])
        self.assertEqual(mode, "exact_match")
        self.assertIsNone(detail)

    def test_shape_error(self):
        mode, detail = classify(predicted=[[1]])
        self.assertEqual(mode, "shape_error")
        self.assertIn("predicted 1x1, expected 2x2", detail)

    def test_spatial_error_same_histogram(self):
        mode, detail = classify(predicted=[[2, 1], [4, 3]])
        self.assertEqual(mode, "spatial_error")
        self.assertIn("misplaced", detail)

    def test_symbol_error_different_histogram(self):
        mode, detail = classify(predicted=[[1, 2], [3, 9]])
        self.assertEqual(mode, "symbol_error")
        self.assertIn("histogram differs", detail)


class TestVocabulary(unittest.TestCase):
    def test_modes_are_the_frozen_v2_set(self):
        self.assertEqual(FAILURE_MODES, [
            "exact_match", "execution_error", "empty_response", "parse_error",
            "shape_error", "spatial_error", "symbol_error", "unknown_error",
        ])

    def test_legacy_api_error_rename(self):
        self.assertEqual(LEGACY_MODE_RENAMES, {"api_error": "execution_error"})

    def test_all_classified_modes_are_in_vocabulary(self):
        cases = [
            classify(solver_status="error"),
            classify(parse_status=PARSE_EMPTY),
            classify(parse_status=PARSE_NO_JSON),
            classify(predicted=[[1, 2], [3, 4]]),
            classify(predicted=[[1]]),
            classify(predicted=[[2, 1], [4, 3]]),
            classify(predicted=[[1, 2], [3, 9]]),
        ]
        for mode, _ in cases:
            self.assertIn(mode, FAILURE_MODES)


if __name__ == "__main__":
    unittest.main()

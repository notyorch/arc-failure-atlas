"""Unit tests for src/kaggle_protocol.py — Kaggle-grader parity checks.

    python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from kaggle_protocol import (  # noqa: E402
    coverage_summary,
    format_coverage_report,
    kaggle_score_from_rows,
    kaggle_strict_issues,
    test_counts_from_items,
    test_counts_from_tasks_df,
)
from submission_io import load_submission_file  # noqa: E402


def _submission(tmp: str, payload: dict):
    path = Path(tmp) / "sub.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return load_submission_file(path)


def _codes(issues, severity=None):
    return [
        i.code for i in issues
        if severity is None or i.severity == severity
    ]


class TestKaggleStrictIssues(unittest.TestCase):
    def test_complete_submission_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = _submission(tmp, {
                "t1": [{"attempt_1": [[1]], "attempt_2": [[2]]}],
                "t2": [
                    {"attempt_1": [[3]], "attempt_2": [[4]]},
                    {"attempt_1": [[5]], "attempt_2": [[6]]},
                ],
            })
            issues = kaggle_strict_issues(sub, {"t1": 1, "t2": 2})
            self.assertEqual(issues, [])

    def test_missing_task_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = _submission(tmp, {
                "t1": [{"attempt_1": [[1]], "attempt_2": [[2]]}],
            })
            issues = kaggle_strict_issues(sub, {"t1": 1, "t2": 1})
            self.assertEqual(_codes(issues, "error"), ["missing_task"])
            self.assertEqual(issues[0].task_id, "t2")

    def test_missing_test_output_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = _submission(tmp, {
                "t1": [{"attempt_1": [[1]], "attempt_2": [[2]]}],
            })
            issues = kaggle_strict_issues(sub, {"t1": 2})
            self.assertEqual(_codes(issues, "error"), ["missing_test_output"])
            self.assertEqual(issues[0].test_index, 2)

    def test_missing_attempt_2_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = _submission(tmp, {
                "t1": [{"attempt_1": [[1]]}],
            })
            issues = kaggle_strict_issues(sub, {"t1": 1})
            self.assertEqual(_codes(issues, "error"), ["missing_attempt"])
            self.assertIn("attempt_2", issues[0].message)

    def test_extra_task_and_attempt_are_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = _submission(tmp, {
                "t1": [{"attempt_1": [[1]], "attempt_2": [[2]],
                        "attempt_3": [[3]]}],
                "ghost": [{"attempt_1": [[7]], "attempt_2": [[8]]}],
            })
            issues = kaggle_strict_issues(sub, {"t1": 1})
            self.assertEqual(_codes(issues, "error"), [])
            self.assertCountEqual(
                _codes(issues, "warning"), ["extra_attempt", "extra_task"])


class TestCoverage(unittest.TestCase):
    def test_summary_counts_tasks_and_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = _submission(tmp, {
                "t1": [{"attempt_1": [[1]], "attempt_2": [[2]]}],
            })
            cov = coverage_summary(sub, {"t1": 2, "t2": 1})
            self.assertEqual(cov["n_expected_tasks"], 2)
            self.assertEqual(cov["n_covered_tasks"], 1)
            self.assertEqual(cov["missing_task_ids"], ["t2"])
            self.assertEqual(cov["n_expected_items"], 3)
            self.assertEqual(cov["n_covered_items"], 1)
            report = format_coverage_report(cov)
            self.assertIn("1 / 2 task(s)", report)
            self.assertIn("t2", report)


class TestTestCounts(unittest.TestCase):
    def test_from_items(self):
        items = [
            {"task_id": "a", "test_example_id": 1},
            {"task_id": "a", "test_example_id": 2},
            {"task_id": "b", "test_example_id": 1},
        ]
        self.assertEqual(test_counts_from_items(items), {"a": 2, "b": 1})

    def test_from_tasks_df(self):
        import pandas as pd
        df = pd.DataFrame([
            {"task_id": "a", "split": "test", "grid_role": "input",
             "example_id": 1},
            {"task_id": "a", "split": "test", "grid_role": "output",
             "example_id": 1},
            {"task_id": "a", "split": "test", "grid_role": "input",
             "example_id": 2},
            {"task_id": "a", "split": "train", "grid_role": "input",
             "example_id": 1},
            {"task_id": "b", "split": "test", "grid_role": "input",
             "example_id": 1},
        ])
        self.assertEqual(test_counts_from_tasks_df(df), {"a": 2, "b": 1})


class TestKaggleScore(unittest.TestCase):
    def test_partial_task_gets_fractional_credit(self):
        import pandas as pd
        # t1: 1 of 2 test outputs solved → 0.5; t2: solved → 1.0; mean 0.75.
        df = pd.DataFrame([
            {"task_id": "t1", "test_example_id": 1, "attempt": 1,
             "is_exact_match": True},
            {"task_id": "t1", "test_example_id": 1, "attempt": 2,
             "is_exact_match": False},
            {"task_id": "t1", "test_example_id": 2, "attempt": 1,
             "is_exact_match": False},
            {"task_id": "t1", "test_example_id": 2, "attempt": 2,
             "is_exact_match": False},
            {"task_id": "t2", "test_example_id": 1, "attempt": 2,
             "is_exact_match": True},
        ])
        result = kaggle_score_from_rows(df)
        self.assertAlmostEqual(result["kaggle_score"], 0.75)
        self.assertEqual(result["n_tasks"], 2)
        self.assertEqual(result["n_items"], 3)

    def test_attempt_3_is_ignored(self):
        import pandas as pd
        df = pd.DataFrame([
            {"task_id": "t1", "test_example_id": 1, "attempt": 1,
             "is_exact_match": False},
            {"task_id": "t1", "test_example_id": 1, "attempt": 3,
             "is_exact_match": True},
        ])
        result = kaggle_score_from_rows(df)
        self.assertEqual(result["kaggle_score"], 0.0)

    def test_null_match_counts_as_unsolved(self):
        import pandas as pd
        df = pd.DataFrame([
            {"task_id": "t1", "test_example_id": 1, "attempt": 1,
             "is_exact_match": None},
        ])
        result = kaggle_score_from_rows(df)
        self.assertEqual(result["kaggle_score"], 0.0)

    def test_empty_rows(self):
        import pandas as pd
        self.assertIsNone(
            kaggle_score_from_rows(pd.DataFrame())["kaggle_score"])
        self.assertIsNone(kaggle_score_from_rows(None)["kaggle_score"])


if __name__ == "__main__":
    unittest.main()

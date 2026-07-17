"""Unit tests for src/presubmit.py — holdout seal + certificate metrics.

    python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from presubmit import (  # noqa: E402
    HoldoutError,
    create_holdout_split,
    load_holdout_split,
    mark_revealed,
    metrics_from_rows,
    render_certificate,
    seal_is_intact,
    score_rows_for_items,
    verdict_from_checks,
    write_holdout_split,
)

TASK_IDS = [f"task{i:02d}" for i in range(10)]


class TestHoldoutSplit(unittest.TestCase):
    def test_deterministic_for_same_seed(self):
        a = create_holdout_split(TASK_IDS, 0.3, seed=7)
        b = create_holdout_split(list(reversed(TASK_IDS)), 0.3, seed=7)
        self.assertEqual(a["holdout_task_ids"], b["holdout_task_ids"])
        self.assertEqual(a["seal_sha256"], b["seal_sha256"])

    def test_different_seed_different_split(self):
        a = create_holdout_split(TASK_IDS, 0.3, seed=1)
        b = create_holdout_split(TASK_IDS, 0.3, seed=2)
        self.assertNotEqual(a["holdout_task_ids"], b["holdout_task_ids"])

    def test_partition_is_complete_and_disjoint(self):
        split = create_holdout_split(TASK_IDS, 0.3, seed=7)
        dev = set(split["dev_task_ids"])
        holdout = set(split["holdout_task_ids"])
        self.assertEqual(dev | holdout, set(TASK_IDS))
        self.assertEqual(dev & holdout, set())
        self.assertEqual(split["n_holdout"], 3)

    def test_fraction_bounds(self):
        with self.assertRaises(HoldoutError):
            create_holdout_split(TASK_IDS, 0.0, seed=1)
        with self.assertRaises(HoldoutError):
            create_holdout_split(TASK_IDS, 1.0, seed=1)
        with self.assertRaises(HoldoutError):
            create_holdout_split(["only-one"], 0.3, seed=1)

    def test_seal_detects_tampering(self):
        split = create_holdout_split(TASK_IDS, 0.3, seed=7)
        self.assertTrue(seal_is_intact(split))
        split["holdout_task_ids"] = split["holdout_task_ids"][:-1]
        self.assertFalse(seal_is_intact(split))

    def test_write_refuses_overwrite_without_force(self):
        split = create_holdout_split(TASK_IDS, 0.3, seed=7)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "holdout.json"
            write_holdout_split(split, path)
            with self.assertRaises(HoldoutError):
                write_holdout_split(split, path)
            write_holdout_split(split, path, force=True)  # explicit override

    def test_load_and_reveal_once(self):
        split = create_holdout_split(TASK_IDS, 0.3, seed=7)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "holdout.json"
            write_holdout_split(split, path)
            loaded = load_holdout_split(path)
            self.assertIsNone(loaded["revealed_at"])
            revealed = mark_revealed(loaded, path)
            self.assertIsNotNone(revealed["revealed_at"])
            on_disk = load_holdout_split(path)
            self.assertEqual(on_disk["revealed_at"], revealed["revealed_at"])
            with self.assertRaises(HoldoutError):
                mark_revealed(on_disk, path)

    def test_load_rejects_wrong_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "holdout.json"
            path.write_text(json.dumps({"manifest_kind": "other"}))
            with self.assertRaises(HoldoutError):
                load_holdout_split(path)


class TestCertificateScoring(unittest.TestCase):
    ITEMS = [
        {
            "task_id": "t1", "test_example_id": 1,
            "train": [{"input": [[1]], "output": [[2]]}],
            "test_input": [[1, 2]], "expected_output": [[2, 1]],
            "source_task_partition": "split=test/task_id=t1",
        },
        {
            "task_id": "t2", "test_example_id": 1,
            "train": [{"input": [[1]], "output": [[2]]}],
            "test_input": [[3]], "expected_output": [[9]],
            "source_task_partition": "split=test/task_id=t2",
        },
    ]

    def _canonical(self, tmp: str):
        from submission_io import load_submission_file
        path = Path(tmp) / "sub.json"
        path.write_text(json.dumps({
            # t1 solved by attempt_2; t2 wrong on both.
            "t1": [{"attempt_1": [[1, 2]], "attempt_2": [[2, 1]]}],
            "t2": [{"attempt_1": [[3]], "attempt_2": [[3]]}],
        }), encoding="utf-8")
        return load_submission_file(path)

    def test_score_rows_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = score_rows_for_items(
                self._canonical(tmp), "cert-test", self.ITEMS)
            metrics = metrics_from_rows(rows)
            self.assertEqual(metrics["n_tasks"], 2)
            self.assertEqual(metrics["n_items"], 2)
            self.assertEqual(metrics["solved_items"], 1)
            self.assertEqual(metrics["solved_tasks"], 1)
            self.assertAlmostEqual(metrics["kaggle_score"], 0.5)
            self.assertIn("exact_match", metrics["failure_modes"])

    def test_metrics_empty(self):
        metrics = metrics_from_rows(None)
        self.assertIsNone(metrics["kaggle_score"])
        self.assertEqual(metrics["n_items"], 0)


class TestVerdictAndRender(unittest.TestCase):
    def test_verdict_precedence(self):
        self.assertEqual(verdict_from_checks(
            [{"status": "pass"}]), "GO")
        self.assertEqual(verdict_from_checks(
            [{"status": "pass"}, {"status": "warn"}]), "GO WITH WARNINGS")
        self.assertEqual(verdict_from_checks(
            [{"status": "warn"}, {"status": "fail"}]), "NO-GO")

    def test_render_contains_verdict_and_scores(self):
        ctx = {
            "solver_name": "demo",
            "submission_path": "sub.json",
            "benchmark": {"benchmark_name": "ARC-AGI-2", "pack_id": "p"},
            "n_expected_tasks": 2,
            "n_expected_items": 3,
            "checks": [
                {"name": "A", "status": "pass", "detail": "ok"},
                {"name": "B", "status": "warn", "detail": "meh"},
            ],
            "verdict": "GO WITH WARNINGS",
            "dev_label": "Dev (1 tasks)",
            "dev_metrics": {
                "n_items": 2, "n_tasks": 2, "solved_items": 1,
                "solved_tasks": 1, "kaggle_score": 0.5,
                "failure_modes": {"exact_match": 1},
            },
            "holdout_metrics": None,
            "holdout_score_cell": "sealed — `--reveal-holdout` (one-shot)",
            "batch": None,
            "batch_manifest_path": "",
            "variance": {"n_runs": 0, "scores": [], "mean": None,
                         "std": None},
            "created_at": "2026-07-16T00:00:00+00:00",
            "git_commit": "abcdef1234567890",
        }
        text = render_certificate(ctx)
        self.assertIn("**Verdict: GO WITH WARNINGS**", text)
        self.assertIn("0.5000", text)
        self.assertIn("sealed", text)
        self.assertIn("local_pilot_partial", text)


if __name__ == "__main__":
    unittest.main()

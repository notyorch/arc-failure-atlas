"""Offline unit tests for analytics legacy upgrade + aggregation helpers.

Does not run the full pipeline — only pure functions from build_analytics.

    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from build_analytics import (  # noqa: E402
    aggregate,
    normalize_evaluation_frame,
    solver_failure_matrix,
)
from contracts import ANALYTICS_METRIC_COLUMNS, EVALUATION_RESULTS_SCHEMA  # noqa: E402


def _v1_row(**overrides):
    base = {
        "run_id": "r1", "experiment_id": "e1",
        "provider": "mock", "model_name": "baseline",
        "prompt_version": "arc_grid_v1", "pipeline_version": "0.1.0",
        "task_id": "t1", "split": "test", "test_example_id": 1,
        "source_task_partition": "split=test/task_id=t1",
        "prompt_text": "p", "response_text": "[[1]]",
        "predicted_grid_json": "[[1]]", "expected_output_grid_json": "[[1]]",
        "status": "ok", "error_message": None,
        "latency_ms": 1.0, "cost_estimate_usd": 0.0,
        "started_at": "t0", "finished_at": "t1",
        "parse_status": "ok", "parse_error": None,
        "is_exact_match": True, "same_shape": True,
        "cell_accuracy": 1.0, "n_diff_cells": 0,
        "failure_mode": "exact_match", "failure_detail": None,
    }
    base.update(overrides)
    return base


class TestNormalizeLegacy(unittest.TestCase):
    def test_v1_upgrades_to_evaluation_schema(self):
        df = pd.DataFrame([
            _v1_row(),
            _v1_row(task_id="t2", failure_mode="api_error",
                    is_exact_match=None, response_text=None,
                    predicted_grid_json=None, status="error"),
        ])
        out = normalize_evaluation_frame(df)
        self.assertEqual(list(out.columns), list(EVALUATION_RESULTS_SCHEMA.keys()))
        self.assertEqual(out.loc[0, "solver_name"], "mock:baseline")
        self.assertEqual(out.loc[0, "raw_output"], "[[1]]")
        self.assertEqual(out.loc[0, "attempt"], 1)
        self.assertEqual(out.loc[0, "execution_mode"], "in_process")
        self.assertEqual(out.loc[1, "failure_mode"], "execution_error")
        self.assertEqual(out.loc[0, "pack_id"], "unknown")
        self.assertEqual(out.loc[0, "benchmark_name"], "unknown")


class TestAggregate(unittest.TestCase):
    def test_solved_rate_is_item_level_pass_at_k(self):
        # One item, two attempts: first miss, second hit → solved.
        rows = []
        for attempt, exact in ((1, False), (2, True)):
            rows.append({
                "run_id": "r1", "experiment_id": "e",
                "solver_name": "s", "solver_family": "submission",
                "solver_version": "v", "execution_mode": "submission_file",
                "pipeline_version": "0.2.0",
                "provider": None, "model_name": None, "prompt_version": None,
                "task_id": "t1", "split": "test", "test_example_id": 1,
                "source_task_partition": "x", "attempt": attempt,
                "prompt_text": None, "raw_output": None,
                "predicted_grid_json": "[[1]]",
                "expected_output_grid_json": "[[1]]",
                "status": "ok", "error_message": None,
                "latency_ms": 0.0, "cost_estimate_usd": 0.0,
                "input_tokens": None, "output_tokens": None,
                "started_at": "a", "finished_at": "b",
                "parse_status": "ok", "parse_error": None,
                "is_exact_match": exact, "same_shape": True,
                "cell_accuracy": 1.0 if exact else 0.0,
                "n_diff_cells": 0 if exact else 1,
                "failure_mode": "exact_match" if exact else "symbol_error",
                "failure_detail": None, "solver_metadata": None,
            })
        df = pd.DataFrame(rows)
        summary = aggregate(df, ["solver_name"])
        self.assertEqual(list(summary.columns),
                         ["solver_name"] + ANALYTICS_METRIC_COLUMNS)
        self.assertEqual(int(summary.loc[0, "n_items"]), 1)
        self.assertEqual(int(summary.loc[0, "n_attempts"]), 2)
        self.assertAlmostEqual(float(summary.loc[0, "exact_match_rate"]), 0.5)
        self.assertAlmostEqual(float(summary.loc[0, "solved_rate"]), 1.0)
        # One task with one (solved) test example → task fully solved.
        self.assertEqual(int(summary.loc[0, "n_tasks"]), 1)
        self.assertAlmostEqual(float(summary.loc[0, "task_solved_rate"]), 1.0)

    def test_task_solved_rate_requires_all_test_examples(self):
        """A task with two test examples counts as solved only when BOTH are;
        solved_rate (per test example) and task_solved_rate must diverge."""
        def _item_row(test_example_id, exact):
            return {
                "run_id": "r1", "experiment_id": "e",
                "solver_name": "s", "solver_family": "llm_direct",
                "solver_version": "v", "execution_mode": "in_process",
                "pipeline_version": "0.3.0",
                "provider": "mock", "model_name": "baseline",
                "prompt_version": "arc_grid_v1",
                "task_id": "t1", "split": "test",
                "test_example_id": test_example_id,
                "source_task_partition": "x", "attempt": 1,
                "prompt_text": None, "raw_output": "[[1]]",
                "predicted_grid_json": "[[1]]",
                "expected_output_grid_json": "[[1]]",
                "status": "ok", "error_message": None,
                "latency_ms": 1.0, "cost_estimate_usd": 0.0,
                "input_tokens": None, "output_tokens": None,
                "started_at": "a", "finished_at": "b",
                "parse_status": "ok", "parse_error": None,
                "is_exact_match": exact, "same_shape": True,
                "cell_accuracy": 1.0 if exact else 0.0,
                "n_diff_cells": 0 if exact else 1,
                "failure_mode": "exact_match" if exact else "symbol_error",
                "failure_detail": None, "solver_metadata": None,
            }
        df = pd.DataFrame([_item_row(1, True), _item_row(2, False)])
        summary = aggregate(df, ["solver_name"])
        self.assertEqual(int(summary.loc[0, "n_items"]), 2)
        self.assertEqual(int(summary.loc[0, "n_tasks"]), 1)
        self.assertAlmostEqual(float(summary.loc[0, "solved_rate"]), 0.5)
        self.assertAlmostEqual(float(summary.loc[0, "task_solved_rate"]), 0.0)

    def test_solver_failure_matrix_columns(self):
        df = pd.DataFrame([
            {"failure_mode": "exact_match", "solver_name": "a", "run_id": "1"},
            {"failure_mode": "shape_error", "solver_name": "a", "run_id": "1"},
            {"failure_mode": "exact_match", "solver_name": "b", "run_id": "2"},
        ])
        matrix = solver_failure_matrix(df)
        self.assertEqual(list(matrix.columns), ["a", "b"])
        self.assertEqual(int(matrix.loc["exact_match", "a"]), 1)
        self.assertEqual(int(matrix.loc["shape_error", "a"]), 1)

    def test_aggregate_when_group_cols_overlap_item_key(self):
        """summary_by_task groups on task_id, which is also in ITEM_KEY."""
        rows = []
        for task_id in ("t1", "t2"):
            rows.append({
                "run_id": "r1", "experiment_id": "e",
                "solver_name": "s", "solver_family": "llm_direct",
                "solver_version": "v", "execution_mode": "in_process",
                "pipeline_version": "0.2.0",
                "provider": "mock", "model_name": "baseline",
                "prompt_version": "arc_grid_v1",
                "task_id": task_id, "split": "test", "test_example_id": 1,
                "source_task_partition": "x", "attempt": 1,
                "prompt_text": None, "raw_output": "[[1]]",
                "predicted_grid_json": "[[1]]",
                "expected_output_grid_json": "[[1]]",
                "status": "ok", "error_message": None,
                "latency_ms": 1.0, "cost_estimate_usd": 0.0,
                "input_tokens": None, "output_tokens": None,
                "started_at": "a", "finished_at": "b",
                "parse_status": "ok", "parse_error": None,
                "is_exact_match": True, "same_shape": True,
                "cell_accuracy": 1.0, "n_diff_cells": 0,
                "failure_mode": "exact_match", "failure_detail": None,
                "solver_metadata": None,
            })
        summary = aggregate(pd.DataFrame(rows), ["task_id", "split"])
        self.assertEqual(len(summary), 2)
        self.assertEqual(int(summary["n_items"].sum()), 2)


if __name__ == "__main__":
    unittest.main()

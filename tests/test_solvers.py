"""Unit tests for src/solvers.py — offline, no subprocesses beyond the
interpret helper and the submission-file adapter.

    python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from solvers import (  # noqa: E402
    LLMDirectSolver,
    SolverAttempt,
    SolverError,
    SolverTask,
    SubmissionFileSolver,
    interpret_solver_output,
)


class TestWireIsolation(unittest.TestCase):
    def test_to_wire_excludes_expected_output(self):
        task = SolverTask(
            task_id="t1", test_example_id=1,
            train=[{"input": [[0]], "output": [[1]]}],
            test_input=[[2]],
            expected_output=[[9]],
        )
        wire = task.to_wire()
        self.assertNotIn("expected_output", wire)
        self.assertNotIn("expected_output", json.dumps(wire))
        self.assertEqual(wire["test"], [{"input": [[2]]}])
        self.assertEqual(wire["task_id"], "t1")


class TestInterpretOutput(unittest.TestCase):
    def test_attempts_envelope(self):
        attempts, meta = interpret_solver_output(json.dumps({
            "attempts": [[[1]], [[2]]],
            "metadata": {"seed": 7},
        }))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0].grid, [[1]])
        self.assertEqual(attempts[1].attempt, 2)
        self.assertEqual(meta, {"seed": 7})

    def test_prediction_envelope(self):
        attempts, meta = interpret_solver_output(
            json.dumps({"prediction": [[0, 1]], "metadata": None})
        )
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].grid, [[0, 1]])
        self.assertIsNone(meta)

    def test_raw_text_fallback(self):
        attempts, meta = interpret_solver_output("here is [[0,1],[2,3]] maybe")
        self.assertEqual(len(attempts), 1)
        self.assertIsInstance(attempts[0], SolverAttempt)
        self.assertIn("[[0,1]", attempts[0].raw_output)
        self.assertIsNone(meta)


class TestSubmissionFileSolver(unittest.TestCase):
    def test_reads_kaggle_style_attempts(self):
        payload = {
            "taskA": [{"attempt_1": [[1]], "attempt_2": [[2]]}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "submission.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            solver = SubmissionFileSolver(name="sub", path=path, version="t")
            result = solver.solve(SolverTask(
                task_id="taskA", test_example_id=1,
                train=[], test_input=[[0]],
            ))
            self.assertEqual(result.status, "ok")
            self.assertEqual(len(result.attempts), 2)
            self.assertEqual(result.attempts[0].grid, [[1]])

    def test_missing_task_is_execution_error_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "submission.json"
            path.write_text(json.dumps({
                "other": [{"attempt_1": [[0]]}],
            }), encoding="utf-8")
            solver = SubmissionFileSolver(name="sub", path=path)
            result = solver.solve(SolverTask(
                task_id="missing", test_example_id=1,
                train=[], test_input=[[0]],
            ))
            self.assertEqual(result.status, "error")
            self.assertIn("not present", result.error_message)

    def test_empty_submission_refuses_at_construction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "submission.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaises(SolverError):
                SubmissionFileSolver(name="sub", path=path)

    def test_missing_file_raises_at_construction(self):
        with self.assertRaises(SolverError):
            SubmissionFileSolver(name="sub", path="/no/such/submission.json")


class TestLLMDirectMultiAttempt(unittest.TestCase):
    def test_n_attempts_draws_independent_samples(self):
        solver = LLMDirectSolver(
            provider_name="mock", model_name="baseline", n_attempts=2,
        )
        task = SolverTask(
            task_id="sample01", test_example_id=1,
            train=[{"input": [[0]], "output": [[1]]}],
            test_input=[[0]],
            expected_output=[[1]],
        )
        result = solver.solve(task)
        self.assertEqual(result.status, "ok")
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.attempts[0].attempt, 1)
        self.assertEqual(result.attempts[1].attempt, 2)
        self.assertEqual(solver.describe()["n_attempts"], 2)


if __name__ == "__main__":
    unittest.main()

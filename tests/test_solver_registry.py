"""Unit tests for src/solver_registry.py — offline registry load + factory.

    python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import ConfigError  # noqa: E402
from solver_registry import (  # noqa: E402
    BUILTIN_ENTRIES,
    create_solver,
    format_registry,
    load_registry,
)
from solvers import (  # noqa: E402
    LLMDirectSolver,
    SubmissionDirSolver,
    SubmissionFileSolver,
)


class TestBuiltinRegistry(unittest.TestCase):
    def test_builtins_always_present(self):
        registry = load_registry(path=Path("/nonexistent/solvers.json"))
        self.assertIn("mock-baseline", registry)
        self.assertIn("mock-large", registry)
        self.assertTrue(registry["mock-baseline"]["enabled"])

    def test_create_mock_baseline(self):
        registry = load_registry(path=Path("/nonexistent/solvers.json"))
        solver = create_solver("mock-baseline", registry)
        self.assertIsInstance(solver, LLMDirectSolver)
        self.assertEqual(solver.name, "mock-baseline")
        self.assertEqual(solver.family, "llm_direct")
        self.assertEqual(solver.execution_mode, "in_process")

    def test_unknown_solver_is_actionable(self):
        registry = load_registry(path=Path("/nonexistent/solvers.json"))
        with self.assertRaises(ConfigError) as ctx:
            create_solver("no-such-solver", registry)
        self.assertIn("Unknown solver", str(ctx.exception))

    def test_format_registry_lists_builtins(self):
        text = format_registry(BUILTIN_ENTRIES)
        self.assertIn("mock-baseline", text)
        self.assertIn("in_process", text)


class TestFileRegistry(unittest.TestCase):
    def test_merges_and_rejects_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solvers.json"
            path.write_text(json.dumps({
                "solvers": {
                    "mock-baseline": {
                        "adapter": "in_process",
                        "provider": "mock", "model": "x",
                    },
                },
            }), encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_registry(path)
            self.assertIn("collides", str(ctx.exception))

    def test_disabled_entry_refuses_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "solvers.json"
            path.write_text(json.dumps({
                "solvers": {
                    "ref-only": {
                        "adapter": "submission_file",
                        "family": "submission",
                        "enabled": False,
                        "path": "artifacts/submissions/x.json",
                        "notes": "wire me up",
                    },
                },
            }), encoding="utf-8")
            registry = load_registry(path)
            with self.assertRaises(ConfigError) as ctx:
                create_solver("ref-only", registry)
            self.assertIn("disabled", str(ctx.exception))
            self.assertIn("wire me up", str(ctx.exception))

    def test_submission_file_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = Path(tmp) / "sub.json"
            sub.write_text(json.dumps({
                "t1": [{"attempt_1": [[1]]}],
            }), encoding="utf-8")
            path = Path(tmp) / "solvers.json"
            path.write_text(json.dumps({
                "solvers": {
                    "file-judge": {
                        "adapter": "submission_file",
                        "family": "submission",
                        "enabled": True,
                        "path": str(sub),
                        "version": "t",
                    },
                },
            }), encoding="utf-8")
            solver = create_solver("file-judge", load_registry(path))
            self.assertIsInstance(solver, SubmissionFileSolver)
            self.assertEqual(solver.execution_mode, "submission_file")

    def test_submission_dir_alias_and_adapter_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            pred_dir = Path(tmp) / "preds"
            pred_dir.mkdir()
            (pred_dir / "t1.json").write_text(
                json.dumps({"attempt_1": [[1]]}), encoding="utf-8")
            path = Path(tmp) / "solvers.json"
            path.write_text(json.dumps({
                "solvers": {
                    "dir-judge": {
                        "adapter_type": "submission_dir",
                        "family": "submission",
                        "enabled": True,
                        "path": str(pred_dir),
                        "version": "t",
                    },
                    "cli-alias": {
                        "adapter": "subprocess_cli",
                        "family": "external",
                        "enabled": True,
                        "command": ["python", "-c", "print(1)"],
                    },
                },
            }), encoding="utf-8")
            registry = load_registry(path)
            self.assertEqual(registry["dir-judge"]["adapter"], "submission_dir")
            self.assertEqual(registry["cli-alias"]["adapter"], "subprocess")
            solver = create_solver("dir-judge", registry)
            self.assertIsInstance(solver, SubmissionDirSolver)
            self.assertEqual(solver.execution_mode, "submission_dir")


if __name__ == "__main__":
    unittest.main()

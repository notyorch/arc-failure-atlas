"""Unit tests for src/batch_runner.py — offline, no GPU, temp dirs only.

    python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from batch_runner import (  # noqa: E402
    ProjectManifestError,
    load_project,
    locate_artifact,
    run_project,
    stage_tasks,
)

TASKS = [
    {
        "task_id": "t1",
        "train": [{"input": [[1, 2]], "output": [[2, 1]]}],
        "test": [
            {"example_id": 1, "input": [[3, 4]], "output": [[4, 3]]},
            {"example_id": 2, "input": [[5]], "output": [[5]]},
        ],
    },
    {
        "task_id": "t2",
        "train": [{"input": [[0]], "output": [[9]]}],
        "test": [{"example_id": 1, "input": [[7, 7]], "output": None}],
    },
]


def _write_project(tmp: str, **overrides) -> Path:
    payload = {
        "manifest_kind": "solver_project",
        "name": "test-project",
        "version": "0.0.1",
        "command": ["python", "-c", "print('noop')"],
        "workdir": ".",
        "artifact": "out/submission.json",
        "budget_hours": 0.01,
        "gpu_telemetry": False,
    }
    payload.update(overrides)
    path = Path(tmp) / "atlas_project.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestLoadProject(unittest.TestCase):
    def test_valid_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_write_project(tmp))
            self.assertEqual(project["name"], "test-project")
            self.assertEqual(project["workdir"], Path(tmp).resolve())
            self.assertEqual(project["budget_hours"], 0.01)

    def test_missing_name_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_project(tmp)
            data = json.loads(path.read_text())
            del data["name"]
            path.write_text(json.dumps(data))
            with self.assertRaises(ProjectManifestError):
                load_project(path)

    def test_command_must_be_string_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProjectManifestError):
                load_project(_write_project(tmp, command="python x.py"))

    def test_wrong_kind_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ProjectManifestError):
                load_project(_write_project(tmp, manifest_kind="solver"))

    def test_missing_file_fails(self):
        with self.assertRaises(ProjectManifestError):
            load_project(Path("/nonexistent/atlas_project.json"))


class TestStageTasks(unittest.TestCase):
    def test_ground_truth_is_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            tasks_dir = stage_tasks(TASKS, Path(tmp), {"pack_id": "x"})
            staged = json.loads(
                (tasks_dir / "t1.json").read_text(encoding="utf-8"))
            self.assertEqual(len(staged["train"]), 1)
            self.assertIn("output", staged["train"][0])
            self.assertEqual(len(staged["test"]), 2)
            for test_example in staged["test"]:
                self.assertEqual(set(test_example.keys()), {"input"})
            raw = (tasks_dir / "t1.json").read_text(encoding="utf-8")
            self.assertNotIn("[[4, 3]]", raw)

    def test_stage_manifest_seals_the_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage_tasks(TASKS, Path(tmp), {"pack_id": "x"})
            manifest = json.loads(
                (Path(tmp) / "_stage_manifest.json").read_text())
            self.assertTrue(manifest["ground_truth_excluded"])
            self.assertEqual(manifest["n_tasks"], 2)
            self.assertEqual(manifest["benchmark"]["pack_id"], "x")


class TestRunProject(unittest.TestCase):
    def test_env_contract_and_artifact(self):
        script = (
            "import json, os, pathlib\n"
            "tasks = sorted(pathlib.Path(os.environ['ATLAS_TASKS_DIR'])"
            ".glob('*.json'))\n"
            "sub = {t.stem: [{'attempt_1': [[0]], 'attempt_2': [[0]]}] "
            "for t in tasks}\n"
            "out = pathlib.Path(os.environ['ATLAS_SUBMISSION_PATH'])\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_text(json.dumps(sub))\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            tasks_dir = stage_tasks(TASKS, stage, {})
            project = load_project(_write_project(
                tmp, command=["python", "-c", script]))
            submission_path = stage / "submission.json"
            execution = run_project(
                project, tasks_dir, submission_path, stage)
            self.assertEqual(execution["exit_code"], 0)
            self.assertFalse(execution["budget_exceeded"])
            self.assertFalse(execution["offline"])
            artifact = locate_artifact(project, submission_path)
            self.assertEqual(artifact, submission_path)
            sub = json.loads(artifact.read_text())
            self.assertEqual(set(sub), {"t1", "t2"})

    def test_budget_enforcement_kills_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp) / "stage"
            tasks_dir = stage_tasks(TASKS, stage, {})
            project = load_project(_write_project(
                tmp,
                command=["python", "-c", "import time; time.sleep(30)"],
                budget_hours=0.5 / 3600.0,  # 0.5 s
            ))
            execution = run_project(
                project, tasks_dir, stage / "submission.json", stage,
                enforce_budget=True,
            )
            self.assertTrue(execution["budget_exceeded"])
            self.assertNotEqual(execution["exit_code"], 0)

    def test_locate_artifact_falls_back_to_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_write_project(tmp))
            fallback = Path(tmp) / "out" / "submission.json"
            fallback.parent.mkdir(parents=True)
            fallback.write_text("{}")
            found = locate_artifact(project, Path(tmp) / "missing.json")
            self.assertEqual(found, fallback.resolve())

    def test_locate_artifact_none_when_nothing_produced(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = load_project(_write_project(tmp))
            self.assertIsNone(
                locate_artifact(project, Path(tmp) / "missing.json"))


if __name__ == "__main__":
    unittest.main()

"""
Batch runner — evaluate a COMPLETE solver project (pipeline) pre-submit.

Systematic ARC systems (test-time training, program search, ensembles —
NVARC / ARChitects style) are not per-task stdin/stdout CLIs: they load
models, fine-tune per task, and emit one submission.json after minutes or
hours. This runner gives them the same judge as every other adapter while
measuring what actually decides a Kaggle submit: wall time vs budget,
offline viability, and coverage.

Flow:

    stage   tasks Parquet → <stage_dir>/tasks/<task_id>.json
            (official ARC JSON, test outputs STRIPPED — fairness invariant)
    run     the project's own command, cwd = its own repo/workdir.
            Env contract:  ATLAS_TASKS_DIR      where to read tasks
                           ATLAS_SUBMISSION_PATH where to write submission.json
            Telemetry: wall clock, exit code, optional nvidia-smi polling.
            Guards: --offline (network-isolated via `unshare -rn`),
            --enforce-budget (kill past budget_hours), --resume (skip run
            when the artifact already exists).
    collect validate the produced submission.json, then score it through
            the standard submission path (identical judge, run manifests,
            taxonomy, analytics). `batch_manifest.json` records telemetry.

The project declares itself in a small JSON manifest (see
examples/batch_project/atlas_project.json):

    {
      "manifest_kind": "solver_project",
      "name": "my-pipeline",
      "version": "1.0.0",
      "command": ["python", "solve_pipeline.py"],
      "workdir": ".",                    // relative to this manifest
      "env": {"MY_FLAG": "1"},           // extra environment (no secrets)
      "artifact": "out/submission.json", // fallback if the project cannot
                                         // honor ATLAS_SUBMISSION_PATH
      "budget_hours": 12.0,              // Kaggle-style wall budget
      "gpu_telemetry": true
    }

Usage (repo root):

    python src/batch_runner.py --project examples/batch_project/atlas_project.json \
        --stage-dir artifacts/batch/example --experiment-id batch-example
    python src/batch_runner.py --project ... --offline --enforce-budget
    python src/batch_runner.py --project ... --resume        # artifact kept
    python src/batch_runner.py --project ... --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from manifest import git_commit_sha, portable_path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STAGE_ROOT = REPO_ROOT / "artifacts" / "batch"
BATCH_MANIFEST_FILENAME = "batch_manifest.json"
GPU_POLL_SECONDS = 15


class ProjectManifestError(ValueError):
    """solver_project manifest missing/invalid. Message is actionable."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Project manifest
# ---------------------------------------------------------------------------

def load_project(path: Path) -> dict:
    """Load + validate an atlas_project.json solver-project manifest."""
    path = Path(path)
    if not path.exists():
        raise ProjectManifestError(f"Project manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectManifestError(
            f"Invalid JSON in {path}: {exc.msg} (line {exc.lineno})"
        ) from exc
    if not isinstance(data, dict):
        raise ProjectManifestError(f"{path} must be a JSON object")

    kind = data.get("manifest_kind", "solver_project")
    if kind != "solver_project":
        raise ProjectManifestError(
            f"{path}: manifest_kind must be 'solver_project' (got {kind!r})"
        )
    name = data.get("name")
    command = data.get("command")
    if not name or not isinstance(name, str):
        raise ProjectManifestError(f"{path}: 'name' (string) is required")
    if (not isinstance(command, list) or not command
            or not all(isinstance(c, str) for c in command)):
        raise ProjectManifestError(
            f"{path}: 'command' must be a non-empty list of strings"
        )
    env = data.get("env") or {}
    if not isinstance(env, dict):
        raise ProjectManifestError(f"{path}: 'env' must be an object")

    workdir = (path.parent / data.get("workdir", ".")).resolve()
    if not workdir.is_dir():
        raise ProjectManifestError(
            f"{path}: workdir does not exist: {workdir}"
        )
    budget_hours = data.get("budget_hours", 12.0)
    try:
        budget_hours = float(budget_hours)
    except (TypeError, ValueError):
        raise ProjectManifestError(
            f"{path}: 'budget_hours' must be a number"
        ) from None

    return {
        "manifest_path": path,
        "name": name,
        "version": str(data.get("version", "unversioned")),
        "command": command,
        "workdir": workdir,
        "env": {str(k): str(v) for k, v in env.items()},
        "artifact": data.get("artifact"),
        "budget_hours": budget_hours,
        "gpu_telemetry": bool(data.get("gpu_telemetry", True)),
    }


# ---------------------------------------------------------------------------
# Stage: official ARC task JSON, ground truth stripped
# ---------------------------------------------------------------------------

def stage_tasks(tasks: list, stage_dir: Path, benchmark_meta: dict) -> Path:
    """
    Write `<stage_dir>/tasks/<task_id>.json` in official ARC format with
    test outputs removed. The solver project reads ONLY this directory, so
    the fairness invariant (ground truth never leaves the judge) holds by
    construction.
    """
    tasks_dir = Path(stage_dir) / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        payload = {
            "train": [
                {"input": ex["input"], "output": ex["output"]}
                for ex in task["train"]
                if ex["input"] is not None and ex["output"] is not None
            ],
            "test": [
                {"input": ex["input"]}
                for ex in task["test"]
                if ex["input"] is not None
            ],
        }
        (tasks_dir / f"{task['task_id']}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
    stage_manifest = {
        "manifest_kind": "batch_stage",
        "created_at": utc_now_iso(),
        "n_tasks": len(tasks),
        "ground_truth_excluded": True,
        "benchmark": dict(benchmark_meta or {}),
        "git_commit": git_commit_sha(),
    }
    (Path(stage_dir) / "_stage_manifest.json").write_text(
        json.dumps(stage_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return tasks_dir


# ---------------------------------------------------------------------------
# Run: subprocess + telemetry
# ---------------------------------------------------------------------------

class GpuSampler:
    """Background nvidia-smi polling; silently absent without a GPU."""

    def __init__(self, interval_s: int = GPU_POLL_SECONDS):
        self.interval_s = interval_s
        self.samples = 0
        self.max_memory_mb = None
        self.max_utilization_pct = None
        self._stop = threading.Event()
        self._thread = None
        self.available = shutil.which("nvidia-smi") is not None

    def _poll_once(self) -> None:
        try:
            out = subprocess.run(
                ["nvidia-smi",
                 "--query-gpu=memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0:
            return
        for line in out.stdout.strip().splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) != 2:
                continue
            try:
                mem, util = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            self.samples += 1
            self.max_memory_mb = max(self.max_memory_mb or 0.0, mem)
            self.max_utilization_pct = max(
                self.max_utilization_pct or 0.0, util)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            self._poll_once()

    def start(self) -> None:
        if not self.available:
            return
        self._poll_once()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if not self.available:
            return {"available": False}
        return {
            "available": True,
            "samples": self.samples,
            "max_memory_mb": self.max_memory_mb,
            "max_utilization_pct": self.max_utilization_pct,
        }


def offline_wrapper() -> list:
    """
    Command prefix that drops network access (Linux user+net namespace).
    Verified with a no-op before use; callers fail loudly when unsupported
    rather than pretending the run was offline.
    """
    unshare = shutil.which("unshare")
    if unshare is None:
        raise RuntimeError(
            "--offline needs the `unshare` binary (util-linux). "
            "Alternatively run your project inside `docker run --network none`."
        )
    probe = subprocess.run(
        [unshare, "-r", "-n", "true"],
        capture_output=True, text=True, timeout=15,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            "--offline: `unshare -r -n` is not permitted on this system "
            f"({probe.stderr.strip() or 'unknown error'}). "
            "Use `docker run --network none` instead."
        )
    return [unshare, "-r", "-n"]


def run_project(project: dict, tasks_dir: Path, submission_path: Path,
                stage_dir: Path, *, offline: bool = False,
                enforce_budget: bool = False) -> dict:
    """
    Execute the project command with the ATLAS env contract. Returns the
    execution block of the batch manifest (timing, exit code, telemetry).
    """
    command = list(project["command"])
    if offline:
        command = offline_wrapper() + command

    env = dict(os.environ)
    env.update(project["env"])
    env["ATLAS_TASKS_DIR"] = str(tasks_dir.resolve())
    env["ATLAS_SUBMISSION_PATH"] = str(submission_path.resolve())

    log_path = Path(stage_dir) / "project_run.log"
    budget_s = project["budget_hours"] * 3600.0
    started_at = utc_now_iso()
    start = time.monotonic()
    budget_exceeded = False
    logging.info("Launching project '%s': %s (cwd=%s, budget=%.2fh%s)",
                 project["name"], " ".join(command), project["workdir"],
                 project["budget_hours"], ", offline" if offline else "")

    sampler = GpuSampler() if project["gpu_telemetry"] else None
    if sampler:
        sampler.start()
    with open(log_path, "w", encoding="utf-8") as log_fh:
        proc = subprocess.Popen(
            command, cwd=project["workdir"], env=env,
            stdout=log_fh, stderr=subprocess.STDOUT,
        )
        try:
            if enforce_budget:
                try:
                    proc.wait(timeout=budget_s)
                except subprocess.TimeoutExpired:
                    budget_exceeded = True
                    logging.error(
                        "Budget of %.2fh exceeded — terminating project "
                        "(this WOULD have failed on Kaggle).",
                        project["budget_hours"],
                    )
                    proc.terminate()
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
            else:
                proc.wait()
        except KeyboardInterrupt:
            proc.terminate()
            raise

    wall_s = time.monotonic() - start
    gpu = sampler.stop() if sampler else {"available": False}
    if not budget_exceeded and wall_s > budget_s:
        budget_exceeded = True

    return {
        "command": command,
        "workdir": portable_path(project["workdir"]),
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "wall_seconds": round(wall_s, 3),
        "wall_hours": round(wall_s / 3600.0, 4),
        "budget_hours": project["budget_hours"],
        "budget_utilization": (
            round(wall_s / budget_s, 4) if budget_s > 0 else None
        ),
        "budget_exceeded": budget_exceeded,
        "budget_enforced": enforce_budget,
        "offline": offline,
        "exit_code": proc.returncode,
        "log": portable_path(log_path),
        "gpu": gpu,
    }


# ---------------------------------------------------------------------------
# Collect: locate artifact, write batch manifest, delegate scoring
# ---------------------------------------------------------------------------

def locate_artifact(project: dict, submission_path: Path) -> Path | None:
    """Prefer the env-contract path; fall back to the manifest's artifact."""
    if submission_path.is_file():
        return submission_path
    if project["artifact"]:
        fallback = (project["workdir"] / project["artifact"]).resolve()
        if fallback.is_file():
            return fallback
    return None


def write_batch_manifest(stage_dir: Path, payload: dict) -> Path:
    path = Path(stage_dir) / BATCH_MANIFEST_FILENAME
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def score_artifact(artifact: Path, project: dict, args) -> int:
    """Same judge as every adapter: delegate to run_evaluation via argv."""
    import run_evaluation

    argv = [sys.argv[0], "--submission-file", str(artifact),
            "--solver-name", project["name"],
            "--solver-version", project["version"]]
    if args.experiment_id:
        argv += ["--experiment-id", args.experiment_id]
    if args.input_path:
        argv += ["--input-path", str(args.input_path)]
    if args.task_id:
        argv += ["--task-id", args.task_id]
    if args.limit is not None:
        argv += ["--limit", str(args.limit)]
    if args.benchmark_pack:
        argv += ["--benchmark-pack", args.benchmark_pack]

    old_argv = sys.argv
    try:
        sys.argv = argv
        run_evaluation.main()
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else (1 if exc.code else 0)
    finally:
        sys.argv = old_argv
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Stage tasks, run a complete solver project against "
                    "them, and judge the submission it produces.",
    )
    parser.add_argument("--project", type=Path, required=True,
                        help="solver_project manifest (atlas_project.json)")
    parser.add_argument("--stage-dir", type=Path, default=None,
                        help=f"working directory (default: "
                             f"{DEFAULT_STAGE_ROOT}/<project-name>)")
    parser.add_argument("--input-path", type=Path, default=None,
                        help="tasks Parquet (default: data/parquet/evaluation)")
    parser.add_argument("--benchmark-pack", default=None,
                        help="restrict staging/scoring to this pack's task ids "
                             "and stamp pack metadata on the score run")
    parser.add_argument("--task-id", default=None,
                        help="stage/score only these task ids (comma-separated)")
    parser.add_argument("--limit", type=int, default=None,
                        help="stage/score at most N tasks")
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--offline", action="store_true",
                        help="run the project without network access "
                             "(detects hidden internet dependencies that "
                             "would fail in a Kaggle notebook)")
    parser.add_argument("--enforce-budget", action="store_true",
                        help="kill the project past budget_hours instead of "
                             "just reporting the overrun")
    parser.add_argument("--resume", action="store_true",
                        help="skip execution when the submission artifact "
                             "already exists; collect and score it")
    parser.add_argument("--no-score", action="store_true",
                        help="stage + run + collect only (no judge run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the staging/run plan and exit")
    return parser


def main() -> None:
    args = build_parser().parse_args()

    try:
        project = load_project(args.project)
    except ProjectManifestError as exc:
        sys.exit(f"ERROR: {exc}")

    stage_dir = (args.stage_dir
                 or DEFAULT_STAGE_ROOT / project["name"]).resolve()
    submission_path = stage_dir / "submission.json"

    # Stage — reuses the ETL contract; identical task universe as the judge.
    from benchmark_packs import metadata_for_evaluation_items
    from task_loader import (
        DEFAULT_TASKS_PARQUET,
        load_tasks_dataframe,
        reconstruct_tasks,
    )
    input_path = args.input_path or DEFAULT_TASKS_PARQUET
    try:
        tasks_df = load_tasks_dataframe(input_path)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    pack_override = None
    pack_task_ids: set[str] | None = None
    if args.benchmark_pack:
        from benchmark_packs import (
            BenchmarkPackError,
            require_tasks_dir,
            resolve_pack,
        )
        try:
            pack_override = resolve_pack(pack_id=args.benchmark_pack)
            tasks_root = require_tasks_dir(pack_override)
        except BenchmarkPackError as exc:
            sys.exit(f"ERROR: {exc}")
        pack_task_ids = {p.stem for p in tasks_root.glob("*.json")}
        if not pack_task_ids:
            sys.exit(
                f"ERROR: pack {args.benchmark_pack!r} has no task JSON under "
                f"{tasks_root}"
            )

    benchmark_meta = metadata_for_evaluation_items(
        tasks_df, input_path, pack_override,
    )
    tasks = reconstruct_tasks(tasks_df)
    if pack_task_ids is not None:
        tasks = [t for t in tasks if t["task_id"] in pack_task_ids]
        if not tasks:
            sys.exit(
                f"ERROR: no tasks from pack {args.benchmark_pack!r} found in "
                f"{input_path}. Re-ETL that pack first:\n"
                f"  python src/main.py --benchmark-pack {args.benchmark_pack}"
            )
    if args.task_id:
        wanted = {t.strip() for t in args.task_id.split(",") if t.strip()}
        missing = wanted - {t["task_id"] for t in tasks}
        if missing:
            sys.exit(f"ERROR: task id(s) not in tasks Parquet: {sorted(missing)}")
        tasks = [t for t in tasks if t["task_id"] in wanted]
    if args.limit is not None:
        tasks = tasks[: args.limit]
    if not tasks:
        sys.exit("ERROR: nothing to stage (check --task-id / --limit).")

    # Keep scoring scoped to the same universe we staged (avoids coverage
    # floods when the local evaluation Parquet mixes multiple packs).
    if args.task_id is None and (pack_task_ids is not None or args.limit is not None):
        args.task_id = ",".join(t["task_id"] for t in tasks)

    if args.dry_run:
        print(f"DRY RUN — project={project['name']} v{project['version']}")
        print(f"  command   : {' '.join(project['command'])}"
              f"{'  (offline-wrapped)' if args.offline else ''}")
        print(f"  workdir   : {project['workdir']}")
        print(f"  stage_dir : {stage_dir}")
        print(f"  tasks     : {len(tasks)} → {stage_dir / 'tasks'} "
              "(test outputs stripped)")
        print(f"  artifact  : {submission_path} "
              f"(fallback: {project['artifact']})")
        print(f"  budget    : {project['budget_hours']}h "
              f"(enforced: {args.enforce_budget})")
        return

    tasks_dir = stage_tasks(tasks, stage_dir, benchmark_meta)
    logging.info("Staged %d task(s) → %s (ground truth stripped)",
                 len(tasks), tasks_dir)

    # Run (or resume past it).
    if args.resume and locate_artifact(project, submission_path):
        logging.info("--resume: artifact already present, skipping execution")
        execution = {"skipped": True, "reason": "resume", "offline": None}
    else:
        try:
            execution = run_project(
                project, tasks_dir, submission_path, stage_dir,
                offline=args.offline, enforce_budget=args.enforce_budget,
            )
        except RuntimeError as exc:
            sys.exit(f"ERROR: {exc}")

    artifact = locate_artifact(project, submission_path)
    payload = {
        "manifest_kind": "batch_run",
        "project": {
            "name": project["name"],
            "version": project["version"],
            "manifest_path": portable_path(project["manifest_path"]),
        },
        "benchmark": dict(benchmark_meta or {}),
        "n_tasks_staged": len(tasks),
        "task_ids": [t["task_id"] for t in tasks],
        "stage_dir": portable_path(stage_dir),
        "artifact": portable_path(artifact) if artifact else None,
        "artifact_found": artifact is not None,
        "execution": execution,
        "git_commit": git_commit_sha(),
        "created_at": utc_now_iso(),
    }
    manifest_path = write_batch_manifest(stage_dir, payload)
    logging.info("Batch manifest → %s", manifest_path)

    if execution.get("budget_exceeded"):
        print(f"\nWARNING: wall time exceeded the {project['budget_hours']}h "
              "budget — this submission flow would time out on Kaggle.")

    if artifact is None:
        sys.exit(
            "ERROR: project finished but no submission artifact was found.\n"
            f"  expected (env contract): {submission_path}\n"
            f"  fallback (manifest)    : {project['artifact']}\n"
            f"  project log            : {stage_dir / 'project_run.log'}"
        )
    print(f"\ncollected artifact  : {artifact}")

    if args.no_score:
        print("scoring skipped (--no-score). Judge it later with:\n"
              f"  python src/submission_cli.py evaluate-submission "
              f"--path {artifact} --solver-name {project['name']}")
        return

    code = score_artifact(artifact, project, args)
    if code:
        sys.exit(code)
    print(f"batch manifest      : {manifest_path}")
    print("next step           : python src/presubmit_cli.py certify "
          f"--submission {artifact} "
          f"--batch-manifest {manifest_path}")


if __name__ == "__main__":
    main()

"""
End-to-end smoke test: ETL → mock inference → analytics on a tiny subset.

Runs the three real CLIs (subprocesses, same interpreter) against an
isolated temporary directory, so it never touches data/ in the repository.
Fully offline: uses 3 bundled sample tasks and the mock provider.

    python scripts/smoke_test.py            # ~10 s, exit 0 on PASS
    python scripts/smoke_test.py --keep     # keep the temp dir for inspection

Checks: task Parquet row counts, inference row count + manifest, the four
analytics tables + build manifest, and the generated report.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = REPO_ROOT / "tests" / "fixtures" / "sample_tasks"

N_TASKS = 3
# Per sample task: 2 train examples (input+output) + 1 test (input+output).
EXPECTED_TASK_ROWS = N_TASKS * 6
MODEL_NAME = "smoke"

_checks_passed = 0


def run_step(name: str, cmd: list, cwd: Path) -> None:
    print(f"\n[{name}] $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        sys.exit(f"SMOKE FAIL — step '{name}' exited with {result.returncode}")
    print(f"[{name}] OK")


def check(label: str, condition: bool, detail: str = "") -> None:
    global _checks_passed
    if not condition:
        sys.exit(f"SMOKE FAIL — {label}{': ' + detail if detail else ''}")
    _checks_passed += 1
    print(f"  ✓ {label}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--keep", action="store_true",
                        help="keep the temporary working directory")
    args = parser.parse_args()

    import pandas as pd  # after argparse so --help works without pandas

    started = time.perf_counter()
    workdir = Path(tempfile.mkdtemp(prefix="arc-smoke-"))
    print(f"Smoke workdir: {workdir}")

    try:
        # 1. Stage a tiny raw dataset.
        raw_dir = workdir / "data" / "raw" / "evaluation"
        raw_dir.mkdir(parents=True)
        sample_files = sorted(SAMPLES_DIR.glob("*.json"))[:N_TASKS]
        check(f"{N_TASKS} sample fixtures available",
              len(sample_files) == N_TASKS, f"found {len(sample_files)}")
        for f in sample_files:
            shutil.copy2(f, raw_dir / f.name)

        # 2. ETL — src/main.py resolves data/ and logs/ relative to the cwd,
        # so running it from the workdir keeps everything isolated.
        run_step("etl", [sys.executable, str(REPO_ROOT / "src" / "main.py")],
                 cwd=workdir)
        tasks_parquet = workdir / "data" / "parquet" / "evaluation"
        tasks = pd.read_parquet(tasks_parquet)
        check("tasks Parquet row count",
              len(tasks) == EXPECTED_TASK_ROWS,
              f"expected {EXPECTED_TASK_ROWS}, got {len(tasks)}")
        check("tasks Parquet has 15 columns", len(tasks.columns) == 15)

        # 3. Mock inference.
        run_dir = workdir / "runs" / "smoke-run"
        run_step("infer-mock", [
            sys.executable, str(REPO_ROOT / "src" / "run_inference.py"),
            "--provider", "mock", "--model", MODEL_NAME,
            "--experiment-id", "smoke",
            "--input-path", str(tasks_parquet),
            "--output-path", str(run_dir),
        ], cwd=workdir)
        results = pd.read_parquet(run_dir)
        check("inference row count", len(results) == N_TASKS,
              f"expected {N_TASKS}, got {len(results)}")
        check("all rows have a failure_mode",
              results["failure_mode"].notna().all())
        manifest = json.loads((run_dir / "_manifest.json").read_text())
        check("run manifest completed",
              manifest["status"] == "completed"
              and manifest["n_rows_written"] == N_TASKS
              and manifest["provider"] == "mock"
              and manifest["prompt_version"] == "arc_grid_v1")

        # 4. Analytics + report.
        analytics_dir = workdir / "analytics"
        report_path = workdir / "reports" / "smoke_report.md"
        run_step("analytics", [
            sys.executable, str(REPO_ROOT / "src" / "build_analytics.py"),
            "--runs-path", str(workdir / "runs"),
            "--output-path", str(analytics_dir),
            "--report-path", str(report_path),
        ], cwd=workdir)
        for table in ("fact_inference_results", "summary_by_model",
                      "summary_by_failure_mode", "summary_by_task"):
            frame = pd.read_parquet(analytics_dir / table)
            check(f"analytics table {table} non-empty", len(frame) > 0)
        fact = pd.read_parquet(analytics_dir / "fact_inference_results")
        check("fact table row count", len(fact) == N_TASKS)
        build_manifest = json.loads(
            (analytics_dir / "_manifest.json").read_text())
        check("analytics manifest completed",
              build_manifest["status"] == "completed"
              and build_manifest["tables"]["fact_inference_results"] == N_TASKS)
        check("report generated",
              report_path.exists()
              and "ARC Failure Atlas" in report_path.read_text(encoding="utf-8"))

        elapsed = time.perf_counter() - started
        print(f"\nSMOKE PASS — {_checks_passed} checks in {elapsed:.1f}s")
        if args.keep:
            print(f"Workdir kept at: {workdir}")
    finally:
        if not args.keep:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()

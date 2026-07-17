"""
Reference solver project for the ATLAS batch runner (env contract demo).

This is deliberately NOT a good solver — it stands in for a complete
pipeline (NVARC / ARChitects style) so you can see the whole pre-submit
loop run in seconds, offline. Replace this file with your system; keep
the contract:

    read  ATLAS_TASKS_DIR        one <task_id>.json per task, official ARC
                                 format, test outputs absent
    write ATLAS_SUBMISSION_PATH  Kaggle-style submission.json with
                                 attempt_1 AND attempt_2 per test example

Baseline strategy: attempt_1 echoes the test input; attempt_2 mirrors it
horizontally. Both are valid grids, so the judge scores (rather than
parse-fails) every item.
"""

import json
import os
import sys
from pathlib import Path


def solve_task(task: dict) -> list:
    predictions = []
    for test_example in task.get("test", []):
        grid = test_example["input"]
        mirrored = [list(reversed(row)) for row in grid]
        predictions.append({"attempt_1": grid, "attempt_2": mirrored})
    return predictions


def main() -> None:
    tasks_dir = os.environ.get("ATLAS_TASKS_DIR")
    out_path = os.environ.get("ATLAS_SUBMISSION_PATH")
    if not tasks_dir:
        sys.exit("ATLAS_TASKS_DIR not set — run me through src/batch_runner.py")
    if not out_path:
        out_path = Path(__file__).parent / "out" / "submission.json"

    submission = {}
    task_files = sorted(Path(tasks_dir).glob("*.json"))
    for i, task_file in enumerate(task_files, start=1):
        task = json.loads(task_file.read_text(encoding="utf-8"))
        submission[task_file.stem] = solve_task(task)
        print(f"[{i}/{len(task_files)}] {task_file.stem}", flush=True)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(submission), encoding="utf-8")
    print(f"wrote {out_path} ({len(submission)} task(s))")


if __name__ == "__main__":
    main()

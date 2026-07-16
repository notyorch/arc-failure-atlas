#!/usr/bin/env python3
"""
Minimal subprocess CLI wrapper template for an external ARC solver.

Wire contract (see src/solvers.py CommandSolver):
  stdin:  JSON task from SolverTask.to_wire() — NEVER includes ground truth
  stdout: {"prediction": grid}  OR  {"attempts": [grid, ...]}  OR raw text

Replace `solve_locally` with a call into your existing project. Do not rewrite
your solver as a Python class for this platform — wrap what you already have.

Usage (manual check):
  echo '{"task_id":"t","test_example_id":1,"train":[],"test":[{"input":[[0]]}]}' \\
    | python examples/external_solver/cli_wrapper_template.py
"""

from __future__ import annotations

import json
import sys


def solve_locally(task: dict) -> list:
    """
    YOUR CODE HERE.

    `task` looks like:
      {"task_id": "...", "test_example_id": 1,
       "train": [{"input": [[...]], "output": [[...]]}, ...],
       "test":  [{"input": [[...]]}]}

    Return a single 2D grid of ints 0–9 (or raise SystemExit with a message).
    """
    test_input = task["test"][0]["input"]
    # Placeholder: echo the test input (wrong for real ARC — replace me).
    return test_input


def main() -> None:
    try:
        task = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"invalid stdin JSON: {exc}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(task, dict) or "test" not in task:
        print("stdin must be a wire-contract task object", file=sys.stderr)
        sys.exit(2)

    try:
        grid = solve_locally(task)
    except Exception as exc:  # noqa: BLE001 — surface to harness as execution_error
        print(f"solver failed: {exc}", file=sys.stderr)
        sys.exit(1)

    json.dump({"prediction": grid}, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()

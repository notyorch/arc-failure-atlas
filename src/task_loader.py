"""
Task ingestion for the evaluation stage — solver-agnostic.

Loads the normalized tasks Parquet written by the ETL (src/main.py),
reconstructs ARC task structures (train pairs + test inputs), and flattens
them into one evaluation item per (task, test example). Solver adapters
receive these items as their input contract; nothing here knows about
prompts, providers, or any particular solver family.

Ground-truth isolation: expected outputs ride along on each item ONLY for
the scoring stage (and the deterministic mock backend). Solver adapters
must never serialize them to an external solver — see SolverTask.to_wire()
in src/solvers.py.

Benchmark pack metadata (pack_id, benchmark_*, split_name, task_source) is
copied onto every evaluation item so run_evaluation can stamp result rows
and manifests without re-resolving the pack (unless overridden via CLI).
"""

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from benchmark_packs import (
    BENCHMARK_METADATA_FIELDS,
    BenchmarkPack,
    metadata_for_evaluation_items,
)
from contracts import require_etl_columns

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASKS_PARQUET = REPO_ROOT / "data" / "parquet" / "evaluation"


def load_tasks_dataframe(parquet_dir: Path = DEFAULT_TASKS_PARQUET) -> pd.DataFrame:
    """Loads the tasks Parquet and fails fast if the ETL contract is not met."""
    if not Path(parquet_dir).exists():
        raise FileNotFoundError(
            f"Tasks Parquet not found at {parquet_dir}. Run the ETL first:\n"
            "    python scripts/fetch_arc_data.py --sample   (or --limit N)\n"
            "    python src/main.py\n"
            "    # or: python src/main.py --benchmark-pack example_local_pack"
        )
    df = pd.read_parquet(parquet_dir, engine="pyarrow")
    require_etl_columns(df)
    return df


def reconstruct_tasks(df: pd.DataFrame) -> list:
    """
    Rebuilds task structures from long-format rows (one row per grid):

        {"task_id": str, "source_path": str,
         "train": [{"input": grid, "output": grid}, ...],
         "test":  [{"example_id": int, "input": grid, "output": grid|None}, ...]}

    Ordered by task_id, examples by example_id — deterministic run order.
    """
    tasks = []
    for task_id, task_df in df.groupby("task_id", sort=True, observed=True):
        grids = {}
        for row in task_df.itertuples(index=False):
            key = (str(row.split), int(row.example_id), str(row.grid_role))
            grids[key] = json.loads(row.grid_2d)

        train_ids = sorted({k[1] for k in grids if k[0] == "train"})
        test_ids = sorted({k[1] for k in grids if k[0] == "test"})

        tasks.append({
            "task_id": str(task_id),
            "source_path": str(task_df["source_path"].iloc[0]),
            "train": [
                {
                    "input": grids.get(("train", eid, "input")),
                    "output": grids.get(("train", eid, "output")),
                }
                for eid in train_ids
            ],
            "test": [
                {
                    "example_id": eid,
                    "input": grids.get(("test", eid, "input")),
                    # None when the ground truth is hidden (competition-style)
                    "output": grids.get(("test", eid, "output")),
                }
                for eid in test_ids
            ],
        })
    return tasks


def build_evaluation_items(
    tasks: list,
    benchmark_meta: Optional[dict] = None,
) -> list:
    """
    Flattens tasks into one evaluation item per (task_id, test example):

        {"task_id", "test_example_id", "train" (clean pairs),
         "test_input", "expected_output" (grid | None),
         "source_task_partition", + optional benchmark pack fields}

    Tasks without train examples or without a test input are skipped —
    there is nothing meaningful to ask a solver.
    """
    meta = dict(benchmark_meta or {})
    items = []
    for task in tasks:
        train = [
            ex for ex in task["train"]
            if ex["input"] is not None and ex["output"] is not None
        ]
        if not train:
            continue
        for test_example in task["test"]:
            if test_example["input"] is None:
                continue
            item = {
                "task_id": task["task_id"],
                "test_example_id": test_example["example_id"],
                "train": train,
                "test_input": test_example["input"],
                "expected_output": test_example["output"],
                "source_task_partition":
                    f"split=test/task_id={task['task_id']}",
            }
            for key in BENCHMARK_METADATA_FIELDS:
                if key in meta:
                    item[key] = meta[key]
            items.append(item)
    return items


def load_evaluation_items(
    parquet_dir: Path = DEFAULT_TASKS_PARQUET,
    pack_override: Optional[BenchmarkPack] = None,
) -> tuple[list, dict]:
    """
    Convenience: load Parquet → reconstruct → items with pack metadata.

    Returns (items, benchmark_meta).
    """
    df = load_tasks_dataframe(parquet_dir)
    meta = metadata_for_evaluation_items(df, parquet_dir, pack_override)
    items = build_evaluation_items(reconstruct_tasks(df), benchmark_meta=meta)
    return items, meta

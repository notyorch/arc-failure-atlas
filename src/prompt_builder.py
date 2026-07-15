"""
Deterministic prompt construction from the normalized tasks Parquet.

Reconstructs ARC task structures (train pairs + test inputs) from the
long-format rows written by the ETL, and renders the versioned prompt.
Same tasks Parquet + same prompt version ⇒ byte-identical prompts.

Prompt contract (arc_grid_v1): the model must reply with ONLY a JSON 2D
integer array — the parser in grid_parser.py is the other half of this
contract.
"""

import json
from pathlib import Path

import pandas as pd

from contracts import require_etl_columns
from grid_parser import serialize_grid

PROMPT_VERSION = "arc_grid_v1"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASKS_PARQUET = REPO_ROOT / "data" / "parquet" / "evaluation"

_PROMPT_HEADER = (
    "You are solving an ARC (Abstraction and Reasoning Corpus) puzzle.\n"
    "Each grid is a JSON 2D array of integers 0-9. Infer the transformation "
    "rule from the training examples, then apply it to the test input.\n"
)
_PROMPT_FOOTER = (
    "\nReply with ONLY the test output grid as a JSON 2D array of integers. "
    "No explanation, no code fences, no extra text."
)


def load_tasks_dataframe(parquet_dir: Path = DEFAULT_TASKS_PARQUET) -> pd.DataFrame:
    """Loads the tasks Parquet and fails fast if the ETL contract is not met."""
    if not Path(parquet_dir).exists():
        raise FileNotFoundError(
            f"Tasks Parquet not found at {parquet_dir}. Run the ETL first:\n"
            "    python scripts/fetch_arc_data.py --sample   (or --limit N)\n"
            "    python src/main.py"
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


def build_prompt(train_examples: list, test_input: list) -> str:
    """Renders the arc_grid_v1 prompt for one test input."""
    parts = [_PROMPT_HEADER]
    for i, example in enumerate(train_examples, start=1):
        parts.append(
            f"\nExample {i}\n"
            f"Input: {serialize_grid(example['input'])}\n"
            f"Output: {serialize_grid(example['output'])}\n"
        )
    parts.append(f"\nTest\nInput: {serialize_grid(test_input)}\n")
    parts.append(_PROMPT_FOOTER)
    return "".join(parts)


def build_inference_items(tasks: list) -> list:
    """
    Flattens tasks into one inference item per (task_id, test example):

        {"task_id", "test_example_id", "prompt", "test_input",
         "expected_output" (grid | None), "source_task_partition"}

    Tasks without train examples or without a test input are skipped —
    there is nothing meaningful to ask the model.
    """
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
            items.append({
                "task_id": task["task_id"],
                "test_example_id": test_example["example_id"],
                "prompt": build_prompt(train, test_example["input"]),
                "test_input": test_example["input"],
                "expected_output": test_example["output"],
                "source_task_partition":
                    f"split=test/task_id={task['task_id']}",
            })
    return items

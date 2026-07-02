"""
Shows how to load the normalized ARC-AGI Parquet dataset and reconstruct
the task structure needed to build inference prompts.

Parquet location : data/parquet/evaluation/
Partition layout : split=<train|test> / task_id=<id> / *.parquet
Schema key fields:
    task_id            str   – ARC task identifier (derived from filename)
    split              str   – "train" | "test"  (within a single task file)
    example_id         int   – 1-based index of the example inside the split
    grid_role          str   – "input" | "output"
    grid_2d            str   – JSON-serialized 2D list  → json.loads() to use
    grid_flat          str   – JSON-serialized 1D list  → json.loads() to use
    rows / cols        int   – grid dimensions
    grid_hash          str   – MD5 of the grid content (for dedup / scoring)
    source_path        str   – original JSON file path (traceability)
    transformation_type str  – NULL at ingestion; filled by analysis module
    pipeline_version   str   – ETL version that produced this row
    ingested_at        str   – UTC ISO-8601 timestamp
"""

import json
import pandas as pd
from pathlib import Path

# Anchored to repo root — works regardless of shell cwd (e.g. Jupyter in notebooks/).
REPO_ROOT   = Path(__file__).resolve().parent.parent
PARQUET_DIR = REPO_ROOT / "data" / "parquet" / "evaluation"


# 1. LOAD THE FULL DATASET 

df = pd.read_parquet(PARQUET_DIR, engine="pyarrow")

print("Total rows   :", len(df))
print("Tasks        :", df["task_id"].nunique())
print("Columns      :", df.columns.tolist())
print()


# 2. LIST AVAILABLE TASKS 

task_ids = sorted(df["task_id"].unique())
print("Available tasks:", task_ids)
print()


# 3. RECONSTRUCT A SINGLE TASK FOR PROMPT BUILDING 
#
# Each task has:
#   - N train examples (input + output pairs)  → used as few-shot context
#   - 1 test example  (input only*)            → the grid the model must solve
#
# *In the evaluation set the test output IS present (ground truth for scoring).
#  In the hidden competition set it would be absent.

def load_task(dataframe: pd.DataFrame, task_id: str) -> dict:
    """
    Returns a dict with the structure an inference function expects:

    {
        "task_id": "00576224",
        "source_path": "data/raw/evaluation/00576224.json",
        "train": [
            {"input": [[...]], "output": [[...]]},
            ...
        ],
        "test": [
            {"input": [[...]], "output": [[...]]}   # output = None if hidden
        ]
    }
    """
    task_df = dataframe[dataframe["task_id"] == task_id].copy()

    def get_grid(split, example_id, role):
        rows = task_df[
            (task_df["split"] == split) &
            (task_df["example_id"] == example_id) &
            (task_df["grid_role"] == role)
        ]
        if rows.empty:
            return None
        return json.loads(rows.iloc[0]["grid_2d"])

    train_ids = sorted(task_df[task_df["split"] == "train"]["example_id"].unique())
    test_ids  = sorted(task_df[task_df["split"] == "test"]["example_id"].unique())

    source_path = task_df["source_path"].iloc[0]

    return {
        "task_id":     task_id,
        "source_path": source_path,
        "train": [
            {"input": get_grid("train", eid, "input"),
             "output": get_grid("train", eid, "output")}
            for eid in train_ids
        ],
        "test": [
            {"input":  get_grid("test", eid, "input"),
             "output": get_grid("test", eid, "output")}  # None if hidden set
            for eid in test_ids
        ],
    }


task = load_task(df, task_ids[0])

print("task_id     :", task["task_id"])
print("source_path :", task["source_path"])
print("train examples:", len(task["train"]))
print("test  examples:", len(task["test"]))
print()
print("Train example 1 input :", task["train"][0]["input"])
print("Train example 1 output:", task["train"][0]["output"])
print()
print("Test  example 1 input :", task["test"][0]["input"])
print("Test  example 1 output:", task["test"][0]["output"], " (ground truth - evaluation set)")


# 4. ITERATE ALL TASKS (inference loop skeleton) 

print("\n--All tasks summary --")
for tid in task_ids:
    t = load_task(df, tid)
    n_train = len(t["train"])
    n_test  = len(t["test"])
    print("  %s  |  %d train examples  |  %d test example(s)" % (tid, n_train, n_test))


# 5. QUICK FILTER EXAMPLES 

# Only test inputs (the grids the model must predict)
test_inputs = df[(df["split"] == "test") & (df["grid_role"] == "input")]
print("\nTest inputs available:", len(test_inputs))

# Tasks with large grids (rows >= 10) — may need special prompt handling
large_grid_tasks = df[df["rows"] >= 10]["task_id"].unique()
print("Tasks with grids >= 10 rows:", list(large_grid_tasks))

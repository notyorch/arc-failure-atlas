"""
Data contracts between pipeline stages.

The tasks Parquet schema stays frozen in `src/main.py` (TASKS_PARQUET_SCHEMA)
and is NOT redefined here. This module declares:

  1. ETL_REQUIRED_COLUMNS       — the subset of task columns the evaluation
                                  stage reads (a consumer contract).
  2. EVALUATION_RESULTS_SCHEMA  — frozen schema of solver evaluation rows
                                  (one row per run × task × test example ×
                                  attempt). Version 2.0.0 — solver-oriented.
  3. Analytics column sets      — metric columns every summary table must carry.
  4. validate_columns()         — the same strict guard style as
                                  `validate_output_schema` in main.py.
  5. LEGACY_INFERENCE_SCHEMA_V1 — the 28-column v1 layout, kept ONLY so the
                                  analytics loader can upgrade pre-platform
                                  runs already on disk (see build_analytics).

Schema changes follow the process in agent_context/conventions/
schema_contracts.md (team approval + DECISIONS.md update). The v1 → v2
change is documented in src/DECISIONS.md Decision 17.
"""

import logging

import pandas as pd

# Version of the evaluation/analytics layer (independent of the ETL's 1.2.0).
EVALUATION_PIPELINE_VERSION = "0.3.0"

# Schema versions, stamped into run/build manifests (never as extra Parquet
# columns — the column sets below are frozen). Bump on any column addition,
# removal, rename, or semantic change:
#   MAJOR — breaking (remove/rename/retype), MINOR — additive, PATCH — docs.
EVALUATION_SCHEMA_VERSION = "2.1.0"  # + benchmark pack metadata (Decision 20)
ANALYTICS_SCHEMA_VERSION = "2.2.0"   # + n_tasks / task_solved_rate (ARC-official
                                     #   task-level pass@k)

# Columns the evaluation stage requires from data/parquet/evaluation/.
# Reading fails fast if any is missing (protects against upstream drift).
# Benchmark pack columns are OPTIONAL on read (legacy Parquets); evaluation
# fills them from the pack sidecar or UNKNOWN_META (see benchmark_packs.py).
ETL_REQUIRED_COLUMNS = [
    "task_id",
    "split",
    "example_id",
    "grid_role",
    "grid_2d",
    "source_path",
]

# Stamped end-to-end when ETL/evaluation run under a resolved pack
# (also present on tasks Parquet from ETL v1.2.0+).
BENCHMARK_METADATA_COLUMNS = [
    "pack_id",
    "benchmark_family",
    "benchmark_name",
    "benchmark_version",
    "split_name",
    "task_source",
]

# Execution modes a solver adapter may declare (stored per row + manifest).
EXECUTION_MODES = [
    "in_process", "subprocess", "http", "submission_file", "submission_dir",
]

# FROZEN SCHEMA v2.0.0 — solver evaluation results Parquet (from 2026-07-15)
# One row per (run_id, task_id, test_example_id, attempt).
# nullable=True means NULL is meaningful (e.g. no parse, no ground truth,
# or a field that only applies to some solver families).
EVALUATION_RESULTS_SCHEMA = {
    # Run identity
    "run_id":                    {"nullable": False},
    "experiment_id":             {"nullable": False},
    # Solver identity — every solver family fills these
    "solver_name":               {"nullable": False},
    "solver_family":             {"nullable": False},  # e.g. llm_direct, dsl_search
    "solver_version":            {"nullable": False},  # "unversioned" when unknown
    "execution_mode":            {"nullable": False},  # see EXECUTION_MODES
    "pipeline_version":          {"nullable": False},
    # LLM-family lineage — NULL for non-LLM solvers
    "provider":                  {"nullable": True},
    "model_name":                {"nullable": True},
    "prompt_version":            {"nullable": True},
    # Task identity / lineage
    "task_id":                   {"nullable": False},
    "split":                     {"nullable": False},
    "test_example_id":           {"nullable": False},
    "source_task_partition":     {"nullable": False},
    # Benchmark pack pin (Decision 20) — always stamped; legacy upgrades use
    # "unknown" / legacy_raw_dir defaults via normalize_evaluation_frame.
    "pack_id":                   {"nullable": False},
    "benchmark_family":          {"nullable": False},
    "benchmark_name":            {"nullable": False},
    "benchmark_version":         {"nullable": False},
    "split_name":                {"nullable": False},  # pack split, not train/test
    "task_source":               {"nullable": False},
    # Attempt index (1-based; Kaggle-style submissions carry up to 2).
    # Computational metrics (latency/cost/tokens) are stamped on attempt 1
    # of each item; further attempts carry 0.0 / NULL so sums stay correct.
    "attempt":                   {"nullable": False},
    # Request / response payloads
    "prompt_text":               {"nullable": True},   # llm_direct only
    "raw_output":                {"nullable": True},   # NULL on execution_error
    "predicted_grid_json":       {"nullable": True},   # NULL unless parse ok
    "expected_output_grid_json": {"nullable": True},   # NULL on hidden sets
    # Execution outcome
    "status":                    {"nullable": False},  # ok | error
    "error_message":             {"nullable": True},
    "latency_ms":                {"nullable": False},  # harness wall clock per item
    "cost_estimate_usd":         {"nullable": False},
    "input_tokens":              {"nullable": True},   # when the backend reports usage
    "output_tokens":             {"nullable": True},
    "started_at":                {"nullable": False},
    "finished_at":               {"nullable": False},
    # Parsing outcome
    "parse_status":              {"nullable": False},  # see grid_parser.py
    "parse_error":               {"nullable": True},
    # Evaluation (NULL when no valid prediction or no ground truth)
    "is_exact_match":            {"nullable": True},
    "same_shape":                {"nullable": True},
    "cell_accuracy":             {"nullable": True},
    "n_diff_cells":              {"nullable": True},
    # Failure taxonomy v2 (NULL only when the row is not classifiable at all,
    # i.e. valid prediction but no ground truth to compare against)
    "failure_mode":              {"nullable": True},
    "failure_detail":            {"nullable": True},
    # Free-form solver extras (JSON string): seed, search depth, program
    # found, backend internals... — extensible without schema churn.
    "solver_metadata":           {"nullable": True},
}

# The retired v1 layout (model/provider-oriented, single attempt). Kept ONLY
# so build_analytics can upgrade old local runs in place when reading; new
# writes always use EVALUATION_RESULTS_SCHEMA. Do not extend.
LEGACY_INFERENCE_SCHEMA_V1 = [
    "run_id", "experiment_id", "provider", "model_name", "prompt_version",
    "pipeline_version", "task_id", "split", "test_example_id",
    "source_task_partition", "prompt_text", "response_text",
    "predicted_grid_json", "expected_output_grid_json", "status",
    "error_message", "latency_ms", "cost_estimate_usd", "started_at",
    "finished_at", "parse_status", "parse_error", "is_exact_match",
    "same_shape", "cell_accuracy", "n_diff_cells", "failure_mode",
    "failure_detail",
]

# Metric columns every analytics summary table must include, in addition to
# its grouping key(s). Kept as a list so build_analytics can enforce it.
#   n_items          — distinct (run, task, test_example) items in the group
#   n_tasks          — distinct (run, task) tasks in the group
#   n_attempts       — result rows (attempts) in the group
#   exact_match_rate — attempt-level: exact rows / ALL rows
#   solved_rate      — item-level pass@k: a test example counts as solved when
#                      ANY of its attempts is an exact match
#   task_solved_rate — ARC-official granularity: a task counts as solved only
#                      when EVERY one of its test examples is solved (pass@k
#                      applied per test example, then AND-ed across the task)
ANALYTICS_METRIC_COLUMNS = [
    "n_items",
    "n_tasks",
    "n_attempts",
    "n_evaluable",
    "exact_match_rate",
    "solved_rate",
    "task_solved_rate",
    "avg_cell_accuracy",
    "avg_latency_ms",
    "total_cost_estimate_usd",
    "parse_error_rate",
    "shape_error_rate",
]


def validate_columns(dataframe: pd.DataFrame, schema: dict, label: str) -> None:
    """
    Strict column guard, same contract as validate_output_schema in main.py:
      1. No unexpected columns.
      2. No missing columns.
      3. Non-nullable columns contain no NULLs.
    Raises ValueError before bad data can reach disk.
    """
    expected = set(schema.keys())
    actual = set(dataframe.columns)

    errors = []
    extra = actual - expected
    missing = expected - actual
    if extra:
        errors.append(f"Unexpected columns: {sorted(extra)}")
    if missing:
        errors.append(f"Missing columns: {sorted(missing)}")
    if errors:
        raise ValueError(
            f"[{label}] Schema violation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    for col, rules in schema.items():
        if not rules["nullable"] and dataframe[col].isnull().any():
            null_count = int(dataframe[col].isnull().sum())
            errors.append(f"Column '{col}' is non-nullable but has {null_count} NULL(s)")

    if errors:
        raise ValueError(
            f"[{label}] Schema violation:\n" + "\n".join(f"  - {e}" for e in errors)
        )

    logging.info(
        "[%s] Schema validation passed (%d columns, %d rows).",
        label, len(actual), len(dataframe),
    )


def require_etl_columns(dataframe: pd.DataFrame) -> None:
    """Fail fast if the tasks Parquet lacks a column the evaluation stage reads."""
    missing = [c for c in ETL_REQUIRED_COLUMNS if c not in dataframe.columns]
    if missing:
        raise ValueError(
            f"Tasks Parquet is missing columns required by evaluation: {missing}. "
            "Regenerate it with `python src/main.py` (ETL v1.2.0+)."
        )

"""
Data contracts between pipeline stages.

The tasks Parquet schema stays frozen in `src/main.py` (TASKS_PARQUET_SCHEMA)
and is NOT redefined here. This module declares:

  1. ETL_REQUIRED_COLUMNS   — the subset of task columns the inference stage
                              reads (a consumer contract, not a new schema).
  2. INFERENCE_PARQUET_SCHEMA — frozen schema of inference result rows
                              (one row per task_id + test example).
  3. Analytics column sets  — metric columns every summary table must carry.
  4. validate_columns()     — the same strict guard style as
                              `validate_output_schema` in main.py, kept here
                              so the frozen ETL module is never modified.

Schema changes follow the process in agent_context/conventions/
schema_contracts.md (team approval + DECISIONS.md update).
"""

import logging

import pandas as pd

# Version of the inference/analytics layer (independent of the ETL's 1.1.0).
INFERENCE_PIPELINE_VERSION = "0.1.0"

# Columns the inference stage requires from data/parquet/evaluation/.
# Reading fails fast if any is missing (protects against upstream drift).
ETL_REQUIRED_COLUMNS = [
    "task_id",
    "split",
    "example_id",
    "grid_role",
    "grid_2d",
    "source_path",
]

# FROZEN SCHEMA — inference results Parquet (effective from 2026-07-15)
# One row per (run_id, task_id, test_example_id).
# nullable=True means NULL is meaningful (e.g. no parse, no ground truth).
INFERENCE_PARQUET_SCHEMA = {
    # Run identity
    "run_id":                    {"nullable": False},
    "experiment_id":             {"nullable": False},
    "provider":                  {"nullable": False},
    "model_name":                {"nullable": False},
    "prompt_version":            {"nullable": False},
    "pipeline_version":          {"nullable": False},
    # Task identity / lineage
    "task_id":                   {"nullable": False},
    "split":                     {"nullable": False},
    "test_example_id":           {"nullable": False},
    "source_task_partition":     {"nullable": False},
    # Request / response payloads
    "prompt_text":               {"nullable": False},
    "response_text":             {"nullable": True},   # NULL on api_error
    "predicted_grid_json":       {"nullable": True},   # NULL unless parse ok
    "expected_output_grid_json": {"nullable": True},   # NULL on hidden sets
    # Provider call outcome
    "status":                    {"nullable": False},  # ok | error
    "error_message":             {"nullable": True},
    "latency_ms":                {"nullable": False},
    "cost_estimate_usd":         {"nullable": False},
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
    # Failure taxonomy v1 (NULL only when the row is not classifiable at all,
    # i.e. valid prediction but no ground truth to compare against)
    "failure_mode":              {"nullable": True},
    "failure_detail":            {"nullable": True},
}

# Metric columns every analytics summary table must include, in addition to
# its grouping key(s). Kept as a list so build_analytics can enforce it.
ANALYTICS_METRIC_COLUMNS = [
    "total_runs",
    "exact_match_rate",
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
    """Fail fast if the tasks Parquet lacks a column the inference stage reads."""
    missing = [c for c in ETL_REQUIRED_COLUMNS if c not in dataframe.columns]
    if missing:
        raise ValueError(
            f"Tasks Parquet is missing columns required by inference: {missing}. "
            "Regenerate it with `python src/main.py` (ETL v1.1.0+)."
        )

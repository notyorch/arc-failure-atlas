# Schema Contracts

**Last updated:** July 15, 2026  
**Pipeline version:** 1.1.0  
**Code source of truth:** `TASKS_PARQUET_SCHEMA` in `src/main.py` · `INFERENCE_PARQUET_SCHEMA` in `src/contracts.py`

## Current State
The base ETL (`src/main.py`) enforces a **frozen tasks Parquet schema** declared as `TASKS_PARQUET_SCHEMA` and validated by `validate_output_schema()` before any write to disk. Column additions, removals, or renames require team approval and updates to this file, `TASKS_PARQUET_SCHEMA`, and `src/DECISIONS.md`.

Authoritative type rationale and design decisions live in `src/DECISIONS.md` (Decision 2 and Decision 5).

> This document supersedes the pre–June 2026 draft that listed Spanish column names (`id_tarea`, `matriz_plana`, etc.) and referenced a removed script path.
### ACTUAL: Tasks Parquet schema (normalized grids)
One row per grid. Fifteen columns:

| Column | Nullable | Notes |
| --- | --- | --- |
| `task_id` | No | Derived from JSON filename stem (e.g. `00576224`). Hive partition key. |
| `split` | No | `train` or `test`. Hive partition key. |
| `example_id` | No | 1-based index within the split. |
| `grid_role` | No | `input` or `output`. |
| `rows` | No | Grid height. |
| `cols` | No | Grid width. |
| `grid_2d` | No | Full 2D matrix as JSON string. Deserialize with `json.loads()`. |
| `grid_flat` | No | Linearized grid as JSON string. |
| `grid_hash` | No | MD5 hex digest of serialized grid content. |
| `n_colors` | No | Count of distinct color values in the grid. |
| `color_counts` | No | Per-color frequency as JSON string (keys are strings). |
| `transformation_type` | Yes | `NULL` at ingestion; filled by analysis module later. |
| `source_path` | No | Repo-relative POSIX path to source JSON (e.g. `data/raw/evaluation/00576224.json`). |
| `pipeline_version` | No | ETL semantic version (e.g. `1.1.0`). |
| `ingested_at` | No | UTC ISO-8601 timestamp from source file mtime (not `datetime.now()`). |

### ACTUAL: Partition layout
```
data/parquet/evaluation/
  split=train/
    task_id=<task_id>/part-*.parquet
  split=test/
    task_id=<task_id>/part-*.parquet
```

Partition order is `split` → `task_id` (see `src/DECISIONS.md`, Decision 4).

### ACTUAL: Error Parquet schema
Written to `data/parquet/evaluation_errors/` with the same Hive partition layout. Only written when validation errors exist.

| Column | Notes |
| --- | --- |
| `task_id` | Task identifier. |
| `split` | `train` or `test`. |
| `example_id` | 1-based example index. |
| `grid_role` | `input` or `output`. |
| `error` | Validation error message. |
| `source_path` | Repo-relative POSIX path to source JSON. |
| `ingested_at` | UTC ISO-8601 from source file mtime. |

The error schema is **not** validated by `TASKS_PARQUET_SCHEMA` (separate shape by design).

### ACTUAL: Quality text log
- Path: `logs/quality_<timestamp>.log`
- Logger: `arc.quality` at `WARNING` level.
- Content: human-readable validation failures, one line per rejected grid.

### Current behavior
- Schema is explicit and enforced before writing valid rows.
- `output=None` in the `test` split is valid (no row generated); in `train` it is logged as an error.
- Grids are stored as JSON strings (`grid_2d`, `grid_flat`), not native Parquet lists.
- `source_path` uses forward slashes regardless of host OS.
- Batch ingestion continues when individual files fail (malformed JSON, etc.).

## Additional Schemas

### 1. Raw Task Schema
Source: ARC-AGI JSON task files.
Expected content:
- task id or file-derived identifier
- train examples
- test examples
- input/output grids
- any source metadata if available

*Status: consumed directly by the ETL; no separate raw-layer Parquet yet.*

### 2. Inference Result Schema — IMPLEMENTED July 15, 2026

**Source of truth:** `INFERENCE_PARQUET_SCHEMA` in `src/contracts.py` (frozen, 28 columns).
One row per `(run_id, task_id, test_example_id)`, written to
`data/parquet/inference/runs/<run_id>/part-NNNN.parquet` (plain directory
names, not Hive — `run_id` stays a physical column; see `src/DECISIONS.md`
Decision 10). Enforced by `contracts.validate_columns()` before every write.

Column groups:

| Group | Columns |
| --- | --- |
| Run identity | `run_id`, `experiment_id`, `provider`, `model_name`, `prompt_version`, `pipeline_version` |
| Task lineage | `task_id`, `split`, `test_example_id`, `source_task_partition` |
| Payloads | `prompt_text`, `response_text`, `predicted_grid_json`, `expected_output_grid_json` |
| Provider outcome | `status` (`ok`/`error`), `error_message`, `latency_ms`, `cost_estimate_usd`, `started_at`, `finished_at` |
| Parsing | `parse_status` (`ok`/`empty_response`/`no_json_array`/`invalid_grid`/`not_attempted`), `parse_error` |
| Evaluation | `is_exact_match`, `same_shape`, `cell_accuracy`, `n_diff_cells` (NULL when not evaluable — never 0) |
| Taxonomy | `failure_mode`, `failure_detail` |

### 3. Failure Taxonomy — IMPLEMENTED July 15, 2026 (v1, embedded)

Implemented as the `failure_mode` / `failure_detail` columns of the
inference schema (not a separate table): one deterministic label per row
from `src/failure_taxonomy.py` — `exact_match`, `api_error`,
`empty_response`, `parse_error`, `shape_error`, `spatial_error`,
`symbol_error`, `unknown_error`; NULL when a valid prediction has no ground
truth. Rule ordering and heuristics: `src/DECISIONS.md` Decision 11.
A separate human-labeled taxonomy table (labeler, evidence, subcategory)
remains future work.

### 4. Analytics Summary Tables — IMPLEMENTED July 15, 2026

Derived layer, fully rebuilt by `src/build_analytics.py` under
`data/parquet/analytics/`: `fact_inference_results/` (Hive-partitioned by
`provider`/`model_name`), `summary_by_model/`, `summary_by_failure_mode/`,
`summary_by_task/`. Every summary carries at least
`ANALYTICS_METRIC_COLUMNS` (`src/contracts.py`): `total_runs`,
`exact_match_rate`, `avg_cell_accuracy`, `avg_latency_ms`,
`total_cost_estimate_usd`, `parse_error_rate`, `shape_error_rate`.
Metric definitions: `src/DECISIONS.md` Decision 12.

## Schema Change Process
To add a column to the tasks Parquet legitimately:
1. Get team approval.
2. Update `TASKS_PARQUET_SCHEMA` in `src/main.py`.
3. Update Decision 2 type map in `src/DECISIONS.md`.
4. Update this file.
5. Regenerate Parquet and confirm `validate_output_schema()` passes.

## Validation Expectations (implemented for tasks Parquet)
- Required fields are present (no missing columns).
- No unexpected columns (strict guard).
- Non-nullable columns contain no NULL values.
- Grid structure validated before row creation: null, empty, inconsistent dimensions, out-of-range values (0–9).
- Split values restricted to `train` / `test`.
- `grid_role` restricted to `input` / `output`.

## Assumptions
- ARC examples are small enough that JSON-serialized grids in string columns remain acceptable.
- Inference results and taxonomy schemas are implemented (see sections 2–4); a separate human-labeled failure table may come later.
- Partition keys (`split`, `task_id`; `provider`, `model_name` in analytics) remain encoded in directory paths; they also appear as columns when the full dataset is loaded with `pd.read_parquet()`.
- Inference run directories are intentionally NOT Hive-style so `run_id` remains a physical column in every part file.

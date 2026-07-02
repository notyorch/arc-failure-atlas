# Schema Contracts

**Last updated:** June 30, 2026  
**Pipeline version:** 1.1.0  
**Code source of truth:** `TASKS_PARQUET_SCHEMA` in `src/main.py`

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

## PROPUESTO: Schemas Not Yet Implemented

### 1. Raw Task Schema
Source: ARC-AGI JSON task files.
Expected content:
- task id or file-derived identifier
- train examples
- test examples
- input/output grids
- any source metadata if available

*Status: consumed directly by the ETL; no separate raw-layer Parquet yet.*

### 2. Inference Result Schema
One row per model prediction.
Recommended fields:
- `run_id`
- `task_id`
- `split`
- `example_index`
- `model_name`
- `prompt_version`
- `prediction`
- `latency_ms`
- `retry_count`
- `cost_usd`
- `status`
- `error_type`
- `created_at`

*Status: proposed. Deferred fields documented in `src/main.py` and `src/DECISIONS.md`.*

### 3. Failure Taxonomy Schema
One row per labeled failure.
Recommended fields:
- `run_id`
- `task_id`
- `model_name`
- `failure_category`
- `failure_subcategory`
- `evidence`
- `labeler`
- `labeled_at`

*Status: proposed.*

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
- The project will eventually need separate schemas for inference results and failure taxonomy.
- Partition keys (`split`, `task_id`) remain encoded in directory paths; they also appear as columns when the full dataset is loaded with `pd.read_parquet()`.

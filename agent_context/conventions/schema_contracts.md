# Schema Contracts

## Current State
There is no formal schema contract yet. The only concrete output shape in the repository is the DataFrame produced by `src/atlas_arc_failure/ingestion/main.py`.

### ACTUAL: Observed current output columns
From the current script, the output table includes:
- `id_tarea`
- `fase`
- `num_ejemplo`
- `tipo_grid`
- `filas`
- `columnas`
- `matriz_plana`

### Current behavior
- The schema is implicit, not validated.
- The script assumes `input` and `output` exist for each example.
- The script flattens each grid into a list and stores it in one column.
- The current code does not distinguish raw task metadata from transformed artifacts.

## PROPUESTO: Canonical Schemas
These are the minimum schemas the project should eventually formalize.

### 1. Raw Task Schema
Source: ARC-AGI JSON task files.
Expected content:
- task id or file-derived identifier
- train examples
- test examples
- input/output grids
- any source metadata if available

### 2. Normalized Grid Schema
One row per example/grid pair.
Recommended fields:
- `task_id`
- `split` (`train` or `test`)
- `example_index`
- `grid_role` (`input` or `output`)
- `rows`
- `columns`
- `cells_flat`
- `source_path`
- `ingested_at`

### 3. Inference Result Schema
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

### 4. Failure Taxonomy Schema
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

## PENDIENTE: Schema Definitions
- No schema file exists in `configs/` or `docs/schemas/`.
- No validation library enforces column shapes.
- No versioning strategy exists for schema changes.

## Validation Expectations
When these schemas are implemented, validation should check:
- required fields are present,
- field types are stable,
- grid dimensions match payload length,
- split values are restricted to known categories,
- nullable fields are intentional and documented.

## Assumptions
- ARC examples are small enough that flattening grids into list-valued cells remains acceptable for the first implementation.
- The project will eventually need separate schemas for raw, normalized, inference, and analytics layers.

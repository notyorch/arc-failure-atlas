# Current Priorities

## Completed (base ETL slice — June 2026)
- Batch folder ingestion (`process_folder`) with per-file error tolerance.
- Grid validation with train/test conditional rules and dual error output (text log + Parquet).
- Frozen tasks Parquet schema (`TASKS_PARQUET_SCHEMA`) enforced before write.
- Hive partitioning by `split` → `task_id`.
- `source_path` traceability with POSIX-normalized repo-relative paths.
- Bit-reproducible `ingested_at` from source file mtime.
- Technical decisions documented in `src/DECISIONS.md`.
- Inference input reader snippet in `notebooks/inference_input_reader.py`.

## Priority 1: Scale ingestion to full evaluation set
Populate `data/raw/evaluation/` with all ~400 ARC-AGI evaluation tasks and run the ETL end to end. Confirm output volume, partition layout, and quality logs at scale.

## Priority 2: Package structure and CLI
Split `src/main.py` into importable modules and expose a CLI entrypoint. Keep the frozen schema guard and partitioning behavior unchanged during the refactor.

## Priority 3: Inference results schema
Define and enforce the inference output Parquet schema (model, prompt version, prediction, latency, cost, status). Document it in `schema_contracts.md` and `src/DECISIONS.md`.

## Priority 4: First inference runs
Connect one or more model providers. Use `notebooks/inference_input_reader.py` (or its extracted module) to build prompts from normalized tasks.

## Priority 5: Tests and fixtures
Add unit tests for JSON parsing, grid validation, schema guard, and partitioning. Include representative ARC task fixtures (valid train/test, missing test output, malformed grids).

## Priority 6: Version prompts and evaluation sets
The `prompts/` tree exists as scaffolding, but there is no versioned prompt registry yet. That work is required before model comparison becomes reliable.

## Priority 7: Failure taxonomy
Implement the failure labeling schema and initial category set for comparative analysis across models.

## Current Bottlenecks
- No package structure with importable modules and package initializers.
- No centralized configuration for models or environments.
- No documented taxonomy implementation.
- No inference orchestration code yet.

## Near-Term Outcome
The repository should reach a state where a developer or CLI agent can run inference on normalized ARC tasks, persist results in a documented Parquet schema, and trace every prediction back to its source task and prompt version.

## Exit Criteria for Next Slice (inference)
- Normalized tasks Parquet loaded for all evaluation tasks.
- At least one model provider connected with retry and latency capture.
- Inference results written to a documented, validated Parquet schema.
- Each result row traceable to `task_id`, `source_path`, model, and prompt version.

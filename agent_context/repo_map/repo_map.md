# Repository Map

## Root Files
- `README.md`: project statement and intended pipeline description.
- `LICENSE`: placeholder text (`TBD`) at the moment.
- `.gitignore`: ignores `data/`, Python bytecode, and local virtual environments.
- `.env.example`: only contains a placeholder comment so far.
- `pyproject.toml`: minimal setuptools project metadata.
- `requirements.txt`: runtime dependencies for the ETL (`pandas`, `numpy`, `pyarrow`, `duckdb`).
- `Makefile`: only a placeholder `help` target.
- `docker-compose.yml`: empty `services` object.

## Source Tree
- `src/main.py`: base ETL implementation (pipeline version `1.1.0`). Reads ARC-AGI JSON tasks from a folder, validates grids, transforms to long-format rows, enforces a frozen Parquet schema, and writes Hive-partitioned output.
- `src/DECISIONS.md`: technical decision log for the ETL (schema types, partitioning, reproducibility, quality logging). Authoritative companion to `main.py`.
- `src/SESION_2026-06-29.md`: session notes from the June 29, 2026 ETL sprint (working context, not a permanent spec).

## Notebooks
- `notebooks/inference_input_reader.py`: reference snippet for loading the partitioned Parquet dataset and reconstructing task structures for prompt building.

## Data Layout (gitignored, created at runtime)
- `data/raw/evaluation/`: ARC-AGI evaluation JSON task files (one file per task).
- `data/parquet/evaluation/`: Hive-partitioned normalized tasks Parquet (`split=<train|test>/task_id=<id>/`).
- `data/parquet/evaluation_errors/`: Hive-partitioned validation error records (same partition layout; written only when errors exist).
- `logs/quality_<timestamp>.log`: per-run text log of grid validation failures (`arc.quality` logger).

## Prompt Scope
- Repo/project prompts live under the top-level `prompts/` tree.
- Agent documentation prompts live under `agent_context/prompts/`.
- These are related but distinct assets and should not be conflated during onboarding.

## Platform and Project Scaffolding
The repository currently contains the following empty or mostly empty top-level areas:
- `artifacts/`
- `configs/`
- `docs/`
- `orchestrations/`
- `paper/`
- `prompts/`
- `scripts/`
- `sql/`
- `tests/`

`agent_context/` and `notebooks/` are populated. `data/` and `logs/` exist on disk after running the ETL but are not tracked in git.

## Current Architectural Reality
The base ingestion pipeline is implemented as a single module (`src/main.py`) with clearly separated functions (extract, validate, transform, schema guard, storage, batch ingestion). It is not yet split into importable subpackages or exposed through a CLI.

What exists:
- Batch folder ingestion with per-file error tolerance.
- Grid validation with conditional train/test rules.
- Frozen tasks Parquet schema enforced before write.
- Hive partitioning by `split` → `task_id`.
- Dual quality output: text log + error Parquet.
- Bit-reproducible `ingested_at` from source file mtime.
- POSIX-normalized `source_path` for cross-platform portability.

What does not exist yet:
- Package layout with `__init__.py` files and importable modules.
- Canonical CLI entrypoint.
- Inference adapters, orchestration, or taxonomy modules.
- Tests and fixtures.
- Model/provider configuration files.
- Versioned prompt assets.

## Proposed Map for Next Iteration
A practical first split would be:
- `ingestion`: JSON loading, task parsing, and raw input handling.
- `validation`: grid and schema checks.
- `transforms`: normalization and tabular conversion.
- `storage`: Parquet persistence and artifact paths.
- `inference`: model execution and response capture.
- `observability`: logging, metrics, retries, and run metadata.
- `taxonomy`: failure labeling and analysis categories.
- `cli`: command-line entrypoints.

## Minimal Data Flow
1. Read ARC-AGI task JSON files from `data/raw/evaluation/`.
2. Validate each grid (structure, dimensions, ARC color range 0–9).
3. Transform to long-format rows (one row per grid).
4. Enforce `TASKS_PARQUET_SCHEMA` before any write.
5. Write Hive-partitioned Parquet to `data/parquet/evaluation/`.
6. Write validation errors to `logs/` (text) and `data/parquet/evaluation_errors/` (Parquet).
7. Feed the Parquet layer into inference and failure-mode analysis (not yet implemented).

## How to Run the ETL
From the repository root:

```bash
python src/main.py
```

Requires JSON files in `data/raw/evaluation/`. Output is written to `data/parquet/evaluation/`.

## Gaps to Track
- No package initializers (`__init__.py`) or installable module layout.
- No canonical CLI entrypoint (script invoked directly).
- No tests or fixtures.
- No inference results Parquet schema implemented yet.
- No model/provider configuration files.
- No versioned prompt assets.
- `agent_context/conventions/schema_contracts.md` documents the tasks schema; inference and taxonomy schemas remain proposed only.

# Project Overview

## Purpose
Atlas | Arc Failure is an infrastructure-first project for evaluating models on ARC-AGI, running inference at scale, storing outputs in Parquet, and analyzing failure modes. The repository is **not** a solver for ARC-AGI.

## Current State
The repository is in an early scaffolding stage.

What exists today:
- A root `README.md` that explains the project intent and pipeline at a high level.
- A minimal `pyproject.toml` with setuptools metadata.
- A root `.env.example`, `Makefile`, `docker-compose.yml`, `LICENSE`, and `.gitignore`.
- One Python script at `src/atlas_arc_failure/ingestion/main.py` that:
  - reads a JSON task,
  - flattens ARC grids into tabular rows,
  - writes a Parquet file.
- A `src/atlas_arc_failure/ingestion/requirements.txt` file listing `pandas`, `numpy`, `pyarrow`, and `duckdb`.
  - `ACTUAL`: this is a provisional dependency location and not the final layout; it sits outside `pyproject.toml` as a migration artifact.

What does not exist yet:
- A real package layout with importable modules and package initializers.
- A validated schema contract for the Parquet outputs.
- A CLI entrypoint, orchestration layer, or model adapters.
- Tests, fixtures, notebooks, and documented runbooks.
- Operational code for observability, prompt versioning, taxonomy classification, or artifact management.

## Proposed Direction
Build a reproducible pipeline that can:
- ingest ARC-AGI task JSON,
- validate and normalize grids,
- execute controlled inference across models,
- persist predictions and metadata in Parquet,
- and analyze failure modes with a stable taxonomy.

## Non-Goals
- Do not treat this repository as an ARC solver project.
- Do not optimize for benchmark leaderboard performance.
- Do not assume production maturity that is not present yet.

## Key Design Priorities
- Reproducibility of data and experiments.
- Explicit schema validation before persistence.
- Parquet-first storage for downstream analysis.
- Versioned prompts and model configurations.
- Measurable observability: latency, retries, cost, and run metadata.
- Failure taxonomy that is stable enough for comparative analysis.

## Assumptions
- The canonical work should live under `src/atlas_arc_failure/`.
- Root-level files should remain thin and declarative.
- `data/`, `artifacts/`, and `prompts/` are working areas, not source-of-truth code.
- Future command-line behavior should be exposed through `src/atlas_arc_failure/cli/` or an equivalent entrypoint package.

# Project Overview

## Purpose
Atlas | Arc Failure is an infrastructure-first project for evaluating models on ARC-AGI, running inference at scale, storing outputs in Parquet, and analyzing failure modes. The repository is **not** a solver for ARC-AGI.

## Current State
The base ingestion ETL is functional for batch processing of ARC-AGI evaluation tasks.

What exists today:
- A root `README.md` that explains the project intent and pipeline at a high level.
- A minimal `pyproject.toml` with setuptools metadata.
- Root `requirements.txt` listing `pandas`, `numpy`, `pyarrow`, and `duckdb`.
- A root `.env.example`, `Makefile`, `docker-compose.yml`, `LICENSE`, and `.gitignore`.
- `src/main.py` (pipeline version `1.1.0`) that:
  - reads all JSON tasks from `data/raw/evaluation/`,
  - validates and normalizes ARC grids into long-format rows,
  - enforces a frozen 15-column Parquet schema,
  - writes Hive-partitioned output to `data/parquet/evaluation/`,
  - logs validation errors to text and Parquet.
- `src/DECISIONS.md`: technical decision log for the ETL.
- `notebooks/inference_input_reader.py`: reference snippet for reconstructing tasks from Parquet for prompt building.
- `agent_context/`: shared documentation for agents and contributors.

What does not exist yet:
- A real package layout with importable modules and package initializers.
- A CLI entrypoint (ETL is run as `python src/main.py`).
- Inference adapters, orchestration layer, or model providers.
- Inference results Parquet schema.
- Tests, fixtures, and documented runbooks beyond the ETL.
- Operational code for taxonomy classification or experiment artifact management.

## Proposed Direction
Build a reproducible pipeline that can:
- ingest ARC-AGI task JSON,
- validate and normalize grids,
- execute controlled inference across models,
- persist predictions and metadata in Parquet,
- and analyze failure modes with a stable taxonomy.

The first slice (ingestion + normalized Parquet) is implemented. The next slices are inference orchestration and failure taxonomy.

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
- Pipeline code lives under `src/` for now.
- Root-level files should remain thin and declarative.
- `data/`, `artifacts/`, and `prompts/` are working areas, not source-of-truth code.
- Future command-line behavior should be exposed through a dedicated CLI entrypoint once the module layout is split.

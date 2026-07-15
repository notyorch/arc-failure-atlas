# ARC-AGI Failure Modes & Evaluation Pipeline

An end-to-end data engineering and evaluation pipeline for studying how local
and frontier LLMs behave on the ARC-AGI benchmark.

This project does **not** aim to solve ARC-AGI directly.
Its goal is to build the infrastructure needed to:

- ingest ARC-AGI tasks from JSON,
- normalize grids and task structures,
- run batched model inference across providers,
- parse, validate, and score model outputs,
- classify failures with a quantitative taxonomy,
- and store everything in Parquet for reproducible analysis.

The main question is:

> When models fail on ARC-AGI, **how** do they fail, **where** do they fail,
> and **what does it cost** to evaluate them?

## Current Architecture (implemented)

```
ARC-AGI JSON tasks                      data/raw/evaluation/*.json
        │  scripts/fetch_arc_data.py  (download or offline --sample)
        ▼
[1] ETL  src/main.py                    data/parquet/evaluation/
        │  frozen 15-column schema, Hive partitions split=/task_id=
        ▼
[2] Inference  src/run_inference.py     data/parquet/inference/runs/<run_id>/
        │  prompt_builder → provider (mock|openai|ollama) → grid_parser
        │  → evaluator → failure_taxonomy, incremental part-file flushes
        ▼
[3] Analytics  src/build_analytics.py   data/parquet/analytics/
        │  fact + summary tables         reports/mvp_report.md
        ▼
[4] Report / ad-hoc analysis (pandas, DuckDB, notebooks)
```

Module map (`src/`):

| Module | Responsibility |
| --- | --- |
| `main.py` | Base ETL (frozen schema, quality logs) — **source of truth** |
| `contracts.py` | Inference/analytics schemas + strict column guards |
| `prompt_builder.py` | Task reconstruction from Parquet + versioned prompt (`arc_grid_v1`) |
| `providers.py` | `mock` / `openai` / `ollama` providers (stdlib HTTP, no SDKs) |
| `grid_parser.py` | Extract + validate JSON grids from model text |
| `evaluator.py` | Exact match, shape, cell accuracy, diff cells |
| `failure_taxonomy.py` | Deterministic failure-mode classification (v1) |
| `run_inference.py` | Batch inference CLI |
| `build_analytics.py` | Analytics tables + markdown report |

## Setup

Requires Python ≥ 3.11.

```bash
pip install -r requirements.txt   # pandas, numpy, pyarrow, duckdb
```

(`duckdb` is optional — used for ad-hoc SQL exploration only; the pipeline
itself needs pandas + pyarrow.)

### Environment variables (only for real providers)

Copy `.env.example` and export what you need:

| Variable | Used by | Default |
| --- | --- | --- |
| `OPENAI_API_KEY` | `--provider openai` | — (required for openai) |
| `OPENAI_BASE_URL` | `--provider openai` | `https://api.openai.com/v1` |
| `OLLAMA_HOST` | `--provider ollama` | `http://localhost:11434` |

The **mock provider needs no credentials and no network** — the full
pipeline is demonstrable offline.

## Running the MVP end to end

All commands run from the repository root.

### 1. Get task data

```bash
# Download the first 20 ARC-AGI-1 evaluation tasks (network required)
python scripts/fetch_arc_data.py --limit 20

# ...or fully offline: copy the 6 bundled sample tasks
python scripts/fetch_arc_data.py --sample
```

### 2. Run the ETL

```bash
python src/main.py
```

Writes normalized grids to `data/parquet/evaluation/` and validation errors
to `data/parquet/evaluation_errors/` + `logs/quality_<ts>.log`.

### 3. Run inference

```bash
# Offline, deterministic, always works:
python src/run_inference.py --provider mock --model baseline --experiment-id mvp-demo

# Real providers (optional):
python src/run_inference.py --provider openai --model gpt-4o-mini --limit 20
python src/run_inference.py --provider ollama --model llama3 --limit 20

# Useful flags: --limit N | --task-id id1,id2 | --dry-run | --experiment-id X
```

Each run writes scored rows (28-column schema, see `src/contracts.py`) to
`data/parquet/inference/runs/<run_id>/part-NNNN.parquet`, flushed
incrementally so partial progress survives interruptions. Per-task provider
errors become `api_error` rows instead of aborting the batch.

### 4. Build analytics + report

```bash
python src/build_analytics.py            # add --experiment-id to filter
```

Rebuilds `data/parquet/analytics/` and regenerates `reports/mvp_report.md`
(metrics by model, failure-mode distribution, example failures).

## Output folder structure

```
data/
  raw/evaluation/                      ARC task JSON (gitignored)
  parquet/
    evaluation/                        normalized tasks (Hive: split=/task_id=)
    evaluation_errors/                 ETL validation rejects
    inference/runs/<run_id>/           one directory per inference run
    analytics/
      fact_inference_results/          cleaned fact table (Hive: provider/model)
      summary_by_model/
      summary_by_failure_mode/
      summary_by_task/
logs/quality_<timestamp>.log           ETL quality log
reports/mvp_report.md                  generated evaluation report
```

## Failure Taxonomy (v1)

Every scored row gets exactly one deterministic label
(`src/failure_taxonomy.py`):

| Mode | Meaning |
| --- | --- |
| `exact_match` | Prediction equals ground truth cell for cell |
| `api_error` | Provider call failed |
| `empty_response` | Empty/whitespace reply |
| `parse_error` | Text present, but no valid ARC grid extractable |
| `shape_error` | Valid grid, wrong dimensions |
| `spatial_error` | Right shape + right color histogram, cells misplaced |
| `symbol_error` | Right shape, wrong color histogram |
| `unknown_error` | Defensive fallback |

## Key Metrics

Captured per run and aggregated in `summary_by_*` tables: exact-match rate,
cell-level accuracy, latency, cost estimate, parse/shape error rates.
Definitions live in `src/DECISIONS.md` (Decision 12).

## Known Limitations

- The `mock` provider is a deterministic pipeline-testing tool, **not** a
  scientific baseline; its numbers demonstrate the pipeline, not model skill.
- Cost estimates come from a static OpenAI price table (0.0 for mock/ollama).
- Taxonomy v1 is heuristic (histogram-based spatial/symbol split); finer
  categories (topological, quantitative...) are future work.
- Inference targets the `test` split only; `transformation_type` labeling of
  tasks is still a placeholder (`NULL`).
- No automated test suite yet — `tests/fixtures/` currently holds sample
  task data used by the offline mode.

## Repository Docs

- `docs/MVP_REMAINING_PLAN.md` — implementation plan for this MVP slice.
- `src/DECISIONS.md` — technical decision log (ETL + evaluation layers).
- `agent_context/` — shared conventions, schema contracts, repo map.

## License

TBD.

## Status

Working MVP: ETL → mock/real inference → scoring → failure taxonomy →
analytics tables → report, reproducible offline end to end.

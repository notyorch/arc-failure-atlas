# Current Priorities

**Last updated:** July 15, 2026

## Completed (base ETL slice — June 2026)
- Batch folder ingestion (`process_folder`) with per-file error tolerance.
- Grid validation with train/test conditional rules and dual error output (text log + Parquet).
- Frozen tasks Parquet schema (`TASKS_PARQUET_SCHEMA`) enforced before write.
- Hive partitioning by `split` → `task_id`.
- `source_path` traceability with POSIX-normalized repo-relative paths.
- Bit-reproducible `ingested_at` from source file mtime.
- Technical decisions documented in `src/DECISIONS.md`.
- Inference input reader snippet in `notebooks/inference_input_reader.py`.

## Completed (evaluation MVP slice — July 2026)
- Data bootstrap: `scripts/fetch_arc_data.py` (GitHub download with `--limit`, offline `--sample` fixtures under `tests/fixtures/sample_tasks/`).
- Inference results schema frozen and enforced (`INFERENCE_PARQUET_SCHEMA` in `src/contracts.py`, 28 columns) — closes former Priority 3.
- Provider abstraction: deterministic offline `mock`, optional `openai` / `ollama` via stdlib HTTP with latency + cost-estimate capture and one retry — closes former Priority 4.
- Versioned prompt (`arc_grid_v1` in `src/prompt_builder.py`) recorded on every row.
- Response grid parsing/validation (`src/grid_parser.py`), scoring (`src/evaluator.py`), failure taxonomy v1 (`src/failure_taxonomy.py`) — closes former Priority 7 (v1 scope).
- Batch runner `src/run_inference.py` (incremental flushes, per-task error tolerance, dry-run).
- Analytics layer `src/build_analytics.py` (fact + 3 summary tables) and generated `reports/mvp_report.md`.
- Docs updated: README, DECISIONS 8–13, schema contracts, `.env.example`, Makefile.
- Hardening: unit tests (34, stdlib unittest) for parser/evaluator/taxonomy; `scripts/smoke_test.py` (isolated end-to-end check); `_manifest.json` per run/build with git SHA + schema versions; `docs/REVIEW_CHECKLIST.md`.
- Demo readiness: `scripts/demo_bundle.py` / `make demo-bundle` — offline pipeline + CSV exports + 4 PNG charts + demo README assembled in `artifacts/demo/` (matplotlib added to requirements).

## Priority 1: Scale to the full evaluation set
Run `scripts/fetch_arc_data.py` (no `--limit`) for all ~400 evaluation tasks, then ETL + a full mock run. Confirm volume, partition layout, latency of `build_analytics.py`, and report readability at scale.

## Priority 2: Real-provider evaluation runs
**First real run done (July 15, 2026):** `z-ai/glm-5.2` via NVIDIA NIM
(OpenAI-compatible endpoint, `OPENAI_BASE_URL` override, zero code changes) —
26 tasks, 8 exact matches (30.8%), 0.776 avg cell accuracy, 0 parse errors,
~15.3 s avg latency. Report: `reports/real_run_glm52.md`. Observed: with
temperature 0, the hosted reasoning model is still nondeterministic across
runs (one task flipped exact↔symbol_error between two runs) — run lineage
matters. Remaining: more models/providers, full 400-task batches, and
sanity-checking cost estimates against actual billing.

## Priority 3: CI wiring and test expansion
Unit tests (parser/evaluator/taxonomy) and the end-to-end smoke test exist; wire them into CI (GitHub Actions running `make test` + `make smoke`), then extend coverage to schema guards and prompt_builder reconstruction.

## Priority 4: Package structure and CLI polish
Split `src/` into an importable package with `__init__.py` and console entry points. Keep frozen schema guards and partitioning behavior unchanged.

## Priority 5: Taxonomy v2 and transformation_type labeling
Refine spatial/symbol heuristics (topological, quantitative categories) and start filling the `transformation_type` column on tasks for accuracy-by-transformation analysis.

## Priority 6: Versioned prompt registry
Move beyond the single `PROMPT_VERSION` constant: a `prompts/` registry with one file per version and metadata linking prompt → runs.

## Current Bottlenecks
- No automated test suite (manual smoke verification only).
- No centralized model/provider configuration (env vars only).
- Mock provider dominates available results until real-provider runs are executed.

## Exit Criteria for Next Slice
- Full 400-task evaluation Parquet generated and ETL quality logs reviewed.
- At least one real-provider run persisted and compared against mock in the report.
- CI running `make test` + `make smoke` on every push.

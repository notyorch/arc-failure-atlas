# RUNBOOK — Manual Operations

Step-by-step instructions for the human team. Everything here is **manual by
design**: the repository contains no CI/CD that runs evaluations, and nothing
that calls external APIs on its own. Commands run from the repository root.

> Status note (July 16, 2026): platform v2 (solver judge, packs, analytics
> v2.2, Decision 21 scoring) is in the tree. **Verified offline:**
> `make test` (135 tests) and `make smoke`. **Manual pilots** documented in
> `reports/README.md`. Gemini/Claude live first-runs still on checklist (§4–5).

## 0. One-time setup

```bash
python --version                     # must be >= 3.11
pip install -r requirements.txt
```

Credentials: copy lines from `.env.example` and `export` them. The pipeline
never auto-loads `.env` files.

## 1. Sanity check the checkout (offline, no keys)

```bash
python -m unittest discover -s tests -v   # expect: OK
python scripts/smoke_test.py              # expect: "SMOKE PASS"
```

Smoke runs ETL → `mock-baseline` evaluation → analytics in a temp dir.

## 2. Offline end-to-end (mock solver)

```bash
python scripts/fetch_arc_data.py --sample
python src/main.py
python src/run_evaluation.py --list-solvers
python src/run_evaluation.py --solver mock-baseline --experiment-id mvp-demo
python src/build_analytics.py --experiment-id mvp-demo
```

Or via a registered pack (bundled fixtures):

```bash
python src/main.py --list-benchmark-packs
python src/main.py --benchmark-pack example_local_pack
python src/run_evaluation.py --solver mock-baseline --experiment-id pack-demo
python src/build_analytics.py --experiment-id pack-demo
```

Verify:

- Run `_manifest.json` has `"manifest_kind": "evaluation_run"`,
  `"status": "completed"`, nested `"solver"` with provider/prompt for LLM-direct,
  and a `"benchmark"` object (`pack_id`, `benchmark_name`, …).
- Tasks Parquet directory has `_benchmark_pack.json`.
- `data/parquet/analytics/csv/` contains `summary_by_solver.csv`,
  `summary_by_failure_mode.csv`, `summary_by_task.csv`,
  `summary_by_benchmark.csv`, `solver_failure_matrix.csv`.
- `reports/mvp_report.md` title mentions **ARC Solver Evaluation Platform**.

ARC-AGI-2: populate `benchmark_packs/arc_agi_2/tasks/` first — see
`docs/BENCHMARK_PACKS.md`. Do not expect auto-download.

## 3. Real run — OpenAI-compatible (LLM-direct)

```bash
export OPENAI_API_KEY="sk-..."
python src/run_evaluation.py --provider openai --model gpt-4o-mini --limit 5 --dry-run
python src/run_evaluation.py --provider openai --model gpt-4o-mini --limit 5 --experiment-id real-openai
python src/build_analytics.py --experiment-id real-openai
```

## 4. Real run — Gemini (manual)

```bash
export GEMINI_API_KEY="AIza..."
python src/run_evaluation.py --provider gemini --model gemini-2.5-flash --limit 1 --task-id sample01
```

Checks: exit 0; manifest `solver.provider == gemini`; row `raw_output` /
`parse_status`; failures should be model-side, not `execution_error` from
auth mistakes. Then scale `--limit 5` / `20`.

## 5. Real run — Claude (manual)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
python src/run_evaluation.py --provider claude --model claude-opus-4-8 --limit 1 --task-id sample01
```

Same checks as Gemini. Refusals become `execution_error` rows. Use
`scripts/plot_run_variance.py` for cross-run nondeterminism.

## 6. Submission-file / external solvers

```bash
# Offline judge before competition upload:
python src/run_evaluation.py --submission-file artifacts/submissions/mine.json \
    --solver-name my-system --experiment-id pre-submit

# Registry entry (after enabling in configs/solvers.json):
python src/run_evaluation.py --solver <name> --limit 3 --dry-run
```

See `docs/SOLVER_ADAPTERS.md` and `docs/QUICKSTART_EXTERNAL_SOLVER.md`.

## 7. Comparing runs / variance

```bash
python src/run_evaluation.py --provider claude --model claude-opus-4-8 --limit 20 --experiment-id exp1-r1
python src/run_evaluation.py --provider claude --model claude-opus-4-8 --limit 20 --experiment-id exp1-r2
python scripts/plot_run_variance.py --prefix exp1
```

## 8. Housekeeping

- Runs are append-only; delete a bad `runs/<run_id>/` then rebuild analytics.
- Analytics is fully rebuilt each `build_analytics.py` call (also drops legacy
  `summary_by_model` / `fact_inference_results` if present).
- Manifest `"status": "running"` means crash/interrupt mid-run.

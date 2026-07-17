# Open-Source Academic MVP — Handoff Guide

**Audience:** a new maintainer or researcher cloning this repository without
the original builder.

**Scope:** local judge + analytics + optional observatory + static frontend +
pre-submit standard for complete solver systems. Not a product, not a hosted
service, not an ARC solver.

---

## What works today

| Workflow | Entry | Verified how |
| --- | --- | --- |
| Offline platform demo | `make smoke`, `make mvp-offline` | Unit tests + isolated smoke script |
| Benchmark packs | `python src/main.py --benchmark-pack <id>` | Pack tests + AGI-2 ETL |
| Submission-first eval | `src/submission_cli.py` | Examples + unit tests |
| Kaggle-strict validate | `validate-submission --kaggle-strict` | `tests/test_kaggle_protocol.py` |
| LLM-direct eval | `src/run_evaluation.py --provider …` | Manual pilot/smoke reports |
| Batch pipeline under judge | `src/batch_runner.py` / `make batch-example` | Unit + CI + Makefile demo |
| Sealed holdout | `presubmit_cli.py create-holdout` | Unit + real AGI-2 split |
| Go/no-go certificate | `presubmit_cli.py certify` / `make presubmit-example` | Unit + Makefile demo |
| Analytics v2.2 | `src/build_analytics.py` | Smoke + pilot reports |
| Public observatory | `src/public_results_cli.py` | Fixture tests |
| Frontend overview | `scripts/export_frontend_data.py` | Manual export (no API) |
| CI | `.github/workflows/ci.yml` | `make test` + `make smoke` + batch round-trip |

**Unit tests:** `make test` → **170 tests** (last checked July 16, 2026).

**Isolated smoke:** `make smoke` → **SMOKE PASS** (ETL → mock eval → analytics
in a temp dir).

---

## Four layers (do not conflate)

```
┌─────────────────────────────────────────────────────────────┐
│  LOCAL JUDGE (authoritative for your runs)                  │
│  run_evaluation.py → Parquet rows + _manifest.json          │
│  Metrics: solved_rate · task_solved_rate · kaggle_score     │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  PRE-SUBMIT STANDARD (complete systems → Kaggle confidence) │
│  batch_runner · kaggle-strict · sealed holdout · certify    │
│  docs/PRESUBMIT_STANDARD.md                                 │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  PUBLIC OBSERVATORY (curated external context only)         │
│  Never re-scores public rows; trust tiers + provenance      │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND (static local dashboard)                          │
│  export_frontend_data.py → overview.json · npx vite         │
└─────────────────────────────────────────────────────────────┘
```

---

## Supported workflows

### 1. Offline (no API keys)

```bash
make test && make smoke
make mvp-offline          # sample data → mock eval → report
make presubmit-example    # batch project → certificate (then: make clean-demo)
```

### 2. Pack-based ETL

```bash
make list-packs
make etl-example-pack     # bundled tiny pack
python src/main.py --benchmark-pack arc_agi_2   # needs local tasks/
```

Official AGI-2 tasks: https://github.com/arcprize/ARC-AGI-2 → `data/evaluation/`
(no auto-download; see `docs/BENCHMARK_PACKS.md`).

### 3. External solver (preferred)

```bash
python src/submission_cli.py validate-submission \
  --path examples/external_solver/submission.json --kaggle-strict
python src/submission_cli.py evaluate-submission \
  --path examples/external_solver/submission.json \
  --solver-name my-system --experiment-id smoke \
  --task-id sample01,sample02
python src/build_analytics.py --experiment-id smoke
```

Partial submissions against a full pack mark missing items as
`execution_error` (= coverage gap). Scope smokes with `--task-id` / `--limit`.

### 4. Complete pipeline under the judge

```bash
# declare atlas_project.json in your solver repo — see examples/batch_project/
python src/batch_runner.py --project atlas_project.json \
  --offline --enforce-budget
python src/presubmit_cli.py create-holdout --seed 42 --holdout-fraction 0.3
python src/presubmit_cli.py certify --submission out/submission.json \
  --holdout configs/holdout_arc_agi_2.json \
  --batch-manifest artifacts/batch/.../batch_manifest.json
```

### 5. Observatory + frontend

```bash
python src/public_results_cli.py compare --run-id <your_run_id>
python scripts/export_frontend_data.py --run-id <your_run_id>
cd frontend && npm install && npx vite   # ephemeral local UI; Ctrl+C when done
```

---

## What remains manual

- Populating `benchmark_packs/arc_agi_2/tasks/` on a fresh clone (JSON not
  committed — see `docs/BENCHMARK_PACKS.md`).
- Exporting environment variables (pipeline does not load `.env` automatically).
- Real LLM / API pilots (CI must not spend API money).
- Gemini / Claude first-run verification (`docs/RUNBOOK.md` §4–5).
- Rotating any API keys that were ever pasted into chat or logs.
- Interpreting certificate **warnings** (offline / holdout / variance not
  verified) vs **NO-GO** (Kaggle would reject the artifact).

---

## Evidence reports

Committed narrative reports live under `reports/`. Index and interpretation:
[`reports/README.md`](../reports/README.md).

Pilot/smoke runs are **`local_pilot_partial`** — partial task counts, not
official full-benchmark leaderboard scores.

Generated certificates (`reports/presubmit_certificate_*.md`) and sealed
holdouts (`configs/holdout_*.json`) are **gitignored** — regenerate locally.

---

## Key caveats

1. **Scoring semantics (Decision 21 + kaggle_score):** use `task_solved_rate`
   for ARC-official all-tests-correct; `solved_rate` is per test example;
   `kaggle_score` is the leaderboard-style per-task mean over test outputs
   (attempts 1–2).
2. **Pass@k:** default LLM-direct `--attempts` is **1**; ARC-style pass@2
   requires `--attempts 2` (batch / Kaggle-strict expect both attempts).
3. **OpenCode Go model ids:** use gateway ids like `glm-5.2`, `qwen3.7-max`,
   `kimi-k2.6` — not vendor-prefixed aliases that the gateway rejects.
4. **Thinking mode:** Kimi K2.5/2.6, Qwen 3.7*, and GLM-5* disable thinking in
   `providers.py` for grid-only runs.
5. **Parse vs solve vs coverage:** high `parse_error` = format; flood of
   `execution_error` on a partial submission = coverage gap (use `--task-id`).
6. **Budget check** measures wall time on *your* machine, not Kaggle hardware.
7. **Pack ETL accumulates** by `task_id`; sidecar reflects the last pack —
   re-ETL the target pack before a real run (or use `--output-root`).
8. **`artifacts/demo/`** may lag templates — prefer `reports/` from a fresh
   `build_analytics.py` run.

---

## Reproduce the main demo (5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"   # or: pip install -r requirements.txt
make test
make smoke
make mvp-offline
make presubmit-example && make clean-demo
```

Console scripts after editable install: `atlas-etl`, `atlas-evaluate`,
`atlas-submission`, `atlas-batch`, `atlas-presubmit`, `atlas-analytics`,
`atlas-public-results`. Legacy `python src/<entrypoint>.py` remains supported.

---

## Further reading

| Doc | Purpose |
| --- | --- |
| [`README.md`](../README.md) | Quick start + rubric |
| [`CHANGELOG.md`](../CHANGELOG.md) | Release notes (v0.1.0) |
| [`docs/CONTRACTS.md`](CONTRACTS.md) | Frozen public schemas / metrics |
| [`docs/REPRODUCIBILITY.md`](REPRODUCIBILITY.md) | Regenerate committed evidence |
| [`docs/ADOPTER_JOURNEY.md`](ADOPTER_JOURNEY.md) | External-style solver path |
| [`docs/EVALUATE_YOUR_SOLVER.md`](EVALUATE_YOUR_SOLVER.md) | Tester step-by-step |
| [`docs/PRESUBMIT_STANDARD.md`](PRESUBMIT_STANDARD.md) | Tiers 1–4 pre-submit |
| [`docs/BENCHMARK_PACKS.md`](BENCHMARK_PACKS.md) | Pack layout + AGI-2 import |
| [`docs/QUICKSTART_EXTERNAL_SOLVER.md`](QUICKSTART_EXTERNAL_SOLVER.md) | Submission copy-paste |
| [`docs/SOLVER_ADAPTERS.md`](SOLVER_ADAPTERS.md) | Adapter families |
| [`docs/PUBLIC_RESULTS_OBSERVATORY.md`](PUBLIC_RESULTS_OBSERVATORY.md) | Observatory rules |
| [`docs/RUNBOOK.md`](RUNBOOK.md) | Operator commands |
| [`docs/RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) | Pre-tag human checklist |
| [`docs/RELEASE_PROCESS.md`](RELEASE_PROCESS.md) | Tag / GitHub release steps |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | Contribution + test policy |
| [`SECURITY.md`](../SECURITY.md) | Keys, artifacts, corpora |
| [`src/DECISIONS.md`](../src/DECISIONS.md) | Design log (Decisions 1–25) |
| [`examples/batch_project/`](../examples/batch_project/) | Minimal batch project |
| [`schemas/`](../schemas/) | JSON Schema contracts |

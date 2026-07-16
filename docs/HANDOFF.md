# Open-Source Academic MVP — Handoff Guide

**Audience:** a new maintainer or researcher cloning this repository without
the original builder.

**Scope:** local judge + analytics + optional observatory + static frontend.
Not a product, not a hosted service, not an ARC solver.

---

## What works today

| Workflow | Entry | Verified how |
| --- | --- | --- |
| Offline platform demo | `make smoke`, `make mvp-offline` | Unit tests + isolated smoke script |
| Benchmark packs | `python src/main.py --benchmark-pack <id>` | Pack tests + AGI-2 ETL smoke |
| Submission-first eval | `src/submission_cli.py` | Examples + unit tests |
| LLM-direct eval | `src/run_evaluation.py --provider …` | Manual pilot/smoke reports |
| Analytics v2.2 | `src/build_analytics.py` | Smoke + pilot reports |
| Public observatory | `src/public_results_cli.py` | Fixture tests |
| Frontend overview | `scripts/export_frontend_data.py` | Manual export (no API) |

**Unit tests:** `python -m unittest discover -s tests -v` → **135 tests** (last
checked July 16, 2026).

**Isolated smoke:** `python scripts/smoke_test.py` → **SMOKE PASS** (ETL → mock
eval → analytics in a temp dir).

---

## Three layers (do not conflate)

```
┌─────────────────────────────────────────────────────────────┐
│  LOCAL JUDGE (authoritative for your runs)                  │
│  run_evaluation.py → Parquet rows + _manifest.json          │
│  build_analytics.py → CSVs + reports/*.md                   │
│  Metrics: solved_rate (item), task_solved_rate (ARC task)   │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ compare (context only)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  PUBLIC OBSERVATORY (curated external context)              │
│  fixtures/public_results/*.json → leaderboard Parquet       │
│  public_results_cli.py compare → reports/public_results_*   │
│  Never re-scores public rows; trust tiers + provenance      │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ export (read-only snapshot)
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND (static dashboard)                                │
│  export_frontend_data.py → frontend/public/data/overview.json │
│  Vite dev server reads JSON only — no backend, no auth      │
└─────────────────────────────────────────────────────────────┘
```

---

## Supported workflows

### 1. Offline (no API keys)

```bash
make test && make smoke
make mvp-offline          # sample data → mock eval → report
```

### 2. Pack-based ETL

```bash
make list-packs
make etl-example-pack     # bundled tiny pack
python src/main.py --benchmark-pack arc_agi_2   # needs local tasks/
```

### 3. External solver (preferred)

```bash
make validate-example-submission
python src/submission_cli.py evaluate-submission \
  --path path/to/submission.json --solver-name mine --experiment-id pre
python src/build_analytics.py --experiment-id pre
```

### 4. LLM-direct pilot (manual, costs money)

```bash
export OPENAI_API_KEY=…
export OPENAI_BASE_URL=https://opencode.ai/zen/go/v1   # example gateway
python src/run_evaluation.py --provider openai --model glm-5.2 \
  --benchmark-pack arc_agi_2 --task-id … --limit 5 --experiment-id pilot
python src/build_analytics.py --experiment-id pilot
```

See `docs/RUNBOOK.md` for provider-specific notes.

### 5. Observatory + frontend

```bash
python src/public_results_cli.py compare --run-id <your_run_id>
python scripts/export_frontend_data.py --run-id <your_run_id>
cd frontend && npm install && npm run dev
```

---

## What remains manual

- Populating `benchmark_packs/arc_agi_2/tasks/` on a fresh clone (JSON not
  committed — see `docs/BENCHMARK_PACKS.md`).
- Exporting environment variables (pipeline does not load `.env` automatically).
- Real LLM / API pilots (no CI that spends API money).
- Gemini / Claude first-run verification (`docs/RUNBOOK.md` §4–5).
- GitHub Actions / CI wiring (deferred).
- Rotating any API keys that were ever pasted into chat or logs.

---

## Evidence reports

Committed narrative reports live under `reports/`. Index and interpretation:
[`reports/README.md`](../reports/README.md).

Pilot/smoke runs are **`local_pilot_partial`** — partial task counts, not
official full-benchmark leaderboard scores.

---

## Key caveats

1. **Scoring semantics (Decision 21):** compare public leaderboards using
   `task_solved_rate`; `solved_rate` is per test example; `exact_match_rate`
   is per attempt row.
2. **Pass@k:** default LLM-direct `--attempts` is **1**; ARC-style pass@2
   requires `--attempts 2`.
3. **OpenCode Go model ids:** use gateway ids like `glm-5.2`, `qwen3.7-max`,
   `kimi-k2.6` — not vendor-prefixed aliases that the gateway rejects.
4. **Thinking mode:** Kimi K2.5/2.6 and Qwen 3.7* disable thinking in
   `providers.py` for grid-only runs.
5. **Parse vs solve:** AGI-2 smokes show the judge works; model output format
   (prose vs grid) is the main LLM-direct friction — not a platform bug.
6. **`artifacts/demo/`** may lag the v2 report template — prefer `reports/`
   from a fresh `build_analytics.py` run.

---

## Reproduce the main demo (5 minutes)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
make test
make smoke
make mvp-offline
cat reports/mvp_report.md
```

---

## Further reading

| Doc | Purpose |
| --- | --- |
| [`README.md`](../README.md) | Quick start + rubric |
| [`docs/BENCHMARK_PACKS.md`](BENCHMARK_PACKS.md) | Pack layout + AGI-2 import |
| [`docs/QUICKSTART_EXTERNAL_SOLVER.md`](QUICKSTART_EXTERNAL_SOLVER.md) | Submission onboarding |
| [`docs/SOLVER_ADAPTERS.md`](SOLVER_ADAPTERS.md) | Adapter families |
| [`docs/PUBLIC_RESULTS_OBSERVATORY.md`](PUBLIC_RESULTS_OBSERVATORY.md) | Observatory rules |
| [`docs/RUNBOOK.md`](RUNBOOK.md) | Operator commands |
| [`docs/RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) | Pre-tag human checklist |
| [`src/DECISIONS.md`](../src/DECISIONS.md) | Design log (Decisions 1–21) |
| [`agent_context/repo_map/repo_map.md`](../agent_context/repo_map/repo_map.md) | File map |

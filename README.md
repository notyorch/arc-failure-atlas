# ARC Solver Evaluation Platform

Open-source **local judge** for ARC-AGI solver research: versioned benchmark
packs, submission-first ingestion, reproducible analytics, optional public-score
context, and a static results UI.

**Handoff guide:** [`docs/HANDOFF.md`](docs/HANDOFF.md) · **Evidence index:**
[`reports/README.md`](reports/README.md)

---

## What this is / what this is not

| This **is** | This **is not** |
| --- | --- |
| A reproducible evaluation **platform** for heterogeneous solvers | An ARC solver or training codebase |
| Submission-first (`submission.json` / prediction dir) | The official ARC Prize / Kaggle leaderboard |
| Local Parquet + manifests + failure taxonomy | A hosted SaaS (you run it locally) |
| Optional curated **observatory** for public-score **context** | Auto-download of licensed AGI-2 corpora |

---

## How it works (today)

```
benchmark pack / raw JSON
        →  src/main.py (ETL)  →  tasks Parquet + pack metadata
        →  src/run_evaluation.py  →  scored rows + run manifest
        →  src/build_analytics.py  →  CSVs + reports/*.md
        →  (optional) public_results_cli + export_frontend_data → UI JSON
```

- **Judge:** parsing, scoring, and taxonomy are solver-agnostic (Standard Solver
  Interface + adapters in `src/solvers.py`).
- **Benchmark packs:** `benchmark_packs/<pack_id>/manifest.json` + `tasks/`
  (`arc_agi_1`, `arc_agi_2`, `example_local_pack`). See
  [`docs/BENCHMARK_PACKS.md`](docs/BENCHMARK_PACKS.md).
- **Submission-first:** external authors validate and score artifacts via
  `src/submission_cli.py` — no core rewrite. See
  [`docs/QUICKSTART_EXTERNAL_SOLVER.md`](docs/QUICKSTART_EXTERNAL_SOLVER.md).
- **Observatory vs judge:** the judge scores **your** runs; the observatory
  ingests **curated public fixtures** for side-by-side context only
  (`comparison_scope=local_pilot_partial`). See
  [`docs/PUBLIC_RESULTS_OBSERVATORY.md`](docs/PUBLIC_RESULTS_OBSERVATORY.md).
- **Frontend:** `scripts/export_frontend_data.py` writes static
  `frontend/public/data/overview.json`; Vite serves it read-only. No backend.

**Scoring (Decision 21):** reports include `solved_rate` (per test example),
`task_solved_rate` (ARC-official per task), and `exact_match_rate` (per attempt).

---

## Ease-of-use rubric (solver developers)

Six dimensions, 1–5 each (total 6–30). Current self-assessment: **~24/30**.

| Dimension | Focus |
| --- | --- |
| Onboarding | Scored run without editing platform core |
| Benchmark pack setup | Pack by id or path; versioned manifest |
| Submission ingest | `submission.json` or prediction directory |
| Reproducibility | Manifests + deterministic offline mock path |
| Analytics | Taxonomy + benchmark metadata in reports |
| Observatory clarity | Local judge ≠ public observatory |

---

## Requirements

- Python **3.11+**
- Node.js **18+** (frontend only)
- Optional: OpenAI-compatible API key for LLM-direct pilots

```bash
git clone <this-repo>
cd arc-failure-atlas
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # optional; export vars yourself — not auto-loaded
```

---

## Quick start

### 1. Verify (offline, no keys)

```bash
make test                 # 135 unit tests
make smoke                # isolated ETL → mock eval → analytics
make mvp-offline          # sample data → report
```

### 2. ARC-AGI-2 pack (local tasks)

Task JSON under `benchmark_packs/arc_agi_2/tasks/` is **gitignored** on fresh
clones. Populate from the official ARC-AGI-2 public evaluation set:

```bash
# after obtaining evaluation JSON elsewhere
cp /path/to/evaluation/*.json benchmark_packs/arc_agi_2/tasks/
# or: ln -sfn /abs/path/to/evaluation benchmark_packs/arc_agi_2/tasks

python src/main.py --benchmark-pack arc_agi_2
python src/main.py --list-benchmark-packs
```

### 3. Evaluate your solver (preferred)

```bash
python src/submission_cli.py validate-submission \
  --path examples/external_solver/submission.json

python src/submission_cli.py evaluate-submission \
  --path path/to/your/submission.json \
  --solver-name my-system --experiment-id pre-submit

python src/build_analytics.py --experiment-id pre-submit
```

### 4. LLM-direct pilot (optional, manual)

```bash
export OPENAI_API_KEY="…"
export OPENAI_BASE_URL="https://opencode.ai/zen/go/v1"

python src/run_evaluation.py \
  --provider openai --model glm-5.2 \
  --prompt-version arc_grid_v2 \
  --benchmark-pack arc_agi_2 \
  --task-id <ids> --limit 5 \
  --experiment-id my-pilot
```

OpenCode Go model ids: `glm-5.2`, `qwen3.7-max`, `kimi-k2.6` (not `z-ai/…`
aliases). Default `--attempts` is **1**; pass@2 → `--attempts 2`.

### 5. Frontend

```bash
python scripts/export_frontend_data.py --run-id <run_id>
cd frontend && npm install && npm run dev
```

### 6. Public context (optional)

```bash
python src/public_results_cli.py compare --run-id <run_id>
```

---

## Release status (academic MVP)

| Area | Status |
| --- | --- |
| Offline pipeline | Verified: `make test`, `make smoke` |
| Benchmark packs + ETL | Verified; AGI-2 smoke on local 120-task pack |
| Submission adapters | Verified via examples + tests |
| LLM-direct pilots | Documented evidence in `reports/` (partial n) |
| Full AGI-2 corpus eval | **Not run** — manual, operator-initiated |
| CI / GitHub Actions | **Not wired** |
| Gemini / Claude live | **Manual** first-run still on checklist |

Details: [`docs/HANDOFF.md`](docs/HANDOFF.md) · [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)

---

## Make targets

| Target | Action |
| --- | --- |
| `make help` | List targets |
| `make test` / `make smoke` | Verification |
| `make mvp-offline` | Offline demo pipeline |
| `make list-packs` / `make list-solvers` | Discovery |
| `make etl-example-pack` | Bundled tiny pack ETL |
| `make validate-example-submission` | Example submission check |
| `make frontend-dev` | Export + Vite |
| `make public-results` | Observatory compare (default pilot id) |

Operator runbook: [`docs/RUNBOOK.md`](docs/RUNBOOK.md)

---

## Safety

- Never commit `.env`, API keys, or pack task corpora (`data/`, `benchmark_packs/*/tasks/*.json`).
- Local pilots ≠ public leaderboard scores.
- Design log: [`src/DECISIONS.md`](src/DECISIONS.md)

## License

See [`LICENSE`](LICENSE).

# Review Checklist — Evaluation MVP

**Scope:** verify the end-to-end pipeline (ETL → inference → scoring →
taxonomy → analytics → report) works from a clean checkout, offline.
**Total reviewer time:** ~5–10 minutes.

## 0. Prerequisites

- Python ≥ 3.11 with `pandas`, `numpy`, `pyarrow` (`pip install -r requirements.txt`;
  `duckdb` is optional).
- No API keys, no network needed for any step below.

## 1. Exact commands to run (from the repository root)

```bash
# (a) Unit tests — expected: 34 tests, OK, < 5 s
python -m unittest discover -s tests -v

# (b) End-to-end smoke test in an isolated temp dir — expected:
#     "SMOKE PASS — 13 checks" in ~2–10 s; repo data/ untouched
python scripts/smoke_test.py

# (c) Full offline demo into the repo's data/ tree — ~10–30 s total
python scripts/fetch_arc_data.py --sample
python src/main.py
python src/run_inference.py --provider mock --model baseline --experiment-id review
python src/build_analytics.py --experiment-id review

# (d) Optional, network required (~30 s extra): add real ARC tasks and rerun
python scripts/fetch_arc_data.py --limit 20
python src/main.py
python src/run_inference.py --provider mock --model baseline --experiment-id review
python src/build_analytics.py --experiment-id review
```

Equivalent Makefile targets (if `make` is installed): `make test`,
`make smoke`, `make mvp-offline`.

## 2. Expected runtime

| Step | Expected |
| --- | --- |
| Unit tests | < 5 s |
| Smoke test | 2–10 s |
| Sample fetch + ETL (6 tasks) | < 5 s |
| Mock inference (6–26 tasks) | < 5 s (synthetic latency, no network) |
| Analytics + report | < 5 s |
| Real-provider runs | minutes; depends on model/limit — not required for review |

## 3. Expected output directories (after step c)

```
data/parquet/evaluation/                 split=<train|test>/task_id=<id>/*.parquet
data/parquet/inference/runs/<run_id>/    part-0000.parquet + _manifest.json
data/parquet/analytics/                  _manifest.json + 4 table directories
reports/mvp_report.md                    regenerated report
logs/quality_<timestamp>.log             ETL quality log
```

Spot checks:

- `data/parquet/inference/runs/<run_id>/_manifest.json` →
  `"status": "completed"`, a real `git_commit` SHA, `prompt_version:
  "arc_grid_v1"`, `n_rows_written` == number of tasks run.
- `reports/mvp_report.md` → metrics-by-model table, failure-mode
  distribution summing to the row count, 3 example failures.
- `python -c "import pandas as pd; print(pd.read_parquet('data/parquet/analytics/summary_by_model'))"`
  → one row per (experiment, provider, model) with the 7 agreed metrics.

## 4. Common failure points

| Symptom | Cause / fix |
| --- | --- |
| `Tasks Parquet not found` | ETL not run yet → `python scripts/fetch_arc_data.py --sample && python src/main.py` |
| `no inference results found under ...` | Run inference before analytics |
| `OPENAI_API_KEY is not set` | Only affects `--provider openai`; use `--provider mock` or export the key |
| `Ollama server not reachable` | Only affects `--provider ollama`; start `ollama serve` or use mock |
| `could not download ARC-AGI dataset` | No network → use `--sample` mode |
| `ModuleNotFoundError: pandas/pyarrow` | `pip install -r requirements.txt` |
| Manifest shows `"status": "running"` | The run crashed/was interrupted; part files written so far are still valid |
| Different numbers than `reports/mvp_report.md` | The committed report used 26 tasks (6 samples + 20 downloaded) and two mock models — see its Reproduce section |

Notes: mock results are deterministic per (model, task) — reruns of step (c)
produce identical metrics; only `run_id`s and timestamps change. ETL output
is bit-identical across reruns of the same files (`ingested_at` = file mtime).

## 5. What counts as MVP done (acceptance criteria)

- [ ] `python -m unittest discover -s tests` passes (34 tests).
- [ ] `python scripts/smoke_test.py` prints `SMOKE PASS` and exits 0.
- [ ] ETL produces the frozen 15-column tasks Parquet from raw JSON with
      Hive partitions (`split`/`task_id`) and quality logging intact.
- [ ] `run_inference.py --provider mock` runs offline end to end, writing
      the 28-column results schema + `_manifest.json` per run.
- [ ] Every result row carries parse status, scoring metrics (NULL when not
      evaluable), and exactly one failure-mode label (or NULL without
      ground truth).
- [ ] `build_analytics.py` rebuilds the 4 analytics tables + build manifest
      and regenerates `reports/mvp_report.md`.
- [ ] Real providers (`openai`/`ollama`) fail fast with actionable messages
      when unconfigured — they must not crash the repo for reviewers
      without credentials.
- [ ] README documents setup, env vars, commands, and expected outputs;
      decisions 8–13 recorded in `src/DECISIONS.md`.

Out of scope for this MVP (tracked in `agent_context/tasks/current_priorities.md`):
full 400-task scale run, real-provider comparison runs, pytest/CI setup,
taxonomy v2, `transformation_type` labeling.

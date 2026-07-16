# Review Checklist — Solver Evaluation Platform MVP

**Scope:** verify ETL → solver evaluation → scoring → taxonomy → analytics →
report from a clean checkout, offline.
**Total reviewer time:** ~5–10 minutes.

## 0. Prerequisites

- Python ≥ 3.11 with `pandas`, `numpy`, `pyarrow` (`pip install -r requirements.txt`).
- No API keys, no network needed for steps below.

## 1. Exact commands (repository root)

```bash
python -m unittest discover -s tests -v
python scripts/smoke_test.py

python scripts/fetch_arc_data.py --sample
python src/main.py
python src/run_evaluation.py --solver mock-baseline --experiment-id review
python src/build_analytics.py --experiment-id review

# Optional network:
python scripts/fetch_arc_data.py --limit 20
python src/main.py
python src/run_evaluation.py --solver mock-baseline --experiment-id review
python src/build_analytics.py --experiment-id review

python scripts/demo_bundle.py
```

Makefile: `make test`, `make smoke`, `make mvp-offline`, `make demo-bundle`.

## 2. Expected artifacts

| Path | Expect |
| --- | --- |
| `data/parquet/inference/runs/<run_id>/` | part files + `_manifest.json` (`evaluation_run`) |
| Columns | `solver_name`, `execution_mode`, `raw_output`, `attempt`, … (schema v2) |
| `analytics/fact_evaluation_results/` | Hive `solver_name=` |
| `analytics/csv/` | `summary_by_solver.csv`, `solver_failure_matrix.csv`, … |
| `reports/mvp_report.md` | title **ARC Solver Evaluation Platform** |

## 3. Spot checks

- [ ] `python src/run_evaluation.py --list-solvers` shows `mock-baseline` / `mock-large` and disabled reference entries.
- [ ] Failure modes use `execution_error` (not `api_error`) for solver crashes.
- [ ] `--dry-run` with `--solver mock-baseline` prints wire/prompt preview without writes.
- [ ] `docs/SOLVER_ADAPTERS.md` matches adapter names in `src/solvers.py`.

## 4. Out of scope for this review

- Live Gemini/Claude API runs (see RUNBOOK §4–5).
- Wiring third-party solvers via submission adapters (human integration).
- Full 400-task evaluation.

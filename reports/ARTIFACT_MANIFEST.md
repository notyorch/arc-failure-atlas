# Evidence artifact manifest

Committed tables/figures under `reports/tables/` and `reports/figures/`.
Regenerate with `python scripts/consolidate_pilot_evidence.py` when local
Parquet runs are present. Scope for all rows: **`local_pilot_partial`**.

| Artifact | Kind | Source | Notes |
| --- | --- | --- | --- |
| `tables/model_comparison.csv` | table | curated pilots in `consolidate_pilot_evidence.py` | machine-readable |
| `tables/model_comparison.md` | table | same | Markdown |
| `tables/pilot_glm52_agi2_n120_attempts.csv` | table | run `20260716T155616Z_opencode-glm-5.2_15691f67` | 167 attempt rows |
| `tables/summary_by_*.csv` | table | analytics export for primary / local builds | may refresh via `build_analytics` |
| `figures/task_solved_rate_by_model.png` | chart | consolidate script | task_solved_rate |
| `figures/parse_error_rate_by_model.png` | chart | consolidate script | parse vs accuracy |
| `figures/latency_by_model.png` | chart | consolidate script | mean latency |
| `figures/failure_mode_mix.png` | chart | primary AGI-2 n=120 run | taxonomy mix |

### Metric definitions

- `task_solved_rate` — ARC-official (all test examples correct).
- `solved_rate` — item-level pass@k.
- `parse_error_rate` — unreadable grid (≠ wrong answer).
- `kaggle_score` — leaderboard-style per-task mean (attempts 1–2).

### Narrative reports

Index: [`README.md`](README.md). Primary: [`pilot_glm52_agi2_n120.md`](pilot_glm52_agi2_n120.md).

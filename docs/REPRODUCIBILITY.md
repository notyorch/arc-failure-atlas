# Reproducibility appendix

How to regenerate committed evidence and verify the platform offline.
All pilots remain **`local_pilot_partial`** unless explicitly labeled otherwise.

## Platform health (no API keys)

```bash
pip install -e .
# or: pip install -r requirements.txt
make test
make smoke
make mvp-offline
make presubmit-example && make clean-demo
```

## Mount ARC-AGI-2 (local only)

Official source: https://github.com/arcprize/ARC-AGI-2 → `data/evaluation/`.
ATLAS never auto-downloads these files.

```bash
cp /path/to/ARC-AGI-2/data/evaluation/*.json benchmark_packs/arc_agi_2/tasks/
# or: ln -sfn /abs/path/to/ARC-AGI-2/data/evaluation benchmark_packs/arc_agi_2/tasks
python src/main.py --benchmark-pack arc_agi_2
```

## Regenerating tables and figures

Committed comparison artifacts under `reports/tables/` and `reports/figures/`
are produced by:

```bash
python scripts/consolidate_pilot_evidence.py \
  --primary-run-id 20260716T155616Z_opencode-glm-5.2_15691f67
```

Requires the local Parquet runs under `data/parquet/inference/runs/`
(gitignored). Manifest of committed figures: [`reports/ARTIFACT_MANIFEST.md`](../reports/ARTIFACT_MANIFEST.md).

## Regenerating the dashboard snapshot

```bash
python scripts/export_frontend_data.py --run-id 20260716T155616Z_opencode-glm-5.2_15691f67
cd frontend && npm install && npx vite
```

`frontend/public/data/overview.json` is gitignored.

## Primary AGI-2 pilot

| Field | Value |
| --- | --- |
| Report | `reports/pilot_glm52_agi2_n120.md` |
| Run id | `20260716T155616Z_opencode-glm-5.2_15691f67` |
| Experiment | `pilot-glm52-agi2-n120` |
| Scope | `local_pilot_partial` · pack `arc_agi_2` · n=120 tasks / 167 items |
| Prompt / attempts | `arc_grid_v2` / 1 |

Re-running the pilot requires an OpenCode-compatible API key and several hours
of wall time; prefer the committed report unless you intend a new experiment.

## Separating evidence kinds

| Kind | Where | Claim |
| --- | --- | --- |
| Demo / offline | `make mvp-offline`, `make smoke` | Pipeline works |
| Local pilot | `reports/pilot_*`, `reports/smoke_*` | Partial corpus; not leaderboard |
| Pre-submit demo | `make presubmit-example` (artifacts gitignored) | Certificate path works |
| Public observatory | `reports/public_results_*` | Curated external **context** only |

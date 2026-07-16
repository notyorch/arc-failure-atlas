# Benchmark packs

**Audience:** anyone loading ARC (or ARC-like) task corpora into this platform
for ETL → evaluation → analytics.

## What a pack is

A **benchmark pack** is a versioned folder of task JSON files plus a
`manifest.json` that pins identity and provenance:

| Field | Meaning |
| --- | --- |
| `pack_id` | Stable id (`arc_agi_2`, `example_local_pack`, …) |
| `benchmark_family` | Family key (`arc_agi`, `custom_arc_like`, …) |
| `benchmark_name` | Human label (`ARC-AGI-2`) |
| `benchmark_version` | Pack pin (`local-pack-v1`, …) |
| `split_name` | Pack-level split label (`public_eval`, `sample`, …) — **not** the per-example `train`/`test` column |
| `task_source` | Provenance (`manual_local_import`, `local_repo_pack`, …) |
| `tasks_dir` | Relative (or absolute) directory of flat `*.json` tasks |

Default layout:

```text
benchmark_packs/<pack_id>/
  manifest.json
  tasks/*.json
```

Pack task bodies may be large or licensed — keep manifests in git; leave
`tasks/` empty (or gitignored) until you place files locally.

## Bring a local ARC-AGI-2 pack

Upstream ARC-AGI-2 uses the same ARC JSON shape as AGI-1
(`train` / `test` pairs, grids 0–9). Public evaluation lives under
`data/evaluation/` in the ARC-AGI-2 repo.

This platform **does not** auto-download ARC-AGI-2. Populate the pack yourself:

```bash
# Option A — symlink an external evaluation JSON directory
rm -rf benchmark_packs/arc_agi_2/tasks
ln -sfn /absolute/path/to/evaluation_json_dir benchmark_packs/arc_agi_2/tasks

# Option B — copy a subset
mkdir -p benchmark_packs/arc_agi_2/tasks
cp /path/to/evaluation/*.json benchmark_packs/arc_agi_2/tasks/

# Option C — point the manifest at another path
# edit benchmark_packs/arc_agi_2/manifest.json → "tasks_dir": "/abs/path/to/evaluation"
```

Then:

```bash
python src/main.py --list-benchmark-packs
python src/main.py --benchmark-pack arc_agi_2
python src/run_evaluation.py --solver mock-baseline --limit 5 --experiment-id agi2-smoke
# or submission-first:
python src/submission_cli.py evaluate-submission \
  --path path/to/submission.json \
  --solver-name my-agi2-system --experiment-id pre-submit
python src/build_analytics.py --experiment-id agi2-smoke
```

Generic local pack (any path with a `manifest.json`):

```bash
python src/main.py --benchmark-pack-path /path/to/my_pack
```

## Legacy ARC-AGI-1 path (unchanged)

```bash
python scripts/fetch_arc_data.py --sample   # or --limit N
python src/main.py                         # reads data/raw/evaluation/
```

Without `--benchmark-pack`, ETL still works and stamps rows with
`pack_id=legacy_raw_dir`, `benchmark_name=ARC-AGI-1`,
`benchmark_version=legacy-unpinned`.

## Metadata preserved end-to-end

These fields are written on:

1. **Tasks Parquet** (`data/parquet/evaluation/`) + sidecar `_benchmark_pack.json`
2. **Evaluation items / result rows** (`EVALUATION_RESULTS_SCHEMA` v2.1.0)
3. **Run manifest** (`_manifest.json` → `benchmark` object)
4. **Analytics** (`summary_by_benchmark` table + CSV)

| Column | Example |
| --- | --- |
| `pack_id` | `arc_agi_2` |
| `benchmark_family` | `arc_agi` |
| `benchmark_name` | `ARC-AGI-2` |
| `benchmark_version` | `local-pack-v1` |
| `split_name` | `public_eval` |
| `task_source` | `manual_local_import` |

Old evaluation Parquets without these columns are upgraded in memory by
`build_analytics` to `unknown` defaults (never silently rewritten on disk).

## Selection

| Mechanism | Example |
| --- | --- |
| Pack id | `--benchmark-pack arc_agi_2` / `ATLAS_BENCHMARK_PACK` |
| Pack path | `--benchmark-pack-path benchmark_packs/arc_agi_2` |
| Input override | `--input-dir other/tasks` with a selected pack (metadata from pack, files from dir) |
| Eval override | `--benchmark-pack …` on `run_evaluation` / `submission_cli` re-stamps rows |

## Non-goals

- No scraping of private / semi-private ARC Prize sets
- No claim that a local pack equals a full public leaderboard
- No automatic fetch of ARC-AGI-2 task JSON

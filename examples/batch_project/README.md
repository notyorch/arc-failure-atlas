# Batch project example — evaluate a COMPLETE pipeline pre-submit

This directory is a runnable stand-in for a full solver system (test-time
training, program search, ensembles…). The batch runner stages tasks,
executes your project under telemetry, and judges the `submission.json` it
produces — the same judge as every other adapter.

## The contract (all your project has to honor)

| Env var | Meaning |
| --- | --- |
| `ATLAS_TASKS_DIR` | read tasks here — one `<task_id>.json` per task, official ARC JSON, **test outputs stripped** |
| `ATLAS_SUBMISSION_PATH` | write your Kaggle-style `submission.json` here (`attempt_1` + `attempt_2` per test example) |

Declare how to run you in `atlas_project.json` (`command`, `workdir`,
`budget_hours`, optional fallback `artifact` path).

## Try it (offline, seconds)

```bash
# from the repo root, with a pack mounted (example_local_pack or arc_agi_2)
python src/batch_runner.py \
  --project examples/batch_project/atlas_project.json \
  --stage-dir artifacts/batch/example --experiment-id batch-example

# Kaggle-style guards:
python src/batch_runner.py --project ... --offline --enforce-budget
```

Outputs land in the stage dir: `tasks/` (what your project saw),
`submission.json`, `project_run.log`, and `batch_manifest.json`
(wall time vs budget, exit code, GPU telemetry, offline flag).

Then certify before submitting:

```bash
python src/presubmit_cli.py certify \
  --submission artifacts/batch/example/submission.json \
  --batch-manifest artifacts/batch/example/batch_manifest.json
```

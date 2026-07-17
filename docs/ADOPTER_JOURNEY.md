# Adopter journey — external-style solver through ATLAS

**Goal:** prove a third-party-style project can reach a certificate using only
docs and bundled fixtures — without maintainer intervention.

This journey uses the **bundled batch project**
([`examples/batch_project/`](../examples/batch_project/)) as a stand-in for a
complete pipeline (TTT / search / ensemble). It is deliberately tiny and
offline; it is **not** a competitive ARC solver.

---

## Time-to-first-score (offline)

| Step | Command | Expected |
| --- | --- | --- |
| 1. Install | `pip install -e .` or `pip install -r requirements.txt` | deps OK |
| 2. Health | `make test && make smoke` | 170 tests · SMOKE PASS |
| 3. Mount tiny pack | `python src/main.py --benchmark-pack example_local_pack` | ETL OK |
| 4. Submission smoke | see Path A below | scoped score, no coverage flood |
| 5. Batch + certify | `make presubmit-example` | certificate verdict printed |
| 6. Cleanup | `make clean-demo` | no generated leftovers |

Wall time on a laptop: **under a few minutes** for steps 1–6 (excluding a
full AGI-2 LLM pilot).

---

## Path A — submission-first (fixtures)

```bash
python src/submission_cli.py validate-submission \
  --path examples/external_solver/submission.json --kaggle-strict

python src/submission_cli.py evaluate-submission \
  --path examples/external_solver/submission.json \
  --solver-name adopter-smoke --experiment-id adopter-smoke \
  --task-id sample01,sample02

python src/build_analytics.py --experiment-id adopter-smoke
```

**Lesson learned (documented in EVALUATE_YOUR_SOLVER):** without `--task-id`,
missing pack tasks become `execution_error` (= coverage gap). Always scope
smokes.

---

## Path E — complete pipeline under the judge

```bash
python src/batch_runner.py \
  --project examples/batch_project/atlas_project.json \
  --stage-dir artifacts/batch/adopter \
  --benchmark-pack example_local_pack \
  --enforce-budget --experiment-id adopter-batch

python src/submission_cli.py validate-submission \
  --path artifacts/batch/adopter/submission.json --kaggle-strict

python src/presubmit_cli.py certify \
  --submission artifacts/batch/adopter/submission.json \
  --solver-name example-batch-pipeline \
  --batch-manifest artifacts/batch/adopter/batch_manifest.json
```

Or one shot: `make presubmit-example`.

**What the adopter sees:**

1. Tasks staged with **test GT stripped** (`ATLAS_TASKS_DIR`).
2. Pipeline writes `submission.json` to `ATLAS_SUBMISSION_PATH`.
3. Judge scores with the same taxonomy as every other adapter.
4. Certificate: `GO` / `GO WITH WARNINGS` / `NO-GO` with six checks.

**What broke during platform development (already fixed):**

| Issue | Symptom | Fix |
| --- | --- | --- |
| Partial submission vs full pack | Flood of `execution_error` | Docs + CLI note + `--task-id` |
| Pack accumulation | Mixed `example_local_pack` + AGI-2 | ETL warning + re-ETL docs |
| Variance mismatch | Certificate always warned | Manifest field `solver_name` (not `name`) |

---

## Scaling to a real system

1. Copy `examples/batch_project/atlas_project.json` into your solver repo.
2. Honor `ATLAS_TASKS_DIR` / `ATLAS_SUBMISSION_PATH`.
3. Mount AGI-2 from https://github.com/arcprize/ARC-AGI-2 (`data/evaluation/`).
4. `atlas-batch --offline --enforce-budget` then `atlas-presubmit certify`.
5. Optional: `create-holdout` → iterate on dev → one-shot `--reveal-holdout`.

Full standard: [`PRESUBMIT_STANDARD.md`](PRESUBMIT_STANDARD.md).
Contracts: [`CONTRACTS.md`](CONTRACTS.md).

# The pre-submit standard — certify a COMPLETE solver system before Kaggle

**Audience:** teams with a full ARC-AGI-1/2 solving *system* (test-time
training, program search, ensembles — NVARC / ARChitects scale), who want
confidence that the score they see locally anticipates the score Kaggle
will give them.

**The claim this standard lets you make:** *"my exact submission artifact
will be accepted by the grader, was produced within the runtime budget,
without network access, and its score estimate comes from data I did not
iterate on."*

A submit costs you a daily attempt. Each check below removes one way of
wasting it.

---

## The four failure modes of a wasted submit

| # | What kills the submit | ATLAS check |
| --- | --- | --- |
| 1 | The grader rejects/truncates the file (missing task, missing test output, missing `attempt_2`) | `validate-submission --kaggle-strict` |
| 2 | The notebook times out or dies (budget, hidden internet dependency) | `batch_runner.py --enforce-budget --offline` |
| 3 | The public-eval score was an overfit illusion — semi-private comes in far lower | sealed holdout (`create-holdout` → one-shot reveal) |
| 4 | The single score you trusted was sampling noise | variance across repeated runs |

The **certificate** (`presubmit_cli.py certify`) runs all four and emits a
one-page go/no-go.

---

## 1. Protocol parity (any integration path)

```bash
# Will Kaggle accept and FULLY score this exact file?
python src/submission_cli.py validate-submission \
  --path path/to/submission.json --kaggle-strict
```

Errors = grader-fatal (absent task, uncovered test example, missing
`attempt_1`/`attempt_2`). Warnings = ignored-but-suspicious (extra tasks,
attempts beyond 2). Every scored run now also prints **`kaggle_score`** —
the leaderboard metric (per task: fraction of test outputs where any of the
first 2 attempts is exact; averaged across tasks). It sits between the
platform's `solved_rate` and the all-or-nothing `task_solved_rate`.

## 2. Run the whole pipeline under the judge's eyes

Your system stays *your* repo; ATLAS orchestrates and measures. Declare it
once (`atlas_project.json`):

```json
{
  "manifest_kind": "solver_project",
  "name": "my-pipeline",
  "version": "1.0.0",
  "command": ["python", "run_my_system.py"],
  "workdir": ".",
  "artifact": "out/submission.json",
  "budget_hours": 12.0,
  "gpu_telemetry": true
}
```

Contract (two env vars — the only integration your code needs):

- `ATLAS_TASKS_DIR` — official ARC task JSON, **test outputs stripped**
  (the fairness invariant holds by construction).
- `ATLAS_SUBMISSION_PATH` — where to write your Kaggle-style
  `submission.json`.

```bash
python src/batch_runner.py --project path/to/atlas_project.json \
  --offline --enforce-budget --experiment-id pre-submit
```

`--offline` runs your command in a network-isolated namespace
(`unshare -rn`; use `docker run --network none` where unavailable) — the
cheapest way to discover the `pip install` / API call that would kill a
Kaggle notebook. `--enforce-budget` terminates past `budget_hours`.
`--resume` skips execution when the artifact already exists.
`batch_manifest.json` records wall time, budget utilization, exit code,
GPU telemetry, and the offline flag — the certificate consumes it.

Runnable example: [`examples/batch_project/`](../examples/batch_project/)
(`make batch-example`).

## 3. Sealed holdout — stop grading your own homework

```bash
python src/presubmit_cli.py create-holdout --seed 42 --holdout-fraction 0.3
```

Splits the mounted pack into **dev** (iterate freely) and **holdout**
(sealed: sha256 over the id lists, creation stamped). `certify` scores dev
only — until the day you actually submit:

```bash
python src/presubmit_cli.py certify --submission ... \
  --holdout configs/holdout_arc_agi_2.json --reveal-holdout   # ONE-shot
```

The reveal is stamped into the seal file; a second `--reveal-holdout`
refuses. The seal is tamper-*evident*, not tamper-proof — its job is to
make peeking a deliberate, visible act.

## 4. The certificate

```bash
python src/presubmit_cli.py certify \
  --submission artifacts/batch/my-pipeline/submission.json \
  --holdout configs/holdout_arc_agi_2.json \
  --batch-manifest artifacts/batch/my-pipeline/batch_manifest.json
```

→ `reports/presubmit_certificate_<solver>.md`, verdict first:

- **NO-GO** — the grader or the notebook runtime would reject this exact
  artifact (format/coverage errors, budget exceeded, non-zero exit,
  broken seal).
- **GO WITH WARNINGS** — accepted, but part of the standard is unverified
  (no offline run, no holdout, variance unknown).
- **GO** — all six checks pass.

Exit code is 0 unless NO-GO, so the certificate slots into your own CI.

---

## What this standard deliberately does NOT do

- **Replicate Kaggle hardware.** Wall time on your box ≠ wall time on
  Kaggle's GPUs; the budget check catches *order-of-magnitude* problems,
  and the certificate says exactly what was measured.
- **Host or verify a leaderboard.** All scores are `local_pilot_partial`;
  the observatory provides public context only.
- **Touch your training loop.** The batch contract is two env vars.

Demo of the whole loop, offline, in under a minute: `make presubmit-example`.

Related: [`EVALUATE_YOUR_SOLVER.md`](EVALUATE_YOUR_SOLVER.md) ·
[`SOLVER_ADAPTERS.md`](SOLVER_ADAPTERS.md) ·
[`BENCHMARK_PACKS.md`](BENCHMARK_PACKS.md)

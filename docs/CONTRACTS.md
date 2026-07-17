# ATLAS public contracts (frozen for 0.x)

**Compatibility policy (0.x):** fields and CLI flags may be **added**. Renames
or removals wait for a **major** version. Existing `python src/<entrypoint>.py`
invocations remain supported alongside `pip install -e .` console scripts.

Schemas (machine-readable): [`schemas/`](../schemas/).

---

## 1. Metrics

| Name | Granularity | Meaning |
| --- | --- | --- |
| `exact_match_rate` | attempt row | Exact attempt rows / all attempt rows |
| `solved_rate` | item `(task, test_example)` | Pass@k: any attempt exact |
| `task_solved_rate` | task | ARC-official: **all** test examples solved |
| `kaggle_score` | task mean | Leaderboard-style: per task, fraction of test outputs where any of attempts 1–2 is exact; averaged across tasks |
| `parse_error_rate` | attempt | Output not readable as a grid |
| `execution_error_rate` | attempt | Adapter/runtime failure; on submissions often = **coverage gap** (task absent) |

See Decision 21 (`src/DECISIONS.md`) and `docs/PRESUBMIT_STANDARD.md`.

---

## 2. Submission artifacts

- **File:** Kaggle-style `submission.json` — schema
  [`schemas/submission_kaggle.schema.json`](../schemas/submission_kaggle.schema.json).
- **Directory:** one `<task_id>.json` per task (same grid/attempt shapes).
- **Kaggle-strict:** every pack task, every test example, `attempt_1` **and**
  `attempt_2` present (`validate-submission --kaggle-strict`).

Partial submissions scored against a full pack mark missing items as
`execution_error` (coverage visibility). Scope smokes with `--task-id` /
`--limit`.

---

## 3. Batch project (`atlas_project.json`)

Schema: [`schemas/atlas_project.schema.json`](../schemas/atlas_project.schema.json).

**Env contract** (only integration your pipeline needs):

| Variable | Meaning |
| --- | --- |
| `ATLAS_TASKS_DIR` | Read official ARC JSON here; **test outputs stripped** |
| `ATLAS_SUBMISSION_PATH` | Write Kaggle-style `submission.json` here |

`--benchmark-pack <id>` on `atlas-batch` stages/scores only task ids present
in that pack’s `tasks/` directory (safe when the local Parquet mixes packs).

Example: [`examples/batch_project/`](../examples/batch_project/).

---

## 4. Holdout split

Schema: [`schemas/holdout_split.schema.json`](../schemas/holdout_split.schema.json).

Created by `atlas-presubmit create-holdout` / `presubmit_cli.py create-holdout`.
Reveal is **one-shot** (`--reveal-holdout`); a second reveal is rejected.

---

## 5. Certificate

Human artifact: `reports/presubmit_certificate_<solver>.md` (gitignored;
regenerate with `make presubmit-example`).

Logical checks: [`schemas/presubmit_certificate.schema.json`](../schemas/presubmit_certificate.schema.json).

`certify --batch-manifest` scopes Kaggle-strict to `task_ids` recorded in the
batch manifest when `--benchmark-pack` is omitted. Pass `--benchmark-pack`
explicitly for holdout creation against a mixed local Parquet.

| Verdict | Meaning |
| --- | --- |
| `GO` | All required checks passed |
| `GO WITH WARNINGS` | Artifact is grader-safe; optional checks (offline / holdout / variance) unverified |
| `NO-GO` | Kaggle would reject or fatally mis-score the artifact |

---

## 6. Console scripts ↔ source CLIs

| Script | Equivalent |
| --- | --- |
| `atlas-etl` | `python src/main.py` |
| `atlas-evaluate` | `python src/run_evaluation.py` |
| `atlas-submission` | `python src/submission_cli.py` |
| `atlas-batch` | `python src/batch_runner.py` |
| `atlas-presubmit` | `python src/presubmit_cli.py` |
| `atlas-analytics` | `python src/build_analytics.py` |
| `atlas-public-results` | `python src/public_results_cli.py` |

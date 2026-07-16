# Quickstart — evaluate your ARC solver without rewriting it

**Audience:** you already have an ARC solver project (or a Kaggle/ARC Prize
`submission.json`). You want a local final judge before uploading.

**You do not need to** implement `solve(task)` in Python, install our
providers, or reshape your training loop.

Preferred order (lowest friction first):

1. Evaluate a **submission.json**
2. Evaluate a **directory of per-task prediction JSON files**
3. Wrap an existing **CLI** (stdin/stdout)
4. Only then: native Python / HTTP adapters

---

## Prerequisites (once)

```bash
pip install -r requirements.txt          # pandas, pyarrow, …
python scripts/fetch_arc_data.py --sample
python src/main.py                       # builds data/parquet/evaluation/
```

---

## A) Evaluate a Kaggle-style `submission.json`

Shape (ARC Prize / Kaggle):

```json
{
  "<task_id>": [
    {"attempt_1": [[0,1],[2,3]], "attempt_2": [[0,1],[2,3]]}
  ]
}
```

Bundled example: `examples/external_solver/submission.json`

```bash
# 1. Validate structure + grids (no scoring yet)
python src/submission_cli.py validate-submission \
  --path examples/external_solver/submission.json

# Optional: check coverage against your tasks Parquet
python src/submission_cli.py validate-submission \
  --path examples/external_solver/submission.json \
  --against-tasks data/parquet/evaluation

# 2. Score (writes a run under data/parquet/inference/runs/)
python src/submission_cli.py evaluate-submission \
  --path examples/external_solver/submission.json \
  --solver-name my-system --experiment-id pre-submit

# Same thing via the main orchestrator:
python src/run_evaluation.py \
  --submission-file examples/external_solver/submission.json \
  --solver-name my-system --experiment-id pre-submit

# 3. Analytics / report
python src/build_analytics.py --experiment-id pre-submit
```

Minimal registry entry (`configs/solvers.json`):

```json
"my-kaggle-submission": {
  "adapter": "submission_file",
  "path": "path/to/your/submission.json",
  "enabled": true
}
```

Then: `python src/run_evaluation.py --solver my-kaggle-submission`

---

## B) Evaluate a directory of per-task predictions

Layout:

```
predictions/
  sample01.json
  sample02.json
```

Each file can be:

- `{"attempt_1": grid, "attempt_2": grid}`
- `{"prediction": grid}`
- `[{"attempt_1": grid}, ...]`  (one object per test example)
- a bare grid `[[...], ...]`

Bundled example: `examples/external_solver/predictions/`

```bash
python src/submission_cli.py validate-submission \
  --path examples/external_solver/predictions

python src/submission_cli.py evaluate-submission \
  --path examples/external_solver/predictions \
  --solver-name my-dir-solver --experiment-id pre-submit-dir
```

Registry:

```json
"my-prediction-dir": {
  "adapter": "submission_dir",
  "path": "path/to/your/predictions/",
  "enabled": true
}
```

(`adapter_type` is accepted as an alias of `adapter`.)

---

## C) Evaluate a CLI solver without rewriting it

If your solver is a binary/script, wrap stdin/stdout once:

- **stdin:** task JSON (no ground truth)
- **stdout:** `{"prediction": grid}` or `{"attempts": [grid, ...]}`

Template: `examples/external_solver/cli_wrapper_template.py`

```bash
python src/run_evaluation.py --solver my-cli-solver --limit 3 --dry-run
```

Registry (`subprocess_cli` aliases to `subprocess`):

```json
"my-cli-solver": {
  "adapter": "subprocess_cli",
  "command": ["python", "examples/external_solver/cli_wrapper_template.py"],
  "timeout_s": 120,
  "enabled": true
}
```

---

## Import → canonical artifact (optional)

Normalize any supported artifact to a portable `atlas_canonical_v1` JSON:

```bash
python src/submission_cli.py import-submission \
  --path examples/external_solver/submission.json \
  --out artifacts/imports/my_canonical.json
```

That file can be re-scored later with `--submission-file`.

---

## What “good” looks like

| Step | Expect |
| --- | --- |
| `validate-submission` | `status: OK`, 0 errors |
| `evaluate-submission` | run dir + `_manifest.json` with `execution_mode` `submission_file` or `submission_dir` |
| `build_analytics.py` | `summary_by_solver.csv`, `solved_rate` (pass@k) |

Invalid JSON, non-rectangular grids, or colors outside 0–9 fail validation
with explicit codes — they are **not** silently fixed.

---

## More detail

- Adapter recipes / reference solvers: `docs/SOLVER_ADAPTERS.md`
- Operator runbook: `docs/RUNBOOK.md`
- Snippet gallery: `examples/external_solver/solvers.snippet.json`

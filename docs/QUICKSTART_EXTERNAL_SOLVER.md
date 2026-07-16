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

Copy-paste examples below use the bundled fixtures under
`examples/external_solver/`.

---

## Prerequisites (once)

```bash
pip install -r requirements.txt
python scripts/fetch_arc_data.py --sample
python src/main.py
# or: python src/main.py --benchmark-pack example_local_pack
# ARC-AGI-2: see docs/BENCHMARK_PACKS.md (local pack, no auto-fetch)
```

---

## A) Evaluate a Kaggle-style `submission.json`

```bash
python src/submission_cli.py validate-submission \
  --path examples/external_solver/submission.json

python src/submission_cli.py evaluate-submission \
  --path examples/external_solver/submission.json \
  --solver-name my-system --experiment-id pre-submit

python src/build_analytics.py --experiment-id pre-submit
```

Minimal registry entry:

```json
"my-kaggle-submission": {
  "adapter": "submission_file",
  "path": "path/to/your/submission.json",
  "enabled": true
}
```

---

## B) Evaluate a directory of per-task predictions

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

Template: `examples/external_solver/cli_wrapper_template.py`

```json
"my-cli-solver": {
  "adapter": "subprocess_cli",
  "command": ["python", "examples/external_solver/cli_wrapper_template.py"],
  "timeout_s": 120,
  "enabled": true
}
```

```bash
python src/run_evaluation.py --solver my-cli-solver --limit 3 --dry-run
```

---

## Import → canonical artifact (optional)

```bash
python src/submission_cli.py import-submission \
  --path examples/external_solver/submission.json \
  --out artifacts/imports/my_canonical.json
```

---

## What “good” looks like

| Step | Expect |
| --- | --- |
| `validate-submission` | `status: OK`, 0 errors |
| `evaluate-submission` | run + `_manifest.json` (`submission_file` / `submission_dir`) |
| `build_analytics.py` | `summary_by_solver.csv` with `solved_rate` |

Invalid JSON / non-rectangular grids / colors outside 0–9 fail with explicit
codes — they are not silently fixed.

More detail: `docs/SOLVER_ADAPTERS.md`, `examples/external_solver/`.

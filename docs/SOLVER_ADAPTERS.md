# ARC Solver Evaluation Platform — how to plug a new solver in

> **External authors: start with
> [`docs/QUICKSTART_EXTERNAL_SOLVER.md`](QUICKSTART_EXTERNAL_SOLVER.md)**
> (submission.json / prediction directory / CLI wrap in ~5 minutes).
> This page is the deeper adapter reference.

**Audience:** researchers who already have (or will produce) an ARC solving
system and want comparable, reproducible scores from this platform before a
real competition submission.

**What this platform is:** a solver-agnostic final judge. It owns task
ingestion, orchestration, parsing, scoring, failure taxonomy, analytics, and
replay manifests.

**What it is not:** an ARC solver. It does not improve your leaderboard score.

**Design principle:** prefer submission-first integration. Do not rewrite
your solver for this framework — bring artifacts the platform can judge.

---

## Recommended adapter order

| Priority | Adapter | When |
| --- | --- | --- |
| 1 | `submission_file` | You have (or can export) Kaggle-style `submission.json` |
| 2 | `submission_dir` | You have one JSON file per `task_id` |
| 3 | `subprocess` / `subprocess_cli` | You have a CLI; wrap stdin/stdout once |
| 4 | `http` / `in_process` | You already expose a service or Python API |

Normalization + validation live in `src/submission_io.py`
(canonical fields: `task_id`, `test_index`, `candidate_rank`,
`predicted_grid`, `source_format`, `source_path`).

CLI for humans: `python src/submission_cli.py --help`
(`validate-submission`, `import-submission`, `evaluate-submission`).

---

## The contract in one page

Every adapter implements:

```text
result = solver.solve(task)   # SolverTask → SolverResult
```

Defined in `src/solvers.py`. The platform never peeks inside your algorithm.
Submission adapters implement this internally from your artifact — **you**
do not have to.

### Wire payload (subprocess stdin / HTTP body)

Ground truth is **never** included (`SolverTask.to_wire()` strips it):

```json
{
  "task_id": "00576224",
  "test_example_id": 1,
  "train": [{"input": [[...]], "output": [[...]]}, ...],
  "test":  [{"input": [[...]]}]
}
```

### Accepted solver outputs (most structured first)

```json
{"attempts": [[[...]], [[...]]], "metadata": {"optional": true}}
```

```json
{"prediction": [[...]], "metadata": {}}
```

Or any text — the same grid parser used for LLM completions scans it.

---

## Adapter types

| Adapter | Class | When to use |
| --- | --- | --- |
| `submission_file` | `SubmissionFileSolver` | Kaggle-style / canonical JSON file (**recommended**) |
| `submission_dir` | `SubmissionDirSolver` | Directory of `<task_id>.json` (**recommended**) |
| `subprocess` / `subprocess_cli` | `CommandSolver` | Existing CLI; aliases accepted in registry |
| `http` | `HTTPSolver` | Long-running solver service |
| `in_process` | `LLMDirectSolver` | Single-prompt LLM via `providers.py` |

Register entries in `configs/solvers.json`. Built-ins include
`mock-baseline`, `example-submission-file`, `example-submission-dir`.

```bash
python src/run_evaluation.py --list-solvers
python src/submission_cli.py validate-submission --path examples/external_solver/submission.json
python src/run_evaluation.py --submission-file path/to/submission.json --solver-name mine
python src/run_evaluation.py --submission-dir path/to/preds/ --solver-name mine
```

---

## Recipes for external systems

You do **not** need this repo to contain third-party solver source trees.
Export predictions as `submission.json` (or a per-task directory) and use
the submission adapters. For a live CLI, start from
`examples/external_solver/cli_wrapper_template.py`.

Historical ARC Prize systems (NVARC, ARChitects, Icecuber, BARC, McARGA, …)
informed the adapter design; they are not dependencies of this platform.

---

## Checklist for a new solver

1. Prefer exporting predictions (file or dir) over rewriting code.
2. `python src/submission_cli.py validate-submission --path ...`
3. `evaluate-submission` with `--limit 3`, then `build_analytics.py`.
4. Only if needed: register a `subprocess_cli` wrapper.
5. Keep secrets in environment variables, never in the registry.

## Fairness invariant

`expected_output` exists on `SolverTask` for scoring and the deterministic
mock backend only. Adapters must not forward it. Submission artifacts never
receive ground truth from the platform.

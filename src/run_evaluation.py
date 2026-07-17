"""
Evaluate an ARC solver over normalized tasks and persist scored results.

This is the platform's execution orchestrator. The flow, per evaluation item
(task × test example):

    task ingestion (task_loader)  →  solver execution (solvers.py adapter)
    →  prediction parsing/validation (grid_parser)  →  deterministic scoring
    (evaluator)  →  failure classification (failure_taxonomy)  →  Parquet row

Rows land in one directory per run:

    data/parquet/inference/runs/<run_id>/part-NNNN.parquet  (+ _manifest.json)

The directory name is deliberately NOT Hive-style ("run_id=..."): run_id is
kept as a physical column in every part file so each file is self-contained,
and pyarrow can read the whole runs/ tree as one dataset without partition-
key/column conflicts. Rows are flushed incrementally (every FLUSH_EVERY
items and on interruption) so partial progress is never lost. Per-item
solver failures become rows with failure_mode="execution_error" instead of
aborting the batch.

Selecting what to evaluate (first match wins):
    --submission-file sub.json      judge a Kaggle-style submission offline
    --submission-dir preds/         judge a directory of per-task JSON files
    --solver <registry-name>        anything in configs/solvers.json (+ built-ins)
    --provider X --model Y          ad-hoc LLM-direct solver (mock|openai|...)

Configuration: every flag falls back to an ATLAS_* environment variable
(see src/config.py and .env.example) — flag > env > default.

Examples (from the repository root):
    python src/run_evaluation.py --list-solvers
    python src/run_evaluation.py --solver mock-baseline --experiment-id demo
    python src/run_evaluation.py --submission-file sub.json --solver-name my-system
    python src/run_evaluation.py --submission-dir preds/ --solver-name my-system
    python src/run_evaluation.py --provider claude --model claude-opus-4-8 --limit 5
    python src/run_evaluation.py --provider openai --model kimi-k2.6 --attempts 2  # pass@2
    python src/run_evaluation.py --solver mock-baseline --dry-run
"""

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from config import ConfigError
from benchmark_packs import (
    BenchmarkPackError,
    format_pack_list,
    metadata_for_evaluation_items,
    resolve_pack,
)
from contracts import (
    EVALUATION_PIPELINE_VERSION,
    EVALUATION_RESULTS_SCHEMA,
    EVALUATION_SCHEMA_VERSION,
    validate_columns,
)
from evaluator import evaluate_prediction
from failure_taxonomy import classify_failure
from grid_parser import (
    PARSE_NOT_ATTEMPTED,
    ParseResult,
    parse_grid_object,
    parse_response,
    serialize_grid,
)
from manifest import git_commit_sha, portable_path, write_manifest
from prompt_builder import PROMPT_VERSION_DEFAULT
from providers import PROVIDERS, STATUS_OK, ProviderConfigError
from solver_registry import create_solver, format_registry, load_registry
from solvers import (
    LLMDirectSolver,
    SolverAttempt,
    SolverError,
    SolverTask,
    SubmissionDirSolver,
    SubmissionFileSolver,
)
from task_loader import (
    DEFAULT_TASKS_PARQUET,
    build_evaluation_items,
    load_tasks_dataframe,
    reconstruct_tasks,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"
FLUSH_EVERY = 10

# Explicit dtypes so every part file (and every run) carries the same Arrow
# schema even when a column is all-NULL in one chunk (e.g. parse_error).
_CHUNK_DTYPES = {
    "run_id": "string", "experiment_id": "string",
    "solver_name": "string", "solver_family": "string",
    "solver_version": "string", "execution_mode": "string",
    "pipeline_version": "string",
    "provider": "string", "model_name": "string", "prompt_version": "string",
    "task_id": "string", "split": "string",
    "test_example_id": "int64", "source_task_partition": "string",
    "pack_id": "string", "benchmark_family": "string",
    "benchmark_name": "string", "benchmark_version": "string",
    "split_name": "string", "task_source": "string",
    "attempt": "int64",
    "prompt_text": "string", "raw_output": "string",
    "predicted_grid_json": "string", "expected_output_grid_json": "string",
    "status": "string", "error_message": "string",
    "latency_ms": "float64", "cost_estimate_usd": "float64",
    "input_tokens": "Int64", "output_tokens": "Int64",
    "started_at": "string", "finished_at": "string",
    "parse_status": "string", "parse_error": "string",
    "is_exact_match": "boolean", "same_shape": "boolean",
    "cell_accuracy": "Float64", "n_diff_cells": "Int64",
    "failure_mode": "string", "failure_detail": "string",
    "solver_metadata": "string",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_run_id(solver_name: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe = "".join(c if c.isalnum() or c in "-_." else "-" for c in solver_name)
    return f"{timestamp}_{safe}_{uuid.uuid4().hex[:8]}"


def evaluate_item(solver, item: dict) -> tuple:
    """
    Full pipeline for one (task, test example): solve → parse → score →
    classify. Returns (rows, result): one row dict per attempt (at least
    one, even on execution errors) plus the raw SolverResult so the caller
    can aggregate token usage into the run manifest.
    """
    task = SolverTask(
        task_id=item["task_id"],
        test_example_id=item["test_example_id"],
        train=item["train"],
        test_input=item["test_input"],
        expected_output=item["expected_output"],
        source_task_partition=item["source_task_partition"],
    )
    started_at = utc_now_iso()
    try:
        result = solver.solve(task)
    except Exception as exc:  # per-item resilience: any bug becomes a row
        logging.exception("[%s] solver raised unexpectedly", item["task_id"])
        from solvers import SolverResult
        result = SolverResult(status="error",
                              error_message=f"unexpected solver exception: {exc}")
    finished_at = utc_now_iso()

    info = solver.describe()
    expected = item["expected_output"]
    attempts = result.attempts or [SolverAttempt(attempt=1)]
    metadata_json = (json.dumps(result.metadata, sort_keys=True)
                     if result.metadata else None)

    rows = []
    for index, attempt in enumerate(attempts):
        if result.status != STATUS_OK:
            parsed = ParseResult(
                PARSE_NOT_ATTEMPTED,
                "solver execution failed; parsing not attempted", None, None,
            )
        elif attempt.grid is not None:
            parsed = parse_grid_object(attempt.grid)
        else:
            parsed = parse_response(attempt.raw_output)

        evaluation = evaluate_prediction(parsed.predicted_grid_obj, expected)
        failure_mode, failure_detail = classify_failure(
            solver_status=result.status,
            parse_status=parsed.parse_status,
            evaluation=evaluation,
            predicted_grid=parsed.predicted_grid_obj,
            expected_grid=expected,
            solver_error=result.error_message,
            parse_error=parsed.parse_error,
        )

        first = index == 0  # computational metrics are stamped once per item
        rows.append({
            "run_id": None,  # filled by the caller (same value for all rows)
            "experiment_id": None,
            "solver_name": solver.name,
            "solver_family": solver.family,
            "solver_version": solver.version,
            "execution_mode": solver.execution_mode,
            "pipeline_version": EVALUATION_PIPELINE_VERSION,
            "provider": info.get("provider"),
            "model_name": info.get("model_name"),
            "prompt_version": info.get("prompt_version"),
            "task_id": item["task_id"],
            "split": "test",
            "test_example_id": item["test_example_id"],
            "source_task_partition": item["source_task_partition"],
            "pack_id": item.get("pack_id", "unknown"),
            "benchmark_family": item.get("benchmark_family", "unknown"),
            "benchmark_name": item.get("benchmark_name", "unknown"),
            "benchmark_version": item.get("benchmark_version", "unknown"),
            "split_name": item.get("split_name", "unknown"),
            "task_source": item.get("task_source", "unknown"),
            "attempt": attempt.attempt,
            "prompt_text": result.prompt_text if first else None,
            "raw_output": attempt.raw_output,
            "predicted_grid_json": parsed.predicted_grid_json,
            "expected_output_grid_json":
                serialize_grid(expected) if expected is not None else None,
            "status": result.status,
            "error_message": result.error_message,
            "latency_ms": float(result.latency_ms) if first else 0.0,
            "cost_estimate_usd": float(result.cost_estimate_usd) if first else 0.0,
            "input_tokens": result.input_tokens if first else None,
            "output_tokens": result.output_tokens if first else None,
            "started_at": started_at,
            "finished_at": finished_at,
            "parse_status": parsed.parse_status,
            "parse_error": parsed.parse_error,
            "is_exact_match": evaluation.is_exact_match,
            "same_shape": evaluation.same_shape,
            "cell_accuracy": evaluation.cell_accuracy,
            "n_diff_cells": evaluation.n_diff_cells,
            "failure_mode": failure_mode,
            "failure_detail": failure_detail,
            "solver_metadata": metadata_json,
        })
    return rows, result


def build_manifest_payload(args, solver_info: dict, run_id: str, run_dir: Path,
                           n_items: int, status: str, run_started_at: str,
                           finished_at=None, n_rows_written=None,
                           token_totals=None, benchmark_meta=None) -> dict:
    """Everything needed to replay a run: code, solver config, data, filters."""
    return {
        "manifest_kind": "evaluation_run",
        "status": status,  # "running" (in progress or crashed) | "completed"
        "run_id": run_id,
        "experiment_id": args.experiment_id,
        # Full solver config snapshot (never contains secrets — see
        # BaseSolver.describe): name, family, version, execution mode, and
        # adapter-specific settings (provider/model/prompt, command, url...).
        "solver": solver_info,
        "benchmark": dict(benchmark_meta or {}),
        "pipeline_version": EVALUATION_PIPELINE_VERSION,
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "git_commit": git_commit_sha(),
        "started_at": run_started_at,
        "finished_at": finished_at,
        "input_path": portable_path(args.input_path),
        "output_path": portable_path(run_dir),
        "n_items_planned": n_items,
        "n_rows_written": n_rows_written,
        # Aggregated from backend usage reports; None until completion or
        # when the solver never reported usage (mock, subprocess, submission).
        "total_input_tokens": (token_totals or {}).get("input"),
        "total_output_tokens": (token_totals or {}).get("output"),
        "filters": {
            "limit": args.limit,
            "task_id": args.task_id,
            "split": args.split,
        },
    }


def flush_chunk(rows: list, run_dir: Path, part_index: int) -> int:
    """Validates and writes pending rows as one part file. Returns next index."""
    if not rows:
        return part_index
    chunk = pd.DataFrame(rows).astype(_CHUNK_DTYPES)
    validate_columns(chunk, EVALUATION_RESULTS_SCHEMA, label="evaluation results")
    run_dir.mkdir(parents=True, exist_ok=True)
    part_path = run_dir / f"part-{part_index:04d}.parquet"
    chunk.to_parquet(part_path, engine="pyarrow", index=False)
    logging.info("Flushed %d row(s) → %s", len(chunk), part_path)
    rows.clear()
    return part_index + 1


def print_summary(all_rows: list, run_dir: Path, run_id: str,
                  token_totals: dict, experiment_id: str | None = None) -> None:
    df = pd.DataFrame(all_rows)
    item_key = ["task_id", "test_example_id"]
    n_items = df.groupby(item_key, sort=False).ngroups
    n_tasks = df["task_id"].nunique()
    evaluable = df["is_exact_match"].notna().sum()
    exact_rows = (df["is_exact_match"] == True).sum()  # noqa: E712 — None-safe
    item_solved = (
        df.assign(_exact=df["is_exact_match"].eq(True).fillna(False))
        .groupby(item_key, sort=False)["_exact"].any()
        .reset_index(name="_item_solved")
    )
    solved_items = int(item_solved["_item_solved"].sum())
    # ARC-official granularity: a task counts as solved only when EVERY one of
    # its test examples is solved (each solved = any attempt matched).
    solved_tasks = int(
        item_solved.groupby("task_id")["_item_solved"].all().sum()
    )
    print("\n" + "=" * 62)
    print(f"EVALUATION SUMMARY  {run_id}")
    print("=" * 62)
    print(f"solver              : {df['solver_name'].iloc[0]} "
          f"({df['solver_family'].iloc[0]}, {df['execution_mode'].iloc[0]})")
    if "benchmark_name" in df.columns:
        print(f"benchmark           : {df['benchmark_name'].iloc[0]} "
              f"({df['benchmark_version'].iloc[0]}, pack={df['pack_id'].iloc[0]})")
    print(f"items / attempt rows: {n_items} / {len(df)}")
    print(f"solved_rate (items) : {solved_items} / {n_items} test example(s)")
    print(f"task_solved_rate    : {solved_tasks} / {n_tasks} "
          "(all test examples correct — ARC-official)")
    from kaggle_protocol import kaggle_score_from_rows
    kaggle = kaggle_score_from_rows(df)
    if kaggle["kaggle_score"] is not None:
        print(f"kaggle_score        : {kaggle['kaggle_score']:.4f} "
              "(leaderboard metric — per-task mean over test outputs, "
              "attempts 1-2)")
    print(f"exact attempt rows  : {int(exact_rows)} / {int(evaluable)} evaluable")
    if df["cell_accuracy"].notna().any():
        print(f"avg cell accuracy   : {df['cell_accuracy'].mean():.3f} "
              "(over valid predictions; secondary metric)")
    print(f"avg latency         : {df['latency_ms'].mean():.1f} ms (attempt rows)")
    print(f"total cost estimate : ${df['cost_estimate_usd'].sum():.4f}")
    if token_totals.get("input") is not None or token_totals.get("output") is not None:
        print(f"tokens in / out     : {token_totals.get('input')} / "
              f"{token_totals.get('output')} (backend-reported)")
    print("failure modes       :")
    counts = df["failure_mode"].fillna("(not classifiable)").value_counts()
    for mode, count in counts.items():
        print(f"    {mode:20s} {count}")
    # Submission adapters mark missing (task, test) as execution_error so
    # coverage gaps stay visible — that is not a solver crash. Surface it
    # explicitly so a partial smoke is not mistaken for a broken judge.
    if "error_message" in df.columns and len(df):
        missing = (
            df["error_message"].fillna("")
            .astype(str).str.contains("not present in submission", regex=False)
        )
        n_missing = int(missing.sum())
        if n_missing:
            print(
                f"note: {n_missing} of {len(df)} items had no prediction in the "
                "submission (counted as execution_error = coverage gap, not "
                "solver failure). Use --task-id / --limit to scope."
            )
    print(f"output              : {run_dir}")
    exp = experiment_id
    if not exp and "experiment_id" in df.columns and len(df):
        exp = df["experiment_id"].iloc[0]
    if exp:
        print(f"next step           : python src/build_analytics.py "
              f"--experiment-id {exp}")
    else:
        print("next step           : python src/build_analytics.py")


def build_solver(args, parser: argparse.ArgumentParser):
    """Resolve which solver to evaluate (see module docstring for precedence)."""
    chosen = [flag for flag, value in (
        ("--submission-file", args.submission_file),
        ("--submission-dir", args.submission_dir),
        ("--solver", args.solver),
        ("--provider/--model", args.provider or args.model),
    ) if value]
    if len(chosen) > 1:
        parser.error(f"Choose ONE way to select a solver — got {', '.join(chosen)}.")

    if args.submission_file:
        name = args.solver_name or Path(args.submission_file).stem
        return SubmissionFileSolver(
            name=name, path=args.submission_file,
            version=args.solver_version or "unversioned",
        )

    if args.submission_dir:
        name = args.solver_name or Path(args.submission_dir).name
        return SubmissionDirSolver(
            name=name, path=args.submission_dir,
            version=args.solver_version or "unversioned",
        )

    solver_name = config.resolve(args.solver, config.ENV_SOLVER)
    if solver_name:
        registry = load_registry(args.registry)
        return create_solver(solver_name, registry)

    provider = config.resolve(args.provider, config.ENV_PROVIDER,
                              config.DEFAULT_PROVIDER)
    config.validate_choice(provider, PROVIDERS, "provider",
                           env_name=config.ENV_PROVIDER)
    model = config.resolve(args.model, config.ENV_MODEL)
    if not model:
        parser.error(
            "Select a solver: `--solver <name>` (try `--list-solvers`), "
            "`--submission-file sub.json`, `--submission-dir preds/`, or an "
            f"ad-hoc LLM run via `--provider X --model Y` "
            f"(or export {config.ENV_MODEL}). "
            "External authors: see docs/QUICKSTART_EXTERNAL_SOLVER.md."
        )
    prompt_version = config.resolve(args.prompt_version,
                                    config.ENV_PROMPT_VERSION,
                                    PROMPT_VERSION_DEFAULT)
    n_attempts = args.attempts if args.attempts is not None else config.attempts()
    if n_attempts < 1:
        parser.error("--attempts must be >= 1 (ARC-AGI official pass@2 → 2).")
    return LLMDirectSolver(
        provider_name=provider, model_name=model,
        prompt_version=prompt_version, name=args.solver_name,
        version=args.solver_version or "unversioned",
        n_attempts=n_attempts,
    )


def default_runs_root() -> Path:
    """<ATLAS_OUTPUT_ROOT>/inference/runs when set, else the repo default."""
    root = config.output_root()
    return (root / "inference" / "runs") if root else DEFAULT_RUNS_DIR


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate an ARC solver (registry entry, submission file, "
                    "or ad-hoc LLM configuration) over normalized tasks. "
                    "Flags fall back to ATLAS_* environment variables.",
    )
    select = parser.add_argument_group("solver selection (choose one)")
    select.add_argument("--solver", default=None,
                        help="registered solver name "
                             f"(see --list-solvers; or ${config.ENV_SOLVER})")
    select.add_argument("--submission-file", type=Path, default=None,
                        help="judge a Kaggle-style submission.json offline")
    select.add_argument("--submission-dir", type=Path, default=None,
                        help="judge a directory of per-task <task_id>.json "
                             "prediction files")
    select.add_argument("--provider", choices=sorted(PROVIDERS), default=None,
                        help="ad-hoc LLM-direct solver: execution backend "
                             f"(${config.ENV_PROVIDER})")
    select.add_argument("--model", default=None,
                        help="ad-hoc LLM-direct solver: model name "
                             f"(${config.ENV_MODEL})")
    select.add_argument("--prompt-version", default=None,
                        help="ad-hoc LLM-direct solver: prompt registry entry "
                             f"(default: {PROMPT_VERSION_DEFAULT}, or "
                             f"${config.ENV_PROMPT_VERSION})")
    select.add_argument("--attempts", type=int, default=None,
                        help="ad-hoc LLM-direct solver: independent samples "
                             "per item (ARC-AGI official pass@2 → 2; default 1, "
                             f"or ${config.ENV_ATTEMPTS})")
    parser.add_argument("--solver-name", default=None,
                        help="override the recorded solver_name (ad-hoc and "
                             "submission modes)")
    parser.add_argument("--solver-version", default=None,
                        help="recorded solver_version for ad-hoc/submission "
                             "modes (registry entries carry their own)")
    parser.add_argument("--registry", type=Path, default=None,
                        help="solver registry JSON (default: configs/solvers.json)")
    parser.add_argument("--list-solvers", action="store_true",
                        help="print the solver registry and exit")
    parser.add_argument("--input-path", type=Path, default=None,
                        help="tasks Parquet directory (default: "
                             f"{DEFAULT_TASKS_PARQUET}, or ${config.ENV_INPUT_PATH})")
    parser.add_argument("--benchmark-pack", default=None,
                        help="override pack metadata stamp "
                             f"(registered id; or ${config.ENV_BENCHMARK_PACK})")
    parser.add_argument("--benchmark-pack-path", type=Path, default=None,
                        help="override pack metadata from a local pack root")
    parser.add_argument("--list-benchmark-packs", action="store_true",
                        help="print registered packs and exit")
    parser.add_argument("--output-path", type=Path, default=None,
                        help="run output directory (default: "
                             f"<runs root>/<run_id>; runs root is {DEFAULT_RUNS_DIR} "
                             f"or ${config.ENV_OUTPUT_ROOT}/inference/runs)")
    parser.add_argument("--limit", type=int, default=None,
                        help="evaluate at most N (task, test example) items")
    parser.add_argument("--split", choices=["test"], default="test",
                        help="which split to predict (MVP supports only 'test')")
    parser.add_argument("--task-id", default=None,
                        help="evaluate only these task ids (comma-separated)")
    parser.add_argument("--experiment-id", default=None,
                        help="experiment label stored on every row "
                             f"(default: dev, or ${config.ENV_EXPERIMENT_ID})")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would run; no solver calls, no writes")
    args = parser.parse_args()

    if args.list_solvers:
        try:
            print(format_registry(load_registry(args.registry)))
        except ConfigError as exc:
            sys.exit(f"ERROR: {exc}")
        return

    if args.list_benchmark_packs:
        print(format_pack_list())
        return

    try:
        solver = build_solver(args, parser)
        args.experiment_id = config.resolve(args.experiment_id,
                                            config.ENV_EXPERIMENT_ID,
                                            config.DEFAULT_EXPERIMENT_ID)
        if args.input_path is None:
            args.input_path = config.env_path(config.ENV_INPUT_PATH,
                                              DEFAULT_TASKS_PARQUET)
        pack_id = config.resolve(args.benchmark_pack, config.ENV_BENCHMARK_PACK)
        if args.benchmark_pack_path and pack_id:
            sys.exit(
                "ERROR: pass only one of --benchmark-pack / --benchmark-pack-path"
            )
        pack_override = None
        if args.benchmark_pack_path or pack_id:
            pack_override = resolve_pack(
                pack_id=pack_id, pack_path=args.benchmark_pack_path,
            )
    except (ConfigError, SolverError, ProviderConfigError, ValueError,
            BenchmarkPackError) as exc:
        sys.exit(f"ERROR: {exc}")

    # 1. Load tasks and build the deterministic work list.
    try:
        tasks_df = load_tasks_dataframe(args.input_path)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")
    benchmark_meta = metadata_for_evaluation_items(
        tasks_df, args.input_path, pack_override,
    )
    items = build_evaluation_items(
        reconstruct_tasks(tasks_df), benchmark_meta=benchmark_meta,
    )
    if args.task_id:
        wanted = {t.strip() for t in args.task_id.split(",") if t.strip()}
        missing = wanted - {item["task_id"] for item in items}
        if missing:
            sys.exit(f"ERROR: task id(s) not found in tasks Parquet: {sorted(missing)}")
        items = [item for item in items if item["task_id"] in wanted]
    if args.limit is not None:
        items = items[: args.limit]
    if not items:
        sys.exit("ERROR: nothing to run (check --task-id / --limit filters).")

    with_truth = sum(1 for item in items if item["expected_output"] is not None)
    logging.info(
        "Prepared %d evaluation item(s) from %d task(s) — %d with ground truth "
        "(pack=%s, benchmark=%s %s)",
        len(items), len({item["task_id"] for item in items}), with_truth,
        benchmark_meta.get("pack_id"), benchmark_meta.get("benchmark_name"),
        benchmark_meta.get("benchmark_version"),
    )

    solver_info = solver.describe()
    if args.dry_run:
        print(f"DRY RUN — solver={solver.name} family={solver.family} "
              f"mode={solver.execution_mode} experiment={args.experiment_id}")
        print(f"benchmark: {json.dumps(benchmark_meta, indent=2)}")
        print(f"solver config: {json.dumps(solver_info, indent=2)}")
        print(f"{len(items)} item(s) would run:")
        for item in items:
            print(f"  {item['task_id']} (test example {item['test_example_id']})")
        first = items[0]
        if isinstance(solver, LLMDirectSolver):
            preview = solver._render(first["train"], first["test_input"])
            label = "First prompt preview"
        else:
            preview = json.dumps(SolverTask(
                task_id=first["task_id"],
                test_example_id=first["test_example_id"],
                train=first["train"], test_input=first["test_input"],
            ).to_wire(), indent=2)
            label = "First wire payload preview (note: no expected output)"
        print(f"\n{label}:\n" + "-" * 40)
        print(preview if len(preview) < 1200 else preview[:1200] + " …[truncated]")
        return

    run_id = build_run_id(solver.name)
    run_dir = args.output_path or (default_runs_root() / run_id)

    # 2. Manifest first (status="running"), so even a crashed run is
    # traceable to its commit, solver config, and inputs.
    run_started_at = utc_now_iso()
    write_manifest(run_dir, build_manifest_payload(
        args, solver_info, run_id, run_dir, len(items), "running",
        run_started_at, benchmark_meta=benchmark_meta,
    ))

    # 3. Evaluation loop — incremental flushes, per-item error tolerance.
    pending, all_rows = [], []
    token_totals = {"input": None, "output": None}
    part_index = 0
    try:
        for i, item in enumerate(items, start=1):
            rows, result = evaluate_item(solver, item)
            for row in rows:
                row["run_id"] = run_id
                row["experiment_id"] = args.experiment_id
            pending.extend(rows)
            all_rows.extend(rows)
            if result.input_tokens is not None:
                token_totals["input"] = (token_totals["input"] or 0) + result.input_tokens
            if result.output_tokens is not None:
                token_totals["output"] = (token_totals["output"] or 0) + result.output_tokens
            logging.info(
                "[%d/%d] %s → status=%s attempts=%d mode=%s (%.0f ms)",
                i, len(items), item["task_id"], result.status, len(rows),
                rows[0]["failure_mode"], rows[0]["latency_ms"],
            )
            if len(pending) >= FLUSH_EVERY:
                part_index = flush_chunk(pending, run_dir, part_index)
    finally:
        part_index = flush_chunk(pending, run_dir, part_index)

    write_manifest(run_dir, build_manifest_payload(
        args, solver_info, run_id, run_dir, len(items), "completed",
        run_started_at, finished_at=utc_now_iso(), n_rows_written=len(all_rows),
        token_totals=token_totals, benchmark_meta=benchmark_meta,
    ))
    print_summary(all_rows, run_dir, run_id, token_totals,
                  experiment_id=args.experiment_id)


if __name__ == "__main__":
    main()

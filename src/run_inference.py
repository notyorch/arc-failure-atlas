"""
Run model inference over normalized ARC tasks and persist scored results.

Reads the tasks Parquet produced by the ETL (src/main.py), builds one prompt
per (task, test example), calls the selected provider, parses/validates the
response grid, scores it against ground truth when available, assigns a
failure mode, and writes rows to a per-run Parquet directory:

    data/parquet/inference/runs/<run_id>/part-NNNN.parquet

The directory name is deliberately NOT Hive-style ("run_id=..."): run_id is
kept as a physical column in every part file so each file is self-contained,
and pyarrow can read the whole runs/ tree as one dataset without partition-
key/column conflicts.

Rows are flushed to disk incrementally (every FLUSH_EVERY items and on
interruption), so partial progress is never lost. Per-task provider errors
become rows with failure_mode="api_error" instead of aborting the batch.

Examples (from the repository root):
    python src/run_inference.py --provider mock --model baseline --limit 20
    python src/run_inference.py --provider openai --model gpt-4o-mini --limit 5
    python src/run_inference.py --provider ollama --model llama3 --task-id sample01
    python src/run_inference.py --provider mock --model baseline --dry-run
"""

import argparse
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from contracts import (
    INFERENCE_PARQUET_SCHEMA,
    INFERENCE_PIPELINE_VERSION,
    validate_columns,
)
from evaluator import evaluate_prediction
from failure_taxonomy import classify_failure
from grid_parser import (
    PARSE_NOT_ATTEMPTED,
    ParseResult,
    parse_response,
    serialize_grid,
)
from prompt_builder import (
    DEFAULT_TASKS_PARQUET,
    PROMPT_VERSION,
    build_inference_items,
    load_tasks_dataframe,
    reconstruct_tasks,
)
from providers import STATUS_OK, ProviderConfigError, ProviderResponse, get_provider

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
    "run_id": "string", "experiment_id": "string", "provider": "string",
    "model_name": "string", "prompt_version": "string",
    "pipeline_version": "string", "task_id": "string", "split": "string",
    "test_example_id": "int64", "source_task_partition": "string",
    "prompt_text": "string", "response_text": "string",
    "predicted_grid_json": "string", "expected_output_grid_json": "string",
    "status": "string", "error_message": "string",
    "latency_ms": "float64", "cost_estimate_usd": "float64",
    "started_at": "string", "finished_at": "string",
    "parse_status": "string", "parse_error": "string",
    "is_exact_match": "boolean", "same_shape": "boolean",
    "cell_accuracy": "Float64", "n_diff_cells": "Int64",
    "failure_mode": "string", "failure_detail": "string",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_run_id(provider: str, model: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_model = model.replace("/", "-").replace(":", "-")
    return f"{timestamp}_{provider}_{safe_model}_{uuid.uuid4().hex[:8]}"


def run_single_item(provider, item: dict) -> dict:
    """Full pipeline for one (task, test example): call → parse → score → label."""
    started_at = utc_now_iso()
    context = {
        "task_id": item["task_id"],
        "test_input": item["test_input"],
        "expected_output": item["expected_output"],
    }
    try:
        response = provider.generate(item["prompt"], context=context)
    except Exception as exc:  # per-task resilience: any bug becomes a row
        logging.exception("[%s] provider raised unexpectedly", item["task_id"])
        response = ProviderResponse(
            response_text=None, status="error",
            error_message=f"unexpected provider exception: {exc}",
        )
    finished_at = utc_now_iso()

    if response.status == STATUS_OK:
        parsed = parse_response(response.response_text)
    else:
        parsed = ParseResult(
            PARSE_NOT_ATTEMPTED,
            "provider call failed; parsing not attempted", None, None,
        )

    expected = item["expected_output"]
    evaluation = evaluate_prediction(parsed.predicted_grid_obj, expected)
    failure_mode, failure_detail = classify_failure(
        provider_status=response.status,
        parse_status=parsed.parse_status,
        evaluation=evaluation,
        predicted_grid=parsed.predicted_grid_obj,
        expected_grid=expected,
        provider_error=response.error_message,
        parse_error=parsed.parse_error,
    )

    return {
        "run_id": None,  # filled by the caller (same value for all rows)
        "experiment_id": None,
        "provider": provider.name,
        "model_name": provider.model_name,
        "prompt_version": PROMPT_VERSION,
        "pipeline_version": INFERENCE_PIPELINE_VERSION,
        "task_id": item["task_id"],
        "split": "test",
        "test_example_id": item["test_example_id"],
        "source_task_partition": item["source_task_partition"],
        "prompt_text": item["prompt"],
        "response_text": response.response_text,
        "predicted_grid_json": parsed.predicted_grid_json,
        "expected_output_grid_json":
            serialize_grid(expected) if expected is not None else None,
        "status": response.status,
        "error_message": response.error_message,
        "latency_ms": float(response.latency_ms),
        "cost_estimate_usd": float(response.cost_estimate_usd),
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
    }


def flush_chunk(rows: list, run_dir: Path, part_index: int) -> int:
    """Validates and writes pending rows as one part file. Returns next index."""
    if not rows:
        return part_index
    chunk = pd.DataFrame(rows).astype(_CHUNK_DTYPES)
    validate_columns(chunk, INFERENCE_PARQUET_SCHEMA, label="inference results")
    run_dir.mkdir(parents=True, exist_ok=True)
    part_path = run_dir / f"part-{part_index:04d}.parquet"
    chunk.to_parquet(part_path, engine="pyarrow", index=False)
    logging.info("Flushed %d row(s) → %s", len(chunk), part_path)
    rows.clear()
    return part_index + 1


def print_summary(all_rows: list, run_dir: Path, run_id: str) -> None:
    df = pd.DataFrame(all_rows)
    evaluable = df["is_exact_match"].notna().sum()
    exact = (df["is_exact_match"] == True).sum()  # noqa: E712 — None-safe
    print("\n" + "=" * 62)
    print(f"RUN SUMMARY  {run_id}")
    print("=" * 62)
    print(f"rows written        : {len(df)}")
    print(f"provider ok / error : {(df['status'] == 'ok').sum()} / "
          f"{(df['status'] != 'ok').sum()}")
    print(f"exact matches       : {int(exact)} / {int(evaluable)} evaluable")
    if df["cell_accuracy"].notna().any():
        print(f"avg cell accuracy   : {df['cell_accuracy'].mean():.3f} "
              "(over valid predictions)")
    print(f"avg latency         : {df['latency_ms'].mean():.1f} ms")
    print(f"total cost estimate : ${df['cost_estimate_usd'].sum():.4f}")
    print("failure modes       :")
    counts = df["failure_mode"].fillna("(not classifiable)").value_counts()
    for mode, count in counts.items():
        print(f"    {mode:20s} {count}")
    print(f"output              : {run_dir}")
    print("next step           : python src/build_analytics.py")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run (mock or real) model inference over normalized ARC tasks."
    )
    parser.add_argument("--provider", required=True,
                        choices=["mock", "openai", "ollama"])
    parser.add_argument("--model", required=True,
                        help="model name recorded in results "
                             "(e.g. baseline, gpt-4o-mini, llama3)")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_TASKS_PARQUET,
                        help="tasks Parquet directory (default: %(default)s)")
    parser.add_argument("--output-path", type=Path, default=None,
                        help="run output directory (default: "
                             f"{DEFAULT_RUNS_DIR}/<run_id>)")
    parser.add_argument("--limit", type=int, default=None,
                        help="run at most N (task, test example) items")
    parser.add_argument("--split", choices=["test"], default="test",
                        help="which split to predict (MVP supports only 'test')")
    parser.add_argument("--task-id", default=None,
                        help="run only these task ids (comma-separated)")
    parser.add_argument("--experiment-id", default="dev",
                        help="experiment label stored on every row (default: dev)")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would run; no provider calls, no writes")
    args = parser.parse_args()

    # 1. Load tasks and build the deterministic work list.
    try:
        tasks_df = load_tasks_dataframe(args.input_path)
    except (FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")
    items = build_inference_items(reconstruct_tasks(tasks_df))
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
        "Prepared %d inference item(s) from %d task(s) — %d with ground truth",
        len(items), len({item["task_id"] for item in items}), with_truth,
    )

    if args.dry_run:
        print(f"DRY RUN — provider={args.provider} model={args.model} "
              f"experiment={args.experiment_id}")
        print(f"{len(items)} item(s) would run:")
        for item in items:
            print(f"  {item['task_id']} (test example {item['test_example_id']})")
        preview = items[0]["prompt"]
        print("\nFirst prompt preview:\n" + "-" * 40)
        print(preview if len(preview) < 1200 else preview[:1200] + " …[truncated]")
        return

    # 2. Provider construction (fails fast with a clear message).
    try:
        provider = get_provider(args.provider, args.model)
    except (ProviderConfigError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")

    run_id = build_run_id(args.provider, args.model)
    run_dir = args.output_path or (DEFAULT_RUNS_DIR / run_id)

    # 3. Inference loop — incremental flushes, per-item error tolerance.
    pending, all_rows = [], []
    part_index = 0
    try:
        for i, item in enumerate(items, start=1):
            row = run_single_item(provider, item)
            row["run_id"] = run_id
            row["experiment_id"] = args.experiment_id
            pending.append(row)
            all_rows.append(row)
            logging.info(
                "[%d/%d] %s → status=%s parse=%s mode=%s (%.0f ms)",
                i, len(items), item["task_id"], row["status"],
                row["parse_status"], row["failure_mode"], row["latency_ms"],
            )
            if len(pending) >= FLUSH_EVERY:
                part_index = flush_chunk(pending, run_dir, part_index)
    finally:
        part_index = flush_chunk(pending, run_dir, part_index)

    print_summary(all_rows, run_dir, run_id)


if __name__ == "__main__":
    main()

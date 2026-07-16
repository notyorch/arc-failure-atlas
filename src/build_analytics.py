"""
Build analysis-ready Parquet tables and the MVP report from evaluation runs.

Reads every run under data/parquet/inference/runs/ and fully REBUILDS the
derived layer (safe: everything here is recomputable from the runs):

    data/parquet/analytics/fact_evaluation_results/   (Hive: solver_name)
    data/parquet/analytics/summary_by_solver/
    data/parquet/analytics/summary_by_failure_mode/
    data/parquet/analytics/summary_by_task/
    data/parquet/analytics/summary_by_benchmark/
    data/parquet/analytics/csv/                      (flat CSV exports:
        summary_by_solver.csv, summary_by_failure_mode.csv,
        summary_by_task.csv, summary_by_benchmark.csv,
        solver_failure_matrix.csv)
    reports/mvp_report.md                            (human-readable report)

Legacy v1 runs (28-column model/provider layout, `response_text`,
`api_error`) are upgraded in memory via `normalize_evaluation_frame`
before aggregation — no on-disk rewrite of old run directories.

Metric definitions (see src/DECISIONS.md — Decision 21):
    n_items           — distinct (run, task, test_example) items
    n_tasks           — distinct (run, task) tasks
    n_attempts        — result rows (attempts) in the group
    exact_match_rate  — exact attempt rows / ALL attempt rows
    solved_rate       — item-level pass@k: a test example is solved when ANY
                        of its attempts is an exact match
    task_solved_rate  — ARC-official: a task is solved only when EVERY one of
                        its test examples is solved (the number to compare
                        against public ARC-AGI leaderboards)
    avg_cell_accuracy — mean over rows with a valid prediction AND ground
                        truth (NULL metrics are excluded, never imputed);
                        shape-mismatch rows use top-left overlap (Decision 21)
    parse_error_rate / shape_error_rate — share of attempt rows whose
                        failure_mode is exactly that value

Usage (from the repository root):
    python src/build_analytics.py
    python src/build_analytics.py --experiment-id mvp-demo
"""

import argparse
import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config
from config import ConfigError
from contracts import (
    ANALYTICS_METRIC_COLUMNS,
    ANALYTICS_SCHEMA_VERSION,
    EVALUATION_RESULTS_SCHEMA,
    EVALUATION_SCHEMA_VERSION,
    LEGACY_INFERENCE_SCHEMA_V1,
    validate_columns,
)
from failure_taxonomy import LEGACY_MODE_RENAMES
from manifest import git_commit_sha, portable_path, write_manifest
from benchmark_packs import UNKNOWN_META

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"
DEFAULT_ANALYTICS_DIR = REPO_ROOT / "data" / "parquet" / "analytics"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "mvp_report.md"

ITEM_KEY = ["run_id", "task_id", "test_example_id"]

CSV_EXPORTS = [
    "summary_by_solver.csv",
    "summary_by_failure_mode.csv",
    "summary_by_task.csv",
    "summary_by_benchmark.csv",
    "solver_failure_matrix.csv",
]

_EXAMPLE_MODE_PRIORITY = [
    "shape_error", "spatial_error", "symbol_error",
    "parse_error", "empty_response", "execution_error", "unknown_error",
]


def normalize_evaluation_frame(df: pd.DataFrame) -> pd.DataFrame:
    """
    Bring a mixed v1/v2 run tree onto EVALUATION_RESULTS_SCHEMA.

    v1 fingerprints: has `response_text` and lacks `solver_name`.
    Always applies taxonomy vocabulary renames (`api_error` →
    `execution_error`). Does not mutate files on disk.
    """
    out = df.copy()

    if "response_text" in out.columns and "raw_output" not in out.columns:
        out = out.rename(columns={"response_text": "raw_output"})

    if "solver_name" not in out.columns:
        missing_v1 = [c for c in LEGACY_INFERENCE_SCHEMA_V1 if c not in out.columns
                      and c != "response_text"]
        # After rename, response_text is gone; raw_output stands in.
        if "raw_output" not in out.columns:
            missing_v1.append("response_text/raw_output")
        if missing_v1:
            logging.warning(
                "Legacy upgrade: some expected v1 columns are missing: %s",
                missing_v1,
            )
        provider = out["provider"].astype(str) if "provider" in out.columns \
            else pd.Series(["unknown"] * len(out))
        model = out["model_name"].astype(str) if "model_name" in out.columns \
            else pd.Series(["unknown"] * len(out))
        out["solver_name"] = provider + ":" + model
        out["solver_family"] = "llm_direct"
        out["solver_version"] = "legacy-v1"
        out["execution_mode"] = "in_process"
        out["attempt"] = 1
        for col in ("input_tokens", "output_tokens", "solver_metadata"):
            if col not in out.columns:
                out[col] = pd.NA

    for col in EVALUATION_RESULTS_SCHEMA:
        if col not in out.columns:
            if col in UNKNOWN_META:
                out[col] = UNKNOWN_META[col]
            else:
                out[col] = pd.NA

    for col, default in UNKNOWN_META.items():
        if col in out.columns:
            out[col] = out[col].fillna(default).astype(str)

    if "failure_mode" in out.columns:
        out["failure_mode"] = out["failure_mode"].replace(LEGACY_MODE_RENAMES)

    return out[list(EVALUATION_RESULTS_SCHEMA.keys())]


def load_fact_table(runs_dir: Path, experiment_id: str | None) -> pd.DataFrame:
    """Loads all runs, upgrades legacy rows, enforces schema, dedups."""
    if not runs_dir.exists() or not any(runs_dir.rglob("*.parquet")):
        sys.exit(
            f"ERROR: no evaluation results found under {runs_dir}.\n"
            "Run an evaluation first, e.g.:\n"
            "    python src/run_evaluation.py --solver mock-baseline\n"
            "    python src/run_evaluation.py --provider mock --model baseline"
        )
    df = pd.read_parquet(runs_dir, engine="pyarrow")
    df = normalize_evaluation_frame(df)
    validate_columns(df, EVALUATION_RESULTS_SCHEMA, label="fact_evaluation_results")

    if experiment_id is not None:
        df = df[df["experiment_id"] == experiment_id]
        if df.empty:
            sys.exit(f"ERROR: no rows with experiment_id='{experiment_id}'.")

    key = ["run_id", "task_id", "test_example_id", "attempt"]
    duplicated = df.duplicated(subset=key).sum()
    if duplicated:
        logging.warning("Dropping %d duplicated row(s) on %s", duplicated, key)
        df = df.drop_duplicates(subset=key, keep="last")
    return df.reset_index(drop=True)


def aggregate(df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    """Uniform metric block for any grouping (see module docstring)."""
    work = df.assign(
        _exact=df["is_exact_match"].eq(True).fillna(False).astype(bool),
        _evaluable=df["is_exact_match"].notna(),
        _parse_err=df["failure_mode"].eq("parse_error").fillna(False).astype(bool),
        _shape_err=df["failure_mode"].eq("shape_error").fillna(False).astype(bool),
    )

    # Deduplicate when group_cols already includes part of ITEM_KEY
    # (e.g. summary_by_task groups on task_id — concatenating would make
    # pandas raise "cannot insert task_id, already exists" on reset_index).
    item_keys = list(dict.fromkeys([*group_cols, *ITEM_KEY]))
    item_level = (
        work.groupby(item_keys, dropna=False, observed=True)["_exact"]
        .any()
        .reset_index(name="_item_solved")
    )
    solved = (
        item_level.groupby(group_cols, dropna=False, observed=True)["_item_solved"]
        .agg(n_items="size", solved_rate="mean")
        .reset_index()
    )

    # ARC-official task granularity: a task is solved only when EVERY one of
    # its test examples is solved. Roll the item-level solves up per task,
    # then average over tasks. task_keys drops test_example_id from item_keys.
    task_keys = list(dict.fromkeys([*group_cols, "run_id", "task_id"]))
    task_level = (
        item_level.groupby(task_keys, dropna=False, observed=True)["_item_solved"]
        .all()
        .reset_index(name="_task_solved")
    )
    tasks = (
        task_level.groupby(group_cols, dropna=False, observed=True)["_task_solved"]
        .agg(n_tasks="size", task_solved_rate="mean")
        .reset_index()
    )

    attempts = (
        work.groupby(group_cols, dropna=False, observed=True)
        .agg(
            n_attempts=("_exact", "size"),
            n_evaluable=("_evaluable", "sum"),
            exact_match_rate=("_exact", "mean"),
            avg_cell_accuracy=("cell_accuracy", "mean"),
            avg_latency_ms=("latency_ms", "mean"),
            total_cost_estimate_usd=("cost_estimate_usd", "sum"),
            parse_error_rate=("_parse_err", "mean"),
            shape_error_rate=("_shape_err", "mean"),
        )
        .reset_index()
    )
    grouped = (
        attempts
        .merge(solved, on=group_cols, how="left")
        .merge(tasks, on=group_cols, how="left")
    )
    missing = [c for c in ANALYTICS_METRIC_COLUMNS if c not in grouped.columns]
    if missing:
        raise ValueError(f"Summary for {group_cols} missing metrics: {missing}")
    # Stable column order: keys then the metric contract.
    return grouped[group_cols + ANALYTICS_METRIC_COLUMNS]


def write_table(df: pd.DataFrame, out_dir: Path, label: str,
                partition_cols: list | None = None) -> None:
    """Clean rebuild: removes the previous derived table, writes the new one."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if partition_cols:
        out = df.copy()
        for col in partition_cols:
            out[col] = out[col].astype(str)
        out.to_parquet(out_dir, engine="pyarrow", index=False,
                       partition_cols=partition_cols)
    else:
        df.to_parquet(out_dir / "part-0.parquet", engine="pyarrow", index=False)
    logging.info("[%s] written → %s (%d rows)", label, out_dir, len(df))


def solver_failure_matrix(fact: pd.DataFrame) -> pd.DataFrame:
    """failure_mode (rows) × solver_name (columns) count matrix, including
    exact_match as the success bucket. Deterministic ordering."""
    matrix = (
        fact.assign(failure_mode=fact["failure_mode"].fillna("not_classifiable"))
        .pivot_table(index="failure_mode", columns="solver_name",
                     values="run_id", aggfunc="count", fill_value=0,
                     observed=True)
        .sort_index()
    )
    matrix.columns = [str(c) for c in matrix.columns]
    return matrix[sorted(matrix.columns)]


def export_csv_tables(fact, by_solver, by_mode, by_task, by_benchmark,
                      csv_dir: Path) -> Path:
    """Flat, BI/Excel-ready copies of the summary tables (see CSV_EXPORTS)."""
    if csv_dir.exists():
        shutil.rmtree(csv_dir)
    csv_dir.mkdir(parents=True, exist_ok=True)

    exports = {
        "summary_by_solver.csv":
            by_solver.sort_values(
                ["solver_family", "solver_name", "execution_mode"],
                kind="mergesort",
            ),
        "summary_by_failure_mode.csv":
            by_mode.sort_values(["n_attempts", "failure_mode"],
                                ascending=[False, True], kind="mergesort"),
        "summary_by_task.csv": by_task.sort_values("task_id", kind="mergesort"),
        "summary_by_benchmark.csv":
            by_benchmark.sort_values(
                ["benchmark_name", "benchmark_version", "pack_id"],
                kind="mergesort",
            ),
        "solver_failure_matrix.csv": solver_failure_matrix(fact).reset_index(),
    }
    for name, frame in exports.items():
        frame.to_csv(csv_dir / name, index=False)
        logging.info("[csv] written → %s", csv_dir / name)
    return csv_dir


# REPORT

def _markdown_table(df: pd.DataFrame, float_fmt: str = "{:.3f}") -> str:
    """Small dependency-free DataFrame → GitHub markdown table."""
    def fmt(value):
        if value is None or pd.isna(value):
            return "—"
        if isinstance(value, float):
            return float_fmt.format(value)
        return str(value)

    header = "| " + " | ".join(df.columns) + " |"
    divider = "|" + "|".join(" --- " for _ in df.columns) + "|"
    rows = ["| " + " | ".join(fmt(v) for v in row) + " |"
            for row in df.itertuples(index=False)]
    return "\n".join([header, divider, *rows])


def _truncate(text: str | None, limit: int = 300) -> str:
    if text is None:
        return "(none)"
    text = str(text).replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + " …[truncated]"


def pick_example_failures(df: pd.DataFrame, n: int = 3) -> pd.DataFrame:
    """Up to n example failures, preferring distinct modes, deterministic order."""
    failures = df[df["failure_mode"].notna() & (df["failure_mode"] != "exact_match")]
    failures = failures.sort_values(["failure_mode", "task_id", "run_id"])
    picked = []
    for mode in _EXAMPLE_MODE_PRIORITY:
        rows = failures[failures["failure_mode"] == mode]
        if not rows.empty:
            picked.append(rows.iloc[0])
        if len(picked) == n:
            break
    if len(picked) < n:
        remaining = failures[~failures.index.isin([r.name for r in picked])]
        picked.extend(remaining.iloc[i] for i in range(min(n - len(picked), len(remaining))))
    return pd.DataFrame(picked)


def render_report(df: pd.DataFrame, by_solver: pd.DataFrame,
                  by_mode: pd.DataFrame, experiment_id: str | None) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    runs = (
        df.groupby(["run_id", "solver_name", "solver_family", "execution_mode",
                    "experiment_id"], observed=True)
        .agg(rows=("task_id", "count"), started_at=("started_at", "min"))
        .reset_index()
        .sort_values("run_id")
    )

    by_mode = by_mode.copy()
    by_mode["share"] = by_mode["n_attempts"] / len(df)
    mode_table = by_mode[["failure_mode", "n_attempts", "n_items", "share",
                          "avg_cell_accuracy"]].sort_values(
        "n_attempts", ascending=False)

    solver_cols = [
        c for c in [
            "solver_name", "solver_family", "execution_mode",
            "n_tasks", "n_items", "n_attempts", "n_evaluable",
            "exact_match_rate", "solved_rate", "task_solved_rate",
            "avg_cell_accuracy",
            "avg_latency_ms", "total_cost_estimate_usd",
            "parse_error_rate", "shape_error_rate",
        ] if c in by_solver.columns
    ]
    solver_table = by_solver[solver_cols]

    sections = [
        "# ARC Solver Evaluation Platform — MVP Report",
        "",
        f"_Generated by `src/build_analytics.py` on {generated_at}"
        + (f" — experiment `{experiment_id}`_" if experiment_id else "_"),
        "",
        "## What was run",
        "",
        f"- **Evaluation attempt rows:** {len(df)} "
        f"(one per run × task × test example × attempt)",
        f"- **Distinct tasks:** {df['task_id'].nunique()}",
        f"- **Runs:** {df['run_id'].nunique()} | **Solvers:** "
        f"{', '.join(sorted(df['solver_name'].astype(str).unique()))}",
        f"- **Families:** "
        f"{', '.join(sorted(df['solver_family'].astype(str).unique()))}",
        (
            f"- **Benchmarks:** "
            f"{', '.join(sorted(df['benchmark_name'].astype(str).unique()))}"
            if "benchmark_name" in df.columns
            else "- **Benchmarks:** (not stamped)"
        ),
        "",
        _markdown_table(runs),
        "",
        "## Metrics by solver",
        "",
        "`exact_match_rate` is attempt-level (execution/parse failures count "
        "against accuracy). `solved_rate` is item-level pass@k — a test "
        "example is solved when any attempt matches. `task_solved_rate` is the "
        "ARC-official number — a task is solved only when every one of its test "
        "examples is solved (compare this against public leaderboards). "
        "`avg_cell_accuracy` averages only rows with a valid prediction and "
        "ground truth; on shape mismatch it uses top-left overlap (secondary "
        "diagnostic — not a leaderboard metric; see Decision 21).",
        "",
        _markdown_table(solver_table, float_fmt="{:.4f}"),
        "",
        "## Failure mode distribution",
        "",
        _markdown_table(mode_table),
        "",
        "## Example failures",
        "",
    ]

    for row in pick_example_failures(df).itertuples(index=False):
        sections += [
            f"### `{row.task_id}` — {row.failure_mode} "
            f"({row.solver_name})",
            "",
            f"- **Detail:** {row.failure_detail}",
            f"- **Parse status:** {row.parse_status}"
            + (f" — {row.parse_error}" if row.parse_error is not None
               and not pd.isna(row.parse_error) else ""),
            f"- **Expected:** `{_truncate(row.expected_output_grid_json)}`",
            f"- **Predicted:** `{_truncate(row.predicted_grid_json)}`",
            f"- **Raw output:** `{_truncate(row.raw_output, 200)}`",
            "",
        ]

    sections += [
        "## Reproduce",
        "",
        "```bash",
        "python scripts/demo_bundle.py                 # offline one-command demo",
        "",
        "# or step by step:",
        "python scripts/fetch_arc_data.py --sample     # 6 offline demo tasks",
        "python src/main.py                             # legacy raw dir, or:",
        "python src/main.py --benchmark-pack example_local_pack",
        "python src/run_evaluation.py --solver mock-baseline --experiment-id <label>",
        "python src/build_analytics.py --experiment-id <label>",
        "# see docs/BENCHMARK_PACKS.md for ARC-AGI-2 packs",
        "```",
        "",
        "Mock results are deterministic per (solver config, task): reruns "
        "reproduce these metrics exactly; only run ids and timestamps change.",
        "",
        "## Notes and limitations",
        "",
        "- The `mock-baseline` / `mock-large` registry entries are "
        "deterministic pipeline-testing tools, not scientific baselines.",
        "- Cost estimates use a static price table (LLM backends) or 0.0 "
        "(mock / most non-LLM adapters); they are reporting aids, not billing.",
        "- Failure taxonomy v2 is heuristic; `spatial_error` vs "
        "`symbol_error` is decided by a color-histogram comparison "
        "(see `src/failure_taxonomy.py`). `execution_error` covers API, "
        "subprocess, and HTTP failures alike.",
        "- Heterogeneous solvers plug in via adapters — see "
        "`docs/SOLVER_ADAPTERS.md` and `configs/solvers.json`.",
        "",
    ]
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build analytics Parquet tables, CSV exports, and the MVP "
                    "markdown report from solver evaluation runs. Flags fall "
                    "back to ATLAS_* variables.",
    )
    parser.add_argument("--runs-path", type=Path, default=None,
                        help=f"evaluation runs directory (default: {DEFAULT_RUNS_DIR}, "
                             f"or ${config.ENV_OUTPUT_ROOT}/inference/runs)")
    parser.add_argument("--output-path", type=Path, default=None,
                        help=f"analytics output directory (default: {DEFAULT_ANALYTICS_DIR}, "
                             f"or ${config.ENV_OUTPUT_ROOT}/analytics)")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH,
                        help="markdown report path (default: %(default)s)")
    parser.add_argument("--experiment-id", default=None,
                        help="only include rows from this experiment "
                             f"(default: all rows, or ${config.ENV_EXPERIMENT_ID})")
    args = parser.parse_args()

    try:
        root = config.output_root()
        if args.runs_path is None:
            args.runs_path = (root / "inference" / "runs") if root else DEFAULT_RUNS_DIR
        if args.output_path is None:
            args.output_path = (root / "analytics") if root else DEFAULT_ANALYTICS_DIR
        args.experiment_id = config.resolve(args.experiment_id,
                                            config.ENV_EXPERIMENT_ID)
    except ConfigError as exc:
        sys.exit(f"ERROR: {exc}")

    build_started_at = datetime.now(timezone.utc).isoformat()
    fact = load_fact_table(args.runs_path, args.experiment_id)

    by_solver = aggregate(fact, ["experiment_id", "solver_name", "solver_family",
                                 "solver_version", "execution_mode"])
    by_mode = aggregate(
        fact.assign(failure_mode=fact["failure_mode"].fillna("not_classifiable")),
        ["failure_mode"],
    )
    by_task = aggregate(fact, ["task_id", "split"])
    by_benchmark = aggregate(fact, [
        "pack_id", "benchmark_family", "benchmark_name",
        "benchmark_version", "split_name", "task_source",
    ])

    # Drop superseded v1 table names if present from earlier builds.
    for stale in ("fact_inference_results", "summary_by_model"):
        stale_path = args.output_path / stale
        if stale_path.exists():
            shutil.rmtree(stale_path)
            logging.info("Removed legacy analytics table → %s", stale_path)

    write_table(fact, args.output_path / "fact_evaluation_results",
                "fact_evaluation_results",
                partition_cols=["solver_name"])
    write_table(by_solver, args.output_path / "summary_by_solver",
                "summary_by_solver")
    write_table(by_mode, args.output_path / "summary_by_failure_mode",
                "summary_by_failure_mode")
    write_table(by_task, args.output_path / "summary_by_task",
                "summary_by_task")
    write_table(by_benchmark, args.output_path / "summary_by_benchmark",
                "summary_by_benchmark")
    csv_dir = export_csv_tables(fact, by_solver, by_mode, by_task, by_benchmark,
                                args.output_path / "csv")

    report = render_report(fact, by_solver, by_mode, args.experiment_id)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(report, encoding="utf-8")
    logging.info("[report] written → %s", args.report_path)

    write_manifest(args.output_path, {
        "manifest_kind": "analytics_build",
        "status": "completed",
        "analytics_schema_version": ANALYTICS_SCHEMA_VERSION,
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "git_commit": git_commit_sha(),
        "started_at": build_started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "runs_path": portable_path(args.runs_path),
        "output_path": portable_path(args.output_path),
        "report_path": portable_path(args.report_path),
        "experiment_id_filter": args.experiment_id,
        "source_runs": {
            str(run_id): int(count)
            for run_id, count in fact["run_id"].value_counts().sort_index().items()
        },
        "tables": {
            "fact_evaluation_results": len(fact),
            "summary_by_solver": len(by_solver),
            "summary_by_failure_mode": len(by_mode),
            "summary_by_task": len(by_task),
            "summary_by_benchmark": len(by_benchmark),
        },
        "csv_exports": CSV_EXPORTS,
    })

    print("\nANALYTICS BUILT")
    print(f"  fact rows      : {len(fact)}")
    print(f"  solvers        : {len(by_solver)}")
    print(f"  failure modes  : {json.dumps(dict(zip(by_mode['failure_mode'], by_mode['n_attempts'].astype(int))))}")
    print(f"  tables         : {args.output_path}")
    print(f"  csv exports    : {csv_dir}")
    print(f"  report         : {args.report_path}")


if __name__ == "__main__":
    main()

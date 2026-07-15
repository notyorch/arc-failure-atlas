"""
Build analysis-ready Parquet tables and the MVP report from inference runs.

Reads every run under data/parquet/inference/runs/ and fully REBUILDS the
derived layer (safe: everything here is recomputable from the runs):

    data/parquet/analytics/fact_inference_results/   (Hive: provider/model)
    data/parquet/analytics/summary_by_model/
    data/parquet/analytics/summary_by_failure_mode/
    data/parquet/analytics/summary_by_task/
    reports/mvp_report.md                            (human-readable report)

Metric definitions (see src/DECISIONS.md — Decision 12):
    exact_match_rate  — exact matches / ALL rows of the group (provider and
                        parse failures count against accuracy).
    avg_cell_accuracy — mean over rows with a valid prediction AND ground
                        truth (NULL metrics are excluded, never imputed).
    parse_error_rate / shape_error_rate — share of rows whose failure_mode
                        is exactly that value.

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

from contracts import (
    ANALYTICS_METRIC_COLUMNS,
    INFERENCE_PARQUET_SCHEMA,
    validate_columns,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s",
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"
DEFAULT_ANALYTICS_DIR = REPO_ROOT / "data" / "parquet" / "analytics"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "mvp_report.md"

# Order used to pick diverse example failures for the report.
_EXAMPLE_MODE_PRIORITY = [
    "shape_error", "spatial_error", "symbol_error",
    "parse_error", "empty_response", "api_error", "unknown_error",
]


def load_fact_table(runs_dir: Path, experiment_id: str | None) -> pd.DataFrame:
    """Loads all runs, enforces the inference schema, dedups on the row key."""
    if not runs_dir.exists() or not any(runs_dir.rglob("*.parquet")):
        sys.exit(
            f"ERROR: no inference results found under {runs_dir}.\n"
            "Run inference first, e.g.:\n"
            "    python src/run_inference.py --provider mock --model baseline"
        )
    df = pd.read_parquet(runs_dir, engine="pyarrow")
    # Column order stable regardless of on-disk order.
    df = df[list(INFERENCE_PARQUET_SCHEMA.keys())]
    validate_columns(df, INFERENCE_PARQUET_SCHEMA, label="fact_inference_results")

    if experiment_id is not None:
        df = df[df["experiment_id"] == experiment_id]
        if df.empty:
            sys.exit(f"ERROR: no rows with experiment_id='{experiment_id}'.")

    key = ["run_id", "task_id", "test_example_id"]
    duplicated = df.duplicated(subset=key).sum()
    if duplicated:
        logging.warning("Dropping %d duplicated row(s) on %s", duplicated, key)
        df = df.drop_duplicates(subset=key, keep="last")
    return df.reset_index(drop=True)


def aggregate(df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    """Uniform metric block for any grouping (see module docstring)."""
    # Helper columns first: with nullable booleans, `NA == True` is NA (not
    # False), which would silently shrink rate denominators — fillna guards.
    work = df.assign(
        _exact=df["is_exact_match"].eq(True).fillna(False).astype(bool),
        _evaluable=df["is_exact_match"].notna(),
        _parse_err=df["failure_mode"].eq("parse_error").fillna(False).astype(bool),
        _shape_err=df["failure_mode"].eq("shape_error").fillna(False).astype(bool),
    )
    grouped = (
        work.groupby(group_cols, dropna=False, observed=True)
        .agg(
            total_runs=("_exact", "size"),
            n_evaluable=("_evaluable", "sum"),
            exact_match_rate=("_exact", "mean"),
            avg_cell_accuracy=("cell_accuracy", "mean"),  # NA-skipping mean
            avg_latency_ms=("latency_ms", "mean"),
            total_cost_estimate_usd=("cost_estimate_usd", "sum"),
            parse_error_rate=("_parse_err", "mean"),
            shape_error_rate=("_shape_err", "mean"),
        )
        .reset_index()
    )
    missing = [c for c in ANALYTICS_METRIC_COLUMNS if c not in grouped.columns]
    if missing:  # contract guard: summaries must carry the agreed metrics
        raise ValueError(f"Summary for {group_cols} missing metrics: {missing}")
    return grouped


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
    if len(picked) < n:  # fill with whatever is left
        remaining = failures[~failures.index.isin([r.name for r in picked])]
        picked.extend(remaining.iloc[i] for i in range(min(n - len(picked), len(remaining))))
    return pd.DataFrame(picked)


def render_report(df: pd.DataFrame, by_model: pd.DataFrame,
                  by_mode: pd.DataFrame, experiment_id: str | None) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    runs = (
        df.groupby(["run_id", "provider", "model_name", "prompt_version",
                    "experiment_id"], observed=True)
        .agg(rows=("task_id", "count"), started_at=("started_at", "min"))
        .reset_index()
        .sort_values("run_id")
    )

    by_mode = by_mode.copy()
    by_mode["share"] = by_mode["total_runs"] / len(df)
    mode_table = by_mode[["failure_mode", "total_runs", "share",
                          "avg_cell_accuracy"]].sort_values(
        "total_runs", ascending=False)

    model_table = by_model[["provider", "model_name", "total_runs",
                            "n_evaluable", "exact_match_rate",
                            "avg_cell_accuracy", "avg_latency_ms",
                            "total_cost_estimate_usd", "parse_error_rate",
                            "shape_error_rate"]]

    sections = [
        "# ARC Failure Atlas — MVP Evaluation Report",
        "",
        f"_Generated by `src/build_analytics.py` on {generated_at}"
        + (f" — experiment `{experiment_id}`_" if experiment_id else "_"),
        "",
        "## What was run",
        "",
        f"- **Inference rows:** {len(df)} "
        f"(one per run × task × test example)",
        f"- **Distinct tasks:** {df['task_id'].nunique()}",
        f"- **Runs:** {df['run_id'].nunique()} | **Providers:** "
        f"{', '.join(sorted(df['provider'].astype(str).unique()))} | **Models:** "
        f"{', '.join(sorted(df['model_name'].astype(str).unique()))}",
        f"- **Prompt version:** {', '.join(sorted(df['prompt_version'].astype(str).unique()))}",
        "",
        _markdown_table(runs),
        "",
        "## Metrics by model",
        "",
        "`exact_match_rate` counts every row (API/parse failures count "
        "against accuracy); `avg_cell_accuracy` averages only rows with a "
        "valid prediction and ground truth.",
        "",
        _markdown_table(model_table, float_fmt="{:.4f}"),
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
            f"({row.provider}/{row.model_name})",
            "",
            f"- **Detail:** {row.failure_detail}",
            f"- **Parse status:** {row.parse_status}"
            + (f" — {row.parse_error}" if row.parse_error is not None
               and not pd.isna(row.parse_error) else ""),
            f"- **Expected:** `{_truncate(row.expected_output_grid_json)}`",
            f"- **Predicted:** `{_truncate(row.predicted_grid_json)}`",
            f"- **Raw response:** `{_truncate(row.response_text, 200)}`",
            "",
        ]

    sections += [
        "## Reproduce",
        "",
        "```bash",
        "python scripts/fetch_arc_data.py --sample     # 6 offline demo tasks",
        "python scripts/fetch_arc_data.py --limit 20   # + 20 real evaluation tasks (needs network)",
        "python src/main.py",
        "python src/run_inference.py --provider mock --model baseline --experiment-id mvp-demo",
        "python src/run_inference.py --provider mock --model mock-large --experiment-id mvp-demo",
        "python src/build_analytics.py",
        "```",
        "",
        "## Notes and limitations",
        "",
        "- The `mock` provider is a deterministic pipeline-testing tool, not "
        "a real model: its accuracy numbers only demonstrate that scoring "
        "and the taxonomy work end to end.",
        "- Cost estimates use a static price table (OpenAI) or 0.0 "
        "(mock/ollama); they are reporting aids, not billing data.",
        "- Failure taxonomy v1 is heuristic; `spatial_error` vs "
        "`symbol_error` is decided by a color-histogram comparison "
        "(see `src/failure_taxonomy.py`).",
        "",
    ]
    return "\n".join(sections)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build analytics Parquet tables and the MVP markdown report."
    )
    parser.add_argument("--runs-path", type=Path, default=DEFAULT_RUNS_DIR,
                        help="inference runs directory (default: %(default)s)")
    parser.add_argument("--output-path", type=Path, default=DEFAULT_ANALYTICS_DIR,
                        help="analytics output directory (default: %(default)s)")
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH,
                        help="markdown report path (default: %(default)s)")
    parser.add_argument("--experiment-id", default=None,
                        help="only include rows from this experiment")
    args = parser.parse_args()

    fact = load_fact_table(args.runs_path, args.experiment_id)

    by_model = aggregate(fact, ["experiment_id", "provider", "model_name",
                                "prompt_version"])
    by_mode = aggregate(
        fact.assign(failure_mode=fact["failure_mode"].fillna("not_classifiable")),
        ["failure_mode"],
    )
    by_task = aggregate(fact, ["task_id", "split"])

    write_table(fact, args.output_path / "fact_inference_results",
                "fact_inference_results",
                partition_cols=["provider", "model_name"])
    write_table(by_model, args.output_path / "summary_by_model",
                "summary_by_model")
    write_table(by_mode, args.output_path / "summary_by_failure_mode",
                "summary_by_failure_mode")
    write_table(by_task, args.output_path / "summary_by_task",
                "summary_by_task")

    report = render_report(fact, by_model, by_mode, args.experiment_id)
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(report, encoding="utf-8")
    logging.info("[report] written → %s", args.report_path)

    print("\nANALYTICS BUILT")
    print(f"  fact rows      : {len(fact)}")
    print(f"  models         : {len(by_model)}")
    print(f"  failure modes  : {json.dumps(dict(zip(by_mode['failure_mode'], by_mode['total_runs'].astype(int))))}")
    print(f"  tables         : {args.output_path}")
    print(f"  report         : {args.report_path}")


if __name__ == "__main__":
    main()

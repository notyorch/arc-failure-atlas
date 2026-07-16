"""Markdown comparison report: local pilot vs public leaderboard context."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from public_results.schemas import PUBLIC_RESULTS_SCHEMA_VERSION


def _md_table(df: pd.DataFrame, float_fmt: str = "{:.3f}") -> str:
    def fmt(value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return "—"
        if isinstance(value, float):
            return float_fmt.format(value)
        return str(value)

    if df.empty:
        return "_(no rows)_"
    header = "| " + " | ".join(df.columns) + " |"
    divider = "|" + "|".join(" --- " for _ in df.columns) + "|"
    rows = [
        "| " + " | ".join(fmt(v) for v in row) + " |"
        for row in df.itertuples(index=False)
    ]
    return "\n".join([header, divider, *rows])


def render_comparison_report(
    public_df: pd.DataFrame,
    *,
    local_run_id: Optional[str] = None,
    chart_relpath: Optional[str] = None,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    df = public_df.copy()

    local = df[df["trust_tier"] == "local_pilot"]
    if local_run_id:
        local = local[local["local_run_id"].astype(str) == str(local_run_id)]
    public = df[df["trust_tier"] != "local_pilot"]

    # Comparable context: exclude sentinel score==0 preview anchors
    context = public[~((public["score"] == 0) & (public["trust_tier"] == "preview"))]

    by_trust = (
        context.groupby("trust_tier", dropna=False)
        .agg(n=("result_id", "count"),
             mean_score=("score", "mean"),
             max_score=("score", "max"))
        .reset_index()
        .sort_values("n", ascending=False)
    )

    overview_cols = [
        "submission_name", "benchmark_name", "score_percent", "trust_tier",
        "split_type", "comparison_scope", "cost_per_task_usd", "source_name",
    ]
    overview = context[overview_cols].sort_values(
        ["benchmark_name", "score_percent"], ascending=[True, False]
    )

    local_section = "_(no local pilot row in this dataset)_"
    if not local.empty:
        row = local.iloc[0]
        local_section = "\n".join([
            f"- **submission:** `{row['submission_name']}`",
            f"- **local_run_id:** `{row['local_run_id']}`",
            f"- **score (task_solved_rate on evaluated tasks):** "
            f"{float(row['score_percent']):.1f}% "
            f"over n_tasks={row['n_tasks']}",
            f"- **comparison_scope:** `{row['comparison_scope']}` "
            "(not a full leaderboard claim)",
            f"- **cost_per_task_usd (platform estimate):** "
            f"{row['cost_per_task_usd']}",
            f"- **notes:** {row['notes']}",
        ])

    chart_block = ""
    if chart_relpath:
        chart_block = (
            f"\n## Chart\n\n"
            f"![score context]({chart_relpath})\n\n"
            "Bars show score %. Local pilot is highlighted; public rows are "
            "external context with trust tiers — **not** a controlled A/B.\n"
        )

    return "\n".join([
        "# Public Results Observatory — Comparison Report",
        "",
        f"_Generated {generated} · schema "
        f"`{PUBLIC_RESULTS_SCHEMA_VERSION}`_",
        "",
        "## What this is",
        "",
        "Structured public ARC / ARC Prize leaderboard **context** alongside "
        "an optional **local platform run**. Public rows are ingested with "
        "provenance and trust metadata. They are **not** re-evaluated here.",
        "",
        "## Local pilot anchor",
        "",
        local_section,
        "",
        "## Honesty rules",
        "",
        "- `local_pilot_partial` ≠ `full_benchmark` / `kaggle_contest` / "
        "`semi_private_100`.",
        "- Prefer `official_verified` / `competition_verified` over "
        "`self_reported` / `preview`.",
        "- Different `benchmark_name` values (ARC-AGI-1 vs ARC-AGI-2) are "
        "**not** interchangeable.",
        "- Cost figures use each source's reported units; platform cost "
        "estimates may be 0.0 when price tables miss a model.",
        chart_block,
        "## Trust-tier summary (public rows only)",
        "",
        _md_table(by_trust),
        "",
        "## Public context table",
        "",
        _md_table(overview, float_fmt="{:.2f}"),
        "",
        "## Sources in this sync",
        "",
        ", ".join(f"`{s}`" for s in sorted(df["source_name"].dropna().unique())),
        "",
        "## Reproduce",
        "",
        "```bash",
        "python src/public_results_cli.py sync",
        "python src/public_results_cli.py compare \\",
        "  --run-id 20260716T010504Z_nim-deepseek-v4-pro_76a8317f",
        "```",
        "",
    ])


def write_report(text: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path

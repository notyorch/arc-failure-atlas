#!/usr/bin/env python3
"""Consolidate pilot/smoke evaluation runs into comparison tables + charts.

Reads completed runs under data/parquet/inference/runs/, optionally filtered
to a curated allow-list of experiment_ids / run_ids, and writes:

  reports/tables/model_comparison.csv
  reports/tables/model_comparison.md
  reports/figures/task_solved_rate_by_model.png
  reports/figures/parse_error_rate_by_model.png
  reports/figures/latency_by_model.png
  reports/figures/failure_mode_mix.png   (for a primary run_id if given)

Usage:
  python scripts/consolidate_pilot_evidence.py
  python scripts/consolidate_pilot_evidence.py --primary-run-id <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RUNS = REPO / "data" / "parquet" / "inference" / "runs"
OUT_TABLES = REPO / "reports" / "tables"
OUT_FIGS = REPO / "reports" / "figures"
sys.path.insert(0, str(REPO / "src"))
from build_analytics import normalize_evaluation_frame  # noqa: E402

# Curated evidence rows (exclude failed auth / unfair thinking dumps / mocks).
INCLUDE = {
    "pilot-glm52-agi1-n20-v2": "20260716T050606Z_opencode-glm-5.2_2343e8c5",
    "smoke-glm52-agi2-n5": "20260716T053528Z_opencode-glm-5.2_83788fd6",
    "smoke-qwen37max-agi2-n5": "20260716T062140Z_opencode-qwen3.7-max_2c9e97c4",
    "pilot-kimi-k26-agi2-n5-nothink": "20260716T032633Z_kimi-k2.6_b997534f",
    "pilot-nim-dsv4pro": "20260716T010504Z_nim-deepseek-v4-pro_76a8317f",
    "real-glm52": "20260715T172307Z_openai_z-ai-glm-5.2_8f9cf828",
    "pilot-glm52-agi2-n120": None,  # latest matching experiment
}

SURFACE = "#F7F4EF"
INK = "#1C1917"
INK2 = "#44403C"
MUTED = "#78716C"
GRID = "#E7E5E4"
TEAL = "#0F766E"
ORANGE = "#C2410C"
BLUE = "#1D4ED8"
AMBER = "#B45309"


def summarize_run(run_dir: Path) -> dict | None:
    parts = list(run_dir.glob("part-*.parquet"))
    if not parts:
        return None
    df = normalize_evaluation_frame(
        pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    )
    item = (
        df.assign(_e=df["is_exact_match"].eq(True).fillna(False))
        .groupby(["task_id", "test_example_id"], sort=False)["_e"].any()
        .reset_index(name="_item")
    )
    task = item.groupby("task_id", sort=False)["_item"].all()
    model = df["model_name"].dropna().astype(str)
    model = model.iloc[0] if len(model) else df["solver_name"].iloc[0]
    bench = df["benchmark_name"].iloc[0] if "benchmark_name" in df else "unknown"
    return {
        "run_id": run_dir.name,
        "experiment_id": str(df["experiment_id"].iloc[0]),
        "solver_name": str(df["solver_name"].iloc[0]),
        "model": str(model),
        "benchmark": str(bench),
        "n_tasks": int(df["task_id"].nunique()),
        "n_items": int(len(item)),
        "n_attempts": int(len(df)),
        "task_solved_rate": float(task.mean()) if len(task) else 0.0,
        "solved_rate": float(item["_item"].mean()) if len(item) else 0.0,
        "exact_match_rate": float(df["is_exact_match"].eq(True).fillna(False).mean()),
        "parse_error_rate": float(df["failure_mode"].eq("parse_error").mean()),
        "execution_error_rate": float(df["failure_mode"].eq("execution_error").mean()),
        "avg_latency_ms": float(df["latency_ms"].mean()),
        "avg_cell_accuracy": float(df["cell_accuracy"].dropna().mean())
        if df["cell_accuracy"].notna().any() else None,
    }


def collect(primary_run_id: str | None = None) -> pd.DataFrame:
    rows = []
    wanted_runs = set()
    for exp, rid in INCLUDE.items():
        if rid:
            wanted_runs.add(rid)
    # Always include primary / latest n120 if present
    if primary_run_id:
        wanted_runs.add(primary_run_id)

    if not RUNS.exists():
        sys.exit(f"missing {RUNS}")

    for d in sorted(RUNS.iterdir()):
        if not d.is_dir():
            continue
        man_path = d / "_manifest.json"
        exp = None
        if man_path.exists():
            try:
                exp = json.loads(man_path.read_text()).get("experiment_id")
            except Exception:
                exp = None
        # include by allow-list run id OR matching experiment with None rid
        include = d.name in wanted_runs
        if not include and exp in INCLUDE and INCLUDE[exp] is None:
            include = True
        if not include and exp == "pilot-glm52-agi2-n120":
            include = True
        if not include:
            continue
        row = summarize_run(d)
        if row:
            rows.append(row)

    if not rows:
        sys.exit("No matching evidence runs found.")
    df = pd.DataFrame(rows).sort_values(
        ["benchmark", "n_tasks", "task_solved_rate"],
        ascending=[True, False, False],
    ).reset_index(drop=True)
    # Prefer the largest n120 run if multiple
    if (df["experiment_id"] == "pilot-glm52-agi2-n120").sum() > 1:
        keep = df[df["experiment_id"] != "pilot-glm52-agi2-n120"]
        n120 = df[df["experiment_id"] == "pilot-glm52-agi2-n120"].sort_values(
            "n_tasks", ascending=False
        ).head(1)
        df = pd.concat([keep, n120], ignore_index=True)
    return df


def write_tables(df: pd.DataFrame) -> None:
    OUT_TABLES.mkdir(parents=True, exist_ok=True)
    csv_path = OUT_TABLES / "model_comparison.csv"
    md_path = OUT_TABLES / "model_comparison.md"
    df.to_csv(csv_path, index=False)
    cols = [
        "model", "benchmark", "n_tasks", "n_items",
        "task_solved_rate", "solved_rate", "parse_error_rate",
        "avg_latency_ms", "experiment_id", "run_id",
    ]
    show = df[[c for c in cols if c in df.columns]].copy()
    for c in ("task_solved_rate", "solved_rate", "parse_error_rate"):
        if c in show.columns:
            show[c] = show[c].map(lambda x: f"{100*float(x):.1f}%")
    if "avg_latency_ms" in show.columns:
        show["avg_latency_ms"] = show["avg_latency_ms"].map(
            lambda x: f"{float(x)/1000:.1f}s"
        )
    lines = [
        "# Model comparison (local pilots / smokes)",
        "",
        "All rows are `local_pilot_partial` unless noted. "
        "`task_solved_rate` is ARC-official task granularity (Decision 21).",
        "",
        show.to_markdown(index=False),
        "",
    ]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {csv_path}")
    print(f"wrote {md_path}")


def _style(ax, fig):
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK2)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def write_charts(df: pd.DataFrame, primary_run_id: str | None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    OUT_FIGS.mkdir(parents=True, exist_ok=True)
    labels = [
        f"{r.model}\n({r.benchmark}, n={r.n_tasks})"
        for r in df.itertuples(index=False)
    ]
    x = range(len(df))

    # 1) task_solved_rate
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=144)
    _style(ax, fig)
    vals = df["task_solved_rate"] * 100
    colors = [TEAL if "agi2" in str(b).lower() or "AGI-2" in str(b) else BLUE
              for b in df["benchmark"]]
    ax.bar(list(x), vals, color=colors, width=0.72)
    ax.set_xticks(list(x), labels, fontsize=8, color=INK2)
    ax.set_ylabel("task_solved_rate (%)", color=INK)
    ax.set_title("Local pilots — ARC task-level solve rate", color=INK, pad=12)
    ax.set_ylim(0, max(40, float(vals.max()) * 1.25 + 5))
    for i, v in enumerate(vals):
        ax.text(i, v + 0.8, f"{v:.1f}%", ha="center", va="bottom",
                fontsize=8, color=INK2)
    fig.tight_layout()
    p1 = OUT_FIGS / "task_solved_rate_by_model.png"
    fig.savefig(p1, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {p1}")

    # 2) parse_error_rate
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=144)
    _style(ax, fig)
    vals = df["parse_error_rate"] * 100
    ax.bar(list(x), vals, color=ORANGE, width=0.72)
    ax.set_xticks(list(x), labels, fontsize=8, color=INK2)
    ax.set_ylabel("parse_error_rate (%)", color=INK)
    ax.set_title("Local pilots — grid parse failures", color=INK, pad=12)
    ax.set_ylim(0, max(40, float(vals.max()) * 1.25 + 5))
    for i, v in enumerate(vals):
        ax.text(i, v + 0.8, f"{v:.1f}%", ha="center", va="bottom",
                fontsize=8, color=INK2)
    fig.tight_layout()
    p2 = OUT_FIGS / "parse_error_rate_by_model.png"
    fig.savefig(p2, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {p2}")

    # 3) latency
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=144)
    _style(ax, fig)
    vals = df["avg_latency_ms"] / 1000.0
    ax.bar(list(x), vals, color=AMBER, width=0.72)
    ax.set_xticks(list(x), labels, fontsize=8, color=INK2)
    ax.set_ylabel("avg latency (s / attempt)", color=INK)
    ax.set_title("Local pilots — mean wall-clock latency", color=INK, pad=12)
    for i, v in enumerate(vals):
        ax.text(i, v + max(vals) * 0.02, f"{v:.1f}s", ha="center",
                va="bottom", fontsize=8, color=INK2)
    fig.tight_layout()
    p3 = OUT_FIGS / "latency_by_model.png"
    fig.savefig(p3, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {p3}")

    # 4) failure mix for primary run
    rid = primary_run_id
    if not rid:
        n120 = df[df["experiment_id"] == "pilot-glm52-agi2-n120"]
        if len(n120):
            rid = n120.iloc[0]["run_id"]
        else:
            rid = df.sort_values("n_tasks", ascending=False).iloc[0]["run_id"]
    run_dir = RUNS / rid
    if run_dir.exists():
        parts = list(run_dir.glob("part-*.parquet"))
        rdf = normalize_evaluation_frame(
            pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
        )
        counts = rdf["failure_mode"].fillna("(null)").value_counts()
        fig, ax = plt.subplots(figsize=(9, 5), dpi=144)
        _style(ax, fig)
        ax.barh(list(counts.index[::-1]), list(counts.values[::-1]),
                color=TEAL, height=0.65)
        ax.set_xlabel("attempt rows", color=INK)
        ax.set_title(f"Failure modes — {rid}", color=INK, pad=12, fontsize=11)
        fig.tight_layout()
        p4 = OUT_FIGS / "failure_mode_mix.png"
        fig.savefig(p4, bbox_inches="tight")
        plt.close(fig)
        print(f"wrote {p4}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary-run-id", default=None)
    args = parser.parse_args()
    df = collect(args.primary_run_id)
    write_tables(df)
    write_charts(df, args.primary_run_id)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Plot per-task performance and cross-run variance for a multi-run experiment.

Point it at two or more evaluation runs under data/parquet/inference/runs/
whose experiment_id values share a common prefix (replicate runs of the same
solver over the same tasks), e.g.:

    python src/run_evaluation.py --provider openai --model M --experiment-id exp1-r1
    python src/run_evaluation.py --provider openai --model M --experiment-id exp1-r2
    python scripts/plot_run_variance.py --prefix exp1

Outputs to artifacts/<prefix>/ (override with --out):
  charts/per_task_cell_accuracy.png
  charts/per_task_latency.png
  charts/variance_summary.png
  summary_by_task.csv
  run_comparison.csv

Optional tooling: needs matplotlib (like scripts/demo_bundle.py). Works with
a single run too, but variance columns are then all zero.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"
sys.path.insert(0, str(REPO_ROOT / "src"))
from build_analytics import normalize_evaluation_frame  # noqa: E402

SURFACE = "#F7F4EF"
INK = "#1C1917"
INK_SECONDARY = "#44403C"
INK_MUTED = "#78716C"
GRIDLINE = "#E7E5E4"
SERIES_1 = "#0F766E"
SERIES_2 = "#C2410C"
SERIES_3 = "#1D4ED8"


def load_runs(prefix: str) -> pd.DataFrame:
    frames = []
    if not RUNS_DIR.exists():
        sys.exit(f"ERROR: missing runs dir {RUNS_DIR}")
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        parts = list(run_dir.glob("part-*.parquet"))
        if not parts:
            continue
        df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
        if "experiment_id" not in df.columns:
            continue
        exp = df["experiment_id"].astype(str)
        if not exp.str.startswith(prefix).any():
            continue
        df = df[exp.str.startswith(prefix)].copy()
        frames.append(df)
    if not frames:
        sys.exit(f"ERROR: no runs matching experiment_id prefix {prefix!r}")
    return normalize_evaluation_frame(pd.concat(frames, ignore_index=True))


def per_task_stats(df: pd.DataFrame) -> pd.DataFrame:
    """One row per task with mean/std across replicate runs."""
    df = df.copy()
    df["exact_match_num"] = df["is_exact_match"].fillna(False).astype(float)
    g = df.groupby("task_id", sort=True)
    out = g.agg(
        n_runs=("run_id", "nunique"),
        n_rows=("run_id", "size"),
        mean_cell_accuracy=("cell_accuracy", "mean"),
        std_cell_accuracy=("cell_accuracy", "std"),
        mean_exact_match=("exact_match_num", "mean"),
        std_exact_match=("exact_match_num", "std"),
        mean_latency_ms=("latency_ms", "mean"),
        std_latency_ms=("latency_ms", "std"),
        dominant_failure=("failure_mode",
                          lambda s: s.mode().iloc[0] if len(s.mode()) else None),
    ).reset_index()
    # pandas std is NaN with a single observation
    for col in ("std_cell_accuracy", "std_exact_match", "std_latency_ms"):
        out[col] = out[col].fillna(0.0)
    return out


def run_comparison(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (run_id, exp), g in df.groupby(["run_id", "experiment_id"], sort=True):
        n = len(g)
        rows.append({
            "run_id": run_id,
            "experiment_id": exp,
            "n_tasks": n,
            "exact_match_rate": g["is_exact_match"].fillna(False).mean(),
            "avg_cell_accuracy": g["cell_accuracy"].mean(),
            "avg_latency_ms": g["latency_ms"].mean(),
            "parse_error_rate": (g["failure_mode"] == "parse_error").mean(),
            "execution_error_rate": (g["failure_mode"] == "execution_error").mean(),
        })
    return pd.DataFrame(rows)


def style_ax(ax, title: str, subtitle: str) -> None:
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=13, color=INK, pad=10, fontweight="600")
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9,
            color=INK_MUTED, va="bottom")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.spines["left"].set_color(GRIDLINE)
    ax.spines["bottom"].set_color(GRIDLINE)
    ax.tick_params(colors=INK_SECONDARY)


def chart_per_task_accuracy(plt, stats: pd.DataFrame, out: Path) -> None:
    data = stats.copy()
    data["mean_plot"] = data["mean_cell_accuracy"].fillna(0.0)
    data["std_plot"] = data["std_cell_accuracy"].fillna(0.0)
    data["evaluated"] = data["mean_cell_accuracy"].notna()
    data = data.sort_values(["evaluated", "mean_plot"], ascending=[True, True])
    y = range(len(data))
    colors = [SERIES_1 if ok else "#A8A29E" for ok in data["evaluated"]]
    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.32 * len(data) + 1.5)))
    fig.patch.set_facecolor(SURFACE)
    n_ok = int(data["evaluated"].sum())
    style_ax(
        ax,
        "Cell accuracy per task (mean ± std across runs)",
        f"Grey bars = never evaluable (execution_error only). "
        f"Evaluated on ≥1 run: {n_ok}/{len(data)}. Error bars = sample std.",
    )
    ax.grid(axis="x", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.barh(
        list(y), data["mean_plot"].tolist(),
        xerr=data["std_plot"].tolist(),
        color=colors, height=0.7,
        error_kw={"ecolor": INK_MUTED, "capsize": 2, "elinewidth": 1},
    )
    ax.set_yticks(list(y), data["task_id"].tolist(), fontsize=8, color=INK_SECONDARY)
    ax.set_xlim(0, 1.05)
    ax.xaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.set_xlabel("mean cell accuracy", fontsize=9, color=INK_MUTED)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"  chart → {out.relative_to(REPO_ROOT)}")


def chart_per_task_latency(plt, stats: pd.DataFrame, out: Path) -> None:
    data = stats.sort_values("mean_latency_ms")
    y = range(len(data))
    fig, ax = plt.subplots(figsize=(9, max(4.5, 0.32 * len(data) + 1.5)))
    fig.patch.set_facecolor(SURFACE)
    style_ax(
        ax,
        "Latency per task (mean ± std across runs)",
        "Wall-clock ms per call. Large variance often signals cold starts / retries.",
    )
    ax.grid(axis="x", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.barh(
        list(y), data["mean_latency_ms"],
        xerr=data["std_latency_ms"],
        color=SERIES_2, height=0.7,
        error_kw={"ecolor": INK_MUTED, "capsize": 2, "elinewidth": 1},
    )
    ax.set_yticks(list(y), data["task_id"].tolist(), fontsize=8, color=INK_SECONDARY)
    ax.set_xlabel("mean latency (ms)", fontsize=9, color=INK_MUTED)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"  chart → {out.relative_to(REPO_ROOT)}")


def chart_variance_summary(plt, stats: pd.DataFrame, runs: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.2))
    fig.patch.set_facecolor(SURFACE)

    ax = axes[0]
    style_ax(ax, "Run-level metrics", "Each bar = one full pass over the same tasks.")
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    labels = [str(e).split("-r")[-1] if "-r" in str(e) else str(e)[-8:]
              for e in runs["experiment_id"]]
    x = range(len(runs))
    w = 0.35
    exact = runs["exact_match_rate"].fillna(0.0).tolist()
    cell = runs["avg_cell_accuracy"].fillna(0.0).tolist()
    ax.bar([i - w / 2 for i in x], exact, w,
           color=SERIES_1, label="exact-match rate")
    ax.bar([i + w / 2 for i in x], cell, w,
           color=SERIES_3, label="avg cell accuracy")
    ax.set_xticks(list(x), [f"run {l}" for l in labels], color=INK_SECONDARY)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.legend(frameon=False, fontsize=8, labelcolor=INK_SECONDARY)

    ax = axes[1]
    style_ax(
        ax,
        "Cross-run variance by task",
        f"Mean of per-task stds over {len(stats)} tasks "
        f"({int(stats['n_runs'].max())} replicate runs).",
    )
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    evaluated = stats[stats["mean_cell_accuracy"].notna()]
    latency_cv = (
        (stats["std_latency_ms"] / stats["mean_latency_ms"].replace(0, pd.NA))
        .dropna()
    )
    metrics = [
        ("cell acc.\nstd",
         float(evaluated["std_cell_accuracy"].mean()) if len(evaluated) else 0.0),
        ("exact match\nstd", float(stats["std_exact_match"].mean())),
        ("latency\nCV", float(latency_cv.mean()) if len(latency_cv) else 0.0),
    ]
    names = [m[0] for m in metrics]
    vals = [float(m[1]) for m in metrics]
    bars = ax.bar(names, vals, color=[SERIES_1, SERIES_3, SERIES_2], width=0.55)
    for bar, val in zip(bars, vals):
        ax.annotate(f"{val:.3f}",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=9, color=INK)
    ax.set_ylabel("dispersion", fontsize=9, color=INK_MUTED)

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE, bbox_inches="tight")
    plt.close(fig)
    print(f"  chart → {out.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-task performance and cross-run variance charts for "
                    "replicate inference runs sharing an experiment_id prefix.",
    )
    parser.add_argument("--prefix", required=True,
                        help="experiment_id prefix shared by the replicate "
                             "runs (e.g. exp1 matches exp1-r1, exp1-r2)")
    parser.add_argument("--out", type=Path, default=None,
                        help="output directory (default: artifacts/<prefix>/)")
    args = parser.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out = args.out
    if out is None:
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", args.prefix).strip("-") or "variance"
        out = REPO_ROOT / "artifacts" / safe

    df = load_runs(args.prefix)
    stats = per_task_stats(df)
    runs = run_comparison(df)

    out.mkdir(parents=True, exist_ok=True)
    charts = out / "charts"
    stats.to_csv(out / "summary_by_task.csv", index=False)
    runs.to_csv(out / "run_comparison.csv", index=False)
    print(f"Loaded {len(df)} rows across {df['run_id'].nunique()} run(s), "
          f"{df['task_id'].nunique()} tasks")
    print(runs.to_string(index=False))

    chart_per_task_accuracy(plt, stats, charts / "per_task_cell_accuracy.png")
    chart_per_task_latency(plt, stats, charts / "per_task_latency.png")
    chart_variance_summary(plt, stats, runs, charts / "variance_summary.png")
    print(f"Done → {out.relative_to(REPO_ROOT)}/")


if __name__ == "__main__":
    main()

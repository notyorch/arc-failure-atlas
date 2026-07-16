"""
Build a presentation-ready demo bundle at artifacts/demo/.

Runs the offline mock pipeline end to end (sample data → ETL → two mock
solver evaluations → analytics + report), copies the analytics CSV exports,
and renders PNG charts:

    artifacts/demo/
      README.md                        what's here + 5-minute demo flow
      mvp_report.md                    copy of the regenerated report
      analytics_manifest.json          provenance (git SHA, runs, versions)
      csv/summary_by_solver.csv
      csv/summary_by_failure_mode.csv
      csv/summary_by_task.csv
      csv/solver_failure_matrix.csv
      charts/accuracy_by_solver.png
      charts/failure_mode_distribution.png
      charts/latency_by_solver.png
      charts/solver_failure_matrix.png

Offline-first and deterministic: only bundled sample tasks are required
(any ARC tasks already in data/raw/evaluation/ are included too), the mock
backends are hash-deterministic per (solver, task), and each bundle uses its
own experiment id (demo-<UTC ts>) so metrics never mix with earlier runs.

    python scripts/demo_bundle.py          # ~15 s, offline
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEMO_DIR = REPO_ROOT / "artifacts" / "demo"
ANALYTICS_DIR = REPO_ROOT / "data" / "parquet" / "analytics"
REPORT_PATH = REPO_ROOT / "reports" / "mvp_report.md"
MOCK_SOLVERS = ["mock-baseline", "mock-large"]

# The bundle is a curated offline demo with fixed paths: strip ATLAS_*
# variables so an exported provider/output-root cannot redirect the
# pipeline steps away from the locations this script reads back.
SUBPROCESS_ENV = {k: v for k, v in os.environ.items()
                  if not k.startswith("ATLAS_")}

# Chart chrome — reference dataviz palette (light mode, validated set).
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES_1 = "#2a78d6"   # categorical slot 1 (blue)
SERIES_2 = "#1baf7a"   # categorical slot 2 (aqua)
SEQ_LOW, SEQ_HIGH = "#cde2fb", "#0d366b"   # sequential blue ramp endpoints


def run_step(name: str, cmd: list) -> None:
    print(f"[{name}] $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True,
                            env=SUBPROCESS_ENV)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        sys.exit(f"DEMO BUNDLE FAIL — step '{name}' exited {result.returncode}")
    print(f"[{name}] OK")


def run_pipeline(experiment_id: str) -> None:
    """Sample data → ETL → two mock solver runs → analytics for this bundle."""
    py = sys.executable
    run_step("fetch-sample",
             [py, "scripts/fetch_arc_data.py", "--sample"])
    run_step("etl", [py, "src/main.py"])
    for solver in MOCK_SOLVERS:
        run_step(f"eval:{solver}", [
            py, "src/run_evaluation.py", "--solver", solver,
            "--experiment-id", experiment_id,
        ])
    run_step("analytics", [
        py, "src/build_analytics.py", "--experiment-id", experiment_id,
    ])


# CHARTS

def new_axes(plt, title: str, subtitle: str, figsize=(8, 4.5)):
    import textwrap

    fig, ax = plt.subplots(figsize=figsize, dpi=144)
    fig.subplots_adjust(top=0.80)  # reserved header band: no title collisions
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)
    ax.tick_params(colors=INK_MUTED, labelsize=9, length=0)
    left = ax.get_position().x0
    fig.text(left, 0.955, title, ha="left", va="top",
             fontsize=12, fontweight="semibold", color=INK)
    fig.text(left, 0.885, "\n".join(textwrap.wrap(subtitle, width=88)),
             ha="left", va="top", fontsize=9, color=INK_SECONDARY)
    return fig, ax


def save(fig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, facecolor=SURFACE, bbox_inches="tight")
    print(f"  chart → {path.relative_to(REPO_ROOT)}")


def chart_accuracy_by_solver(plt, by_solver, out: Path) -> None:
    data = by_solver.sort_values("solver_name")
    labels = data["solver_name"].astype(str).tolist()
    x = range(len(labels))
    width = 0.26

    fig, ax = new_axes(
        plt, "Accuracy by solver",
        "Exact-match rate is attempt-level; solved_rate (not shown) is "
        "item-level pass@k. Mock solvers demo the platform, not skill.",
        figsize=(7, 4.5),
    )
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    bars1 = ax.bar([i - width / 2 - 0.01 for i in x],
                   data["exact_match_rate"], width,
                   color=SERIES_1, label="exact-match rate")
    bars2 = ax.bar([i + width / 2 + 0.01 for i in x],
                   data["avg_cell_accuracy"], width,
                   color=SERIES_2, label="avg cell accuracy")
    for bars in (bars1, bars2):
        for bar in bars:
            ax.annotate(f"{bar.get_height():.0%}",
                        (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                        xytext=(0, 4), textcoords="offset points",
                        ha="center", fontsize=9, color=INK)
    ax.set_xticks(list(x), labels, color=INK_SECONDARY)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(plt.matplotlib.ticker.PercentFormatter(1.0))
    ax.legend(frameon=False, fontsize=9, labelcolor=INK_SECONDARY,
              loc="upper right")
    save(fig, out)
    plt.close(fig)


def chart_failure_modes(plt, by_mode, total_rows: int, out: Path) -> None:
    data = by_mode.sort_values(["n_attempts", "failure_mode"],
                               ascending=[True, False])
    labels = data["failure_mode"].astype(str).tolist()
    counts = data["n_attempts"].tolist()

    fig, ax = new_axes(
        plt, "Failure mode distribution",
        f"All modes across {total_rows} scored attempt rows (both mock "
        "solvers); exact_match is the success bucket.",
        figsize=(8, 4.8),
    )
    ax.grid(axis="x", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    bars = ax.barh(labels, counts, height=0.62, color=SERIES_1)
    for bar, count in zip(bars, counts):
        share = count / total_rows
        ax.annotate(f"{count}  ({share:.0%})",
                    (bar.get_width(), bar.get_y() + bar.get_height() / 2),
                    xytext=(5, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)
    ax.tick_params(axis="y", labelsize=10)
    for tick in ax.get_yticklabels():
        tick.set_color(INK_SECONDARY)
    ax.set_xlim(0, max(counts) * 1.18)
    ax.xaxis.set_major_locator(plt.matplotlib.ticker.MaxNLocator(integer=True))
    save(fig, out)
    plt.close(fig)


def chart_latency_by_solver(plt, by_solver, out: Path) -> None:
    data = by_solver.sort_values("solver_name")
    labels = data["solver_name"].astype(str).tolist()
    values = data["avg_latency_ms"].tolist()

    fig, ax = new_axes(
        plt, "Average latency by solver",
        "Milliseconds per evaluation item. Mock latency is synthetic and "
        "deterministic; real backends report wall-clock time.",
        figsize=(6, 4.2),
    )
    ax.grid(axis="y", color=GRIDLINE, linewidth=0.8)
    ax.set_axisbelow(True)
    bars = ax.bar(labels, values, width=0.3, color=SERIES_1)
    for bar in bars:
        ax.annotate(f"{bar.get_height():.1f} ms",
                    (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 4), textcoords="offset points",
                    ha="center", fontsize=9, color=INK)
    for tick in ax.get_xticklabels():
        tick.set_color(INK_SECONDARY)
    ax.set_ylim(0, max(values) * 1.15)
    ax.set_ylabel("avg latency (ms)", fontsize=9, color=INK_MUTED)
    save(fig, out)
    plt.close(fig)


def chart_solver_failure_matrix(plt, matrix, out: Path):
    """Heatmap: failure_mode rows × solver columns, annotated counts."""
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("seq_blue", [SEQ_LOW, SEQ_HIGH])
    fig, ax = new_axes(
        plt, "Failure mode × solver (row counts)",
        "Compact comparison of error types per solver over the same tasks.",
        figsize=(7, 4.8),
    )
    ax.spines["bottom"].set_visible(False)
    mesh = ax.pcolormesh(matrix.values, cmap=cmap, vmin=0,
                         edgecolors=SURFACE, linewidth=2)
    vmax = matrix.values.max() or 1
    for i, _mode in enumerate(matrix.index):
        for j, _solver in enumerate(matrix.columns):
            value = int(matrix.iat[i, j])
            dark_cell = (value / vmax) > 0.55
            ax.text(j + 0.5, i + 0.5, str(value), ha="center", va="center",
                    fontsize=10, color="#ffffff" if dark_cell else INK)
    ax.set_xticks([j + 0.5 for j in range(len(matrix.columns))],
                  [str(c) for c in matrix.columns], color=INK_SECONDARY)
    ax.set_yticks([i + 0.5 for i in range(len(matrix.index))],
                  [str(r) for r in matrix.index], color=INK_SECONDARY)
    ax.invert_yaxis()
    mesh.set_rasterized(False)
    save(fig, out)
    plt.close(fig)


# BUNDLE ASSEMBLY

def copy_csv_exports(pd, csv_src: Path, csv_dir: Path):
    """
    Copy the CSVs that build_analytics already exported (single source of
    truth — this script no longer recomputes them). Returns the
    failure-mode × solver matrix for the heatmap chart, read back from the
    same CSV so chart and table can never disagree.
    """
    if not csv_src.exists():
        sys.exit(f"ERROR: analytics CSV exports not found at {csv_src}. "
                 "Run `python src/build_analytics.py` first "
                 "(or drop --skip-pipeline).")
    shutil.copytree(csv_src, csv_dir)
    for path in sorted(csv_dir.glob("*.csv")):
        print(f"  csv   → {path.relative_to(REPO_ROOT)}")
    return pd.read_csv(csv_dir / "solver_failure_matrix.csv",
                       index_col="failure_mode")


def write_demo_readme(experiment_id: str, n_tasks: int, n_rows: int) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (DEMO_DIR / "README.md").write_text(f"""# ARC Solver Evaluation Platform — Demo Bundle

Generated by `python scripts/demo_bundle.py` on {generated}
(experiment `{experiment_id}`, {n_tasks} tasks, {n_rows} scored rows,
two deterministic mock solvers — fully offline).

## Contents

| File | Show it when you say... |
| --- | --- |
| `mvp_report.md` | "here is the generated evaluation report" |
| `charts/accuracy_by_solver.png` | "we score every prediction cell by cell" |
| `charts/failure_mode_distribution.png` | "failures get a deterministic taxonomy label" |
| `charts/solver_failure_matrix.png` | "and we can compare error types across solvers" |
| `charts/latency_by_solver.png` | "latency and cost are captured per call" |
| `csv/*.csv` | "summaries are plain tables — Excel/BI ready" |
| `analytics_manifest.json` | "every artifact traces to a git commit and run" |

## 5-minute demo flow

1. **The problem (30 s)** — we evaluate *heterogeneous ARC solvers* under one
   protocol, not how to solve ARC. README top + architecture diagram.
2. **The pipeline (1 min)** — raw JSON → frozen-schema Parquet → solver
   adapter → parse → score → failure taxonomy → analytics. Everything here
   ran offline with deterministic mock solvers.
3. **The report (1.5 min)** — open `mvp_report.md`: metrics by solver,
   failure-mode distribution, concrete example failures.
4. **The charts (1.5 min)** — accuracy, failure modes, solver × failure
   matrix, latency. Same numbers as the CSVs and Parquet tables.
5. **Reproducibility (30 s)** — `analytics_manifest.json`: git SHA, run
   ids, schema versions. Rerun `python scripts/demo_bundle.py` → same
   metrics. Swap `--solver mock-baseline` for a real registry entry or
   `--provider`/`--model` and the same platform evaluates it.

## Regenerate

```bash
python scripts/demo_bundle.py
```

Mock results are deterministic per (solver, task); rerunning changes only
run ids and timestamps. With network, add more real tasks first:
`python scripts/fetch_arc_data.py --limit 20`.
""", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--skip-pipeline", action="store_true",
                        help="reuse existing analytics outputs; only rebuild "
                             "the artifacts/demo/ bundle")
    args = parser.parse_args()

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("ERROR: matplotlib is required for demo charts — "
                 "pip install -r requirements.txt")
    import pandas as pd

    experiment_id = "demo-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if not args.skip_pipeline:
        run_pipeline(experiment_id)

    fact = pd.read_parquet(ANALYTICS_DIR / "fact_evaluation_results")
    by_solver = pd.read_parquet(ANALYTICS_DIR / "summary_by_solver")
    by_mode = pd.read_parquet(ANALYTICS_DIR / "summary_by_failure_mode")

    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir(parents=True)

    print("\nExporting bundle:")
    matrix = copy_csv_exports(pd, ANALYTICS_DIR / "csv", DEMO_DIR / "csv")

    charts = DEMO_DIR / "charts"
    chart_accuracy_by_solver(plt, by_solver, charts / "accuracy_by_solver.png")
    chart_failure_modes(plt, by_mode, len(fact),
                        charts / "failure_mode_distribution.png")
    chart_latency_by_solver(plt, by_solver, charts / "latency_by_solver.png")
    chart_solver_failure_matrix(plt, matrix,
                                charts / "solver_failure_matrix.png")

    shutil.copy2(REPORT_PATH, DEMO_DIR / "mvp_report.md")
    shutil.copy2(ANALYTICS_DIR / "_manifest.json",
                 DEMO_DIR / "analytics_manifest.json")
    manifest = json.loads((DEMO_DIR / "analytics_manifest.json").read_text())
    write_demo_readme(manifest.get("experiment_id_filter") or experiment_id,
                      n_tasks=fact["task_id"].nunique(), n_rows=len(fact))

    print(f"\nDEMO BUNDLE READY → {DEMO_DIR.relative_to(REPO_ROOT)}")
    for path in sorted(DEMO_DIR.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(DEMO_DIR)}")


if __name__ == "__main__":
    main()

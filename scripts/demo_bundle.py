"""
Build a presentation-ready demo bundle at artifacts/demo/.

Runs the offline mock pipeline end to end (sample data → ETL → two mock
runs → analytics + report), then exports CSV summaries and PNG charts:

    artifacts/demo/
      README.md                        what's here + 5-minute demo flow
      mvp_report.md                    copy of the regenerated report
      analytics_manifest.json          provenance (git SHA, runs, versions)
      csv/summary_by_model.csv
      csv/summary_by_failure_mode.csv
      csv/summary_by_task.csv
      csv/model_failure_matrix.csv
      charts/accuracy_by_model.png
      charts/failure_mode_distribution.png
      charts/latency_by_model.png
      charts/model_failure_matrix.png

Offline-first and deterministic: only bundled sample tasks are required
(any ARC tasks already in data/raw/evaluation/ are included too), the mock
provider is hash-deterministic per (model, task), and each bundle uses its
own experiment id (demo-<UTC ts>) so metrics never mix with earlier runs.

    python scripts/demo_bundle.py          # ~15 s, offline
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

DEMO_DIR = REPO_ROOT / "artifacts" / "demo"
ANALYTICS_DIR = REPO_ROOT / "data" / "parquet" / "analytics"
REPORT_PATH = REPO_ROOT / "reports" / "mvp_report.md"
MOCK_MODELS = ["baseline", "mock-large"]

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
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        sys.exit(f"DEMO BUNDLE FAIL — step '{name}' exited {result.returncode}")
    print(f"[{name}] OK")


def run_pipeline(experiment_id: str) -> None:
    """Sample data → ETL → two mock runs → analytics filtered to this bundle."""
    py = sys.executable
    run_step("fetch-sample",
             [py, "scripts/fetch_arc_data.py", "--sample"])
    run_step("etl", [py, "src/main.py"])
    for model in MOCK_MODELS:
        run_step(f"infer-mock:{model}", [
            py, "src/run_inference.py", "--provider", "mock",
            "--model", model, "--experiment-id", experiment_id,
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


def chart_accuracy_by_model(plt, by_model, out: Path) -> None:
    data = by_model.sort_values("model_name")
    labels = data["model_name"].astype(str).tolist()
    x = range(len(labels))
    width = 0.26

    fig, ax = new_axes(
        plt, "Accuracy by model",
        "Exact-match rate counts every row; cell accuracy averages valid "
        "predictions only. Mock models demo the pipeline, not skill.",
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
    data = by_mode.sort_values(["total_runs", "failure_mode"],
                               ascending=[True, False])
    labels = data["failure_mode"].astype(str).tolist()
    counts = data["total_runs"].tolist()

    fig, ax = new_axes(
        plt, "Failure mode distribution",
        f"All modes across {total_rows} scored rows (both mock models); "
        "exact_match is the success bucket.",
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


def chart_latency_by_model(plt, by_model, out: Path) -> None:
    data = by_model.sort_values("model_name")
    labels = data["model_name"].astype(str).tolist()
    values = data["avg_latency_ms"].tolist()

    fig, ax = new_axes(
        plt, "Average latency by model",
        "Milliseconds per inference call. Mock latency is synthetic and "
        "deterministic; real providers report wall-clock time.",
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


def chart_model_failure_matrix(plt, matrix, out: Path):
    """Heatmap: failure_mode rows × model columns, annotated counts."""
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("seq_blue", [SEQ_LOW, SEQ_HIGH])
    fig, ax = new_axes(
        plt, "Failure mode × model (row counts)",
        "Compact comparison of error types per model over the same tasks.",
        figsize=(7, 4.8),
    )
    ax.spines["bottom"].set_visible(False)
    mesh = ax.pcolormesh(matrix.values, cmap=cmap, vmin=0,
                         edgecolors=SURFACE, linewidth=2)
    vmax = matrix.values.max() or 1
    for i, mode in enumerate(matrix.index):
        for j, _model in enumerate(matrix.columns):
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

def export_csvs(pd, fact, by_model, by_mode, by_task, csv_dir: Path):
    csv_dir.mkdir(parents=True, exist_ok=True)
    exports = {
        "summary_by_model.csv": by_model.sort_values("model_name"),
        "summary_by_failure_mode.csv":
            by_mode.sort_values(["total_runs", "failure_mode"],
                                ascending=[False, True]),
        "summary_by_task.csv": by_task.sort_values("task_id"),
    }
    matrix = (
        fact.assign(failure_mode=fact["failure_mode"].fillna("not_classifiable"))
        .pivot_table(index="failure_mode", columns="model_name",
                     values="run_id", aggfunc="count", fill_value=0,
                     observed=True)
        .sort_index()
    )
    matrix.columns = [str(c) for c in matrix.columns]
    exports["model_failure_matrix.csv"] = matrix.reset_index()

    for name, frame in exports.items():
        frame.to_csv(csv_dir / name, index=False)
        print(f"  csv   → {(csv_dir / name).relative_to(REPO_ROOT)}")
    return matrix


def write_demo_readme(experiment_id: str, n_tasks: int, n_rows: int) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (DEMO_DIR / "README.md").write_text(f"""# ARC Failure Atlas — Demo Bundle

Generated by `python scripts/demo_bundle.py` on {generated}
(experiment `{experiment_id}`, {n_tasks} tasks, {n_rows} scored rows,
two deterministic mock models — fully offline).

## Contents

| File | Show it when you say... |
| --- | --- |
| `mvp_report.md` | "here is the generated evaluation report" |
| `charts/accuracy_by_model.png` | "we score every prediction cell by cell" |
| `charts/failure_mode_distribution.png` | "failures get a deterministic taxonomy label" |
| `charts/model_failure_matrix.png` | "and we can compare error types across models" |
| `charts/latency_by_model.png` | "latency and cost are captured per call" |
| `csv/*.csv` | "summaries are plain tables — Excel/BI ready" |
| `analytics_manifest.json` | "every artifact traces to a git commit and run" |

## 5-minute demo flow

1. **The problem (30 s)** — we study *how* LLMs fail on ARC-AGI, not how to
   solve it. README top + architecture diagram.
2. **The pipeline (1 min)** — raw JSON → frozen-schema Parquet → prompts →
   provider → grid parsing → scoring → failure taxonomy → analytics.
   Everything here ran offline with the deterministic mock provider.
3. **The report (1.5 min)** — open `mvp_report.md`: metrics by model,
   failure-mode distribution, three concrete example failures with
   expected vs predicted grids.
4. **The charts (1.5 min)** — accuracy, failure modes, model × failure
   matrix, latency. Same numbers as the CSVs and Parquet tables.
5. **Reproducibility (30 s)** — `analytics_manifest.json`: git SHA, run
   ids, schema versions. Rerun `python scripts/demo_bundle.py` → same
   metrics. Swap `--provider mock` for `openai`/`ollama` and the same
   pipeline evaluates real models.

## Regenerate

```bash
python scripts/demo_bundle.py
```

Mock results are deterministic per (model, task); rerunning changes only
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

    fact = pd.read_parquet(ANALYTICS_DIR / "fact_inference_results")
    by_model = pd.read_parquet(ANALYTICS_DIR / "summary_by_model")
    by_mode = pd.read_parquet(ANALYTICS_DIR / "summary_by_failure_mode")
    by_task = pd.read_parquet(ANALYTICS_DIR / "summary_by_task")

    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir(parents=True)

    print("\nExporting bundle:")
    matrix = export_csvs(pd, fact, by_model, by_mode, by_task, DEMO_DIR / "csv")

    charts = DEMO_DIR / "charts"
    chart_accuracy_by_model(plt, by_model, charts / "accuracy_by_model.png")
    chart_failure_modes(plt, by_mode, len(fact),
                        charts / "failure_mode_distribution.png")
    chart_latency_by_model(plt, by_model, charts / "latency_by_model.png")
    chart_model_failure_matrix(plt, matrix,
                               charts / "model_failure_matrix.png")

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

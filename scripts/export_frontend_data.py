"""
Export frontend-ready JSON from existing platform artifacts.

Reads:
  - local evaluation run Parquet + _manifest.json
  - public_results leaderboard_rows Parquet (if present)

Writes:
  frontend/public/data/overview.json

Does not call model APIs. Safe to re-run after new analytics/compare syncs.

    python scripts/export_frontend_data.py
    python scripts/export_frontend_data.py --run-id <id>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
# Primary evidence for the presentation: full ARC-AGI-2 public-eval pilot (n=120).
DEFAULT_RUN_ID = "20260716T155616Z_opencode-glm-5.2_15691f67"
RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"
PUBLIC_DIR = REPO_ROOT / "data" / "parquet" / "public_results" / "leaderboard_rows"
OUT_PATH = REPO_ROOT / "frontend" / "public" / "data" / "overview.json"


def _resolve_run_dir(run_id: str) -> Path | None:
    run_dir = RUNS_DIR / run_id
    if run_dir.exists():
        return run_dir
    matches = (
        [p for p in RUNS_DIR.iterdir() if p.is_dir() and run_id in p.name]
        if RUNS_DIR.exists()
        else []
    )
    return matches[0] if len(matches) == 1 else None


def summarize_run(run_dir: Path) -> dict | None:
    """Full per-run summary including Decision 21 metrics (item + task level)."""
    manifest_path = run_dir / "_manifest.json"
    parts = list(run_dir.glob("part-*.parquet"))
    if not parts or not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    exact = df["is_exact_match"].eq(True).fillna(False)

    item_key = ["task_id", "test_example_id"]
    item_solved = df.assign(_exact=exact).groupby(item_key, sort=False)["_exact"].any()
    n_items = int(item_solved.shape[0])
    solved_items = int(item_solved.sum())

    # ARC-official: a task counts as solved only if ALL its test examples solved.
    task_all_solved = item_solved.reset_index().groupby("task_id")["_exact"].all()
    n_task_count = int(task_all_solved.shape[0])
    solved_tasks = int(task_all_solved.sum())

    parse_errors = int(df["failure_mode"].eq("parse_error").sum())
    exec_errors = int(df["failure_mode"].eq("execution_error").sum())
    failure_counts = df["failure_mode"].fillna("not_classifiable").value_counts().to_dict()
    failure_modes = [
        {"mode": str(k), "count": int(v)}
        for k, v in sorted(failure_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    dominant = failure_modes[0]["mode"] if failure_modes else None
    solver = manifest.get("solver") or {}
    benchmark = manifest.get("benchmark") or {}
    return {
        "run_id": manifest.get("run_id") or run_dir.name,
        "experiment_id": manifest.get("experiment_id"),
        "status": manifest.get("status"),
        "solver_name": solver.get("solver_name"),
        "solver_family": solver.get("solver_family"),
        "model_name": solver.get("model_name"),
        "provider": solver.get("provider"),
        "prompt_version": solver.get("prompt_version"),
        "base_url": solver.get("base_url"),
        "pack_id": benchmark.get("pack_id"),
        "benchmark_name": benchmark.get("benchmark_name"),
        "benchmark_version": benchmark.get("benchmark_version"),
        "n_tasks": n_items,
        "n_task_count": n_task_count,
        "n_attempts": int(len(df)),
        "solved_rate": (solved_items / n_items) if n_items else None,
        "task_solved_rate": (solved_tasks / n_task_count) if n_task_count else None,
        "exact_match_rate": float(exact.mean()) if len(df) else None,
        "parse_error_rate": (parse_errors / len(df)) if len(df) else None,
        "parse_error_count": parse_errors,
        "execution_error_rate": (exec_errors / len(df)) if len(df) else None,
        "execution_error_count": exec_errors,
        "avg_cell_accuracy": float(df["cell_accuracy"].mean()) if df["cell_accuracy"].notna().any() else None,
        "avg_latency_ms": float(df["latency_ms"].mean()) if len(df) else None,
        "total_cost_estimate_usd": float(df["cost_estimate_usd"].sum()) if len(df) else None,
        "tokens_in": manifest.get("total_input_tokens"),
        "tokens_out": manifest.get("total_output_tokens"),
        "started_at": manifest.get("started_at"),
        "finished_at": manifest.get("finished_at"),
        "dominant_failure_mode": dominant,
        "failure_modes": failure_modes,
        "comparison_scope": "local_pilot_partial",
        "artifact_path": str(run_dir.relative_to(REPO_ROOT).as_posix()),
    }


def load_pilot(run_id: str) -> dict | None:
    run_dir = _resolve_run_dir(run_id)
    return summarize_run(run_dir) if run_dir else None


def load_all_runs() -> list[dict]:
    """Compact summary of every run on disk, newest first."""
    if not RUNS_DIR.exists():
        return []
    rows: list[dict] = []
    for run_dir in sorted(RUNS_DIR.iterdir()):
        if not run_dir.is_dir():
            continue
        try:
            full = summarize_run(run_dir)
        except Exception as exc:  # noqa: BLE001 - keep export resilient
            print(f"WARNING: skipped {run_dir.name}: {exc}", file=sys.stderr)
            continue
        if not full:
            continue
        rows.append({
            k: full[k]
            for k in (
                "run_id", "experiment_id", "status", "model_name", "solver_name",
                "provider", "prompt_version", "pack_id", "benchmark_name",
                "n_tasks", "n_task_count", "n_attempts", "solved_rate",
                "task_solved_rate", "exact_match_rate", "parse_error_rate",
                "parse_error_count", "execution_error_rate", "execution_error_count",
                "avg_latency_ms", "dominant_failure_mode",
                "started_at", "finished_at", "artifact_path",
            )
        })
    rows.sort(key=lambda r: (r.get("started_at") or r.get("run_id") or ""), reverse=True)
    return rows


def load_public_context() -> dict:
    if not PUBLIC_DIR.exists():
        return {"available": False, "rows": [], "by_trust": [], "message": "No public_results Parquet yet. Run public_results_cli.py compare."}
    df = pd.read_parquet(PUBLIC_DIR)
    # Exclude sentinel preview zeros from chart-like lists
    view = df[~((df["score"] == 0) & (df["trust_tier"] == "preview"))].copy()
    by_trust = (
        view[view["trust_tier"] != "local_pilot"]
        .groupby("trust_tier", dropna=False)
        .agg(n=("result_id", "count"), mean_score=("score", "mean"), max_score=("score", "max"))
        .reset_index()
        .sort_values("n", ascending=False)
    )
    rows = []
    for r in view.sort_values(["benchmark_name", "score"], ascending=[True, False]).itertuples(index=False):
        rows.append({
            "submission_name": r.submission_name,
            "benchmark_name": r.benchmark_name,
            "score": float(r.score) if pd.notna(r.score) else None,
            "score_percent": float(r.score_percent) if pd.notna(r.score_percent) else None,
            "trust_tier": r.trust_tier,
            "verification_status": r.verification_status,
            "split_type": r.split_type,
            "comparison_scope": r.comparison_scope,
            "cost_per_task_usd": float(r.cost_per_task_usd) if pd.notna(r.cost_per_task_usd) else None,
            "source_name": r.source_name,
            "local_run_id": r.local_run_id if pd.notna(r.local_run_id) else None,
            "team_authors": r.team_authors if pd.notna(r.team_authors) else None,
        })
    return {
        "available": True,
        "n_rows": len(rows),
        "by_trust": [
            {
                "trust_tier": str(r.trust_tier),
                "n": int(r.n),
                "mean_score": float(r.mean_score) if pd.notna(r.mean_score) else None,
                "max_score": float(r.max_score) if pd.notna(r.max_score) else None,
            }
            for r in by_trust.itertuples(index=False)
        ],
        "rows": rows,
    }


def artifact_catalog(pilot: dict | None) -> list[dict]:
    items = [
        {"label": "Primary pilot — GLM-5.2 · ARC-AGI-2 (n=120)", "path": "reports/pilot_glm52_agi2_n120.md", "kind": "report"},
        {"label": "Evidence index", "path": "reports/README.md", "kind": "report"},
        {"label": "Model comparison table", "path": "reports/tables/model_comparison.md", "kind": "report"},
        {"label": "Public results comparison", "path": "reports/public_results_comparison.md", "kind": "report"},
        {"label": "Public score context chart", "path": "artifacts/public_results/score_context.png", "kind": "chart"},
        {"label": "Public results Parquet", "path": "data/parquet/public_results/leaderboard_rows", "kind": "parquet"},
        {"label": "Evaluate your solver — step by step", "path": "docs/EVALUATE_YOUR_SOLVER.md", "kind": "docs"},
        {"label": "Observatory docs", "path": "docs/PUBLIC_RESULTS_OBSERVATORY.md", "kind": "docs"},
        {"label": "External solver quickstart", "path": "docs/QUICKSTART_EXTERNAL_SOLVER.md", "kind": "docs"},
        {"label": "Solver adapters", "path": "docs/SOLVER_ADAPTERS.md", "kind": "docs"},
        {"label": "Platform README", "path": "README.md", "kind": "docs"},
    ]
    if pilot and pilot.get("artifact_path"):
        items.insert(0, {
            "label": "Local pilot run directory",
            "path": pilot["artifact_path"],
            "kind": "parquet",
        })
    # Mark existence
    for item in items:
        p = REPO_ROOT / item["path"]
        item["exists"] = p.exists()
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()

    if not RUNS_DIR.exists():
        print(f"WARNING: runs dir missing ({RUNS_DIR})", file=sys.stderr)

    pilot = load_pilot(args.run_id)
    runs = load_all_runs()
    if pilot is None and runs:
        # Fall back to the newest run so the dashboard is never empty.
        pilot = summarize_run(_resolve_run_dir(runs[0]["run_id"]))
    public = load_public_context()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "name": "ARC Solver Evaluation Platform",
            "brand": "ATLAS",
            "tagline": "Reproducible evaluation infrastructure for heterogeneous ARC-AGI solvers",
            "mission": (
                "Evaluate complete solving systems under one protocol — "
                "not a single-model benchmark, and not an ARC solver itself."
            ),
            "what_it_is_not": [
                "Not an ARC solver",
                "Not a leaderboard optimization toolkit",
                "Not a claim that local pilots equal full public benchmarks",
            ],
        },
        "pilot": pilot,
        "runs": runs,
        "public_context": public,
        "artifacts": artifact_catalog(pilot),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out.relative_to(REPO_ROOT)} "
          f"(pilot={'yes' if pilot else 'missing'}, "
          f"runs={len(runs)}, "
          f"public_rows={public.get('n_rows', 0)})")


if __name__ == "__main__":
    main()

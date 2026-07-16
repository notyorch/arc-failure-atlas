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
DEFAULT_RUN_ID = "20260716T032633Z_kimi-k2.6_b997534f"
RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"
PUBLIC_DIR = REPO_ROOT / "data" / "parquet" / "public_results" / "leaderboard_rows"
OUT_PATH = REPO_ROOT / "frontend" / "public" / "data" / "overview.json"


def load_pilot(run_id: str) -> dict | None:
    run_dir = RUNS_DIR / run_id
    if not run_dir.exists():
        matches = [p for p in RUNS_DIR.iterdir() if p.is_dir() and run_id in p.name] if RUNS_DIR.exists() else []
        if len(matches) == 1:
            run_dir = matches[0]
        else:
            return None
    manifest_path = run_dir / "_manifest.json"
    parts = list(run_dir.glob("part-*.parquet"))
    if not parts or not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)
    item_key = ["task_id", "test_example_id"]
    n_items = int(df.groupby(item_key, sort=False).ngroups)
    solved = int(
        df.assign(_exact=df["is_exact_match"].eq(True).fillna(False))
        .groupby(item_key, sort=False)["_exact"].any().sum()
    )
    failure_counts = (
        df["failure_mode"].fillna("not_classifiable").value_counts().to_dict()
    )
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
        "n_attempts": int(len(df)),
        "solved_rate": (solved / n_items) if n_items else None,
        "exact_match_rate": float(df["is_exact_match"].eq(True).fillna(False).mean()),
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
        {"label": "Pilot evaluation report", "path": "reports/pilot_nim_deepseek_v4_pro.md", "kind": "report"},
        {"label": "Public results comparison", "path": "reports/public_results_comparison.md", "kind": "report"},
        {"label": "Public score context chart", "path": "artifacts/public_results/score_context.png", "kind": "chart"},
        {"label": "Public results Parquet", "path": "data/parquet/public_results/leaderboard_rows", "kind": "parquet"},
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
    public = load_public_context()
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "name": "ARC Solver Evaluation Platform",
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
        "public_context": public,
        "artifacts": artifact_catalog(pilot),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.out.relative_to(REPO_ROOT)} "
          f"(pilot={'yes' if pilot else 'missing'}, "
          f"public_rows={public.get('n_rows', 0)})")


if __name__ == "__main__":
    main()

"""
Read a completed local evaluation run and project it into a public-results
row for side-by-side context (never claimed as full-benchmark comparable).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pandas as pd

from public_results.ingestion import PublicResultsError, normalize_row, utc_now_iso

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"


def load_run_manifest(run_dir: Path) -> dict:
    path = run_dir / "_manifest.json"
    if not path.exists():
        raise PublicResultsError(f"Run manifest not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicResultsError(f"Could not read manifest {path}: {exc}") from exc


def resolve_run_dir(run_id: str, runs_dir: Path = DEFAULT_RUNS_DIR) -> Path:
    direct = runs_dir / run_id
    if direct.exists():
        return direct
    matches = [p for p in runs_dir.iterdir()
               if p.is_dir() and run_id in p.name] if runs_dir.exists() else []
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise PublicResultsError(
            f"No local run matching {run_id!r} under {runs_dir}."
        )
    raise PublicResultsError(
        f"Ambiguous run_id {run_id!r}; matches: {[p.name for p in matches]}"
    )


def local_run_to_public_row(run_id: str,
                            runs_dir: Path = DEFAULT_RUNS_DIR,
                            *,
                            benchmark_name: str = "ARC-AGI-1",
                            ingested_at: Optional[str] = None) -> dict:
    """
    Build one observatory row from a local evaluation run.

    Score = task_solved_rate (Decision 21): a task counts only when EVERY
    test example is solved under pass@k. comparison_scope is always
    local_pilot_partial — do not treat as full leaderboard score.
    """
    run_dir = resolve_run_dir(run_id, runs_dir)
    manifest = load_run_manifest(run_dir)
    parts = list(run_dir.glob("part-*.parquet"))
    if not parts:
        raise PublicResultsError(f"No Parquet parts in {run_dir}")
    df = pd.concat([pd.read_parquet(p) for p in parts], ignore_index=True)

    item_key = ["task_id", "test_example_id"]
    item_solved = (
        df.assign(_exact=df["is_exact_match"].eq(True).fillna(False))
        .groupby(item_key, sort=False)["_exact"].any()
        .reset_index(name="_item_solved")
    )
    n_items = len(item_solved)
    item_solved_rate = (
        float(item_solved["_item_solved"].mean()) if n_items else 0.0
    )
    task_level = (
        item_solved.groupby("task_id", sort=False)["_item_solved"]
        .all()
        .reset_index(name="_task_solved")
    )
    n_tasks = len(task_level)
    task_solved_rate = (
        float(task_level["_task_solved"].mean()) if n_tasks else 0.0
    )
    # Observatory score uses ARC-official task granularity (Decision 21).
    score = task_solved_rate
    avg_latency = float(df["latency_ms"].mean()) if len(df) else None
    total_cost = float(df["cost_estimate_usd"].sum()) if len(df) else None
    cost_per = (total_cost / n_tasks) if (total_cost is not None and n_tasks) else None

    solver = manifest.get("solver") or {}
    submission = solver.get("solver_name") or manifest.get("run_id")
    model = solver.get("model_name")
    family = solver.get("solver_family") or solver.get("model_family")
    date_observed = (manifest.get("finished_at") or manifest.get("started_at")
                     or "")[:10]
    if not date_observed:
        date_observed = utc_now_iso()[:10]

    latency_txt = f"{avg_latency:.1f}" if avg_latency is not None else "n/a"
    notes = (
        f"Local platform pilot/eval run. "
        f"n_tasks={n_tasks}, task_solved_rate={task_solved_rate:.3f}, "
        f"n_items={n_items}, item_solved_rate={item_solved_rate:.3f}, "
        f"exact_attempt_rate="
        f"{float(df['is_exact_match'].eq(True).fillna(False).mean()):.3f}, "
        f"avg_latency_ms={latency_txt}. "
        "Score field = task_solved_rate (Decision 21). "
        "NOT a full-benchmark leaderboard score — comparison_scope="
        "local_pilot_partial."
    )
    raw = {
        "source_name": "local_platform_run",
        "source_url": f"file://{run_dir.as_posix()}",
        "benchmark_name": benchmark_name,
        "submission_name": submission,
        "team_authors": "arc-failure-atlas local pilot",
        "model_family": family or model,
        "score": score,
        "rank": None,
        "cost_per_task_usd": cost_per,
        "total_cost_usd": total_cost,
        "date_observed": date_observed,
        "verification_status": "local_platform",
        "trust_tier": "local_pilot",
        "split_type": "partial",
        "comparison_scope": "local_pilot_partial",
        "n_tasks": int(n_tasks),
        "notes": notes,
        "local_run_id": manifest.get("run_id") or run_dir.name,
    }
    return normalize_row(
        raw,
        provenance_kind="local_run",
        ingested_at=ingested_at or utc_now_iso(),
        label=f"local_run:{run_dir.name}",
    )

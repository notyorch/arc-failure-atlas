"""
Pre-submit discipline — sealed holdout splits, variance, and the
go/no-go certificate.

Why this exists: iterating against the FULL public evaluation set slowly
overfits your system to it, so the public-eval score overestimates what the
semi-private Kaggle set will give you. The antidote is the same one the
competition uses: hide part of the data from yourself.

    create-holdout   split the mounted pack into dev / holdout task ids,
                     deterministically (seed) and SEALED (sha256 over the
                     id lists). Iterate on dev only.
    certify          score a submission on dev, check Kaggle-grader rules,
                     runtime budget, offline viability, and variance — and
                     emit a one-page go/no-go certificate. The holdout is
                     scored ONLY under --reveal-holdout, once; the reveal
                     timestamp is stamped into the seal file.

The seal is tamper-*evident*, not tamper-proof: anyone can edit a local
JSON file. Its job is to make peeking a deliberate, visible act instead of
an accident.
"""

from __future__ import annotations

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

from manifest import git_commit_sha

HOLDOUT_MANIFEST_KIND = "holdout_split"


class HoldoutError(ValueError):
    """Holdout split file missing/invalid/violated. Message is actionable."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Holdout split: create, load, verify, reveal
# ---------------------------------------------------------------------------

def compute_seal(seed: int, dev_ids: list, holdout_ids: list) -> str:
    payload = json.dumps(
        {"seed": seed, "dev": sorted(dev_ids), "holdout": sorted(holdout_ids)},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def create_holdout_split(task_ids: list, holdout_fraction: float, seed: int,
                         benchmark_meta: dict | None = None) -> dict:
    """
    Deterministic dev/holdout partition of a task-id universe. Same ids +
    same seed + same fraction → identical split on any machine.
    """
    ids = sorted({str(t) for t in task_ids})
    if len(ids) < 2:
        raise HoldoutError(
            f"need at least 2 tasks to split, got {len(ids)}"
        )
    if not 0.0 < holdout_fraction < 1.0:
        raise HoldoutError(
            f"--holdout-fraction must be in (0, 1), got {holdout_fraction}"
        )
    n_holdout = max(1, round(len(ids) * holdout_fraction))
    if n_holdout >= len(ids):
        n_holdout = len(ids) - 1

    shuffled = list(ids)
    random.Random(seed).shuffle(shuffled)
    holdout_ids = sorted(shuffled[:n_holdout])
    dev_ids = sorted(shuffled[n_holdout:])

    return {
        "manifest_kind": HOLDOUT_MANIFEST_KIND,
        "benchmark": dict(benchmark_meta or {}),
        "seed": seed,
        "holdout_fraction": holdout_fraction,
        "n_tasks": len(ids),
        "n_dev": len(dev_ids),
        "n_holdout": len(holdout_ids),
        "dev_task_ids": dev_ids,
        "holdout_task_ids": holdout_ids,
        "seal_sha256": compute_seal(seed, dev_ids, holdout_ids),
        "created_at": utc_now_iso(),
        "git_commit": git_commit_sha(),
        "revealed_at": None,
    }


def write_holdout_split(split: dict, path: Path, force: bool = False) -> Path:
    path = Path(path)
    if path.exists() and not force:
        raise HoldoutError(
            f"{path} already exists. A holdout split should be created ONCE "
            "and kept — recreating it after seeing scores defeats the "
            "purpose. Pass --force only if you know what you are doing."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(split, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return path


def load_holdout_split(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise HoldoutError(f"holdout split file not found: {path}")
    try:
        split = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HoldoutError(f"invalid JSON in {path}: {exc.msg}") from exc
    if split.get("manifest_kind") != HOLDOUT_MANIFEST_KIND:
        raise HoldoutError(
            f"{path} is not a holdout_split file "
            f"(manifest_kind={split.get('manifest_kind')!r})"
        )
    for key in ("seed", "dev_task_ids", "holdout_task_ids", "seal_sha256"):
        if key not in split:
            raise HoldoutError(f"{path} is missing '{key}'")
    return split


def seal_is_intact(split: dict) -> bool:
    expected = compute_seal(
        split["seed"], split["dev_task_ids"], split["holdout_task_ids"])
    return expected == split["seal_sha256"]


def mark_revealed(split: dict, path: Path) -> dict:
    """One-shot: stamp the reveal into the seal file. Refuses a second one."""
    if split.get("revealed_at"):
        raise HoldoutError(
            f"holdout was already revealed at {split['revealed_at']} — "
            "a second look is no longer an unbiased estimate. If you truly "
            "need a fresh holdout, create a new split with a NEW seed and "
            "stop iterating against the old one."
        )
    split["revealed_at"] = utc_now_iso()
    split["revealed_git_commit"] = git_commit_sha()
    Path(path).write_text(
        json.dumps(split, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return split


# ---------------------------------------------------------------------------
# Scoring for the certificate (same judge components, in memory)
# ---------------------------------------------------------------------------

def score_rows_for_items(canonical, solver_name: str, items: list):
    """
    Judge a canonical submission over evaluation items using the SAME
    per-item pipeline as run_evaluation (solve → parse → score → classify),
    aggregated in memory: a certificate is a judgment snapshot, not a
    persisted run.
    """
    import pandas as pd

    from run_evaluation import evaluate_item
    from solvers import CanonicalSubmissionSolver

    solver = CanonicalSubmissionSolver(
        name=solver_name, canonical=canonical, refuse_on_errors=False,
    )
    rows: list = []
    for item in items:
        item_rows, _ = evaluate_item(solver, item)
        rows.extend(item_rows)
    return pd.DataFrame(rows)


def metrics_from_rows(rows_df) -> dict:
    """solved/task/kaggle rates + failure mix from scored attempt rows."""
    from kaggle_protocol import kaggle_score_from_rows

    if rows_df is None or len(rows_df) == 0:
        return {"n_items": 0, "n_tasks": 0, "solved_items": 0,
                "solved_tasks": 0, "kaggle_score": None,
                "failure_modes": {}}
    item_key = ["task_id", "test_example_id"]
    per_item = (
        rows_df.assign(_exact=rows_df["is_exact_match"].eq(True).fillna(False))
        .groupby(item_key, sort=False)["_exact"].any()
    )
    solved_tasks = int(per_item.groupby("task_id").all().sum())
    failure_modes = (
        rows_df["failure_mode"].fillna("(not classifiable)")
        .value_counts().to_dict()
    )
    kaggle = kaggle_score_from_rows(rows_df)
    return {
        "n_items": int(per_item.size),
        "n_tasks": int(rows_df["task_id"].nunique()),
        "solved_items": int(per_item.sum()),
        "solved_tasks": solved_tasks,
        "kaggle_score": kaggle["kaggle_score"],
        "failure_modes": {str(k): int(v) for k, v in failure_modes.items()},
    }


def variance_across_runs(runs_root: Path, solver_name: str,
                         pack_id: str | None, max_runs: int = 8) -> dict:
    """
    kaggle_score across completed persisted runs of the same solver (and
    pack, when stamped). ≥2 runs → mean ± population std; the certificate
    treats fewer as 'unknown', which is itself a warning.
    """
    import pandas as pd

    runs_root = Path(runs_root)
    if not runs_root.is_dir():
        return {"n_runs": 0, "scores": [], "mean": None, "std": None}

    from kaggle_protocol import kaggle_score_from_rows

    scored: list = []
    run_dirs = sorted(runs_root.iterdir(), reverse=True)
    for run_dir in run_dirs:
        if len(scored) >= max_runs:
            break
        manifest_path = run_dir / "_manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("status") != "completed":
            continue
        if manifest.get("solver", {}).get("solver_name") != solver_name:
            continue
        run_pack = manifest.get("benchmark", {}).get("pack_id")
        if pack_id and run_pack and run_pack != pack_id:
            continue
        try:
            rows = pd.read_parquet(run_dir, engine="pyarrow")
        except Exception:  # unreadable run — variance is best-effort
            continue
        score = kaggle_score_from_rows(rows)["kaggle_score"]
        if score is not None:
            scored.append({"run_id": manifest.get("run_id", run_dir.name),
                           "kaggle_score": score})

    scores = [s["kaggle_score"] for s in scored]
    result = {"n_runs": len(scored), "scores": scored,
              "mean": None, "std": None}
    if len(scores) >= 2:
        mean = sum(scores) / len(scores)
        variance = sum((s - mean) ** 2 for s in scores) / len(scores)
        result["mean"] = mean
        result["std"] = variance ** 0.5
    return result


# ---------------------------------------------------------------------------
# Certificate rendering
# ---------------------------------------------------------------------------

VERDICT_GO = "GO"
VERDICT_WARN = "GO WITH WARNINGS"
VERDICT_NO_GO = "NO-GO"

_STATUS_ICON = {"pass": "✅", "warn": "⚠️", "fail": "❌", "n/a": "—"}


def verdict_from_checks(checks: list) -> str:
    statuses = {c["status"] for c in checks}
    if "fail" in statuses:
        return VERDICT_NO_GO
    if "warn" in statuses:
        return VERDICT_WARN
    return VERDICT_GO


def _fmt_rate(numerator, denominator) -> str:
    if not denominator:
        return "n/a"
    return f"{numerator} / {denominator} ({numerator / denominator:.1%})"


def _fmt_score(score) -> str:
    return "n/a" if score is None else f"{score:.4f}"


def render_certificate(ctx: dict) -> str:
    """One page, verdict first. `ctx` is assembled by presubmit_cli.certify."""
    checks = ctx["checks"]
    verdict = ctx["verdict"]
    lines = [
        f"# Pre-submit certificate — {ctx['solver_name']}",
        "",
        f"**Verdict: {verdict}**",
        "",
        f"- Benchmark: {ctx['benchmark'].get('benchmark_name', 'unknown')} "
        f"(pack `{ctx['benchmark'].get('pack_id', 'unknown')}`, "
        f"{ctx['n_expected_tasks']} task(s) / "
        f"{ctx['n_expected_items']} test output(s))",
        f"- Submission: `{ctx['submission_path']}`",
        f"- Generated: {ctx['created_at']} · git `{ctx['git_commit'][:12]}` "
        "· judge: ATLAS local (`local_pilot_partial`)",
        "",
        "## Checklist",
        "",
        "| Check | Status | Detail |",
        "| --- | --- | --- |",
    ]
    for check in checks:
        icon = _STATUS_ICON.get(check["status"], check["status"])
        lines.append(
            f"| {check['name']} | {icon} {check['status']} "
            f"| {check['detail']} |"
        )

    dev = ctx["dev_metrics"]
    holdout = ctx.get("holdout_metrics")
    dev_label = ctx["dev_label"]
    lines += [
        "",
        "## Scores",
        "",
        f"| Metric | {dev_label} | Holdout |",
        "| --- | --- | --- |",
        f"| `kaggle_score` (leaderboard metric) | {_fmt_score(dev['kaggle_score'])} "
        f"| {ctx['holdout_score_cell']} |",
        f"| `task_solved_rate` (all-or-nothing) "
        f"| {_fmt_rate(dev['solved_tasks'], dev['n_tasks'])} "
        f"| {_fmt_rate(holdout['solved_tasks'], holdout['n_tasks']) if holdout else '—'} |",
        f"| `solved_rate` (test outputs) "
        f"| {_fmt_rate(dev['solved_items'], dev['n_items'])} "
        f"| {_fmt_rate(holdout['solved_items'], holdout['n_items']) if holdout else '—'} |",
    ]

    if dev["failure_modes"]:
        lines += ["", f"## Failure taxonomy — {dev_label}", "",
                  "| Mode | Attempt rows |", "| --- | ---: |"]
        for mode, count in sorted(dev["failure_modes"].items(),
                                  key=lambda kv: -kv[1]):
            lines.append(f"| `{mode}` | {count} |")

    batch = ctx.get("batch")
    lines += ["", "## Runtime & environment", ""]
    if batch:
        execution = batch.get("execution", {})
        gpu = execution.get("gpu") or {}
        gpu_txt = (
            f"max {gpu.get('max_memory_mb', 0):.0f} MB VRAM, "
            f"max {gpu.get('max_utilization_pct', 0):.0f}% util"
            if gpu.get("available") else "no GPU telemetry"
        )
        lines += [
            f"- Wall time: **{execution.get('wall_hours', '?')} h** of "
            f"{execution.get('budget_hours', '?')} h budget "
            f"(utilization {execution.get('budget_utilization', '?')})",
            f"- Exit code: {execution.get('exit_code')} · offline: "
            f"{execution.get('offline')} · {gpu_txt}",
            f"- Batch manifest: `{ctx['batch_manifest_path']}`",
        ]
    else:
        lines.append(
            "- No batch manifest provided — runtime, budget, and offline "
            "viability were **not** verified by the judge. Run your "
            "pipeline through `src/batch_runner.py` to certify them."
        )

    var = ctx["variance"]
    lines += ["", "## Variance across persisted runs", ""]
    if var["n_runs"] >= 2:
        lines.append(
            f"- {var['n_runs']} completed run(s) of this solver: "
            f"kaggle_score {var['mean']:.4f} ± {var['std']:.4f}"
        )
    else:
        lines.append(
            f"- Only {var['n_runs']} completed persisted run(s) found — "
            "variance unknown. Stochastic pipelines should be run at least "
            "twice before trusting a single score."
        )

    lines += [
        "",
        "---",
        "",
        "*Local scores are `local_pilot_partial` context, **not** leaderboard "
        "results. Public-eval numbers typically **overestimate** the "
        "semi-private set — that is exactly what the sealed holdout is for.*",
        "",
    ]
    return "\n".join(lines)

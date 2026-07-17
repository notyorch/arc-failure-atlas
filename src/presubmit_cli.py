"""
CLI for the pre-submit standard — sealed holdout + go/no-go certificate.

    create-holdout   split the mounted pack into dev/holdout ONCE (sealed)
    certify          one-page go/no-go before spending a Kaggle submit

Examples (repository root):

    python src/presubmit_cli.py create-holdout --seed 42 \\
        --holdout-fraction 0.3

    python src/presubmit_cli.py certify \\
        --submission artifacts/batch/my-pipeline/submission.json \\
        --holdout configs/holdout_arc_agi_2.json \\
        --batch-manifest artifacts/batch/my-pipeline/batch_manifest.json

    # the day you decide to submit (one-shot):
    python src/presubmit_cli.py certify --submission ... \\
        --holdout configs/holdout_arc_agi_2.json --reveal-holdout

The certificate is Markdown → reports/presubmit_certificate_<solver>.md.
Verdict semantics: NO-GO = the Kaggle grader (or notebook runtime) would
reject or truncate this exact artifact; WARNINGS = accepted, but part of
the pre-submit standard was not verified (offline, holdout, variance).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports"
DEFAULT_RUNS_DIR = REPO_ROOT / "data" / "parquet" / "inference" / "runs"
DEFAULT_CONFIGS_DIR = REPO_ROOT / "configs"

from manifest import git_commit_sha  # noqa: E402
from presubmit import (  # noqa: E402
    HoldoutError,
    create_holdout_split,
    load_holdout_split,
    mark_revealed,
    metrics_from_rows,
    render_certificate,
    score_rows_for_items,
    seal_is_intact,
    utc_now_iso,
    variance_across_runs,
    verdict_from_checks,
    write_holdout_split,
)


def _load_task_universe(
    input_path: Path | None,
    pack_id: str | None = None,
    task_ids: list[str] | None = None,
):
    """(tasks_df, benchmark_meta, items, expected_counts) from the corpus.

    Optional ``pack_id`` / ``task_ids`` scope the Kaggle-strict universe so a
    partial batch demo is not judged against a mixed local Parquet.
    """
    from benchmark_packs import (
        BenchmarkPackError,
        metadata_for_evaluation_items,
        require_tasks_dir,
        resolve_pack,
    )
    from kaggle_protocol import test_counts_from_tasks_df
    from task_loader import (
        DEFAULT_TASKS_PARQUET,
        build_evaluation_items,
        load_tasks_dataframe,
        reconstruct_tasks,
    )
    path = input_path or DEFAULT_TASKS_PARQUET
    tasks_df = load_tasks_dataframe(path)

    pack_override = None
    wanted: set[str] | None = None
    if pack_id:
        try:
            pack_override = resolve_pack(pack_id=pack_id)
            wanted = {
                p.stem for p in require_tasks_dir(pack_override).glob("*.json")
            }
        except BenchmarkPackError as exc:
            raise ValueError(str(exc)) from exc
    if task_ids is not None:
        scoped = {str(t) for t in task_ids}
        wanted = scoped if wanted is None else (wanted & scoped)

    if wanted is not None:
        tasks_df = tasks_df[tasks_df["task_id"].astype(str).isin(wanted)]
        if tasks_df.empty:
            raise ValueError(
                "no tasks match the requested pack/task filter in "
                f"{path}"
            )

    benchmark_meta = metadata_for_evaluation_items(
        tasks_df, path, pack_override)
    items = build_evaluation_items(
        reconstruct_tasks(tasks_df), benchmark_meta=benchmark_meta)
    return tasks_df, benchmark_meta, items, test_counts_from_tasks_df(tasks_df)


# ---------------------------------------------------------------------------
# create-holdout
# ---------------------------------------------------------------------------

def cmd_create_holdout(args: argparse.Namespace) -> int:
    try:
        tasks_df, benchmark_meta, _, _ = _load_task_universe(
            args.input_path, pack_id=args.benchmark_pack)
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    task_ids = sorted(tasks_df["task_id"].astype(str).unique())
    try:
        split = create_holdout_split(
            task_ids, args.holdout_fraction, args.seed, benchmark_meta)
        out = args.out or (
            DEFAULT_CONFIGS_DIR
            / f"holdout_{benchmark_meta.get('pack_id', 'pack')}.json"
        )
        path = write_holdout_split(split, out, force=args.force)
    except HoldoutError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"holdout split → {path}")
    print(f"  pack     : {benchmark_meta.get('pack_id', 'unknown')}")
    print(f"  dev      : {split['n_dev']} task(s)")
    print(f"  holdout  : {split['n_holdout']} task(s)  (sealed — iterate on "
          "dev only)")
    print(f"  seed     : {split['seed']}  ·  seal sha256 "
          f"{split['seal_sha256'][:16]}…")
    print("\nIterate with certify (scores dev only); reveal the holdout "
          "ONCE, the day you submit:\n"
          f"  python src/presubmit_cli.py certify --submission <sub.json> "
          f"--holdout {path} [--reveal-holdout]")
    return 0


# ---------------------------------------------------------------------------
# certify
# ---------------------------------------------------------------------------

def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def cmd_certify(args: argparse.Namespace) -> int:
    from kaggle_protocol import (
        coverage_summary,
        kaggle_strict_issues,
    )
    from submission_io import SubmissionFormatError, load_submission_artifact

    # 1. Artifact parses at all?
    try:
        canonical = load_submission_artifact(args.submission)
    except SubmissionFormatError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    solver_name = args.solver_name or Path(args.submission).stem

    # 2. Task universe (the same corpus the judge scores against).
    # Prefer explicit --benchmark-pack; else scope to batch_manifest.task_ids
    # when the submission was produced by atlas-batch.
    staged_ids = None
    if args.batch_manifest:
        try:
            preview = json.loads(
                Path(args.batch_manifest).read_text(encoding="utf-8"))
            raw_ids = preview.get("task_ids")
            if isinstance(raw_ids, list) and raw_ids:
                staged_ids = [str(t) for t in raw_ids]
        except (OSError, json.JSONDecodeError):
            staged_ids = None

    try:
        _, benchmark_meta, items, expected_counts = _load_task_universe(
            args.input_path,
            pack_id=args.benchmark_pack,
            task_ids=staged_ids if args.benchmark_pack is None else None,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    checks: list = []
    n_format_errors = len(canonical.errors)
    checks.append(_check(
        "Artifact parses (valid JSON, rectangular grids, colors 0–9)",
        "fail" if n_format_errors else "pass",
        (f"{n_format_errors} validation error(s) — run validate-submission "
         "for details") if n_format_errors else canonical.source_format,
    ))

    strict_issues = kaggle_strict_issues(canonical, expected_counts)
    strict_errors = [i for i in strict_issues if i.severity == "error"]
    strict_warnings = [i for i in strict_issues if i.severity == "warning"]
    cov = coverage_summary(canonical, expected_counts)
    coverage_txt = (
        f"{cov['n_covered_tasks']}/{cov['n_expected_tasks']} tasks, "
        f"{cov['n_covered_items']}/{cov['n_expected_items']} test outputs"
    )
    if strict_errors:
        detail = (f"{len(strict_errors)} error(s) — first: "
                  f"{strict_errors[0].message}")
        status = "fail"
    elif strict_warnings:
        detail = (f"{coverage_txt}; {len(strict_warnings)} warning(s) — "
                  f"first: {strict_warnings[0].message}")
        status = "warn"
    else:
        detail = coverage_txt
        status = "pass"
    checks.append(_check(
        "Kaggle grader accepts (every task, every test, attempt_1+2)",
        status, detail,
    ))

    # 3. Holdout discipline.
    split = None
    dev_items = items
    dev_label = "Public eval (full — no holdout)"
    holdout_items: list = []
    if args.holdout:
        try:
            split = load_holdout_split(args.holdout)
        except HoldoutError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if not seal_is_intact(split):
            checks.append(_check(
                "Holdout discipline (sealed dev/holdout split)", "fail",
                f"seal sha256 mismatch in {args.holdout} — the split was "
                "edited after creation; recreate it with a new seed",
            ))
            split = None
        else:
            dev_ids = set(split["dev_task_ids"])
            holdout_ids = set(split["holdout_task_ids"])
            dev_items = [i for i in items if i["task_id"] in dev_ids]
            holdout_items = [i for i in items if i["task_id"] in holdout_ids]
            dev_label = f"Dev ({split['n_dev']} tasks)"
            revealed = split.get("revealed_at")
            checks.append(_check(
                "Holdout discipline (sealed dev/holdout split)", "pass",
                f"{split['n_holdout']} task(s) sealed (seed "
                f"{split['seed']})"
                + (f"; revealed at {revealed}" if revealed else ""),
            ))
    else:
        checks.append(_check(
            "Holdout discipline (sealed dev/holdout split)", "warn",
            "no split — you are iterating against the full public eval, "
            "which overestimates the semi-private score. "
            "Run create-holdout.",
        ))

    # 4. Score dev (the certificate's own in-memory judge pass).
    rows_dev = score_rows_for_items(canonical, solver_name, dev_items)
    dev_metrics = metrics_from_rows(rows_dev)

    holdout_metrics = None
    holdout_score_cell = "—"
    if split is not None:
        if args.reveal_holdout:
            try:
                split = mark_revealed(split, args.holdout)
            except HoldoutError as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 1
            rows_holdout = score_rows_for_items(
                canonical, solver_name, holdout_items)
            holdout_metrics = metrics_from_rows(rows_holdout)
            holdout_score_cell = (
                f"**{holdout_metrics['kaggle_score']:.4f}** "
                f"(revealed {split['revealed_at']})"
            )
        elif split.get("revealed_at"):
            holdout_score_cell = (
                f"revealed {split['revealed_at']} (not re-scored — "
                "one-shot)"
            )
        else:
            holdout_score_cell = "sealed — `--reveal-holdout` (one-shot)"

    # 5. Runtime / offline via the batch manifest, when provided.
    batch = None
    if args.batch_manifest:
        try:
            batch = json.loads(
                Path(args.batch_manifest).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"ERROR: cannot read --batch-manifest: {exc}",
                  file=sys.stderr)
            return 2
        execution = batch.get("execution", {})
        if execution.get("skipped"):
            checks.append(_check(
                "Runtime budget (wall time vs Kaggle hours)", "warn",
                "batch run was resumed — timing reflects a previous "
                "execution",
            ))
        else:
            exceeded = bool(execution.get("budget_exceeded"))
            exit_code = execution.get("exit_code")
            if exceeded or (exit_code not in (0, None)):
                checks.append(_check(
                    "Runtime budget (wall time vs Kaggle hours)", "fail",
                    f"exit_code={exit_code}, budget_exceeded={exceeded} "
                    f"({execution.get('wall_hours')}h of "
                    f"{execution.get('budget_hours')}h)",
                ))
            else:
                checks.append(_check(
                    "Runtime budget (wall time vs Kaggle hours)", "pass",
                    f"{execution.get('wall_hours')}h of "
                    f"{execution.get('budget_hours')}h "
                    f"(utilization {execution.get('budget_utilization')})",
                ))
        offline = execution.get("offline")
        checks.append(_check(
            "Offline viability (no hidden network dependency)",
            "pass" if offline else "warn",
            "verified via network-isolated batch run" if offline else
            "NOT verified — rerun batch_runner with --offline; API-based "
            "pipelines are not submittable to Kaggle as-is",
        ))
    else:
        checks.append(_check(
            "Runtime budget (wall time vs Kaggle hours)", "warn",
            "no --batch-manifest — wall time unverified; run your pipeline "
            "through src/batch_runner.py",
        ))
        checks.append(_check(
            "Offline viability (no hidden network dependency)", "warn",
            "no --batch-manifest — offline behavior unverified",
        ))

    # 6. Variance across persisted runs.
    variance = variance_across_runs(
        args.runs_root or DEFAULT_RUNS_DIR, solver_name,
        benchmark_meta.get("pack_id"))
    if variance["n_runs"] >= 2:
        checks.append(_check(
            "Variance (repeated persisted runs)", "pass",
            f"{variance['n_runs']} run(s): kaggle_score "
            f"{variance['mean']:.4f} ± {variance['std']:.4f}",
        ))
    else:
        checks.append(_check(
            "Variance (repeated persisted runs)", "warn",
            f"{variance['n_runs']} completed run(s) of '{solver_name}' "
            "found — run the judge at least twice for stochastic pipelines",
        ))

    verdict = verdict_from_checks(checks)
    ctx = {
        "solver_name": solver_name,
        "submission_path": str(args.submission),
        "benchmark": benchmark_meta,
        "n_expected_tasks": cov["n_expected_tasks"],
        "n_expected_items": cov["n_expected_items"],
        "checks": checks,
        "verdict": verdict,
        "dev_label": dev_label,
        "dev_metrics": dev_metrics,
        "holdout_metrics": holdout_metrics,
        "holdout_score_cell": holdout_score_cell,
        "batch": batch,
        "batch_manifest_path": str(args.batch_manifest or ""),
        "variance": variance,
        "created_at": utc_now_iso(),
        "git_commit": git_commit_sha(),
    }
    markdown = render_certificate(ctx)
    out = args.out or (
        DEFAULT_REPORTS_DIR / f"presubmit_certificate_{solver_name}.md")
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown, encoding="utf-8")

    print(f"\n{'=' * 62}\nPRE-SUBMIT CERTIFICATE — {solver_name}\n{'=' * 62}")
    for check in checks:
        print(f"  [{check['status']:^4}] {check['name']}")
    print(f"\nverdict     : {verdict}")
    print(f"kaggle_score: {dev_metrics['kaggle_score']:.4f} on {dev_label}"
          if dev_metrics["kaggle_score"] is not None
          else "kaggle_score: n/a")
    if holdout_metrics and holdout_metrics["kaggle_score"] is not None:
        print(f"holdout     : {holdout_metrics['kaggle_score']:.4f} "
              "(one-shot reveal — this is your submit estimate)")
    print(f"certificate : {out}")
    return 0 if verdict != "NO-GO" else 1


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="presubmit_cli.py",
        description="Pre-submit standard: sealed holdout + go/no-go "
                    "certificate for complete ARC solver systems.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_split = sub.add_parser(
        "create-holdout",
        help="split the mounted pack into dev/holdout, sealed (one-time)",
    )
    p_split.add_argument("--holdout-fraction", type=float, default=0.3)
    p_split.add_argument("--seed", type=int, default=42)
    p_split.add_argument("--input-path", type=Path, default=None,
                         help="tasks Parquet (default: data/parquet/evaluation)")
    p_split.add_argument("--benchmark-pack", default=None,
                         help="restrict the split to this pack's task ids")
    p_split.add_argument("--out", type=Path, default=None,
                         help="destination (default: "
                              "configs/holdout_<pack_id>.json)")
    p_split.add_argument("--force", action="store_true",
                         help="overwrite an existing split (defeats the "
                              "discipline — avoid)")
    p_split.set_defaults(func=cmd_create_holdout)

    p_cert = sub.add_parser(
        "certify",
        help="emit the one-page go/no-go certificate for a submission",
    )
    p_cert.add_argument("--submission", type=Path, required=True,
                        help="submission.json OR predictions directory")
    p_cert.add_argument("--solver-name", default=None,
                        help="recorded name (default: submission path stem)")
    p_cert.add_argument("--holdout", type=Path, default=None,
                        help="sealed split from create-holdout; scores dev "
                             "only unless --reveal-holdout")
    p_cert.add_argument("--reveal-holdout", action="store_true",
                        help="score the sealed holdout ONCE and stamp the "
                             "reveal into the split file")
    p_cert.add_argument("--batch-manifest", type=Path, default=None,
                        help="batch_manifest.json from src/batch_runner.py "
                             "(enables runtime/offline checks; scopes "
                             "Kaggle-strict to staged task_ids when present)")
    p_cert.add_argument("--benchmark-pack", default=None,
                        help="restrict Kaggle-strict / scoring to this pack")
    p_cert.add_argument("--input-path", type=Path, default=None,
                        help="tasks Parquet (default: data/parquet/evaluation)")
    p_cert.add_argument("--runs-root", type=Path, default=None,
                        help="persisted runs dir for the variance check "
                             "(default: data/parquet/inference/runs)")
    p_cert.add_argument("--out", type=Path, default=None,
                        help="certificate path (default: reports/"
                             "presubmit_certificate_<solver>.md)")
    p_cert.set_defaults(func=cmd_certify)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()

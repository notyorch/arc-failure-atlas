"""
CLI for external solver authors — submission-first workflows.

Humans who already have ARC solver outputs should not need to learn the
full pipeline. This entrypoint exposes four focused commands:

    validate-submission   parse + normalize + validate an artifact
    import-submission     write atlas_canonical_v1 JSON for replay
    score-submission      evaluate against tasks Parquet (alias of evaluate)
    evaluate-submission   same as score-submission

Examples (from the repository root):

    python src/submission_cli.py validate-submission \\
        --path examples/external_solver/submission.json

    python src/submission_cli.py import-submission \\
        --path examples/external_solver/predictions \\
        --out artifacts/imports/example_canonical.json

    python src/submission_cli.py evaluate-submission \\
        --path examples/external_solver/submission.json \\
        --solver-name my-system --experiment-id pre-submit --limit 3

Under the hood, evaluate/score delegates to run_evaluation.py so scoring,
taxonomy, manifests, and analytics stay identical to every other adapter.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from submission_io import (
    SubmissionFormatError,
    cross_check_expected_tasks,
    format_validation_report,
    load_submission_artifact,
    write_canonical_json,
)


def _load_expected_task_ids(tasks_parquet: Path | None) -> set:
    if tasks_parquet is None:
        return set()
    from task_loader import load_tasks_dataframe
    df = load_tasks_dataframe(tasks_parquet)
    return set(df["task_id"].astype(str).unique())


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        submission = load_submission_artifact(args.path)
    except SubmissionFormatError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.against_tasks is not None:
        try:
            expected = _load_expected_task_ids(args.against_tasks)
        except (FileNotFoundError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        missing_as = "error" if args.strict_coverage else "warning"
        submission = cross_check_expected_tasks(
            submission, expected, missing_as=missing_as, extra_as="warning",
        )

    print(format_validation_report(submission))
    if not submission.ok:
        return 1
    if args.fail_on_warning and submission.warnings:
        print("\nTreating warnings as failure (--fail-on-warning).",
              file=sys.stderr)
        return 1
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    try:
        submission = load_submission_artifact(args.path)
    except SubmissionFormatError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(format_validation_report(submission))
    if not submission.ok and not args.allow_errors:
        print(
            "\nRefusing to import: fix validation errors, or pass "
            "--allow-errors to write a partial canonical file.",
            file=sys.stderr,
        )
        return 1

    dest = write_canonical_json(submission, args.out)
    print(f"\nWrote canonical artifact → {dest}")
    return 0 if submission.ok else 1


def cmd_evaluate(args: argparse.Namespace) -> int:
    """Delegate to run_evaluation with --submission-file or --submission-dir."""
    path = Path(args.path)
    if not path.exists():
        print(f"ERROR: path not found: {path}", file=sys.stderr)
        return 2

    # Late import keeps validate/import light when pandas isn't needed yet.
    import run_evaluation

    # Build an argv-compatible Namespace by invoking run_evaluation.main
    # through a reconstructed CLI — keeps a single code path for scoring.
    argv = [sys.argv[0]]
    if path.is_dir():
        argv += ["--submission-dir", str(path)]
    else:
        argv += ["--submission-file", str(path)]

    if args.solver_name:
        argv += ["--solver-name", args.solver_name]
    if args.solver_version:
        argv += ["--solver-version", args.solver_version]
    if args.experiment_id:
        argv += ["--experiment-id", args.experiment_id]
    if args.input_path:
        argv += ["--input-path", str(args.input_path)]
    if args.output_path:
        argv += ["--output-path", str(args.output_path)]
    if args.limit is not None:
        argv += ["--limit", str(args.limit)]
    if args.task_id:
        argv += ["--task-id", args.task_id]
    if args.dry_run:
        argv.append("--dry-run")
    if getattr(args, "benchmark_pack", None):
        argv += ["--benchmark-pack", args.benchmark_pack]
    if getattr(args, "benchmark_pack_path", None):
        argv += ["--benchmark-pack-path", str(args.benchmark_pack_path)]

    old_argv = sys.argv
    try:
        sys.argv = argv
        run_evaluation.main()
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (1 if exc.code else 0)
        return code
    finally:
        sys.argv = old_argv
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="submission_cli.py",
        description="Submission-first tools for external ARC solver authors.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_val = sub.add_parser(
        "validate-submission",
        help="parse, normalize, and validate a submission file or directory",
    )
    p_val.add_argument("--path", type=Path, required=True,
                       help="submission.json OR directory of <task_id>.json")
    p_val.add_argument("--against-tasks", type=Path, default=None,
                       help="optional tasks Parquet dir to check coverage")
    p_val.add_argument("--strict-coverage", action="store_true",
                       help="treat missing expected tasks as errors")
    p_val.add_argument("--fail-on-warning", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_imp = sub.add_parser(
        "import-submission",
        help="normalize an artifact to atlas_canonical_v1 JSON",
    )
    p_imp.add_argument("--path", type=Path, required=True)
    p_imp.add_argument("--out", type=Path, required=True,
                       help="destination .json path")
    p_imp.add_argument("--allow-errors", action="store_true",
                       help="write even when validation reported errors")
    p_imp.set_defaults(func=cmd_import)

    for name in ("score-submission", "evaluate-submission"):
        p_eval = sub.add_parser(
            name,
            help="score a submission artifact against tasks Parquet "
                 "(full evaluation pipeline)",
        )
        p_eval.add_argument("--path", type=Path, required=True,
                            help="submission.json OR predictions directory")
        p_eval.add_argument("--solver-name", default=None,
                            help="recorded solver_name (default: path stem)")
        p_eval.add_argument("--solver-version", default=None)
        p_eval.add_argument("--experiment-id", default=None)
        p_eval.add_argument("--input-path", type=Path, default=None,
                            help="tasks Parquet (default: data/parquet/evaluation)")
        p_eval.add_argument("--output-path", type=Path, default=None)
        p_eval.add_argument("--limit", type=int, default=None)
        p_eval.add_argument("--task-id", default=None,
                            help="comma-separated task ids")
        p_eval.add_argument("--benchmark-pack", default=None,
                            help="optional pack id override for metadata stamp")
        p_eval.add_argument("--benchmark-pack-path", type=Path, default=None,
                            help="optional local pack root for metadata stamp")
        p_eval.add_argument("--dry-run", action="store_true")
        p_eval.set_defaults(func=cmd_evaluate)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    code = args.func(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()

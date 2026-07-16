"""
CLI for the Public Results Observatory.

    python src/public_results_cli.py sync
    python src/public_results_cli.py report
    python src/public_results_cli.py compare --run-id <id>

Does not call model APIs and does not run solvers. Sync reads curated
fixtures (+ optional markdown table snapshots) under fixtures/public_results/.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow `python src/public_results_cli.py` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from public_results.charts import write_score_context_chart
from public_results.ingestion import DEFAULT_FIXTURES_DIR, PublicResultsError, load_all_fixtures
from public_results.local_anchor import DEFAULT_RUNS_DIR, local_run_to_public_row
from public_results.report import render_comparison_report, write_report
from public_results.store import (
    DEFAULT_PUBLIC_DIR,
    load_public_results,
    write_public_results,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = REPO_ROOT / "reports" / "public_results_comparison.md"
DEFAULT_CHART = REPO_ROOT / "artifacts" / "public_results" / "score_context.png"
DEFAULT_PILOT_RUN = "20260716T010504Z_nim-deepseek-v4-pro_76a8317f"


def cmd_sync(args: argparse.Namespace) -> None:
    rows = load_all_fixtures(args.fixtures_dir)
    if args.run_id:
        rows.append(local_run_to_public_row(
            args.run_id, args.runs_dir,
            benchmark_name=args.benchmark_name,
        ))
    path = write_public_results(rows, args.output_dir)
    print(f"PUBLIC RESULTS SYNCED → {path} ({len(rows)} rows)")


def _chart_link(chart_path: Path, report_path: Path) -> str:
    """Prefer a repo-relative path from the report file for markdown images."""
    try:
        return Path(os.path.relpath(chart_path, start=report_path.parent)).as_posix()
    except ValueError:
        return str(chart_path)


def cmd_report(args: argparse.Namespace) -> None:
    df = load_public_results(args.output_dir)
    chart_rel = None
    if not args.skip_chart:
        write_score_context_chart(
            df, args.chart_path, local_run_id=args.run_id,
        )
        chart_rel = _chart_link(args.chart_path, args.report_path)
    text = render_comparison_report(
        df, local_run_id=args.run_id, chart_relpath=chart_rel,
    )
    write_report(text, args.report_path)
    print(f"REPORT → {args.report_path}")
    if not args.skip_chart:
        print(f"CHART  → {args.chart_path}")


def cmd_compare(args: argparse.Namespace) -> None:
    """Sync fixtures + local run, then write report + chart (one-shot)."""
    rows = load_all_fixtures(args.fixtures_dir)
    rows.append(local_run_to_public_row(
        args.run_id, args.runs_dir,
        benchmark_name=args.benchmark_name,
    ))
    write_public_results(rows, args.output_dir)
    df = load_public_results(args.output_dir)
    write_score_context_chart(df, args.chart_path, local_run_id=args.run_id)
    chart_rel = _chart_link(args.chart_path, args.report_path)
    text = render_comparison_report(
        df, local_run_id=args.run_id, chart_relpath=chart_rel,
    )
    write_report(text, args.report_path)
    print(f"COMPARE OK — {len(df)} rows")
    print(f"  parquet : {args.output_dir / 'leaderboard_rows'}")
    print(f"  report  : {args.report_path}")
    print(f"  chart   : {args.chart_path}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Public Results Observatory (ARC / ARC Prize context).",
    )
    sub = p.add_subparsers(dest="command", required=True)

    def add_paths(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--fixtures-dir", type=Path, default=DEFAULT_FIXTURES_DIR)
        sp.add_argument("--output-dir", type=Path, default=DEFAULT_PUBLIC_DIR)
        sp.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
        sp.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
        sp.add_argument("--chart-path", type=Path, default=DEFAULT_CHART)
        sp.add_argument("--benchmark-name", default="ARC-AGI-1",
                        help="benchmark label stamped on the local pilot row")

    sync = sub.add_parser("sync", help="ingest fixtures (+ optional local run) → Parquet")
    add_paths(sync)
    sync.add_argument("--run-id", default=None,
                      help="optional local run_id to include as local_pilot row")
    sync.set_defaults(func=cmd_sync)

    report = sub.add_parser("report", help="render markdown (+ chart) from Parquet")
    add_paths(report)
    report.add_argument("--run-id", default=None,
                        help="highlight this local_run_id in report/chart")
    report.add_argument("--skip-chart", action="store_true")
    report.set_defaults(func=cmd_report)

    compare = sub.add_parser(
        "compare",
        help="sync fixtures + local run, then report + chart (recommended)",
    )
    add_paths(compare)
    compare.add_argument(
        "--run-id", default=DEFAULT_PILOT_RUN,
        help=f"local run anchor (default: {DEFAULT_PILOT_RUN})",
    )
    compare.set_defaults(func=cmd_compare)
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (PublicResultsError, RuntimeError, FileNotFoundError, ValueError) as exc:
        sys.exit(f"ERROR: {exc}")


if __name__ == "__main__":
    main()

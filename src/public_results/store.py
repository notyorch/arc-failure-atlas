"""Persist / load the public-results Parquet dataset."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from contracts import validate_columns
from manifest import git_commit_sha, portable_path, write_manifest
from public_results.ingestion import PublicResultsError
from public_results.schemas import (
    PUBLIC_RESULTS_SCHEMA,
    PUBLIC_RESULTS_SCHEMA_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PUBLIC_DIR = REPO_ROOT / "data" / "parquet" / "public_results"
TABLE_NAME = "leaderboard_rows"


def rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        raise PublicResultsError("Cannot write empty public-results table.")
    df = pd.DataFrame(rows)
    # Stable column order + dtypes friendly to Parquet
    df = df[list(PUBLIC_RESULTS_SCHEMA.keys())]
    for col in ("rank", "n_tasks"):
        df[col] = df[col].astype("Int64")
    for col in ("score", "score_percent", "cost_per_task_usd", "total_cost_usd"):
        df[col] = df[col].astype("Float64")
    for col in df.columns:
        if col not in ("rank", "n_tasks", "score", "score_percent",
                       "cost_per_task_usd", "total_cost_usd"):
            df[col] = df[col].astype("string")
    validate_columns(df, PUBLIC_RESULTS_SCHEMA, label="public_results")
    return df


def write_public_results(rows: list[dict],
                         output_dir: Path = DEFAULT_PUBLIC_DIR,
                         *,
                         source_labels: Optional[list[str]] = None) -> Path:
    """Clean rebuild of leaderboard_rows/ + _manifest.json."""
    table_dir = output_dir / TABLE_NAME
    if output_dir.exists():
        # Only replace our table + manifest; leave sibling dirs alone.
        if table_dir.exists():
            shutil.rmtree(table_dir)
    table_dir.mkdir(parents=True, exist_ok=True)
    df = rows_to_dataframe(rows)
    part = table_dir / "part-0.parquet"
    df.to_parquet(part, engine="pyarrow", index=False)

    write_manifest(output_dir, {
        "manifest_kind": "public_results_sync",
        "status": "completed",
        "public_results_schema_version": PUBLIC_RESULTS_SCHEMA_VERSION,
        "git_commit": git_commit_sha(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "output_path": portable_path(output_dir),
        "n_rows": len(df),
        "sources": source_labels or sorted(df["source_name"].dropna().unique()),
        "benchmarks": sorted(df["benchmark_name"].dropna().unique()),
    })
    return table_dir


def load_public_results(output_dir: Path = DEFAULT_PUBLIC_DIR) -> pd.DataFrame:
    table_dir = output_dir / TABLE_NAME
    if not table_dir.exists():
        raise PublicResultsError(
            f"No public results at {table_dir}. Run:\n"
            "    python src/public_results_cli.py sync"
        )
    df = pd.read_parquet(table_dir, engine="pyarrow")
    validate_columns(df, PUBLIC_RESULTS_SCHEMA, label="public_results")
    return df

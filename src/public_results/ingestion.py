"""
Load curated + parseable public leaderboard fixtures into normalized rows.

Primary path: versioned JSON fixtures under fixtures/public_results/
(deterministic, reviewable, no live scrape required).

Secondary path: simple markdown/HTML tables with an explicit column map
(for when a human saves a public page snapshot).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from public_results.schemas import (
    COMPARISON_SCOPES,
    PUBLIC_RESULTS_SCHEMA,
    SPLIT_TYPES,
    TRUST_TIERS,
    VERIFICATION_STATUSES,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FIXTURES_DIR = REPO_ROOT / "fixtures" / "public_results"


class PublicResultsError(ValueError):
    """Invalid public-results input. Message is safe to print."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require(row: dict, key: str, label: str) -> Any:
    if key not in row or row[key] is None or row[key] == "":
        raise PublicResultsError(f"{label}: missing required field '{key}'")
    return row[key]


def _as_float(value: Any, field: str, label: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PublicResultsError(
            f"{label}: field '{field}' must be numeric, got {value!r}"
        ) from exc


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    return int(value)


def make_result_id(parts: Iterable[str]) -> str:
    blob = "|".join(str(p) for p in parts)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def normalize_row(raw: dict, *, provenance_kind: str,
                  ingested_at: Optional[str] = None,
                  label: str = "row") -> dict:
    """Validate and normalize one public-results record to the frozen schema."""
    source_name = str(_require(raw, "source_name", label))
    source_url = str(_require(raw, "source_url", label))
    benchmark = str(_require(raw, "benchmark_name", label))
    submission = str(_require(raw, "submission_name", label))
    date_observed = str(_require(raw, "date_observed", label))
    verification = str(_require(raw, "verification_status", label))
    trust = str(_require(raw, "trust_tier", label))
    split_type = str(_require(raw, "split_type", label))
    scope = str(_require(raw, "comparison_scope", label))

    if verification not in VERIFICATION_STATUSES:
        raise PublicResultsError(
            f"{label}: unknown verification_status {verification!r}. "
            f"Allowed: {VERIFICATION_STATUSES}"
        )
    if trust not in TRUST_TIERS:
        raise PublicResultsError(
            f"{label}: unknown trust_tier {trust!r}. Allowed: {TRUST_TIERS}"
        )
    if split_type not in SPLIT_TYPES:
        raise PublicResultsError(
            f"{label}: unknown split_type {split_type!r}. Allowed: {SPLIT_TYPES}"
        )
    if scope not in COMPARISON_SCOPES:
        raise PublicResultsError(
            f"{label}: unknown comparison_scope {scope!r}. "
            f"Allowed: {COMPARISON_SCOPES}"
        )

    score = _as_float(_require(raw, "score", label), "score", label)
    if not 0.0 <= score <= 1.0:
        # Allow 0–100 input as a convenience when authors paste percents.
        if 1.0 < score <= 100.0:
            score = score / 100.0
        else:
            raise PublicResultsError(
                f"{label}: score must be in [0,1] (or percent 0–100), got {score}"
            )

    score_percent = raw.get("score_percent")
    if score_percent is None:
        score_percent = round(score * 100.0, 4)
    else:
        score_percent = _as_float(score_percent, "score_percent", label)

    result_id = raw.get("result_id") or make_result_id([
        source_name, benchmark, submission, date_observed,
        f"{score:.6f}", str(raw.get("split_type")), str(raw.get("local_run_id") or ""),
    ])

    out = {
        "result_id": str(result_id),
        "source_name": source_name,
        "source_url": source_url,
        "benchmark_name": benchmark,
        "submission_name": submission,
        "team_authors": raw.get("team_authors"),
        "model_family": raw.get("model_family"),
        "score": float(score),
        "score_percent": float(score_percent),
        "rank": _optional_int(raw.get("rank")),
        "cost_per_task_usd": _optional_float(raw.get("cost_per_task_usd")),
        "total_cost_usd": _optional_float(raw.get("total_cost_usd")),
        "date_observed": date_observed,
        "verification_status": verification,
        "trust_tier": trust,
        "split_type": split_type,
        "comparison_scope": scope,
        "n_tasks": _optional_int(raw.get("n_tasks")),
        "notes": raw.get("notes"),
        "local_run_id": raw.get("local_run_id"),
        "provenance_kind": provenance_kind,
        "ingested_at": ingested_at or utc_now_iso(),
    }
    # Strict key set
    unexpected = set(out) - set(PUBLIC_RESULTS_SCHEMA)
    if unexpected:
        raise PublicResultsError(f"{label}: unexpected keys {sorted(unexpected)}")
    return out


def load_curated_fixture(path: Path) -> list[dict]:
    """Load a curated JSON fixture: {source_meta..., "rows": [...]}."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublicResultsError(f"Could not read fixture {path}: {exc}") from exc

    if not isinstance(data, dict) or "rows" not in data:
        raise PublicResultsError(
            f"Fixture {path} must be a JSON object with a 'rows' array."
        )
    rows_in = data["rows"]
    if not isinstance(rows_in, list) or not rows_in:
        raise PublicResultsError(f"Fixture {path}: 'rows' must be a non-empty list.")

    defaults = {
        "source_name": data.get("source_name"),
        "source_url": data.get("source_url"),
        "benchmark_name": data.get("benchmark_name"),
        "date_observed": data.get("date_observed"),
    }
    ingested_at = utc_now_iso()
    out = []
    for i, raw in enumerate(rows_in):
        if not isinstance(raw, dict):
            raise PublicResultsError(f"{path.name} rows[{i}] must be an object")
        merged = {k: v for k, v in defaults.items() if v is not None}
        merged.update(raw)
        out.append(normalize_row(
            merged, provenance_kind="curated_fixture",
            ingested_at=ingested_at, label=f"{path.name}[{i}]",
        ))
    return out


def parse_markdown_score_table(text: str, *, defaults: dict) -> list[dict]:
    """
    Deterministic parser for a simple GitHub-style markdown table that
    includes at least columns: submission_name | score | (optional others).

    Expected header names (case-insensitive, flexible):
      submission_name / model / system
      score / score_percent
      team / authors (optional)
      cost_per_task_usd (optional)
      split_type (optional)
      notes (optional)
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 2:
        raise PublicResultsError("Markdown table: need a header row and at least one data row.")

    def cells(line: str) -> list[str]:
        parts = [p.strip() for p in line.strip("|").split("|")]
        return parts

    header = [h.lower().replace(" ", "_") for h in cells(lines[0])]
    # skip separator row if present
    data_lines = lines[1:]
    if data_lines and re.match(r"^:?-+:?$", data_lines[0].replace(" ", "").replace("|", "")):
        data_lines = data_lines[1:]
    elif data_lines and set(data_lines[0].replace("|", "").replace(":", "").replace("-", "").strip()) <= {""}:
        data_lines = data_lines[1:]

    name_aliases = {"submission_name", "model", "system", "submission", "name"}
    score_aliases = {"score", "score_percent", "accuracy", "pct"}
    team_aliases = {"team", "authors", "team_authors"}
    cost_aliases = {"cost_per_task_usd", "cost/task", "cost_per_task"}
    split_aliases = {"split_type", "split"}
    notes_aliases = {"notes", "note"}

    def find_col(aliases: set[str]) -> Optional[int]:
        for i, h in enumerate(header):
            if h in aliases:
                return i
        return None

    i_name = find_col(name_aliases)
    i_score = find_col(score_aliases)
    if i_name is None or i_score is None:
        raise PublicResultsError(
            "Markdown table must include submission/model and score columns. "
            f"Got headers: {header}"
        )
    i_team = find_col(team_aliases)
    i_cost = find_col(cost_aliases)
    i_split = find_col(split_aliases)
    i_notes = find_col(notes_aliases)

    ingested_at = utc_now_iso()
    out = []
    for ridx, line in enumerate(data_lines):
        cols = cells(line)
        if len(cols) < len(header):
            cols = cols + [""] * (len(header) - len(cols))
        raw = dict(defaults)
        raw["submission_name"] = cols[i_name]
        raw["score"] = cols[i_score].replace("%", "").strip()
        if i_team is not None:
            raw["team_authors"] = cols[i_team] or None
        if i_cost is not None and cols[i_cost].strip():
            raw["cost_per_task_usd"] = cols[i_cost].replace("$", "").strip()
        if i_split is not None and cols[i_split].strip():
            raw["split_type"] = cols[i_split].strip()
        if i_notes is not None:
            raw["notes"] = cols[i_notes] or None
        out.append(normalize_row(
            raw, provenance_kind="parsed_table",
            ingested_at=ingested_at, label=f"md_table[{ridx}]",
        ))
    return out


def load_all_fixtures(fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> list[dict]:
    """Load every *.json curated fixture (skip _* and non-row files)."""
    if not fixtures_dir.exists():
        raise PublicResultsError(
            f"Fixtures directory not found: {fixtures_dir}. "
            "Expected curated JSON under fixtures/public_results/."
        )
    rows: list[dict] = []
    for path in sorted(fixtures_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        rows.extend(load_curated_fixture(path))
    md_dir = fixtures_dir / "tables"
    if md_dir.exists():
        for path in sorted(md_dir.glob("*.md")):
            meta_path = path.with_suffix(".meta.json")
            if not meta_path.exists():
                raise PublicResultsError(
                    f"Table snapshot {path.name} needs sibling {meta_path.name} "
                    "with default provenance fields."
                )
            defaults = json.loads(meta_path.read_text(encoding="utf-8"))
            rows.extend(parse_markdown_score_table(
                path.read_text(encoding="utf-8"), defaults=defaults,
            ))
    if not rows:
        raise PublicResultsError(f"No public-results rows loaded from {fixtures_dir}")
    return rows

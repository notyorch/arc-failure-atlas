"""
Submission normalization — parse heterogeneous ARC prediction artifacts into
one canonical representation the evaluator can consume.

Official, recommended integration path for external solvers (no Python
`solve(task)` rewrite required):

  submission.json  OR  predictions/*.json  →  parse → normalize → validate
  → CanonicalSubmission  →  scoring / taxonomy / analytics

Supported source shapes (deterministic mapping only; ambiguous data fails
loudly — never silently coerced):

  1. Kaggle ARC Prize submission.json:
       {"<task_id>": [{"attempt_1": grid, "attempt_2": grid}, ...], ...}

  2. Small structural variants of (1):
       - task value is a single attempt object (one test example)
       - task value is a bare grid (one test, one attempt)
       - task value is a list of bare grids (one grid per test example)
       - attempt keys "attempt1" / "output_1" (underscore/hyphen tolerant)

  3. Directory of per-task JSON files (`<task_id>.json`):
       - same shapes as a single task value in (1)/(2)
       - or a one-key submission object {"<task_id>": [...]}
       - or {"prediction": grid} / {"attempts": [grid, ...]}

  4. Atlas canonical export (format=atlas_canonical_v1) for re-import.

Canonical fields (one row per candidate):
  task_id, test_index (1-based), candidate_rank (1-based),
  predicted_grid, source_format, source_path
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from grid_parser import validate_grid

CANONICAL_FORMAT = "atlas_canonical_v1"

SOURCE_KAGGLE_FILE = "kaggle_submission_json"
SOURCE_PER_TASK_DIR = "per_task_json_dir"
SOURCE_CANONICAL = "atlas_canonical_v1"

# attempt_1, attempt-1, attempt1, output_1, prediction_1, ...
_ATTEMPT_KEY_RE = re.compile(
    r"^(?:attempt|output|prediction)[_-]?(\d+)$", re.IGNORECASE
)


class SubmissionFormatError(ValueError):
    """Artifact cannot be parsed/normalized. Message is human-actionable."""


@dataclass
class CanonicalPrediction:
    """One candidate grid for one (task, test example)."""
    task_id: str
    test_index: int          # 1-based (matches evaluation test_example_id)
    candidate_rank: int      # 1-based (attempt_1 → 1)
    predicted_grid: list     # rectangular list[list[int]] colors 0–9
    source_format: str
    source_path: str


@dataclass
class ValidationIssue:
    severity: str            # "error" | "warning"
    code: str
    message: str
    task_id: Optional[str] = None
    test_index: Optional[int] = None


@dataclass
class CanonicalSubmission:
    """Normalized prediction set + provenance."""
    predictions: list = field(default_factory=list)  # [CanonicalPrediction]
    source_format: str = ""
    source_path: str = ""
    issues: list = field(default_factory=list)       # [ValidationIssue]

    @property
    def errors(self) -> list:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def task_ids(self) -> set:
        return {p.task_id for p in self.predictions}

    def as_attempt_index(self) -> dict:
        """
        Map (task_id, test_index) → list of grids ordered by candidate_rank.
        Used by submission adapters' solve().
        """
        buckets: dict = {}
        for pred in self.predictions:
            key = (pred.task_id, pred.test_index)
            buckets.setdefault(key, []).append(pred)
        index = {}
        for key, preds in buckets.items():
            preds_sorted = sorted(preds, key=lambda p: p.candidate_rank)
            index[key] = [p.predicted_grid for p in preds_sorted]
        return index

    def to_canonical_dict(self) -> dict:
        return {
            "format": CANONICAL_FORMAT,
            "source_format": self.source_format,
            "source_path": self.source_path,
            "n_predictions": len(self.predictions),
            "n_tasks": len(self.task_ids()),
            "predictions": [asdict(p) for p in self.predictions],
            "issues": [asdict(i) for i in self.issues],
        }


def _issue(severity: str, code: str, message: str,
           task_id: Optional[str] = None,
           test_index: Optional[int] = None) -> ValidationIssue:
    return ValidationIssue(severity, code, message, task_id, test_index)


def _require_valid_grid(grid, task_id: str, test_index: int,
                        rank: int) -> tuple:
    """Returns (ok_grid_or_None, issue_or_None)."""
    ok, err = validate_grid(grid)
    if not ok:
        return None, _issue(
            "error", "invalid_grid",
            f"task '{task_id}' test {test_index} attempt {rank}: {err}",
            task_id, test_index,
        )
    return grid, None


def _parse_attempt_object(obj: dict, task_id: str, test_index: int,
                          source_format: str, source_path: str) -> tuple:
    """
    Extract ranked grids from an attempt object.
    Returns (list[CanonicalPrediction], list[ValidationIssue]).
    """
    ranked = {}
    for key, value in obj.items():
        if value is None:
            continue
        match = _ATTEMPT_KEY_RE.match(str(key).strip())
        if not match:
            continue
        rank = int(match.group(1))
        if rank < 1:
            continue
        ranked[rank] = value

    if not ranked:
        # Bare {"prediction": grid} / {"output": grid} without a number.
        for soft_key in ("prediction", "output", "grid"):
            if soft_key in obj and obj[soft_key] is not None:
                ranked[1] = obj[soft_key]
                break

    if not ranked:
        return [], [_issue(
            "error", "no_attempts",
            f"task '{task_id}' test {test_index}: attempt object has no "
            "attempt_1/attempt_2 (or prediction/output) keys",
            task_id, test_index,
        )]

    preds, issues = [], []
    for rank in sorted(ranked):
        grid, issue = _require_valid_grid(ranked[rank], task_id, test_index, rank)
        if issue:
            issues.append(issue)
            continue
        preds.append(CanonicalPrediction(
            task_id=task_id, test_index=test_index, candidate_rank=rank,
            predicted_grid=grid, source_format=source_format,
            source_path=source_path,
        ))
    if not preds and not issues:
        issues.append(_issue(
            "error", "no_valid_attempts",
            f"task '{task_id}' test {test_index}: no valid grids after validation",
            task_id, test_index,
        ))
    return preds, issues


def _normalize_task_value(task_id: str, value, source_format: str,
                          source_path: str) -> tuple:
    """
    Normalize one task's payload into CanonicalPrediction rows.
    Returns (predictions, issues).
    """
    # Case A: list — either attempt-objects per test, or bare grids per test.
    if isinstance(value, list):
        if not value:
            return [], [_issue(
                "error", "empty_task",
                f"task '{task_id}': empty list (no test predictions)",
                task_id,
            )]
        # Distinguish list-of-grids (2D) vs list-of-attempt-objects / mixed.
        # A "bare grid" is a non-empty list whose first element is a list of
        # ints (a row). A list of attempt objects has dicts. A list of grids
        # for multiple tests has list elements that are themselves grids.
        first = value[0]
        if isinstance(first, list) and first and isinstance(first[0], int):
            # Entire value is ONE bare grid (rows of ints), not a list of tests.
            grid, issue = _require_valid_grid(value, task_id, 1, 1)
            if issue:
                return [], [issue]
            return [CanonicalPrediction(
                task_id=task_id, test_index=1, candidate_rank=1,
                predicted_grid=grid, source_format=source_format,
                source_path=source_path,
            )], []

        preds, issues = [], []
        for i, item in enumerate(value):
            test_index = i + 1
            if isinstance(item, dict):
                p, iss = _parse_attempt_object(
                    item, task_id, test_index, source_format, source_path)
                preds.extend(p)
                issues.extend(iss)
            elif isinstance(item, list):
                grid, issue = _require_valid_grid(item, task_id, test_index, 1)
                if issue:
                    issues.append(issue)
                else:
                    preds.append(CanonicalPrediction(
                        task_id=task_id, test_index=test_index,
                        candidate_rank=1, predicted_grid=grid,
                        source_format=source_format, source_path=source_path,
                    ))
            else:
                issues.append(_issue(
                    "error", "unsupported_test_entry",
                    f"task '{task_id}' test {test_index}: expected attempt "
                    f"object or grid, got {type(item).__name__}",
                    task_id, test_index,
                ))
        return preds, issues

    # Case B: single attempt object (one test example).
    if isinstance(value, dict):
        if set(value.keys()) == {task_id}:
            return _normalize_task_value(
                task_id, value[task_id], source_format, source_path)
        return _parse_attempt_object(
            value, task_id, 1, source_format, source_path)

    return [], [_issue(
        "error", "unsupported_task_value",
        f"task '{task_id}': unsupported value type {type(value).__name__}. "
        "Expected list of attempts, attempt object, or grid.",
        task_id,
    )]


def _normalize_submission_object(data: dict, source_format: str,
                                 source_path: str) -> CanonicalSubmission:
    """Normalize a top-level {task_id: ...} mapping."""
    if not data:
        return CanonicalSubmission(
            source_format=source_format, source_path=source_path,
            issues=[_issue("error", "empty_submission",
                           "submission object is empty")],
        )

    bad_keys = [k for k in data if not isinstance(k, str)]
    if bad_keys:
        return CanonicalSubmission(
            source_format=source_format, source_path=source_path,
            issues=[_issue(
                "error", "invalid_task_id",
                f"submission keys must be task_id strings; got non-strings: "
                f"{bad_keys[:5]!r}",
            )],
        )

    preds, issues = [], []
    for task_id, value in data.items():
        if task_id.startswith("_"):
            continue
        p, iss = _normalize_task_value(
            task_id, value, source_format, source_path)
        preds.extend(p)
        issues.extend(iss)

    if not preds and not issues:
        issues.append(_issue(
            "error", "no_predictions",
            "no predictions could be extracted from the submission object",
        ))

    return CanonicalSubmission(
        predictions=preds, source_format=source_format,
        source_path=source_path, issues=issues,
    )


def load_canonical_dict(data: dict, source_path: str) -> CanonicalSubmission:
    """Re-import an atlas_canonical_v1 artifact."""
    preds, issues = [], []
    raw_list = data.get("predictions")
    if not isinstance(raw_list, list):
        return CanonicalSubmission(
            source_format=SOURCE_CANONICAL, source_path=source_path,
            issues=[_issue("error", "canonical_missing_predictions",
                           "atlas_canonical_v1 requires a 'predictions' list")],
        )
    for i, row in enumerate(raw_list):
        if not isinstance(row, dict):
            issues.append(_issue(
                "error", "canonical_bad_row",
                f"predictions[{i}] must be an object",
            ))
            continue
        try:
            task_id = str(row["task_id"])
            test_index = int(row["test_index"])
            rank = int(row["candidate_rank"])
            grid = row["predicted_grid"]
        except (KeyError, TypeError, ValueError) as exc:
            issues.append(_issue(
                "error", "canonical_bad_row",
                f"predictions[{i}] missing/invalid fields: {exc}",
            ))
            continue
        ok_grid, issue = _require_valid_grid(grid, task_id, test_index, rank)
        if issue:
            issues.append(issue)
            continue
        preds.append(CanonicalPrediction(
            task_id=task_id, test_index=test_index, candidate_rank=rank,
            predicted_grid=ok_grid,
            source_format=row.get("source_format") or SOURCE_CANONICAL,
            source_path=row.get("source_path") or source_path,
        ))
    return CanonicalSubmission(
        predictions=preds, source_format=SOURCE_CANONICAL,
        source_path=source_path, issues=issues,
    )


def load_submission_file(path: Path) -> CanonicalSubmission:
    """Load + normalize a single JSON submission / canonical file."""
    path = Path(path)
    if not path.exists():
        raise SubmissionFormatError(f"Submission file not found: {path}")
    if not path.is_file():
        raise SubmissionFormatError(f"Not a file: {path}")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SubmissionFormatError(
            f"Invalid JSON in {path}: {exc.msg} (line {exc.lineno}, "
            f"col {exc.colno})"
        ) from exc
    except OSError as exc:
        raise SubmissionFormatError(f"Could not read {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SubmissionFormatError(
            f"{path} must be a JSON object (got {type(data).__name__}). "
            "Expected a Kaggle-style submission map or atlas_canonical_v1."
        )

    source_path = str(path)
    if data.get("format") == CANONICAL_FORMAT:
        return load_canonical_dict(data, source_path)

    sample_vals = [v for k, v in data.items() if not str(k).startswith("_")]
    if not sample_vals:
        return CanonicalSubmission(
            source_format=SOURCE_KAGGLE_FILE, source_path=source_path,
            issues=[_issue("error", "empty_submission",
                           f"{path.name} has no task entries")],
        )

    return _normalize_submission_object(data, SOURCE_KAGGLE_FILE, source_path)


def _normalize_per_task_file(path: Path, task_id: str) -> tuple:
    """Normalize one per-task JSON file. Returns (predictions, issues)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        return [], [_issue(
            "error", "invalid_json",
            f"{path.name}: invalid JSON: {exc.msg} "
            f"(line {exc.lineno}, col {exc.colno})",
            task_id,
        )]
    except OSError as exc:
        return [], [_issue(
            "error", "read_error",
            f"{path.name}: could not read: {exc}", task_id,
        )]

    source_path = str(path)

    if isinstance(data, dict) and data.get("format") == CANONICAL_FORMAT:
        sub = load_canonical_dict(data, source_path)
        preds = [p for p in sub.predictions if p.task_id == task_id]
        if not preds and sub.predictions:
            preds = []
            for p in sub.predictions:
                preds.append(CanonicalPrediction(
                    task_id=task_id, test_index=p.test_index,
                    candidate_rank=p.candidate_rank,
                    predicted_grid=p.predicted_grid,
                    source_format=p.source_format,
                    source_path=p.source_path,
                ))
        return preds, list(sub.issues)

    if isinstance(data, dict) and task_id in data and len(data) == 1:
        return _normalize_task_value(
            task_id, data[task_id], SOURCE_PER_TASK_DIR, source_path)

    if isinstance(data, dict):
        keys = {str(k).lower() for k in data.keys()}
        envelope_keys = {
            "prediction", "predictions", "attempts", "output", "grid",
            "attempt_1", "attempt_2", "attempt1", "attempt2",
        }
        if keys and keys <= envelope_keys | {k for k in keys if _ATTEMPT_KEY_RE.match(k)}:
            if "attempts" in data and isinstance(data["attempts"], list):
                return _normalize_task_value(
                    task_id, data["attempts"], SOURCE_PER_TASK_DIR, source_path)
            if "predictions" in data and isinstance(data["predictions"], list):
                return _normalize_task_value(
                    task_id, data["predictions"], SOURCE_PER_TASK_DIR, source_path)
            return _parse_attempt_object(
                data, task_id, 1, SOURCE_PER_TASK_DIR, source_path)

    return _normalize_task_value(
        task_id, data, SOURCE_PER_TASK_DIR, source_path)


def load_submission_dir(path: Path) -> CanonicalSubmission:
    """
    Load a directory of per-task JSON prediction files.

    Each `*.json` file's stem is the task_id (e.g. sample01.json → sample01).
    Non-JSON files are ignored. Empty directories fail with an explicit error.
    """
    path = Path(path)
    if not path.exists():
        raise SubmissionFormatError(f"Submission directory not found: {path}")
    if not path.is_dir():
        raise SubmissionFormatError(f"Not a directory: {path}")

    files = sorted(path.glob("*.json"))
    if not files:
        return CanonicalSubmission(
            source_format=SOURCE_PER_TASK_DIR, source_path=str(path),
            issues=[_issue(
                "error", "empty_directory",
                f"No *.json files under {path}. Expected one file per task_id "
                "(e.g. 00576224.json).",
            )],
        )

    preds, issues = [], []
    for file_path in files:
        task_id = file_path.stem
        p, iss = _normalize_per_task_file(file_path, task_id)
        preds.extend(p)
        issues.extend(iss)

    return CanonicalSubmission(
        predictions=preds, source_format=SOURCE_PER_TASK_DIR,
        source_path=str(path), issues=issues,
    )


def load_submission_artifact(path: Path) -> CanonicalSubmission:
    """Auto-detect file vs directory and load."""
    path = Path(path)
    if path.is_dir():
        return load_submission_dir(path)
    return load_submission_file(path)


def cross_check_expected_tasks(
    submission: CanonicalSubmission,
    expected_task_ids: set,
    *,
    missing_as: str = "warning",
    extra_as: str = "warning",
) -> CanonicalSubmission:
    """
    Compare normalized task coverage against an expected set (usually from
    the tasks Parquet). Adds issues; does not remove predictions.
    missing_as / extra_as: "error" | "warning" | "ignore"
    """
    if not expected_task_ids:
        return submission

    present = submission.task_ids()
    missing = sorted(expected_task_ids - present)
    extra = sorted(present - expected_task_ids)

    issues = list(submission.issues)
    if missing_as != "ignore":
        for task_id in missing:
            issues.append(_issue(
                missing_as, "missing_task",
                f"expected task '{task_id}' has no predictions in the artifact",
                task_id,
            ))
    if extra_as != "ignore":
        for task_id in extra:
            issues.append(_issue(
                extra_as, "extra_task",
                f"artifact has task '{task_id}' which is not in the expected "
                "task set",
                task_id,
            ))
    submission.issues = issues
    return submission


def format_validation_report(submission: CanonicalSubmission) -> str:
    """Human-readable validation summary for CLI output."""
    lines = [
        f"source_format : {submission.source_format}",
        f"source_path   : {submission.source_path}",
        f"tasks         : {len(submission.task_ids())}",
        f"predictions   : {len(submission.predictions)} "
        f"(task × test × candidate rows)",
        f"status        : {'OK' if submission.ok else 'FAILED'} "
        f"({len(submission.errors)} error(s), "
        f"{len(submission.warnings)} warning(s))",
    ]
    if submission.issues:
        lines.append("issues:")
        for issue in submission.issues:
            loc = ""
            if issue.task_id:
                loc = f" [{issue.task_id}"
                if issue.test_index is not None:
                    loc += f" test={issue.test_index}"
                loc += "]"
            lines.append(
                f"  - {issue.severity.upper()} {issue.code}{loc}: {issue.message}"
            )
    return "\n".join(lines)


def write_canonical_json(submission: CanonicalSubmission, dest: Path) -> Path:
    """Persist atlas_canonical_v1 for import-submission / replay."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    payload = submission.to_canonical_dict()
    payload["import_error_count"] = len(submission.errors)
    payload["import_warning_count"] = len(submission.warnings)
    payload.pop("issues", None)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")
    return dest

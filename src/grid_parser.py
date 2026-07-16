"""
Parse and validate model responses into ARC grids.

A model reply may be a plain JSON array, a fenced ```json block, or prose
with a grid buried somewhere inside. The parser scans the text for balanced
JSON arrays and returns the first one that validates as an ARC grid
(rectangular 2D array of ints 0-9).

Parse status values (stable vocabulary, consumed by failure_taxonomy.py):
    ok              — a valid grid was extracted
    empty_response  — response text is None / empty / whitespace
    no_json_array   — no parseable JSON array anywhere in the text
    invalid_grid    — JSON array(s) found, but none is a valid ARC grid
    not_attempted   — provider call failed, so there was nothing to parse
                      (set by the runner, never returned by parse_response)
"""

import json
from dataclasses import dataclass
from typing import Iterator, Optional

ARC_COLOR_MIN = 0
ARC_COLOR_MAX = 9

# Bound the scan so a pathological response cannot stall the run.
# Thinking dumps can contain many nested arrays; keep headroom above 200.
_MAX_CANDIDATES = 2000

PARSE_OK = "ok"
PARSE_EMPTY = "empty_response"
PARSE_NO_JSON = "no_json_array"
PARSE_INVALID_GRID = "invalid_grid"
PARSE_NOT_ATTEMPTED = "not_attempted"


@dataclass
class ParseResult:
    parse_status: str
    parse_error: Optional[str]
    predicted_grid_json: Optional[str]
    predicted_grid_obj: Optional[list]


def serialize_grid(grid: list) -> str:
    """Compact, deterministic JSON serialization (no whitespace)."""
    return json.dumps(grid, separators=(",", ":"))


def normalize_grid(grid: list) -> list:
    """
    Light normalization before validation: cast integral floats to int
    (models sometimes emit 2.0 instead of 2). Everything else is left
    untouched so validate_grid can report the real problem.
    """
    normalized = []
    for row in grid:
        if not isinstance(row, list):
            return grid  # not 2D; let validate_grid explain
        new_row = []
        for val in row:
            if isinstance(val, float) and val.is_integer():
                new_row.append(int(val))
            else:
                new_row.append(val)
        normalized.append(new_row)
    return normalized


def validate_grid(grid) -> tuple:
    """
    Validates a candidate as an ARC grid: non-empty rectangular 2D list of
    ints in [0, 9]. Returns (is_valid, error_message). Booleans are rejected
    even though bool subclasses int in Python.
    """
    if not isinstance(grid, list) or len(grid) == 0:
        return False, "not a non-empty list"
    if not all(isinstance(row, list) for row in grid):
        return False, "not 2D (expected list of lists)"
    if len(grid[0]) == 0:
        return False, "first row is empty"

    expected_cols = len(grid[0])
    for i, row in enumerate(grid):
        if len(row) != expected_cols:
            return False, (
                f"inconsistent dimensions: row {i} has {len(row)} cols, "
                f"expected {expected_cols}"
            )
        for j, val in enumerate(row):
            if isinstance(val, bool) or not isinstance(val, int):
                return False, f"non-integer value at [{i}][{j}]: {val!r}"
            if not (ARC_COLOR_MIN <= val <= ARC_COLOR_MAX):
                return False, (
                    f"value out of ARC range [{ARC_COLOR_MIN}-{ARC_COLOR_MAX}] "
                    f"at [{i}][{j}]: {val}"
                )
    return True, ""


def _iter_json_array_candidates(text: str) -> Iterator[list]:
    """
    Yields every parseable JSON array found in the text, left to right.
    Balanced-bracket matching tracks string literals so brackets inside
    quotes do not break alignment. Nested arrays inside an already-yielded
    candidate are not re-yielded (the scan resumes after the closing bracket).
    """
    n = len(text)
    pos = 0
    yielded = 0
    while pos < n and yielded < _MAX_CANDIDATES:
        start = text.find("[", pos)
        if start == -1:
            return
        depth = 0
        in_string = False
        escaped = False
        end = -1
        for i in range(start, n):
            ch = text[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end == -1:
            # Unbalanced from this '['; retry from the next one.
            pos = start + 1
            continue
        candidate = text[start:end + 1]
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            pos = start + 1
            continue
        if isinstance(obj, list):
            yielded += 1
            yield obj
            pos = end + 1
        else:
            pos = start + 1


def extract_first_json_array(text: str) -> Optional[list]:
    """First parseable JSON array in the text (grid candidate), or None."""
    if not text:
        return None
    return next(_iter_json_array_candidates(text), None)


def parse_grid_object(obj) -> ParseResult:
    """
    Validate an ALREADY-STRUCTURED prediction (a Python list from a solver's
    JSON envelope or a submission file) into the same ParseResult contract as
    free-text parsing, so structured and text-emitting solvers flow through
    identical validation, scoring, and taxonomy paths.
    """
    if obj is None:
        return ParseResult(PARSE_EMPTY, "solver returned no prediction", None, None)
    grid = normalize_grid(obj) if isinstance(obj, list) else obj
    is_valid, error = validate_grid(grid)
    if is_valid:
        return ParseResult(PARSE_OK, None, serialize_grid(grid), grid)
    return ParseResult(
        PARSE_INVALID_GRID, f"structured prediction is not a valid ARC grid: {error}",
        None, None,
    )


def parse_response(response_text: Optional[str]) -> ParseResult:
    """
    Full pipeline: scan → normalize → validate.

    Returns the **last** candidate that validates as an ARC grid. Thinking
    models often emit intermediate arrays while reasoning; the final answer
    is typically the last valid grid in the text. Earlier invalid arrays are
    skipped (same as before).
    """
    if response_text is None or not response_text.strip():
        return ParseResult(PARSE_EMPTY, "response text is empty", None, None)

    found_any = False
    last_error = None
    last_ok: Optional[ParseResult] = None
    for candidate in _iter_json_array_candidates(response_text):
        found_any = True
        grid = normalize_grid(candidate)
        is_valid, error = validate_grid(grid)
        if is_valid:
            last_ok = ParseResult(PARSE_OK, None, serialize_grid(grid), grid)
        else:
            last_error = error

    if last_ok is not None:
        return last_ok
    if not found_any:
        return ParseResult(
            PARSE_NO_JSON, "no parseable JSON array in response", None, None
        )
    return ParseResult(
        PARSE_INVALID_GRID, f"JSON array found but not a valid ARC grid: {last_error}",
        None, None,
    )

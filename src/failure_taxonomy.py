"""
Failure taxonomy v2 — deterministic heuristic classification of one
evaluation result into exactly one mode. Solver-agnostic: the same rules
judge an LLM completion, a subprocess solver's stdout, or a submission-file
attempt.

Modes (stable vocabulary, stored in the `failure_mode` column):
    exact_match     — prediction equals ground truth cell for cell
    execution_error — the solver never produced a judgeable output
                      (API failure, subprocess crash/timeout, HTTP error).
                      v1 called this `api_error`; renamed for solver
                      neutrality in v2 (Decision 17).
    empty_response  — solver replied with empty/whitespace output
    parse_error     — output present but no valid ARC grid extractable
    shape_error     — valid grid, wrong dimensions
    spatial_error   — right shape AND right color histogram, cells misplaced
                      (content moved around incorrectly — transformation/
                      placement failure)
    symbol_error    — right shape, wrong color histogram (wrong/hallucinated
                      symbols)
    unknown_error   — defensive fallback; should not occur in practice

Classification is rule-ordered (first hit wins) and uses only the row's own
data, so re-running classification on stored rows is reproducible:

    1. solver status != ok                          -> execution_error
    2. parse_status == empty_response               -> empty_response
    3. parse_status in {no_json_array,invalid_grid} -> parse_error
    4. no ground truth available                    -> None (not classifiable)
    5. exact match                                  -> exact_match
    6. shape mismatch                               -> shape_error
    7. same shape, same color histogram             -> spatial_error
    8. same shape, different histogram              -> symbol_error
    9. anything else                                -> unknown_error

Note: `exact_match` is included as a taxonomy outcome so the distribution
over ALL rows sums to 100% (success is just another bucket in the atlas).
Finer reasoning-level categories (abstraction failures, wrong-rule-applied,
near-miss program synthesis...) are future taxonomy v3 work and would need
task/transformation labels the platform does not have yet.
"""

from typing import Optional, Tuple

from evaluator import EvalResult, color_histogram
from grid_parser import PARSE_EMPTY, PARSE_INVALID_GRID, PARSE_NO_JSON, PARSE_OK

# Kept in sync with providers.STATUS_OK / solvers: "ok" is the only success.
_STATUS_OK = "ok"

FAILURE_MODES = [
    "exact_match",
    "execution_error",
    "empty_response",
    "parse_error",
    "shape_error",
    "spatial_error",
    "symbol_error",
    "unknown_error",
]

# v1 -> v2 vocabulary migration (applied by the analytics legacy upgrade).
LEGACY_MODE_RENAMES = {"api_error": "execution_error"}


def classify_failure(
    solver_status: str,
    parse_status: str,
    evaluation: EvalResult,
    predicted_grid: Optional[list],
    expected_grid: Optional[list],
    solver_error: Optional[str] = None,
    parse_error: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (failure_mode, failure_detail).

    failure_mode is None only when the prediction is valid but there is no
    ground truth to compare against (hidden-set style rows).
    """
    # 1. Solver never produced a judgeable output.
    if solver_status != _STATUS_OK:
        return "execution_error", solver_error or "solver execution failed"

    # 2-3. Output exists but no valid grid came out of it.
    if parse_status == PARSE_EMPTY:
        return "empty_response", "solver returned an empty response"
    if parse_status in (PARSE_NO_JSON, PARSE_INVALID_GRID):
        return "parse_error", parse_error or "no valid grid in output"
    if parse_status != PARSE_OK or predicted_grid is None:
        return "unknown_error", f"unexpected parse_status '{parse_status}'"

    # 4. Valid prediction but nothing to compare against.
    if expected_grid is None:
        return None, "no ground truth available for this test example"

    # 5. Success is a taxonomy bucket too.
    if evaluation.is_exact_match:
        return "exact_match", None

    # 6. Wrong dimensions.
    if not evaluation.same_shape:
        pred_shape = f"{len(predicted_grid)}x{len(predicted_grid[0])}"
        exp_shape = f"{len(expected_grid)}x{len(expected_grid[0])}"
        return "shape_error", f"predicted {pred_shape}, expected {exp_shape}"

    # 7-8. Same shape: histogram heuristic separates "right colors, wrong
    # places" from "wrong colors".
    pred_hist = color_histogram(predicted_grid)
    exp_hist = color_histogram(expected_grid)
    if pred_hist == exp_hist:
        return "spatial_error", (
            f"same shape and color histogram; {evaluation.n_diff_cells} "
            "cell(s) misplaced"
        )
    return "symbol_error", (
        f"same shape but color histogram differs; {evaluation.n_diff_cells} "
        "cell(s) wrong"
    )

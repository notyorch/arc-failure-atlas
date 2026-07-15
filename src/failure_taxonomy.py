"""
Failure taxonomy v1 — deterministic heuristic classification of one
inference result into exactly one mode.

Modes (stable vocabulary, stored in the `failure_mode` column):
    exact_match     — prediction equals ground truth cell for cell
    api_error       — provider call failed (no response to judge)
    empty_response  — provider replied with empty/whitespace text
    parse_error     — text present but no valid ARC grid extractable
    shape_error     — valid grid, wrong dimensions
    spatial_error   — right shape AND right color histogram, cells misplaced
                      (the model moved content around incorrectly)
    symbol_error    — right shape, wrong color histogram
                      (the model used the wrong symbols/colors)
    unknown_error   — defensive fallback; should not occur in practice

Classification is rule-ordered (first hit wins) and uses only the row's own
data, so re-running classification on stored rows is reproducible:

    1. provider status != ok                        -> api_error
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
"""

from typing import Optional, Tuple

from evaluator import EvalResult, color_histogram
from grid_parser import PARSE_EMPTY, PARSE_INVALID_GRID, PARSE_NO_JSON, PARSE_OK
from providers import STATUS_OK

FAILURE_MODES = [
    "exact_match",
    "api_error",
    "empty_response",
    "parse_error",
    "shape_error",
    "spatial_error",
    "symbol_error",
    "unknown_error",
]


def classify_failure(
    provider_status: str,
    parse_status: str,
    evaluation: EvalResult,
    predicted_grid: Optional[list],
    expected_grid: Optional[list],
    provider_error: Optional[str] = None,
    parse_error: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (failure_mode, failure_detail).

    failure_mode is None only when the prediction is valid but there is no
    ground truth to compare against (hidden-set style rows).
    """
    # 1. Provider never produced a judgeable response.
    if provider_status != STATUS_OK:
        return "api_error", provider_error or "provider call failed"

    # 2-3. Response exists but no valid grid came out of it.
    if parse_status == PARSE_EMPTY:
        return "empty_response", "model returned an empty response"
    if parse_status in (PARSE_NO_JSON, PARSE_INVALID_GRID):
        return "parse_error", parse_error or "no valid grid in response"
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

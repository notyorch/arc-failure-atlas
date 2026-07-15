"""
Scoring of predicted grids against expected (ground truth) grids.

Definitions (documented in src/DECISIONS.md — Decision 12):
    is_exact_match — same shape AND every cell equal.
    same_shape     — identical (rows, cols).
    cell_accuracy  — same shape: matching cells / total cells.
                     different shape: matching cells in the top-left overlap
                     region / max(total predicted cells, total expected
                     cells), so both missing and extra cells count against
                     the score.
    n_diff_cells   — the complementary count: denominator - matching cells.

When there is no valid prediction or no ground truth, every metric is None
(never 0.0) so failed parses cannot silently deflate or inflate averages.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Optional


@dataclass
class EvalResult:
    is_exact_match: Optional[bool] = None
    same_shape: Optional[bool] = None
    cell_accuracy: Optional[float] = None
    n_diff_cells: Optional[int] = None


def color_histogram(grid: list) -> dict:
    """Color value -> count over the whole grid (order-independent)."""
    return dict(Counter(val for row in grid for val in row))


def evaluate_prediction(predicted: Optional[list],
                        expected: Optional[list]) -> EvalResult:
    """
    Compares a predicted grid with the expected grid. Both inputs must be
    already-validated 2D int grids (see grid_parser.validate_grid) or None.
    Returns an EvalResult with all fields None when comparison is impossible.
    """
    if predicted is None or expected is None:
        return EvalResult()

    pred_shape = (len(predicted), len(predicted[0]))
    exp_shape = (len(expected), len(expected[0]))
    same_shape = pred_shape == exp_shape

    if same_shape:
        total = exp_shape[0] * exp_shape[1]
        matches = sum(
            1
            for row_pred, row_exp in zip(predicted, expected)
            for val_pred, val_exp in zip(row_pred, row_exp)
            if val_pred == val_exp
        )
        diff = total - matches
        return EvalResult(
            is_exact_match=(diff == 0),
            same_shape=True,
            cell_accuracy=matches / total,
            n_diff_cells=diff,
        )

    # Shape mismatch: score the top-left overlap, denominate by the larger
    # grid so extra or missing area is penalized.
    overlap_rows = min(pred_shape[0], exp_shape[0])
    overlap_cols = min(pred_shape[1], exp_shape[1])
    matches = sum(
        1
        for i in range(overlap_rows)
        for j in range(overlap_cols)
        if predicted[i][j] == expected[i][j]
    )
    denominator = max(pred_shape[0] * pred_shape[1], exp_shape[0] * exp_shape[1])
    return EvalResult(
        is_exact_match=False,
        same_shape=False,
        cell_accuracy=matches / denominator,
        n_diff_cells=denominator - matches,
    )

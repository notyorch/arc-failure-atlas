"""Unit tests for src/grid_parser.py — run from the repo root:

    python -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from grid_parser import (  # noqa: E402
    PARSE_EMPTY,
    PARSE_INVALID_GRID,
    PARSE_NO_JSON,
    PARSE_OK,
    extract_first_json_array,
    normalize_grid,
    parse_response,
    serialize_grid,
    validate_grid,
)


class TestParseResponse(unittest.TestCase):
    def test_plain_json_array(self):
        result = parse_response("[[1,2],[3,4]]")
        self.assertEqual(result.parse_status, PARSE_OK)
        self.assertEqual(result.predicted_grid_obj, [[1, 2], [3, 4]])
        self.assertEqual(result.predicted_grid_json, "[[1,2],[3,4]]")

    def test_fenced_code_block(self):
        result = parse_response("Here you go:\n```json\n[[0,1],[2,3]]\n```\nDone.")
        self.assertEqual(result.parse_status, PARSE_OK)
        self.assertEqual(result.predicted_grid_obj, [[0, 1], [2, 3]])

    def test_prose_with_stray_array_before_grid(self):
        # "[1]" is a valid JSON array but not a grid; the scan must continue.
        result = parse_response("row [1] is odd, but the answer is [[5,5],[5,5]].")
        self.assertEqual(result.parse_status, PARSE_OK)
        self.assertEqual(result.predicted_grid_obj, [[5, 5], [5, 5]])

    def test_prefers_last_valid_grid(self):
        result = parse_response(
            "maybe [[1,1],[1,1]] but final answer [[9,9],[9,9]]"
        )
        self.assertEqual(result.parse_status, PARSE_OK)
        self.assertEqual(result.predicted_grid_obj, [[9, 9], [9, 9]])

    def test_integral_floats_are_normalized(self):
        result = parse_response("[[1.0, 2.0], [3.0, 4.0]]")
        self.assertEqual(result.parse_status, PARSE_OK)
        self.assertEqual(result.predicted_grid_obj, [[1, 2], [3, 4]])

    def test_flat_array_is_invalid_grid(self):
        result = parse_response("[1,2,3,4]")
        self.assertEqual(result.parse_status, PARSE_INVALID_GRID)
        self.assertIsNone(result.predicted_grid_obj)

    def test_out_of_range_value(self):
        result = parse_response("[[11,2],[3,4]]")
        self.assertEqual(result.parse_status, PARSE_INVALID_GRID)
        self.assertIn("out of ARC range", result.parse_error)

    def test_booleans_rejected(self):
        result = parse_response("[[true, false]]")
        self.assertEqual(result.parse_status, PARSE_INVALID_GRID)

    def test_ragged_rows_rejected(self):
        result = parse_response("[[1,2],[3]]")
        self.assertEqual(result.parse_status, PARSE_INVALID_GRID)
        self.assertIn("inconsistent dimensions", result.parse_error)

    def test_no_json_at_all(self):
        result = parse_response("I cannot determine the output grid.")
        self.assertEqual(result.parse_status, PARSE_NO_JSON)

    def test_empty_and_none_responses(self):
        for text in ("", "   \n\t ", None):
            with self.subTest(text=text):
                self.assertEqual(parse_response(text).parse_status, PARSE_EMPTY)

    def test_unbalanced_brackets_recovers_nothing_valid(self):
        result = parse_response("[[1,2],[3")
        self.assertNotEqual(result.parse_status, PARSE_OK)


class TestValidateGrid(unittest.TestCase):
    def test_valid_grid(self):
        ok, error = validate_grid([[0, 9], [5, 5]])
        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_rejects_non_list_empty_and_empty_row(self):
        for bad in ("nope", [], [[]], [[1], "x"]):
            with self.subTest(bad=bad):
                ok, _ = validate_grid(bad)
                self.assertFalse(ok)

    def test_rejects_non_integer_cells(self):
        for bad in ([[1, "2"]], [[1, 2.5]], [[None, 1]]):
            with self.subTest(bad=bad):
                ok, _ = validate_grid(bad)
                self.assertFalse(ok)


class TestHelpers(unittest.TestCase):
    def test_serialize_grid_is_compact(self):
        self.assertEqual(serialize_grid([[1, 2], [3, 4]]), "[[1,2],[3,4]]")

    def test_extract_first_json_array(self):
        self.assertEqual(extract_first_json_array("x [1,2] y [[3]]"), [1, 2])
        self.assertIsNone(extract_first_json_array("no arrays here"))
        self.assertIsNone(extract_first_json_array(""))

    def test_normalize_grid_leaves_non_integral_floats(self):
        self.assertEqual(normalize_grid([[1.5]]), [[1.5]])  # validate rejects later


if __name__ == "__main__":
    unittest.main()

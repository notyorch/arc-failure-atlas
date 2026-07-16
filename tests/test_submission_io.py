"""Unit tests for src/submission_io.py — offline normalization / validation.

    python -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from submission_io import (  # noqa: E402
    CANONICAL_FORMAT,
    SOURCE_KAGGLE_FILE,
    SOURCE_PER_TASK_DIR,
    SubmissionFormatError,
    cross_check_expected_tasks,
    load_submission_dir,
    load_submission_file,
    write_canonical_json,
)


class TestKaggleSubmission(unittest.TestCase):
    def test_classic_attempt_objects(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub.json"
            path.write_text(json.dumps({
                "t1": [{"attempt_1": [[1]], "attempt_2": [[2]]}],
            }), encoding="utf-8")
            sub = load_submission_file(path)
            self.assertTrue(sub.ok)
            self.assertEqual(sub.source_format, SOURCE_KAGGLE_FILE)
            self.assertEqual(len(sub.predictions), 2)
            index = sub.as_attempt_index()
            self.assertEqual(index[("t1", 1)], [[[1]], [[2]]])

    def test_bare_grid_per_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub.json"
            path.write_text(json.dumps({
                "t1": [[0, 1], [2, 3]],
            }), encoding="utf-8")
            sub = load_submission_file(path)
            self.assertTrue(sub.ok)
            self.assertEqual(sub.predictions[0].candidate_rank, 1)
            self.assertEqual(sub.predictions[0].predicted_grid, [[0, 1], [2, 3]])

    def test_invalid_color_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub.json"
            path.write_text(json.dumps({
                "t1": [{"attempt_1": [[99]]}],
            }), encoding="utf-8")
            sub = load_submission_file(path)
            self.assertFalse(sub.ok)
            self.assertTrue(any(i.code == "invalid_grid" for i in sub.errors))

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(SubmissionFormatError):
                load_submission_file(path)


class TestPredictionDir(unittest.TestCase):
    def test_per_task_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpha.json").write_text(
                json.dumps({"prediction": [[1, 0]]}), encoding="utf-8")
            (root / "beta.json").write_text(
                json.dumps({"attempt_1": [[2]]}), encoding="utf-8")
            sub = load_submission_dir(root)
            self.assertTrue(sub.ok)
            self.assertEqual(sub.source_format, SOURCE_PER_TASK_DIR)
            self.assertEqual(sub.task_ids(), {"alpha", "beta"})

    def test_empty_dir_is_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            sub = load_submission_dir(Path(tmp))
            self.assertFalse(sub.ok)
            self.assertEqual(sub.errors[0].code, "empty_directory")


class TestCanonicalRoundTrip(unittest.TestCase):
    def test_import_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "sub.json"
            src.write_text(json.dumps({
                "t1": [{"attempt_1": [[4]]}],
            }), encoding="utf-8")
            sub = load_submission_file(src)
            dest = Path(tmp) / "canonical.json"
            write_canonical_json(sub, dest)
            data = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(data["format"], CANONICAL_FORMAT)
            again = load_submission_file(dest)
            self.assertTrue(again.ok)
            self.assertEqual(len(again.predictions), 1)


class TestCoverageCheck(unittest.TestCase):
    def test_missing_and_extra(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sub.json"
            path.write_text(json.dumps({
                "only": [{"attempt_1": [[0]]}],
            }), encoding="utf-8")
            sub = load_submission_file(path)
            sub = cross_check_expected_tasks(
                sub, {"only", "missing"}, missing_as="error", extra_as="warning",
            )
            codes = {i.code for i in sub.issues}
            self.assertIn("missing_task", codes)
            self.assertTrue(any(i.severity == "error" for i in sub.issues
                                if i.code == "missing_task"))


if __name__ == "__main__":
    unittest.main()

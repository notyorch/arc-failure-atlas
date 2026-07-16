"""Unit tests for public_results observatory (offline fixtures only)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from public_results.ingestion import (  # noqa: E402
    PublicResultsError,
    load_curated_fixture,
    normalize_row,
    parse_markdown_score_table,
)
from public_results.schemas import PUBLIC_RESULTS_SCHEMA  # noqa: E402
from public_results.store import rows_to_dataframe  # noqa: E402
from public_results.local_anchor import local_run_to_public_row  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FIXTURES = REPO / "fixtures" / "public_results"


class TestNormalize(unittest.TestCase):
    def test_percent_score_coerced(self):
        row = normalize_row({
            "source_name": "t", "source_url": "http://x",
            "benchmark_name": "ARC-AGI-1", "submission_name": "s",
            "score": 75.7, "date_observed": "2025-01-01",
            "verification_status": "verified",
            "trust_tier": "official_verified",
            "split_type": "semi_private",
            "comparison_scope": "semi_private_100",
        }, provenance_kind="curated_fixture")
        self.assertAlmostEqual(row["score"], 0.757, places=4)
        self.assertEqual(set(row), set(PUBLIC_RESULTS_SCHEMA))

    def test_rejects_unknown_trust(self):
        with self.assertRaises(PublicResultsError):
            normalize_row({
                "source_name": "t", "source_url": "http://x",
                "benchmark_name": "ARC-AGI-1", "submission_name": "s",
                "score": 0.1, "date_observed": "2025-01-01",
                "verification_status": "verified",
                "trust_tier": "not_a_tier",
                "split_type": "public",
                "comparison_scope": "full_benchmark",
            }, provenance_kind="curated_fixture")


class TestFixtures(unittest.TestCase):
    def test_official_fixture_loads(self):
        rows = load_curated_fixture(FIXTURES / "arc_prize_official.json")
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(all(r["source_name"] == "arc_prize_official" for r in rows))

    def test_markdown_table_parser(self):
        text = (FIXTURES / "tables" / "arc_prize_o3_snippet.md").read_text()
        import json
        defaults = json.loads(
            (FIXTURES / "tables" / "arc_prize_o3_snippet.meta.json").read_text()
        )
        rows = parse_markdown_score_table(text, defaults=defaults)
        self.assertEqual(len(rows), 2)
        self.assertAlmostEqual(rows[0]["score"], 0.757, places=3)
        self.assertEqual(rows[0]["provenance_kind"], "parsed_table")

    def test_dataframe_schema_guard(self):
        rows = load_curated_fixture(FIXTURES / "kaggle_public.json")
        df = rows_to_dataframe(rows)
        self.assertEqual(list(df.columns), list(PUBLIC_RESULTS_SCHEMA.keys()))


class TestLocalAnchor(unittest.TestCase):
    def test_score_uses_task_solved_rate(self):
        """Two test examples on one task: 1/2 items solved → task unsolved."""
        import json
        import pandas as pd

        rows = []
        for test_id, exact in ((1, True), (2, False)):
            rows.append({
                "task_id": "t1", "test_example_id": test_id,
                "is_exact_match": exact,
                "latency_ms": 10.0, "cost_estimate_usd": 0.0,
            })
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "_manifest.json").write_text(json.dumps({
                "run_id": "run1",
                "solver": {"solver_name": "mock:baseline",
                           "solver_family": "llm_direct"},
                "started_at": "2026-07-15T00:00:00+00:00",
            }), encoding="utf-8")
            pd.DataFrame(rows).to_parquet(run_dir / "part-0000.parquet",
                                          index=False)
            row = local_run_to_public_row("run1", runs_dir=Path(tmp))
            self.assertEqual(row["n_tasks"], 1)
            self.assertAlmostEqual(row["score"], 0.0)
            self.assertIn("task_solved_rate=0.000", row["notes"])
            self.assertIn("item_solved_rate=0.500", row["notes"])


if __name__ == "__main__":
    unittest.main()

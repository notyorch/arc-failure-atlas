"""Unit tests for benchmark pack resolve + metadata stamping."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from benchmark_packs import (  # noqa: E402
    BENCHMARK_METADATA_FIELDS,
    BenchmarkPackError,
    attach_benchmark_columns,
    list_registered_packs,
    load_manifest,
    metadata_for_evaluation_items,
    pack_from_manifest,
    require_tasks_dir,
    resolve_pack,
    write_pack_sidecar,
)
from contracts import EVALUATION_RESULTS_SCHEMA  # noqa: E402
from task_loader import build_evaluation_items  # noqa: E402


REPO = Path(__file__).resolve().parent.parent


class TestRegisteredPacks(unittest.TestCase):
    def test_discovers_shipped_packs(self):
        packs = {p.pack_id: p for p in list_registered_packs()}
        self.assertIn("arc_agi_1", packs)
        self.assertIn("arc_agi_2", packs)
        self.assertIn("example_local_pack", packs)
        self.assertEqual(packs["arc_agi_2"].benchmark_name, "ARC-AGI-2")
        self.assertEqual(packs["example_local_pack"].split_name, "sample")

    def test_example_pack_has_tasks(self):
        pack = resolve_pack(pack_id="example_local_pack")
        tasks_dir = require_tasks_dir(pack)
        self.assertGreaterEqual(len(list(tasks_dir.glob("*.json"))), 2)

    def test_empty_tasks_dir_fails_require(self):
        """Empty tasks directories must fail fast (independent of local AGI-2 data)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps({
                    "pack_id": "empty_pack",
                    "benchmark_family": "test",
                    "benchmark_name": "Empty",
                    "benchmark_version": "t1",
                    "task_source": "test",
                    "split_name": "sample",
                    "tasks_dir": "tasks",
                }),
                encoding="utf-8",
            )
            (root / "tasks").mkdir()
            pack = pack_from_manifest(root)
            with self.assertRaises(BenchmarkPackError):
                require_tasks_dir(pack)


class TestResolveByPath(unittest.TestCase):
    def test_resolve_pack_path_to_example(self):
        root = REPO / "benchmark_packs" / "example_local_pack"
        pack = resolve_pack(pack_path=root)
        self.assertEqual(pack.pack_id, "example_local_pack")
        self.assertEqual(pack.benchmark_version, "example-v1")

    def test_unknown_id(self):
        with self.assertRaises(BenchmarkPackError):
            resolve_pack(pack_id="does_not_exist")


class TestMetadataStamp(unittest.TestCase):
    def test_attach_columns(self):
        df = pd.DataFrame({"task_id": ["a", "b"]})
        pack = resolve_pack(pack_id="example_local_pack")
        attach_benchmark_columns(df, pack.metadata())
        for key in BENCHMARK_METADATA_FIELDS:
            self.assertIn(key, df.columns)
            self.assertTrue((df[key] == pack.metadata()[key]).all())

    def test_sidecar_roundtrip(self):
        pack = resolve_pack(pack_id="example_local_pack")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            path = write_pack_sidecar(out, pack, n_tasks=2)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["manifest_kind"], "benchmark_pack")
            self.assertEqual(data["pack_id"], "example_local_pack")
            self.assertEqual(data["task_count"], 2)

    def test_evaluation_items_carry_meta(self):
        tasks = [{
            "task_id": "t1",
            "source_path": "x",
            "train": [{"input": [[1]], "output": [[1]]}],
            "test": [{"example_id": 1, "input": [[0]], "output": [[0]]}],
        }]
        meta = resolve_pack(pack_id="example_local_pack").metadata()
        items = build_evaluation_items(tasks, benchmark_meta=meta)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["benchmark_name"], "Example Local Pack")
        self.assertEqual(items[0]["pack_id"], "example_local_pack")

    def test_schema_includes_benchmark_fields(self):
        for key in BENCHMARK_METADATA_FIELDS:
            self.assertIn(key, EVALUATION_RESULTS_SCHEMA)
            self.assertFalse(EVALUATION_RESULTS_SCHEMA[key]["nullable"])

    def test_metadata_from_frame_columns(self):
        pack = resolve_pack(pack_id="example_local_pack")
        df = pd.DataFrame({"task_id": ["a"], **{k: [v] for k, v in pack.metadata().items()}})
        meta = metadata_for_evaluation_items(df, Path("."), None)
        self.assertEqual(meta["pack_id"], "example_local_pack")


class TestManifestContract(unittest.TestCase):
    def test_manifest_requires_core_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manifest.json").write_text(
                json.dumps({"benchmark_name": "Only Name"}),
                encoding="utf-8",
            )
            with self.assertRaises(BenchmarkPackError):
                pack_from_manifest(root)

    def test_load_manifest_ok(self):
        path = REPO / "benchmark_packs" / "arc_agi_1" / "manifest.json"
        data = load_manifest(path)
        self.assertEqual(data["benchmark_name"], "ARC-AGI-1")


if __name__ == "__main__":
    unittest.main()

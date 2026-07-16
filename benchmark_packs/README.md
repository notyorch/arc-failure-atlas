# Benchmark Packs

Versioned task corpora for the evaluation platform.

Each pack directory contains:

| Path | Role |
| --- | --- |
| `manifest.json` | Identity + provenance (required) |
| `tasks/` | Flat `*.json` ARC task files (default `tasks_dir`) |

| Pack id | Notes |
| --- | --- |
| `arc_agi_1` | Populate `tasks/` yourself, or keep using `data/raw/evaluation/` (legacy) |
| `arc_agi_2` | Local import only — place/symlink public eval JSON under `tasks/` |
| `example_local_pack` | Tiny bundled fixtures for offline tests |

```bash
python src/main.py --list-benchmark-packs
python src/main.py --benchmark-pack example_local_pack
```

Full guide: [`docs/BENCHMARK_PACKS.md`](../docs/BENCHMARK_PACKS.md).

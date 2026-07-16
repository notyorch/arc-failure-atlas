# Tasks directory for pack `arc_agi_2`

Put ARC-AGI-2 **public evaluation** JSON files here (flat `*.json`), or symlink
an external checkout. This repository does **not** ship those task files in git
(see root `.gitignore`).

On a maintainer machine the pack may already hold **120** evaluation tasks
after a local import from the official ARC-AGI-2 `data/evaluation/` tree.

```bash
# from repository root — after you obtain public evaluation JSON elsewhere
cp /path/to/ARC-AGI-2/data/evaluation/*.json benchmark_packs/arc_agi_2/tasks/
# or symlink:
rm -rf benchmark_packs/arc_agi_2/tasks
ln -sfn /absolute/path/to/evaluation_json_dir benchmark_packs/arc_agi_2/tasks
```

Until `*.json` files exist, `python src/main.py --benchmark-pack arc_agi_2`
fails with a clear error. See `docs/BENCHMARK_PACKS.md`.

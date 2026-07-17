# Changelog

All notable changes to ATLAS (ARC Solver Evaluation Platform) are documented
here. The project follows a practical SemVer for an application: **0.x** while
adopter validation is still deepening; public CLI flags and schemas may gain
fields, but renames/removals wait for a major version.

## [0.1.0] — 2026-07-16

First tagged open-source academic release candidate.

### Added

- Local judge for heterogeneous ARC solvers (submission-first, subprocess,
  HTTP, LLM-direct, batch pipeline).
- Versioned benchmark packs (`arc_agi_1`, `arc_agi_2`, `example_local_pack`).
- Decision 21 scoring: `solved_rate` (item), `task_solved_rate` (ARC task),
  `exact_match_rate` (attempt), plus `kaggle_score` (leaderboard-style).
- Failure taxonomy v2 and reproducible Parquet/CSV/Markdown analytics.
- Public results observatory (curated context, not a hosted leaderboard).
- Static local dashboard (`frontend/` + `export_frontend_data.py`).
- Pre-submit standard (Tiers 1–4): Kaggle-strict validation, batch runner,
  sealed holdout, go/no-go certificate (`docs/PRESUBMIT_STANDARD.md`).
- CI: unit tests, isolated smoke, batch round-trip
  (`.github/workflows/ci.yml`).
- Installable console scripts via `pip install -e .` (`atlas-etl`,
  `atlas-evaluate`, `atlas-submission`, `atlas-batch`, `atlas-presubmit`,
  `atlas-analytics`, `atlas-public-results`).
- Frozen JSON Schema contracts under `schemas/`.
- Contribution / security / issue templates and release process docs.

### Evidence (local_pilot_partial)

- Primary AGI-2 corpus pilot: OpenCode `glm-5.2`, n=120
  (`reports/pilot_glm52_agi2_n120.md`).
- Comparative tables/figures under `reports/tables/` and `reports/figures/`.

### Non-goals (unchanged)

- Not an ARC solver or training codebase.
- Not the official ARC Prize / Kaggle leaderboard.
- No auto-download of licensed ARC-AGI-2 corpora.
- No hosted SaaS; you run ATLAS locally.

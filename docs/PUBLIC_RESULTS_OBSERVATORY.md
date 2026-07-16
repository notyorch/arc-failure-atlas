# Public Results Observatory

**What this is:** a lightweight layer that ingests *publicly visible*
ARC / ARC Prize leaderboard context into structured Parquet, then compares
it to a **local platform run** (default: the NVIDIA NIM DeepSeek-V4-Pro
pilot).

**What this is not:** a new benchmark runner, a scraper of private
leaderboards, a claim that local pilots are full-benchmark scores, or a
substitute for the local judge.

The **local judge** (`run_evaluation.py`) is authoritative for your runs.
The **observatory** only ingests curated public fixtures and optional local
anchor rows for **context** (`trust_tier`, `comparison_scope`).

## Why it exists

The team needs one place to ask:

- Where does our local run sit *relative to* publicly discussed results?
- What is official / competition-verified vs self-reported vs preview?
- How do score and cost-per-task relate in public narratives?
- How do we keep provenance instead of pasting numbers into chat?

## Flow

```
fixtures/public_results/*.json (+ optional tables/*.md)
        │  python src/public_results_cli.py sync|compare
        ▼
data/parquet/public_results/leaderboard_rows/   (+ _manifest.json)
        │
        ├── reports/public_results_comparison.md
        └── artifacts/public_results/score_context.png
```

Local anchor (optional / compare default):

```
data/parquet/inference/runs/<run_id>/
  → one row with trust_tier=local_pilot, comparison_scope=local_pilot_partial
```

## CLI

```bash
# Fixtures only → Parquet
python src/public_results_cli.py sync

# Recommended one-shot: fixtures + local pilot + report + chart
python src/public_results_cli.py compare \
  --run-id 20260716T010504Z_nim-deepseek-v4-pro_76a8317f

# Report/chart from existing Parquet
python src/public_results_cli.py report \
  --run-id 20260716T010504Z_nim-deepseek-v4-pro_76a8317f
```

Makefile: `make public-results` (compare against the default pilot run id).

## Sources (v1)

| Source id | Fixture | Notes |
| --- | --- | --- |
| `arc_prize_official` | `fixtures/public_results/arc_prize_official.json` | ARC Prize blog / leaderboard policy figures (o3, GPT-4o baseline) |
| `arc_community` | `arc_community.json` | Competition-adjacent public figures (NVARC, MindsAI) + explicit self-reported placeholder |
| `kaggle_public` | `kaggle_public.json` | Sparse Kaggle-facing numbers corroborated by public writeups — **no private scrape** |
| table snapshot | `tables/arc_prize_o3_snippet.md` | Example deterministic markdown-table parser |

Live HTML scrape is **not** the default. ARC Prize pages are JS-rendered and
change. Humans refresh fixtures when they verify new public pages.

## Trust / verification

| trust_tier | Meaning |
| --- | --- |
| `official_verified` | ARC Prize organizers / official testing writeup |
| `competition_verified` | Contest public/private figures with public corroboration |
| `self_reported` | Author/community claim — treat cautiously |
| `preview` | Incomplete / unofficial / sentinel documentation rows |
| `partial` | Partial coverage (split_type often `partial`) |
| `local_pilot` | This platform's evaluated run |

`verification_status` mirrors the same intent with values used in the schema
(`verified`, `self_reported`, `preview`, `partial`, `unverified`,
`local_platform`).

## What is / is not comparable

**Comparable as context (with caveats):**

- Same `benchmark_name` + similar `comparison_scope` + high trust_tier.
- Cost-per-task when both rows actually report cost.

**Not comparable as a bake-off:**

- `local_pilot_partial` (e.g. 5 tasks) vs `full_benchmark` / `semi_private_100` / `kaggle_contest`.
- ARC-AGI-1 vs ARC-AGI-2 rows.
- Self-reported community scores vs official verified rows without labeling.

The report and chart deliberately call this out. The local pilot is an
**anchor**, not a leaderboard submission.

## Schema

Frozen columns live in `src/public_results/schemas.py`
(`PUBLIC_RESULTS_SCHEMA`, version `1.0.0`). Every row includes
`source_name`, `source_url`, `date_observed`, trust/verification fields,
`comparison_scope`, optional `local_run_id`, and `provenance_kind`.

## Limitations

- Fixtures are curated snapshots — they drift unless refreshed.
- Kaggle private boards are out of scope.
- Cost estimates on local rows may be `$0` when the platform price table
  does not know the NIM model id.
- Sentinel / placeholder rows (self-reported example, Kaggle class note)
  exist to exercise trust tiers — remove or replace when refreshing data.

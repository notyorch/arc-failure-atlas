# Public Results Observatory — Comparison Report

_Generated 2026-07-16 03:27 UTC · schema `1.0.0`_

## What this is

Structured public ARC / ARC Prize leaderboard **context** alongside an optional **local platform run**. Public rows are ingested with provenance and trust metadata. They are **not** re-evaluated here.

## Local pilot anchor

- **submission:** `kimi-k2.6`
- **local_run_id:** `20260716T032633Z_kimi-k2.6_b997534f`
- **score (solved_rate on evaluated items):** 0.0% over n_tasks=5
- **comparison_scope:** `local_pilot_partial` (not a full leaderboard claim)
- **cost_per_task_usd (platform estimate):** 0.0
- **notes:** Local platform pilot/eval run. n_items=5, exact_attempt_rate=0.000, avg_latency_ms=2822.4. NOT a full-benchmark leaderboard score — comparison_scope=local_pilot_partial.

## Honesty rules

- `local_pilot_partial` ≠ `full_benchmark` / `kaggle_contest` / `semi_private_100`.
- Prefer `official_verified` / `competition_verified` over `self_reported` / `preview`.
- Different `benchmark_name` values (ARC-AGI-1 vs ARC-AGI-2) are **not** interchangeable.
- Cost figures use each source's reported units; platform cost estimates may be 0.0 when price tables miss a model.

## Chart

![score context](../artifacts/public_results/score_context.png)

Bars show score %. Local pilot is highlighted; public rows are external context with trust tiers — **not** a controlled A/B.

## Trust-tier summary (public rows only)

| trust_tier | n | mean_score | max_score |
| --- | --- | --- | --- |
| official_verified | 6 | 0.553 | 0.875 |
| competition_verified | 4 | 0.237 | 0.276 |
| self_reported | 1 | 0.420 | 0.420 |

## Public context table

| submission_name | benchmark_name | score_percent | trust_tier | split_type | comparison_scope | cost_per_task_usd | source_name |
| --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI o3 (low-efficiency / high-compute) | ARC-AGI-1 | 87.50 | official_verified | semi_private | semi_private_100 | 4560.00 | arc_prize_official |
| OpenAI o3 (high-efficiency, public eval) | ARC-AGI-1 | 82.80 | official_verified | public | full_benchmark | 167.00 | arc_prize_official |
| OpenAI o3 (high-efficiency) | ARC-AGI-1 | 75.70 | official_verified | semi_private | semi_private_100 | 26.00 | arc_prize_official |
| OpenAI o3 high-eff (table snapshot) | ARC-AGI-1 | 75.70 | official_verified | semi_private | semi_private_100 | 26.00 | arc_prize_official_table_snapshot |
| GPT-4o (context baseline) | ARC-AGI-1 | 5.00 | official_verified | public | full_benchmark | <NA> | arc_prize_official |
| GPT-4o era baseline (table snapshot) | ARC-AGI-1 | 5.00 | official_verified | public | semi_private_100 | <NA> | arc_prize_official_table_snapshot |
| Example self-reported community entry | ARC-AGI-2 | 42.00 | self_reported | public | unknown | <NA> | arc_community |
| NVARC (ARC Prize 2025, public LB) | ARC-AGI-2 | 27.64 | competition_verified | public | kaggle_contest | 0.20 | arc_community |
| NVARC Kaggle public (ARC Prize 2025) | ARC-AGI-2 | 27.64 | competition_verified | public | kaggle_contest | <NA> | kaggle_public |
| NVARC (ARC Prize 2025, private) | ARC-AGI-2 | 24.03 | competition_verified | private | kaggle_contest | 0.20 | arc_community |
| MindsAI (ARC Prize 2025) | ARC-AGI-2 | 15.42 | competition_verified | private | kaggle_contest | <NA> | arc_community |

## Sources in this sync

`arc_community`, `arc_prize_official`, `arc_prize_official_table_snapshot`, `kaggle_public`, `local_platform_run`

## Reproduce

```bash
python src/public_results_cli.py sync
python src/public_results_cli.py compare \
  --run-id 20260716T010504Z_nim-deepseek-v4-pro_76a8317f
```

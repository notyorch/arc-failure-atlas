"""
Public Results Observatory — schemas for externally visible ARC/ARC Prize
leaderboard context.

This layer is NOT the same as local evaluation runs. Public scores come from
heterogeneous sources (official verification, community self-reports,
Kaggle pages, previews). Every row carries provenance + trust metadata so
comparisons stay honest.
"""

from __future__ import annotations

# Schema version stamped into Parquet manifests (not a Parquet column).
PUBLIC_RESULTS_SCHEMA_VERSION = "1.0.0"

# Trust tiers — higher = more official verification.
TRUST_TIERS = (
    "official_verified",   # ARC Prize / organizers verified
    "competition_verified",  # Kaggle private/public with contest rules
    "self_reported",       # community / author claim
    "preview",             # marked preview / incomplete testing
    "partial",             # partial task coverage
    "local_pilot",         # this platform's own evaluated run
)

VERIFICATION_STATUSES = (
    "verified",
    "self_reported",
    "preview",
    "partial",
    "unverified",
    "local_platform",
)

SPLIT_TYPES = (
    "public",
    "semi_private",
    "private",
    "live",
    "preview",
    "partial",
    "unknown",
)

COMPARISON_SCOPES = (
    "full_benchmark",          # claimed full eval set for that benchmark
    "semi_private_100",        # ARC Prize semi-private style
    "kaggle_contest",          # contest compute constraints
    "local_pilot_partial",     # our small local run — NOT full-benchmark comparable
    "unknown",
)

# FROZEN column contract for data/parquet/public_results/leaderboard_rows/
PUBLIC_RESULTS_SCHEMA = {
    "result_id":            {"nullable": False},  # stable hash/id within a sync
    "source_name":          {"nullable": False},
    "source_url":           {"nullable": False},
    "benchmark_name":       {"nullable": False},  # e.g. ARC-AGI-1, ARC-AGI-2
    "submission_name":      {"nullable": False},
    "team_authors":         {"nullable": True},
    "model_family":         {"nullable": True},
    "score":                {"nullable": False},  # 0–1 accuracy / solve rate
    "score_percent":        {"nullable": True},  # 0–100 convenience mirror
    "rank":                 {"nullable": True},
    "cost_per_task_usd":    {"nullable": True},
    "total_cost_usd":       {"nullable": True},
    "date_observed":        {"nullable": False},  # ISO date YYYY-MM-DD
    "verification_status":  {"nullable": False},
    "trust_tier":           {"nullable": False},
    "split_type":           {"nullable": False},
    "comparison_scope":     {"nullable": False},
    "n_tasks":              {"nullable": True},
    "notes":                {"nullable": True},
    "local_run_id":         {"nullable": True},  # set for platform-local rows
    "provenance_kind":      {"nullable": False},  # curated_fixture | parsed_table | local_run
    "ingested_at":          {"nullable": False},
}

PUBLIC_RESULTS_REQUIRED = list(PUBLIC_RESULTS_SCHEMA.keys())

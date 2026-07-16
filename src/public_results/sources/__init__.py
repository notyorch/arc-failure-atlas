"""
Curated source loaders — thin wrappers around fixtures with source labels.

Live HTML scrape is intentionally NOT the default: ARC Prize pages are
JS-heavy and change layout. Humans refresh fixtures when scores move.
"""

from __future__ import annotations

from pathlib import Path

from public_results.ingestion import DEFAULT_FIXTURES_DIR, load_all_fixtures, load_curated_fixture

# Documented source ids → fixture filenames (optional selective sync).
SOURCE_FIXTURES = {
    "arc_prize_official": "arc_prize_official.json",
    "arc_community": "arc_community.json",
    "kaggle_public": "kaggle_public.json",
}


def load_source(source_id: str, fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> list[dict]:
    if source_id not in SOURCE_FIXTURES:
        raise ValueError(
            f"Unknown source {source_id!r}. Known: {sorted(SOURCE_FIXTURES)}"
        )
    return load_curated_fixture(fixtures_dir / SOURCE_FIXTURES[source_id])


def load_default_corpus(fixtures_dir: Path = DEFAULT_FIXTURES_DIR) -> list[dict]:
    return load_all_fixtures(fixtures_dir)

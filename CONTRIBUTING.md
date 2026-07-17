# Contributing to ATLAS

Thanks for helping improve **evaluation infrastructure** for ARC-AGI research.
ATLAS is a local judge — not a solver and not a hosted leaderboard.

## Before you start

1. Read [`README.md`](README.md) (what this is / is not).
2. Read [`docs/CONTRACTS.md`](docs/CONTRACTS.md) (compatibility policy).
3. Prefer opening an issue before large architectural changes.

## Development setup

```bash
git clone <this-repo>
cd arc-failure-atlas
python -m venv .venv && source .venv/bin/activate
pip install -e .
# or: pip install -r requirements.txt
make test
make smoke
```

Existing `python src/<entrypoint>.py` commands remain supported.

## Requirements for a PR

- [ ] `make test` green.
- [ ] `make smoke` green if you touched ETL / evaluation / analytics / adapters.
- [ ] Docs updated when CLI flags, metrics, or contracts change.
- [ ] No secrets, `.env` files, or licensed ARC task corpora.
- [ ] No generated leftovers (`artifacts/batch/`, certificates, holdout JSON).
- [ ] Prefer additive API changes (0.x compatibility policy).

## What we will not merge

- A new ARC solver marketed as part of ATLAS.
- Auto-download of ARC-AGI-2 / private evaluation sets.
- CI jobs that spend third-party API money by default.
- Silent renames of public metrics or schema fields without a major version.

## Code style

- Python 3.11+, standard library + pinned deps in `requirements.txt` /
  `pyproject.toml`.
- Keep CLI help actionable; prefer English docs matching existing tone.
- Decisions that change scoring / fairness go in `src/DECISIONS.md`.

## Release process

See [`docs/RELEASE_PROCESS.md`](docs/RELEASE_PROCESS.md) and
[`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).

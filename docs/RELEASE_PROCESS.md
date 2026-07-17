# Release process

## Versioning

- **0.x** — academic open-source; additive CLI/schema changes allowed.
- **Major** — required for renames/removals of public contracts
  ([`docs/CONTRACTS.md`](CONTRACTS.md)).

Current target: **v0.1.0** (see [`CHANGELOG.md`](../CHANGELOG.md)).

## Steps to cut a release

1. Ensure working tree is intentional; run `make clean-demo`.
2. Complete [`RELEASE_CHECKLIST.md`](RELEASE_CHECKLIST.md) manually.
3. Update `CHANGELOG.md` and bump `version` in `pyproject.toml` if needed.
4. Confirm CI green on the release commit
   ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)).
5. Tag annotated: `git tag -a v0.1.0 -m "ATLAS v0.1.0"` (human does this).
6. Push tag and create a GitHub Release from `CHANGELOG.md` notes.
7. Remind users: clone or `pip install -e .`; mount packs locally; no SaaS.

## Rollback

If a tag ships a regression: publish a patch `0.1.1` rather than rewriting
history of a public tag.

# RELEASE CHECKLIST — Human Verification

Run through this list before tagging a release. Every box is **manual**.
Commands: [`docs/RUNBOOK.md`](RUNBOOK.md) · pre-submit:
[`docs/PRESUBMIT_STANDARD.md`](PRESUBMIT_STANDARD.md).

## A. Code health (offline)

- [ ] Clean working tree: `git status` shows only intentional release changes.
- [ ] No session scratchpads (`tasks.md`, agent notes) in the tree.
- [ ] No generated demo leftovers: `artifacts/batch/`,
      `reports/presubmit_certificate_*.md`, `configs/holdout_*.json`.
- [ ] `make test` → `OK` (currently **170** unit tests).
- [ ] `make smoke` → `SMOKE PASS`.
- [ ] `python src/run_evaluation.py --solver mock-baseline --dry-run`
      prints work list + preview (needs sample data + ETL).

## B. Offline pipeline evidence

- [ ] `make mvp-offline` completes.
- [ ] Run manifest: `manifest_kind=evaluation_run`, `status=completed`,
      nested `solver` snapshot, real `git_commit`.
- [ ] Analytics CSVs: `summary_by_solver.csv`, `solver_failure_matrix.csv`,
      plus failure_mode / task / benchmark summaries; report regenerated.
- [ ] Summary prints `solved_rate`, `task_solved_rate`, and `kaggle_score`.
- [ ] `python scripts/demo_bundle.py` → charts + CSVs under `artifacts/demo/`.

## C. Pre-submit standard (Tiers 1–4)

- [ ] `make batch-example` stages tasks (test GT stripped), writes submission +
      `batch_manifest.json` under `artifacts/batch/example/` (gitignored).
- [ ] `make presubmit-example` emits a certificate under
      `reports/presubmit_certificate_*.md` with a clear verdict
      (`GO` / `GO WITH WARNINGS` / `NO-GO`).
- [ ] `validate-submission --kaggle-strict` on the example submission: every
      pack task, every test example, `attempt_1` **and** `attempt_2`.
- [ ] Optional: `make create-holdout` then certify with `--holdout` (one-shot
      `--reveal-holdout` rejects a second reveal).
- [ ] After checks: `make clean-demo` (or equivalent) so generated batch /
      certificate / holdout files are not left for commit.

## D. Real-provider / external-solver spot checks

- [ ] OpenAI-compatible LLM-direct: small `--limit` run, `execution_error` from auth = 0.
- [ ] Gemini first-run (RUNBOOK §4).
- [ ] Claude first-run (RUNBOOK §5).
- [ ] Unconfigured real providers exit with actionable messages (no stack dump).
- [ ] Cost sanity vs dashboard using `summary_by_solver.csv`.
- [ ] Optional: one `submission_file` or registry subprocess entry dry-run.

## E. Documentation truthfulness

- [ ] README / HANDOFF / reports index match the code.
- [ ] [`EVALUATE_YOUR_SOLVER.md`](EVALUATE_YOUR_SOLVER.md) and
      [`PRESUBMIT_STANDARD.md`](PRESUBMIT_STANDARD.md) describe current CLIs.
- [ ] SOLVER_ADAPTERS / Decision 17–21 match adapter and metric names.
- [ ] `.env.example` matches `src/config.py` (incl. `ATLAS_ATTEMPTS`).
- [ ] `reports/README.md` labels archive vs current evidence.
- [ ] No claim of full-benchmark / leaderboard success without committed evidence.
- [ ] Release status table in README reflects CI + pre-submit status.

## F. CI

- [ ] [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) runs on push/PR:
      `make test`, `make smoke`, batch runner round-trip on `example_local_pack`.
- [ ] CI green on the release commit / tag candidate.

## G. Pilot / smoke evidence (optional pre-release)

- [ ] `reports/smoke_*` and `reports/pilot_*` reviewed for `local_pilot_partial`.
- [ ] AGI-2 pack populates locally on fresh clone (`docs/BENCHMARK_PACKS.md`).
- [ ] `python scripts/export_frontend_data.py` after choosing anchor `run_id`.
- [ ] Frontend: `cd frontend && npm install && npx vite` shows pilot + All Runs.

## H. Non-goals still honored

- [ ] Platform does not ship a new ARC solver.
- [ ] No hardcoded dependency on a single third-party solver tree.
- [ ] No silent CI that spends API money.
- [ ] No auto-download of licensed ARC-AGI-2 corpora.
- [ ] Budget check = wall time on the runner host (not Kaggle hardware parity).

## I. Packaging / contracts (Beyond MVP)

- [ ] `pip install -e .` works; `atlas-evaluate --help` (and siblings) run.
- [ ] Legacy `python src/run_evaluation.py --help` still works without install.
- [ ] [`docs/CONTRACTS.md`](CONTRACTS.md) + `schemas/*.schema.json` match code.
- [ ] [`docs/ADOPTER_JOURNEY.md`](ADOPTER_JOURNEY.md) path still reaches certificate.
- [ ] [`CONTRIBUTING.md`](../CONTRIBUTING.md), [`SECURITY.md`](../SECURITY.md),
      issue templates, and [`RELEASE_PROCESS.md`](RELEASE_PROCESS.md) present.

## J. Tag readiness

- [ ] Version / tag name agreed (`v0.1.0` recommended for first open release).
- [ ] [`CHANGELOG.md`](../CHANGELOG.md) updated for the tag.
- [ ] Follow [`RELEASE_PROCESS.md`](RELEASE_PROCESS.md).
- [ ] Secrets: no keys in history of the release branch; rotate any leaked keys.
- [ ] `git status` clean except intentional release commit(s).
- [ ] No generated local artifacts (`make clean-demo`).

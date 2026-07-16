# RELEASE CHECKLIST — Human Verification

Run through this list before tagging a release. Every box is **manual**.
Commands: `docs/RUNBOOK.md`.

## A. Code health (offline)

- [ ] Clean checkout: `git status` shows expected changes only.
- [ ] `python -m unittest discover -s tests -v` → `OK`.
- [ ] `python scripts/smoke_test.py` → `SMOKE PASS`.
- [ ] `python src/run_evaluation.py --solver mock-baseline --dry-run`
      prints work list + preview (needs sample data + ETL).

## B. Offline pipeline evidence

- [ ] `make mvp-offline` completes.
- [ ] Run manifest: `manifest_kind=evaluation_run`, `status=completed`,
      nested `solver` snapshot, real `git_commit`.
- [ ] Analytics CSVs: `summary_by_solver.csv`, `solver_failure_matrix.csv`,
      plus failure_mode / task summaries; report regenerated.
- [ ] `python scripts/demo_bundle.py` → charts + CSVs under `artifacts/demo/`.

## C. Real-provider / external-solver spot checks

- [ ] OpenAI-compatible LLM-direct: small `--limit` run, `execution_error` from auth = 0.
- [ ] Gemini first-run (RUNBOOK §4).
- [ ] Claude first-run (RUNBOOK §5).
- [ ] Unconfigured real providers exit with actionable messages (no stack dump).
- [ ] Cost sanity vs dashboard using `summary_by_solver.csv`.
- [ ] Optional: one `submission_file` or registry subprocess entry dry-run.

## D. Documentation truthfulness

- [ ] README / HANDOFF / reports index match the code.
- [ ] SOLVER_ADAPTERS / Decision 17–21 match adapter and metric names.
- [ ] `.env.example` matches `src/config.py` (incl. `ATLAS_ATTEMPTS`).
- [ ] `agent_context/repo_map` reflects the tree.
- [ ] `reports/README.md` labels archive vs current evidence.
- [ ] No claim of full-benchmark success without committed evidence.

## F. Pilot / smoke evidence (optional pre-release)

- [ ] `reports/smoke_*` and `reports/pilot_*` reviewed for `local_pilot_partial`.
- [ ] AGI-2 pack populates locally on fresh clone (`docs/BENCHMARK_PACKS.md`).
- [ ] `python scripts/export_frontend_data.py` run after choosing anchor `run_id`.

## E. Non-goals still honored

- [ ] Platform does not ship a new ARC solver.
- [ ] No hardcoded dependency on a single third-party solver tree.
- [ ] No silent CI that spends API money.

.PHONY: help data-sample data-20 etl etl-example-pack list-packs eval-mock eval-gemini eval-claude analytics mvp-offline smoke test demo-bundle list-solvers validate-example-submission public-results frontend-data frontend-dev frontend-build

help:
	@echo "ARC Solver Evaluation Platform — common targets"
	@echo "  make data-sample   copy bundled offline sample tasks"
	@echo "  make data-20       download first 20 ARC-AGI evaluation tasks"
	@echo "  make etl           normalize tasks to Parquet (legacy data/raw)"
	@echo "  make etl-example-pack  ETL from benchmark_packs/example_local_pack"
	@echo "  make list-packs    list registered benchmark packs"
	@echo "  make list-solvers  print the solver registry"
	@echo "  make eval-mock     mock solver evaluation (offline, deterministic)"
	@echo "  make validate-example-submission  validate bundled external-solver example"
	@echo "  make eval-gemini   small real LLM-direct run via Gemini"
	@echo "  make eval-claude   small real LLM-direct run via Claude"
	@echo "  make analytics     build analytics tables + CSVs + reports/mvp_report.md"
	@echo "  make public-results  sync public leaderboard fixtures + compare to local pilot"
	@echo "  make frontend-data   export overview.json for the React UI"
	@echo "  make frontend-dev    run Vite frontend (requires Node)"
	@echo "  make frontend-build  production build of frontend/"
	@echo "  make mvp-offline   full offline pipeline: sample data → report"
	@echo "  make demo-bundle   presentation bundle → artifacts/demo/"
	@echo "  make smoke         end-to-end smoke test in an isolated temp dir"
	@echo "  make test          unit tests"

data-sample:
	python scripts/fetch_arc_data.py --sample

data-20:
	python scripts/fetch_arc_data.py --limit 20

etl:
	python src/main.py

etl-example-pack:
	python src/main.py --benchmark-pack example_local_pack

list-packs:
	python src/main.py --list-benchmark-packs

list-solvers:
	python src/run_evaluation.py --list-solvers

validate-example-submission:
	python src/submission_cli.py validate-submission --path examples/external_solver/submission.json
	python src/submission_cli.py validate-submission --path examples/external_solver/predictions

eval-mock:
	python src/run_evaluation.py --solver mock-baseline --experiment-id mvp-demo

GEMINI_MODEL ?= gemini-2.5-flash
CLAUDE_MODEL ?= claude-opus-4-8

eval-gemini:
	python src/run_evaluation.py --provider gemini --model $(GEMINI_MODEL) --limit 5 --experiment-id real-gemini

eval-claude:
	python src/run_evaluation.py --provider claude --model $(CLAUDE_MODEL) --limit 5 --experiment-id real-claude

analytics:
	python src/build_analytics.py

mvp-offline: data-sample etl eval-mock analytics

public-results:
	python src/public_results_cli.py compare \
		--run-id 20260716T010504Z_nim-deepseek-v4-pro_76a8317f

frontend-data:
	python scripts/export_frontend_data.py

frontend-dev:
	cd frontend && npm run data && npx vite

frontend-build:
	cd frontend && npm run data && npm run build

demo-bundle:
	python scripts/demo_bundle.py

smoke:
	python scripts/smoke_test.py

test:
	python -m unittest discover -s tests -v

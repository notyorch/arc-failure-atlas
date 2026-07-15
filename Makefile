.PHONY: help data-sample data-20 etl infer-mock analytics mvp-offline

help:
	@echo "ARC Failure Atlas — common targets"
	@echo "  make data-sample   copy bundled offline sample tasks"
	@echo "  make data-20       download first 20 ARC-AGI evaluation tasks"
	@echo "  make etl           normalize tasks to Parquet (src/main.py)"
	@echo "  make infer-mock    mock inference run (offline, deterministic)"
	@echo "  make analytics     build analytics tables + reports/mvp_report.md"
	@echo "  make mvp-offline   full offline pipeline: sample data → report"

data-sample:
	python scripts/fetch_arc_data.py --sample

data-20:
	python scripts/fetch_arc_data.py --limit 20

etl:
	python src/main.py

infer-mock:
	python src/run_inference.py --provider mock --model baseline --experiment-id mvp-demo

analytics:
	python src/build_analytics.py

mvp-offline: data-sample etl infer-mock analytics

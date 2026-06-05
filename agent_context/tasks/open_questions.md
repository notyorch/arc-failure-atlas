# Open Questions

## Data and Source Questions
- What is the canonical source for ARC-AGI tasks in this project: local files, a shared dataset path, or a download step?
- Will raw tasks be copied into `data/raw/` or referenced externally?
- Do we need to support multiple ARC variants or only one benchmark format?

## Blockers
- What is the canonical source for ARC-AGI tasks in this project: local files, a shared dataset path, or a download step?
- What should be the canonical task identifier when input files do not include one?
- Which fields are required for every inference record versus optional metadata?
- Should the first CLI target single-task runs, batch runs, or both?
- Which model providers are in scope first: local models, OpenAI, Google AI Studio, Ollama, or a mix?
- How should retries and rate limiting be represented in the output schema?

## Schema Questions
- Should normalized rows store flattened grids as lists, strings, or a nested structure encoded in Parquet?

## Second-Fase Questions
- What folder convention should separate raw, interim, processed, and experiment artifacts?
- Should the project adopt a single Parquet dataset layout or one dataset per experiment?
- Do we want partitioning by model, date, task family, or experiment id?

## Observability Questions
- Which metrics are mandatory from day one: latency, token counts, cost, retries, or all of them?
- What logging format should be used so CLI agents can parse runs easily?
- Where should run logs live relative to analytical artifacts?

## Taxonomy Questions
- What failure categories are considered canonical for the first release?
- Will failure labels be manual, automated, or mixed?
- How do we store evidence for a failure label in a way that is auditable?

## Repository Questions
- Should `src/atlas_arc_failure/ingestion/main.py` remain a temporary script or become the first CLI command?
- Do we want to introduce `__init__.py` files now or later?
- Should `requirements.txt` be consolidated into `pyproject.toml` or kept alongside the current script during migration?

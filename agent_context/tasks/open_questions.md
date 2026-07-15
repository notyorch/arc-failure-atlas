# Open Questions

## Resolved (for reference)
- **Canonical ARC task source:** local JSON files in `data/raw/evaluation/`.
- **Task identifier:** filename stem (`Path.stem`), e.g. `00576224`.
- **Normalized grid storage:** JSON strings in `grid_2d` and `grid_flat` columns (not native Parquet lists).
- **Tasks Parquet partitioning:** Hive layout `split` → `task_id`.
- **Schema enforcement:** frozen `TASKS_PARQUET_SCHEMA` in `src/main.py`, validated before write.

## Data and Source Questions
- Will raw tasks always be copied into `data/raw/` or will some environments reference an external dataset path?
- Do we need to support multiple ARC variants or only the public evaluation format?
- Should we add a download step or script to populate `data/raw/evaluation/` with all ~400 tasks?

## Blockers
- Which model providers are in scope first: local models, OpenAI, Google AI Studio, Ollama, or a mix?
- Should the first CLI target single-task runs, batch runs, or both?
- Which fields are required for every inference record versus optional metadata?
- How should retries and rate limiting be represented in the inference output schema?

## Schema Questions
- Should the error Parquet schema get its own frozen constant and validation guard (like tasks Parquet)?
- When should the inference results schema be formalized and where should it live?

## Second-Phase Questions
- What folder convention should separate experiment artifacts from normalized task data?
- Should inference results use a single Parquet dataset layout or one dataset per experiment?
- Do we want additional partitioning for inference outputs (by model, date, or experiment id)?

## Observability Questions
- Which metrics are mandatory from day one: latency, token counts, cost, retries, or all of them?
- What logging format should be used so CLI agents can parse inference runs easily?
- Where should inference run logs live relative to analytical artifacts?

## Taxonomy Questions
- What failure categories are considered canonical for the first release?
- Will failure labels be manual, automated, or mixed?
- How do we store evidence for a failure label in a way that is auditable?

## Repository Questions
- Should `src/main.py` be split into subpackages now or kept monolithic until inference work starts?
- Should `src/main.py` become the first CLI command, or should a new `cli/` module wrap it?
- Should dependencies move fully into `pyproject.toml` optional extras, or keep `requirements.txt` as the ETL install path?

# Repository Map

## Root Files
- `README.md`: project statement and intended pipeline description.
- `LICENSE`: placeholder text (`TBD`) at the moment.
- `.gitignore`: ignores `data/`, Python bytecode, and local virtual environments.
- `.env.example`: only contains a placeholder comment so far.
- `pyproject.toml`: minimal setuptools project metadata.
- `Makefile`: only a placeholder `help` target.
- `docker-compose.yml`: empty `services` object.
- `src/atlas_arc_failure/ingestion/requirements.txt`: provisional dependency file; it is not the final project layout and is separate from `pyproject.toml` during migration.

## Source Tree
- `src/atlas_arc_failure/ingestion/main.py`: currently the only real Python implementation. It loads a JSON ARC task, flattens grids into rows, and writes a Parquet file.
- `src/atlas_arc_failure/ingestion/requirements.txt`: lists the runtime libraries used by the current script.
- `src/atlas_arc_failure/analytics/`: empty scaffold.
- `src/atlas_arc_failure/cli/`: empty scaffold.
- `src/atlas_arc_failure/inference/`: empty scaffold.
- `src/atlas_arc_failure/observability/`: empty scaffold.
- `src/atlas_arc_failure/prompts/`: empty scaffold.
- `src/atlas_arc_failure/storage/`: empty scaffold.
- `src/atlas_arc_failure/taxonomy/`: empty scaffold.
- `src/atlas_arc_failure/transforms/`: empty scaffold.
- `src/atlas_arc_failure/utils/`: empty scaffold.
- `src/atlas_arc_failure/validation/`: empty scaffold.

## Prompt Scope
- Repo/project prompts live under the top-level `prompts/` tree.
- Agent documentation prompts live under `agent_context/prompts/`.
- These are related but distinct assets and should not be conflated during onboarding.

## Platform and Project Scaffolding
The repository currently contains the following empty or mostly empty top-level areas:
- `agent_context/`
- `artifacts/`
- `configs/`
- `data/`
- `docs/`
- `notebooks/`
- `orchestrations/`
- `paper/`
- `prompts/`
- `scripts/`
- `sql/`
- `tests/`

## Current Architectural Reality
The codebase is not yet modular. There is no separate ingestion library, validation library, storage abstraction, or inference adapter layer. The present implementation is a single-file proof of concept.

## Proposed Map for Next Iteration
A practical first split would be:
- `ingestion`: JSON loading, task parsing, and raw input handling.
- `validation`: grid and schema checks.
- `transforms`: normalization and tabular conversion.
- `storage`: Parquet persistence and artifact paths.
- `inference`: model execution and response capture.
- `observability`: logging, metrics, retries, and run metadata.
- `taxonomy`: failure labeling and analysis categories.
- `cli`: command-line entrypoints.

## Minimal Data Flow
1. Read ARC-AGI task JSON.
2. Normalize grids into tabular rows.
3. Validate shapes, splits, and required fields.
4. Write normalized results to Parquet.
5. Feed the Parquet layer into future analytics and failure-mode reporting.

## Gaps to Track
- Missing package initializers such as `__init__.py` files.
- No canonical CLI entrypoint.
- No tests or fixtures.
- No documented Parquet schema.
- No model/provider configuration files.
- No versioned prompt assets.

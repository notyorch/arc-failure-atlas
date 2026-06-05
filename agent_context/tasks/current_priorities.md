# Current Priorities

## Priority 1: Stabilize the ingestion path
Current code is a single script that reads a JSON task and writes Parquet. The next step is to split that logic into importable functions and a usable CLI entrypoint.

## Priority 2: Define and enforce schemas
The project needs formal contracts for raw tasks, normalized rows, inference outputs, and failure labels. Without schemas, reproducibility and analysis will drift.

## Priority 3: Establish validation and error handling
The current script does not validate input structure or handle malformed tasks. Validation should cover JSON shape, grid consistency, and expected ARC splits.

## Priority 4: Create Parquet output conventions
The project goal depends on Parquet as a stable analysis layer. The team needs a documented layout for output files, partitions, and naming.

## Priority 5: Add observability and run metadata
Inference and batch execution need latency, retry, cost, and run identifiers. These should be captured from the first real experiments.

## Priority 6: Version prompts and evaluation sets
The `prompts/` tree exists as scaffolding, but there is no versioned prompt registry yet. That work is required before model comparison becomes reliable.

## Priority 7: Add tests and fixtures
There are no tests in the repository today. The project needs unit tests for JSON parsing, normalization, and schema checks, plus fixtures for representative ARC tasks.

## Current Bottlenecks
- No package structure with importable modules and package initializers.
- No centralized configuration for models or environments.
- No documented taxonomy implementation.
- No analysis notebooks or reporting assets yet.

## Near-Term Outcome
The repository should reach a state where a developer or CLI agent can ingest one ARC task, validate it, transform it, write Parquet, and trace the run end to end.

## Exit Criteria for This Slice
- One representative ARC JSON task can be processed end to end without manual file edits.
- The output Parquet file follows a documented schema and can be traced back to its input and run context.

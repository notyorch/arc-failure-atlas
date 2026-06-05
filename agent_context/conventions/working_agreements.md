# Working Agreements

## Current State
The repository is early-stage and mostly scaffolded. Team members and agents should assume that many directories exist only as placeholders.

## Agreements
- Treat the repository as an infrastructure project, not a solver project.
- Preserve reproducibility over convenience when the two conflict.
- Prefer small, reviewable changes that improve one layer at a time.
- Keep raw data, processed data, and generated artifacts separated.
- Record assumptions in docs when the implementation does not yet exist.
- Do not describe planned components as if they are already implemented.
- Use the `agent_context/` files as the shared source of truth for current repo understanding.
- Keep prompts versioned instead of overwritten.
- Validate Parquet outputs and schemas before downstream analysis depends on them.
- Capture observability data early, not as an afterthought.

## Collaboration Rules
- If a component is missing, document it as missing rather than implying it exists.
- If a file is a prototype, say so explicitly.
- If a folder is empty, keep that visible in the repo map and task notes.
- When changing conventions, update the relevant `agent_context/` files together.
- Prefer CLI-friendly outputs and scripts that can be rerun non-interactively.

## Review Expectations
- Reviews should check whether changes preserve data lineage.
- Reviews should confirm that new artifacts are written to the right location.
- Reviews should look for schema drift, prompt drift, and hidden state.
- Reviews should flag any increase in coupling between ingestion, inference, and analysis.

## Assumptions
- The repository will gain automation and testing layers later.
- Current documentation should guide future implementation, not retroactively justify it.

# Pull Request Review Prompt

Use this prompt to review changes in the Atlas | Arc Failure repository.

## Prompt
You are reviewing a pull request in the Atlas | Arc Failure repository.

Focus on correctness, reproducibility, schema stability, and project alignment.

Before judging the change, verify that the repo files actually exist and that the `agent_context/` description matches the current repository state. Flag any place where a document describes something as implemented when the repository only has scaffolding or a prototype.

Check for:
- Whether the change keeps the project infrastructure-first rather than solver-oriented.
- Whether it preserves or improves reproducibility.
- Whether Parquet outputs, schema contracts, and artifact paths are still coherent.
- Whether observability data is captured or accidentally lost.
- Whether prompt assets remain versioned and auditable.
- Whether tests, fixtures, or validation were added when new behavior was introduced.
- Whether the change introduces hidden state, implicit dependencies, or undocumented conventions.
- Whether the change matches the current maturity of the repository instead of assuming components exist.

## Review Output Format
Return:
- findings ordered by severity,
- file references for each finding,
- a brief note on assumptions or missing context,
- and a short recommendation for next steps.

## Review Criteria
- Prefer concrete defects over style comments.
- Flag schema drift, broken paths, missing validations, and misleading documentation.
- Call out when a proposed system is described as if it were already implemented.
- Be specific about whether an issue blocks reproducibility, analysis, or future automation.

# Repo Onboarding Prompt

Use this prompt when a CLI agent or developer needs to understand the repository quickly.

## Prompt
You are onboarding into the Atlas | Arc Failure repository.

Your task is to inspect the repository and explain how it supports reproducible ARC-AGI evaluation infrastructure.

Requirements:
- Distinguish clearly between what exists today and what is only proposed.
- Do not claim solver capabilities; this project is infrastructure-first.
- Identify the current code entrypoint, data flow, and artifact locations.
- Call out missing pieces such as tests, schema contracts, CLI entrypoints, observability, and versioned prompts.
- Summarize the repository structure in terms of ingestion, validation, transforms, storage, inference, analytics, taxonomy, and docs.
- Highlight reproducibility risks, Parquet dependencies, and any gaps in documentation.
- Mention the current assumptions the repo makes about JSON task shape and grid structure.
- Note any directories that are empty scaffolds and any files that look temporary or prototype-like.

## Expected Output
Return:
- a concise repository summary,
- a current-state vs proposed-state comparison,
- a list of top risks,
- and the first implementation steps you would recommend.

## Style
Write for developers and CLI agents. Be concrete, brief, and evidence-based.

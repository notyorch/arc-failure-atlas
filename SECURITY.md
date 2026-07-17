# Security policy

## Supported versions

The `main` branch and the latest `0.x` tag receive security fixes.

## What to report

Please report privately (or via a private GitHub security advisory if enabled):

- Accidental inclusion of API keys, tokens, or credentials in the repo.
- Path traversal or command-injection issues in batch / subprocess adapters.
- Ways to leak ground-truth test outputs through staged task JSON or wire
  contracts (`to_wire()` must never serialize `expected_output`).

## What is out of scope

- Model jailbreaks / prompt injection against third-party LLM providers.
- Weaknesses of user-supplied solver projects under `atlas-batch`.
- Scores that look “too low” — ATLAS is a judge, not a solver.

## Local secrets

- Never commit `.env` (gitignored). Use `.env.example` as a template.
- The pipeline reads `os.environ` only; it does not auto-load dotenv files.
- Rotate any key that was pasted into chat, CI logs, or terminal history.

## Corpora

ATLAS does not ship licensed ARC-AGI-2 evaluation JSON. Users who mount
upstream data must follow the upstream license. Do not open PRs that add
full evaluation corpora to git.

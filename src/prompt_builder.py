"""
Versioned prompt construction for the LLM-direct solver family.

This module is intentionally narrow: it owns ONLY the prompt registry used
by `LLMDirectSolver` (src/solvers.py). Task ingestion lives in
src/task_loader.py; other solver families never touch prompts at all.

Prompt versions live in the PROMPT_BUILDERS registry. Versions are
append-only: never edit the text of a released version — add a new entry
(e.g. "arc_grid_v2") so stored rows always point at the exact prompt that
produced them. The version string is stamped on every result row and in
every run manifest. Same train examples + test input + version ⇒
byte-identical prompt.

Prompt contract (arc_grid_v1 / arc_grid_v2): the model must reply with ONLY
a JSON 2D integer array — the parser in grid_parser.py is the other half of
this contract. v2 strengthens the "no chain-of-thought" instruction for
reasoning models that otherwise dump intermediate arrays.
"""

import config
from grid_parser import serialize_grid

PROMPT_VERSION_DEFAULT = "arc_grid_v1"

_PROMPT_HEADER = (
    "You are solving an ARC (Abstraction and Reasoning Corpus) puzzle.\n"
    "Each grid is a JSON 2D array of integers 0-9. Infer the transformation "
    "rule from the training examples, then apply it to the test input.\n"
)
_PROMPT_FOOTER = (
    "\nReply with ONLY the test output grid as a JSON 2D array of integers. "
    "No explanation, no code fences, no extra text."
)

_PROMPT_FOOTER_V2 = (
    "\nIMPORTANT: Do not write step-by-step reasoning, analysis, or intermediate "
    "grids. Your entire reply must be exactly one JSON 2D array of integers "
    "0-9 (the test output). No prose, no markdown, no code fences."
)


def build_prompt(train_examples: list, test_input: list) -> str:
    """Renders the arc_grid_v1 prompt for one test input. FROZEN — released
    prompt text is never edited; new wording means a new registry entry."""
    parts = [_PROMPT_HEADER]
    for i, example in enumerate(train_examples, start=1):
        parts.append(
            f"\nExample {i}\n"
            f"Input: {serialize_grid(example['input'])}\n"
            f"Output: {serialize_grid(example['output'])}\n"
        )
    parts.append(f"\nTest\nInput: {serialize_grid(test_input)}\n")
    parts.append(_PROMPT_FOOTER)
    return "".join(parts)


def build_prompt_v2(train_examples: list, test_input: list) -> str:
    """arc_grid_v2 — same examples, stricter no-reasoning footer."""
    parts = [_PROMPT_HEADER]
    for i, example in enumerate(train_examples, start=1):
        parts.append(
            f"\nExample {i}\n"
            f"Input: {serialize_grid(example['input'])}\n"
            f"Output: {serialize_grid(example['output'])}\n"
        )
    parts.append(f"\nTest\nInput: {serialize_grid(test_input)}\n")
    parts.append(_PROMPT_FOOTER_V2)
    return "".join(parts)


# Registry: prompt version string -> renderer(train_examples, test_input).
# Append-only (see module docstring).
PROMPT_BUILDERS = {
    "arc_grid_v1": build_prompt,
    "arc_grid_v2": build_prompt_v2,
}


def get_prompt_builder(version: str):
    """Resolve a prompt version to its renderer, with a readable error."""
    config.validate_choice(version, PROMPT_BUILDERS, "prompt-version",
                           env_name=config.ENV_PROMPT_VERSION)
    return PROMPT_BUILDERS[version]

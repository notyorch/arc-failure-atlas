"""
Unified configuration for the pipeline: environment variables + CLI flags.

Single strategy, applied by every entrypoint:

    CLI flag  >  ATLAS_* environment variable  >  built-in default

Provider credentials add one more level: a provider-specific variable
(OPENAI_API_KEY, GEMINI_API_KEY, ANTHROPIC_API_KEY...) wins over the generic
ATLAS_API_KEY, so an already-exported provider key keeps working unchanged.
Providers log WHICH variable supplied a value (never the value itself).

Environment variables and their scope:

    ATLAS_SOLVER            run_evaluation  default solver registry entry
    ATLAS_PROVIDER          run_evaluation  default LLM execution backend (mock)
    ATLAS_MODEL             run_evaluation  default model name (llm_direct family)
    ATLAS_API_KEY           providers       generic API key fallback
    ATLAS_BASE_URL          providers       generic endpoint override
    ATLAS_PROMPT_VERSION    run_evaluation  default prompt version (llm_direct)
    ATLAS_ATTEMPTS          run_evaluation  attempts per item for llm_direct
                            (ARC pass@k; ARC-AGI official is 2, default 1)
    ATLAS_EXPERIMENT_ID     run_evaluation / build_analytics
    ATLAS_INPUT_PATH        run_evaluation  tasks-Parquet directory
    ATLAS_OUTPUT_ROOT       main / run_evaluation / build_analytics
                            root of the derived-data tree (default data/parquet)
    ATLAS_BENCHMARK_PACK    main / run_evaluation  registered pack id
                            (e.g. arc_agi_2, example_local_pack)
    ATLAS_TIMEOUT_S         providers/solvers  per-call timeout (default 600)
    ATLAS_MAX_OUTPUT_TOKENS providers       output-token cap where the API
                                            requires/accepts one (default 16000)

Notes:
  - Nothing here auto-loads a .env file. Export variables in your shell
    (see .env.example); the pipeline reads os.environ only, so a stray
    .env can never silently change a run.
  - ATLAS_OUTPUT_ROOT may be relative; it resolves against the current
    working directory (the smoke test relies on this for isolation).
    Prefer an absolute path when running from other directories.
  - This module is stdlib-only so tests and providers stay import-light.
"""

import os
from pathlib import Path
from typing import Optional

# Canonical variable names — import these instead of retyping strings.
ENV_SOLVER = "ATLAS_SOLVER"
ENV_PROVIDER = "ATLAS_PROVIDER"
ENV_MODEL = "ATLAS_MODEL"
ENV_API_KEY = "ATLAS_API_KEY"
ENV_BASE_URL = "ATLAS_BASE_URL"
ENV_PROMPT_VERSION = "ATLAS_PROMPT_VERSION"
ENV_ATTEMPTS = "ATLAS_ATTEMPTS"
ENV_EXPERIMENT_ID = "ATLAS_EXPERIMENT_ID"
ENV_INPUT_PATH = "ATLAS_INPUT_PATH"
ENV_OUTPUT_ROOT = "ATLAS_OUTPUT_ROOT"
ENV_BENCHMARK_PACK = "ATLAS_BENCHMARK_PACK"
ENV_TIMEOUT_S = "ATLAS_TIMEOUT_S"
ENV_MAX_OUTPUT_TOKENS = "ATLAS_MAX_OUTPUT_TOKENS"

DEFAULT_PROVIDER = "mock"
DEFAULT_EXPERIMENT_ID = "dev"
DEFAULT_ATTEMPTS = 1
DEFAULT_TIMEOUT_S = 600.0
DEFAULT_MAX_OUTPUT_TOKENS = 16000


class ConfigError(ValueError):
    """Invalid or missing configuration. The message tells the user what to
    set and where — always safe to print to the terminal."""


def env_str(name: str, default: Optional[str] = None) -> Optional[str]:
    """String env var; empty/whitespace-only values count as unset."""
    value = os.environ.get(name, "").strip()
    return value if value else default


def env_path(name: str, default: Optional[Path] = None) -> Optional[Path]:
    """Path env var; empty values count as unset. No existence check here —
    callers validate existence where it matters, with a better message."""
    value = env_str(name)
    return Path(value) if value else default


def env_float(name: str, default: float) -> float:
    """Positive float env var, with a readable error on garbage input."""
    raw = env_str(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(
            f"{name} must be a number, got {raw!r}. "
            f"Unset it to use the default ({default})."
        )
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {raw!r}.")
    return value


def env_int(name: str, default: int) -> int:
    """Positive integer env var, with a readable error on garbage input."""
    raw = env_str(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(
            f"{name} must be an integer, got {raw!r}. "
            f"Unset it to use the default ({default})."
        )
    if value <= 0:
        raise ConfigError(f"{name} must be positive, got {raw!r}.")
    return value


def resolve(cli_value, env_name: str, default=None):
    """CLI flag > environment variable > default (for string-like settings)."""
    if cli_value is not None:
        return cli_value
    return env_str(env_name, default)


def first_env(*names: str):
    """
    First set variable among `names`, as (name, value) — or (None, None).
    Returning the NAME lets callers log which variable supplied a credential
    without ever logging the credential itself.
    """
    for name in names:
        value = env_str(name)
        if value:
            return name, value
    return None, None


def output_root() -> Optional[Path]:
    """ATLAS_OUTPUT_ROOT as a Path, or None when unset (callers keep their
    stage-specific default anchoring in that case)."""
    return env_path(ENV_OUTPUT_ROOT)


def provider_timeout(legacy_env: Optional[str] = None) -> float:
    """
    HTTP timeout for provider calls: provider-specific legacy variable
    (e.g. OPENAI_TIMEOUT_S) > ATLAS_TIMEOUT_S > default. Large hosted models
    routinely need several minutes per call.
    """
    if legacy_env:
        raw = env_str(legacy_env)
        if raw is not None:
            return env_float(legacy_env, DEFAULT_TIMEOUT_S)
    return env_float(ENV_TIMEOUT_S, DEFAULT_TIMEOUT_S)


def max_output_tokens() -> int:
    """Output-token cap passed to providers whose API takes one."""
    return env_int(ENV_MAX_OUTPUT_TOKENS, DEFAULT_MAX_OUTPUT_TOKENS)


def attempts() -> int:
    """
    Attempts per evaluation item for the llm_direct family (independent
    samples of the same prompt → up to N candidate grids). ARC-AGI official
    scoring is pass@2; keep the default at 1 so single-attempt runs and the
    offline smoke test are unchanged unless explicitly opted in.
    """
    return env_int(ENV_ATTEMPTS, DEFAULT_ATTEMPTS)


def validate_choice(value: str, valid, what: str, env_name: Optional[str] = None) -> str:
    """Membership check with a message that names the offending setting."""
    if value in valid:
        return value
    source = f" (check --{what} or ${env_name})" if env_name else ""
    raise ConfigError(
        f"Unknown {what} {value!r}{source}. Available: {sorted(valid)}"
    )

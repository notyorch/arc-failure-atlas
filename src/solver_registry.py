"""
Solver registry — where the platform learns which solvers exist and how to
run them.

Two layers, merged at load time:
  1. BUILTIN_ENTRIES (this module): the always-available offline mock
     configurations used by smoke tests and demos.
  2. configs/solvers.json (optional, human-edited): external solvers —
     submission artifacts (recommended), subprocess CLIs, HTTP services,
     and ad-hoc LLM configurations. Reference entries for the local corpus
     may ship disabled until a human wires path/command.

Entry shape (JSON) — minimal fields preferred:

    "my-solver": {
        "adapter":  "submission_file" | "submission_dir" | "subprocess"
                    | "subprocess_cli" | "http" | "in_process",
        // "adapter_type" is accepted as an alias of "adapter"
        "path":     "...",          // submission_file / submission_dir
        "command":  ["..."],        // subprocess / subprocess_cli
        "attempts": 2,              // in_process only: pass@k samples (default 1)
        "family":   free-form label,
        "version":  solver version string,
        "enabled":  true|false,
        "notes":    free text
    }

Recommended for external authors (lowest friction first):
  1. submission_file  — point at their submission.json
  2. submission_dir   — point at a folder of per-task prediction JSONs
  3. subprocess_cli   — wrap an existing CLI (stdin/stdout wire contract)
  4. in_process/http  — only when they already expose Python/HTTP APIs

Never put secrets in registry entries.
"""

import json
from pathlib import Path
from typing import Optional

from config import ConfigError
from solvers import (
    BaseSolver,
    CommandSolver,
    HTTPSolver,
    LLMDirectSolver,
    SolverError,
    SubmissionDirSolver,
    SubmissionFileSolver,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = REPO_ROOT / "configs" / "solvers.json"

# Canonical adapter names stored on rows / manifests.
ADAPTER_TYPES = (
    "in_process", "subprocess", "http", "submission_file", "submission_dir",
)

# Human-friendly aliases accepted in configs/solvers.json.
ADAPTER_ALIASES = {
    "subprocess_cli": "subprocess",
    "cli": "subprocess",
    "submission": "submission_file",
}


def normalize_adapter_name(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    name = str(raw).strip()
    return ADAPTER_ALIASES.get(name, name)


def resolve_entry_adapter(entry: dict) -> Optional[str]:
    """Prefer `adapter`, fall back to `adapter_type` (docs/examples alias)."""
    raw = entry.get("adapter", entry.get("adapter_type"))
    return normalize_adapter_name(raw)


BUILTIN_ENTRIES = {
    "mock-baseline": {
        "adapter": "in_process", "family": "llm_direct",
        "provider": "mock", "model": "baseline", "version": "builtin",
        "enabled": True,
        "notes": "Deterministic offline pipeline exerciser (hash-bucketed "
                 "behaviors). Demonstrates the platform, not solver skill.",
    },
    "mock-large": {
        "adapter": "in_process", "family": "llm_direct",
        "provider": "mock", "model": "mock-large", "version": "builtin",
        "enabled": True,
        "notes": "Second deterministic mock configuration so multi-solver "
                 "comparisons work offline.",
    },
    "example-submission-file": {
        "adapter": "submission_file", "family": "submission",
        "version": "example", "enabled": True,
        "path": "examples/external_solver/submission.json",
        "notes": "Bundled Kaggle-style example for QUICKSTART_EXTERNAL_SOLVER.",
    },
    "example-submission-dir": {
        "adapter": "submission_dir", "family": "submission",
        "version": "example", "enabled": True,
        "path": "examples/external_solver/predictions",
        "notes": "Bundled per-task prediction directory example.",
    },
}


def load_registry(path: Optional[Path] = None) -> dict:
    """Built-in entries + configs/solvers.json (when present), validated.
    Returns {name: entry_dict}. Raises ConfigError with readable messages."""
    entries = {name: dict(entry) for name, entry in BUILTIN_ENTRIES.items()}

    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    if not registry_path.exists():
        return entries

    try:
        with open(registry_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Could not read solver registry {registry_path}: {exc}")

    solvers = data.get("solvers")
    if not isinstance(solvers, dict):
        raise ConfigError(
            f"Solver registry {registry_path} must contain a top-level "
            '"solvers" object mapping name -> entry.'
        )

    for name, entry in solvers.items():
        if name in entries:
            raise ConfigError(
                f"Registry entry '{name}' in {registry_path} collides with a "
                "built-in solver name. Rename the entry."
            )
        if not isinstance(entry, dict):
            raise ConfigError(f"Registry entry '{name}' must be an object.")
        adapter = resolve_entry_adapter(entry)
        if adapter not in ADAPTER_TYPES:
            raise ConfigError(
                f"Registry entry '{name}' has unknown adapter {adapter!r}. "
                f"Available: {list(ADAPTER_TYPES)} "
                f"(aliases: {sorted(ADAPTER_ALIASES)})"
            )
        normalized = dict(entry)
        normalized["adapter"] = adapter
        entries[name] = normalized
    return entries


def _resolve_artifact_path(raw_path) -> Path:
    """Resolve registry paths: absolute as-is; relative against repo root."""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return (REPO_ROOT / path).resolve()


def create_solver(name: str, registry: dict) -> BaseSolver:
    """Instantiate the adapter for a registry entry. Raises ConfigError /
    SolverError / ProviderConfigError with actionable messages."""
    entry = registry.get(name)
    if entry is None:
        available = ", ".join(sorted(registry)) or "(none)"
        raise ConfigError(
            f"Unknown solver '{name}'. Registered solvers: {available}. "
            "Add entries in configs/solvers.json "
            "(see docs/QUICKSTART_EXTERNAL_SOLVER.md)."
        )
    if not entry.get("enabled", True):
        notes = entry.get("notes", "no notes")
        raise ConfigError(
            f"Solver '{name}' is registered but disabled — it is a reference "
            f"entry that a human must wire up first. Notes: {notes} "
            "(see docs/QUICKSTART_EXTERNAL_SOLVER.md, then set "
            '"enabled": true).'
        )

    adapter = resolve_entry_adapter(entry) or entry.get("adapter")
    family = entry.get("family", "external")
    version = entry.get("version", "unversioned")

    if adapter == "in_process":
        for required in ("provider", "model"):
            if not entry.get(required):
                raise ConfigError(
                    f"Solver '{name}' (in_process) is missing '{required}'."
                )
        return LLMDirectSolver(
            provider_name=entry["provider"], model_name=entry["model"],
            prompt_version=entry.get("prompt_version") or "arc_grid_v1",
            name=name, version=version,
            n_attempts=int(entry.get("attempts", 1)),
        )
    if adapter == "subprocess":
        if not entry.get("command"):
            raise ConfigError(
                f"Solver '{name}' (subprocess / subprocess_cli) is missing "
                "'command' (argv list)."
            )
        return CommandSolver(
            name=name, command=entry["command"], family=family,
            version=version, timeout_s=entry.get("timeout_s"),
            workdir=entry.get("workdir"),
        )
    if adapter == "http":
        if not entry.get("url"):
            raise ConfigError(f"Solver '{name}' (http) is missing 'url'.")
        return HTTPSolver(
            name=name, url=entry["url"], family=family, version=version,
            timeout_s=entry.get("timeout_s"),
        )
    if adapter == "submission_file":
        if not entry.get("path"):
            raise ConfigError(f"Solver '{name}' (submission_file) is missing 'path'.")
        return SubmissionFileSolver(
            name=name, path=_resolve_artifact_path(entry["path"]), version=version,
        )
    if adapter == "submission_dir":
        if not entry.get("path"):
            raise ConfigError(f"Solver '{name}' (submission_dir) is missing 'path'.")
        return SubmissionDirSolver(
            name=name, path=_resolve_artifact_path(entry["path"]), version=version,
        )
    raise ConfigError(f"Solver '{name}': unhandled adapter '{adapter}'.")


def format_registry(registry: dict) -> str:
    """Human-readable listing for `run_evaluation.py --list-solvers`."""
    lines = [f"{'NAME':24} {'ADAPTER':16} {'FAMILY':14} {'ENABLED':8} NOTES"]
    for name in sorted(registry):
        entry = registry[name]
        adapter = resolve_entry_adapter(entry) or entry.get("adapter", "?")
        lines.append(
            f"{name:24} {adapter:16} "
            f"{entry.get('family', '?'):14} "
            f"{str(entry.get('enabled', True)):8} "
            f"{(entry.get('notes') or '')[:70]}"
        )
    return "\n".join(lines)

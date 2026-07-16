"""
Deprecated compatibility shim for the former model-inference entrypoint.

Prefer the solver-oriented orchestrator:

    python src/run_evaluation.py --solver mock-baseline
    python src/run_evaluation.py --provider mock --model baseline

This module forwards to `run_evaluation.main` with the same CLI surface
(`--provider` / `--model` still work). New code and docs should not import
or invoke this file.
"""

from __future__ import annotations

import sys
import warnings

warnings.warn(
    "src/run_inference.py is deprecated; use src/run_evaluation.py "
    "(same --provider/--model flags; prefer --solver <registry-name>).",
    DeprecationWarning,
    stacklevel=1,
)

from run_evaluation import main  # noqa: E402


if __name__ == "__main__":
    main()
    sys.exit(0)

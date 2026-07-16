"""
Standard Solver Interface — the platform's one abstraction over ARC solvers.

Every solving system (frontier LLM pipeline, local model, DSL/program
search, agentic workflow, neuro-symbolic hybrid...) is evaluated as a BLACK
BOX behind this contract:

    result: SolverResult = solver.solve(task: SolverTask)

The platform owns everything around the box: task ingestion, orchestration,
parsing, validation, deterministic scoring, failure taxonomy, metrics,
Parquet/CSV/report generation, and replay manifests. Adapters exist so
heterogeneous solvers can meet the contract without evaluator changes:

    LLMDirectSolver      in_process       prompt → LLM backend (providers.py)
    CommandSolver        subprocess       task JSON on stdin → output on stdout
                                          (registry alias: subprocess_cli)
    HTTPSolver           http             POST <url> with task JSON envelope
    SubmissionFileSolver submission_file  score a Kaggle-style submission.json
    SubmissionDirSolver  submission_dir   score a directory of per-task JSONs

Preferred external onboarding is submission-first — see
docs/QUICKSTART_EXTERNAL_SOLVER.md.

Wire contract (subprocess stdin / HTTP request body) — classic ARC shape,
one test input per call:

    {"task_id": "...", "test_example_id": 1,
     "train": [{"input": [[...]], "output": [[...]]}, ...],
     "test":  [{"input": [[...]]}]}

GROUND-TRUTH ISOLATION: SolverTask carries `expected_output` only so the
scoring stage (and the deterministic mock backend) can reach it.
`to_wire()` NEVER serializes it, and no adapter may forward it to a real
solver. This is the platform's fairness invariant.

Solver output contract (subprocess stdout / HTTP response body), most
structured first:
    {"attempts": [grid, grid], "metadata": {...}}   up to 2 attempts
    {"prediction": grid, "metadata": {...}}         single attempt
    any other text                                  scanned for the first
                                                    valid ARC grid (same
                                                    parser as LLM output)
Validation, scoring, and failure classification are identical for all
solver families — that is what makes results comparable.
"""

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import config
from prompt_builder import PROMPT_VERSION_DEFAULT, get_prompt_builder
from providers import (
    STATUS_ERROR,
    STATUS_OK,
    get_provider,
    post_json,
)


class SolverError(RuntimeError):
    """Solver adapter cannot be constructed (bad registry entry, missing
    file, malformed submission...). Message is human-readable."""


@dataclass
class SolverTask:
    """One evaluation item: a full ARC task with exactly one test input."""
    task_id: str
    test_example_id: int
    train: list                      # [{"input": grid, "output": grid}, ...]
    test_input: list
    # For the scoring stage and the deterministic mock backend ONLY.
    # Never serialized by to_wire(); adapters must not leak it.
    expected_output: Optional[list] = None
    source_task_partition: str = ""

    def to_wire(self) -> dict:
        """External representation sent to subprocess/HTTP solvers.
        Deliberately excludes expected_output (ground-truth isolation)."""
        return {
            "task_id": self.task_id,
            "test_example_id": self.test_example_id,
            "train": [{"input": ex["input"], "output": ex["output"]}
                      for ex in self.train],
            "test": [{"input": self.test_input}],
        }


@dataclass
class SolverAttempt:
    """One candidate answer. Either raw text (to be parsed) or an already-
    structured grid object (to be validated) — never both required."""
    attempt: int                     # 1-based
    raw_output: Optional[str] = None
    grid: Optional[list] = None      # structured prediction, pre-parse


@dataclass
class SolverResult:
    """The normalized outcome of one solver call on one SolverTask."""
    status: str                      # STATUS_OK | STATUS_ERROR
    attempts: list = field(default_factory=list)   # [SolverAttempt, ...]
    error_message: Optional[str] = None
    latency_ms: float = 0.0          # harness/backend wall clock for the call
    cost_estimate_usd: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    prompt_text: Optional[str] = None        # llm_direct family only
    metadata: Optional[dict] = None          # free-form, JSON-serializable


class BaseSolver:
    """
    Minimal interface every adapter implements.

    Identity attributes are stamped on every result row and into the run
    manifest; keep them stable for a given configuration so runs stay
    comparable across time.
    """

    name: str = "base"
    family: str = "unknown"          # e.g. llm_direct, dsl_search, external
    version: str = "unversioned"
    execution_mode: str = "in_process"   # see contracts.EXECUTION_MODES

    def solve(self, task: SolverTask) -> SolverResult:
        raise NotImplementedError

    def describe(self) -> dict:
        """Config snapshot for the run manifest. MUST NOT contain secrets —
        adapters only ever reference credentials by environment variable
        name, never by value."""
        return {
            "solver_name": self.name,
            "solver_family": self.family,
            "solver_version": self.version,
            "execution_mode": self.execution_mode,
        }


# ---------------------------------------------------------------------------
# In-process adapter: single-prompt LLM solvers (providers.py backends)
# ---------------------------------------------------------------------------

class LLMDirectSolver(BaseSolver):
    """
    The platform's built-in solver family: render a versioned prompt from
    the task, call an LLM execution backend, return the completion text.
    The deterministic offline configuration (provider=mock) is what smoke
    tests and demos run.

    Multi-attempt (pass@k): `n_attempts` independent samples of the SAME
    prompt are drawn per item, each becoming one candidate grid. ARC-AGI is
    officially scored pass@2 (an item counts solved when ANY attempt matches
    — see build_analytics `solved_rate`). The default is 1 so single-sample
    runs are unchanged; set `--attempts 2` (or ATLAS_ATTEMPTS) for pass@2.
    Latency and cost are summed across the calls and stamped once per item;
    a call that errors is skipped, and the item errors only if EVERY sample
    failed (partial success still yields the attempts that came back).
    """

    family = "llm_direct"
    execution_mode = "in_process"

    def __init__(self, provider_name: str, model_name: str,
                 prompt_version: str = PROMPT_VERSION_DEFAULT,
                 name: Optional[str] = None, version: str = "unversioned",
                 n_attempts: int = 1):
        self.provider_name = provider_name
        self.model_name = model_name
        self.prompt_version = prompt_version
        self.n_attempts = max(1, int(n_attempts))
        self._render = get_prompt_builder(prompt_version)  # fail fast
        self.provider = get_provider(provider_name, model_name)  # fail fast
        self.name = name or f"{provider_name}:{model_name}"
        self.version = version

    def solve(self, task: SolverTask) -> SolverResult:
        prompt = self._render(task.train, task.test_input)
        # `context` is consumed ONLY by the deterministic mock backend;
        # real providers ignore it by contract (see providers.py docstring).
        context = {
            "task_id": task.task_id,
            "test_input": task.test_input,
            "expected_output": task.expected_output,
        }
        attempts = []
        total_latency = 0.0
        total_cost = 0.0
        input_tokens = None
        output_tokens = None
        last_error = None
        for _ in range(self.n_attempts):
            response = self.provider.generate(prompt, context=context)
            total_latency += response.latency_ms
            total_cost += response.cost_estimate_usd
            if response.input_tokens is not None:
                input_tokens = (input_tokens or 0) + response.input_tokens
            if response.output_tokens is not None:
                output_tokens = (output_tokens or 0) + response.output_tokens
            if response.status == STATUS_OK:
                attempts.append(SolverAttempt(
                    attempt=len(attempts) + 1,
                    raw_output=response.response_text,
                ))
            else:
                last_error = response.error_message

        # Item succeeds if at least one sample came back; it errors only when
        # every sample failed (so a fully-dead backend still yields a row).
        status = STATUS_OK if attempts else STATUS_ERROR
        return SolverResult(
            status=status,
            attempts=attempts,
            error_message=None if attempts else last_error,
            latency_ms=total_latency,
            cost_estimate_usd=total_cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            prompt_text=prompt,
        )

    def describe(self) -> dict:
        info = super().describe()
        info.update({
            "provider": self.provider_name,
            "model_name": self.model_name,
            "prompt_version": self.prompt_version,
            "n_attempts": self.n_attempts,
            "base_url": self.provider.base_url,
        })
        return info


# ---------------------------------------------------------------------------
# Subprocess adapter: wrap any CLI-invocable solver
# ---------------------------------------------------------------------------

def interpret_solver_output(stdout: str) -> tuple:
    """
    Decode a solver's textual output into (attempts, metadata).

    Accepts, most structured first:
      {"attempts": [grid, ...], "metadata": {...}}  → up to N structured attempts
      {"prediction": grid, "metadata": {...}}       → one structured attempt
      anything else                                 → one raw-text attempt
    Pure function — unit-testable without spawning processes.
    """
    try:
        envelope = json.loads(stdout)
    except (json.JSONDecodeError, TypeError):
        envelope = None

    if isinstance(envelope, dict) and "attempts" in envelope:
        grids = envelope.get("attempts") or []
        attempts = [SolverAttempt(attempt=i, grid=g)
                    for i, g in enumerate(grids, start=1)]
        return attempts, envelope.get("metadata")
    if isinstance(envelope, dict) and "prediction" in envelope:
        return ([SolverAttempt(attempt=1, grid=envelope["prediction"])],
                envelope.get("metadata"))
    # Raw text (possibly a bare JSON grid, prose, or anything in between):
    # the grid parser downstream scans it exactly like an LLM completion.
    return [SolverAttempt(attempt=1, raw_output=stdout)], None


class CommandSolver(BaseSolver):
    """
    Runs an external command once per (task, test example):

        echo '<wire task JSON>' | <command>

    stdout is interpreted via interpret_solver_output(); non-zero exit or
    timeout becomes an execution_error row (never aborts the batch).
    Wrap heavyweight solvers with a small shim script that speaks this
    contract — see docs/SOLVER_ADAPTERS.md for per-family recipes.
    """

    execution_mode = "subprocess"

    def __init__(self, name: str, command: list,
                 family: str = "external", version: str = "unversioned",
                 timeout_s: Optional[float] = None, workdir: Optional[str] = None):
        if not command or not isinstance(command, list):
            raise SolverError(
                f"Solver '{name}': `command` must be a non-empty list of "
                f"argv strings, got {command!r}."
            )
        self.name = name
        self.family = family
        self.version = version
        self.command = [str(c) for c in command]
        self.timeout_s = timeout_s if timeout_s is not None \
            else config.provider_timeout()
        self.workdir = workdir

    def solve(self, task: SolverTask) -> SolverResult:
        payload = json.dumps(task.to_wire())
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                self.command, input=payload, capture_output=True, text=True,
                timeout=self.timeout_s, cwd=self.workdir,
            )
        except subprocess.TimeoutExpired:
            return SolverResult(
                status=STATUS_ERROR,
                error_message=f"solver timed out after {self.timeout_s:.0f}s",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        except (OSError, ValueError) as exc:
            return SolverResult(
                status=STATUS_ERROR,
                error_message=f"could not launch solver command: {exc}",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        latency_ms = (time.perf_counter() - started) * 1000

        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "").strip()[-300:]
            return SolverResult(
                status=STATUS_ERROR,
                error_message=(f"solver exited with code {proc.returncode}"
                               + (f": {stderr_tail}" if stderr_tail else "")),
                latency_ms=latency_ms,
            )

        attempts, metadata = interpret_solver_output(proc.stdout)
        return SolverResult(status=STATUS_OK, attempts=attempts,
                            latency_ms=latency_ms, metadata=metadata)

    def describe(self) -> dict:
        info = super().describe()
        info.update({"command": self.command, "timeout_s": self.timeout_s,
                     "workdir": self.workdir})
        return info


# ---------------------------------------------------------------------------
# HTTP adapter: POST the task to a solver service
# ---------------------------------------------------------------------------

class HTTPSolver(BaseSolver):
    """
    POSTs the wire task JSON to a solver endpoint and expects the same JSON
    envelope as CommandSolver stdout ({"prediction": ...} or
    {"attempts": [...]}). Transient HTTP failures are retried once
    (providers.post_json); persistent failures become execution_error rows.
    Authentication, if the service needs it, is a human/deployment concern —
    keep such services on localhost or a trusted network for now.
    """

    execution_mode = "http"

    def __init__(self, name: str, url: str,
                 family: str = "external", version: str = "unversioned",
                 timeout_s: Optional[float] = None):
        if not url or not str(url).startswith(("http://", "https://")):
            raise SolverError(
                f"Solver '{name}': `url` must start with http:// or "
                f"https://, got {url!r}."
            )
        self.name = name
        self.family = family
        self.version = version
        self.url = str(url)
        self.timeout_s = timeout_s if timeout_s is not None \
            else config.provider_timeout()

    def solve(self, task: SolverTask) -> SolverResult:
        started = time.perf_counter()
        try:
            data = post_json(self.url, task.to_wire(), headers={},
                             timeout=self.timeout_s)
        except RuntimeError as exc:
            return SolverResult(
                status=STATUS_ERROR, error_message=str(exc),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        latency_ms = (time.perf_counter() - started) * 1000

        attempts, metadata = interpret_solver_output(json.dumps(data))
        if not any(a.grid is not None or a.raw_output for a in attempts):
            return SolverResult(
                status=STATUS_ERROR,
                error_message=("solver response is not a recognized envelope "
                               "(expected 'prediction' or 'attempts' key): "
                               f"{str(data)[:300]}"),
                latency_ms=latency_ms,
            )
        return SolverResult(status=STATUS_OK, attempts=attempts,
                            latency_ms=latency_ms, metadata=metadata)

    def describe(self) -> dict:
        info = super().describe()
        info.update({"url": self.url, "timeout_s": self.timeout_s})
        return info


# ---------------------------------------------------------------------------
# Submission adapters: score artifacts without running a solver
# ---------------------------------------------------------------------------

class CanonicalSubmissionSolver(BaseSolver):
    """
    Judge from an already-normalized CanonicalSubmission index.
    Missing (task, test) pairs become execution_error rows so coverage
    gaps stay visible. Latency/cost are 0 (offline artifact).
    """

    family = "submission"

    def __init__(self, name: str, canonical, version: str = "unversioned",
                 execution_mode: str = "submission_file",
                 refuse_on_errors: bool = True):
        from submission_io import CanonicalSubmission
        if not isinstance(canonical, CanonicalSubmission):
            raise SolverError(
                f"Solver '{name}': expected CanonicalSubmission, "
                f"got {type(canonical).__name__}"
            )
        if refuse_on_errors and not canonical.ok:
            n = len(canonical.errors)
            sample = canonical.errors[0].message if canonical.errors else ""
            raise SolverError(
                f"Submission artifact for '{name}' has {n} validation "
                f"error(s); fix them or re-run with validate-submission. "
                f"First error: {sample}"
            )
        self.name = name
        self.version = version
        self.execution_mode = execution_mode
        self.canonical = canonical
        self._index = canonical.as_attempt_index()
        self._source_path = canonical.source_path
        self._source_format = canonical.source_format

    def solve(self, task: SolverTask) -> SolverResult:
        key = (task.task_id, task.test_example_id)
        grids = self._index.get(key)
        if grids is None:
            return SolverResult(
                status=STATUS_ERROR,
                error_message=(
                    f"task '{task.task_id}' test example "
                    f"{task.test_example_id} not present in submission "
                    f"artifact ({self._source_format}: {self._source_path})"
                ),
            )
        attempts = [
            SolverAttempt(attempt=i, grid=g)
            for i, g in enumerate(grids, start=1)
        ]
        return SolverResult(
            status=STATUS_OK, attempts=attempts,
            metadata={
                "source_format": self._source_format,
                "source_path": self._source_path,
            },
        )

    def describe(self) -> dict:
        info = super().describe()
        info.update({
            "path": self._source_path,
            "source_format": self._source_format,
            "n_tasks": len(self.canonical.task_ids()),
            "n_predictions": len(self.canonical.predictions),
            "n_warnings": len(self.canonical.warnings),
        })
        return info


class SubmissionFileSolver(CanonicalSubmissionSolver):
    """
    Official path A: score a Kaggle-style submission.json (or atlas
    canonical export) without running the solver.
    """

    execution_mode = "submission_file"

    def __init__(self, name: str, path, version: str = "unversioned",
                 refuse_on_errors: bool = True):
        from submission_io import SubmissionFormatError, load_submission_file
        try:
            canonical = load_submission_file(Path(path))
        except SubmissionFormatError as exc:
            raise SolverError(str(exc)) from exc
        super().__init__(
            name=name, canonical=canonical, version=version,
            execution_mode="submission_file",
            refuse_on_errors=refuse_on_errors,
        )


class SubmissionDirSolver(CanonicalSubmissionSolver):
    """
    Official path B: score a directory of per-task prediction JSON files
    (`<task_id>.json`) without running the solver.
    """

    execution_mode = "submission_dir"

    def __init__(self, name: str, path, version: str = "unversioned",
                 refuse_on_errors: bool = True):
        from submission_io import SubmissionFormatError, load_submission_dir
        try:
            canonical = load_submission_dir(Path(path))
        except SubmissionFormatError as exc:
            raise SolverError(str(exc)) from exc
        super().__init__(
            name=name, canonical=canonical, version=version,
            execution_mode="submission_dir",
            refuse_on_errors=refuse_on_errors,
        )
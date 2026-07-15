"""
Model provider abstraction for the inference runner.

Providers:
    mock    — deterministic, offline, zero-dependency. Always available.
    openai  — OpenAI-compatible Chat Completions API via stdlib urllib.
              Needs OPENAI_API_KEY (and optionally OPENAI_BASE_URL).
    ollama  — local Ollama server via stdlib urllib. Needs a running server
              (OLLAMA_HOST, default http://localhost:11434).

Real providers use only the standard library (urllib) so the repo gains no
new dependencies. They fail at construction time with a clear message when
credentials / servers are absent; per-call failures return status="error"
instead of raising, so one bad call never kills a batch run.

The `context` argument of generate() exists ONLY so MockProvider can
fabricate deterministic responses (it carries task_id, test_input and
expected_output). Real providers MUST ignore it — ground truth never
reaches a real model.
"""

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

STATUS_OK = "ok"
STATUS_ERROR = "error"

_RETRYABLE_HTTP = {429, 500, 502, 503, 504}

# USD per 1M tokens (input, output) — estimates for reporting, not billing.
# Unknown models fall back to (0.0, 0.0) and cost_estimate_usd stays 0.0.
OPENAI_PRICES_PER_MTOK = {
    "gpt-4o":        (2.50, 10.00),
    "gpt-4o-mini":   (0.15, 0.60),
    "gpt-4.1":       (2.00, 8.00),
    "gpt-4.1-mini":  (0.40, 1.60),
    "gpt-4.1-nano":  (0.10, 0.40),
}


class ProviderConfigError(RuntimeError):
    """Provider cannot be constructed (missing key, unreachable server...)."""


@dataclass
class ProviderResponse:
    response_text: Optional[str]
    status: str                    # STATUS_OK | STATUS_ERROR
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    cost_estimate_usd: float = 0.0
    raw: Optional[dict] = field(default=None, repr=False)


class BaseProvider:
    """Minimal interface: a name and a generate() call."""

    name = "base"

    def __init__(self, model_name: str):
        self.model_name = model_name

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        raise NotImplementedError


# MOCK PROVIDER

def _hflip(grid: list) -> list:
    return [list(reversed(row)) for row in grid]


def _recolor(grid: list) -> list:
    return [[(val + 3) % 10 for val in row] for row in grid]


class MockProvider(BaseProvider):
    """
    Deterministic fake model for pipeline testing (NOT a scientific baseline).

    The behavior for a given (model_name, task_id) pair is chosen by an MD5
    hash bucket, so runs are fully reproducible and, across a batch of tasks,
    every downstream code path is exercised: correct answers, wrong grids of
    every flavor, unparseable text, empty replies, and provider errors.

    Buckets (10% each unless noted):
        0,1  identity        — echoes the test input (20%)
        2    oracle          — echoes the expected output when available
        3    horizontal flip — same colors, moved positions
        4    recolor         — same shape, shifted color values
        5    tiny grid       — returns [[0]] (wrong shape)
        6    prose           — natural language, no JSON anywhere
        7    empty           — empty string response
        8    fenced          — correct-shaped JSON inside ```json fence + prose
        9    api failure     — simulated provider outage (status="error")

    Latency is synthetic and deterministic (no sleep, no wall-clock noise).
    """

    name = "mock"

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        context = context or {}
        task_id = str(context.get("task_id", "unknown"))
        test_input = context.get("test_input") or [[0]]
        expected = context.get("expected_output")

        digest = hashlib.md5(f"{self.model_name}:{task_id}".encode()).hexdigest()
        bucket = int(digest, 16) % 10
        latency_ms = 3.0 + bucket * 1.5
        grid_json = json.dumps  # alias for brevity

        if bucket in (0, 1):
            text = grid_json(test_input)
        elif bucket == 2:
            text = grid_json(expected if expected is not None else test_input)
        elif bucket == 3:
            text = grid_json(_hflip(test_input))
        elif bucket == 4:
            text = grid_json(_recolor(test_input))
        elif bucket == 5:
            text = "[[0]]"
        elif bucket == 6:
            text = (
                "The pattern seems to involve reflecting the shapes, "
                "but I cannot determine the exact output grid."
            )
        elif bucket == 7:
            text = ""
        elif bucket == 8:
            text = (
                "Sure! Applying the transformation:\n"
                f"```json\n{grid_json(_hflip(test_input))}\n```\n"
                "Let me know if you need anything else."
            )
        else:  # bucket == 9
            return ProviderResponse(
                response_text=None,
                status=STATUS_ERROR,
                error_message="mock: simulated provider outage (bucket 9)",
                latency_ms=latency_ms,
                raw={"mock_bucket": bucket},
            )

        return ProviderResponse(
            response_text=text,
            status=STATUS_OK,
            latency_ms=latency_ms,
            cost_estimate_usd=0.0,
            raw={"mock_bucket": bucket},
        )


# HTTP HELPERS (shared by real providers)

def _post_json(url: str, payload: dict, headers: dict, timeout: float,
               max_attempts: int = 2, backoff_s: float = 2.0) -> dict:
    """
    POST JSON, return decoded JSON. Retries once on retryable HTTP codes and
    network errors. Raises RuntimeError with a readable message on failure.
    """
    body = json.dumps(payload).encode("utf-8")
    last_error = None
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            last_error = f"HTTP {exc.code} from {url}: {detail}"
            if exc.code not in _RETRYABLE_HTTP:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = f"connection error to {url}: {exc}"
        if attempt < max_attempts:
            time.sleep(backoff_s)
    raise RuntimeError(last_error or f"request to {url} failed")


# OPENAI PROVIDER

class OpenAIProvider(BaseProvider):
    """OpenAI-compatible Chat Completions endpoint (stdlib HTTP, no SDK)."""

    name = "openai"

    def __init__(self, model_name: str, timeout: float = 120.0):
        super().__init__(model_name)
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.base_url = os.environ.get(
            "OPENAI_BASE_URL", "https://api.openai.com/v1"
        ).rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ProviderConfigError(
                "OPENAI_API_KEY is not set. Export it (see .env.example) or "
                "use `--provider mock` for an offline run."
            )

    def _estimate_cost(self, usage: dict) -> float:
        price_in, price_out = OPENAI_PRICES_PER_MTOK.get(self.model_name, (0.0, 0.0))
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0
        return (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        }
        started = time.perf_counter()
        try:
            data = _post_json(
                f"{self.base_url}/chat/completions", payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        except RuntimeError as exc:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR, error_message=str(exc),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        latency_ms = (time.perf_counter() - started) * 1000

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR,
                error_message=f"unexpected response payload: {exc}",
                latency_ms=latency_ms, raw=data,
            )
        return ProviderResponse(
            response_text=text, status=STATUS_OK, latency_ms=latency_ms,
            cost_estimate_usd=self._estimate_cost(data.get("usage", {}) or {}),
            raw=data,
        )


# OLLAMA PROVIDER

class OllamaProvider(BaseProvider):
    """Local Ollama server via its native /api/generate endpoint."""

    name = "ollama"

    def __init__(self, model_name: str, timeout: float = 300.0):
        super().__init__(model_name)
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        self.timeout = timeout
        # Fail fast with a clear message instead of N per-task timeouts.
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=3) as resp:
                resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderConfigError(
                f"Ollama server not reachable at {self.host} ({exc}). "
                "Start it with `ollama serve`, set OLLAMA_HOST, or use "
                "`--provider mock` for an offline run."
            )

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0},
        }
        started = time.perf_counter()
        try:
            data = _post_json(f"{self.host}/api/generate", payload,
                              headers={}, timeout=self.timeout)
        except RuntimeError as exc:
            message = str(exc)
            if "HTTP 404" in message:
                message += f" (hint: `ollama pull {self.model_name}`)"
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR, error_message=message,
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        latency_ms = (time.perf_counter() - started) * 1000
        text = data.get("response")
        if text is None:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR,
                error_message=f"unexpected response payload: {str(data)[:300]}",
                latency_ms=latency_ms, raw=data,
            )
        return ProviderResponse(
            response_text=text, status=STATUS_OK, latency_ms=latency_ms,
            cost_estimate_usd=0.0, raw=data,
        )


PROVIDERS = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}


def get_provider(provider_name: str, model_name: str) -> BaseProvider:
    """Factory. Raises ProviderConfigError / ValueError with clear messages."""
    try:
        provider_cls = PROVIDERS[provider_name]
    except KeyError:
        raise ValueError(
            f"Unknown provider '{provider_name}'. "
            f"Available: {sorted(PROVIDERS)}"
        )
    return provider_cls(model_name)

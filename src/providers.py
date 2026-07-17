"""
LLM execution backends for the `llm_direct` solver family.

In platform terms (src/solvers.py) this module is NOT the solver interface —
it is the lowest layer of ONE solver family: single-prompt LLM solvers.
`LLMDirectSolver` composes a versioned prompt (src/prompt_builder.py) and
delegates the completion call to one of these backends. Other solver
families (subprocess, HTTP, submission-file) never import this module.

Providers:
    mock    — deterministic, offline, zero-dependency. Always available.
    openai  — OpenAI-compatible Chat Completions API (also NIM, OpenRouter,
              Azure-style gateways). Needs OPENAI_API_KEY or ATLAS_API_KEY.
    gemini  — Google Generative Language API (generateContent).
              Needs GEMINI_API_KEY, GOOGLE_API_KEY, or ATLAS_API_KEY.
    claude  — Anthropic Messages API.
              Needs ANTHROPIC_API_KEY or ATLAS_API_KEY.
    ollama  — local Ollama server via stdlib urllib. Needs a running server
              (OLLAMA_HOST, default http://localhost:11434).

Real providers use only the standard library (urllib) so the repo gains no
new dependencies (Decision 8). They fail at construction time with a clear
message when credentials / servers are absent; per-call failures return
status="error" instead of raising, so one bad call never kills a batch run.

Every response is normalized into ONE internal contract, ProviderResponse:
text, status, error, latency, token counts when the API reports them, and a
static-price cost estimate (a reporting aid, not billing data).

The `context` argument of generate() exists ONLY so MockProvider can
fabricate deterministic responses (it carries task_id, test_input and
expected_output). Real providers MUST ignore it — ground truth never
reaches a real model.
"""

import hashlib
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

import config

STATUS_OK = "ok"
STATUS_ERROR = "error"

# 529 is Anthropic's "overloaded"; the rest are the usual transient set.
_RETRYABLE_HTTP = {429, 500, 502, 503, 504, 529}

# USD per 1M tokens (input, output) — static estimates for reporting, not
# billing (checked 2026-07; tiered/long-context pricing is ignored).
# Unknown models fall back to (0.0, 0.0) and cost_estimate_usd stays 0.0.
OPENAI_PRICES_PER_MTOK = {
    "gpt-4o":        (2.50, 10.00),
    "gpt-4o-mini":   (0.15, 0.60),
    "gpt-4.1":       (2.00, 8.00),
    "gpt-4.1-mini":  (0.40, 1.60),
    "gpt-4.1-nano":  (0.10, 0.40),
}
GEMINI_PRICES_PER_MTOK = {
    "gemini-2.5-pro":        (1.25, 10.00),
    "gemini-2.5-flash":      (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
}
CLAUDE_PRICES_PER_MTOK = {
    "claude-fable-5":    (10.00, 50.00),
    "claude-opus-4-8":   (5.00, 25.00),
    "claude-opus-4-7":   (5.00, 25.00),
    "claude-opus-4-6":   (5.00, 25.00),
    "claude-sonnet-5":   (3.00, 15.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5":  (1.00, 5.00),
}


class ProviderConfigError(RuntimeError):
    """Provider cannot be constructed (missing key, unreachable server...)."""


@dataclass
class ProviderResponse:
    """The one internal response contract every adapter normalizes into."""
    response_text: Optional[str]
    status: str                    # STATUS_OK | STATUS_ERROR
    error_message: Optional[str] = None
    latency_ms: float = 0.0
    cost_estimate_usd: float = 0.0
    input_tokens: Optional[int] = None    # None when the API reports no usage
    output_tokens: Optional[int] = None
    raw: Optional[dict] = field(default=None, repr=False)


class BaseProvider:
    """Minimal interface: a name, an optional endpoint, and generate()."""

    name = "base"
    base_url: Optional[str] = None   # real providers set this; recorded in manifests

    def __init__(self, model_name: str):
        self.model_name = model_name

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        raise NotImplementedError


# CONFIG RESOLUTION HELPERS (shared by real providers)

def _resolve_api_key(provider_label: str, *env_names: str) -> str:
    """
    First set variable wins (provider-specific first, generic ATLAS_API_KEY
    last). Logs the variable NAME that supplied the key — never the key.
    """
    name, value = config.first_env(*env_names)
    if not value:
        options = " or ".join(env_names)
        raise ProviderConfigError(
            f"No API key configured for provider '{provider_label}'. "
            f"Export {options} (see .env.example), or use `--provider mock` "
            "for an offline run."
        )
    logging.info("[%s] using API key from $%s", provider_label, name)
    return value


def _resolve_base_url(provider_label: str, default: str, *env_names: str) -> str:
    name, value = config.first_env(*env_names)
    if value:
        logging.info("[%s] using base URL from $%s", provider_label, name)
    return (value or default).rstrip("/")


def _estimate_cost(prices: dict, model_name: str,
                   input_tokens: Optional[int],
                   output_tokens: Optional[int]) -> float:
    price_in, price_out = prices.get(model_name, (0.0, 0.0))
    return ((input_tokens or 0) * price_in
            + (output_tokens or 0) * price_out) / 1_000_000


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


# HTTP HELPERS (shared by real providers; also reused by the HTTP solver
# adapter in src/solvers.py)

def post_json(url: str, payload: dict, headers: dict, timeout: float,
              max_attempts: int = 2, backoff_s: float = 2.0) -> dict:
    """
    POST JSON, return decoded JSON. Retries once on retryable HTTP codes and
    network errors. Raises RuntimeError with a readable message on failure.
    """
    body = json.dumps(payload).encode("utf-8")
    last_error = None
    # Some gateways (e.g. Cloudflare in front of OpenCode Zen) reject the
    # default Python-urllib User-Agent. Always send an explicit one unless
    # the caller already set it.
    merged_headers = {
        "Content-Type": "application/json",
        "User-Agent": "AtlasEval/0.3 (+https://github.com/local/arc-failure-atlas)",
        "Accept": "application/json",
        **headers,
    }
    for attempt in range(1, max_attempts + 1):
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers=merged_headers,
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


# OPENAI-COMPATIBLE PROVIDER

class OpenAIProvider(BaseProvider):
    """OpenAI-compatible Chat Completions endpoint (stdlib HTTP, no SDK)."""

    name = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, model_name: str, timeout: float | None = None):
        super().__init__(model_name)
        self.api_key = _resolve_api_key(self.name, "OPENAI_API_KEY",
                                        config.ENV_API_KEY)
        self.base_url = _resolve_base_url(self.name, self.DEFAULT_BASE_URL,
                                          "OPENAI_BASE_URL", config.ENV_BASE_URL)
        # Large hosted models (e.g. NVIDIA NIM 70B+) often need minutes;
        # override with OPENAI_TIMEOUT_S / ATLAS_TIMEOUT_S when needed.
        self.timeout = timeout if timeout is not None \
            else config.provider_timeout(legacy_env="OPENAI_TIMEOUT_S")

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        payload = {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": config.max_output_tokens(),
        }
        # Kimi K2.5/K2.6, Qwen 3.7*, and GLM-5*: thinking is ON by default on
        # OpenCode Go and burns tokens / timeouts on ARC prompts. Disable for
        # grid-only runs. Do not send temperature=0 with these models.
        model_l = self.model_name.lower()
        if (model_l.startswith("kimi-k2.5") or model_l.startswith("kimi-k2.6")
                or model_l.startswith("qwen3.7")
                or model_l.startswith("glm-5")):
            payload["thinking"] = {"type": "disabled"}
        else:
            payload["temperature"] = 0
        started = time.perf_counter()
        try:
            data = post_json(
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
            message = data["choices"][0]["message"]
            text = message.get("content")
            # Some gateways put the visible answer in content and reasoning
            # elsewhere; if content is empty, fall back to reasoning_content.
            if text is None or (isinstance(text, str) and not text.strip()):
                text = message.get("reasoning_content") or message.get("reasoning")
        except (KeyError, IndexError, TypeError) as exc:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR,
                error_message=f"unexpected response payload: {exc}",
                latency_ms=latency_ms, raw=data,
            )
        usage = data.get("usage") or {}
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        return ProviderResponse(
            response_text=text, status=STATUS_OK, latency_ms=latency_ms,
            cost_estimate_usd=_estimate_cost(OPENAI_PRICES_PER_MTOK,
                                             self.model_name,
                                             input_tokens, output_tokens),
            input_tokens=input_tokens, output_tokens=output_tokens,
            raw=data,
        )


# GEMINI PROVIDER

def extract_gemini_text(data: dict) -> tuple:
    """
    Pull the model text out of a generateContent response.
    Returns (text, None) on success or (None, error_message) on failure —
    pure function so the parsing rules are unit-testable offline.
    """
    feedback = data.get("promptFeedback") or {}
    if feedback.get("blockReason"):
        return None, f"prompt blocked by Gemini: {feedback['blockReason']}"

    candidates = data.get("candidates") or []
    if not candidates:
        return None, f"no candidates in response: {str(data)[:300]}"

    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(part["text"] for part in parts if "text" in part)
    if not text:
        reason = candidate.get("finishReason", "unknown")
        return None, f"candidate contains no text (finishReason={reason})"
    return text, None


class GeminiProvider(BaseProvider):
    """Google Generative Language API — models/<name>:generateContent."""

    name = "gemini"
    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"

    def __init__(self, model_name: str, timeout: float | None = None):
        super().__init__(model_name)
        self.api_key = _resolve_api_key(self.name, "GEMINI_API_KEY",
                                        "GOOGLE_API_KEY", config.ENV_API_KEY)
        self.base_url = _resolve_base_url(self.name, self.DEFAULT_BASE_URL,
                                          "GEMINI_BASE_URL", config.ENV_BASE_URL)
        self.timeout = timeout if timeout is not None else config.provider_timeout()
        self.max_output_tokens = config.max_output_tokens()

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": self.max_output_tokens,
            },
        }
        url = f"{self.base_url}/v1beta/models/{self.model_name}:generateContent"
        started = time.perf_counter()
        try:
            # Key goes in a header, not the URL, so it never lands in logs.
            data = post_json(url, payload,
                              headers={"x-goog-api-key": self.api_key},
                              timeout=self.timeout)
        except RuntimeError as exc:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR, error_message=str(exc),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        latency_ms = (time.perf_counter() - started) * 1000

        text, error = extract_gemini_text(data)
        usage = data.get("usageMetadata") or {}
        input_tokens = usage.get("promptTokenCount")
        output_tokens = usage.get("candidatesTokenCount")
        if error is not None:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR, error_message=error,
                latency_ms=latency_ms, input_tokens=input_tokens,
                output_tokens=output_tokens, raw=data,
            )
        return ProviderResponse(
            response_text=text, status=STATUS_OK, latency_ms=latency_ms,
            cost_estimate_usd=_estimate_cost(GEMINI_PRICES_PER_MTOK,
                                             self.model_name,
                                             input_tokens, output_tokens),
            input_tokens=input_tokens, output_tokens=output_tokens,
            raw=data,
        )


# CLAUDE PROVIDER

def extract_claude_text(data: dict) -> tuple:
    """
    Pull the model text out of an Anthropic Messages API response.
    Returns (text, None) on success or (None, error_message) on failure.
    A refusal (stop_reason="refusal") is an error for this pipeline: there
    is no grid to score. stop_reason="max_tokens" with partial text is kept —
    the parser downstream will classify a truncated grid.
    """
    stop_reason = data.get("stop_reason")
    if stop_reason == "refusal":
        details = data.get("stop_details") or {}
        category = details.get("category") or "unspecified"
        return None, f"Claude declined the request (refusal, category={category})"

    content = data.get("content")
    if not isinstance(content, list):
        return None, f"unexpected response payload: {str(data)[:300]}"
    text = "".join(block.get("text", "") for block in content
                   if isinstance(block, dict) and block.get("type") == "text")
    if not text:
        return None, f"no text blocks in response (stop_reason={stop_reason})"
    return text, None


class ClaudeProvider(BaseProvider):
    """
    Anthropic Messages API (stdlib HTTP, no SDK).

    Deliberately sends NO sampling parameters: `temperature`/`top_p` are
    rejected (HTTP 400) by the newest Anthropic models (Opus 4.7+), and the
    prompt contract is the reproducibility mechanism here, as everywhere
    else in this pipeline. `max_tokens` is required by the API — configured
    via ATLAS_MAX_OUTPUT_TOKENS (default 16000).
    """

    name = "claude"
    DEFAULT_BASE_URL = "https://api.anthropic.com"
    API_VERSION = "2023-06-01"

    def __init__(self, model_name: str, timeout: float | None = None):
        super().__init__(model_name)
        self.api_key = _resolve_api_key(self.name, "ANTHROPIC_API_KEY",
                                        config.ENV_API_KEY)
        self.base_url = _resolve_base_url(self.name, self.DEFAULT_BASE_URL,
                                          "ANTHROPIC_BASE_URL", config.ENV_BASE_URL)
        self.timeout = timeout if timeout is not None else config.provider_timeout()
        self.max_output_tokens = config.max_output_tokens()

    def generate(self, prompt: str, context: Optional[dict] = None) -> ProviderResponse:
        payload = {
            "model": self.model_name,
            "max_tokens": self.max_output_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }
        started = time.perf_counter()
        try:
            data = post_json(
                f"{self.base_url}/v1/messages", payload,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": self.API_VERSION,
                },
                timeout=self.timeout,
            )
        except RuntimeError as exc:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR, error_message=str(exc),
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        latency_ms = (time.perf_counter() - started) * 1000

        text, error = extract_claude_text(data)
        usage = data.get("usage") or {}
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        if error is not None:
            return ProviderResponse(
                response_text=None, status=STATUS_ERROR, error_message=error,
                latency_ms=latency_ms, input_tokens=input_tokens,
                output_tokens=output_tokens, raw=data,
            )
        return ProviderResponse(
            response_text=text, status=STATUS_OK, latency_ms=latency_ms,
            cost_estimate_usd=_estimate_cost(CLAUDE_PRICES_PER_MTOK,
                                             self.model_name,
                                             input_tokens, output_tokens),
            input_tokens=input_tokens, output_tokens=output_tokens,
            raw=data,
        )


# OLLAMA PROVIDER

class OllamaProvider(BaseProvider):
    """Local Ollama server via its native /api/generate endpoint."""

    name = "ollama"

    def __init__(self, model_name: str, timeout: float | None = None):
        super().__init__(model_name)
        self.base_url = _resolve_base_url(
            self.name, "http://localhost:11434", "OLLAMA_HOST", config.ENV_BASE_URL,
        )
        self.timeout = timeout if timeout is not None else config.provider_timeout()
        # Fail fast with a clear message instead of N per-task timeouts.
        try:
            with urllib.request.urlopen(f"{self.base_url}/api/tags", timeout=3) as resp:
                resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderConfigError(
                f"Ollama server not reachable at {self.base_url} ({exc}). "
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
            data = post_json(f"{self.base_url}/api/generate", payload,
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
            cost_estimate_usd=0.0,
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
            raw=data,
        )


PROVIDERS = {
    "mock": MockProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "claude": ClaudeProvider,
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

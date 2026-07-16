"""Unit tests for src/providers.py — run from the repo root:

    python -m unittest discover -s tests -v

Fully offline: only the mock provider's generate() is exercised; for real
providers these tests cover construction-time config resolution and the pure
payload-extraction helpers (no HTTP is ever issued — OllamaProvider, whose
constructor pings a server, is deliberately not constructed here).
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from providers import (  # noqa: E402
    CLAUDE_PRICES_PER_MTOK,
    GEMINI_PRICES_PER_MTOK,
    PROVIDERS,
    STATUS_ERROR,
    STATUS_OK,
    ClaudeProvider,
    GeminiProvider,
    MockProvider,
    OpenAIProvider,
    ProviderConfigError,
    ProviderResponse,
    _estimate_cost,
    extract_claude_text,
    extract_gemini_text,
    get_provider,
)

CONTEXT = {
    "task_id": "sample01",
    "test_input": [[1, 2], [3, 4]],
    "expected_output": [[4, 3], [2, 1]],
}


class TestMockProvider(unittest.TestCase):
    def test_deterministic_per_model_and_task(self):
        first = MockProvider("baseline").generate("prompt", context=CONTEXT)
        second = MockProvider("baseline").generate("prompt", context=CONTEXT)
        self.assertEqual(first.response_text, second.response_text)
        self.assertEqual(first.status, second.status)
        self.assertEqual(first.latency_ms, second.latency_ms)

    def test_different_model_may_change_bucket_but_stays_deterministic(self):
        a = MockProvider("baseline").generate("p", context=CONTEXT)
        b = MockProvider("mock-large").generate("p", context=CONTEXT)
        # Not asserting inequality (hash collisions are legal) — only that
        # each is internally reproducible.
        self.assertEqual(
            b.response_text,
            MockProvider("mock-large").generate("p", context=CONTEXT).response_text,
        )
        self.assertIn(a.status, (STATUS_OK, STATUS_ERROR))

    def test_simulated_outage_bucket_returns_error_row_material(self):
        import hashlib
        provider = MockProvider("baseline")
        task_id = next(
            f"task{i}" for i in range(1000)
            if int(hashlib.md5(f"baseline:task{i}".encode()).hexdigest(), 16) % 10 == 9
        )
        response = provider.generate("p", context={**CONTEXT, "task_id": task_id})
        self.assertEqual(response.status, STATUS_ERROR)
        self.assertIn("outage", response.error_message)

    def test_token_fields_default_to_none(self):
        response = MockProvider("baseline").generate("p", context=CONTEXT)
        self.assertIsNone(response.input_tokens)
        self.assertIsNone(response.output_tokens)


class TestFactory(unittest.TestCase):
    def test_registry_contains_expected_providers(self):
        self.assertEqual(sorted(PROVIDERS),
                         ["claude", "gemini", "mock", "ollama", "openai"])

    def test_unknown_provider_lists_available(self):
        with self.assertRaises(ValueError) as ctx:
            get_provider("bogus", "model")
        self.assertIn("claude", str(ctx.exception))

    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_fails_fast_with_var_names(self):
        for name, expected_var in (("openai", "OPENAI_API_KEY"),
                                   ("gemini", "GEMINI_API_KEY"),
                                   ("claude", "ANTHROPIC_API_KEY")):
            with self.subTest(provider=name):
                with self.assertRaises(ProviderConfigError) as ctx:
                    get_provider(name, "some-model")
                message = str(ctx.exception)
                self.assertIn(expected_var, message)
                self.assertIn("ATLAS_API_KEY", message)
                self.assertIn("mock", message)  # points at the offline path


class TestKeyAndUrlResolution(unittest.TestCase):
    @patch.dict(os.environ, {"ATLAS_API_KEY": "generic-key"}, clear=True)
    def test_generic_atlas_key_is_accepted(self):
        provider = ClaudeProvider("claude-opus-4-8")
        self.assertEqual(provider.api_key, "generic-key")
        self.assertEqual(provider.base_url, ClaudeProvider.DEFAULT_BASE_URL)

    @patch.dict(os.environ,
                {"ATLAS_API_KEY": "generic-key",
                 "ANTHROPIC_API_KEY": "specific-key"},
                clear=True)
    def test_provider_specific_key_wins_over_generic(self):
        self.assertEqual(ClaudeProvider("claude-opus-4-8").api_key,
                         "specific-key")

    @patch.dict(os.environ,
                {"GEMINI_API_KEY": "g-key",
                 "ATLAS_BASE_URL": "https://proxy.example.test/gemini/"},
                clear=True)
    def test_generic_base_url_applies_and_strips_trailing_slash(self):
        provider = GeminiProvider("gemini-2.5-flash")
        self.assertEqual(provider.base_url, "https://proxy.example.test/gemini")

    @patch.dict(os.environ,
                {"OPENAI_API_KEY": "o-key", "OPENAI_TIMEOUT_S": "42"},
                clear=True)
    def test_openai_legacy_timeout_still_honored(self):
        self.assertEqual(OpenAIProvider("gpt-4o-mini").timeout, 42.0)

    @patch.dict(os.environ,
                {"ANTHROPIC_API_KEY": "k", "ATLAS_MAX_OUTPUT_TOKENS": "9000"},
                clear=True)
    def test_claude_max_output_tokens_from_env(self):
        self.assertEqual(ClaudeProvider("claude-opus-4-8").max_output_tokens,
                         9000)


class TestClaudePayloadExtraction(unittest.TestCase):
    def test_joins_text_blocks(self):
        text, error = extract_claude_text({
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "[[1,2],"},
                {"type": "text", "text": "[3,4]]"},
            ],
        })
        self.assertIsNone(error)
        self.assertEqual(text, "[[1,2],[3,4]]")

    def test_refusal_is_an_error_with_category(self):
        text, error = extract_claude_text({
            "stop_reason": "refusal",
            "stop_details": {"type": "refusal", "category": "cyber"},
            "content": [],
        })
        self.assertIsNone(text)
        self.assertIn("refusal", error)
        self.assertIn("cyber", error)

    def test_no_text_blocks_is_an_error_naming_stop_reason(self):
        text, error = extract_claude_text({
            "stop_reason": "end_turn",
            "content": [{"type": "thinking", "thinking": ""}],
        })
        self.assertIsNone(text)
        self.assertIn("end_turn", error)

    def test_malformed_payload_is_an_error(self):
        text, error = extract_claude_text({"error": {"message": "boom"}})
        self.assertIsNone(text)
        self.assertIn("unexpected response payload", error)

    def test_max_tokens_truncation_still_returns_partial_text(self):
        text, error = extract_claude_text({
            "stop_reason": "max_tokens",
            "content": [{"type": "text", "text": "[[1,2"}],
        })
        self.assertIsNone(error)
        self.assertEqual(text, "[[1,2")


class TestGeminiPayloadExtraction(unittest.TestCase):
    def test_joins_candidate_parts(self):
        text, error = extract_gemini_text({
            "candidates": [{
                "content": {"parts": [{"text": "[[0,1]"}, {"text": ",[2,3]]"}]},
                "finishReason": "STOP",
            }],
        })
        self.assertIsNone(error)
        self.assertEqual(text, "[[0,1],[2,3]]")

    def test_blocked_prompt_is_an_error(self):
        text, error = extract_gemini_text({
            "promptFeedback": {"blockReason": "SAFETY"},
        })
        self.assertIsNone(text)
        self.assertIn("SAFETY", error)

    def test_no_candidates_is_an_error(self):
        text, error = extract_gemini_text({"candidates": []})
        self.assertIsNone(text)
        self.assertIn("no candidates", error)

    def test_candidate_without_text_names_finish_reason(self):
        text, error = extract_gemini_text({
            "candidates": [{"content": {}, "finishReason": "MAX_TOKENS"}],
        })
        self.assertIsNone(text)
        self.assertIn("MAX_TOKENS", error)


class TestCostEstimates(unittest.TestCase):
    def test_known_model_prices_apply_per_mtok(self):
        cost = _estimate_cost(CLAUDE_PRICES_PER_MTOK, "claude-opus-4-8",
                              1_000_000, 1_000_000)
        self.assertAlmostEqual(cost, 30.0)  # $5 in + $25 out

    def test_unknown_model_costs_zero(self):
        self.assertEqual(
            _estimate_cost(GEMINI_PRICES_PER_MTOK, "mystery-model", 1000, 1000),
            0.0,
        )

    def test_none_token_counts_cost_zero(self):
        self.assertEqual(
            _estimate_cost(CLAUDE_PRICES_PER_MTOK, "claude-opus-4-8", None, None),
            0.0,
        )


class TestProviderResponseContract(unittest.TestCase):
    def test_defaults(self):
        response = ProviderResponse(response_text="x", status=STATUS_OK)
        self.assertIsNone(response.error_message)
        self.assertEqual(response.cost_estimate_usd, 0.0)
        self.assertIsNone(response.input_tokens)
        self.assertIsNone(response.output_tokens)


if __name__ == "__main__":
    unittest.main()

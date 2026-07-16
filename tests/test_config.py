"""Unit tests for src/config.py — run from the repo root:

    python -m unittest discover -s tests -v

All tests control os.environ explicitly (clear=True) so a developer's real
ATLAS_* exports can never change the results.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config  # noqa: E402
from config import ConfigError  # noqa: E402


class TestEnvStr(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_unset_returns_default(self):
        self.assertEqual(config.env_str("ATLAS_MODEL", "fallback"), "fallback")
        self.assertIsNone(config.env_str("ATLAS_MODEL"))

    @patch.dict(os.environ, {"ATLAS_MODEL": "   "}, clear=True)
    def test_whitespace_only_counts_as_unset(self):
        self.assertEqual(config.env_str("ATLAS_MODEL", "fallback"), "fallback")

    @patch.dict(os.environ, {"ATLAS_MODEL": " gpt-4o-mini "}, clear=True)
    def test_value_is_stripped(self):
        self.assertEqual(config.env_str("ATLAS_MODEL"), "gpt-4o-mini")


class TestNumericEnv(unittest.TestCase):
    @patch.dict(os.environ, {"ATLAS_TIMEOUT_S": "120.5"}, clear=True)
    def test_float_parses(self):
        self.assertEqual(config.env_float("ATLAS_TIMEOUT_S", 600.0), 120.5)

    @patch.dict(os.environ, {"ATLAS_TIMEOUT_S": "fast"}, clear=True)
    def test_float_garbage_raises_readable_error(self):
        with self.assertRaises(ConfigError) as ctx:
            config.env_float("ATLAS_TIMEOUT_S", 600.0)
        self.assertIn("ATLAS_TIMEOUT_S", str(ctx.exception))
        self.assertIn("'fast'", str(ctx.exception))

    @patch.dict(os.environ, {"ATLAS_TIMEOUT_S": "-5"}, clear=True)
    def test_float_must_be_positive(self):
        with self.assertRaises(ConfigError):
            config.env_float("ATLAS_TIMEOUT_S", 600.0)

    @patch.dict(os.environ, {"ATLAS_MAX_OUTPUT_TOKENS": "4096"}, clear=True)
    def test_int_parses(self):
        self.assertEqual(config.env_int("ATLAS_MAX_OUTPUT_TOKENS", 16000), 4096)

    @patch.dict(os.environ, {"ATLAS_MAX_OUTPUT_TOKENS": "4k"}, clear=True)
    def test_int_garbage_raises_readable_error(self):
        with self.assertRaises(ConfigError) as ctx:
            config.env_int("ATLAS_MAX_OUTPUT_TOKENS", 16000)
        self.assertIn("ATLAS_MAX_OUTPUT_TOKENS", str(ctx.exception))

    @patch.dict(os.environ, {}, clear=True)
    def test_unset_numeric_returns_default(self):
        self.assertEqual(config.env_float("ATLAS_TIMEOUT_S", 600.0), 600.0)
        self.assertEqual(config.env_int("ATLAS_MAX_OUTPUT_TOKENS", 16000), 16000)


class TestResolvePrecedence(unittest.TestCase):
    @patch.dict(os.environ, {"ATLAS_PROVIDER": "openai"}, clear=True)
    def test_cli_flag_beats_env(self):
        self.assertEqual(config.resolve("claude", "ATLAS_PROVIDER", "mock"),
                         "claude")

    @patch.dict(os.environ, {"ATLAS_PROVIDER": "openai"}, clear=True)
    def test_env_beats_default(self):
        self.assertEqual(config.resolve(None, "ATLAS_PROVIDER", "mock"),
                         "openai")

    @patch.dict(os.environ, {}, clear=True)
    def test_default_when_nothing_set(self):
        self.assertEqual(config.resolve(None, "ATLAS_PROVIDER", "mock"),
                         "mock")


class TestFirstEnv(unittest.TestCase):
    @patch.dict(os.environ,
                {"ATLAS_API_KEY": "generic", "ANTHROPIC_API_KEY": "specific"},
                clear=True)
    def test_earlier_name_wins(self):
        name, value = config.first_env("ANTHROPIC_API_KEY", "ATLAS_API_KEY")
        self.assertEqual((name, value), ("ANTHROPIC_API_KEY", "specific"))

    @patch.dict(os.environ,
                {"ANTHROPIC_API_KEY": "", "ATLAS_API_KEY": "generic"},
                clear=True)
    def test_empty_values_are_skipped(self):
        name, value = config.first_env("ANTHROPIC_API_KEY", "ATLAS_API_KEY")
        self.assertEqual((name, value), ("ATLAS_API_KEY", "generic"))

    @patch.dict(os.environ, {}, clear=True)
    def test_nothing_set(self):
        self.assertEqual(config.first_env("A", "B"), (None, None))


class TestProviderTimeout(unittest.TestCase):
    @patch.dict(os.environ,
                {"OPENAI_TIMEOUT_S": "30", "ATLAS_TIMEOUT_S": "90"},
                clear=True)
    def test_legacy_specific_var_wins(self):
        self.assertEqual(config.provider_timeout(legacy_env="OPENAI_TIMEOUT_S"),
                         30.0)

    @patch.dict(os.environ, {"ATLAS_TIMEOUT_S": "90"}, clear=True)
    def test_generic_var_used_without_legacy(self):
        self.assertEqual(config.provider_timeout(legacy_env="OPENAI_TIMEOUT_S"),
                         90.0)
        self.assertEqual(config.provider_timeout(), 90.0)

    @patch.dict(os.environ, {}, clear=True)
    def test_default(self):
        self.assertEqual(config.provider_timeout(), config.DEFAULT_TIMEOUT_S)


class TestOutputRoot(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_unset_is_none(self):
        self.assertIsNone(config.output_root())

    @patch.dict(os.environ, {"ATLAS_OUTPUT_ROOT": "/tmp/atlas"}, clear=True)
    def test_set_returns_path(self):
        self.assertEqual(config.output_root(), Path("/tmp/atlas"))


class TestValidateChoice(unittest.TestCase):
    def test_valid_value_passes_through(self):
        self.assertEqual(
            config.validate_choice("mock", {"mock", "openai"}, "provider"),
            "mock",
        )

    def test_invalid_value_names_setting_and_options(self):
        with self.assertRaises(ConfigError) as ctx:
            config.validate_choice("bogus", {"mock", "openai"}, "provider",
                                   env_name="ATLAS_PROVIDER")
        message = str(ctx.exception)
        self.assertIn("'bogus'", message)
        self.assertIn("ATLAS_PROVIDER", message)
        self.assertIn("mock", message)


class TestPromptVersionRegistry(unittest.TestCase):
    """The registry lives in prompt_builder but validates through config."""

    def test_default_version_resolves(self):
        from prompt_builder import PROMPT_VERSION_DEFAULT, get_prompt_builder
        self.assertTrue(callable(get_prompt_builder(PROMPT_VERSION_DEFAULT)))

    def test_unknown_version_raises_readable_error(self):
        from prompt_builder import get_prompt_builder
        with self.assertRaises(ConfigError) as ctx:
            get_prompt_builder("arc_grid_v999")
        message = str(ctx.exception)
        self.assertIn("arc_grid_v999", message)
        self.assertIn("arc_grid_v1", message)
        self.assertIn("ATLAS_PROMPT_VERSION", message)


class TestAttemptsConfig(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_default_is_one(self):
        self.assertEqual(config.attempts(), 1)

    @patch.dict(os.environ, {"ATLAS_ATTEMPTS": "2"}, clear=True)
    def test_env_override(self):
        self.assertEqual(config.attempts(), 2)


if __name__ == "__main__":
    unittest.main()

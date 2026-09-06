from __future__ import annotations

import logging
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("test.canvas_improvements")
sys.modules.setdefault("astrbot", astrbot)
sys.modules.setdefault("astrbot.api", api)

from astrbot_plugin_bestnai_x.core.api_errors import describe_api_error, format_api_diagnostic
from astrbot_plugin_bestnai_x.core.generator import (
    AccessBlockedError, APIKeyError, ImageGenerator, ProxyConnectionError,
    QuotaExceededError, RateLimitError, ServerBusyError,
)
from astrbot_plugin_bestnai_x.models.config import GenerationConfig, PluginConfig
from astrbot_plugin_bestnai_x.services.generation_parameters import apply_canvas_generation_overrides


class GenerationDiagnosticsTest(unittest.TestCase):
    def test_http_status_and_response_body_have_distinct_categories(self):
        generator = ImageGenerator(PluginConfig.from_dict({}))
        for status, raw, expected in (
            (403, "Cloudflare: Sorry, you have been blocked", AccessBlockedError),
            (403, "Forbidden", AccessBlockedError),
            (401, "Invalid API key", APIKeyError),
            (403, "Invalid API key", APIKeyError),
            (403, "The origin web server returned an incomplete response to Cloudflare", ServerBusyError),
            (502, "Bad Gateway", ServerBusyError),
            (407, "Proxy Authentication Required", ProxyConnectionError),
            (402, "HTTP 402", QuotaExceededError),
            (429, "rate limit exceeded", RateLimitError),
        ):
            with self.subTest(status=status, raw=raw):
                with self.assertRaises(expected) as caught:
                    generator._raise_for_status(status, raw)
                self.assertEqual(caught.exception.status_code, status)
                self.assertIn(str(status), caught.exception.diagnostic)

    def test_proxy_connection_failure_keeps_a_safe_diagnostic(self):
        generator = ImageGenerator(PluginConfig.from_dict({}))
        error = type("ClientProxyConnectionError", (Exception,), {})("Cannot connect to http://alice:privatepass@proxy.example")
        result = generator._connection_error(error)
        self.assertIsInstance(result, ProxyConnectionError)
        self.assertIn("代理", result.message)
        self.assertNotIn("privatepass", result.diagnostic)
        self.assertNotIn("alice", result.diagnostic)

    def test_diagnostics_redact_tokens_and_proxy_credentials(self):
        raw = "http://alice:privatepass@proxy.example/?api_key=hidden-secret Bearer verylongtoken123 sk-private-secret123 pst-private-token123 token=secret-token456"
        diagnostic = format_api_diagnostic(raw, 403)
        for secret in ("alice", "privatepass", "hidden-secret", "verylongtoken123", "sk-private-secret123", "pst-private-token123", "secret-token456"):
            self.assertNotIn(secret, diagnostic)
        self.assertIn("403", diagnostic)
        self.assertIn("访问", describe_api_error("Cloudflare 403", "生图", status_code=403))


class PerNodeParameterTest(unittest.TestCase):
    def test_reused_empty_negative_and_zero_preset_are_not_defaults(self):
        original = GenerationConfig(negative_prompt="default negative", quality=True)
        result = apply_canvas_generation_overrides(original, {
            "negative_prompt": "", "quality": False, "uc_preset": "0", "image_format": "webp",
        })
        self.assertEqual(result.negative_prompt, "")
        self.assertFalse(result.quality)
        self.assertEqual(result.uc_preset, "heavy")
        self.assertEqual(result.image_format, "webp")
        self.assertEqual(original.negative_prompt, "default negative")
        self.assertIs(apply_canvas_generation_overrides(original, {}), original)

    def test_invalid_reuse_fields_are_rejected(self):
        for payload in ({"negative_prompt": []}, {"negative_prompt": "x" * 6001}, {"uc_preset": "not-a-preset"}, {"image_format": "exe"}):
            with self.subTest(payload=str(payload)[:80]), self.assertRaises(ValueError):
                apply_canvas_generation_overrides(GenerationConfig(), payload)

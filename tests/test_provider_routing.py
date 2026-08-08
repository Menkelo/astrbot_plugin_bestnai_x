from __future__ import annotations

import asyncio
import logging
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


# These modules are optional in the unit-test environment.  The provider
# routing tests exercise the duck-typed compatibility layer, not AstrBot's
# concrete network adapters.
workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
astrbot_module = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
astrbot_api_module = sys.modules.setdefault(
    "astrbot.api", types.ModuleType("astrbot.api")
)
astrbot_api_module.logger = logging.getLogger("test.provider_routing")
astrbot_module.api = astrbot_api_module

from astrbot_plugin_bestnai_x.core.image_retagger import (  # noqa: E402
    ImageRetagError,
    ImageRetagger,
)
from astrbot_plugin_bestnai_x.core.provider_utils import (  # noqa: E402
    call_provider,
    response_text,
)
from astrbot_plugin_bestnai_x.core.safety import SafetyModerator  # noqa: E402
from astrbot_plugin_bestnai_x.core.translator import PromptTranslator  # noqa: E402


class FakeResponse:
    def __init__(self, text: str, role: str = "assistant"):
        self.completion_text = text
        self.role = role


class FakeProvider:
    def __init__(self, response: str = "ok"):
        self.provider_config = {"id": "vision-provider"}
        self.model_name = "fake-vision-model"
        self.response = response
        self.text_chat_calls: list[dict] = []

    def get_model(self) -> str:
        return self.model_name

    async def text_chat(self, **kwargs):
        self.text_chat_calls.append(kwargs)
        return FakeResponse(self.response)

    def meta(self):
        return SimpleNamespace(id="vision-provider")


class FakeContext:
    def __init__(
        self,
        response: str = "ok",
        *,
        with_llm: bool = True,
        llm_error: Exception | None = None,
        response_role: str = "assistant",
    ):
        self.provider = FakeProvider(response)
        self.llm_calls: list[dict] = []
        self.with_llm = with_llm
        self.llm_error = llm_error
        self.response_role = response_role

    def get_provider_by_id(self, provider_id: str):
        return self.provider if provider_id == "vision-provider" else None

    def get_using_provider(self):
        return self.provider

    async def llm_generate(self, **kwargs):
        if not self.with_llm:
            raise NotImplementedError("old AstrBot context")
        self.llm_calls.append(kwargs)
        if self.llm_error is not None:
            raise self.llm_error
        return FakeResponse(self.provider.response, self.response_role)


class LegacySignatureContext(FakeContext):
    async def llm_generate(self, prompt):
        return FakeResponse(str(prompt or ""))


class ProviderRoutingTest(unittest.IsolatedAsyncioTestCase):
    def test_model_features_do_not_rebuild_provider_http_endpoints(self) -> None:
        plugin_root = Path(__file__).resolve().parents[1]
        translator = (plugin_root / "core" / "translator.py").read_text(encoding="utf-8")
        retagger = (plugin_root / "core" / "image_retagger.py").read_text(encoding="utf-8")
        safety = (plugin_root / "core" / "safety.py").read_text(encoding="utf-8")

        for source in (translator, retagger, safety):
            self.assertNotIn("/chat/completions", source)
            self.assertNotIn(":generateContent", source)
        self.assertNotIn("_call_openai_compatible", translator)
        self.assertNotIn("_call_gemini", translator)

    async def test_public_llm_generate_is_preferred(self) -> None:
        context = FakeContext("translated")

        provider_id, provider, response = await call_provider(
            context,
            "vision-provider",
            prompt="蓝头发",
            system_prompt="tags only",
            image_urls=["C:/tmp/source.png"],
            temperature=0.2,
        )

        self.assertEqual(provider_id, "vision-provider")
        self.assertIs(provider, context.provider)
        self.assertEqual(response.completion_text, "translated")
        self.assertEqual(len(context.llm_calls), 1)
        self.assertEqual(context.llm_calls[0]["image_urls"], ["C:/tmp/source.png"])
        self.assertEqual(context.provider.text_chat_calls, [])

    async def test_provider_text_chat_is_compatibility_fallback(self) -> None:
        context = FakeContext("fallback", with_llm=False)

        _, _, response = await call_provider(
            context,
            "vision-provider",
            prompt="describe",
        )

        self.assertEqual(response.completion_text, "fallback")
        self.assertEqual(len(context.provider.text_chat_calls), 1)

    async def test_signature_mismatch_uses_compatibility_fallback(self) -> None:
        context = LegacySignatureContext("fallback")

        _, _, response = await call_provider(
            context,
            "vision-provider",
            prompt="describe",
            system_prompt="tags only",
        )

        self.assertEqual(response.completion_text, "fallback")
        self.assertEqual(len(context.provider.text_chat_calls), 1)

    async def test_real_provider_failure_is_not_sent_twice(self) -> None:
        context = FakeContext(llm_error=RuntimeError("upstream unavailable"))

        with self.assertRaisesRegex(RuntimeError, "upstream unavailable"):
            await call_provider(
                context,
                "vision-provider",
                prompt="describe",
            )

        self.assertEqual(len(context.llm_calls), 1)
        self.assertEqual(context.provider.text_chat_calls, [])

    async def test_error_role_is_raised_instead_of_becoming_tags(self) -> None:
        context = FakeContext(
            "The origin web server returned an invalid response to Cloudflare.",
            response_role="err",
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "origin web server returned an invalid response",
        ):
            await call_provider(
                context,
                "vision-provider",
                prompt="describe",
            )

        self.assertEqual(context.provider.text_chat_calls, [])

    def test_empty_provider_object_does_not_become_pseudo_tags(self) -> None:
        self.assertEqual(response_text(FakeResponse("")), "")

    async def test_raw_error_dictionary_is_raised(self) -> None:
        context = FakeContext()

        async def raw_error(**kwargs):
            context.llm_calls.append(kwargs)
            return {"error": {"message": "provider rejected request"}}

        context.llm_generate = raw_error
        with self.assertRaisesRegex(RuntimeError, "provider rejected request"):
            await call_provider(context, "vision-provider", prompt="describe")
        self.assertEqual(context.provider.text_chat_calls, [])

    async def test_translator_uses_provider_without_raw_endpoint(self) -> None:
        context = FakeContext("blue hair, 1girl")
        config = SimpleNamespace(
            enabled=True,
            provider_id="vision-provider",
            base_url="",
            api_key="",
            model="",
            system_prompt="",
            custom_prefix="",
            max_retries=1,
            is_configured=lambda: True,
        )

        result = await PromptTranslator(config, context=context).translate("蓝头发")

        self.assertEqual(str(result), "blue hair, 1girl")
        self.assertEqual(len(context.llm_calls), 1)

    async def test_image_retagger_passes_image_to_provider(self) -> None:
        context = FakeContext(
            '{"character":"","series":"","tags":"1girl, blue hair"}'
        )
        config = SimpleNamespace(provider_id="vision-provider")

        result = await ImageRetagger(config, context).retag_details("C:/tmp/a.png")

        self.assertEqual(result["prompt"], "1girl, blue hair")
        self.assertEqual(context.llm_calls[0]["image_urls"], ["C:/tmp/a.png"])

    async def test_image_retagger_rejects_empty_provider_response(self) -> None:
        context = FakeContext("")
        config = SimpleNamespace(provider_id="vision-provider")

        with self.assertRaisesRegex(ImageRetagError, "结果为空"):
            await ImageRetagger(config, context).retag_details("C:/tmp/a.png")

    async def test_safety_uses_provider_and_parses_json(self) -> None:
        context = FakeContext('{"safe":false,"reason":"blocked"}')
        config = SimpleNamespace(enabled=True, provider_id="vision-provider")

        result = await SafetyModerator(config, context=context).check_image(b"\x89PNG\r\n")

        self.assertFalse(result.safe)
        self.assertTrue(context.llm_calls[0]["image_urls"][0].startswith("data:image/png;base64,"))

    async def test_safety_without_explicit_provider_does_not_use_active_chat(self) -> None:
        context = FakeContext('{"safe":false,"reason":"blocked"}')
        config = SimpleNamespace(enabled=True, provider_id="")

        result = await SafetyModerator(config, context=context).check_image(b"\x89PNG\r\n")

        self.assertTrue(result.safe)
        self.assertEqual(result.source, "provider_unconfigured")
        self.assertEqual(context.llm_calls, [])
        self.assertEqual(context.provider.text_chat_calls, [])


if __name__ == "__main__":
    unittest.main()

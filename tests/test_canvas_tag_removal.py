from __future__ import annotations

import __future__
import ast
import asyncio
import copy
import logging
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("test.canvas_tag_removal")
sys.modules.setdefault("astrbot", astrbot)
sys.modules.setdefault("astrbot.api", api)

from astrbot_plugin_bestnai_x.core.char_prompts import automatic_char_layout, normalize_char_entries
from astrbot_plugin_bestnai_x.core.debug_trace import DebugTrace
from astrbot_plugin_bestnai_x.core.generator import GenerationError
from astrbot_plugin_bestnai_x.core.novelai_api import build_generate_payload
from astrbot_plugin_bestnai_x.core.prompt_tokens import normalize_count_tokens
from astrbot_plugin_bestnai_x.models.config import MODEL_V45_FULL, PluginConfig, TranslatorConfig, resolve_model_choice
from astrbot_plugin_bestnai_x.services.generation_parameters import apply_canvas_generation_overrides
from astrbot_plugin_bestnai_x.services.prompt_builder import PromptBuilder
from astrbot_plugin_bestnai_x.services.prompt_merge import (
    MAX_RETAG_DROP_TAGS,
    RETAG_LAYER_CATEGORIES,
    filter_retag_prompt,
    merge_retag_prompt_details,
    normalize_retag_layer_categories,
)


logger = logging.getLogger("test.canvas_tag_removal")
CHARACTER = "ganyu_(genshin_impact)"
SOURCE = f"1.3::{CHARACTER}, rolua, nuegochi ::, yoneyama_mai, 0.7::sixii"


class CanvasTagRemovalTest(unittest.IsolatedAsyncioTestCase):
    """Exercise the production canvas handler up to the generator request boundary."""

    @classmethod
    def setUpClass(cls):
        # Defer this import until collection has finished: the HTTP failover
        # tests replace other modules' aiohttp stubs with the real local client.
        from astrbot_plugin_bestnai_x.core import translator

        # Importing the plugin entry point requires a running AstrBot host.
        # Compile its real handlers and constants, replacing only host/provider services.
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        function_names = {
            "_canvas_generate", "_clamp_steps", "_clamp_scale", "_with_debug", "_unsupported_sampler_error",
        }
        functions = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in function_names
        ]
        for function in functions:
            function.decorator_list = []
        constants = [
            node for node in tree.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id in {
                "MIN_STEPS", "MAX_STEPS", "MIN_SCALE", "MAX_SCALE",
            } for target in node.targets)
        ]
        namespace = dict(globals())
        namespace.update({
            name: getattr(translator, name) for name in (
                "apply_character_candidate", "has_chinese", "prompt_has_tag", "resolve_translation_cache",
            )
        })
        module = ast.Module(body=[*constants, *functions], type_ignores=[])
        exec(compile(module, str(ROOT / "main.py"), "exec", flags=__future__.annotations.compiler_flag), namespace)
        cls.handlers = namespace

    async def asyncSetUp(self):
        config = PluginConfig(
            api_url="https://fixture.invalid", api_key="fixture-key", prompt_suffix="",
            translator=TranslatorConfig(enabled=True, provider_id="fixture"),
        )
        self.generator = AsyncMock(return_value=types.SimpleNamespace(images=[("png", b"fixture")], seed=123))
        self.plugin = types.SimpleNamespace(
            plugin_config=config,
            default_ratio="2:3",
            prompt_builder=PromptBuilder(config, lambda ratio: (832, 1216)),
            generator=types.SimpleNamespace(generate=self.generator),
            _generation_semaphore=asyncio.Semaphore(1),
            _clamp_steps=self.handlers["_clamp_steps"],
            _clamp_scale=self.handlers["_clamp_scale"],
            _provider_credentials_for_model=lambda model: ("https://fixture.invalid", "fixture-key"),
            _resolve_prompt_identity_details=AsyncMock(return_value=("", "", [])),
            _translate_prompt_with_reason=AsyncMock(return_value=("smile", "")),
            _get_effective_artist_prompt=lambda: "",
            _get_default_artist_display_name=lambda: "",
            _display_ratio_label=lambda ratio, width, height: ratio,
        )
        self.plugin._with_debug = lambda trace, result: self.handlers["_with_debug"](self.plugin, trace, result)

    async def generate(self, **overrides):
        payload = {
            "prompt": "outdoors", "retagPrompt": SOURCE, "retagDropTags": [CHARACTER],
            "model": MODEL_V45_FULL, "artist": "__none__", "debug": True, **overrides,
        }
        original = copy.deepcopy(payload)
        images, meta = await self.handlers["_canvas_generate"](self.plugin, payload)
        self.assertEqual(payload, original)
        self.assertEqual(images, [("png", b"fixture")])
        prompt, config = self.generator.await_args.args
        self.assertEqual(meta["finalPrompt"], prompt)
        self.assertEqual(meta["retagPrompt"], payload["retagPrompt"])
        return prompt, config, meta

    async def test_removed_character_never_reaches_normal_or_raw_generation(self):
        for raw in (False, True):
            for source in (f"{CHARACTER}, rolua, nuegochi", SOURCE):
                with self.subTest(raw=raw, source=source):
                    prompt, _, meta = await self.generate(raw=raw, retagPrompt=source)
                    self.assertNotIn(CHARACTER, prompt)
                    self.assertIn("rolua", prompt)
                    self.assertIn("nuegochi", prompt)
                    self.assertIn("outdoors", prompt)
                    if source == SOURCE:
                        self.assertIn("1.3::rolua, nuegochi ::", prompt)
                        self.assertIn("0.7::sixii", prompt)
                    if not raw:
                        self.assertIn(CHARACTER, meta["debug"]["notes"]["提示词冲突处理"]["removed"])

    async def test_cached_translation_and_restoring_a_tag_use_current_removals(self):
        for raw in (False, True):
            with self.subTest(raw=raw):
                options = {
                    "prompt": "微笑", "raw": raw, "rawTranslate": raw,
                    "translationSource": "微笑", "cachedTranslationSource": "微笑",
                    "cachedTranslation": "smile",
                }
                removed, _, _ = await self.generate(**options)
                restored, _, _ = await self.generate(**options, retagDropTags=[])
                self.assertNotIn(CHARACTER, removed)
                self.assertIn(CHARACTER, restored)
                self.assertIn("smile", removed)
                self.plugin._translate_prompt_with_reason.assert_not_awaited()

    async def test_raw_category_removal_keeps_handwritten_tags_literal(self):
        prompt, _, _ = await self.generate(
            raw=True, prompt="1.70::white_dress, white_dress ::",
            retagPrompt=f"1.2::{CHARACTER}, school_uniform, rolua ::",
            retagDropCategories=["clothing"],
        )
        self.assertEqual(prompt, "1.70::white_dress, white_dress ::, 1.2::rolua ::")

    async def test_structured_characters_cannot_restore_a_removed_positive_tag(self):
        characters = [{
            "prompt": f"1.1::{CHARACTER}, blue_hair ::",
            "negative_prompt": f"{CHARACTER}, blurry", "center": {"x": .17, "y": .53},
        }, {
            "prompt": "red_hair", "negative_prompt": "closed_eyes", "center": {"x": .8, "y": .5},
        }]
        for raw in (False, True):
            with self.subTest(raw=raw):
                prompt, config, meta = await self.generate(raw=raw, retagCharPrompts=characters)
                self.assertNotIn(CHARACTER, prompt)
                self.assertEqual(config.characters[0]["prompt"], "1.1::blue_hair ::")
                self.assertEqual(config.characters[0]["negative_prompt"], f"{CHARACTER}, blurry")
                self.assertEqual(config.characters[0]["center"], {"x": .17, "y": .53})
                self.assertEqual(config.characters[1]["prompt"], "red_hair")
                self.assertEqual(meta["characterPrompts"], config.characters)
                self.assertTrue(config.use_coords)
                request = build_generate_payload(prompt, config)
                self.assertNotIn(CHARACTER, request["input"])
                captions = request["parameters"]["v4_prompt"]["caption"]["char_captions"]
                self.assertTrue(all(CHARACTER not in item["char_caption"] for item in captions))
                negatives = request["parameters"]["v4_negative_prompt"]["caption"]["char_captions"]
                self.assertEqual(negatives[0]["char_caption"], f"{CHARACTER}, blurry")

    async def test_translated_character_caption_is_filtered_after_translation(self):
        self.plugin._translate_prompt_with_reason.return_value = (f"{CHARACTER}, blue_hair", "")
        _, config, _ = await self.generate(retagCharPrompts=[{"prompt": "甘雨，蓝发", "negative_prompt": "blurry"}])
        self.assertEqual(config.characters[0]["prompt"], "blue_hair")
        self.assertEqual(config.characters[0]["negative_prompt"], "blurry")

    async def test_removed_empty_character_keeps_remaining_coordinates_and_negative_pairing(self):
        _, config, _ = await self.generate(retagCharPrompts=[
            {"prompt": CHARACTER, "negative_prompt": "first negative", "center": {"x": .1, "y": .5}},
            {"prompt": "red_hair", "negative_prompt": "second negative", "center": {"x": .9, "y": .5}},
        ])
        self.assertEqual(len(config.characters), 1)
        self.assertEqual(config.characters[0]["negative_prompt"], "second negative")
        self.assertEqual(config.characters[0]["center"], {"x": .9, "y": .5})
        self.assertFalse(config.use_coords)
        self.assertTrue(config.use_order)
        _, config, _ = await self.generate(retagCharPrompts=[{"prompt": CHARACTER}])
        self.assertEqual(config.characters, [])

    async def test_explicit_handwritten_tag_and_negative_prompt_are_not_removed(self):
        for raw in (False, True):
            with self.subTest(raw=raw):
                prompt, config, _ = await self.generate(raw=raw, prompt=CHARACTER, negative_prompt=CHARACTER)
                self.assertEqual(prompt.count(CHARACTER), 1)
                self.assertEqual(config.negative_prompt, CHARACTER)
        _, config, _ = await self.generate(retagPrompt="", retagCharPrompts=[{"prompt": CHARACTER}])
        self.assertEqual(config.characters[0]["prompt"], CHARACTER)

    async def test_removing_all_raw_source_tags_stops_before_generation(self):
        with self.assertRaisesRegex(ValueError, "提示词清理后为空"):
            await self.generate(raw=True, prompt="", retagPrompt=CHARACTER)
        self.generator.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()

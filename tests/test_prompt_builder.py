from __future__ import annotations

import logging
import sys
import types
import unittest
from pathlib import Path


astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("test.prompt_builder")
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.models.config import (  # noqa: E402
    GenerationConfig,
    PluginConfig,
    model_supports_cjk,
)
from astrbot_plugin_bestnai_x.services.prompt_builder import (  # noqa: E402
    PromptBuilder,
    normalize_prompt_ascii,
)
from dataclasses import replace  # noqa: E402


class FakePluginConfig:
    def get_generation_config_for_version(self, version: str) -> GenerationConfig:
        return GenerationConfig(negative_prompt="custom negative")


class PromptBuilderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = PromptBuilder(FakePluginConfig(), lambda _: (832, 1216))

    def test_canvas_can_skip_qq_safe_negative_tags(self) -> None:
        config = self.builder.build_generation_config(
            "2:3",
            apply_safe_negative=False,
        )

        self.assertEqual(config.negative_prompt, "custom negative")

    def test_qq_path_keeps_safe_negative_tags_by_default(self) -> None:
        config = self.builder.build_generation_config("2:3")

        self.assertIn("custom negative", config.negative_prompt)
        self.assertIn("nsfw", config.negative_prompt)


class CjkPromptSupportTest(unittest.TestCase):
    def test_v5_models_support_cjk_but_45_does_not(self) -> None:
        self.assertTrue(model_supports_cjk("nai-diffusion-5-full"))
        self.assertTrue(model_supports_cjk("nai-diffusion-5-curated"))
        self.assertFalse(model_supports_cjk("nai-diffusion-4-5-full"))
        self.assertFalse(model_supports_cjk(""))

    def test_normalize_keeps_non_ascii_only_when_asked(self) -> None:
        text = "1girl, 蓝发少女，"

        self.assertEqual(normalize_prompt_ascii(text), "1girl")
        self.assertEqual(
            normalize_prompt_ascii(text, keep_non_ascii=True),
            "1girl, 蓝发少女",
        )

    def test_final_prompt_keeps_chinese_on_v5_and_strips_on_45(self) -> None:
        plugin_config = PluginConfig.from_dict({})

        plugin_config.generation = replace(
            plugin_config.generation, model="nai-diffusion-5-full"
        )
        v5_builder = PromptBuilder(plugin_config, lambda _: (832, 1216))
        self.assertIn(
            "蓝发少女",
            v5_builder.build_final_prompt("蓝发少女", "", ""),
        )
        self.assertNotIn(
            "，",
            v5_builder.build_final_prompt("蓝发少女，", "", ""),
        )

        plugin_config.generation = replace(
            plugin_config.generation, model="nai-diffusion-4-5-full"
        )
        v45_builder = PromptBuilder(plugin_config, lambda _: (832, 1216))
        self.assertEqual(v45_builder.build_final_prompt("蓝发少女", "", ""), "")


if __name__ == "__main__":
    unittest.main()

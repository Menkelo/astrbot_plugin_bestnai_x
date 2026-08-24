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


class ModelCapabilityTest(unittest.TestCase):
    def test_v5_detected_for_provider_routing(self) -> None:
        # model_supports_cjk 现在只服务于 V5 提供商槽位路由，
        # 语言处理（翻译/清理）不再按模型区分
        self.assertTrue(model_supports_cjk("nai-diffusion-5-full"))
        self.assertTrue(model_supports_cjk("nai-diffusion-5-curated"))
        self.assertFalse(model_supports_cjk("nai-diffusion-4-5-full"))
        self.assertFalse(model_supports_cjk(""))

    def test_normalize_strips_non_ascii_for_all_models(self) -> None:
        text = "1girl, 蓝发少女，"

        self.assertEqual(normalize_prompt_ascii(text), "1girl")

    def test_final_prompt_strips_chinese_regardless_of_model(self) -> None:
        plugin_config = PluginConfig.from_dict({})
        plugin_config.generation = replace(
            plugin_config.generation, model="nai-diffusion-5-full"
        )
        builder = PromptBuilder(plugin_config, lambda _: (832, 1216))

        self.assertEqual(builder.build_final_prompt("蓝发少女", "", ""), "")


if __name__ == "__main__":
    unittest.main()

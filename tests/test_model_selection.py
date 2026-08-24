from __future__ import annotations

import logging
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path


astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("test.model_selection")
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.models.config import (  # noqa: E402
    FIXED_MODEL,
    MODEL_V45_FULL,
    MODEL_V5_FULL,
    GenerationConfig,
    PluginConfig,
)
from astrbot_plugin_bestnai_x.services.prompt_builder import PromptBuilder  # noqa: E402


class ModelSelectionTest(unittest.TestCase):
    def test_default_model_is_v45_full(self) -> None:
        config = PluginConfig.from_dict({})

        self.assertEqual(config.generation.model, MODEL_V45_FULL)
        self.assertEqual(FIXED_MODEL, MODEL_V45_FULL)

    def test_provider_model_flows_into_api_params(self) -> None:
        # 生图模型跟随接口提供商，运行时写入 generation.model
        config = PluginConfig.from_dict({})
        config.generation = replace(config.generation, model=MODEL_V5_FULL)

        versioned = config.get_generation_config_for_version("4.5")
        self.assertEqual(versioned.model, MODEL_V5_FULL)

        params = versioned.to_api_params("1girl")
        self.assertEqual(params["model"], MODEL_V5_FULL)

    def test_prompt_builder_keeps_provider_model(self) -> None:
        plugin_config = PluginConfig.from_dict({})
        plugin_config.generation = replace(
            plugin_config.generation, model=MODEL_V5_FULL
        )
        builder = PromptBuilder(plugin_config, lambda _: (832, 1216))

        gen_config = builder.build_generation_config("2:3")

        self.assertEqual(gen_config.model, MODEL_V5_FULL)

    def test_generation_config_default_uses_fixed_model(self) -> None:
        gen_config = GenerationConfig()

        self.assertEqual(gen_config.model, FIXED_MODEL)


if __name__ == "__main__":
    unittest.main()

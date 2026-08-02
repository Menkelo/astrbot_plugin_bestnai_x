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

workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

safety_module = types.ModuleType("astrbot_plugin_bestnai_x.core.safety")
safety_module.append_safe_negative = lambda prompt: f"{prompt}, nsfw"
sys.modules.setdefault("astrbot_plugin_bestnai_x.core.safety", safety_module)

from astrbot_plugin_bestnai_x.models.config import GenerationConfig
from astrbot_plugin_bestnai_x.services.prompt_builder import PromptBuilder


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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import logging
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path


astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("test.studio_overrides")
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.models.config import GenerationConfig
from astrbot_plugin_bestnai_x.services.prompt_builder import (
    ALLOWED_NOISE_SCHEDULES,
    ALLOWED_SAMPLERS,
    apply_generation_overrides,
)


class ApplyGenerationOverridesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.base = GenerationConfig()

    def test_empty_overrides_keep_config(self) -> None:
        self.assertIs(apply_generation_overrides(self.base), self.base)

    def test_valid_sampler_and_noise_schedule_are_applied(self) -> None:
        result = apply_generation_overrides(
            self.base,
            sampler="k_dpmpp_2m",
            noise_schedule="exponential",
        )
        self.assertEqual(result.sampler, "k_dpmpp_2m")
        self.assertEqual(result.noise_schedule, "exponential")

    def test_invalid_sampler_is_ignored(self) -> None:
        result = apply_generation_overrides(self.base, sampler="ddim hack")
        self.assertEqual(result.sampler, self.base.sampler)

    def test_invalid_noise_schedule_is_ignored(self) -> None:
        result = apply_generation_overrides(self.base, noise_schedule="linear")
        self.assertEqual(result.noise_schedule, self.base.noise_schedule)

    def test_cfg_rescale_is_clamped_to_unit_range(self) -> None:
        self.assertEqual(
            apply_generation_overrides(self.base, cfg_rescale=1.7).cfg_rescale,
            1.0,
        )
        self.assertEqual(
            apply_generation_overrides(self.base, cfg_rescale=-2).cfg_rescale,
            0.0,
        )

    def test_non_numeric_cfg_rescale_is_ignored(self) -> None:
        result = apply_generation_overrides(self.base, cfg_rescale="high")
        self.assertEqual(result.cfg_rescale, self.base.cfg_rescale)

    def test_negative_prompt_is_ascii_cleaned(self) -> None:
        result = apply_generation_overrides(
            self.base,
            negative_prompt="lowres，bad hands　，",
        )
        self.assertEqual(result.negative_prompt, "lowres, bad hands")

    def test_whitespace_negative_prompt_keeps_default(self) -> None:
        result = apply_generation_overrides(self.base, negative_prompt="   ")
        self.assertEqual(result.negative_prompt, self.base.negative_prompt)

    def test_other_generation_fields_survive_overrides(self) -> None:
        tuned = replace(self.base, steps=12, scale=5.0)
        result = apply_generation_overrides(tuned, sampler="k_euler")
        self.assertEqual((result.steps, result.scale), (12, 5.0))


class StudioWhitelistTest(unittest.TestCase):
    def test_whitelists_are_stable_ordered_lists(self) -> None:
        # 列表顺序即 Studio 下拉框的展示顺序，前端也依赖这些值。
        self.assertEqual(ALLOWED_SAMPLERS[0], "k_euler_ancestral")
        self.assertEqual(ALLOWED_NOISE_SCHEDULES[0], "karras")
        self.assertEqual(len(set(ALLOWED_SAMPLERS)), len(ALLOWED_SAMPLERS))
        self.assertEqual(
            len(set(ALLOWED_NOISE_SCHEDULES)),
            len(ALLOWED_NOISE_SCHEDULES),
        )


if __name__ == "__main__":
    unittest.main()

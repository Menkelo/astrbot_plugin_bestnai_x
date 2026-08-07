from __future__ import annotations

import logging
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
workspace_dir = ROOT.parent
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("test.prompt_merge")
astrbot_module.api = astrbot_api_module
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)

from astrbot_plugin_bestnai_x.services.prompt_merge import merge_retag_prompt


class PromptOverrideMergeTest(unittest.TestCase):
    source = (
        "kasumigaoka_utaha, saenai_heroine_no_sodatekata, black_hair, "
        "school_uniform, sitting, classroom"
    )

    def test_character_replacement_removes_old_identity_and_signature(self) -> None:
        result = merge_retag_prompt(
            "change to izumi_sagiri",
            self.source,
            original_user_prompt="换成埃罗芒阿老师",
            weight_user=False,
        )

        self.assertIn("izumi_sagiri", result)
        self.assertIn("sitting", result)
        self.assertIn("classroom", result)
        self.assertNotIn("kasumigaoka_utaha", result)
        self.assertNotIn("saenai_heroine_no_sodatekata", result)
        self.assertNotIn("black_hair", result)
        self.assertNotIn("school_uniform", result)

    def test_clothing_override_only_removes_clothing_category(self) -> None:
        result = merge_retag_prompt(
            "change outfit to white_dress",
            self.source,
            weight_user=False,
        )

        self.assertIn("white_dress", result)
        self.assertIn("kasumigaoka_utaha", result)
        self.assertIn("black_hair", result)
        self.assertIn("sitting", result)
        self.assertNotIn("school_uniform", result)

    def test_pose_override_only_removes_pose_category(self) -> None:
        result = merge_retag_prompt(
            "change pose to standing",
            self.source,
            weight_user=False,
        )

        self.assertIn("standing", result)
        self.assertIn("school_uniform", result)
        self.assertIn("classroom", result)
        self.assertNotIn("sitting", result)

    def test_plain_additive_prompt_keeps_unmentioned_source_tags(self) -> None:
        result = merge_retag_prompt(
            "blue_hair",
            self.source,
            weight_user=False,
        )

        self.assertIn("blue_hair", result)
        self.assertIn("school_uniform", result)
        self.assertIn("sitting", result)
        self.assertNotIn("black_hair", result)

    def test_duplicate_tags_are_kept_once(self) -> None:
        result = merge_retag_prompt(
            "classroom, blue_hair",
            self.source,
            weight_user=False,
        )

        self.assertEqual(result.count("classroom"), 1)
        self.assertEqual(result.count("blue_hair"), 1)

    def test_character_replacement_does_not_drop_generic_subject_tags(self) -> None:
        result = merge_retag_prompt(
            "change to izumi_sagiri",
            "1girl, solo, black_hair, school_uniform, sitting, classroom",
            weight_user=False,
        )

        self.assertIn("1girl", result)
        self.assertIn("solo", result)
        self.assertIn("sitting", result)
        self.assertNotIn("black_hair", result)
        self.assertNotIn("school_uniform", result)


if __name__ == "__main__":
    unittest.main()

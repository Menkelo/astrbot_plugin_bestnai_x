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

    def test_extended_clothing_and_expression_tags_are_overridden(self) -> None:
        result = merge_retag_prompt(
            "change outfit to gothic_lolita, smirk",
            "1girl, long_sleeves, gothic_lolita, smile, classroom",
            weight_user=False,
        )

        self.assertIn("gothic_lolita", result)
        self.assertIn("smirk", result)
        self.assertNotIn("long_sleeves", result)
        self.assertNotIn("smile", result)
        self.assertIn("classroom", result)

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

    def test_resolved_character_name_forces_identity_replacement_without_verb(self) -> None:
        result = merge_retag_prompt(
            "izumi_sagiri, eromanga_sensei",
            self.source,
            original_user_prompt="埃罗芒阿老师",
            user_character="izumi_sagiri",
            user_series="eromanga_sensei",
            weight_user=False,
        )

        self.assertIn("izumi_sagiri", result)
        self.assertIn("eromanga_sensei", result)
        self.assertNotIn("kasumigaoka_utaha", result)
        self.assertNotIn("saenai_heroine_no_sodatekata", result)

    def test_structured_identity_does_not_remove_leading_pose_or_expression(self) -> None:
        result = merge_retag_prompt(
            "izumi_sagiri, eromanga_sensei",
            (
                "smile, looking_at_viewer, kasumigaoka_utaha, "
                "saenai_heroine_no_sodatekata, black_hair, school_uniform, sunset"
            ),
            user_character="izumi_sagiri",
            user_series="eromanga_sensei",
            source_character="kasumigaoka_utaha",
            source_series="saenai_heroine_no_sodatekata",
            weight_user=False,
        )

        self.assertIn("smile", result)
        self.assertIn("looking_at_viewer", result)
        self.assertIn("sunset", result)
        self.assertNotIn("kasumigaoka_utaha", result)

    def test_unstructured_fallback_preserves_categorized_leading_tags(self) -> None:
        result = merge_retag_prompt(
            "izumi_sagiri, eromanga_sensei",
            "smile, looking_at_viewer, sunset, outdoors",
            user_character="izumi_sagiri",
            user_series="eromanga_sensei",
            weight_user=False,
        )

        self.assertIn("smile", result)
        self.assertIn("looking_at_viewer", result)
        self.assertIn("sunset", result)

    def test_unstructured_fallback_removes_both_old_identity_tags_after_subject_count(self) -> None:
        result = merge_retag_prompt(
            "change to izumi_sagiri",
            "1girl, kasumigaoka_utaha, saenai_heroine_no_sodatekata, black_hair, sitting, classroom",
            weight_user=False,
        )

        self.assertNotIn("kasumigaoka_utaha", result)
        self.assertNotIn("saenai_heroine_no_sodatekata", result)
        self.assertIn("sitting", result)
        self.assertIn("classroom", result)

    def test_weighted_source_group_is_not_split_or_malformed(self) -> None:
        result = merge_retag_prompt(
            "change to izumi_sagiri",
            "1.2::kasumigaoka_utaha, saenai_heroine_no_sodatekata ::, black_hair, sitting",
            weight_user=False,
        )

        self.assertIn("izumi_sagiri", result)
        self.assertIn("sitting", result)
        self.assertNotIn("kasumigaoka_utaha", result)
        self.assertNotIn("saenai_heroine_no_sodatekata", result)
        self.assertNotIn("::,", result)


if __name__ == "__main__":
    unittest.main()

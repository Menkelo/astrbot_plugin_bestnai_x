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

from astrbot_plugin_bestnai_x.services.prompt_merge import (
    MAX_RETAG_DROP_TAGS,
    extract_retag_mode,
    group_prompt_tags,
    merge_retag_prompt,
    merge_retag_prompt_details,
    normalize_retag_layer_tags,
)


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
        details = merge_retag_prompt_details(
            "classroom, blue_hair",
            self.source,
            weight_user=False,
        )
        result = details["prompt"]

        self.assertEqual(result.count("classroom"), 1)
        self.assertEqual(result.count("blue_hair"), 1)
        self.assertIn("classroom", details["duplicates"])
        self.assertIn("classroom", details["retained"])
        self.assertNotIn("classroom", details["added"])
        self.assertNotIn("classroom", details["removed"])
        self.assertNotIn("classroom", details["conflicts"].get("background", []))

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

    def test_legacy_replicate_mode_now_uses_edit_conflict_rules(self) -> None:
        result = merge_retag_prompt(
            "blue_hair, white_dress, standing",
            self.source,
            weight_user=False,
            mode="replicate",
        )

        self.assertIn("blue_hair", result)
        self.assertIn("white_dress", result)
        self.assertIn("standing", result)
        self.assertNotIn("black_hair", result)
        self.assertNotIn("school_uniform", result)
        self.assertNotIn("sitting", result)

    def test_legacy_replicate_mode_normalizes_to_edit_in_details(self) -> None:
        details = merge_retag_prompt_details(
            "change outfit to white_dress",
            self.source,
            weight_user=False,
            mode="replicate",
        )

        self.assertEqual(details["mode"], "edit")
        self.assertIn("white_dress", details["prompt"])
        self.assertNotIn("school_uniform", details["prompt"])

    def test_extended_categories_are_overridden_in_edit_mode(self) -> None:
        result = merge_retag_prompt(
            "close-up, outdoors, dramatic_lighting, watercolor",
            "1girl, full_body, classroom, soft_lighting, realistic, sunset",
            weight_user=False,
        )

        self.assertIn("close-up", result)
        self.assertIn("outdoors", result)
        self.assertIn("dramatic_lighting", result)
        self.assertIn("watercolor", result)
        self.assertNotIn("full_body", result)
        self.assertNotIn("classroom", result)
        self.assertNotIn("soft_lighting", result)
        self.assertNotIn("realistic", result)
        self.assertIn("sunset", result)

    def test_merge_details_expose_conflicts_for_preview(self) -> None:
        details = merge_retag_prompt_details(
            "change to izumi_sagiri, change pose to standing",
            self.source,
            weight_user=False,
        )

        self.assertEqual(details["mode"], "edit")
        self.assertIn("izumi_sagiri", details["added"])
        self.assertIn("kasumigaoka_utaha", details["removed"])
        self.assertIn("sitting", details["removed"])
        self.assertIn("identity", details["overrides"])
        self.assertIn("pose", details["overrides"])
        self.assertIn("identity", details["conflicts"])
        self.assertIn("pose", details["conflicts"])

    def test_retag_mode_flag_is_explicit_and_removed_from_prompt(self) -> None:
        mode, prompt = extract_retag_mode("--mode replicate blue_hair, standing")

        self.assertEqual(mode, "edit")
        self.assertEqual(prompt, "blue_hair, standing")

    def test_retag_mode_flag_accepts_prompt_punctuation(self) -> None:
        cases = (
            ("--mode replicate, blue_hair", "blue_hair"),
            ("blue_hair, --mode replicate", "blue_hair"),
            ("blue_hair, --mode replicate, standing", "blue_hair, standing"),
            ("--mode：复刻；蓝头发", "蓝头发"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                mode, prompt = extract_retag_mode(value)
                self.assertEqual(mode, "edit")
                self.assertEqual(prompt, expected)

    def test_weighted_multi_category_overlay_is_emitted_once(self) -> None:
        details = merge_retag_prompt_details(
            "1.2::white_dress, standing ::",
            "1girl, school_uniform, sitting, classroom",
            weight_user=False,
        )

        self.assertEqual(details["prompt"].count("1.2::white_dress, standing ::"), 1)
        self.assertEqual(details["overrides"]["clothing"], ["white_dress"])
        self.assertEqual(details["overrides"]["pose"], ["standing"])
        self.assertNotIn("school_uniform", details["prompt"])
        self.assertNotIn("sitting", details["prompt"])

    def test_generic_change_verb_routes_visual_target_to_its_category(self) -> None:
        details = merge_retag_prompt_details(
            "change to white_dress",
            self.source,
            source_character="kasumigaoka_utaha",
            source_series="saenai_heroine_no_sodatekata",
            weight_user=False,
        )

        self.assertIn("white_dress", details["prompt"])
        self.assertIn("kasumigaoka_utaha", details["prompt"])
        self.assertIn("saenai_heroine_no_sodatekata", details["prompt"])
        self.assertIn("black_hair", details["prompt"])
        self.assertNotIn("school_uniform", details["prompt"])
        self.assertNotIn("identity", details["overrides"])
        self.assertEqual(details["overrides"]["clothing"], ["white_dress"])

    def test_hair_override_preserves_other_appearance_traits(self) -> None:
        result = merge_retag_prompt(
            "blonde_hair",
            "1girl, black_hair, blue_eyes, cat_ears, glasses, classroom",
            weight_user=False,
        )

        self.assertIn("blonde_hair", result)
        self.assertNotIn("black_hair", result)
        self.assertIn("blue_eyes", result)
        self.assertIn("cat_ears", result)
        self.assertIn("glasses", result)

    def test_outfit_override_preserves_footwear_and_handwear(self) -> None:
        result = merge_retag_prompt(
            "white_dress",
            "1girl, black_dress, brown_boots, black_gloves, classroom",
            weight_user=False,
        )

        self.assertIn("white_dress", result)
        self.assertNotIn("black_dress", result)
        self.assertIn("brown_boots", result)
        self.assertIn("black_gloves", result)

    def test_posture_override_preserves_gaze_and_gesture(self) -> None:
        result = merge_retag_prompt(
            "standing",
            "1girl, sitting, holding_book, looking_at_viewer, classroom",
            weight_user=False,
        )

        self.assertIn("standing", result)
        self.assertNotIn("sitting", result)
        self.assertIn("holding_book", result)
        self.assertIn("looking_at_viewer", result)

    def test_atmosphere_override_preserves_location(self) -> None:
        result = merge_retag_prompt(
            "night",
            "1girl, classroom, day, soft_lighting",
            weight_user=False,
        )

        self.assertIn("night", result)
        self.assertNotIn("day", result)
        self.assertIn("classroom", result)
        self.assertIn("soft_lighting", result)

    def test_pose_override_removes_common_kneeling_and_stance_tags(self) -> None:
        result = merge_retag_prompt(
            "standing",
            "1girl, squatting, on_one_knee, battoujutsu_stance, holding_sword, looking_at_viewer",
            weight_user=False,
        )

        self.assertIn("standing", result)
        self.assertNotIn("squatting", result)
        self.assertNotIn("on_one_knee", result)
        self.assertNotIn("battoujutsu_stance", result)
        self.assertIn("holding_sword", result)
        self.assertIn("looking_at_viewer", result)

    def test_outfit_override_removes_clothing_detail_tags(self) -> None:
        result = merge_retag_prompt(
            "white_dress",
            "1girl, pink_dress, frills, clothing_cutout, puffy_sleeves, black_boots",
            weight_user=False,
        )

        self.assertIn("white_dress", result)
        self.assertNotIn("pink_dress", result)
        self.assertNotIn("frills", result)
        self.assertNotIn("clothing_cutout", result)
        self.assertNotIn("puffy_sleeves", result)
        self.assertIn("black_boots", result)

    def test_style_override_removes_common_retag_style_controls(self) -> None:
        result = merge_retag_prompt(
            "watercolor",
            "1girl, anime_coloring, official_art, flat_color, classroom",
            weight_user=False,
        )

        self.assertIn("watercolor", result)
        self.assertNotIn("anime_coloring", result)
        self.assertNotIn("official_art", result)
        self.assertNotIn("flat_color", result)
        self.assertIn("classroom", result)

    def test_directive_cleanup_does_not_remove_words_containing_to_or_by(self) -> None:
        result = merge_retag_prompt(
            "change pose to standing, stone_wall, by_the_window",
            "1girl, sitting, classroom",
            weight_user=False,
        )

        self.assertIn("standing", result)
        self.assertIn("stone_wall", result)
        self.assertIn("by_the_window", result)
        self.assertNotIn("sitting", result)

    def test_legacy_mode_flag_does_not_treat_chair_as_a_hair_directive(self) -> None:
        result = merge_retag_prompt(
            "wooden_chair beside_window",
            "1girl, black_hair, school_uniform, sitting",
            weight_user=False,
            mode="replicate",
        )

        self.assertIn("wooden_chair beside_window", result)
        self.assertIn("black_hair", result)
        self.assertIn("school_uniform", result)

    def test_source_tags_are_grouped_with_structured_identity(self) -> None:
        groups = group_prompt_tags(
            self.source,
            character="kasumigaoka_utaha",
            series="saenai_heroine_no_sodatekata",
        )

        self.assertEqual(
            groups["identity"],
            ["kasumigaoka_utaha", "saenai_heroine_no_sodatekata"],
        )
        self.assertEqual(groups["hair"], ["black_hair"])
        self.assertEqual(groups["clothing"], ["school_uniform"])
        self.assertEqual(groups["pose"], ["sitting"])
        self.assertEqual(groups["background"], ["classroom"])

    def test_locked_clothing_keeps_source_and_user_outfits(self) -> None:
        details = merge_retag_prompt_details(
            "white_dress",
            self.source,
            weight_user=False,
            preserve_categories=["clothing"],
        )

        self.assertIn("white_dress", details["prompt"])
        self.assertIn("school_uniform", details["prompt"])
        self.assertEqual(details["preserveCategories"], ["clothing"])

    def test_dropped_clothing_removes_only_source_outfit(self) -> None:
        details = merge_retag_prompt_details(
            "white_dress",
            self.source,
            weight_user=False,
            drop_categories=["clothing"],
        )

        self.assertIn("white_dress", details["prompt"])
        self.assertNotIn("school_uniform", details["prompt"])
        self.assertIn("black_hair", details["prompt"])
        self.assertEqual(details["dropCategories"], ["clothing"])

    def test_dropped_single_tag_leaves_the_rest_of_its_category(self) -> None:
        # 分类级移除是整类一刀切；这里只点名一条，同类其余标签要留下
        source = f"{self.source}, blue_eyes, closed_eyes"
        details = merge_retag_prompt_details(
            "",
            source,
            weight_user=False,
            drop_tags=["closed_eyes"],
        )

        self.assertNotIn("closed_eyes", details["prompt"])
        self.assertIn("blue_eyes", details["prompt"])
        self.assertIn("school_uniform", details["prompt"])

    def test_dropped_tag_matching_ignores_case_and_spacing(self) -> None:
        details = merge_retag_prompt_details(
            "",
            self.source,
            weight_user=False,
            drop_tags=["  School_Uniform  "],
        )

        self.assertNotIn("school_uniform", details["prompt"])
        self.assertIn("black_hair", details["prompt"])

    def test_dropped_tags_combine_with_dropped_categories(self) -> None:
        source = f"{self.source}, blue_eyes, closed_eyes"
        details = merge_retag_prompt_details(
            "",
            source,
            weight_user=False,
            drop_categories=["clothing"],
            drop_tags=["closed_eyes"],
        )

        self.assertNotIn("school_uniform", details["prompt"])
        self.assertNotIn("closed_eyes", details["prompt"])
        self.assertIn("blue_eyes", details["prompt"])

    def test_unknown_or_malformed_drop_tags_change_nothing(self) -> None:
        baseline = merge_retag_prompt_details("", self.source, weight_user=False)

        for value in (None, "not-a-list", [], ["", "   "], ["never_tagged"]):
            with self.subTest(value=value):
                details = merge_retag_prompt_details(
                    "",
                    self.source,
                    weight_user=False,
                    drop_tags=value,
                )
                self.assertEqual(details["prompt"], baseline["prompt"])

    def test_drop_tag_normalizer_is_bounded_and_keyed(self) -> None:
        self.assertEqual(normalize_retag_layer_tags(["A_Tag", "a_tag"]), {"a_tag"})
        self.assertEqual(normalize_retag_layer_tags("nope"), set())
        oversized = [f"tag_{index}" for index in range(MAX_RETAG_DROP_TAGS + 50)]
        self.assertEqual(
            len(normalize_retag_layer_tags(oversized)), MAX_RETAG_DROP_TAGS
        )

    def test_drop_tags_reach_the_compatibility_wrapper(self) -> None:
        result = merge_retag_prompt(
            "",
            self.source,
            weight_user=False,
            drop_tags=["school_uniform"],
        )

        self.assertNotIn("school_uniform", result)
        self.assertIn("black_hair", result)

    def test_locked_hair_survives_structured_character_replacement(self) -> None:
        result = merge_retag_prompt(
            "izumi_sagiri, eromanga_sensei",
            self.source,
            user_character="izumi_sagiri",
            user_series="eromanga_sensei",
            source_character="kasumigaoka_utaha",
            source_series="saenai_heroine_no_sodatekata",
            weight_user=False,
            preserve_categories=["hair"],
        )

        self.assertIn("izumi_sagiri", result)
        self.assertIn("black_hair", result)
        self.assertNotIn("kasumigaoka_utaha", result)
        self.assertNotIn("school_uniform", result)

    def test_drop_mode_wins_when_same_category_is_also_locked(self) -> None:
        details = merge_retag_prompt_details(
            "",
            self.source,
            weight_user=False,
            preserve_categories=["clothing"],
            drop_categories=["clothing"],
        )

        self.assertNotIn("school_uniform", details["prompt"])
        self.assertEqual(details["preserveCategories"], [])
        self.assertEqual(details["dropCategories"], ["clothing"])

    def test_layer_removal_does_not_break_weighted_source_groups(self) -> None:
        result = merge_retag_prompt(
            "",
            "1.2::black_hair, school_uniform, sitting ::, classroom",
            weight_user=False,
            drop_categories=["clothing"],
        )

        self.assertEqual(result, "1.2::black_hair, sitting ::, classroom")
        self.assertNotIn("school_uniform", result)


if __name__ == "__main__":
    unittest.main()

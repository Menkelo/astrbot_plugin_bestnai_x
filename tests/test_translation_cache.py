from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from astrbot_plugin_bestnai_x.core.translator import (
    _result_items,
    apply_character_candidate,
    normalize_translation_text,
    prompt_has_tag,
    resolve_character_candidate,
    resolve_translation_cache,
)


class TranslationCacheTest(unittest.TestCase):
    def test_short_hair_color_terms_are_expanded_for_provider_requests(self) -> None:
        self.assertEqual(normalize_translation_text("蓝发少女"), "蓝头发少女")
        self.assertEqual(normalize_translation_text("蓝头发少女"), "蓝头发少女")

    def test_unchanged_chinese_prompt_reuses_translation(self) -> None:
        source, suffix, cached = resolve_translation_cache(
            "蓝发少女",
            "蓝发少女",
            "蓝发少女",
            "1girl, blue hair",
        )

        self.assertEqual(source, "蓝发少女")
        self.assertEqual(suffix, "")
        self.assertEqual(cached, "1girl, blue hair")

    def test_retag_suffix_does_not_invalidate_chinese_translation(self) -> None:
        source, suffix, cached = resolve_translation_cache(
            "蓝发少女, solo, outdoors",
            "蓝发少女",
            "蓝发少女",
            "1girl, blue hair",
        )

        self.assertEqual(source, "蓝发少女")
        self.assertEqual(suffix, "solo, outdoors")
        self.assertEqual(cached, "1girl, blue hair")

    def test_changed_chinese_prompt_invalidates_translation(self) -> None:
        source, suffix, cached = resolve_translation_cache(
            "红发少女",
            "红发少女",
            "蓝发少女",
            "1girl, blue hair",
        )

        self.assertEqual(source, "红发少女")
        self.assertEqual(suffix, "")
        self.assertEqual(cached, "")

    def test_chinese_suffix_falls_back_to_translating_full_prompt(self) -> None:
        source, suffix, cached = resolve_translation_cache(
            "蓝发少女, 夜景",
            "蓝发少女",
            "蓝发少女",
            "1girl, blue hair",
        )

        self.assertEqual(source, "蓝发少女, 夜景")
        self.assertEqual(suffix, "")
        self.assertEqual(cached, "")


class CharacterCandidateResolutionTest(unittest.TestCase):
    results = {
        "search": [
            {
                "tag": "eromanga_sensei",
                "cn_name": "埃罗芒阿老师, 动漫, 轻小说",
                "category": "Copyright",
                "score": 0.9282,
                "source": "埃罗芒阿老师",
            },
            {
                "tag": "yamada_elf",
                "cn_name": "山田妖精, 埃罗芒阿老师, 轻小说作家",
                "category": "Character",
                "score": 0.5345,
                "source": "埃罗芒阿老师",
            },
        ],
        "related": [
            {
                "tag": "senju_muramasa",
                "cn_name": "千寿村正, 埃罗芒阿老师",
                "category": "Character",
                "sources": ["eromanga_sensei", "yamada_elf"],
                "wiki": "作品中的女性角色。",
            },
            {
                "tag": "izumi_sagiri",
                "cn_name": "和泉纱雾, 埃罗芒阿老师, Eromanga Sensei",
                "category": "Character",
                "sources": ["eromanga_sensei", "yamada_elf"],
                "wiki": "《埃罗芒阿老师》中的女主角。",
            },
        ],
    }

    def test_series_alias_uses_first_linked_related_character(self) -> None:
        character, series = resolve_character_candidate(
            "埃罗芒阿老师",
            self.results,
        )

        self.assertEqual(character, "izumi_sagiri")
        self.assertEqual(series, "eromanga_sensei")

    def test_character_plus_clothing_and_pose_still_resolves_identity(self) -> None:
        character, series = resolve_character_candidate(
            "埃罗芒阿老师穿白色连衣裙坐着",
            self.results,
        )

        self.assertEqual((character, series), ("izumi_sagiri", "eromanga_sensei"))

    def test_character_named_after_series_is_not_replaced_by_protagonist(self) -> None:
        self.assertEqual(
            resolve_character_candidate(
                "埃罗芒阿老师里的山田妖精穿白色连衣裙",
                self.results,
            ),
            ("yamada_elf", "eromanga_sensei"),
        )

    def test_canonical_english_character_tag_with_suffix_resolves_identity(self) -> None:
        character, series = resolve_character_candidate(
            "izumi_sagiri, white dress",
            self.results,
        )

        self.assertEqual((character, series), ("izumi_sagiri", "eromanga_sensei"))

    def test_long_metadata_prompt_matches_exact_canonical_identity_tags(self) -> None:
        results = {
            "search": [
                {
                    "tag": "kasugano_sora",
                    "category": "Character",
                    "score": 0.91,
                    "source": "kasugano_sora",
                },
                {
                    "tag": "yotsunoha",
                    "category": "Copyright",
                    "score": 0.84,
                },
            ],
            "related": [],
        }

        self.assertEqual(
            resolve_character_candidate(
                "1girl, solo, 1.2::kasugano_sora ::, yotsunoha, white_dress, sitting",
                results,
            ),
            ("kasugano_sora", "yotsunoha"),
        )

    def test_character_fix_removes_wrong_year_and_other_character_candidates(self) -> None:
        result = apply_character_candidate(
            "eromanga_sensei, year 2025, senju_muramasa",
            "izumi_sagiri",
            "eromanga_sensei",
            self.results,
        )

        self.assertEqual(result, "izumi_sagiri, eromanga_sensei")

    def test_weighted_wrong_character_candidate_is_removed(self) -> None:
        result = apply_character_candidate(
            "1.2::yamada_elf::, year 2025, solo, 1girl",
            "izumi_sagiri",
            "eromanga_sensei",
            self.results,
        )

        self.assertEqual(result, "izumi_sagiri, eromanga_sensei, solo, 1girl")

    def test_descriptive_prompt_is_not_forced_to_a_character(self) -> None:
        generic_results = {
            "search": [
                {
                    "tag": "cyberpunk",
                    "cn_name": "赛博朋克, 风格",
                    "category": "General",
                    "score": 0.8676,
                },
                {
                    "tag": "cyberpunk_(series)",
                    "cn_name": "赛博朋克, 游戏",
                    "category": "Copyright",
                    "score": 0.7476,
                },
                {
                    "tag": "supergirl",
                    "cn_name": "超级少女, DC",
                    "category": "Character",
                    "score": 0.6348,
                },
            ],
            "related": [],
        }
        character, series = resolve_character_candidate(
            "赛博朋克少女",
            generic_results,
        )

        self.assertEqual((character, series), ("", ""))

    def test_related_endpoint_object_shape_is_supported(self) -> None:
        items = _result_items({"results": [{"tag": "izumi_sagiri"}]})

        self.assertEqual(items, [{"tag": "izumi_sagiri"}])

    def test_prompt_tag_detection_understands_nai_weight(self) -> None:
        self.assertTrue(prompt_has_tag("1.2::izumi_sagiri::, solo", "izumi_sagiri"))

    def test_replacement_instruction_prefers_target_canonical_name(self) -> None:
        character, series = resolve_character_candidate(
            "change kasugano_sora to izumi_sagiri",
            self.results,
        )

        self.assertEqual((character, series), ("izumi_sagiri", "eromanga_sensei"))

    def test_multi_character_metadata_does_not_silently_drop_the_second_role(self) -> None:
        results = {
            "search": [
                {"tag": "izumi_sagiri", "category": "Character", "score": 0.9},
                {"tag": "kasugano_sora", "category": "Character", "score": 0.8},
                {"tag": "eromanga_sensei", "category": "Copyright", "score": 0.7},
            ],
            "related": [],
        }

        self.assertEqual(
            resolve_character_candidate(
                "1girl, izumi_sagiri, 1girl, kasugano_sora, eromanga_sensei",
                results,
            ),
            ("", ""),
        )

    def test_two_named_roles_in_natural_language_are_ambiguous(self) -> None:
        results = {
            "search": [
                {"tag": "izumi_sagiri", "category": "Character", "score": 0.9},
                {"tag": "kasugano_sora", "category": "Character", "score": 0.8},
            ],
            "related": [],
        }
        self.assertEqual(
            resolve_character_candidate("izumi_sagiri and kasugano_sora", results),
            ("", ""),
        )

if __name__ == "__main__":
    unittest.main()

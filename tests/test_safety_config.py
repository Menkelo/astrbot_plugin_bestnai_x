from __future__ import annotations

import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from astrbot_plugin_bestnai_x.core.safety import (  # noqa: E402
    HARD_BLOCK_WORDS,
    SafetyModerator,
    filter_sensitive_prompt,
)
from astrbot_plugin_bestnai_x.models.config import (  # noqa: E402
    PluginConfig,
    migrate_legacy_prompt_block_words,
)


class SafetyPromptWordsTest(unittest.TestCase):
    def test_vision_string_false_is_not_treated_as_truthy(self) -> None:
        moderator = SafetyModerator(SimpleNamespace())

        blocked = moderator._parse_result('{"safe":"false","reason":"blocked"}')
        allowed = moderator._parse_result('{"safe":"true","reason":""}')

        self.assertFalse(blocked.safe)
        self.assertTrue(allowed.safe)

    def test_configured_words_replace_builtin_defaults(self) -> None:
        moderator = SafetyModerator(
            SimpleNamespace(
                prompt_block_enabled=True,
                prompt_block_words=["custom blocked"],
            )
        )

        result = moderator.check_prompt("nude, custom blocked, portrait")

        self.assertIn("nude", result.filtered_prompt)
        self.assertNotIn("custom blocked", result.filtered_prompt)

    def test_detection_mode_keeps_prompt_intact(self) -> None:
        moderator = SafetyModerator(
            SimpleNamespace(
                prompt_block_enabled=True,
                prompt_block_words=["custom blocked"],
            )
        )

        result = moderator.detect_prompt("nude, custom blocked, portrait")

        self.assertEqual(result.filtered_prompt, "nude, custom blocked, portrait")
        self.assertNotIn("nude", result.reason)
        self.assertIn("custom blocked", result.reason)

    def test_empty_configured_list_disables_word_detection(self) -> None:
        filtered, removed = filter_sensitive_prompt("nude portrait", [])

        self.assertEqual(filtered, "nude portrait")
        self.assertEqual(removed, [])

    def test_missing_custom_list_keeps_builtin_compatibility(self) -> None:
        filtered, removed = filter_sensitive_prompt("nude portrait", None)

        self.assertEqual(filtered, "")
        self.assertIn("nude", removed)

    def test_danbooru_separator_variants_are_filtered(self) -> None:
        filtered, removed = filter_sensitive_prompt(
            "1girl, oral_sex, nude_female, blue_hair, rating:explicit",
            None,
        )

        self.assertIn("1girl", filtered)
        self.assertIn("blue_hair", filtered)
        self.assertNotIn("oral_sex", filtered)
        self.assertNotIn("nude", filtered)
        self.assertNotIn("rating:", filtered)
        self.assertIn("oral sex", removed)
        self.assertIn("nude", removed)
        self.assertIn("explicit", removed)

    def test_explicit_tags_are_removed_but_soft_tags_remain(self) -> None:
        filtered, removed = filter_sensitive_prompt(
            "girl, school uniform, torn clothes, torn panties, wet panties, "
            "panties aside, pussy, vaginal, sex, deep penetration, lying on back, "
            "on bed, bedroom, man on top, rough sex, exposed breasts, nipples, "
            "spread legs, blush, heavy breathing, looking at viewer, from above, "
            "close-up, dim lighting",
            None,
        )

        for word in (
            "pussy",
            "vaginal",
            "sex",
            "deep penetration",
            "rough sex",
            "exposed breasts",
            "nipples",
        ):
            with self.subTest(word=word):
                self.assertIn(word, removed)

        for tag in (
            "torn clothes",
            "torn panties",
            "wet panties",
            "panties aside",
            "man on top",
            "spread legs",
        ):
            with self.subTest(tag=tag):
                self.assertIn(tag, filtered)

    def test_removed_overbroad_defaults_no_longer_trigger(self) -> None:
        prompt = (
            "泳装, 比基尼, 内衣, 性感, 诱惑, swimsuit, bikini, underwear, "
            "sexy, suggestive, breast focus, loli, shota"
        )

        filtered, removed = filter_sensitive_prompt(prompt, None)

        self.assertEqual(removed, [])
        self.assertEqual(filtered, prompt)

    def test_zero_width_characters_cannot_bypass_filter(self) -> None:
        filtered, removed = filter_sensitive_prompt("n\u200bude, portrait", None)

        self.assertEqual(filtered, "portrait")
        self.assertIn("nude", removed)

    def test_common_vision_moderation_shapes_are_supported(self) -> None:
        moderator = SafetyModerator(SimpleNamespace())

        self.assertFalse(moderator._parse_result('{"nsfw":true}').safe)
        self.assertTrue(moderator._parse_result('{"nsfw":false}').safe)
        self.assertFalse(moderator._parse_result('{"verdict":"unsafe"}').safe)
        self.assertFalse(moderator._parse_result("图片不安全，存在裸露").safe)

    def test_plugin_config_preserves_an_explicit_empty_textbox(self) -> None:
        config = PluginConfig.from_dict(
            {"safety_config": {"prompt_block_words": ""}}
        )

        self.assertEqual(config.safety.prompt_block_words, [])

    def test_plugin_config_parses_chinese_comma_and_legacy_formats(self) -> None:
        chinese_comma_config = PluginConfig.from_dict(
            {"safety_config": {"prompt_block_words": "first word，second_word"}}
        )
        text_config = PluginConfig.from_dict(
            {"safety_config": {"prompt_block_words": "first word\nsecond_word\n"}}
        )
        legacy_config = PluginConfig.from_dict(
            {"safety_config": {"prompt_block_words": ["first word", "second_word"]}}
        )
        comma_config = PluginConfig.from_dict(
            {"safety_config": {"prompt_block_words": "first word,second_word"}}
        )

        self.assertEqual(
            chinese_comma_config.safety.prompt_block_words,
            ["first word", "second_word"],
        )
        self.assertEqual(text_config.safety.prompt_block_words, ["first word", "second_word"])
        self.assertEqual(legacy_config.safety.prompt_block_words, ["first word", "second_word"])
        self.assertEqual(comma_config.safety.prompt_block_words, ["first word", "second_word"])

    def test_legacy_widget_migration_prunes_soft_words_and_keeps_custom_words(self) -> None:
        migrated = migrate_legacy_prompt_block_words(
            ["nude", "泳装", "custom blocked", "SEXY", "nude"]
        )

        self.assertEqual(migrated, "nude，custom blocked")
        self.assertEqual(
            migrate_legacy_prompt_block_words("nude\ncustom blocked"),
            "nude，custom blocked",
        )
        self.assertIsNone(migrate_legacy_prompt_block_words("nude，custom blocked"))

    def test_visual_review_provider_was_removed_from_schema(self) -> None:
        config = PluginConfig.from_dict({})
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

        self.assertFalse(config.safety.enabled)
        safety_items = schema["safety_config"]["items"]
        self.assertNotIn("enabled", safety_items)
        self.assertNotIn("provider_id", safety_items)
        self.assertTrue(safety_items["prompt_block_enabled"]["default"])

    def test_retag_controls_include_artist_presets_and_quality_suffix(self) -> None:
        config = PluginConfig.from_dict(
            {
                "prompt_config": {
                    "artist_presets": ["watercolor:{hokori sakuni}, {ciloranko}"],
                    "quality_prompt": "masterpiece, highres",
                }
            }
        )

        self.assertEqual(
            config.get_retag_control_prompts(),
            ["{hokori sakuni}, {ciloranko}", "masterpiece, highres"],
        )

    def test_schema_exposes_builtin_words_as_chinese_comma_text(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        prompt_words = schema["safety_config"]["items"]["prompt_block_words"]

        self.assertEqual(prompt_words["type"], "text")
        self.assertEqual(prompt_words["default"].split("，"), HARD_BLOCK_WORDS)

    def test_schema_exposes_generation_providers(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        api_config = schema["api_config"]

        self.assertEqual(api_config["description"], "生图接口配置")
        # 主提供商（4.5/默认）+ V5 专用槽位，以及 NovelAI 官方接口的开关/地址/Token
        self.assertEqual(
            list(api_config["items"]),
            [
                "provider_id",
                "provider_id_v5",
                "use_official_api",
                "official_api_url",
                "official_api_token",
            ],
        )

    def test_legacy_manual_generation_fields_are_ignored(self) -> None:
        config = PluginConfig.from_dict(
            {
                "api_config": {
                    "provider_id": "image-provider",
                    "prefer_provider": False,
                    "api_url": "https://legacy.example/v1",
                    "api_key": "legacy-key",
                }
            }
        )

        self.assertEqual(config.image_provider_id, "image-provider")
        self.assertEqual(config.api_url, "")
        self.assertEqual(config.api_key, "")

    def test_qq_path_filters_the_fully_assembled_prompt(self) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("final_prompt_check = self.safety.detect_prompt(final_prompt)", main)
        self.assertIn("最终 prompt 命中敏感词", main)


if __name__ == "__main__":
    unittest.main()

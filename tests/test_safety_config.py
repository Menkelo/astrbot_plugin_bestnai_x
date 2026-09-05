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
            "1girl, oral_sex, nude_female, blue_hair, rating:nude",
            None,
        )

        self.assertIn("1girl", filtered)
        self.assertIn("blue_hair", filtered)
        self.assertNotIn("oral_sex", filtered)
        self.assertNotIn("nude", filtered)
        # 命名空间连同被拦的词一起吃掉，不留下 ``rating:`` 这样的残词。
        self.assertNotIn("rating:", filtered)
        self.assertIn("sex", removed)
        self.assertIn("nude", removed)

    def test_rating_meta_tags_are_allowed(self) -> None:
        filtered, removed = filter_sensitive_prompt(
            "1girl, rating:explicit, nsfw, blue_hair",
            None,
        )

        # 分级元标签不点名部位，放行以免泳装、透视这类轻度暴露被一并混淆。
        self.assertEqual(removed, [])
        self.assertIn("rating:explicit", filtered)
        self.assertIn("nsfw", filtered)

    def test_explicit_tags_are_removed_but_soft_tags_remain(self) -> None:
        filtered, removed = filter_sensitive_prompt(
            "girl, school uniform, torn clothes, torn panties, wet panties, "
            "panties aside, pussy, vaginal, sex, deep penetration, lying on back, "
            "on bed, bedroom, man on top, rough sex, exposed breasts, nipples, "
            "spread legs, blush, heavy breathing, looking at viewer, from above, "
            "close-up, dim lighting",
            None,
        )

        # ``deep penetration`` / ``rough sex`` 由 ``penetration`` / ``sex`` 覆盖，
        # 词条照样被剔除，只是上报的命中词是更短的那个。
        for word in (
            "pussy",
            "vaginal",
            "sex",
            "penetration",
            "exposed breasts",
            "nipples",
        ):
            with self.subTest(word=word):
                self.assertIn(word, removed)

        for tag in ("deep penetration", "rough sex"):
            with self.subTest(dropped=tag):
                self.assertNotIn(tag, filtered)

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

    def test_untouched_previous_default_is_replaced_by_current_default(self) -> None:
        current_default = "，".join(HARD_BLOCK_WORDS)
        previous_default = (
            "裸体，全裸，露点，乳头，乳晕，下体，阴部，阴道，阴茎，性器，生殖器，性交，做爱，"
            "性爱，色情，黄片，黄图，涩图，色图，r18，18禁，自慰，口交，内射，射精，强奸，"
            "萝莉色情，幼女色情，儿童色情，正太色情，幼态色情，露胸，裸胸，胸部裸露，开裆，"
            "无内裤，无胸罩，色情姿势，nsfw，explicit，nude，naked，nipples，nipple，areola，"
            "pussy，penis，vagina，vaginal，vulva，clitoris，clit，genitals，genitalia，anus，"
            "anal，sex，sexual content，vaginal sex，anal sex，rough sex，sex position，"
            "penetration，deep penetration，vaginal penetration，anal penetration，"
            "multiple penetration，porn，hentai，masturbation，ejaculation，cum，cumshot，"
            "creampie，oral sex，blowjob，handjob，fingering，intercourse，rape，loli porn，"
            "child porn，child sexualization，topless，bottomless，exposed breasts，cameltoe，"
            "pornographic，lolicon，shotacon"
        )

        # 4.6.20 的中文逗号版和 4.6.19 的换行版都会换成新默认值。
        self.assertEqual(
            migrate_legacy_prompt_block_words(previous_default, current_default),
            current_default,
        )
        self.assertEqual(
            migrate_legacy_prompt_block_words(
                previous_default.replace("，", "\n"), current_default
            ),
            current_default,
        )
        # 用户改过的列表按原样保留，不会被换成默认值。
        self.assertIsNone(
            migrate_legacy_prompt_block_words(
                previous_default + "，我自己加的词", current_default
            )
        )
        # 已经是新默认值时不再重复写回。
        self.assertIsNone(
            migrate_legacy_prompt_block_words(current_default, current_default)
        )

    def test_builtin_words_block_organs_but_allow_mild_exposure(self) -> None:
        for prompt in (
            "pussy", "penis", "vagina", "clitoris", "genitals", "anus",
            "阴部", "阴道", "下体", "性器", "生殖器",
            "nipples", "nipple", "areola", "露点", "乳头", "胸部裸露",
            "topless", "bottomless", "cameltoe", "开裆",
            "nude", "naked", "裸体", "全裸",
            "rape", "强奸", "lolicon", "shotacon", "child sexualization",
            # 这几条曾靠 ``色情`` / ``porn`` 覆盖，两者作为元标签放行后必须自带条目。
            "儿童色情", "萝莉色情", "幼女色情", "正太色情", "幼态色情",
            "loli porn", "child porn",
        ):
            with self.subTest(blocked=prompt):
                self.assertTrue(filter_sensitive_prompt(prompt, None)[1])

        for prompt in (
            "bikini", "swimsuit", "lingerie", "see-through", "sideboob",
            "no bra", "cleavage", "suggestive", "ecchi",
            "泳装", "内衣", "性感", "露肩",
            # 分级元标签本身不点名部位，放行以免轻度暴露也被混淆。
            "nsfw", "explicit", "r18", "hentai", "涩图", "色情",
        ):
            with self.subTest(allowed=prompt):
                self.assertFalse(filter_sensitive_prompt(prompt, None)[1])

    def test_builtin_words_have_no_redundant_entries(self) -> None:
        for word in HARD_BLOCK_WORDS:
            rest = [other for other in HARD_BLOCK_WORDS if other != word]
            with self.subTest(word=word):
                self.assertFalse(
                    filter_sensitive_prompt(word, rest)[1],
                    f"{word} 已被列表中其它词覆盖，应当删除",
                )

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
        # 主提供商、V5 专用槽位，以及官方接口和代理配置。
        self.assertEqual(
            list(api_config["items"]),
            [
                "provider_id",
                "provider_id_v5",
                "use_official_api",
                "official_api_url",
                "official_api_token",
                "proxy",
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

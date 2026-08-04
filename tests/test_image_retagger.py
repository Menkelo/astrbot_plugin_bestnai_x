from __future__ import annotations

import logging
import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("test.image_retag")
astrbot_module.api = astrbot_api_module
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)

from astrbot_plugin_bestnai_x.core.image_retagger import (
    compose_retag_prompt,
    parse_retag_response,
)


class ParseRetagResponseTest(unittest.TestCase):
    def test_structured_response_splits_character_series_and_tags(self) -> None:
        character, series, tags = parse_retag_response(
            '{"character": "hatsune_miku", "series": "vocaloid",'
            ' "tags": "1girl, solo, twintails"}'
        )

        self.assertEqual(character, "hatsune_miku")
        self.assertEqual(series, "vocaloid")
        self.assertEqual(tags, "1girl, solo, twintails")

    def test_markdown_fenced_json_is_accepted(self) -> None:
        character, _, tags = parse_retag_response(
            '```json\n{"character": "kafuu_chino", "series": "gochuumon_wa_usagi_desu_ka",'
            ' "tags": "1girl, blue hair"}\n```'
        )

        self.assertEqual(character, "kafuu_chino")
        self.assertEqual(tags, "1girl, blue hair")

    def test_json_wrapped_in_prose_is_recovered(self) -> None:
        character, _, tags = parse_retag_response(
            'Sure! Here is the result:\n'
            '{"character": "rem", "series": "re_zero", "tags": "1girl, blue hair"}\n'
            'Hope this helps.'
        )

        self.assertEqual(character, "rem")
        self.assertEqual(tags, "1girl, blue hair")

    def test_plain_tag_string_falls_back_to_tags_only(self) -> None:
        # 模型没守格式时必须退回旧行为，而不是整条反推失败
        character, series, tags = parse_retag_response("1girl, solo, looking at viewer")

        self.assertEqual(character, "")
        self.assertEqual(series, "")
        self.assertEqual(tags, "1girl, solo, looking at viewer")

    def test_placeholder_character_values_are_dropped(self) -> None:
        for placeholder in ("none", "N/A", "unknown", "original character", "-", ""):
            with self.subTest(placeholder=placeholder):
                character, _, tags = parse_retag_response(
                    '{"character": "%s", "series": "none", "tags": "1girl, solo"}'
                    % placeholder
                )
                self.assertEqual(character, "")
                self.assertEqual(tags, "1girl, solo")

    def test_non_ascii_is_stripped_from_character(self) -> None:
        character, _, _ = parse_retag_response(
            '{"character": "初音ミク hatsune_miku", "series": "", "tags": "1girl"}'
        )

        self.assertEqual(character, "hatsune_miku")

    def test_tags_given_as_list_are_joined(self) -> None:
        _, _, tags = parse_retag_response(
            '{"character": "", "series": "", "tags": ["1girl", "solo", "smile"]}'
        )

        self.assertEqual(tags, "1girl, solo, smile")

    def test_response_without_tags_key_is_treated_as_plain_text(self) -> None:
        character, _, tags = parse_retag_response('{"character": "rem"}')

        self.assertEqual(character, "")
        self.assertIn("rem", tags)


class ComposeRetagPromptTest(unittest.TestCase):
    def test_character_and_series_lead_the_prompt(self) -> None:
        self.assertEqual(
            compose_retag_prompt("hatsune_miku", "vocaloid", "1girl, solo"),
            "hatsune_miku, vocaloid, 1girl, solo",
        )

    def test_duplicate_character_tag_is_not_prepended_twice(self) -> None:
        self.assertEqual(
            compose_retag_prompt("rem", "re_zero", "1girl, rem, blue hair"),
            "re_zero, 1girl, rem, blue hair",
        )

    def test_missing_character_leaves_tags_untouched(self) -> None:
        self.assertEqual(
            compose_retag_prompt("", "", "1girl, solo"),
            "1girl, solo",
        )

    def test_character_without_series_still_leads(self) -> None:
        self.assertEqual(
            compose_retag_prompt("rem", "", "1girl, solo"),
            "rem, 1girl, solo",
        )

    def test_substring_match_does_not_suppress_character(self) -> None:
        # "rem" 是 "tremble" 的子串，但不是独立 tag，仍应补在最前
        self.assertEqual(
            compose_retag_prompt("rem", "", "1girl, trembling"),
            "rem, 1girl, trembling",
        )


if __name__ == "__main__":
    unittest.main()

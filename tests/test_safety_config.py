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
from astrbot_plugin_bestnai_x.models.config import PluginConfig  # noqa: E402


class SafetyPromptWordsTest(unittest.TestCase):
    def test_vision_string_false_is_not_treated_as_truthy(self) -> None:
        moderator = SafetyModerator(SimpleNamespace())

        blocked = moderator._parse_result('{"safe":"false","reason":"blocked"}')
        allowed = moderator._parse_result('{"safe":"true","reason":""}')

        self.assertFalse(blocked.safe)
        self.assertTrue(allowed.safe)

    def test_custom_words_replace_builtin_detection_words(self) -> None:
        moderator = SafetyModerator(
            SimpleNamespace(
                prompt_block_enabled=True,
                prompt_block_words=["custom blocked"],
            )
        )

        result = moderator.check_prompt("nude, custom blocked, portrait")

        self.assertIn("nude", result.filtered_prompt)
        self.assertNotIn("custom blocked", result.filtered_prompt)

    def test_empty_custom_list_disables_word_removal(self) -> None:
        filtered, removed = filter_sensitive_prompt("nude portrait", [])

        self.assertEqual(filtered, "nude portrait")
        self.assertEqual(removed, [])

    def test_missing_custom_list_keeps_builtin_compatibility(self) -> None:
        filtered, removed = filter_sensitive_prompt("nude portrait", None)

        self.assertEqual(filtered, "portrait")
        self.assertIn("nude", removed)

    def test_plugin_config_preserves_an_explicit_empty_list(self) -> None:
        config = PluginConfig.from_dict(
            {"safety_config": {"prompt_block_words": []}}
        )

        self.assertEqual(config.safety.prompt_block_words, [])

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

    def test_schema_exposes_the_current_builtin_words(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        prompt_words = schema["safety_config"]["items"]["prompt_block_words"]

        self.assertEqual(prompt_words["type"], "list")
        self.assertEqual(prompt_words["default"], HARD_BLOCK_WORDS)

    def test_qq_path_filters_the_fully_assembled_prompt(self) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("final_prompt_check = self.safety.check_prompt(final_prompt)", main)
        self.assertIn("已自动过滤最终 prompt", main)


if __name__ == "__main__":
    unittest.main()

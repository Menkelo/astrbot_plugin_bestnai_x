from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from astrbot_plugin_bestnai_x.core.translator import resolve_translation_cache


class TranslationCacheTest(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

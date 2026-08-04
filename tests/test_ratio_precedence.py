from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from astrbot_plugin_bestnai_x.services.image_ratio import (
    RATIO_SOURCE_ARTIST,
    RATIO_SOURCE_DEFAULT,
    RATIO_SOURCE_IMAGE,
    RATIO_SOURCE_USER,
    choose_ratio_source,
)


ROOT = Path(__file__).resolve().parents[1]


class ChooseRatioSourceTest(unittest.TestCase):
    def test_user_written_ratio_always_wins(self) -> None:
        for artist in (True, False):
            for inferred in (True, False):
                with self.subTest(artist=artist, inferred=inferred):
                    self.assertEqual(
                        choose_ratio_source(True, artist, inferred),
                        RATIO_SOURCE_USER,
                    )

    def test_artist_ratio_beats_image_inference(self) -> None:
        # 这条是本次修复的核心：反推推断出的比例不得盖掉画师串里的比例
        self.assertEqual(
            choose_ratio_source(False, True, True),
            RATIO_SOURCE_ARTIST,
        )

    def test_artist_ratio_used_when_no_image_inference(self) -> None:
        self.assertEqual(
            choose_ratio_source(False, True, False),
            RATIO_SOURCE_ARTIST,
        )

    def test_image_inference_used_only_when_nothing_else_specifies(self) -> None:
        self.assertEqual(
            choose_ratio_source(False, False, True),
            RATIO_SOURCE_IMAGE,
        )

    def test_default_when_nothing_specifies(self) -> None:
        self.assertEqual(
            choose_ratio_source(False, False, False),
            RATIO_SOURCE_DEFAULT,
        )

    def test_precedence_is_strictly_ordered(self) -> None:
        rank = {
            RATIO_SOURCE_USER: 0,
            RATIO_SOURCE_ARTIST: 1,
            RATIO_SOURCE_IMAGE: 2,
            RATIO_SOURCE_DEFAULT: 3,
        }
        # 把 8 种组合全枚举一遍，确认永远选中排名最高的那个可用来源
        for user in (True, False):
            for artist in (True, False):
                for inferred in (True, False):
                    available = [RATIO_SOURCE_DEFAULT]
                    if inferred:
                        available.append(RATIO_SOURCE_IMAGE)
                    if artist:
                        available.append(RATIO_SOURCE_ARTIST)
                    if user:
                        available.append(RATIO_SOURCE_USER)
                    expected = min(available, key=lambda s: rank[s])
                    with self.subTest(user=user, artist=artist, inferred=inferred):
                        self.assertEqual(
                            choose_ratio_source(user, artist, inferred),
                            expected,
                        )


class RetagRatioWiringTest(unittest.TestCase):
    """反推推断的比例必须以参数传递，不能拼进提示词字符串。"""

    def setUp(self) -> None:
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")

    def test_inferred_ratio_is_not_appended_to_the_prompt(self) -> None:
        # 拼进提示词会让它在 prompt_has_explicit_ratio 判定里等同于用户手写，
        # 从而把画师串的比例挤掉
        self.assertNotIn('merged_prompt = f"{merged_prompt} {inferred_ratio}"', self.main)

    def test_inferred_ratio_is_passed_as_fallback(self) -> None:
        self.assertIn("fallback_ratio: str = \"\"", self.main)
        self.assertIn("fallback_ratio=inferred_ratio", self.main)

    def test_precedence_helper_is_used(self) -> None:
        self.assertIn("ratio_source = choose_ratio_source(", self.main)
        self.assertIn("user_specified=user_specified_ratio", self.main)
        self.assertIn("artist_has_ratio=artist_has_ratio", self.main)
        self.assertIn("has_inferred_ratio=bool(fallback_ratio)", self.main)


if __name__ == "__main__":
    unittest.main()

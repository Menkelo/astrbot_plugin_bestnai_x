from __future__ import annotations

import sys
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.core.char_prompts import (  # noqa: E402
    char_grid_position,
    default_char_position,
    normalize_char_entries,
)


class CharGridPositionTest(unittest.TestCase):
    def test_fractional_centers_map_to_grid_cells(self) -> None:
        # 与原版 BestNAI 插件的默认站位一致：C3 居中、B3/D3 左右
        self.assertEqual(char_grid_position(0.5, 0.5), "C3")
        self.assertEqual(char_grid_position(0.25, 0.5), "B3")
        self.assertEqual(char_grid_position(0.75, 0.5), "D3")
        self.assertEqual(char_grid_position(0.1, 0.9), "A5")

    def test_out_of_range_and_invalid_values_are_clamped_or_rejected(self) -> None:
        self.assertEqual(char_grid_position(-2, 7), "A5")
        self.assertEqual(char_grid_position(1, 0), "E1")
        for x, y in ((None, 0.5), (0.5, "abc"), ("", "")):
            with self.subTest(x=x, y=y):
                self.assertIsNone(char_grid_position(x, y))


class DefaultCharPositionTest(unittest.TestCase):
    def test_defaults_match_original_plugin_layout(self) -> None:
        self.assertEqual(default_char_position(0, 1), "C3")
        self.assertEqual(default_char_position(0, 2), "B3")
        self.assertEqual(default_char_position(1, 2), "D3")
        self.assertEqual(default_char_position(4, 5), "C5")


class NormalizeCharEntriesTest(unittest.TestCase):
    def test_normalizes_metadata_entries_into_gateway_shape(self) -> None:
        entries = normalize_char_entries(
            [
                {
                    "prompt": "hatsune miku",
                    "negative": "bad hands",
                    "x": 0.3,
                    "y": 0.5,
                },
                {"caption": "kagamine rin"},
            ]
        )

        self.assertEqual(
            entries,
            [
                {
                    "prompt": "hatsune miku",
                    "negative_prompt": "bad hands",
                    "position": "B3",
                },
                {
                    "prompt": "kagamine rin",
                    "negative_prompt": "",
                    # 无坐标的角色按数量套用原版默认站位：2 角色 -> 第二个 D3
                    "position": "D3",
                },
            ],
        )

    def test_explicit_position_wins_and_invalid_input_is_dropped(self) -> None:
        entries = normalize_char_entries(
            [
                {"prompt": "a", "position": "d4"},
                {"negative_prompt": "no prompt"},
                "not-a-dict",
                {"prompt": ""},
            ]
        )

        self.assertEqual(
            [entry["position"] for entry in entries],
            ["D4"],
        )
        self.assertEqual(len(entries), 1)

    def test_caps_entry_count(self) -> None:
        raw = [{"prompt": f"char {index}"} for index in range(40)]

        self.assertEqual(len(normalize_char_entries(raw)), 16)

    def test_non_list_input_returns_empty(self) -> None:
        for value in (None, "x", {}, 42):
            with self.subTest(value=value):
                self.assertEqual(normalize_char_entries(value), [])


if __name__ == "__main__":
    unittest.main()

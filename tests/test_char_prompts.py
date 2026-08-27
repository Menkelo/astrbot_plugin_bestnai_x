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
    has_explicit_positions,
    is_valid_position,
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

    def test_never_overflows_past_the_last_row(self) -> None:
        # 网格只有五行；以前 6 人以上会算出 C6 这种非法站位，网关 400 打回
        for index in range(5, 16):
            with self.subTest(index=index):
                position = default_char_position(index, 16)
                self.assertTrue(is_valid_position(position), position)


class IsValidPositionTest(unittest.TestCase):
    def test_accepts_the_five_by_five_grid(self) -> None:
        for position in ("A1", "C3", "E5", "b2"):
            with self.subTest(position=position):
                self.assertTrue(is_valid_position(position))

    def test_rejects_anything_outside_the_grid(self) -> None:
        for position in ("C6", "F1", "Z9", "C", "3C", "", None, 33):
            with self.subTest(position=position):
                self.assertFalse(is_valid_position(position))

    def test_tolerates_surrounding_whitespace(self) -> None:
        self.assertTrue(is_valid_position(" C3 "))


class HasExplicitPositionsTest(unittest.TestCase):
    def test_true_only_when_someone_actually_specified_one(self) -> None:
        self.assertTrue(has_explicit_positions([{"prompt": "a", "position": "B3"}]))

    def test_false_without_positions(self) -> None:
        # 只有坐标、或什么都没有，都不算「用户明确指定」
        self.assertFalse(has_explicit_positions([{"prompt": "a"}]))
        self.assertFalse(has_explicit_positions([{"prompt": "a", "x": 0.3, "y": 0.5}]))

    def test_false_for_invalid_positions(self) -> None:
        self.assertFalse(has_explicit_positions([{"prompt": "a", "position": "Z9"}]))

    def test_false_for_non_list(self) -> None:
        for value in (None, "x", {}, 42):
            with self.subTest(value=value):
                self.assertFalse(has_explicit_positions(value))


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

    def test_out_of_grid_position_falls_back_instead_of_being_sent(self) -> None:
        # "Z9" 原样送出去会让网关 400，把整批角色一起废掉
        entries = normalize_char_entries(
            [
                {"prompt": "a", "position": "Z9", "x": 0.25, "y": 0.5},
                {"prompt": "b", "position": "C6"},
            ]
        )

        self.assertEqual(entries[0]["position"], "B3")  # 退回坐标推算
        self.assertEqual(entries[1]["position"], "D3")  # 退回两人默认站位

    def test_every_emitted_position_is_valid(self) -> None:
        raw = [{"prompt": f"char {index}"} for index in range(40)]

        for entry in normalize_char_entries(raw):
            with self.subTest(position=entry["position"]):
                self.assertTrue(is_valid_position(entry["position"]))

    def test_caps_entry_count(self) -> None:
        raw = [{"prompt": f"char {index}"} for index in range(40)]

        self.assertEqual(len(normalize_char_entries(raw)), 16)

    def test_non_list_input_returns_empty(self) -> None:
        for value in (None, "x", {}, 42):
            with self.subTest(value=value):
                self.assertEqual(normalize_char_entries(value), [])


if __name__ == "__main__":
    unittest.main()

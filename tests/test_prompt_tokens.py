from __future__ import annotations

import sys
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.core.prompt_tokens import normalize_count_tokens  # noqa: E402


class NormalizeCountTokensTest(unittest.TestCase):
    def test_explicit_aggregate_wins_and_drops_section_counts(self) -> None:
        # 用户实际遇到的场景：全局计数 + 每个角色段落开头的裸计数
        prompt = (
            "Living room, 1boy, 4girls, 1.5::teamwork ::, "
            "boy, male_rover_(wuthering_waves), faceless, "
            "girl, mornye_(wuthering_waves), licking, "
            "girl, chisa_(wuthering_waves), oral"
        )

        self.assertEqual(
            normalize_count_tokens(prompt),
            "Living room, 1boy, 4girls, 1.5::teamwork ::, "
            "male_rover_(wuthering_waves), faceless, "
            "mornye_(wuthering_waves), licking, "
            "chisa_(wuthering_waves), oral",
        )

    def test_bare_only_counts_are_summed_into_one_aggregate(self) -> None:
        prompt = "girl, mornye_(a), girl, chisa_(b), girl, lynae_(c)"

        self.assertEqual(
            normalize_count_tokens(prompt),
            "3girls, mornye_(a), chisa_(b), lynae_(c)",
        )

    def test_single_count_is_untouched(self) -> None:
        for prompt in ("1girl, solo", "boy, male_rover", "1boy, 4girls"):
            with self.subTest(prompt=prompt):
                self.assertEqual(normalize_count_tokens(prompt), prompt)

    def test_weighted_blocks_and_parentheses_are_not_touched(self) -> None:
        # 计数词出现在权重组或括号里时不参与判定
        prompt = "1.5::girl, girl ::, {girl}, 1boy"

        self.assertEqual(normalize_count_tokens(prompt), "1.5::girl, girl ::, {girl}, 1boy")

    def test_mixed_families_are_normalized_independently(self) -> None:
        prompt = "1boy, boy, rover, girl, aemeath"

        # boy 家族有显式总数 -> 裸 boy 被丢弃；girl 只有单条 -> 原样保留
        self.assertEqual(
            normalize_count_tokens(prompt),
            "1boy, rover, girl, aemeath",
        )


if __name__ == "__main__":
    unittest.main()

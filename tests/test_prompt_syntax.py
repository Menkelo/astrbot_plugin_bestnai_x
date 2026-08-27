from __future__ import annotations

import sys
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.core.prompt_syntax import (  # noqa: E402
    convert_nai_to_sd,
    convert_sd_to_nai,
    strip_inline_tags,
)


class SdToNaiTest(unittest.TestCase):
    def test_explicit_weight_becomes_double_colon(self) -> None:
        self.assertEqual(
            convert_sd_to_nai("(masterpiece:1.2)"), "1.2::masterpiece::"
        )

    def test_105_becomes_brace(self) -> None:
        self.assertEqual(convert_sd_to_nai("(twintails:1.05)"), "{twintails}")

    def test_095_and_reciprocal_become_bracket(self) -> None:
        self.assertEqual(convert_sd_to_nai("(blurry:0.95)"), "[blurry]")
        self.assertEqual(convert_sd_to_nai("(blurry:0.952381)"), "[blurry]")

    def test_bare_parenthesis_becomes_brace(self) -> None:
        self.assertEqual(convert_sd_to_nai("(smile)"), "{smile}")

    def test_escaped_parenthesis_becomes_literal(self) -> None:
        # 角色名里的括号最常见：`sho_\(sho_lwlw\)`
        self.assertEqual(
            convert_sd_to_nai(r"artist:sho_\(sho_lwlw\)"), "artist:sho_(sho_lwlw)"
        )

    def test_colon_without_number_is_not_a_weight(self) -> None:
        # `artist:foo` 的冒号不是权重，不能吃掉右半边
        self.assertEqual(convert_sd_to_nai("(artist:ciloranko)"), "{artist:ciloranko}")

    def test_square_bracket_is_preserved_and_recursed(self) -> None:
        self.assertEqual(convert_sd_to_nai("[(blurry:1.2)]"), "[1.2::blurry::]")

    def test_integer_weight_drops_trailing_zero(self) -> None:
        self.assertEqual(convert_sd_to_nai("(x:2.0)"), "2::x::")

    def test_unbalanced_parenthesis_is_left_alone(self) -> None:
        self.assertEqual(convert_sd_to_nai("(x:1.2"), "(x:1.2")

    def test_plain_prompt_is_unchanged(self) -> None:
        prompt = "1girl, solo, twintails, best quality"
        self.assertEqual(convert_sd_to_nai(prompt), prompt)

    def test_empty_input(self) -> None:
        self.assertEqual(convert_sd_to_nai(""), "")
        self.assertEqual(convert_sd_to_nai(None), "")


class NaiToSdTest(unittest.TestCase):
    def test_double_colon_becomes_explicit_weight(self) -> None:
        self.assertEqual(convert_nai_to_sd("1.2::masterpiece::"), "(masterpiece:1.2)")

    def test_brace_becomes_105(self) -> None:
        self.assertEqual(convert_nai_to_sd("{twintails}"), "(twintails:1.05)")

    def test_bracket_is_preserved(self) -> None:
        self.assertEqual(convert_nai_to_sd("[blurry]"), "[blurry]")

    def test_literal_parenthesis_is_escaped(self) -> None:
        self.assertEqual(
            convert_nai_to_sd("artist:sho_(sho_lwlw)"), r"artist:sho_\(sho_lwlw\)"
        )

    def test_nested_brace_inside_weight(self) -> None:
        self.assertEqual(
            convert_nai_to_sd("1.3::{smile}::"), "((smile:1.05):1.3)"
        )

    def test_unterminated_weight_is_left_alone(self) -> None:
        self.assertEqual(convert_nai_to_sd("1.2::x"), "1.2::x")

    def test_empty_input(self) -> None:
        self.assertEqual(convert_nai_to_sd(""), "")
        self.assertEqual(convert_nai_to_sd(None), "")


class RoundTripTest(unittest.TestCase):
    def test_explicit_weight_survives_round_trip(self) -> None:
        for source in ("1.2::masterpiece::", "0.8::blurry::", "2::x::"):
            with self.subTest(source=source):
                self.assertEqual(
                    convert_sd_to_nai(convert_nai_to_sd(source)), source
                )

    def test_brace_survives_round_trip(self) -> None:
        self.assertEqual(convert_sd_to_nai(convert_nai_to_sd("{x}")), "{x}")


class StripInlineTagsTest(unittest.TestCase):
    def test_lora_tag_is_removed_with_its_comma(self) -> None:
        self.assertEqual(
            strip_inline_tags("1girl, <lora:styleXL:0.8>, solo"), "1girl, solo"
        )

    def test_lyco_and_hypernet_are_removed(self) -> None:
        self.assertEqual(
            strip_inline_tags("<lyco:a:1>, 1girl, <hypernet:b:1>"), "1girl"
        )

    def test_case_insensitive(self) -> None:
        self.assertEqual(strip_inline_tags("<LoRA:x:1>, 1girl"), "1girl")

    def test_weight_syntax_is_not_touched(self) -> None:
        # 剥标签不该顺手改方言，转不转由调用方决定
        self.assertEqual(
            strip_inline_tags("(masterpiece:1.2), <lora:x:1>"), "(masterpiece:1.2)"
        )

    def test_plain_prompt_is_unchanged(self) -> None:
        self.assertEqual(strip_inline_tags("1girl, solo"), "1girl, solo")


if __name__ == "__main__":
    unittest.main()

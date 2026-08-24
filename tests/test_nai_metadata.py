from __future__ import annotations

import json
import asyncio
import sys
import types
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image, PngImagePlugin


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

import logging

astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("test.nai_meta")
astrbot_module.api = astrbot_api_module
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)

from astrbot_plugin_bestnai_x.services.nai_metadata import (
    is_trusted_nai_generation_info,
    parse_nai_info,
    read_image_generation_info,
    read_image_generation_info_any,
)
from astrbot_plugin_bestnai_x.services.prompt_builder import apply_prompt_weight
from astrbot_plugin_bestnai_x.constants import MAX_SEED, normalize_nai_seed
from astrbot_plugin_bestnai_x.core.generator import ImageGenerator


NAI_COMMENT = {
    "prompt": "1girl, solo, twintails, best quality",
    "uc": "lowres, bad anatomy",
    "steps": 28,
    "height": 1216,
    "width": 832,
    "scale": 7.0,
    "sampler": "k_euler_ancestral",
    "seed": 3405988762,
    "noise_schedule": "karras",
}


def _nai_png(tmp_path: Path, **overrides) -> Path:
    comment = {**NAI_COMMENT, **overrides}
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Software", "NovelAI")
    meta.add_text("Description", comment["prompt"])
    meta.add_text("Comment", json.dumps(comment))
    path = tmp_path / "nai.png"
    Image.new("RGB", (32, 32), (10, 20, 30)).save(path, format="PNG", pnginfo=meta)
    return path


class NaiMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_seed_prompt_and_parameters(self) -> None:
        info = read_image_generation_info(_nai_png(self.tmp_path))

        self.assertEqual(info["seed"], 3405988762)
        self.assertEqual(info["steps"], 28)
        self.assertEqual(info["scale"], 7.0)
        self.assertEqual(info["sampler"], "k_euler_ancestral")
        self.assertEqual(info["prompt"], "1girl, solo, twintails, best quality")
        self.assertEqual(info["negativePrompt"], "lowres, bad anatomy")

    def test_async_reader_supports_local_canvas_or_qq_path(self) -> None:
        info = asyncio.run(read_image_generation_info_any(_nai_png(self.tmp_path)))
        self.assertEqual(info["seed"], 3405988762)

    def test_reencoding_drops_metadata(self) -> None:
        # 这是本功能最重要的边界：图片被重存后元数据必然丢失，
        # 所以 QQ 收到的图基本读不到种子
        source = _nai_png(self.tmp_path)
        for fmt, name in (("JPEG", "x.jpg"), ("WEBP", "x.webp"), ("PNG", "x2.png")):
            with self.subTest(fmt=fmt):
                target = self.tmp_path / name
                with Image.open(source) as im:
                    im.convert("RGB").save(target, format=fmt)
                self.assertEqual(read_image_generation_info(target), {})

    def test_plain_image_returns_empty(self) -> None:
        path = self.tmp_path / "plain.png"
        Image.new("RGB", (8, 8), (0, 0, 0)).save(path, format="PNG")

        self.assertEqual(read_image_generation_info(path), {})

    def test_missing_file_returns_empty(self) -> None:
        self.assertEqual(read_image_generation_info(self.tmp_path / "nope.png"), {})

    def test_broken_comment_json_falls_back_to_description(self) -> None:
        meta = PngImagePlugin.PngInfo()
        meta.add_text("Comment", "{ 这不是合法 JSON")
        meta.add_text("Description", "1girl, solo")
        path = self.tmp_path / "broken.png"
        Image.new("RGB", (8, 8), (1, 2, 3)).save(path, format="PNG", pnginfo=meta)

        info = read_image_generation_info(path)
        self.assertEqual(info["prompt"], "1girl, solo")
        self.assertNotIn("seed", info)

    def test_plain_description_is_not_trusted_as_novelai_prompt(self) -> None:
        self.assertFalse(
            is_trusted_nai_generation_info({"prompt": "ordinary image caption"})
        )

    def test_seed_or_novelai_software_makes_prompt_trusted(self) -> None:
        self.assertTrue(
            is_trusted_nai_generation_info({"prompt": "1girl", "seed": 123})
        )
        self.assertTrue(
            is_trusted_nai_generation_info(
                {"prompt": "1girl", "software": "NovelAI"}
            )
        )

    def test_seedless_generation_fields_can_still_be_trusted(self) -> None:
        self.assertTrue(
            is_trusted_nai_generation_info(
                {
                    "prompt": "1girl, solo",
                    "steps": 28,
                    "sampler": "k_euler_ancestral",
                }
            )
        )
        self.assertFalse(
            is_trusted_nai_generation_info(
                {"prompt": "ordinary image caption", "width": 1024, "height": 768}
            )
        )

    def test_parses_v4_char_captions(self) -> None:
        comment = {
            **NAI_COMMENT,
            "v4_prompt": {
                "caption": {
                    "base_caption": NAI_COMMENT["prompt"],
                    "char_captions": [
                        {
                            "char_caption": "hatsune miku, twintails",
                            "centers": [{"x": 0.3, "y": 0.5}],
                        },
                        {"char_caption": "kagamine rin, blonde hair"},
                    ],
                },
                "use_coords": True,
                "use_order": True,
            },
            "v4_negative_prompt": {
                "caption": {
                    "base_caption": NAI_COMMENT["uc"],
                    "char_captions": [
                        {"char_caption": "bad hands"},
                        {"char_caption": ""},
                    ],
                },
            },
        }

        info = parse_nai_info({"Comment": json.dumps(comment)})

        self.assertEqual(
            info["characterPrompts"],
            [
                {
                    "prompt": "hatsune miku, twintails",
                    "negative": "bad hands",
                    "x": 0.3,
                    "y": 0.5,
                },
                {
                    "prompt": "kagamine rin, blonde hair",
                    "negative": "",
                    "x": None,
                    "y": None,
                },
            ],
        )
        self.assertTrue(info["characterUseCoords"])
        self.assertTrue(info["characterUseOrder"])

    def test_char_captions_absent_without_v4_prompt_or_malformed_entries(self) -> None:
        # V4.5 之前的图没有 v4_prompt 结构
        self.assertNotIn(
            "characterPrompts",
            parse_nai_info({"Comment": json.dumps(NAI_COMMENT)}),
        )
        malformed = {
            **NAI_COMMENT,
            "v4_prompt": {
                "caption": {"char_captions": [{"nope": 1}, 42, "", {"char_caption": "   "}]},
            },
        }
        self.assertNotIn(
            "characterPrompts",
            parse_nai_info({"Comment": json.dumps(malformed)}),
        )

    def test_reads_char_captions_from_png(self) -> None:
        path = _nai_png(
            self.tmp_path,
            v4_prompt={
                "caption": {
                    "base_caption": NAI_COMMENT["prompt"],
                    "char_captions": [{"char_caption": "hatsune miku"}],
                },
                "use_coords": False,
                "use_order": True,
            },
        )

        info = read_image_generation_info(path)

        self.assertEqual(
            info["characterPrompts"],
            [{"prompt": "hatsune miku", "negative": "", "x": None, "y": None}],
        )
        self.assertFalse(info["characterUseCoords"])
        # 带角色提示词不影响可信判定与种子读取
        self.assertTrue(is_trusted_nai_generation_info(info))
        self.assertEqual(info["seed"], 3405988762)

    def test_invalid_numbers_are_dropped(self) -> None:
        info = parse_nai_info(
            {"Comment": json.dumps({"seed": "abc", "steps": 0, "scale": "x"})}
        )

        self.assertNotIn("seed", info)
        self.assertNotIn("steps", info)
        self.assertNotIn("scale", info)

    def test_zero_seed_is_rejected(self) -> None:
        info = parse_nai_info({"Comment": json.dumps({"seed": 0})})
        self.assertNotIn("seed", info)

    def test_negative_fractional_boolean_and_oversized_seeds_are_rejected(self) -> None:
        for value in (-1, 1.5, True, MAX_SEED + 1, "1.5"):
            with self.subTest(value=value):
                info = parse_nai_info({"Comment": json.dumps({"seed": value})})
                self.assertNotIn("seed", info)

    def test_seed_can_be_received_as_an_integer_string(self) -> None:
        info = parse_nai_info({"Comment": json.dumps({"seed": "3405988762"})})
        self.assertEqual(info["seed"], 3405988762)

    def test_seed_range_keeps_unsigned_32_bit_values(self) -> None:
        self.assertEqual(MAX_SEED, 4_294_967_295)
        self.assertLess(3405988762, MAX_SEED)
        self.assertEqual(ImageGenerator._resolve_seed(3405988762), 3405988762)

    def test_shared_seed_normalizer_has_one_boundary_rule(self) -> None:
        self.assertEqual(normalize_nai_seed("3405988762"), 3405988762)
        self.assertIsNone(normalize_nai_seed(True))
        self.assertIsNone(normalize_nai_seed(1.5))
        self.assertIsNone(normalize_nai_seed(MAX_SEED + 1))


class PromptWeightTest(unittest.TestCase):
    def test_wraps_with_novelai_numeric_syntax(self) -> None:
        self.assertEqual(
            apply_prompt_weight("1girl, blue hair", 1.3),
            "1.3::1girl, blue hair ::",
        )

    def test_weight_of_one_is_left_alone(self) -> None:
        self.assertEqual(apply_prompt_weight("1girl", 1.0), "1girl")

    def test_weight_below_one_is_left_alone(self) -> None:
        self.assertEqual(apply_prompt_weight("1girl", 0.8), "1girl")

    def test_empty_input_returns_empty(self) -> None:
        for value in ("", "   ", ",", None):
            with self.subTest(value=value):
                self.assertEqual(apply_prompt_weight(value), "")

    def test_already_weighted_text_is_not_double_wrapped(self) -> None:
        self.assertEqual(
            apply_prompt_weight("1.5::1girl ::", 1.3),
            "1.5::1girl ::",
        )

    def test_mixed_weighted_text_is_kept_valid(self) -> None:
        self.assertEqual(
            apply_prompt_weight("1girl, 1.5::blue_hair ::, night", 1.3),
            "1.3::1girl ::, 1.5::blue_hair ::, 1.3::night ::",
        )

    def test_trailing_comma_is_trimmed(self) -> None:
        self.assertEqual(apply_prompt_weight("1girl,", 1.3), "1.3::1girl ::")

    def test_integer_weight_has_no_trailing_zero(self) -> None:
        self.assertEqual(apply_prompt_weight("1girl", 2.0), "2::1girl ::")

    def test_trailing_number_is_separated_from_closing_marker(self) -> None:
        # `year 2025::` 会被解析成"权重 2025 的新段落"，收尾 :: 前必须有空格
        result = apply_prompt_weight("1girl, year 2025", 1.3)
        self.assertEqual(result, "1.3::1girl, year 2025 ::")
        self.assertNotRegex(result, r"\d::$")

    def test_invalid_weight_returns_plain_text(self) -> None:
        self.assertEqual(apply_prompt_weight("1girl", "abc"), "1girl")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import asyncio
import struct
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
    parse_user_comment_text,
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


def _build_exif_user_comment(payload: bytes) -> bytes:
    """构造最小 EXIF：IFD0 → ExifIFD → UserComment(0x9286)。

    JPEG / WebP 保存时 Pillow 需要带 ``Exif\\0\\0`` 前缀的完整字节串。
    """

    exif_ifd_offset = 8 + 2 + 12 + 4
    payload_offset = exif_ifd_offset + 2 + 12 + 4
    tiff = b"II" + struct.pack("<HI", 42, 8)
    tiff += struct.pack("<H", 1)
    tiff += struct.pack("<HHI", 0x8769, 4, 1) + struct.pack("<I", exif_ifd_offset)
    tiff += struct.pack("<I", 0)
    tiff += struct.pack("<H", 1)
    tiff += struct.pack("<HHI", 0x9286, 7, len(payload)) + struct.pack("<I", payload_offset)
    tiff += struct.pack("<I", 0)
    return b"Exif\x00\x00" + tiff + payload


def _image_with_user_comment(
    tmp_path: Path,
    name: str,
    fmt: str,
    payload: bytes,
) -> Path:
    path = tmp_path / name
    Image.new("RGB", (32, 32), (10, 20, 30)).save(
        path,
        format=fmt,
        exif=_build_exif_user_comment(payload),
    )
    return path


def _nai_user_comment_payload(comment: dict, charset: str = "ASCII") -> bytes:
    body = json.dumps(comment).encode("utf-8")
    prefix = {
        "ASCII": b"ASCII\x00\x00\x00",
        "UNICODE": b"UNICODE\x00",
        "none": b"",
    }[charset]
    return prefix + body


SD_PARAMETERS = (
    "masterpiece, 1girl, solo, silver hair\n"
    "Negative prompt: lowres, bad anatomy\n"
    "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1234567, Size: 832x1216"
)


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


class NaiWebpJpegMetadataTest(unittest.TestCase):
    """NovelAI 新版默认导出是 WebP/JPEG，参数 JSON 在 EXIF UserComment 里。"""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_nai_webp_user_comment_json(self) -> None:
        # NAI 官方导出的 WebP：ASCII 字符集前缀 + UTF-8 JSON
        path = _image_with_user_comment(
            self.tmp_path,
            "nai.webp",
            "WEBP",
            _nai_user_comment_payload(NAI_COMMENT),
        )

        info = read_image_generation_info(path)

        self.assertEqual(info["prompt"], NAI_COMMENT["prompt"])
        self.assertEqual(info["negativePrompt"], NAI_COMMENT["uc"])
        self.assertEqual(info["seed"], 3405988762)
        self.assertEqual(info["steps"], 28)
        self.assertEqual(info["sampler"], "k_euler_ancestral")
        # 带 seed 的内嵌参数可信，导入画布时可以直接复用而不必视觉反推
        self.assertTrue(is_trusted_nai_generation_info(info))

    def test_reads_nai_jpeg_unicode_user_comment(self) -> None:
        # UNICODE 字符集前缀 + UTF-16 正文
        payload = b"UNICODE\x00" + json.dumps(NAI_COMMENT).encode("utf-16-le")
        path = _image_with_user_comment(self.tmp_path, "nai.jpg", "JPEG", payload)

        info = read_image_generation_info(path)

        self.assertEqual(info["prompt"], NAI_COMMENT["prompt"])
        self.assertEqual(info["seed"], 3405988762)

    def test_reads_nai_user_comment_without_charset_prefix(self) -> None:
        # 有些实现不写 8 字节字符集标记，正文直接从 JSON 开头
        path = _image_with_user_comment(
            self.tmp_path,
            "nai_raw.webp",
            "WEBP",
            _nai_user_comment_payload(NAI_COMMENT, charset="none"),
        )

        info = read_image_generation_info(path)
        self.assertEqual(info["prompt"], NAI_COMMENT["prompt"])

    def test_reads_char_captions_from_webp_user_comment(self) -> None:
        comment = {
            **NAI_COMMENT,
            "v4_prompt": {
                "caption": {
                    "base_caption": NAI_COMMENT["prompt"],
                    "char_captions": [
                        {"char_caption": "hatsune miku", "centers": [{"x": 0.4, "y": 0.6}]},
                    ],
                },
                "use_coords": True,
                "use_order": True,
            },
        }
        path = _image_with_user_comment(
            self.tmp_path,
            "nai_chars.webp",
            "WEBP",
            _nai_user_comment_payload(comment),
        )

        info = read_image_generation_info(path)

        self.assertEqual(
            info["characterPrompts"],
            [{"prompt": "hatsune miku", "negative": "", "x": 0.4, "y": 0.6}],
        )
        self.assertTrue(info["characterUseCoords"])

    def test_random_user_comment_text_is_ignored(self) -> None:
        # 无关的 EXIF 备注不是生成参数，不能当 prompt 用
        for text in ("我家猫的照片", "nothing here", "{ 这不是合法 JSON"):
            with self.subTest(text=text):
                self.assertEqual(parse_user_comment_text(text), {})
        path = _image_with_user_comment(
            self.tmp_path, "note.jpg", "JPEG", b"ASCII\x00\x00\x00my cat photo"
        )
        self.assertEqual(read_image_generation_info(path), {})


class SdWebuiMetadataTest(unittest.TestCase):
    """SD WebUI 的 parameters 三段式文本（spell.novelai.dev 的口径）。"""

    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_sd_parameters_from_png_text_chunk(self) -> None:
        meta = PngImagePlugin.PngInfo()
        meta.add_text("parameters", SD_PARAMETERS)
        path = self.tmp_path / "sd.png"
        Image.new("RGB", (16, 16), (1, 2, 3)).save(path, format="PNG", pnginfo=meta)

        info = read_image_generation_info(path)

        self.assertEqual(info["prompt"], "masterpiece, 1girl, solo, silver hair")
        self.assertEqual(info["negativePrompt"], "lowres, bad anatomy")
        self.assertEqual(info["steps"], 20)
        self.assertEqual(info["sampler"], "Euler a")
        self.assertEqual(info["scale"], 7.0)
        self.assertEqual(info["seed"], 1234567)
        self.assertEqual(info["width"], 832)
        self.assertEqual(info["height"], 1216)
        self.assertTrue(is_trusted_nai_generation_info(info))

    def test_reads_sd_parameters_from_jpeg_user_comment(self) -> None:
        payload = b"ASCII\x00\x00\x00" + SD_PARAMETERS.encode("utf-8")
        path = _image_with_user_comment(self.tmp_path, "sd.jpg", "JPEG", payload)

        info = read_image_generation_info(path)

        self.assertEqual(info["prompt"], "masterpiece, 1girl, solo, silver hair")
        self.assertEqual(info["seed"], 1234567)

    def test_sd_parameters_without_negative_prompt(self) -> None:
        text = "1girl, solo\nSteps: 28, Sampler: DPM++ 2M Karras, CFG scale: 5, Seed: 42, Size: 1024x1024"
        info = parse_user_comment_text(text)

        self.assertEqual(info["prompt"], "1girl, solo")
        self.assertNotIn("negativePrompt", info)
        self.assertEqual(info["steps"], 28)
        self.assertEqual(info["scale"], 5.0)
        self.assertEqual(info["seed"], 42)

    def test_nai_comment_takes_priority_over_sd_parameters(self) -> None:
        # NovelAI 格式和 SD 格式同存时（正常不会发生），NovelAI 优先
        meta = PngImagePlugin.PngInfo()
        meta.add_text("Comment", json.dumps(NAI_COMMENT))
        meta.add_text("parameters", SD_PARAMETERS)
        info = parse_nai_info(
            {"Comment": json.dumps(NAI_COMMENT), "parameters": SD_PARAMETERS}
        )

        self.assertEqual(info["prompt"], NAI_COMMENT["prompt"])
        self.assertEqual(info["seed"], 3405988762)

    def test_sd_weights_are_converted_to_nai_dialect(self) -> None:
        # 这些参数的用途是「拿原图参数再生成一张」，而生成走 NovelAI。
        # SD 的 (tag:1.2) 到了 NAI 那边只是字面括号，不转等于丢权重。
        text = (
            "masterpiece, (silver hair:1.2), (blurry:0.95)\n"
            "Negative prompt: (lowres:1.3), bad anatomy\n"
            "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1234567"
        )

        info = parse_user_comment_text(text)

        self.assertEqual(info["prompt"], "masterpiece, 1.2::silver hair::, [blurry]")
        self.assertEqual(info["negativePrompt"], "1.3::lowres::, bad anatomy")

    def test_lora_tags_are_stripped_from_sd_prompt(self) -> None:
        text = (
            "1girl, <lora:styleXL:0.8>, solo\n"
            "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 1"
        )

        info = parse_user_comment_text(text)

        self.assertEqual(info["prompt"], "1girl, solo")

    def test_novelai_prompt_is_never_run_through_the_converter(self) -> None:
        # NAI 分支的提示词已经是 NAI 方言，再转一次会把角色名里的
        # 括号（sho_(sho_lwlw)）变成权重记号。
        comment = {**NAI_COMMENT, "prompt": "artist:sho_(sho_lwlw), 1girl"}

        info = parse_nai_info({"Comment": json.dumps(comment)})

        self.assertEqual(info["prompt"], "artist:sho_(sho_lwlw), 1girl")


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

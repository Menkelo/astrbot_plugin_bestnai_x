from __future__ import annotations

import asyncio
import base64
import logging
import random
import sys
import tempfile
import types
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
from PIL.PngImagePlugin import PngInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
api = sys.modules.setdefault("astrbot.api", types.ModuleType("astrbot.api"))
api.logger = logging.getLogger("test.image_input")
sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))

from astrbot_plugin_bestnai_x.core import image_input
from astrbot_plugin_bestnai_x.core.image_input import ImageInputError, static_png, vision_image_path
from astrbot_plugin_bestnai_x.core.image_retagger import ImageRetagError, ImageRetagger
from astrbot_plugin_bestnai_x.services.image_extract import find_image_in_segments
from astrbot_plugin_bestnai_x.services.image_ratio import read_image_size_any
from astrbot_plugin_bestnai_x.services.nai_metadata import read_image_generation_info_any


def image_bytes(fmt="PNG", *, size=(48, 32), mode="RGB", **kwargs):
    output = BytesIO()
    with Image.new(mode, size) as image:
        image.save(output, format=fmt, **kwargs)
    return output.getvalue()


def animated_gif(*, transparent_first=False):
    frames = [Image.new("P", (48, 32), index) for index in (0, 1)]
    for frame in frames:
        frame.putpalette([255, 0, 0, 0, 255, 0] + [0] * 762)
    output = BytesIO()
    frames[0].save(
        output, format="GIF", save_all=True, append_images=frames[1:],
        loop=0, duration=100, disposal=2, optimize=False,
        **({"transparency": 0} if transparent_first else {}),
    )
    for frame in frames:
        frame.close()
    return output.getvalue()


class FakeResponse:
    def __init__(self, data, *, status=200, content_length=None, chunks=None):
        self.status = status
        self.content_length = content_length
        # Simulate a QQ URL whose filename and Content-Type disagree with its bytes.
        self.headers = {"Content-Type": "application/octet-stream"}
        self.chunks = chunks if chunks is not None else [data]
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def mock_download(response):
    session = FakeSession(response)
    fake_aiohttp = SimpleNamespace(
        ClientSession=lambda **kwargs: session,
        ClientTimeout=lambda **kwargs: kwargs,
        ClientError=ConnectionError,
    )
    return session, patch.object(image_input, "aiohttp", fake_aiohttp)


class InspectingContext:
    def __init__(self, error=None):
        self.error = error
        self.calls = []
        self.images = []
        self.provider = SimpleNamespace(model_name="fixture-vision")

    def get_provider_by_id(self, provider_id):
        return self.provider

    async def llm_generate(self, **kwargs):
        self.calls.append(kwargs)
        path = Path(kwargs["image_urls"][0])
        with Image.open(path) as image:
            image.load()
            self.images.append({
                "format": image.format, "mode": image.mode, "frames": getattr(image, "n_frames", 1),
                "pixel": image.convert("RGB").getpixel((0, 0)),
            })
        if self.error:
            raise self.error
        return SimpleNamespace(completion_text='{"character":"","series":"","tags":"1girl, green hair"}')


class StaticImageTest(unittest.TestCase):
    def test_common_formats_and_color_modes_become_valid_static_png(self):
        for fmt, mode in (
            ("PNG", "P"), ("JPEG", "CMYK"), ("WEBP", "RGBA"), ("GIF", "P"),
            ("BMP", "RGB"), ("TIFF", "L"), ("ICO", "RGBA"), ("AVIF", "RGB"),
        ):
            with self.subTest(format=fmt, mode=mode):
                data = image_bytes(fmt, size=(32, 32), mode=mode)
                result = static_png(data)
                self.assertEqual(result.source_format, fmt)
                with Image.open(BytesIO(result.data)) as image:
                    image.load()
                    self.assertEqual(image.format, "PNG")
                    self.assertIn(image.mode, {"RGB", "RGBA"})
                    self.assertEqual(getattr(image, "n_frames", 1), 1)

    def test_gif_uses_first_visible_frame_and_preserves_transparency(self):
        result = static_png(animated_gif(transparent_first=True))
        self.assertEqual(result.frame_index, 1)
        with Image.open(BytesIO(result.data)) as image:
            self.assertEqual(image.convert("RGBA").getpixel((0, 0)), (0, 255, 0, 255))
        result = static_png(image_bytes(mode="RGBA"))
        with Image.open(BytesIO(result.data)) as image:
            self.assertEqual(image.getchannel("A").getextrema(), (0, 0))

    def test_tiff_uses_first_page(self):
        output = BytesIO()
        first = Image.new("RGB", (40, 20), "red")
        second = Image.new("RGB", (20, 40), "green")
        first.save(output, format="TIFF", save_all=True, append_images=[second])
        result = static_png(output.getvalue())
        self.assertEqual(result.original_size, (40, 20))
        self.assertEqual(result.frame_index, 0)
        with Image.open(BytesIO(result.data)) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))

    def test_16_bit_tiff_does_not_turn_midtones_white(self):
        output = BytesIO()
        Image.new("I;16", (32, 24), 32768).save(output, format="TIFF")
        with Image.open(BytesIO(static_png(output.getvalue()).data)) as image:
            self.assertAlmostEqual(image.getpixel((0, 0))[0], 128, delta=1)

    def test_animated_png_and_webp_are_flattened(self):
        for fmt in ("PNG", "WEBP"):
            with self.subTest(format=fmt):
                output = BytesIO()
                Image.new("RGB", (32, 24), "red").save(
                    output, format=fmt, save_all=True,
                    append_images=[Image.new("RGB", (32, 24), "blue")], duration=100, loop=0,
                )
                with Image.open(BytesIO(static_png(output.getvalue()).data)) as image:
                    image.load()
                    self.assertEqual(getattr(image, "n_frames", 1), 1)
                    self.assertGreater(image.getpixel((0, 0))[0], 240)

    def test_orientation_is_applied_once_and_metadata_is_not_forwarded(self):
        exif = Image.Exif()
        exif[274] = 6
        result = static_png(image_bytes("JPEG", size=(80, 40), exif=exif))
        self.assertEqual(result.original_size, (40, 80))
        with Image.open(BytesIO(result.data)) as image:
            self.assertEqual(image.size, (40, 80))
            self.assertFalse(image.getexif())

    def test_dimensions_and_encoded_payload_are_bounded(self):
        result = static_png(image_bytes(size=(400, 200)), max_side=64)
        self.assertEqual(result.size, (64, 32))
        image = Image.frombytes("RGB", (320, 200), random.Random(7).randbytes(320 * 200 * 3))
        output = BytesIO()
        image.save(output, "PNG")
        result = static_png(output.getvalue(), max_side=256, max_bytes=12000)
        self.assertLessEqual(len(result.data), 12000)
        self.assertLess(result.size[0], 256)

    def test_invalid_content_and_oversize_are_rejected(self):
        for data in (b"", b"<html>expired</html>", b'{"error":"expired"}', image_bytes()[:30], image_bytes("JPEG")[:-20]):
            with self.subTest(data=data[:20]), self.assertRaises(ImageInputError):
                static_png(data)
        with patch.object(image_input, "MAX_IMAGE_PIXELS", 100), self.assertRaisesRegex(ImageInputError, "像素"):
            static_png(image_bytes(size=(11, 10)))
        with patch.object(image_input, "MAX_IMAGE_BYTES", 10), self.assertRaisesRegex(ImageInputError, "15 MB"):
            static_png(image_bytes())


class ImageInputAsyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "QQ 动图.gif"
        self.path.write_bytes(animated_gif())

    async def test_canvas_local_gif_is_converted_only_for_provider(self):
        context = InspectingContext()
        original = self.path.read_bytes()
        result = await ImageRetagger(SimpleNamespace(provider_id="vision"), context).retag_details(str(self.path))
        self.assertEqual(result["prompt"], "1girl, green hair")
        self.assertEqual(context.images[0]["format"], "PNG")
        self.assertEqual(context.images[0]["frames"], 1)
        self.assertEqual(context.images[0]["pixel"], (255, 0, 0))
        self.assertEqual(len(context.calls), 1)
        self.assertFalse(Path(context.calls[0]["image_urls"][0]).exists())
        self.assertEqual(self.path.read_bytes(), original)

    async def test_qq_url_is_downloaded_then_passed_as_static_file(self):
        context = InspectingContext()
        source = "https://multimedia.example/qq-image.jpg?token=secret"
        session, mocked = mock_download(FakeResponse(animated_gif(transparent_first=True)))
        with mocked:
            await ImageRetagger(SimpleNamespace(provider_id="vision"), context).retag_details(source)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][0], source)
        self.assertEqual(set(session.calls[0][1]["headers"]), {"User-Agent", "Accept"})
        self.assertEqual(context.images[0]["format"], "PNG")
        self.assertEqual(context.images[0]["pixel"], (0, 255, 0))
        self.assertNotEqual(context.calls[0]["image_urls"], [source])

    async def test_bad_downloads_fail_before_provider_and_hide_url_credentials(self):
        for response in (FakeResponse(b"<html>expired</html>"), FakeResponse(b""), FakeResponse(b"error", status=403)):
            context = InspectingContext()
            _, mocked = mock_download(response)
            with mocked, self.assertRaises(ImageRetagError) as caught:
                await ImageRetagger(SimpleNamespace(provider_id="vision"), context).retag_details(
                    "https://image.example/path?token=private-secret"
                )
            self.assertEqual(context.calls, [])
            self.assertNotIn("private-secret", str(caught.exception))
            self.assertNotIn("API Key", str(caught.exception))
        self.assertIn("HTTP 403", str(caught.exception))

    async def test_stream_and_content_length_limits_are_enforced(self):
        for response in (
            FakeResponse(b"x", content_length=11),
            FakeResponse(b"", chunks=[b"123456", b"abcdef"]),
        ):
            _, mocked = mock_download(response)
            with mocked, patch.object(image_input, "MAX_IMAGE_BYTES", 10), self.assertRaisesRegex(ImageInputError, "15 MB"):
                await image_input.read_image_bytes("https://image.example/picture")

    async def test_inline_and_file_uri_sources_work(self):
        data = self.path.read_bytes()
        encoded = base64.b64encode(data).decode()
        for source in (self.path.as_uri(), "file://" + str(self.path), "data:image/gif;base64," + encoded, "base64://" + encoded):
            with self.subTest(source=source[:50]):
                self.assertEqual(await image_input.read_image_bytes(source), data)
                self.assertEqual(await read_image_size_any(source), (48, 32))
                self.assertEqual(find_image_in_segments({"type": "image", "data": {"file": source}}), source)

    async def test_temp_file_is_removed_after_provider_failure_and_cancellation(self):
        for error in (RuntimeError("upstream unavailable"), asyncio.CancelledError()):
            context = InspectingContext(error)
            expected = asyncio.CancelledError if isinstance(error, asyncio.CancelledError) else ImageRetagError
            with self.assertRaises(expected):
                await ImageRetagger(SimpleNamespace(provider_id="vision"), context).retag_details(str(self.path))
            self.assertEqual(len(context.calls), 1)
            self.assertFalse(Path(context.calls[0]["image_urls"][0]).parent.exists())
            self.assertTrue(self.path.is_file())

    async def test_original_metadata_survives_vision_preparation(self):
        info = PngInfo()
        info.add_text("Software", "NovelAI")
        info.add_text("Comment", '{"prompt":"1girl, blue hair","seed":12345,"steps":28}')
        data = image_bytes(pnginfo=info)
        self.path.write_bytes(data)
        before = await read_image_generation_info_any(self.path)
        async with vision_image_path(self.path) as converted:
            with Image.open(converted) as image:
                self.assertNotIn("Comment", image.info)
        after = await read_image_generation_info_any(self.path)
        self.assertEqual(before["seed"], 12345)
        self.assertEqual(before, after)
        self.assertEqual(self.path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()

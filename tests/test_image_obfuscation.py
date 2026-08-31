from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from astrbot_plugin_bestnai_x.services.image_obfuscation import (
    obfuscate_image_bytes,
)
from astrbot_plugin_bestnai_x.services.nai_metadata import read_image_generation_info


class ImageObfuscationTest(unittest.TestCase):
    def test_obfuscation_preserves_dimensions_and_uses_png(self) -> None:
        source = Image.new("RGB", (32, 24), "white")
        for x in range(16, 32):
            for y in range(12, 24):
                source.putpixel((x, y), (255, 0, 0))

        raw = io.BytesIO()
        source.save(raw, format="PNG")
        result = obfuscate_image_bytes(raw.getvalue(), key=1.0)

        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, source.size)
            self.assertNotEqual(image.tobytes(), source.tobytes())

    def test_invalid_input_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            obfuscate_image_bytes(b"not an image")

    def test_novelai_comment_is_carried_to_jpeg_user_comment(self) -> None:
        source = Image.new("RGB", (8, 8), "white")
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text("Comment", json.dumps({"prompt": "1girl", "seed": 42}))
        raw = io.BytesIO()
        source.save(raw, format="PNG", pnginfo=metadata)

        result = obfuscate_image_bytes(raw.getvalue())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "obfuscated.jpg"
            path.write_bytes(result)
            info = read_image_generation_info(path)
            self.assertEqual(info.get("prompt"), "1girl")
            self.assertEqual(info.get("seed"), 42)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from astrbot_plugin_bestnai_x.services.image_obfuscation import (
    obfuscate_image_bytes,
)


class ImageObfuscationTest(unittest.TestCase):
    def test_obfuscation_preserves_dimensions_and_format(self) -> None:
        source = Image.new("RGB", (32, 24), "white")
        for x in range(16, 32):
            for y in range(12, 24):
                source.putpixel((x, y), (255, 0, 0))

        raw = io.BytesIO()
        source.save(raw, format="PNG")
        result = obfuscate_image_bytes(raw.getvalue(), block_size=8)

        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, source.size)
            self.assertNotEqual(image.tobytes(), source.tobytes())

    def test_invalid_input_is_rejected(self) -> None:
        with self.assertRaises(Exception):
            obfuscate_image_bytes(b"not an image")


if __name__ == "__main__":
    unittest.main()

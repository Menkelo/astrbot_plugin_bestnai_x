from __future__ import annotations

import tempfile
import unittest
import logging
import sys
import types
from io import BytesIO
from pathlib import Path

from PIL import Image


astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_web_module = types.ModuleType("astrbot.api.web")
astrbot_api_module.logger = logging.getLogger("test.canvas")
astrbot_web_module.error_response = lambda *args, **kwargs: None
astrbot_web_module.file_response = lambda *args, **kwargs: None
astrbot_web_module.json_response = lambda *args, **kwargs: None
astrbot_web_module.request = object()
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)
sys.modules.setdefault("astrbot.api.web", astrbot_web_module)

from services.canvas import CanvasStore, CanvasValidationError


class CanvasStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CanvasStore("test_plugin", Path(self.temp_dir.name))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_workspace_is_sanitized_and_round_trips(self) -> None:
        payload = {
            "viewport": {"x": 12, "y": -9, "scale": 99},
            "nodes": [
                {
                    "id": "prompt_1",
                    "type": "prompt",
                    "x": 10,
                    "y": 20,
                    "width": 9999,
                    "prompt": "1girl",
                    "dataUrl": "data:image/png;base64,not-persisted",
                    "status": "generating",
                },
                {
                    "id": "image_1",
                    "type": "image",
                    "x": 500,
                    "y": 20,
                    "assetId": "a" * 32,
                    "meta": {
                        "prompt": "1girl",
                        "ratio": "2:3",
                        "width": 832,
                        "height": 1216,
                    },
                },
            ],
            "connections": [
                {"source": "prompt_1", "target": "image_1"},
                {"source": "missing", "target": "image_1"},
            ],
        }

        saved = self.store.save_workspace(payload)
        loaded = self.store.load_workspace()

        self.assertEqual(saved["viewport"]["scale"], 4)
        self.assertEqual(saved["nodes"][0]["width"], 640)
        self.assertNotIn("dataUrl", saved["nodes"][0])
        self.assertNotIn("status", saved["nodes"][0])
        self.assertEqual(len(loaded["connections"]), 1)
        self.assertEqual(loaded["nodes"][1]["meta"]["width"], 832)

    def test_duplicate_node_id_is_rejected(self) -> None:
        node = {"id": "same", "type": "note"}
        with self.assertRaises(CanvasValidationError):
            self.store.sanitize_workspace({"nodes": [node, node], "connections": []})

    def test_valid_png_asset_is_stored_and_returned(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (32, 24), (32, 120, 84)).save(buffer, format="PNG")

        asset = self.store.store_asset(buffer.getvalue())
        payload = self.store.asset_payload(asset["id"])

        self.assertEqual(asset["width"], 32)
        self.assertEqual(asset["height"], 24)
        self.assertTrue(payload["dataUrl"].startswith("data:image/png;base64,"))

    def test_invalid_image_is_rejected(self) -> None:
        with self.assertRaises(CanvasValidationError):
            self.store.store_asset(b"this is not an image")


if __name__ == "__main__":
    unittest.main()

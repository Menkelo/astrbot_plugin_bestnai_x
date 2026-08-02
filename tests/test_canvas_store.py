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

from services.canvas import CanvasService, CanvasStore, CanvasValidationError


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
                {
                    "id": "note_1",
                    "type": "note",
                    "x": 80,
                    "y": 120,
                    "width": 420,
                    "height": 900,
                    "note": "layout notes",
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
        self.assertEqual(loaded["nodes"][2]["width"], 420)
        self.assertEqual(loaded["nodes"][2]["height"], 800)

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

    def test_projects_keep_canvas_workspaces_isolated(self) -> None:
        project = self.store.create_project("角色设计")
        first = self.store.create_canvas({"projectId": project["id"], "title": "角色 A"})
        second = self.store.create_canvas({"projectId": project["id"], "title": "角色 B"})

        self.store.save_workspace(
            {"nodes": [{"id": "note_a", "type": "note", "note": "A"}], "connections": []},
            first["id"],
        )
        self.store.save_workspace(
            {"nodes": [{"id": "note_b", "type": "note", "note": "B"}], "connections": []},
            second["id"],
        )

        self.assertEqual(self.store.load_workspace(first["id"])["nodes"][0]["note"], "A")
        self.assertEqual(self.store.load_workspace(second["id"])["nodes"][0]["note"], "B")
        self.assertEqual(len(self.store.list_projects()), 2)

    def test_canvas_trash_restore_and_purge(self) -> None:
        canvas = self.store.create_canvas({"title": "可恢复画布"})
        self.store.trash_canvas(canvas["id"])
        self.assertEqual(self.store.list_canvases(), [])
        self.assertEqual(len(self.store.list_canvases(include_deleted=True)), 1)

        self.store.restore_canvas(canvas["id"])
        self.assertEqual(len(self.store.list_canvases()), 1)
        self.store.trash_canvas(canvas["id"])
        self.store.purge_canvas(canvas["id"])
        self.assertEqual(self.store.list_canvases(include_deleted=True), [])

    def test_image_and_prompt_assets_round_trip(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (48, 32), (90, 120, 200)).save(buffer, format="PNG")
        image = self.store.store_asset(buffer.getvalue())
        self.store.add_image_to_library(image, "天空参考", "upload")
        prompt = self.store.save_prompt_asset(
            {"name": "逆光人像", "prompt": "1girl, backlight", "ratio": "2:3"}
        )

        library = self.store.list_library()
        self.assertEqual(library["images"][0]["name"], "天空参考")
        self.assertEqual(library["prompts"][0]["prompt"], "1girl, backlight")

        self.store.remove_image_from_library(image["id"])
        self.store.delete_prompt_asset(prompt["id"])
        self.assertEqual(self.store.list_library(), {"images": [], "prompts": []})

    def test_legacy_workspace_is_migrated_to_default_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            (data_dir / "workspace.json").write_text(
                '{"nodes":[{"id":"legacy","type":"note","note":"old"}],"connections":[]}',
                encoding="utf-8",
            )
            store = CanvasStore("test_plugin", data_dir)
            canvases = store.list_canvases()

            self.assertEqual(len(canvases), 1)
            self.assertEqual(canvases[0]["projectId"], "default")
            self.assertEqual(store.load_workspace(canvases[0]["id"])["nodes"][0]["note"], "old")

    def test_canvas_registers_retag_route(self) -> None:
        routes = []

        class FakeContext:
            def register_web_api(self, path, handler, methods, description):
                routes.append((path, tuple(methods), description))

        async def generate(payload):
            return [], {}

        async def retag(image_path, user_hint):
            return {"prompt": "1girl", "ratio": "1:1"}

        service = CanvasService(
            "test_plugin",
            generate_callback=generate,
            config_callback=lambda: {},
            retag_callback=retag,
            data_dir=Path(self.temp_dir.name),
        )
        service.register(FakeContext())

        self.assertIn(
            (
                "/test_plugin/canvas/retag",
                ("POST",),
                "Infinite Canvas：反推图片提示词",
            ),
            routes,
        )


if __name__ == "__main__":
    unittest.main()

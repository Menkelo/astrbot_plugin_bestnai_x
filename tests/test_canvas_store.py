from __future__ import annotations

import os
import tempfile
import time
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
from services import canvas as canvas_module


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
                    "height": 490,
                    "meta": {
                        "translatedPrompt": "1girl, blue hair",
                        "translationSource": "蓝发少女",
                        "translationResult": "1girl, blue hair",
                        "translatedPromptExpanded": True,
                        "characterKeep": True,
                        "advancedOpen": True,
                        "steps": 32,
                        "scale": 6.5,
                        "retagPrompt": "hatsune_miku, vocaloid",
                        "retagAssetId": "a" * 32,
                        "retagRatio": "2:3",
                        "tags": "1girl, hatsune_miku, vocaloid",
                    },
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
        self.assertEqual(loaded["nodes"][0]["meta"]["translatedPrompt"], "1girl, blue hair")
        self.assertEqual(loaded["nodes"][0]["meta"]["translationSource"], "蓝发少女")
        self.assertEqual(loaded["nodes"][0]["meta"]["translationResult"], "1girl, blue hair")
        self.assertTrue(loaded["nodes"][0]["meta"]["advancedOpen"])
        self.assertEqual(loaded["nodes"][0]["meta"]["steps"], 32)
        self.assertEqual(loaded["nodes"][0]["meta"]["scale"], 6.5)
        # 已删除的字段走白名单被丢掉，不会随旧工作区一直带着
        self.assertNotIn("translatedPromptExpanded", loaded["nodes"][0]["meta"])
        self.assertNotIn("characterKeep", loaded["nodes"][0]["meta"])
        self.assertEqual(loaded["nodes"][0]["meta"]["retagPrompt"], "hatsune_miku, vocaloid")
        self.assertEqual(loaded["nodes"][0]["meta"]["retagAssetId"], "a" * 32)
        self.assertEqual(loaded["nodes"][0]["meta"]["retagRatio"], "2:3")
        self.assertEqual(loaded["nodes"][0]["meta"]["tags"], "1girl, hatsune_miku, vocaloid")
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

    def test_canvas_preferences_persist_last_canvas_ratio_and_artist(self) -> None:
        first = self.store.create_canvas({"title": "first"})
        saved = self.store.save_preferences(
            {"lastCanvasId": first["id"], "ratio": "3:2", "artist": "watercolor"}
        )

        reopened = CanvasStore("test_plugin", Path(self.temp_dir.name))
        self.assertEqual(reopened.load_preferences(), saved)
        self.assertEqual(saved["lastCanvasId"], first["id"])
        self.assertEqual(saved["ratio"], "3:2")
        self.assertEqual(saved["artist"], "watercolor")

        reopened.trash_canvas(first["id"])
        self.assertEqual(reopened.load_preferences()["lastCanvasId"], "")
        self.assertEqual(reopened.load_preferences()["ratio"], "3:2")
        self.assertEqual(reopened.load_preferences()["artist"], "watercolor")

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
        # 入库只会由用户主动收藏触发，前端传的 source 是 generated / retagged，
        # 所以素材库不该按 source 过滤掉任何条目。
        self.store.add_image_to_library(image, "生成结果", "generated")
        self.assertEqual(len(self.store.list_library()["images"]), 1)
        self.store.add_image_to_library(
            image,
            "天空参考",
            "canvas",
            "蓝色天空",
            "blue sky, clouds",
            "3:2",
            "里番",
            987654321,
        )
        prompt = self.store.save_prompt_asset(
            {"name": "逆光人像", "prompt": "1girl, backlight", "ratio": "2:3"}
        )

        library = self.store.list_library()
        self.assertEqual(library["images"][0]["name"], "天空参考")
        self.assertEqual(library["images"][0]["prompt"], "蓝色天空")
        self.assertEqual(library["images"][0]["tags"], "blue sky, clouds")
        self.assertEqual(library["images"][0]["ratio"], "3:2")
        self.assertEqual(library["images"][0]["artist"], "里番")
        self.assertEqual(library["images"][0]["seed"], 987654321)
        self.assertEqual(library["prompts"][0]["prompt"], "1girl, backlight")

        self.store.remove_image_from_library(image["id"])
        self.store.delete_prompt_asset(prompt["id"])
        self.assertEqual(self.store.list_library(), {"images": [], "prompts": []})

    def _store_aged_asset(self, color: tuple) -> str:
        """存一张图并把 mtime 调老，绕过回收宽限期。"""
        buffer = BytesIO()
        Image.new("RGB", (16, 16), color).save(buffer, format="PNG")
        asset = self.store.store_asset(buffer.getvalue())
        path, _ = self.store.get_asset(asset["id"])
        aged = time.time() - canvas_module.ASSET_GC_GRACE_SECONDS - 60
        os.utime(path, (aged, aged))
        return asset["id"]

    def test_orphan_assets_are_collected_but_referenced_ones_survive(self) -> None:
        node_asset = self._store_aged_asset((10, 20, 30))
        retag_asset = self._store_aged_asset((40, 50, 60))
        library_asset = self._store_aged_asset((70, 80, 90))
        orphan_asset = self._store_aged_asset((100, 110, 120))

        canvas = self.store.create_canvas({"title": "引用检查"})
        self.store.save_workspace(
            {
                "nodes": [
                    {"id": "img", "type": "image", "assetId": node_asset},
                    {
                        "id": "retag",
                        "type": "image",
                        "meta": {"retagAssetId": retag_asset},
                    },
                ],
                "connections": [],
            },
            canvas["id"],
        )
        self.store.add_image_to_library(
            {"id": library_asset, "width": 16, "height": 16, "format": "png"},
            "收藏",
            "generated",
        )

        self.assertEqual(self.store.collect_orphan_assets(), 1)

        for kept in (node_asset, retag_asset, library_asset):
            self.assertIsNotNone(self.store.get_asset(kept))

        with self.assertRaises(FileNotFoundError):
            self.store.get_asset(orphan_asset)

    def test_fresh_assets_are_not_collected(self) -> None:
        buffer = BytesIO()
        Image.new("RGB", (16, 16), (1, 2, 3)).save(buffer, format="PNG")
        fresh = self.store.store_asset(buffer.getvalue())

        # 刚生成、还没进节点的图片处在宽限期内，不能被回收
        self.assertEqual(self.store.collect_orphan_assets(), 0)
        self.assertIsNotNone(self.store.get_asset(fresh["id"]))

    def test_unreadable_workspace_aborts_collection(self) -> None:
        orphan_asset = self._store_aged_asset((5, 5, 5))
        canvas = self.store.create_canvas({"title": "坏工作区"})
        (self.store.workspaces_dir / f"{canvas['id']}.json").write_text(
            "{ 这不是合法 JSON",
            encoding="utf-8",
        )

        # 读不出引用关系时宁可不回收，也不能误删还在用的图
        self.assertEqual(self.store.collect_orphan_assets(), 0)
        self.assertIsNotNone(self.store.get_asset(orphan_asset))

    def test_purging_canvas_releases_its_assets(self) -> None:
        asset_id = self._store_aged_asset((9, 9, 9))
        canvas = self.store.create_canvas({"title": "待删除"})
        self.store.save_workspace(
            {
                "nodes": [{"id": "img", "type": "image", "assetId": asset_id}],
                "connections": [],
            },
            canvas["id"],
        )

        self.assertIsNotNone(self.store.get_asset(asset_id))

        self.store.trash_canvas(canvas["id"])
        self.store.purge_canvas(canvas["id"])

        with self.assertRaises(FileNotFoundError):
            self.store.get_asset(asset_id)

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

    def test_canvas_registers_retag_and_health_routes(self) -> None:
        routes = []

        class FakeContext:
            def register_web_api(self, path, handler, methods, description):
                routes.append((path, tuple(methods), description))

        async def generate(payload):
            return [], {}

        async def retag(image_path, user_hint, keep_character, character_name):
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
        self.assertIn(
            (
                "/test_plugin/canvas/health",
                ("GET",),
                "Infinite Canvas：连接状态检测",
            ),
            routes,
        )
        self.assertIn(
            (
                "/test_plugin/canvas/preferences",
                ("GET",),
                "Infinite Canvas：获取用户偏好",
            ),
            routes,
        )
        self.assertIn(
            (
                "/test_plugin/canvas/asset/download",
                ("GET",),
                "Infinite Canvas：下载图片",
            ),
            routes,
        )
        self.assertIn(
            (
                "/test_plugin/canvas/preferences",
                ("POST",),
                "Infinite Canvas：保存用户偏好",
            ),
            routes,
        )


if __name__ == "__main__":
    unittest.main()

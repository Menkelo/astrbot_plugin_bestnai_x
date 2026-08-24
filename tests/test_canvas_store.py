from __future__ import annotations

import json
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
from PIL.PngImagePlugin import PngInfo


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
                    "retagMode": "replicate",
                    "meta": {
                        "translatedPrompt": "1girl, blue hair",
                        "translationSource": "蓝发少女",
                        "translationResult": "1girl, blue hair",
                        "translationCharacter": "hatsune_miku",
                        "translationSeries": "vocaloid",
                        "translatedPromptExpanded": True,
                        "characterKeep": True,
                        "advancedOpen": True,
                        "steps": 32,
                        "scale": 6.5,
                        "retagPrompt": "hatsune_miku, vocaloid",
                        "retagAssetId": "a" * 32,
                        "retagRatio": "2:3",
                        "retagSeed": 3405988762,
                        "retagSeedPrompt": "1girl",
                        "retagSeedRatio": "2:3",
                        "retagSeedArtist": "default",
                        "retagSeedRaw": False,
                        "retagFromCanvasCache": True,
                        "retagLayerExpanded": True,
                        "retagTagGroups": {
                            "identity": ["hatsune_miku", "vocaloid"],
                            "hair": ["aqua_hair"],
                        },
                        "retagTagTranslations": {
                            "hatsune_miku": "初音未来",
                            "aqua hair": "水蓝色头发",
                        },
                        "retagLayerModes": {
                            "identity": "preserve",
                            "hair": "drop",
                        },
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
                        "tagTranslations": {"1girl": "1个女孩"},
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
        self.assertEqual(loaded["nodes"][0]["meta"]["translationCharacter"], "hatsune_miku")
        self.assertEqual(loaded["nodes"][0]["meta"]["translationSeries"], "vocaloid")
        self.assertNotIn("advancedOpen", loaded["nodes"][0]["meta"])
        self.assertEqual(loaded["nodes"][0]["meta"]["steps"], 32)
        self.assertEqual(loaded["nodes"][0]["meta"]["scale"], 6.5)
        # 已删除的字段走白名单被丢掉，不会随旧工作区一直带着
        self.assertNotIn("translatedPromptExpanded", loaded["nodes"][0]["meta"])
        self.assertNotIn("characterKeep", loaded["nodes"][0]["meta"])
        self.assertEqual(loaded["nodes"][0]["meta"]["retagPrompt"], "hatsune_miku, vocaloid")
        self.assertEqual(loaded["nodes"][0]["meta"]["retagAssetId"], "a" * 32)
        self.assertEqual(loaded["nodes"][0]["meta"]["retagSeed"], 3405988762)
        self.assertEqual(loaded["nodes"][0]["meta"]["retagSeedPrompt"], "1girl")
        self.assertEqual(loaded["nodes"][0]["meta"]["retagSeedRatio"], "2:3")
        self.assertEqual(loaded["nodes"][0]["meta"]["retagSeedArtist"], "default")
        self.assertFalse(loaded["nodes"][0]["meta"]["retagSeedRaw"])
        self.assertNotIn("retagMode", loaded["nodes"][0])
        self.assertTrue(loaded["nodes"][0]["meta"]["retagFromCanvasCache"])
        self.assertTrue(loaded["nodes"][0]["meta"]["retagLayerExpanded"])
        self.assertEqual(
            loaded["nodes"][0]["meta"]["retagTagGroups"]["identity"],
            ["hatsune_miku", "vocaloid"],
        )
        self.assertEqual(
            loaded["nodes"][0]["meta"]["retagLayerModes"],
            {"identity": "preserve", "hair": "drop"},
        )
        self.assertEqual(
            loaded["nodes"][0]["meta"]["retagTagTranslations"],
            {"hatsune_miku": "初音未来", "aqua_hair": "水蓝色头发"},
        )
        self.assertEqual(loaded["nodes"][0]["meta"]["retagRatio"], "2:3")
        self.assertEqual(loaded["nodes"][0]["meta"]["tags"], "1girl, hatsune_miku, vocaloid")
        self.assertEqual(len(loaded["connections"]), 1)
        self.assertEqual(loaded["nodes"][1]["meta"]["width"], 832)
        self.assertEqual(
            loaded["nodes"][1]["meta"]["tagTranslations"],
            {"1girl": "1个女孩"},
        )
        self.assertEqual(loaded["nodes"][2]["width"], 420)
        self.assertEqual(loaded["nodes"][2]["height"], 800)

    def test_duplicate_node_id_is_rejected(self) -> None:
        node = {"id": "same", "type": "note"}
        with self.assertRaises(CanvasValidationError):
            self.store.sanitize_workspace({"nodes": [node, node], "connections": []})

    def test_workspace_keeps_node_model_and_count_bounds(self) -> None:
        sanitized = self.store.sanitize_workspace(
            {
                "nodes": [
                    {
                        "id": "prompt_1",
                        "type": "prompt",
                        "x": 0,
                        "y": 0,
                        "prompt": "1girl",
                        "model": "nai-diffusion-5-full",
                        "meta": {"count": 9, "cfgRescale": 0.4, "varietyBoost": True},
                    },
                    {
                        "id": "prompt_2",
                        "type": "prompt",
                        "x": 10,
                        "y": 10,
                        "prompt": "2girl",
                        "meta": {"count": 0},
                    },
                ],
                "connections": [],
            }
        )

        first = sanitized["nodes"][0]
        self.assertEqual(first["model"], "nai-diffusion-5-full")
        self.assertEqual(first["meta"]["count"], 4)
        self.assertEqual(first["meta"]["cfgRescale"], 0.4)
        self.assertTrue(first["meta"]["varietyBoost"])

        second = sanitized["nodes"][1]
        self.assertEqual(second["meta"]["count"], 1)
        self.assertFalse(second["meta"]["varietyBoost"])
        # 未设置的采样参数不得物化成 0，否则重载后滑条会显示"手写值 0"
        self.assertNotIn("steps", second["meta"])
        self.assertNotIn("scale", second["meta"])
        self.assertNotIn("cfgRescale", second["meta"])

    def test_workspace_keeps_ratio_manual_flag_for_prompt_nodes(self) -> None:
        # 首次链接图片的画幅自动对齐依赖这个标记记住"用户手动选过画幅"
        sanitized = self.store.sanitize_workspace(
            {
                "nodes": [
                    {
                        "id": "prompt_1",
                        "type": "prompt",
                        "x": 0,
                        "y": 0,
                        "prompt": "1girl",
                        "meta": {"ratioManual": True},
                    },
                    {
                        "id": "prompt_2",
                        "type": "prompt",
                        "x": 10,
                        "y": 10,
                        "prompt": "2girl",
                        "meta": {},
                    },
                ],
                "connections": [],
            }
        )

        self.assertTrue(sanitized["nodes"][0]["meta"]["ratioManual"])
        self.assertFalse(sanitized["nodes"][1]["meta"]["ratioManual"])

    def test_workspace_keeps_sanitized_char_prompt_entries(self) -> None:
        sanitized = self.store.sanitize_workspace(
            {
                "nodes": [
                    {
                        "id": "prompt_1",
                        "type": "prompt",
                        "x": 0,
                        "y": 0,
                        "prompt": "1girl",
                        "meta": {
                            "retagCharPrompts": [
                                {
                                    "prompt": "hatsune miku, twintails",
                                    "negative_prompt": "bad hands",
                                    "position": "B3",
                                },
                                {"prompt": ""},
                                "junk",
                            ],
                            "retagUseCoords": True,
                            "retagSteps": 28,
                            "retagScale": 5.1,
                            "retagCfgRescale": 0.34,
                            "retagNoiseSchedule": "karras",
                        },
                    }
                ],
                "connections": [],
            }
        )

        meta = sanitized["nodes"][0]["meta"]
        self.assertEqual(
            meta["retagCharPrompts"],
            [
                {
                    "prompt": "hatsune miku, twintails",
                    "negative_prompt": "bad hands",
                    "position": "B3",
                }
            ],
        )
        self.assertTrue(meta["retagUseCoords"])
        # 沿用原图采样参数的缓存字段也要能过清洗器
        self.assertEqual(meta["retagSteps"], 28)
        self.assertEqual(meta["retagScale"], 5.1)
        self.assertEqual(meta["retagCfgRescale"], 0.34)
        self.assertEqual(meta["retagNoiseSchedule"], "karras")

    def test_workspace_clamps_out_of_range_source_sampling_params(self) -> None:
        sanitized = self.store.sanitize_workspace(
            {
                "nodes": [
                    {
                        "id": "prompt_1",
                        "type": "prompt",
                        "x": 0,
                        "y": 0,
                        "prompt": "1girl",
                        "meta": {
                            "retagSteps": 9999,
                            "retagScale": -5,
                            "retagCfgRescale": "not-a-number",
                            "retagNoiseSchedule": "x" * 99,
                        },
                    }
                ],
                "connections": [],
            }
        )

        meta = sanitized["nodes"][0]["meta"]
        self.assertEqual(meta["retagSteps"], 200)
        self.assertEqual(meta["retagScale"], 0)
        self.assertEqual(meta["retagCfgRescale"], 0)
        self.assertLessEqual(len(meta["retagNoiseSchedule"]), 32)

    def test_workspace_drops_malformed_seed_values_instead_of_clamping_them(self) -> None:
        workspace = self.store.sanitize_workspace(
            {
                "nodes": [
                    {
                        "id": "seed_bad",
                        "type": "image",
                        "meta": {"seed": 1.5, "retagSeed": 4_294_967_296},
                    }
                ],
                "connections": [],
            }
        )
        self.assertEqual(workspace["nodes"][0]["meta"]["seed"], 0)
        self.assertEqual(workspace["nodes"][0]["meta"]["retagSeed"], 0)

    def test_retag_layer_state_is_whitelisted_and_bounded(self) -> None:
        tags = [f"tag_{index}" for index in range(80)]
        workspace = self.store.sanitize_workspace(
            {
                "nodes": [
                    {
                        "id": "prompt_layers",
                        "type": "prompt",
                        "meta": {
                            "retagLayerExpanded": True,
                            "retagTagGroups": {
                                "hair": [*tags, "x" * 500],
                                "clothing": ["tag_0", "white_dress"],
                                "not_allowed": ["must_drop"],
                            },
                            "retagLayerModes": {
                                "hair": "PRESERVE",
                                "clothing": "drop",
                                "pose": "invalid",
                                "not_allowed": "drop",
                            },
                            "retagTagTranslations": {
                                **{f"tag {index}": f"标签 {index}" for index in range(400)},
                                "x" * 500: "y" * 500,
                            },
                        },
                    }
                ],
                "connections": [],
            }
        )
        meta = workspace["nodes"][0]["meta"]

        self.assertTrue(meta["retagLayerExpanded"])
        self.assertEqual(len(meta["retagTagGroups"]["hair"]), 64)
        self.assertNotIn("not_allowed", meta["retagTagGroups"])
        self.assertEqual(meta["retagTagGroups"]["clothing"], ["white_dress"])
        self.assertEqual(
            meta["retagLayerModes"],
            {"hair": "preserve", "clothing": "drop"},
        )
        self.assertEqual(len(meta["retagTagTranslations"]), 320)
        self.assertEqual(meta["retagTagTranslations"]["tag_0"], "标签 0")

    def test_debug_trace_survives_round_trip_and_is_bounded(self) -> None:
        long_value = "x" * 5000
        payload = {
            "nodes": [
                {
                    "id": "prompt_debug",
                    "type": "prompt",
                    "meta": {
                        "debug": {
                            "scope": "canvas.generate",
                            "totalMs": 123,
                            "stages": [
                                {"name": "翻译", "ms": 40, "error": long_value},
                                {"name": "生成", "ms": 83},
                            ],
                            "notes": {"最终提示词": long_value, "nested": {"keep": True}},
                            "untrusted": "must be dropped",
                        },
                    },
                },
            ],
            "connections": [],
        }

        saved = self.store.save_workspace(payload)
        loaded = self.store.load_workspace()
        debug = loaded["nodes"][0]["meta"]["debug"]

        self.assertEqual(debug["scope"], "canvas.generate")
        self.assertEqual(debug["totalMs"], 123)
        self.assertEqual(debug["stages"][1]["name"], "生成")
        self.assertLessEqual(len(debug["stages"][0]["error"]), 2000)
        self.assertLessEqual(len(debug["notes"]["最终提示词"]), 2000)
        self.assertEqual(debug["notes"]["nested"], {"keep": True})
        self.assertNotIn("untrusted", debug)
        self.assertEqual(saved["nodes"][0]["meta"]["debug"], debug)

    def test_named_debug_runs_survive_round_trip(self) -> None:
        """画布同时保存反推和生图流水时，不能把嵌套结构误当成单条流水。"""
        payload = {
            "nodes": [
                {
                    "id": "prompt_debug_runs",
                    "type": "prompt",
                    "meta": {
                        "debug": {
                            "retag": {
                                "scope": "canvas.retag",
                                "totalMs": 31,
                                "stages": [{"name": "反推", "ms": 31}],
                                "notes": {"反推 tags": "1girl, blue_hair"},
                            },
                            "generate": {
                                "scope": "canvas.generate",
                                "totalMs": 82,
                                "stages": [{"name": "生图", "ms": 82}],
                                "notes": {"最终提示词": "1girl, blue_hair"},
                            },
                            "unsafe key": {"scope": "should be ignored"},
                        },
                    },
                }
            ],
            "connections": [],
        }

        loaded = self.store.save_workspace(payload)
        debug = loaded["nodes"][0]["meta"]["debug"]

        self.assertEqual(set(debug), {"retag", "generate"})
        self.assertEqual(debug["retag"]["scope"], "canvas.retag")
        self.assertEqual(debug["generate"]["stages"][0]["name"], "生图")

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
            {
                "lastCanvasId": first["id"],
                "ratio": "3:2",
                "artist": "watercolor",
                "model": "nai-diffusion-5-full",
                "advSteps": 24,
                "advScale": 5.5,
                "advCfgRescale": 0.2,
                "advVariety": True,
            }
        )

        reopened = CanvasStore("test_plugin", Path(self.temp_dir.name))
        self.assertEqual(reopened.load_preferences(), saved)
        self.assertEqual(saved["lastCanvasId"], first["id"])
        self.assertEqual(saved["ratio"], "3:2")
        self.assertEqual(saved["artist"], "watercolor")
        # 模型与高级参数跟随默认值同样持久化
        self.assertEqual(saved["model"], "nai-diffusion-5-full")
        self.assertEqual(saved["advSteps"], 24)
        self.assertEqual(saved["advScale"], 5.5)
        self.assertEqual(saved["advCfgRescale"], 0.2)
        self.assertTrue(saved["advVariety"])

        reopened.trash_canvas(first["id"])
        self.assertEqual(reopened.load_preferences()["lastCanvasId"], "")
        self.assertEqual(reopened.load_preferences()["ratio"], "3:2")
        self.assertEqual(reopened.load_preferences()["artist"], "watercolor")
        self.assertEqual(reopened.load_preferences()["model"], "nai-diffusion-5-full")

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
            tag_translations={"blue sky": "蓝天", "clouds": "云"},
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
        self.assertEqual(
            library["images"][0]["tagTranslations"],
            {"blue_sky": "蓝天", "clouds": "云"},
        )
        # Re-saving the same asset without metadata must not erase the seed
        # that was already collected from the NovelAI image.
        self.store.add_image_to_library(image, "再次收录", "generated", seed=0)
        self.assertEqual(self.store.list_library()["images"][0]["seed"], 987654321)
        self.store.add_image_to_library(image, "", "", "", "", "", "", seed=0)
        preserved = self.store.list_library()["images"][0]
        self.assertEqual(preserved["prompt"], "蓝色天空")
        self.assertEqual(preserved["tags"], "blue sky, clouds")
        self.assertEqual(preserved["ratio"], "3:2")
        self.assertEqual(preserved["artist"], "里番")
        self.assertEqual(
            preserved["tagTranslations"],
            {"blue_sky": "蓝天", "clouds": "云"},
        )
        self.assertEqual(library["prompts"][0]["prompt"], "1girl, backlight")

        self.store.remove_image_from_library(image["id"])
        self.store.delete_prompt_asset(prompt["id"])
        self.assertEqual(self.store.list_library(), {"images": [], "prompts": []})

    def _store_png_asset(self, nai_comment: dict | None = None) -> dict:
        """存一张 PNG；传入 nai_comment 时附带 NovelAI 风格的 tEXt 元数据。"""
        buffer = BytesIO()
        image = Image.new("RGB", (48, 32), (90, 120, 200))
        if nai_comment is None:
            image.save(buffer, format="PNG")
        else:
            info = PngInfo()
            info.add_text("Software", "NovelAI 4.5")
            info.add_text("Description", "1girl, blue hair")
            info.add_text("Comment", json.dumps(nai_comment))
            image.save(buffer, format="PNG", pnginfo=info)
        return self.store.store_asset(buffer.getvalue())

    def test_repair_library_image_seed_backfills_from_nai_metadata(self) -> None:
        # 旧版本收录的条目没有 seed，放入画布时应能从图片元数据补回
        asset = self._store_png_asset({"seed": 3405988762, "steps": 28, "scale": 7.0})
        self.store.add_image_to_library(asset, "旧素材", "generated")

        entry = self.store.repair_library_image_seed(asset["id"])

        self.assertEqual(entry["seed"], 3405988762)
        self.assertEqual(self.store.list_library()["images"][0]["seed"], 3405988762)

    def test_repair_library_image_seed_keeps_existing_seed_and_plain_images(self) -> None:
        seeded_asset = self._store_png_asset({"seed": 111})
        self.store.add_image_to_library(seeded_asset, "有种子", "generated", seed=222)
        self.assertEqual(
            self.store.repair_library_image_seed(seeded_asset["id"])["seed"], 222
        )

        plain_asset = self._store_png_asset()
        self.store.add_image_to_library(plain_asset, "重编码图", "generated")
        entry = self.store.repair_library_image_seed(plain_asset["id"])
        self.assertEqual(entry["seed"], 0)

    def test_repair_library_image_seed_rejects_unknown_or_invalid_ids(self) -> None:
        asset = self._store_png_asset({"seed": 5})
        with self.assertRaises(CanvasValidationError):
            self.store.repair_library_image_seed("not-an-id")
        with self.assertRaises(CanvasValidationError):
            self.store.repair_library_image_seed(asset["id"])

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
                "/test_plugin/canvas/tags/translate",
                ("POST",),
                "Infinite Canvas：读取中英文 Tags",
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
        self.assertIn(
            (
                "/test_plugin/canvas/library/image/recover",
                ("POST",),
                "Infinite Canvas：回填图片种子",
            ),
            routes,
        )


class CanvasTagTranslationEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_tag_translation_callback_returns_ordered_pairs(self) -> None:
        seen = {}

        async def translate(tags):
            seen["tags"] = tags
            return {
                "pairs": [
                    {"tag": "blue_hair", "cnName": "蓝发"},
                    {"tag": "school_uniform", "cnName": "校服"},
                ],
                "translations": {
                    "blue_hair": "蓝发",
                    "school uniform": "校服",
                },
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            service = CanvasService(
                "test_plugin",
                generate_callback=lambda _payload: None,
                config_callback=lambda: {},
                tag_translation_callback=translate,
                data_dir=Path(temp_dir),
            )
            old_request = canvas_module.request
            old_json_response = canvas_module.json_response
            old_error_response = canvas_module.error_response

            class FakeRequest:
                async def json(self, default=None):
                    return {"tags": "blue_hair, school_uniform"}

            canvas_module.request = FakeRequest()
            canvas_module.json_response = lambda value: value
            canvas_module.error_response = lambda message, status_code=500: {
                "error": message,
                "status": status_code,
            }
            try:
                result = await service.translate_tags()
            finally:
                canvas_module.request = old_request
                canvas_module.json_response = old_json_response
                canvas_module.error_response = old_error_response

        self.assertEqual(seen["tags"], "blue_hair, school_uniform")
        self.assertEqual(result["pairs"][0], {"tag": "blue_hair", "cnName": "蓝发"})
        self.assertEqual(
            result["translations"],
            {"blue_hair": "蓝发", "school_uniform": "校服"},
        )


class CanvasRetagEndpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.service = CanvasService(
            "test_plugin",
            generate_callback=lambda _payload: None,
            config_callback=lambda: {},
            data_dir=Path(self.temp_dir.name),
        )
        buffer = BytesIO()
        Image.new("RGB", (16, 16), (40, 80, 120)).save(buffer, format="PNG")
        self.asset = self.service.store.store_asset(buffer.getvalue())

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _invoke(self, callback, payload):
        old_request = canvas_module.request
        old_json_response = canvas_module.json_response
        old_error_response = canvas_module.error_response

        class FakeRequest:
            async def json(self, default=None):
                return payload

        canvas_module.request = FakeRequest()
        canvas_module.json_response = lambda value: value
        canvas_module.error_response = lambda message, status_code=500: {
            "error": message,
            "status": status_code,
        }
        self.service.retag_callback = callback
        try:
            return await self.service.retag()
        finally:
            canvas_module.request = old_request
            canvas_module.json_response = old_json_response
            canvas_module.error_response = old_error_response

    async def test_current_callback_receives_cached_seed_and_prompt(self) -> None:
        seen = {}

        async def callback(path, hint, debug, seed, source_prompt):
            seen.update(
                path=path,
                hint=hint,
                debug=debug,
                seed=seed,
                source_prompt=source_prompt,
            )
            return {"prompt": "1girl, blue hair", "seed": seed}

        result = await self._invoke(
            callback,
            {
                "assetId": self.asset["id"],
                "debug": True,
                "seed": 4_294_967_295,
                "sourcePrompt": "1girl, blue hair",
            },
        )

        self.assertEqual(seen["seed"], 4_294_967_295)
        self.assertEqual(seen["source_prompt"], "1girl, blue hair")
        self.assertTrue(seen["debug"])
        self.assertEqual(result["seed"], 4_294_967_295)

    async def test_legacy_identity_callback_keeps_old_signature(self) -> None:
        seen = {}

        async def callback(path, hint, keep_character, character_name):
            seen.update(
                path=path,
                hint=hint,
                keep_character=keep_character,
                character_name=character_name,
            )
            return {"prompt": "1girl"}

        result = await self._invoke(
            callback,
            {"assetId": self.asset["id"], "seed": 123, "sourcePrompt": "cached"},
        )

        self.assertEqual(result["prompt"], "1girl")
        self.assertFalse(seen["keep_character"])
        self.assertEqual(seen["character_name"], "")


if __name__ == "__main__":
    unittest.main()

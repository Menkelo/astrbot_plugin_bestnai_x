from __future__ import annotations

import asyncio
import json
import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from astrbot_plugin_bestnai_x.core.api_errors import mask_secrets
from astrbot_plugin_bestnai_x.core.debug_trace import DebugTrace

ROOT = Path(__file__).resolve().parents[1]


class MaskSecretsTest(unittest.TestCase):
    """报错原文和调试流水都会进日志，Key 不能跟着一起进去。"""

    def test_key_in_url_query_is_masked(self) -> None:
        # Gemini 就是这么传 key 的，aiohttp 的异常消息常常带着整条 URL
        masked = mask_secrets(
            "Cannot connect to https://api.example.com/v1beta/models?key=AIzaSyD-abcdefg123"
        )

        self.assertNotIn("AIzaSyD-abcdefg123", masked)
        self.assertIn("key=***", masked)

    def test_bearer_and_bare_key_are_masked(self) -> None:
        masked = mask_secrets("Authorization: Bearer sk-proj-abcdefghijklmn 失败")

        self.assertNotIn("abcdefghijklmn", masked)

    def test_json_api_key_field_is_masked(self) -> None:
        masked = mask_secrets('{"api_key": "abcd1234efgh5678", "model": "gpt-4o"}')

        self.assertNotIn("abcd1234efgh5678", masked)
        self.assertIn("gpt-4o", masked)

    def test_ordinary_text_survives(self) -> None:
        text = "提示词翻译失败：内容没通过服务商的审核"

        self.assertEqual(mask_secrets(text), text)


class DebugTraceTest(unittest.TestCase):
    """关着开关时必须彻底不出声，开着时该记的一样不少。"""

    def test_disabled_trace_produces_nothing(self) -> None:
        trace = DebugTrace("canvas.generate", False)
        with trace.stage("翻译"):
            pass
        trace.note("最终提示词", "1girl")

        self.assertIsNone(trace.payload())
        self.assertEqual(trace.log_text(), "")

    def test_stages_and_notes_are_recorded(self) -> None:
        trace = DebugTrace("canvas.generate", True)
        with trace.stage("翻译"):
            pass
        trace.note("最终提示词", "1girl, solo")
        trace.note("生图请求参数", {"steps": 28, "scale": 7.0})

        payload = trace.payload()

        self.assertEqual(payload["scope"], "canvas.generate")
        self.assertEqual([stage["name"] for stage in payload["stages"]], ["翻译"])
        self.assertIsInstance(payload["stages"][0]["ms"], int)
        self.assertGreaterEqual(payload["totalMs"], 0)
        self.assertEqual(payload["notes"]["最终提示词"], "1girl, solo")
        # 数字留成数字，前端好排版
        self.assertEqual(payload["notes"]["生图请求参数"]["steps"], 28)

    def test_failed_stage_is_recorded_and_reraised(self) -> None:
        trace = DebugTrace("canvas.retag", True)

        with self.assertRaises(RuntimeError):
            with trace.stage("反推"):
                raise RuntimeError("boom")

        stage = trace.payload()["stages"][0]

        self.assertEqual(stage["name"], "反推")
        self.assertIn("RuntimeError: boom", stage["error"])

    def test_stage_error_is_masked(self) -> None:
        trace = DebugTrace("canvas.retag", True)

        with self.assertRaises(RuntimeError):
            with trace.stage("反推"):
                raise RuntimeError("GET https://x.test/v1?key=AIzaSyD-abcdefg123 失败")

        self.assertNotIn("AIzaSyD-abcdefg123", trace.payload()["stages"][0]["error"])

    def test_notes_are_masked_and_clipped(self) -> None:
        trace = DebugTrace("canvas.generate", True)
        trace.note("上游报错", "api_key: abcd1234efgh5678")
        trace.note("最终提示词", "x" * 5000)

        notes = trace.payload()["notes"]

        self.assertNotIn("abcd1234efgh5678", notes["上游报错"])
        self.assertLess(len(notes["最终提示词"]), 2200)
        self.assertIn("共 5000 字", notes["最终提示词"])

    def test_nested_lists_remain_structured_for_debug_ui(self) -> None:
        trace = DebugTrace("canvas.generate", True)
        trace.note(
            "提示词冲突处理",
            {
                "added": ["izumi_sagiri", "white_dress"],
                "conflicts": {"identity": ["kasugano_sora"]},
            },
        )

        details = trace.payload()["notes"]["提示词冲突处理"]

        self.assertEqual(details["added"], ["izumi_sagiri", "white_dress"])
        self.assertEqual(details["conflicts"]["identity"], ["kasugano_sora"])

    def test_timed_awaits_and_records(self) -> None:
        trace = DebugTrace("canvas.retag", True)

        async def work() -> str:
            await asyncio.sleep(0)
            return "tags"

        result = asyncio.run(trace.timed("反推", work()))

        self.assertEqual(result, "tags")
        self.assertEqual(trace.payload()["stages"][0]["name"], "反推")

    def test_payload_is_json_serialisable(self) -> None:
        # 要原样塞进接口返回体，序列化不了就白记了
        trace = DebugTrace("canvas.generate", True)
        with trace.stage("生图"):
            pass
        trace.note("生图请求参数", {"steps": 28, "raw": False, "seed": None})

        json.dumps(trace.payload())

    def test_log_text_covers_stages_and_notes(self) -> None:
        trace = DebugTrace("canvas.generate", True)
        with trace.stage("翻译"):
            pass
        trace.note("最终提示词", "1girl")

        text = trace.log_text()

        self.assertIn("canvas.generate", text)
        self.assertIn("翻译", text)
        self.assertIn("最终提示词: 1girl", text)


class DebugModeWiringTest(unittest.TestCase):
    """开关要一路通到画布接口和前端面板，缺一环就等于没有。"""

    def setUp(self) -> None:
        self.schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        self.config = (ROOT / "models" / "config.py").read_text(encoding="utf-8")
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.editor = (ROOT / "pages" / "canvas" / "canvas.js").read_text(encoding="utf-8")
        self.styles = (ROOT / "pages" / "canvas" / "canvas.css").read_text(encoding="utf-8")

    def test_switch_is_canvas_only(self) -> None:
        self.assertNotIn("debug_mode", self.schema)
        self.assertNotIn("debug_mode", self.config)
        self.assertIn('localStorage.getItem("bestnaiCanvasDebug")', self.editor)

    def test_canvas_config_does_not_expose_a_global_switch(self) -> None:
        self.assertNotIn('"debugMode"', self.main)
        self.assertNotIn("debugMode: false", self.editor)
        self.assertIn('state.debugEnabled = savedDebug === "1";', self.editor)

    def test_both_canvas_paths_record_a_trace(self) -> None:
        self.assertIn('DebugTrace("canvas.generate"', self.main)
        self.assertIn('DebugTrace("canvas.retag"', self.main)
        # 生图和翻译的耗时是排查"为什么这么慢"的第一手材料
        self.assertIn('trace.stage("生图")', self.main)
        self.assertIn('trace.stage("翻译")', self.main)
        self.assertIn('trace.note("最终提示词", final_prompt)', self.main)
        self.assertIn('trace.note(\n            "生图请求参数"', self.main)

    def test_concurrent_retag_branches_are_timed_separately(self) -> None:
        # 反推和翻译是并发跑的，两边各自的耗时才看得出是谁拖慢了整体
        start = self.main.index("async def _canvas_retag")
        end = self.main.index("except ImageRetagError", start)
        block = self.main[start:end]

        self.assertIn("trace.timed(", block)
        self.assertIn('"反推"', block)
        self.assertNotIn("_translate_canvas_hint(user_hint)", block)
        self.assertIn("debug=debug", block)

    def test_trace_goes_to_both_the_response_and_the_log(self) -> None:
        start = self.main.index("def _with_debug")
        end = self.main.index("async def _canvas_retag")
        with_debug = self.main[start:end]

        self.assertIn("logger.info(trace.log_text())", with_debug)
        self.assertIn('result["debug"] = debug', with_debug)
        # 关着开关时返回体一个字段都不能多
        self.assertIn("if debug is None:\n            return result", with_debug)

    def test_frontend_keeps_the_recorder_visible_and_gates_only_details(self) -> None:
        self.assertIn("function makeDebugPanel(node)", self.editor)
        self.assertIn("if (!debugModeEnabled() || !runs.length) return null;", self.editor)
        self.assertIn('recordRunDebug(node, "generate", lastDebug)', self.editor)
        self.assertIn('recordRunDebug(node, "retag", result.debug)', self.editor)
        self.assertIn(".debug-bar {", self.styles)
        self.assertIn("els.debugBar.hidden = false;", self.editor)
        self.assertIn("const OPERATION_LOG_KEY", self.editor)
        self.assertIn("persistOperationLog()", self.editor)
        self.assertIn("if (debugModeEnabled())", self.editor)
        self.assertNotIn(".prompt-debug {", self.styles)

    def test_bottom_bar_has_one_working_disclosure_layer(self) -> None:
        render = self.editor.split("function renderDebugBar() {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn("const panel = makeDebugPanel(node);", render)
        self.assertNotIn("panel.open", render)
        self.assertNotIn("debug-bar-details", self.styles)
        self.assertIn("max-height: min(420px, 48vh);", self.styles)

    def test_frontend_accepts_legacy_flat_debug_trace(self) -> None:
        runs = self.editor.split("function debugRunsForNode(node)", 1)[1].split(
            "\nfunction ", 1
        )[0]

        self.assertIn("const legacyRun = node.meta?.debug;", runs)
        self.assertIn('includes("retag") ? "反推" : "生图"', runs)

    def test_editing_inputs_clears_the_visible_stale_trace(self) -> None:
        clear = self.editor.split("function clearDebugTrace(node)", 1)[1].split(
            "\nfunction ", 1
        )[0]

        self.assertIn("renderDebugBar();", clear)
        self.assertIn("debug: _debug", self.editor.split("function clearRetagCache", 1)[1].split(
            "\nfunction ", 1
        )[0])
        render = self.editor.split("function renderDebugBar()", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn('selectedNode?.type === "prompt"', render)
        self.assertIn("操作记录 · ${latestText}", render)


if __name__ == "__main__":
    unittest.main()

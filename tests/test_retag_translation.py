from __future__ import annotations

import ast
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

ROOT = Path(__file__).resolve().parents[1]


class RetagCommandDisplayTest(unittest.IsolatedAsyncioTestCase):
    """Run the real command handler with external providers replaced by fixtures."""

    async def run_command(self, text, source_tags, translated=None, show_result=True):
        from astrbot_plugin_bestnai_x.core.char_prompts import normalize_char_entries
        from astrbot_plugin_bestnai_x.constants import normalize_nai_seed
        from astrbot_plugin_bestnai_x.services.prompt_merge import merge_retag_prompt_details

        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        handler = next(node for node in ast.walk(tree) if isinstance(node, ast.AsyncFunctionDef) and node.name == "_handle_nai_command")
        module = ast.Module(body=[handler], type_ignores=[])
        namespace = {
            "extract_retag_mode": lambda value: ("replicate", value),
            "extract_image_from_event_best_effort": lambda event: "fixture.png",
            "read_image_generation_info_any": AsyncMock(return_value={}),
            "read_image_size_any": AsyncMock(return_value=(960, 640)),
            "infer_ratio_label_from_size": lambda *args: "3:2",
            "normalize_nai_seed": normalize_nai_seed,
            "normalize_char_entries": normalize_char_entries,
            "strip_control_tags": lambda value, **kwargs: value,
            "is_trusted_nai_generation_info": lambda value: False,
            "prompt_has_explicit_ratio": lambda *args: False,
            "merge_retag_prompt_details": merge_retag_prompt_details,
            "has_chinese": lambda value: any("\u4e00" <= char <= "\u9fff" for char in value),
            "logger": logging.getLogger("test.retag_display"),
            "ImageRetagError": RuntimeError,
        }
        exec(compile(module, str(ROOT / "main.py"), "exec"), namespace)
        captured = {}

        async def generate(**kwargs):
            captured.update(kwargs)
            yield "generated"

        plugin = types.SimpleNamespace(
            plugin_config=types.SimpleNamespace(
                generation=types.SimpleNamespace(model="fixture-model"),
                image_retag=types.SimpleNamespace(enabled=True, show_result=show_result, is_configured=lambda: True),
                translator=types.SimpleNamespace(enabled=True, show_result=True, is_configured=lambda: True),
                is_configured=lambda: True, get_retag_control_prompts=lambda: [],
            ),
            image_retagger=types.SimpleNamespace(retag_details=AsyncMock(return_value={"prompt": source_tags})),
            _strip_named_command_prefix=lambda *args: text,
            _short_ratio_aliases=lambda: {}, ratio_presets={}, _normalize_ratio_label=lambda value: value,
            _progress_message_for_prompt=lambda *args, **kwargs: "working",
            _session_id=lambda event: "test", _extract_ratio_from_prompt=lambda value: (value, ""),
            _extract_artist_slot_from_prompt=lambda value: (value, "", ""),
            _resolve_prompt_identity=AsyncMock(return_value=("", "")),
            _translate_prompt=AsyncMock(return_value=translated), _do_generate=generate,
        )
        event = types.SimpleNamespace(message_str="/nai " + text, plain_result=lambda value: value)
        results = [result async for result in namespace["_handle_nai_command"](plugin, event, command_name="nai")]
        self.assertEqual(results, ["working", "generated"])
        return captured

    async def test_english_overlay_is_separated_in_both_display_and_generation(self):
        for source in ("1girl, outdoors", "1girl, outdoors,", "1girl, outdoors， "):
            with self.subTest(source=source):
                result = await self.run_command(" , smile, blue hair, ", source)
                self.assertEqual(result["followup_messages"], ["🔎 反推结果：\n1girl, outdoors, smile, blue hair"])
                self.assertIn("smile", result["prompt"])
                self.assertIn("blue hair", result["prompt"])
                self.assertNotIn("outdoorssmile", result["prompt"])

    async def test_translated_overlay_uses_the_same_separator(self):
        result = await self.run_command("微笑", "1girl, outdoors,", translated="smile, blue hair,")
        self.assertEqual(result["followup_messages"], ["🔎 反推结果：\n1girl, outdoors, smile, blue hair"])

    async def test_hidden_retag_result_does_not_add_a_display_message(self):
        result = await self.run_command("smile", "1girl, outdoors", show_result=False)
        self.assertEqual(result["followup_messages"], [])


class RetagTranslationTest(unittest.TestCase):
    """反推只提取图片 tags，手写提示词在生图阶段单独翻译。"""

    def setUp(self) -> None:
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")
        # 切出这两个方法之间的代码，任一被删掉都会在这里直接报错
        start = self.main.index("async def _canvas_retag")
        end = self.main.index("async def _translate_canvas_hint")
        self.retag = self.main[start:end]

    def test_canvas_retag_does_not_send_hint_to_vision_model(self) -> None:
        self.assertIn("self.image_retagger.retag_details(image_path, debug=debug)", self.retag)
        self.assertNotIn("user_hint=user_hint", self.retag)
        self.assertNotIn("apply_prompt_weight(user_hint)", self.retag)

    def test_metadata_branch_does_not_translate(self) -> None:
        # Embedded NAI prompts do not need a second translation request.
        start = self.retag.index("if source_prompt:")
        end = self.retag.index("if not retag_config.enabled:")
        metadata_branch = self.retag[start:end]

        self.assertNotIn("self._translate_canvas_hint(user_hint)", metadata_branch)

    def test_metadata_branch_resolves_source_identity_without_llm(self) -> None:
        start = self.retag.index("if source_prompt:")
        end = self.retag.index("if not retag_config.enabled:")
        metadata_branch = self.retag[start:end]

        self.assertIn("await self._canvas_source_tag_details(source_prompt)", metadata_branch)
        self.assertIn('"character": source_character', metadata_branch)
        self.assertIn('"series": source_series', metadata_branch)
        self.assertIn('"tagTranslations": tag_translations', metadata_branch)

    def test_retag_uses_one_tagging_request(self) -> None:
        self.assertNotIn("asyncio.gather(", self.retag)
        self.assertIn("self.image_retagger.retag_details(", self.retag)
        self.assertNotIn("self._translate_canvas_hint(user_hint)", self.retag)

    def test_cached_translation_is_recleaned_with_current_identity_candidates(self) -> None:
        generate_start = self.main.index("async def _canvas_generate")
        generate_end = self.main.index("@staticmethod\n    def _clamp_steps", generate_start)
        generate = self.main[generate_start:generate_end]

        self.assertIn("self._resolve_prompt_identity_details(clean_prompt)", generate)
        self.assertIn("if translation_cache_reused and translated_character:", generate)
        self.assertIn("translated_source = apply_character_candidate(", generate)
        self.assertIn(
            "part for part in (translated_source, untranslated_suffix)",
            generate,
        )

    def test_canvas_trace_marks_hint_as_generation_only(self) -> None:
        self.assertIn("手写提示词（不送反推）", self.retag)

    def test_canvas_retag_trace_does_not_require_removed_config_model_field(self) -> None:
        self.assertNotIn("retag_config.model", self.retag)
        self.assertNotIn('getattr(retag_config, "model", "")', self.retag)
        self.assertIn('"provider": retag_config.provider_id', self.retag)

    def test_qq_retag_has_metadata_seed_shortcut_before_vision_provider(self) -> None:
        command = self.main[self.main.index("async def _handle_nai_command"):]
        self.assertIn("read_image_generation_info_any(image_src)", command)
        self.assertIn("is_trusted_nai_generation_info(", command)
        self.assertIn("source_prompt = raw_source_prompt if metadata_retag else", command)
        self.assertIn(
            "if not metadata_retag and not self.plugin_config.image_retag.enabled:",
            command,
        )
        self.assertIn('"fromMetadata": True', command)
        self.assertIn("self._resolve_prompt_identity(\n                        source_prompt", command)
        self.assertIn("seed=source_seed if metadata_retag else None", command)

    def test_translation_failure_keeps_the_original_text(self) -> None:
        start = self.main.index("async def _translate_canvas_hint")
        end = self.main.index("def _ratio_from_generation_info")
        hint = self.main[start:end]

        self.assertIn("return hint", hint)
        self.assertIn("has_chinese(hint)", hint)


class FreeTierStepsCapTest(unittest.TestCase):
    """免费额度只在 ≤28 步时生效，超了就开始扣 Anlas。"""

    def setUp(self) -> None:
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")
        self.editor = (ROOT / "pages" / "canvas" / "canvas.js").read_text(encoding="utf-8")

    def test_backend_caps_at_28(self) -> None:
        self.assertIn("MAX_STEPS = 28", self.main)
        self.assertNotIn("MAX_STEPS = 50", self.main)

    def test_frontend_steps_follow_priority_chain(self) -> None:
        self.assertNotIn("steps: { default: 28, min: 1, max: 28 }", self.editor)
        # 节点高级参数卡 > 反推命中的原图参数 > 插件默认（后端仍封顶 28）
        self.assertIn(
            "steps: node.meta?.steps || node.meta?.retagSteps || undefined",
            self.editor,
        )

    def test_frontend_advanced_params_use_sliders(self) -> None:
        # 高级参数卡（高级参数/滑条）已取代旧的"画布不提供参数调节"约定
        self.assertNotIn("function makeAdvancedPanel", self.editor)
        self.assertIn('slider.type = "range"', self.editor)
        # 步数滑条仍受后端 28 步上限约束
        self.assertIn('slider.max = String(max)', self.editor)


if __name__ == "__main__":
    unittest.main()

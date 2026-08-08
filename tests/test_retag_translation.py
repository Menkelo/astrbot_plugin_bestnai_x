from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

ROOT = Path(__file__).resolve().parents[1]


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
        start = self.retag.index("if source_seed is not None and source_prompt:")
        end = self.retag.index("if not retag_config.enabled:")
        metadata_branch = self.retag[start:end]

        self.assertNotIn("self._translate_canvas_hint(user_hint)", metadata_branch)

    def test_metadata_branch_resolves_source_identity_without_llm(self) -> None:
        start = self.retag.index("if source_seed is not None and source_prompt:")
        end = self.retag.index("if not retag_config.enabled:")
        metadata_branch = self.retag[start:end]

        self.assertIn("self._resolve_prompt_identity(source_prompt, timeout=3.0)", metadata_branch)
        self.assertIn('"character": source_character', metadata_branch)
        self.assertIn('"series": source_series', metadata_branch)

    def test_retag_uses_one_tagging_request(self) -> None:
        self.assertNotIn("asyncio.gather(", self.retag)
        self.assertIn("self.image_retagger.retag_details(", self.retag)
        self.assertNotIn("self._translate_canvas_hint(user_hint)", self.retag)

    def test_canvas_trace_marks_hint_as_generation_only(self) -> None:
        self.assertIn("手写提示词（不送反推）", self.retag)

    def test_canvas_retag_trace_does_not_require_removed_config_model_field(self) -> None:
        self.assertNotIn("retag_config.model", self.retag)
        self.assertIn('getattr(retag_config, "model", "")', self.retag)

    def test_qq_retag_has_metadata_seed_shortcut_before_vision_provider(self) -> None:
        command = self.main[self.main.index("async def _handle_nai_command"):]
        self.assertIn("read_image_generation_info_any(image_src)", command)
        self.assertIn("metadata_retag = source_seed is not None and bool(source_prompt)", command)
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

    def test_frontend_does_not_override_steps(self) -> None:
        self.assertNotIn("steps: { default: 28, min: 1, max: 28 }", self.editor)
        self.assertNotIn("steps: node.meta?.steps", self.editor)

    def test_frontend_has_no_generation_parameter_slider(self) -> None:
        self.assertNotIn("function makeAdvancedPanel", self.editor)
        self.assertNotIn('slider.type = "range"', self.editor)


if __name__ == "__main__":
    unittest.main()

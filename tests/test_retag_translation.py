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
    """反推附带的中文提示词必须在反推那一步就翻掉。

    留着中文拼进 prompt，生成阶段 has_chinese() 会命中，
    把「中文 hint + 几十个英文 tag」整串再翻一遍：白花一次调用，
    而且第二次的译文和第一次不一定一致。
    """

    def setUp(self) -> None:
        self.main = (ROOT / "main.py").read_text(encoding="utf-8")
        # 切出这两个方法之间的代码，任一被删掉都会在这里直接报错
        start = self.main.index("async def _canvas_retag")
        end = self.main.index("async def _translate_canvas_hint")
        self.retag = self.main[start:end]

    def test_canvas_retag_leaves_weighting_to_the_merge_step(self) -> None:
        self.assertIn("normalize_prompt_ascii(user_hint)", self.retag)
        self.assertNotIn("apply_prompt_weight(user_hint)", self.retag)

    def test_metadata_branch_does_not_translate(self) -> None:
        # Embedded NAI prompts do not need a second translation request.
        start = self.retag.index("if source_seed and source_prompt:")
        end = self.retag.index("if not retag_config.enabled:")
        metadata_branch = self.retag[start:end]

        self.assertNotIn("self._translate_canvas_hint(user_hint)", metadata_branch)

    def test_retag_uses_one_tagging_request(self) -> None:
        self.assertNotIn("asyncio.gather(", self.retag)
        self.assertIn("self.image_retagger.retag(", self.retag)
        self.assertNotIn("self._translate_canvas_hint(user_hint)", self.retag)

    def test_vision_model_still_receives_the_original_chinese(self) -> None:
        # 中文引导直接交给标签模型，避免重复翻译。
        self.assertIn("self.image_retagger.retag(image_path, user_hint=user_hint)", self.retag)

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

    def test_frontend_slider_caps_at_28(self) -> None:
        self.assertIn("steps: { default: 28, min: 1, max: 28 }", self.editor)
        self.assertNotIn("field.integer ? 50 : 10", self.editor)

    def test_frontend_clamps_values_from_image_metadata(self) -> None:
        # 反推复用的原图可能带 >28 步，不夹回区间的话读数显示 50、滑块停在 28
        self.assertIn("Math.min(max, Math.max(min, raw))", self.editor)


if __name__ == "__main__":
    unittest.main()

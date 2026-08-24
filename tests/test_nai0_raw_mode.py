from __future__ import annotations

import sys
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[1]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

MAIN_SOURCE = (workspace_dir / "main.py").read_text(encoding="utf-8")


class Nai0RawModeTranslationTest(unittest.TestCase):
    """中文提示词一律翻译（V5 与 4.5 同策略）；raw 只影响画师串与质量词。

    V5 对中文自然语言与角色别名的理解不稳定（"鸣潮爱弥斯"识别不到角色），
    曾经的"V5 直通 + 身份增强"方案已回退。
    """

    def test_main_generation_path_translates_chinese_for_all_models(self) -> None:
        self.assertIn("if has_chinese(clean_prompt):", MAIN_SOURCE)
        self.assertNotIn("V5 角色增强", MAIN_SOURCE)
        self.assertNotIn("model_supports_cjk(current_model)", MAIN_SOURCE)

    def test_raw_empty_after_translation_gives_actionable_hint(self) -> None:
        self.assertIn("中文提示词翻译结果为空", MAIN_SOURCE)

    def test_retag_merge_path_translates_chinese_desc(self) -> None:
        # raw 只影响画师串/质量词：反推合并的中文描述同样要翻译
        self.assertIn("if desc_part and has_chinese(desc_part):", MAIN_SOURCE)
        self.assertIn("if desc_part:", MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()

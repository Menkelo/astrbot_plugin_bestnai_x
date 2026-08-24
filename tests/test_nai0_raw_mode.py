from __future__ import annotations

import sys
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[1]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

MAIN_SOURCE = (workspace_dir / "main.py").read_text(encoding="utf-8")


class Nai0RawModeTranslationTest(unittest.TestCase):
    """nai0（原始提示词模式）不得触发翻译与身份检索。

    README 承诺 nai0「跳过翻译」，但两处翻译入口此前都没有判断
    raw_mode，导致 /nai0 中文输入仍然调用翻译器。
    """

    def test_main_generation_path_skips_translation_in_raw_mode(self) -> None:
        # raw 模式与 V5 中文直通都不进翻译
        self.assertIn(
            "if not raw_mode and not model_supports_cjk(current_model) and has_chinese(clean_prompt):",
            MAIN_SOURCE,
        )

    def test_retag_merge_path_skips_translation_and_identity_in_raw_mode(self) -> None:
        self.assertIn(
            "if desc_part and has_chinese(desc_part) and not raw_mode:",
            MAIN_SOURCE,
        )
        # 身份检索也不应在 raw 模式下对中文描述空跑
        self.assertIn("if desc_part and not raw_mode:", MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()

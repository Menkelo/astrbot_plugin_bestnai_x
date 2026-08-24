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

    def test_main_generation_path_translation_follows_model(self) -> None:
        # 翻译策略只看模型：4.5（含 /nai0）翻译；V5 中文直通
        self.assertIn(
            "elif not model_supports_cjk(current_model) and has_chinese(clean_prompt):",
            MAIN_SOURCE,
        )

    def test_v5_direct_pass_gets_danbooru_identity_enhancement(self) -> None:
        # V5 中文直通时做 Danbooru 身份检索，命中角色则追加英文 tag
        self.assertIn("V5 角色增强", MAIN_SOURCE)
        self.assertIn("await self._resolve_prompt_identity(", MAIN_SOURCE)

    def test_retag_merge_path_skips_translation_and_identity_in_raw_mode(self) -> None:
        self.assertIn(
            "if desc_part and has_chinese(desc_part) and not raw_mode:",
            MAIN_SOURCE,
        )
        # 身份检索也不应在 raw 模式下对中文描述空跑
        self.assertIn("if desc_part and not raw_mode:", MAIN_SOURCE)

    def test_raw_mode_cjk_uses_request_model_not_plugin_default(self) -> None:
        # 画布 raw 分支必须看本次请求的节点模型；看插件默认模型会让
        # V5 节点的中文被 ASCII 清理误删
        self.assertIn("model_supports_cjk(current_model)", MAIN_SOURCE)

    def test_empty_after_cleanup_gives_actionable_hint_for_raw_chinese(self) -> None:
        # 4.5 + raw + 中文清空后必须告诉用户出路，而不是"清理后为空"
        self.assertIn("原始提示词模式下 4.5 不支持中文", MAIN_SOURCE)
        self.assertIn("请把节点模型切换为 V5", MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()

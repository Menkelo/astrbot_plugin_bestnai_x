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

    def test_main_generation_path_skips_translation_for_raw_mode(self) -> None:
        self.assertIn("if has_chinese(clean_prompt) and not raw_mode:", MAIN_SOURCE)
        self.assertIn("final_prompt = clean_prompt", MAIN_SOURCE)
        self.assertNotIn("V5 角色增强", MAIN_SOURCE)
        self.assertNotIn("model_supports_cjk(current_model)", MAIN_SOURCE)

    def test_raw_commands_select_fixed_models(self) -> None:
        self.assertIn('@filter.command("nai0")', MAIN_SOURCE)
        self.assertIn('@filter.command("nai50")', MAIN_SOURCE)
        self.assertIn('command_name="nai50"', MAIN_SOURCE)

    def test_retag_merge_path_keeps_raw_overlay_literal(self) -> None:
        self.assertIn("if desc_part and has_chinese(desc_part) and not raw_mode:", MAIN_SOURCE)
        self.assertIn("Raw mode is literal", MAIN_SOURCE)


class NaiCommandPrefixTest(unittest.TestCase):
    """四个 nai 指令都必须按自己的名字剥前缀。

    剥前缀的正则是 ``nai(?:\\s+|$)``——``nai`` 后面必须是空格或结尾。
    ``/nai5`` 曾经漏传 ``command_name``，于是拿 "nai" 去剥
    "nai5 可爱 1girl"：正则匹配不上、原样返回，画师预设名匹配到的就成了
    "nai5"，临时画师串因此失效（``/nai`` 因为默认值恰好是 "nai" 所以正常）。
    """

    COMMANDS = ("nai", "nai5", "nai0", "nai50")

    def _handler_body(self, command: str) -> str:
        marker = f'@filter.command("{command}")'
        self.assertIn(marker, MAIN_SOURCE)
        body = MAIN_SOURCE.split(marker, 1)[1]
        return body.split("@filter.command", 1)[0]

    def test_every_command_passes_its_own_name(self) -> None:
        for command in self.COMMANDS:
            with self.subTest(command=command):
                self.assertIn(
                    f'command_name="{command}"',
                    self._handler_body(command),
                )

    def test_command_name_has_no_default_to_fall_back_on(self) -> None:
        # 这个 bug 的根因是「静默的错误默认值」。参数必填，漏传就直接 TypeError，
        # 而不是安静地按 "nai" 剥前缀。
        signature = MAIN_SOURCE.split("async def _handle_nai_command(", 1)[1]
        signature = signature.split(")", 1)[0]

        self.assertIn("command_name: str", signature)
        self.assertNotIn('command_name: str = ""', signature)
        self.assertNotIn('command_name = command_name or', MAIN_SOURCE)


if __name__ == "__main__":
    unittest.main()

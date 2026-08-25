from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

from astrbot_plugin_bestnai_x.core.api_errors import (
    describe_api_error,
    strip_error_subject,
)


class DescribeApiErrorTest(unittest.TestCase):
    """上游报错要换成用户能照着做的话，而不是原样甩出英文报文。"""

    def test_moderation_rejection_reads_as_moderation(self) -> None:
        raw = (
            'OpenAI 兼容翻译接口返回 400: {"error": {"message": "Your request was '
            'rejected as a result of our safety system.", "type": "invalid_request_error"}}'
        )
        message = describe_api_error(raw, "提示词翻译")

        self.assertIn("没通过服务商的审核", message)
        self.assertIn("提示词翻译失败", message)
        # 非调试模式不把原始报文倒给用户
        self.assertNotIn("invalid_request_error", message)

    def test_chinese_moderation_wording_also_matches(self) -> None:
        message = describe_api_error("请求内容涉嫌违规，已被拦截", "图片反推")

        self.assertIn("没通过服务商的审核", message)

    def test_cloudflare_origin_failure_is_localized(self) -> None:
        message = describe_api_error(
            "The origin web server returned an invalid or incomplete response to Cloudflare.",
            "生图",
        )

        self.assertIn("上游服务器暂时不可用", message)
        self.assertNotIn("origin web server", message)

    def test_auth_and_quota_have_their_own_advice(self) -> None:
        auth = describe_api_error("Incorrect API key provided: sk-***", "提示词翻译")
        quota = describe_api_error(
            '{"error": {"message": "You exceeded your current quota"}}',
            "提示词翻译",
        )

        self.assertIn("API Key", auth)
        self.assertIn("余额", quota)
        self.assertNotEqual(auth, quota)

    def test_unknown_error_keeps_the_raw_text(self) -> None:
        # 认不出原因时原文是唯一线索，藏起来只会更难查
        message = describe_api_error("open error", "提示词翻译")

        self.assertIn("open error", message)

    def test_empty_error_still_says_something(self) -> None:
        message = describe_api_error("   ", "图片反推")

        self.assertIn("图片反推失败", message)
        self.assertIn("没有返回错误信息", message)

    def test_repeated_subject_prefix_is_removed(self) -> None:
        self.assertEqual(
            strip_error_subject(
                "图片反推失败：图片反推失败：服务商额度不足",
                "图片反推",
            ),
            "服务商额度不足",
        )

    def test_debug_mode_appends_the_raw_report(self) -> None:
        raw = 'moderation_blocked: {"code": "data_inspection_failed"}'
        message = describe_api_error(raw, "提示词翻译", True)

        self.assertIn("没通过服务商的审核", message)
        self.assertIn("原始报错", message)
        self.assertIn("data_inspection_failed", message)

    def test_long_raw_text_is_clipped(self) -> None:
        message = describe_api_error("x" * 900, "提示词翻译")

        self.assertLess(len(message), 300)
        self.assertIn("…", message)


if __name__ == "__main__":
    unittest.main()

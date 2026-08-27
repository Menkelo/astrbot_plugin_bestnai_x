from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.core import tag_dict  # noqa: E402
from astrbot_plugin_bestnai_x.core.tag_dict import (  # noqa: E402
    canonical_tag,
    chinese_name,
    is_known_tag,
    normalize_key,
    tag_for_chinese,
)
from astrbot_plugin_bestnai_x.core.translator import (  # noqa: E402
    DanbooruTagRetriever,
    PromptTranslator,
    localize_prompt_tags,
)


class NormalizeKeyTest(unittest.TestCase):
    def test_spaces_and_case_fold_into_the_underscore_form(self) -> None:
        self.assertEqual(normalize_key("Silver Hair"), "silver_hair")
        self.assertEqual(normalize_key("  looking   at viewer "), "looking_at_viewer")
        self.assertEqual(normalize_key("1girl"), "1girl")

    def test_empty_input(self) -> None:
        self.assertEqual(normalize_key(""), "")
        self.assertEqual(normalize_key(None), "")


class TagDictLookupTest(unittest.TestCase):
    """跑真实词库（assets/danbooru.tsv），断言四种查询都通。"""

    def test_known_tag_is_recognized(self) -> None:
        self.assertTrue(is_known_tag("twintails"))
        self.assertTrue(is_known_tag("1girl"))

    def test_alias_normalizes_to_canonical_tag(self) -> None:
        self.assertEqual(canonical_tag("high_res"), "highres")
        self.assertEqual(canonical_tag("hires"), "highres")

    def test_canonical_tag_accepts_the_space_form(self) -> None:
        self.assertEqual(canonical_tag("looking at viewer"), "looking_at_viewer")

    def test_chinese_lookup_hits_the_tag(self) -> None:
        self.assertEqual(tag_for_chinese("双马尾"), "twintails")
        self.assertEqual(tag_for_chinese("猫耳"), "cat_ears")

    def test_chinese_name_of_a_tag(self) -> None:
        self.assertEqual(chinese_name("twintails"), "双马尾")

    def test_unknown_tag_reports_empty(self) -> None:
        self.assertEqual(canonical_tag("zzz_not_a_real_tag_xyz"), "")
        self.assertFalse(is_known_tag("zzz_not_a_real_tag_xyz"))
        self.assertEqual(tag_for_chinese("这不是一个标签"), "")


class MissingAssetTest(unittest.TestCase):
    """词库读不到时必须整体降级，不能把生图拖下水。"""

    def setUp(self) -> None:
        self._asset = tag_dict.ASSET_PATH
        self._tables = tag_dict._tables
        tag_dict.ASSET_PATH = Path("no", "such", "danbooru.tsv")
        tag_dict._tables = None

    def tearDown(self) -> None:
        tag_dict.ASSET_PATH = self._asset
        tag_dict._tables = self._tables

    def test_lookups_degrade_to_empty(self) -> None:
        self.assertEqual(canonical_tag("twintails"), "")
        self.assertEqual(tag_for_chinese("双马尾"), "")
        self.assertEqual(chinese_name("twintails"), "")

    def test_nothing_is_reported_as_hallucinated(self) -> None:
        # 查不到词库时把所有 tag 判成幻觉，比不校验更糟
        self.assertTrue(is_known_tag("twintails"))
        self.assertTrue(is_known_tag("zzz_not_a_real_tag_xyz"))

    def test_prompt_passes_through_untouched(self) -> None:
        prompt = "1girl, high_res, solo"
        self.assertEqual(localize_prompt_tags(prompt), prompt)


class LocalizePromptTagsTest(unittest.TestCase):
    def test_alias_is_normalized(self) -> None:
        self.assertEqual(
            localize_prompt_tags("1girl, high_res, solo"), "1girl, highres, solo"
        )

    def test_space_form_is_preserved(self) -> None:
        # `looking at viewer` 与 `looking_at_viewer` 是同一个 tag 的两种写法，
        # 不该被全局下划线化
        self.assertEqual(
            localize_prompt_tags("1girl, looking at viewer"),
            "1girl, looking at viewer",
        )

    def test_unknown_tags_are_kept(self) -> None:
        # 只记日志不删词：本地表不含最新 tag，删了会误伤
        result = localize_prompt_tags("1girl, zzz_not_a_real_tag_xyz, solo")
        self.assertIn("zzz_not_a_real_tag_xyz", result)

    def test_weight_syntax_is_not_touched(self) -> None:
        for prompt in ("{high_res}", "1.2::high_res::", "[high_res]"):
            with self.subTest(prompt=prompt):
                self.assertEqual(localize_prompt_tags(prompt), prompt)

    def test_sentences_are_left_alone(self) -> None:
        sentence = "the umbrella belongs only to the girl in the red coat"
        self.assertEqual(localize_prompt_tags(f"1girl, {sentence}"), f"1girl, {sentence}")

    def test_empty_prompt(self) -> None:
        self.assertEqual(localize_prompt_tags(""), "")


class ChineseDirectHitTest(unittest.IsolatedAsyncioTestCase):
    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            enabled=True,
            provider_id="translator-provider",
            system_prompt="",
            custom_prefix="",
            max_retries=1,
            is_configured=lambda: True,
        )

    async def test_single_chinese_term_skips_the_llm(self) -> None:
        translator = PromptTranslator(self._config(), context=None)

        result = await translator.translate("双马尾")

        # context=None 意味着一旦走 LLM 必然抛错回落原文，能拿到 tag 就说明
        # 直查生效了
        self.assertEqual(str(result), "twintails")

    async def test_terse_hair_color_hits_before_llm_expansion(self) -> None:
        # normalize_translation_text 会把「蓝发」扩写成「蓝头发」喂 LLM，
        # 而词库收的是「蓝发」——直查必须先用原文
        translator = PromptTranslator(self._config(), context=None)

        result = await translator.translate("蓝发")

        self.assertEqual(str(result), "blue_hair")

    async def test_sentence_does_not_hit_and_falls_back(self) -> None:
        translator = PromptTranslator(self._config(), context=None)

        result = await translator.translate("一个女孩站在海边，夕阳西下")

        # 没命中直查，LLM 又不可用，按既有约定回落原文
        self.assertEqual(str(result), "一个女孩站在海边，夕阳西下")


class OfflineTranslationFallbackTest(unittest.IsolatedAsyncioTestCase):
    """在线标签服务休眠时，本地词库要能把中文名补上。"""

    async def test_local_names_fill_in_when_the_service_is_down(self) -> None:
        retriever = DanbooruTagRetriever(base_url="https://example.invalid", timeout=0.1)

        async def dead_service(*args, **kwargs):
            raise RuntimeError("service asleep")

        retriever._post_json = dead_service

        result = await retriever.lookup_tags(["twintails", "cat_ears"])

        self.assertEqual(result["translations"]["twintails"], "双马尾")
        self.assertEqual(result["translations"]["cat_ears"], "猫耳")

    async def test_empty_request_stays_empty(self) -> None:
        retriever = DanbooruTagRetriever(base_url="https://example.invalid", timeout=0.1)

        result = await retriever.lookup_tags([])

        self.assertEqual(result, {"items": [], "translations": {}})


if __name__ == "__main__":
    unittest.main()

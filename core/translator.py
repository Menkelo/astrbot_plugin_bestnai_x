"""提示词翻译模块。

功能：
- 使用 LLM 将中文描述转换为 NovelAI / Danbooru 英文 tag。
- 支持 AstrBot 供应商对接。
- 优先使用 translator_provider_id 对应供应商。
- 兼容 OpenAI API 格式。
- 兼容 Gemini 官方 generativelanguage.googleapis.com。
- 翻译失败自动重试，默认最多 3 次。
- 保留旧 translator_base_url / translator_api_key / translator_model 作为 fallback。
- 支持 Danbooru 在线 tag 候选检索注入。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import aiohttp


SYSTEM_PROMPT = """
你是 NovelAI 4/4.5 提示词专家，精通 Danbooru 标签体系。
任务：把用户中文描述转换为高质量英文 Danbooru tag 串。

输出规则：
- 只输出英文 tag，用英文逗号分隔。
- 禁止解释、禁止前缀、禁止代码块。
- 禁止输出负面提示词。
- 禁止添加 masterpiece、best quality 等质量词。
- 已知二次元角色使用 Danbooru 角色名格式，如 hatsune_miku_(vocaloid)。
- 单人女性使用 solo, 1girl。
- 单人男性使用 solo, 1boy。
- 多人使用 2girls、2boys、1boy 1girl 等，不加 solo。
- 现代二次元人物插画默认添加 year 2025。
- 如果是原创人物，需要补充发色、发型、瞳色、服装、动作、表情、场景、光影。
- 如果是已知角色，除非用户明确要求改变外貌，否则不要额外补发色、发型、瞳色等容易冲突的外貌 tag。
- 使用 NovelAI 权重时，格式必须正确，例如 {tag}, 1.2::tag::。
- 禁止输出中文。
""".strip()


def has_chinese(text: str) -> bool:
    """检测文本是否包含中文字符。"""

    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


class TranslatorError(Exception):
    """翻译错误。"""

    pass


@dataclass
class ResolvedProvider:
    """解析后的翻译供应商配置。"""

    name: str
    api_type: str
    base_url: str
    api_key: str
    model: str


class DanbooruTagRetriever:
    """Danbooru 在线 tag 候选检索器。"""

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def retrieve(self, query: str) -> Dict[str, List[Dict]]:
        """检索语义匹配和共现推荐 tag。失败返回空结构。"""

        empty = {"search": [], "related": []}

        if not query.strip():
            return empty

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(
                    f"{self.base_url}/api/search",
                    json={
                        "query": query,
                        "top_k": 5,
                        "limit": 30,
                        "popularity_weight": 0.15,
                        "show_nsfw": False,
                        "use_segmentation": True,
                    },
                ) as resp:
                    if resp.status != 200:
                        return empty

                    search_data = await resp.json()

                search_results = []

                for item in search_data.get("results", []):
                    if not isinstance(item, dict):
                        continue

                    tag = item.get("tag")
                    if not tag:
                        continue

                    search_results.append(
                        {
                            "tag": tag,
                            "cn_name": item.get("cn_name", ""),
                            "score": item.get("final_score", 0.0),
                            "category": item.get("category", "General"),
                        }
                    )

                if not search_results:
                    return empty

                seed_tags = [r["tag"] for r in search_results[:8]]
                related_results = []

                async with session.post(
                    f"{self.base_url}/api/related",
                    json={"tags": seed_tags, "limit": 20, "show_nsfw": False},
                ) as resp:
                    if resp.status == 200:
                        related_data = await resp.json()
                        items = related_data if isinstance(related_data, list) else []
                        search_tag_set = {r["tag"] for r in search_results}

                        for item in items:
                            if not isinstance(item, dict):
                                continue

                            tag = item.get("tag")
                            if not tag or tag in search_tag_set:
                                continue

                            related_results.append(
                                {
                                    "tag": tag,
                                    "cn_name": item.get("cn_name", ""),
                                    "cooc_score": item.get("cooc_score", 0.0),
                                    "category": item.get("category", "General"),
                                }
                            )

                return {
                    "search": search_results,
                    "related": related_results,
                }

        except Exception:
            return empty

    def format_candidates(self, results: Dict[str, List[Dict]]) -> str:
        """格式化为可注入 LLM 的文本块。"""

        search_items = results.get("search", [])
        related_items = results.get("related", [])

        if not search_items and not related_items:
            return ""

        lines = [
            "<tag_candidates>",
            "以下是从 Danbooru 数据库检索到的候选标签，仅供参考：",
            "",
        ]

        if search_items:
            lines.append("## 语义匹配")
            for item in search_items:
                cn = f"{item['cn_name']} → " if item.get("cn_name") else ""
                lines.append(
                    f"- {cn}{item['tag']} [{item['category']}] "
                    f"(相关度 {item['score']:.2f})"
                )

        if related_items:
            lines.append("")
            lines.append("## 共现推荐")
            for item in related_items:
                cn = f"{item['cn_name']} → " if item.get("cn_name") else ""
                lines.append(
                    f"- {cn}{item['tag']} [{item['category']}] "
                    f"(共现度 {item['cooc_score']:.2f})"
                )

        lines += [
            "",
            "使用规则：",
            "- 与用户描述相关的候选 tag 可优先采用。",
            "- 候选 tag 不完整时，用你自己的 Danbooru 知识补充。",
            "- 与描述不符的候选必须忽略。",
            "</tag_candidates>",
        ]

        return "\n".join(lines)


class PromptTranslator:
    """提示词翻译器。"""

    def __init__(self, config, context: Any = None):
        self.config = config
        self.context = context
        self.timeout = 60

    async def translate(self, text: str, danbooru_api_url: str = "") -> str:
        """将中文描述翻译为英文提示词。

        失败时返回原文，由上层逻辑决定是否中断。
        """

        if not self.config.enabled:
            return text

        if not has_chinese(text):
            return text

        if not self.config.is_configured():
            return text

        max_retries = int(getattr(self.config, "max_retries", 3) or 3)
        max_retries = max(1, min(max_retries, 5))

        last_error: Optional[Exception] = None

        for attempt in range(1, max_retries + 1):
            try:
                return await self._call_llm(text, danbooru_api_url=danbooru_api_url)

            except Exception as e:
                last_error = e

                try:
                    from astrbot.api import logger

                    logger.warning(
                        f"[BestNAI] 翻译失败，第 {attempt}/{max_retries} 次：{e}"
                    )
                except Exception:
                    pass

                if attempt < max_retries:
                    await asyncio.sleep(min(2 ** (attempt - 1), 5))

        try:
            from astrbot.api import logger

            logger.warning(f"[BestNAI] 翻译最终失败，使用原文: {last_error}")
        except Exception:
            pass

        return text

    def _resolve_provider(self) -> ResolvedProvider:
        """解析翻译供应商。

        优先级：
        1. translator_provider_id 对应 AstrBot 供应商。
        2. 旧配置 translator_base_url / translator_api_key / translator_model。
        """

        provider_id = getattr(self.config, "provider_id", "") or ""

        if provider_id and self.context is not None:
            provider = self.context.get_provider_by_id(provider_id)

            if not provider:
                raise TranslatorError(f"找不到翻译供应商 ID: {provider_id}")

            p_conf = getattr(provider, "provider_config", {}) or {}

            base_url = (
                getattr(provider, "api_base", "")
                or p_conf.get("api_base")
                or p_conf.get("api_base_url")
                or p_conf.get("base_url")
                or "https://generativelanguage.googleapis.com"
            )
            base_url = str(base_url).rstrip("/")

            api_key = ""

            for k in ("key", "keys", "api_key", "access_token"):
                val = p_conf.get(k)

                if isinstance(val, str) and val.strip():
                    api_key = val.strip()
                    break

                if isinstance(val, list) and val:
                    for item in val:
                        if isinstance(item, str) and item.strip():
                            api_key = item.strip()
                            break

                    if api_key:
                        break

            model = (
                getattr(provider, "model", "")
                or p_conf.get("model")
                or getattr(self.config, "model", "")
                or "gpt-4o-mini"
            )
            model = str(model).strip()

            api_type = "openai"

            if "generativelanguage.googleapis.com" in base_url:
                api_type = "gemini"
            elif "aiplatform.googleapis.com" in base_url:
                api_type = "vertex"
            else:
                api_type = "openai"

            if not api_key and api_type != "vertex":
                raise TranslatorError(f"翻译供应商 {provider_id} 缺少 API Key")

            return ResolvedProvider(
                name=provider_id,
                api_type=api_type,
                base_url=base_url,
                api_key=api_key,
                model=model,
            )

        base_url = getattr(self.config, "base_url", "") or ""
        api_key = getattr(self.config, "api_key", "") or ""
        model = getattr(self.config, "model", "") or "gpt-4o-mini"

        if not base_url or not api_key:
            raise TranslatorError("翻译器未配置 provider_id，也未配置 base_url/api_key")

        base_url = base_url.rstrip("/")

        api_type = "gemini" if "generativelanguage.googleapis.com" in base_url else "openai"

        return ResolvedProvider(
            name="manual_translator",
            api_type=api_type,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

    async def _call_llm(self, text: str, danbooru_api_url: str = "") -> str:
        """调用 LLM。"""

        provider = self._resolve_provider()

        system_prompt = (
            self.config.system_prompt.strip()
            if getattr(self.config, "system_prompt", "").strip()
            else SYSTEM_PROMPT
        )

        if getattr(self.config, "custom_prefix", "").strip():
            system_prompt = self.config.custom_prefix.strip() + "\n\n" + system_prompt

        tag_candidates_block = ""

        if danbooru_api_url:
            try:
                retriever = DanbooruTagRetriever(base_url=danbooru_api_url, timeout=8.0)
                results = await retriever.retrieve(text)
                tag_candidates_block = retriever.format_candidates(results)

                if tag_candidates_block:
                    from astrbot.api import logger

                    logger.info(
                        f"[BestNAI] Danbooru 检索完成："
                        f"{len(results['search'])} 条语义匹配，"
                        f"{len(results['related'])} 条共现推荐"
                    )

            except Exception as e:
                try:
                    from astrbot.api import logger

                    logger.warning(f"[BestNAI] Danbooru 检索失败，跳过: {e}")
                except Exception:
                    pass

        final_system_prompt = system_prompt

        if tag_candidates_block:
            final_system_prompt = f"{system_prompt}\n\n{tag_candidates_block}"

        try:
            from astrbot.api import logger

            logger.info(
                f"[BestNAI] 使用翻译供应商：{provider.name} "
                f"type={provider.api_type}, model={provider.model}"
            )
        except Exception:
            pass

        if provider.api_type == "gemini":
            return await self._call_gemini(provider, final_system_prompt, text)

        if provider.api_type == "vertex":
            raise TranslatorError(
                "当前 BestNAI 翻译器暂不直接支持 Vertex 供应商。"
                "请使用 OpenAI 兼容供应商或 Gemini API 供应商。"
            )

        return await self._call_openai_compatible(provider, final_system_prompt, text)

    async def _call_openai_compatible(
        self,
        provider: ResolvedProvider,
        system_prompt: str,
        text: str,
    ) -> str:
        """调用 OpenAI 兼容接口。"""

        base = provider.base_url.rstrip("/")

        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        payload = {
            "model": provider.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                body = await resp.text()

                if resp.status != 200:
                    raise TranslatorError(
                        f"OpenAI 兼容翻译接口返回 {resp.status}: {body[:300]}"
                    )

                try:
                    data = await resp.json(content_type=None)
                    result = data["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    raise TranslatorError(f"解析 OpenAI 兼容翻译响应失败: {e}") from e

                return self._clean_result(result)

    async def _call_gemini(
        self,
        provider: ResolvedProvider,
        system_prompt: str,
        text: str,
    ) -> str:
        """调用 Gemini 官方 API。

        支持：
        - https://generativelanguage.googleapis.com
        - https://generativelanguage.googleapis.com/v1beta
        - https://generativelanguage.googleapis.com/v1
        """

        base = provider.base_url.rstrip("/")

        if base.endswith("/v1beta") or base.endswith("/v1"):
            url = f"{base}/models/{provider.model}:generateContent?key={provider.api_key}"
        else:
            url = f"{base}/v1beta/models/{provider.model}:generateContent?key={provider.api_key}"

        user_text = (
            f"{system_prompt}\n\n"
            f"用户输入：{text}\n\n"
            f"请只输出最终英文 Danbooru tag 串，不要解释。"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": user_text,
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2000,
            },
        }

        headers = {
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                body = await resp.text()

                if resp.status != 200:
                    raise TranslatorError(
                        f"Gemini 翻译接口返回 {resp.status}: {body[:300]}"
                    )

                try:
                    data = await resp.json(content_type=None)
                    candidates = data.get("candidates", [])

                    if not candidates:
                        raise TranslatorError("Gemini 返回 candidates 为空")

                    parts = candidates[0].get("content", {}).get("parts", [])

                    result = "\n".join(
                        p.get("text", "") for p in parts if isinstance(p, dict)
                    ).strip()

                    if not result:
                        raise TranslatorError("Gemini 返回文本为空")

                    return self._clean_result(result)

                except TranslatorError:
                    raise
                except Exception as e:
                    raise TranslatorError(f"解析 Gemini 翻译响应失败: {e}") from e

    def _clean_result(self, result: str) -> str:
        """清理模型输出。"""

        result = (result or "").strip()

        result = re.sub(
            r"^```(?:text|txt|markdown)?",
            "",
            result,
            flags=re.IGNORECASE,
        ).strip()

        result = re.sub(r"```$", "", result).strip()

        result = re.sub(
            r"^(prompt|tags|tag|英文提示词|提示词)\s*[:：]\s*",
            "",
            result,
            flags=re.IGNORECASE,
        ).strip()

        lines = [line.strip() for line in result.splitlines() if line.strip()]

        if len(lines) > 1:
            result = ", ".join(lines)

        result = result.strip("`\"' ")

        return result

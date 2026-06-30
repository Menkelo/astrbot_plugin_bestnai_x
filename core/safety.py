"""QQ 防封安全审核模块。

功能：
- 提示词 NSFW 关键词过滤。
- 固定追加安全负面词。
- 图片发送前调用视觉模型审核。
- 审核模型明确判定 unsafe 时拦截。
- 审核模型报错 / 超时 / SSL 错误 / 供应商异常 / 结果解析失败时放行。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

try:
    from astrbot.api import logger
except Exception:
    import logging

    logger = logging.getLogger("bestnai.safety")


SAFE_NEGATIVE_TAGS = (
    "nsfw, explicit, nude, naked, nipples, nipple, areola, pussy, penis, vagina, "
    "sex, porn, hentai, ejaculation, cum, masturbation, oral sex, intercourse, "
    "underwear, lingerie, bikini, swimsuit, cleavage, see-through, transparent clothes, "
    "cameltoe, spread legs, ass focus, breast focus, erotic, suggestive"
)

HARD_BLOCK_WORDS = [
    # 中文 explicit
    "裸",
    "裸体",
    "全裸",
    "露点",
    "乳头",
    "乳晕",
    "下体",
    "阴部",
    "阴道",
    "阴茎",
    "性器",
    "生殖器",
    "性交",
    "做爱",
    "性爱",
    "色情",
    "黄片",
    "黄图",
    "涩图",
    "色图",
    "r18",
    "R18",
    "18禁",
    "本子",
    "自慰",
    "口交",
    "内射",
    "射精",
    "强奸",
    "凌辱",
    "调教",
    "援交",
    "萝莉色情",
    "幼女色情",

    # English explicit
    "nsfw",
    "explicit",
    "nude",
    "naked",
    "nipples",
    "nipple",
    "areola",
    "pussy",
    "penis",
    "vagina",
    "sex",
    "porn",
    "hentai",
    "masturbation",
    "ejaculation",
    "cum",
    "oral sex",
    "intercourse",
    "rape",
    "loli porn",
]


@dataclass
class SafetyCheckResult:
    safe: bool
    reason: str = ""
    source: str = "unknown"
    filtered_prompt: str = ""


@dataclass
class ResolvedProvider:
    name: str
    api_type: str
    base_url: str
    api_key: str
    model: str


def append_safe_negative(negative_prompt: str) -> str:
    """向负面提示词追加安全负面词。"""
    negative_prompt = negative_prompt or ""

    existing = negative_prompt.lower()
    tags_to_add = []

    for tag in [x.strip() for x in SAFE_NEGATIVE_TAGS.split(",") if x.strip()]:
        if tag.lower() not in existing:
            tags_to_add.append(tag)

    if not negative_prompt:
        return ", ".join(tags_to_add)

    if not tags_to_add:
        return negative_prompt

    return negative_prompt.rstrip(" ,") + ", " + ", ".join(tags_to_add)


def filter_sensitive_prompt(prompt: str) -> tuple[str, list[str]]:
    """从提示词中移除明显 NSFW / explicit 关键词。"""
    filtered = str(prompt or "")
    removed_words: list[str] = []

    for word in sorted(HARD_BLOCK_WORDS, key=len, reverse=True):
        if not word:
            continue

        pattern = re.escape(word)
        flags = re.IGNORECASE

        if word.isascii():
            pattern = rf"(?<![A-Za-z0-9_]){pattern}(?![A-Za-z0-9_])"

        filtered, count = re.subn(pattern, " ", filtered, flags=flags)

        if count:
            removed_words.append(word)

    filtered = re.sub(r"\s+", " ", filtered)
    filtered = re.sub(r"\s*[,，、;；]+\s*", ", ", filtered)
    filtered = re.sub(r"(,\s*){2,}", ", ", filtered)

    return filtered.strip(" ,;，。；、").strip(), removed_words


class SafetyModerator:
    """安全审核器。"""

    def __init__(self, config, context: Any = None):
        self.config = config
        self.context = context
        self.timeout = 60

    def check_prompt(self, prompt: str) -> SafetyCheckResult:
        """提示词前置过滤。

        这里只过滤明显 NSFW / explicit 关键词，不再直接拒绝生成。
        """
        if not getattr(self.config, "prompt_block_enabled", True):
            return SafetyCheckResult(
                safe=True,
                source="prompt",
                filtered_prompt=prompt or "",
            )

        filtered_prompt, removed_words = filter_sensitive_prompt(prompt)

        if removed_words:
            return SafetyCheckResult(
                safe=True,
                reason=f"prompt 已过滤敏感词：{', '.join(removed_words)}",
                source="prompt",
                filtered_prompt=filtered_prompt,
            )

        return SafetyCheckResult(
            safe=True,
            source="prompt",
            filtered_prompt=prompt or "",
        )

    async def check_image(self, image_bytes: bytes) -> SafetyCheckResult:
        """图片发送前审核。

        当前策略：
        - 审核关闭：放行
        - 审核供应商未配置 / 获取失败：放行
        - 审核接口超时 / 报错 / SSL 错误：放行
        - 审核供应商不支持：放行
        - 审核模型返回格式无法解析：放行
        - 只有审核模型明确返回 unsafe / safe=false 时拦截

        这样可以避免因为审核模型或网络异常导致正常图片被误拦。
        """
        if not getattr(self.config, "enabled", True):
            return SafetyCheckResult(safe=True, source="disabled")

        try:
            provider = self._resolve_provider()
        except Exception as e:
            logger.warning(f"[BestNAI/Safety] 审核供应商解析失败，已放行: {e}")
            return SafetyCheckResult(
                safe=True,
                reason=f"审核供应商不可用，已放行：{e}",
                source="provider_error",
            )

        try:
            if provider.api_type == "gemini":
                return await self._check_image_gemini(provider, image_bytes)

            if provider.api_type == "openai":
                return await self._check_image_openai(provider, image_bytes)

            if provider.api_type == "vertex":
                logger.warning("[BestNAI/Safety] 暂不支持 Vertex 审核供应商，已放行")
                return SafetyCheckResult(
                    safe=True,
                    reason="暂不支持 Vertex 审核供应商，已放行",
                    source="unsupported_provider",
                )

            logger.warning(
                f"[BestNAI/Safety] 未知审核供应商类型 {provider.api_type}，已放行"
            )
            return SafetyCheckResult(
                safe=True,
                reason=f"未知审核供应商类型：{provider.api_type}，已放行",
                source="unknown_provider",
            )

        except asyncio.TimeoutError:
            logger.warning("[BestNAI/Safety] 图片审核超时，已放行")
            return SafetyCheckResult(
                safe=True,
                reason="图片审核超时，已放行",
                source="timeout",
            )

        except Exception as e:
            logger.warning(f"[BestNAI/Safety] 图片审核失败，已放行: {e}")
            return SafetyCheckResult(
                safe=True,
                reason=f"图片审核失败，已放行：{e}",
                source="error",
            )

    def _resolve_provider(self) -> ResolvedProvider:
        """解析审核供应商。"""
        provider_id = getattr(self.config, "provider_id", "") or ""

        if not provider_id:
            raise RuntimeError("未选择 safety_config.provider_id")

        if self.context is None:
            raise RuntimeError("缺少 AstrBot context")

        provider = self.context.get_provider_by_id(provider_id)

        if not provider:
            raise RuntimeError(f"找不到审核供应商 ID: {provider_id}")

        p_conf = getattr(provider, "provider_config", {}) or {}

        base_url = (
            getattr(provider, "api_base", "")
            or p_conf.get("api_base")
            or p_conf.get("api_base_url")
            or p_conf.get("base_url")
            or ""
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
            or "gpt-4o-mini"
        )
        model = str(model).strip()

        if not base_url:
            raise RuntimeError("审核供应商缺少 API Base")

        if not api_key:
            raise RuntimeError("审核供应商缺少 API Key")

        if "generativelanguage.googleapis.com" in base_url:
            api_type = "gemini"
        elif "aiplatform.googleapis.com" in base_url:
            api_type = "vertex"
        else:
            api_type = "openai"

        return ResolvedProvider(
            name=provider_id,
            api_type=api_type,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

    def _mime(self, image_bytes: bytes) -> str:
        """根据图片头判断 MIME。"""
        if image_bytes.startswith(b"\x89PNG"):
            return "image/png"

        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"

        if image_bytes.startswith(b"RIFF") and b"WEBP" in image_bytes[:20]:
            return "image/webp"

        return "image/png"

    def _audit_prompt(self) -> str:
        """视觉审核提示词。"""
        return (
            "你是图片安全审核器。请判断图片是否适合发送到 QQ 群聊。\n"
            "如果图片包含以下任意内容，判定 unsafe：\n"
            "- 裸露胸部、乳头、乳晕、裸露下体、生殖器\n"
            "- 明显性行为、色情姿势、自慰、射精、性交\n"
            "- 低胸、过度暴露、强性暗示构图\n"
            "- 未成年人色情化或疑似未成年人色情化\n"
            "- hentai、pornographic、explicit 内容\n\n"
            "只输出 JSON，不要解释：\n"
            "{\"safe\": true, \"reason\": \"\"}\n"
            "或\n"
            "{\"safe\": false, \"reason\": \"原因\"}"
        )

    def _parse_result(self, text: str) -> SafetyCheckResult:
        """解析审核模型输出。

        解析策略：
        - JSON 中 safe=true：放行
        - JSON 中 safe=false：拦截
        - 文本中明确出现 safe false / unsafe：拦截
        - 无法解析：放行
        """
        raw = (text or "").strip()

        raw = re.sub(r"^```(?:json)?", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"```$", "", raw).strip()

        m = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if m:
            raw = m.group(0)

        try:
            data = json.loads(raw)
            safe = bool(data.get("safe", False))
            reason = str(data.get("reason", "") or "")
            return SafetyCheckResult(safe=safe, reason=reason, source="vision")
        except Exception:
            lower = raw.lower()

            if '"safe": true' in lower or "safe true" in lower:
                return SafetyCheckResult(safe=True, reason="", source="vision")

            if "unsafe" in lower or '"safe": false' in lower or "safe false" in lower:
                return SafetyCheckResult(
                    safe=False,
                    reason=raw[:120],
                    source="vision",
                )

        logger.warning(f"[BestNAI/Safety] 无法解析审核结果，已放行：{raw[:120]}")
        return SafetyCheckResult(
            safe=True,
            reason=f"无法解析审核结果，已放行：{raw[:120]}",
            source="parse_error",
        )

    async def _check_image_openai(
        self,
        provider: ResolvedProvider,
        image_bytes: bytes,
    ) -> SafetyCheckResult:
        """调用 OpenAI 兼容视觉接口审核。"""
        base = provider.base_url.rstrip("/")

        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        b64 = base64.b64encode(image_bytes).decode()
        mime = self._mime(image_bytes)

        payload = {
            "model": provider.model,
            "messages": [
                {
                    "role": "system",
                    "content": self._audit_prompt(),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}"
                            },
                        },
                        {
                            "type": "text",
                            "text": "请审核这张图片是否安全。",
                        },
                    ],
                },
            ],
            "temperature": 0,
            "max_tokens": 200,
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
                    raise RuntimeError(
                        f"OpenAI 审核接口返回 {resp.status}: {body[:200]}"
                    )

                data = await resp.json(content_type=None)
                text = data["choices"][0]["message"]["content"]
                result = self._parse_result(text)

                logger.info(
                    f"[BestNAI/Safety] OpenAI 审核结果 "
                    f"safe={result.safe}, reason={result.reason}"
                )
                return result

    async def _check_image_gemini(
        self,
        provider: ResolvedProvider,
        image_bytes: bytes,
    ) -> SafetyCheckResult:
        """调用 Gemini 视觉接口审核。"""
        base = provider.base_url.rstrip("/")

        if base.endswith("/v1beta") or base.endswith("/v1"):
            url = f"{base}/models/{provider.model}:generateContent?key={provider.api_key}"
        else:
            url = f"{base}/v1beta/models/{provider.model}:generateContent?key={provider.api_key}"

        b64 = base64.b64encode(image_bytes).decode()
        mime = self._mime(image_bytes)

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": self._audit_prompt()
                        },
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": b64
                            }
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 200,
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
                    raise RuntimeError(
                        f"Gemini 审核接口返回 {resp.status}: {body[:200]}"
                    )

                data = await resp.json(content_type=None)
                candidates = data.get("candidates", [])

                if not candidates:
                    raise RuntimeError("Gemini 审核返回 candidates 为空")

                parts = candidates[0].get("content", {}).get("parts", [])
                text = "\n".join(
                    p.get("text", "") for p in parts if isinstance(p, dict)
                ).strip()

                result = self._parse_result(text)

                logger.info(
                    f"[BestNAI/Safety] Gemini 审核结果 "
                    f"safe={result.safe}, reason={result.reason}"
                )
                return result

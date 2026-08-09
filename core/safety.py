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

try:
    from astrbot.api import logger
except Exception:
    import logging

    logger = logging.getLogger("bestnai.safety")

from .api_errors import describe_api_error
from .provider_utils import (
    ProviderRoutingError,
    call_provider,
    provider_model_of,
    response_text,
)


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


def filter_sensitive_prompt(
    prompt: str,
    blocked_words: list[str] | None = None,
) -> tuple[str, list[str]]:
    """从提示词中移除明显 NSFW / explicit 关键词。"""
    filtered = str(prompt or "")
    removed_words: list[str] = []
    words = HARD_BLOCK_WORDS if blocked_words is None else blocked_words
    normalized_words: list[str] = []
    seen_words: set[str] = set()
    for raw_word in words:
        word = str(raw_word).strip()
        word_key = word.casefold()
        if not word or word_key in seen_words:
            continue
        seen_words.add(word_key)
        normalized_words.append(word)

    for word in sorted(normalized_words, key=len, reverse=True):
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

        blocked_words = getattr(self.config, "prompt_block_words", None)
        filtered_prompt, removed_words = filter_sensitive_prompt(
            prompt,
            blocked_words,
        )

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

        configured_id = str(
            getattr(self.config, "provider_id", "") or ""
        ).strip()
        if not configured_id:
            # Safety is enabled by default, while its visual provider is not.
            # Do not silently bill or send images to AstrBot's active chat
            # model merely because the user left this optional field empty.
            return SafetyCheckResult(
                safe=True,
                reason="未配置图片审核提供商，已放行",
                source="provider_unconfigured",
            )

        try:
            mime = self._mime(image_bytes)
            b64 = base64.b64encode(image_bytes).decode("ascii")
            provider_id, provider, response = await call_provider(
                self.context,
                configured_id,
                prompt="请审核这张图片是否安全。",
                system_prompt=self._audit_prompt(),
                image_urls=[f"data:{mime};base64,{b64}"],
                temperature=0,
                max_tokens=200,
            )
            result = self._parse_result(response_text(response))
            logger.info(
                f"[BestNAI/Safety] 使用 AstrBot provider={provider_id}, "
                f"model={provider_model_of(provider) or '(当前模型)'}, "
                f"safe={result.safe}, reason={result.reason}"
            )
            return result
        except ProviderRoutingError as e:
            logger.warning(f"[BestNAI/Safety] 审核供应商解析失败，已放行: {e}")
            reason = describe_api_error(str(e), "图片审核")
            return SafetyCheckResult(
                safe=True,
                reason=f"{reason}，已放行",
                source="provider_error",
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.warning("[BestNAI/Safety] 图片审核超时，已放行")
            return SafetyCheckResult(
                safe=True,
                reason="图片审核超时，已放行",
                source="timeout",
            )

        except Exception as e:
            logger.warning(f"[BestNAI/Safety] 图片审核失败，已放行: {e}")
            reason = describe_api_error(str(e), "图片审核")
            return SafetyCheckResult(
                safe=True,
                reason=f"{reason}，已放行",
                source="error",
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
        except Exception:
            data = None

        # 缺少 safe 字段说明模型没按格式回答，按模块约定继续走文本兜底，
        # 不能默认成 False 把正常图片拦下来。
        if isinstance(data, dict) and "safe" in data:
            safe_value = data.get("safe")
            parsed_safe: bool | None = None
            if isinstance(safe_value, bool):
                parsed_safe = safe_value
            elif isinstance(safe_value, (int, float)) and safe_value in {0, 1}:
                parsed_safe = bool(safe_value)
            elif isinstance(safe_value, str):
                normalized = safe_value.strip().casefold()
                if normalized in {"true", "safe", "yes", "1", "安全"}:
                    parsed_safe = True
                elif normalized in {"false", "unsafe", "no", "0", "不安全"}:
                    parsed_safe = False
            if parsed_safe is not None:
                return SafetyCheckResult(
                    safe=parsed_safe,
                    reason=str(data.get("reason", "") or ""),
                    source="vision",
                )

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

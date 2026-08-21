from __future__ import annotations

import os
import re
import tempfile
from dataclasses import replace
from typing import List, Tuple

from astrbot.api import logger

from ..core.safety import append_safe_negative
from ..core.prompt_tokens import rebuild_weighted_token, split_prompt_tokens, weighted_token_parts
from ..models.config import GenerationConfig, PluginConfig


FIXED_MODEL = "nai-diffusion-4-5-full"

# Studio 工作区允许覆盖的采样器与噪声调度白名单（NovelAI V4.5 常用集合），
# 列表顺序即前端下拉框的展示顺序。
ALLOWED_SAMPLERS: tuple = (
    "k_euler_ancestral",
    "k_euler",
    "k_dpmpp_2s",
    "k_dpmpp_2m",
    "k_dpmpp_sde",
)
ALLOWED_NOISE_SCHEDULES: tuple = (
    "karras",
    "native",
    "exponential",
    "polyexponential",
)
_SAMPLER_SET = frozenset(ALLOWED_SAMPLERS)
_NOISE_SCHEDULE_SET = frozenset(ALLOWED_NOISE_SCHEDULES)


def apply_generation_overrides(
    gen_config: GenerationConfig,
    negative_prompt: str = "",
    sampler: str = "",
    noise_schedule: str = "",
    cfg_rescale: object = None,
) -> GenerationConfig:
    """把 Studio 工作区传入的参数覆盖到生成配置上。

    空值直接沿用配置；采样器 / 噪声调度不在白名单内时忽略该覆盖，
    cfg_rescale 收敛到 [0, 1]，负面提示词走与配置一致的 ASCII 清洗。
    """
    overrides: dict = {}

    if negative_prompt:
        cleaned_negative = normalize_prompt_ascii(negative_prompt)
        if cleaned_negative:
            overrides["negative_prompt"] = cleaned_negative

    if sampler in _SAMPLER_SET:
        overrides["sampler"] = sampler

    if noise_schedule in _NOISE_SCHEDULE_SET:
        overrides["noise_schedule"] = noise_schedule

    if cfg_rescale is not None:
        try:
            overrides["cfg_rescale"] = max(0.0, min(1.0, float(cfg_rescale)))
        except (TypeError, ValueError):
            pass

    if not overrides:
        return gen_config

    return replace(gen_config, **overrides)

# 反推时给用户手写提示词加的正向权重。
# NovelAI 数值语法：`1.3::tag, tag::`，比花括号叠加更好控制强度。
RETAG_USER_PROMPT_WEIGHT = 1.3


def apply_prompt_weight(text: str, weight: float = RETAG_USER_PROMPT_WEIGHT) -> str:
    """用 NovelAI 数值语法给一段提示词整体加权。

    官方格式：权重数字紧贴 `::` 开头，用不带数字的 `::` 收尾，例如
    `1girl, 1.5::rain, night ::, 0.5::coat ::, black shoes`。
    仅 V4 及以上模型支持，本插件固定 nai-diffusion-4-5-full，可用。

    收尾的 `::` 前必须留一个空格：内容若以数字结尾（例如 `year 2025`），
    写成 `year 2025::` 会被解析成"权重 2025 的新段落"。

    反推产出的 tags 往往几十个，用户自己写的那几个词会被淹没。
    加权后它们在最终 prompt 里的影响力才和"用户主动要求"相称。

    权重为 1（或更小 / 非法）时原样返回，不引入多余语法。
    """
    content = str(text or "").strip().strip(",").strip()

    if not content:
        return ""

    try:
        value = float(weight)
    except (TypeError, ValueError):
        return content

    if not (value > 1.0):
        return content

    segments = split_prompt_tokens(content)
    if not any(weighted_token_parts(segment)[2] for segment in segments):
        return f"{value:g}::{content} ::"

    # Preserve existing NAI groups and weight only the unweighted runs around
    # them.  Wrapping the whole string would produce invalid nested syntax such
    # as ``1.3::1.2::tag ::, other ::``.
    weighted_parts: list[str] = []
    pending: list[str] = []

    def flush_pending() -> None:
        if not pending:
            return
        weighted_parts.append(f"{value:g}::{', '.join(pending)} ::")
        pending.clear()

    for segment in segments:
        existing_weight, inner, weighted = weighted_token_parts(segment)
        if weighted:
            flush_pending()
            weighted_parts.append(rebuild_weighted_token(existing_weight, inner))
        else:
            pending.append(segment)
    flush_pending()
    return ", ".join(part for part in weighted_parts if part)


def cleanup_file(file_path: str) -> None:
    if not file_path:
        return

    try:
        if os.path.exists(file_path) and os.path.isfile(file_path):
            os.remove(file_path)
    except Exception as e:
        logger.debug(f"[BestNAI] 清理临时文件失败: {file_path}, {e}")


def normalize_prompt_ascii(text: str) -> str:
    text = str(text or "")

    replacements = {
        "，": ",",
        "。": ".",
        "：": ":",
        "；": ";",
        "！": "!",
        "？": "?",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "、": ",",
        "　": " ",
        "×": "x",
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }

    for k, v in replacements.items():
        text = text.replace(k, v)

    text = re.sub(r"[^\x00-\x7F]+", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"(,\s*){2,}", ", ", text)

    return text.strip(" ,;").strip()


def find_non_ascii_chars(text: str) -> List[str]:
    seen = set()
    result: List[str] = []

    for ch in str(text or ""):
        if ord(ch) > 127 and ch not in seen:
            seen.add(ch)
            result.append(ch)

    return result


def save_image_to_temp(img_bytes: bytes, img_format: str = "png") -> str:
    img_format = (img_format or "png").lower().strip(". ")

    if img_format in {"jpeg", "jpg"}:
        suffix = ".jpg"
    elif img_format == "webp":
        suffix = ".webp"
    elif img_format == "gif":
        suffix = ".gif"
    else:
        suffix = ".png"

    fd, path = tempfile.mkstemp(prefix="bestnai_", suffix=suffix)

    try:
        with os.fdopen(fd, "wb") as f:
            f.write(img_bytes)
    except Exception:
        try:
            os.close(fd)
        except Exception:
            pass
        cleanup_file(path)
        raise

    return path


class PromptBuilder:
    def __init__(self, plugin_config: PluginConfig, resolve_ratio_to_size):
        self.plugin_config = plugin_config
        self.resolve_ratio_to_size = resolve_ratio_to_size

    def build_generation_config(
        self,
        ratio_name_or_size: str,
        apply_safe_negative: bool = True,
    ) -> GenerationConfig:
        gen_config = self.plugin_config.get_generation_config_for_version("4.5")

        width, height = self.resolve_ratio_to_size(ratio_name_or_size)

        raw_negative_prompt = gen_config.negative_prompt
        if apply_safe_negative:
            raw_negative_prompt = append_safe_negative(raw_negative_prompt)
        cleaned_negative_prompt = normalize_prompt_ascii(raw_negative_prompt)

        removed_chars = find_non_ascii_chars(raw_negative_prompt)

        if removed_chars:
            logger.info(
                f"[BestNAI] 已自动清理负面提示词中的非 ASCII 字符：{' '.join(removed_chars)}"
            )

        gen_config = replace(
            gen_config,
            width=width,
            height=height,
            model=FIXED_MODEL,
            negative_prompt=cleaned_negative_prompt,
        )

        return gen_config

    def build_final_prompt(
        self,
        prompt: str,
        artist_prompt: str,
        suffix: str,
    ) -> str:
        raw_parts = [
            (artist_prompt or "").strip(),
            (prompt or "").strip(),
            (suffix or "").strip(),
        ]

        raw_final_prompt = ", ".join(p for p in raw_parts if p)
        cleaned_final_prompt = normalize_prompt_ascii(raw_final_prompt)

        removed_chars = find_non_ascii_chars(raw_final_prompt)

        if removed_chars:
            logger.info(
                f"[BestNAI] 已自动清理最终 prompt 中的非 ASCII 字符：{' '.join(removed_chars)}"
            )

        return cleaned_final_prompt

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import replace
from typing import List, Tuple

from astrbot.api import logger

from ..core.safety import append_safe_negative
from ..models.config import GenerationConfig, PluginConfig


FIXED_MODEL = "nai-diffusion-4-5-full"


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

    def build_generation_config(self, ratio_name_or_size: str) -> GenerationConfig:
        gen_config = self.plugin_config.get_generation_config_for_version("4.5")

        width, height = self.resolve_ratio_to_size(ratio_name_or_size)

        raw_negative_prompt = append_safe_negative(gen_config.negative_prompt)
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

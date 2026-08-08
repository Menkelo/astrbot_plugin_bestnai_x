from __future__ import annotations

import asyncio
import json
import re
from typing import Dict, Iterable, Tuple

from astrbot.api import logger

from .api_errors import describe_api_error
from .provider_utils import (
    ProviderRoutingError,
    call_provider,
    provider_model_of,
    response_text,
)
from .prompt_tokens import (
    expand_prompt_tokens,
    rebuild_weighted_token,
    split_prompt_tokens,
    weighted_token_parts,
)


class ImageRetagError(Exception):
    pass


# These are generation controls, not visual attributes. Keeping them out of
# retag output prevents the normal canvas artist/quality pipeline from adding
# them a second time.
_CONTROL_TAGS = {
    "best quality",
    "amazing quality",
    "very aesthetic",
    "absurdres",
    "masterpiece",
    "high quality",
    "ultra detailed",
    "highres",
    "score_9",
    "score_8_up",
    "score_7_up",
    "score_6_up",
    "rating:safe",
    "rating:general",
    "rating:questionable",
    "rating:explicit",
}


def _clean_tags(text: str) -> str:
    text = str(text or "").strip()

    text = re.sub(r"^```(?:txt|text|json)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"```$", "", text).strip()

    try:
        data = json.loads(text)

        if isinstance(data, list):
            text = ", ".join(str(x) for x in data)

        elif isinstance(data, dict):
            for key in ("tags", "prompt", "result", "output", "caption"):
                val = data.get(key)

                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    break

                if isinstance(val, list):
                    text = ", ".join(str(x) for x in val)
                    break

    except Exception:
        pass

    for prefix in [
        "tags:",
        "prompt:",
        "danbooru tags:",
        "novelai tags:",
        "nai tags:",
        "caption:",
        "result:",
        "output:",
    ]:
        idx = text.lower().find(prefix)

        if idx >= 0:
            text = text[idx + len(prefix):].strip()
            break

    text = text.replace("，", ",").replace("、", ",").replace("\n", ",")
    text = re.sub(r"\s*,\s*", ", ", text)
    text = re.sub(r"(,\s*){2,}", ", ", text)
    text = text.strip(" ,;")

    # 移除中文/emoji/非 ASCII，避免生图接口拒绝
    text = re.sub(r"[^\x00-\x7F]+", "", text)
    text = re.sub(r"\s+", " ", text).strip(" ,;")

    return text


def _clean_tag_token(value: str) -> str:
    """清理单个角色 / 作品 tag。"""
    token = str(value or "").strip()

    # 模型偶尔会返回 ["hatsune_miku"] 或 "character: hatsune_miku"
    token = token.strip("[]()\"' \t")
    token = re.sub(
        r"^(?:character|series|copyright|角色|作品)\s*[:：]\s*",
        "",
        token,
        flags=re.IGNORECASE,
    ).strip()

    token = re.sub(r"[^\x00-\x7F]+", "", token)
    token = re.sub(r"\s+", " ", token).strip(" ,;")

    # 明确表示「没识别出来」的各种写法一律当空，避免污染提示词
    if token.lower() in {
        "",
        "none",
        "null",
        "n/a",
        "na",
        "nan",
        "unknown",
        "unidentified",
        "original",
        "original character",
        "not a character",
        "no character",
        "-",
    }:
        return ""

    return token


def _tag_key(value: str) -> str:
    """Return a stable comparison key without prompt grouping brackets."""
    return re.sub(r"\s+", " ", re.sub(r"[\[\]{}()]+", "", str(value or "").lower())).strip()


def _extra_control_tag_keys(extra_control_tags: Iterable[str] | str | None) -> set[str]:
    """Expand configured artist/quality prompts into exact tag keys.

    Some artist presets use bare tags wrapped in braces rather than the usual
    ``artist:`` prefix.  They cannot be identified safely by a generic regex,
    so callers may provide the configured control prompts and we compare their
    atomic tags exactly.
    """
    if not extra_control_tags:
        return set()
    values = (extra_control_tags,) if isinstance(extra_control_tags, str) else extra_control_tags
    keys: set[str] = set()
    for value in values or ():
        for segment in split_prompt_tokens(_clean_tags(str(value or ""))):
            _, atoms, _weighted = weighted_token_parts(segment)
            for atom in atoms:
                key = _tag_key(atom).strip(" ,;")
                if key:
                    keys.add(key)
    return keys


def strip_control_tags(
    text: str,
    *,
    extra_control_tags: Iterable[str] | str | None = None,
) -> str:
    """Remove artist/quality/rating controls from a retag prompt.

    ``extra_control_tags`` is used for configured presets whose artist names
    are bare tags (for example ``{hokori sakuni}``) and therefore cannot be
    recognized from the tag text alone.
    """
    cleaned = _clean_tags(text)
    extra_keys = _extra_control_tag_keys(extra_control_tags)
    kept = []
    seen = set()
    for token_segment in split_prompt_tokens(cleaned):
        weight, atoms, weighted = weighted_token_parts(token_segment)
        filtered_atoms = []
        for raw_token in atoms:
            token = raw_token.strip(" ,;")
            if not token:
                continue
            lowered = token.lower()
            plain = _tag_key(token)
            if "artist:" in lowered or re.search(r"\bartist(?:_|\s)", lowered):
                continue
            if plain in extra_keys or plain in _CONTROL_TAGS or any(
                phrase in plain for phrase in ("quality", "aesthetic", "absurdres")
            ):
                continue
            if re.match(r"^(?:rating|score)\s*[:_]", plain):
                continue
            if plain in seen:
                continue
            seen.add(plain)
            filtered_atoms.append(token)
        if not filtered_atoms:
            continue
        kept.append(
            rebuild_weighted_token(weight, filtered_atoms)
            if weighted
            else ", ".join(filtered_atoms)
        )
    return ", ".join(kept).strip(" ,;")


def parse_retag_response(
    text: str,
    *,
    extra_control_tags: Iterable[str] | str | None = None,
) -> Tuple[str, str, str]:
    """解析反推模型输出，返回 (角色 tag, 作品 tag, 其余 tags)。

    模型被要求返回 {"character","series","tags"}。拿不到结构化结果时
    退回旧行为：整段当作 tags，角色和作品为空。
    """
    raw = str(text or "").strip()

    raw_json = re.sub(r"^```(?:json|txt|text)?", "", raw, flags=re.IGNORECASE).strip()
    raw_json = re.sub(r"```$", "", raw_json).strip()

    data = None

    try:
        data = json.loads(raw_json)
    except Exception:
        # 有些模型会在 JSON 前后多带一句解释
        match = re.search(r"\{.*\}", raw_json, flags=re.DOTALL)

        if match:
            try:
                data = json.loads(match.group(0))
            except Exception:
                data = None

    if not isinstance(data, dict) or "tags" not in data:
        return "", "", strip_control_tags(
            raw,
            extra_control_tags=extra_control_tags,
        )

    tags_value = data.get("tags")

    if isinstance(tags_value, list):
        tags_value = ", ".join(str(x) for x in tags_value)

    character = _clean_tag_token(data.get("character", ""))
    series = _clean_tag_token(data.get("series", ""))
    tags = strip_control_tags(
        str(tags_value or ""),
        extra_control_tags=extra_control_tags,
    )

    return character, series, tags


def compose_retag_prompt(character: str, series: str, tags: str) -> str:
    """把角色、作品、其余 tags 拼成最终提示词，角色信息排在最前。"""
    parts = []
    tag_keys = {
        re.sub(r"\s+", " ", str(item or "").strip(" ,;{}[]()").lower())
        for item in expand_prompt_tokens(tags)
        if str(item or "").strip()
    }

    for token in (character, series):
        if not token:
            continue

        # 模型可能已经把角色 tag 写进 tags 里了，避免重复
        token_key = re.sub(r"\s+", " ", token.strip(" ,;{}[]()").lower())
        if token_key in tag_keys:
            continue

        if token not in parts:
            parts.append(token)

    if tags:
        parts.append(tags)

    return ", ".join(parts).strip(" ,")


class ImageRetagger:
    def __init__(
        self,
        config,
        context,
        extra_control_tags: Iterable[str] | str | None = None,
    ) -> None:
        self.config = config
        self.context = context
        self.extra_control_tags = tuple(
            (extra_control_tags,)
            if isinstance(extra_control_tags, str)
            else (extra_control_tags or ())
        )

    async def retag(
        self,
        image_path_or_url: str,
        user_hint: str = "",
        debug: bool = False,
    ) -> str:
        result = await self.retag_details(
            image_path_or_url,
            user_hint=user_hint,
            debug=debug,
        )
        return str(result.get("prompt") or "")

    async def retag_details(
        self,
        image_path_or_url: str,
        user_hint: str = "",
        debug: bool = False,
    ) -> Dict[str, str]:
        provider_id = getattr(self.config, "provider_id", "") or ""

        if not provider_id:
            raise ImageRetagError("未配置图片反推接口提供商")

        system_prompt = (
            "You are an expert anime image tagger for NovelAI image generation.\n"
            "\n"
            "Work in two steps.\n"
            "Step 1 - Identify the character. Decide whether the subject is a "
            "recognizable named character from an existing work. Only when you are "
            "confident, report its canonical Danbooru character tag and the "
            "copyright/series tag. When the subject is an original character, a real "
            "person, or you are not confident, leave both fields empty. "
            "Never guess and never invent an identity.\n"
            "Step 2 - Describe the image as English Danbooru/NovelAI tags. "
            "Focus on subject, hair, eyes, clothing, pose, expression, background, "
            "composition, lighting, camera angle, and visible style. Do not output "
            "artist:, quality, rating, score, masterpiece, or aesthetic control tags.\n"
            "\n"
            "Respond with a single JSON object and nothing else. No markdown fence, "
            "no explanation:\n"
            '{"character": "hatsune_miku", "series": "vocaloid", '
            '"tags": "1girl, solo, twintails, ..."}\n'
            'Use "" for character and series when there is no recognizable character. '
            "Do not repeat the character or series tag inside tags. Do not include "
            "artist or quality controls in tags. "
            "Tags must be comma-separated English Danbooru tags. "
            "Do not output Chinese, Japanese, emoji, or non-ASCII characters."
        )

        user_text = (
            "Convert this image into NovelAI / Danbooru image generation tags. "
            "Return the JSON object described in the system prompt."
        )
        # Pass the original local path/URL to AstrBot.  Its provider adapter
        # owns media resolution and the correct multimodal request shape.
        try:
            resolved_id, provider, response = await call_provider(
                self.context,
                provider_id,
                prompt=user_text,
                system_prompt=system_prompt,
                image_urls=[str(image_path_or_url)],
                temperature=0.2,
            )
            content = response_text(response)
            logger.info(
                f"[BestNAI/ImageRetag] 使用 AstrBot provider={resolved_id}, "
                f"model={provider_model_of(provider) or '(当前模型)'}"
            )
        except ProviderRoutingError as exc:
            raise ImageRetagError(describe_api_error(str(exc), "图片反推", debug)) from exc
        except (asyncio.TimeoutError, TimeoutError) as e:
            raise ImageRetagError("图片反推请求超时") from e
        except Exception as e:
            logger.exception(f"[BestNAI/ImageRetag] 调用提供商反推失败: {e}")
            raise ImageRetagError(describe_api_error(str(e), "图片反推", debug)) from e

        character, series, tags = parse_retag_response(
            content,
            extra_control_tags=self.extra_control_tags,
        )

        if not tags and not character:
            logger.warning(f"[BestNAI/ImageRetag] 空反推结果，raw={content[:1000]}")
            raise ImageRetagError("图片反推结果为空")

        if character:
            logger.info(
                f"[BestNAI/ImageRetag] 已识别角色：{character}"
                f"{f'（{series}）' if series else ''}"
            )
        else:
            logger.info("[BestNAI/ImageRetag] 未识别到已知角色，仅使用外观 tags")

        prompt = compose_retag_prompt(character, series, tags)

        logger.info(f"[BestNAI/ImageRetag] tags={prompt[:500]}")

        return {
            "prompt": prompt,
            "character": character,
            "series": series,
        }

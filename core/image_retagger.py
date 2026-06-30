from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, Dict, Tuple

import aiohttp

from astrbot.api import logger


class ImageRetagError(Exception):
    pass


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


def _guess_mime(path_or_url: str) -> str:
    low = str(path_or_url or "").lower()

    if low.endswith(".jpg") or low.endswith(".jpeg"):
        return "image/jpeg"

    if low.endswith(".webp"):
        return "image/webp"

    if low.endswith(".gif"):
        return "image/gif"

    return "image/png"


async def _url_to_data_url(url: str) -> str:
    timeout = aiohttp.ClientTimeout(total=60)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/*,*/*",
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status < 200 or resp.status >= 300:
                text = await resp.text()
                raise ImageRetagError(f"下载图片失败 HTTP {resp.status}: {text[:200]}")

            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            data = await resp.read()

    if not content_type.startswith("image/"):
        content_type = _guess_mime(url)

    b64 = base64.b64encode(data).decode("utf-8")

    return f"data:{content_type};base64,{b64}"


async def _image_to_data_url(image_path_or_url: str) -> str:
    value = str(image_path_or_url or "").strip()

    if not value:
        raise ImageRetagError("图片为空")

    if value.startswith("http://") or value.startswith("https://"):
        return await _url_to_data_url(value)

    if value.startswith("file://"):
        value = value[7:]

    value = value.replace("\\", "/")

    while value.startswith("//"):
        value = value[1:]

    if not os.path.isabs(value):
        value = os.path.abspath(value)

    if not os.path.exists(value):
        raise ImageRetagError(f"图片不存在：{value}")

    mime = _guess_mime(value)

    with open(value, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime};base64,{b64}"


def _extract_provider_api_info(provider) -> Tuple[str, str, str]:
    p_conf = getattr(provider, "provider_config", {}) or {}

    base_url = (
        getattr(provider, "api_base", "")
        or p_conf.get("api_base")
        or p_conf.get("api_base_url")
        or p_conf.get("base_url")
        or ""
    )

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
        or p_conf.get("model_name")
        or p_conf.get("default_model")
        or ""
    )

    base_url = str(base_url or "").strip().rstrip("/")
    api_key = str(api_key or "").strip()
    model = str(model or "").strip()

    return base_url, api_key, model


def _extract_error_message(text: str) -> str:
    text = text or ""

    try:
        data = json.loads(text)
    except Exception:
        return text.strip()[:500] or "API 请求失败"

    if isinstance(data, dict):
        err = data.get("error")

        if isinstance(err, str):
            return err

        if isinstance(err, dict):
            for k in ("message", "msg", "detail", "error"):
                v = err.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

        for k in ("message", "msg", "detail", "reason"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    return text.strip()[:500] or "API 请求失败"


def _extract_chat_content(data: Any) -> str:
    if isinstance(data, str):
        return data

    if not isinstance(data, dict):
        return str(data)

    choices = data.get("choices")

    if isinstance(choices, list) and choices:
        parts = []

        for choice in choices:
            if not isinstance(choice, dict):
                continue

            message = choice.get("message")

            if isinstance(message, dict):
                content = message.get("content")

                if isinstance(content, str):
                    parts.append(content)

                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str):
                                parts.append(text)

            text = choice.get("text")

            if isinstance(text, str):
                parts.append(text)

        if parts:
            return "\n".join(parts).strip()

    for k in ("content", "text", "message", "result", "output", "caption"):
        v = data.get(k)
        if isinstance(v, str):
            return v

    return json.dumps(data, ensure_ascii=False)


class ImageRetagger:
    def __init__(self, config, context) -> None:
        self.config = config
        self.context = context
        self.timeout = 180

    async def retag(self, image_path_or_url: str, user_hint: str = "") -> str:
        provider_id = getattr(self.config, "provider_id", "") or ""

        if not provider_id:
            raise ImageRetagError("未配置图片反推接口提供商")

        try:
            provider = self.context.get_provider_by_id(provider_id)
        except Exception as e:
            raise ImageRetagError(f"获取图片反推接口提供商失败：{e}") from e

        if not provider:
            raise ImageRetagError(f"找不到图片反推接口提供商：{provider_id}")

        base_url, api_key, model = _extract_provider_api_info(provider)

        if not base_url:
            raise ImageRetagError(f"图片反推提供商 {provider_id} 缺少 API Base")

        if not api_key:
            raise ImageRetagError(f"图片反推提供商 {provider_id} 缺少 API Key")

        if not model:
            raise ImageRetagError(f"图片反推提供商 {provider_id} 缺少模型配置")

        endpoint = f"{base_url}/chat/completions"
        image_url = await _image_to_data_url(image_path_or_url)

        system_prompt = (
            "You are an expert anime image tagger for NovelAI image generation. "
            "Analyze the image and output only English Danbooru/NovelAI tags. "
            "Use comma-separated tags only. "
            "Do not output explanations. Do not output markdown. "
            "Do not output Chinese, Japanese, emoji, or non-ASCII characters. "
            "Focus on subject, hair, eyes, clothing, pose, expression, background, composition, lighting, camera angle, style, and quality tags."
        )

        user_text = (
            "Convert this image into NovelAI / Danbooru image generation tags. "
            "Output tags only, separated by commas."
        )

        if user_hint:
            user_text += f"\nAdditional user hint to merge into the tag result: {user_hint}"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": user_text,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_url,
                            },
                        },
                    ],
                },
            ],
            "stream": False,
            "temperature": 0.2,
        }

        logger.info(
            f"[BestNAI/ImageRetag] endpoint={endpoint}, provider={provider_id}, model={model}"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        timeout = aiohttp.ClientTimeout(total=self.timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                ) as resp:
                    text = await resp.text()

                    if resp.status < 200 or resp.status >= 300:
                        message = _extract_error_message(text)
                        raise ImageRetagError(message)

                    try:
                        data = json.loads(text)
                    except Exception as e:
                        raise ImageRetagError(f"反推接口返回非 JSON：{text[:500]}") from e

        except ImageRetagError:
            raise

        except TimeoutError as e:
            raise ImageRetagError("图片反推请求超时") from e

        except aiohttp.ClientError as e:
            raise ImageRetagError(f"图片反推网络请求失败：{e}") from e

        except Exception as e:
            logger.exception(f"[BestNAI/ImageRetag] 调用提供商反推失败: {e}")
            raise ImageRetagError(f"图片反推失败：{e}") from e

        content = _extract_chat_content(data)
        tags = _clean_tags(content)

        if not tags:
            logger.warning(f"[BestNAI/ImageRetag] 空反推结果，raw={str(data)[:1000]}")
            raise ImageRetagError("图片反推结果为空")

        logger.info(f"[BestNAI/ImageRetag] tags={tags[:500]}")

        return tags

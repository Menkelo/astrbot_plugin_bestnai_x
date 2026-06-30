from __future__ import annotations

import base64
import json
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from astrbot.api import logger

from ..models.config import GenerationConfig, PluginConfig


class GenerationError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class APIKeyError(GenerationError):
    pass


class QuotaExceededError(GenerationError):
    pass


class RateLimitError(GenerationError):
    pass


class ServerBusyError(GenerationError):
    pass


class ImageGenerator:
    def __init__(self, config: PluginConfig) -> None:
        self.config = config
        self.timeout = 300

    async def generate(
        self,
        prompt: str,
        gen_config: GenerationConfig,
    ) -> List[Tuple[str, bytes]]:
        if not self.config.api_url or not self.config.api_key:
            raise APIKeyError("未配置生图 API 地址或 API Key")

        api_base = self.config.api_url.rstrip("/")
        api_key = self.config.api_key.strip()

        if getattr(self.config, "use_manual_api", False):
            logger.info("[BestNAI] 当前为手动生图 API 模式，直接使用 /chat/completions")
            return await self._generate_by_chat_endpoint(
                api_base=api_base,
                api_key=api_key,
                prompt=prompt,
                gen_config=gen_config,
            )

        try:
            return await self._generate_by_images_endpoint(
                api_base=api_base,
                api_key=api_key,
                prompt=prompt,
                gen_config=gen_config,
            )

        except GenerationError as e:
            if self._should_fallback_to_chat(e):
                logger.warning(
                    f"[BestNAI] /images/generations 不可用，尝试 fallback 到 /chat/completions：{e.message}"
                )

                return await self._generate_by_chat_endpoint(
                    api_base=api_base,
                    api_key=api_key,
                    prompt=prompt,
                    gen_config=gen_config,
                )

            raise

    async def _generate_by_images_endpoint(
        self,
        api_base: str,
        api_key: str,
        prompt: str,
        gen_config: GenerationConfig,
    ) -> List[Tuple[str, bytes]]:
        endpoint = f"{api_base}/images/generations"

        payload = gen_config.to_api_params(prompt)

        seed = random.randint(1, 2_147_483_647)
        payload["seed"] = seed

        logger.info(f"[BestNAI] endpoint={endpoint}")
        logger.info(f"[BestNAI] timeout={self.timeout}s")
        logger.info(f"[BestNAI] 发出参数 prompt={prompt}")
        logger.info(
            "[BestNAI] 发出参数 "
            f"model={payload.get('model')}, "
            f"size={payload.get('size')}, "
            f"steps={payload.get('steps')}, "
            f"scale={payload.get('scale')}, "
            f"sampler={payload.get('sampler')}, "
            f"quality={payload.get('quality')}, "
            f"uc_preset={payload.get('uc_preset')}, "
            f"seed={seed}"
        )

        data = await self._post_json(
            endpoint=endpoint,
            api_key=api_key,
            payload=payload,
        )

        images = await self._extract_images_from_response(data, api_key=api_key)

        if not images:
            raise GenerationError("API 未返回图片")

        return images

    async def _generate_by_chat_endpoint(
        self,
        api_base: str,
        api_key: str,
        prompt: str,
        gen_config: GenerationConfig,
    ) -> List[Tuple[str, bytes]]:
        endpoint = f"{api_base}/chat/completions"

        seed = random.randint(1, 2_147_483_647)
        size_array = [int(gen_config.width), int(gen_config.height)]

        user_payload = {
            "prompt": prompt,
            "model": gen_config.model,
            "size": size_array,
            "width": int(gen_config.width),
            "height": int(gen_config.height),
            "steps": int(gen_config.steps),
            "scale": float(gen_config.scale),
            "sampler": gen_config.sampler,
            "noise_schedule": gen_config.noise_schedule,
            "image_format": gen_config.image_format,
            "n_samples": 1,
            "seed": seed
        }

        if gen_config.negative_prompt:
            user_payload["negative_prompt"] = gen_config.negative_prompt

        if gen_config.uc_preset:
            user_payload["uc_preset"] = gen_config.uc_preset

        payload = {
            "model": gen_config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an image generation endpoint. "
                        "Generate one image and return image URL, markdown image, data URL, or base64."
                    )
                },
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False)
                }
            ],
            "stream": False
        }

        logger.info(f"[BestNAI] chat_endpoint={endpoint}")
        logger.info(f"[BestNAI] timeout={self.timeout}s")
        logger.info(f"[BestNAI] chat 生图 prompt={prompt}")
        logger.info(
            "[BestNAI] chat 生图参数 "
            f"model={gen_config.model}, "
            f"size={size_array}, "
            f"steps={gen_config.steps}, "
            f"scale={gen_config.scale}, "
            f"sampler={gen_config.sampler}, "
            f"seed={seed}"
        )

        data = await self._post_json(
            endpoint=endpoint,
            api_key=api_key,
            payload=payload,
        )

        images = await self._extract_images_from_response(data, api_key=api_key)

        if not images:
            content = self._extract_chat_content(data)
            logger.warning(f"[BestNAI] chat/completions 未解析到图片，content={content[:500]}")
            raise GenerationError("chat/completions 未返回可解析图片")

        return images

    async def _post_json(
        self,
        endpoint: str,
        api_key: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
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
                        message = self._extract_error_message_from_text(text)
                        self._raise_for_status(resp.status, message)

                    try:
                        return json.loads(text)
                    except Exception as e:
                        raise GenerationError(f"API 返回非 JSON 内容：{text[:300]}") from e

        except GenerationError:
            raise

        except aiohttp.ClientResponseError as e:
            raise GenerationError(f"HTTP 请求失败：{e.status} {e.message}", e.status) from e

        except aiohttp.ClientConnectorError as e:
            raise GenerationError(f"无法连接 API：{e}") from e

        except TimeoutError as e:
            raise ServerBusyError("生图请求超时，请稍后重试") from e

        except aiohttp.ClientError as e:
            raise GenerationError(f"网络请求失败：{e}") from e

        except Exception as e:
            raise GenerationError(f"请求生图接口失败：{e}") from e

    def _raise_for_status(self, status: int, message: str) -> None:
        msg = message or f"HTTP {status}"

        if status in (401, 403):
            raise APIKeyError(msg, status)

        if status == 429:
            lower = msg.lower()

            if any(x in lower for x in ["quota", "余额", "insufficient", "credit"]):
                raise QuotaExceededError(msg, status)

            raise RateLimitError(msg, status)

        if status in (500, 502, 503, 504):
            raise ServerBusyError(msg, status)

        raise GenerationError(msg, status)

    def _extract_error_message_from_text(self, text: str) -> str:
        text = text or ""

        try:
            data = json.loads(text)
        except Exception:
            return text.strip()[:500] or "API 请求失败"

        return self._extract_error_message(data) or text.strip()[:500] or "API 请求失败"

    def _extract_error_message(self, data: Any) -> str:
        if isinstance(data, str):
            return data.strip()

        if isinstance(data, dict):
            err = data.get("error")

            if isinstance(err, str):
                return err.strip()

            if isinstance(err, dict):
                for k in ("message", "msg", "detail", "error"):
                    v = err.get(k)
                    if isinstance(v, str) and v.strip():
                        return v.strip()

            for k in ("message", "msg", "detail", "reason"):
                v = data.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

        return ""

    def _should_fallback_to_chat(self, e: GenerationError) -> bool:
        text = (e.message or "").lower()
        status = getattr(e, "status_code", None)

        if status in (400, 404, 405, 501):
            status_match = True
        else:
            status_match = False

        keywords = [
            "未开放",
            "接口不支持",
            "能力或接口不支持",
            "not support",
            "not supported",
            "unsupported",
            "not implemented",
            "is not implemented",
            "images/generations is not implemented",
            "openai-compatible /v1/images/generations is not implemented",
            "use /v1/chat/completions",
            "chat/completions for text-to-image",
            "text-to-image instead",
            "invalid endpoint",
            "unknown endpoint",
            "not found",
            "no route",
            "route not found",
            "method not allowed",
        ]

        keyword_match = any(k.lower() in text for k in keywords)

        return status_match and keyword_match or keyword_match

    async def _extract_images_from_response(
        self,
        data: Any,
        api_key: str,
    ) -> List[Tuple[str, bytes]]:
        images: List[Tuple[str, bytes]] = []

        direct_images = self._extract_images_from_json_tree(data)

        for img_format, img_bytes in direct_images:
            if img_bytes:
                images.append((img_format, img_bytes))

        urls = self._extract_urls_from_json_tree(data)

        for url in urls:
            try:
                img_bytes, img_format = await self._download_image(url, api_key=api_key)
                if img_bytes:
                    images.append((img_format, img_bytes))
            except Exception as e:
                logger.warning(f"[BestNAI] 下载图片失败 url={url}: {e}")

        if images:
            return images

        content = self._extract_chat_content(data)

        if content:
            content_images = await self._extract_images_from_text(content, api_key=api_key)
            images.extend(content_images)

        return images

    def _extract_images_from_json_tree(self, data: Any) -> List[Tuple[str, bytes]]:
        images: List[Tuple[str, bytes]] = []

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = str(key).lower()

                    if key_lower in {
                        "b64_json",
                        "base64",
                        "image_base64",
                        "image",
                        "data",
                    } and isinstance(value, str):
                        parsed = self._try_decode_image_base64(value)
                        if parsed:
                            images.append(parsed)

                    else:
                        walk(value)

            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(data)

        return images

    def _extract_urls_from_json_tree(self, data: Any) -> List[str]:
        urls: List[str] = []

        def add_url(value: str) -> None:
            value = value.strip()

            if not value:
                return

            if value.startswith("http://") or value.startswith("https://"):
                if value not in urls:
                    urls.append(value)

        def walk(obj: Any) -> None:
            if isinstance(obj, dict):
                for key, value in obj.items():
                    key_lower = str(key).lower()

                    if key_lower in {
                        "url",
                        "image_url",
                        "image",
                        "output_url",
                    } and isinstance(value, str):
                        add_url(value)

                    else:
                        walk(value)

            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

            elif isinstance(obj, str):
                for url in self._find_image_urls(obj):
                    add_url(url)

        walk(data)

        return urls

    def _extract_chat_content(self, data: Any) -> str:
        if not isinstance(data, dict):
            return ""

        choices = data.get("choices")

        if isinstance(choices, list) and choices:
            parts: List[str] = []

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
                                if isinstance(item.get("text"), str):
                                    parts.append(item["text"])

                                image_url = item.get("image_url")

                                if isinstance(image_url, dict) and isinstance(image_url.get("url"), str):
                                    parts.append(image_url["url"])

                                elif isinstance(image_url, str):
                                    parts.append(image_url)

                delta = choice.get("delta")

                if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                    parts.append(delta["content"])

                text = choice.get("text")

                if isinstance(text, str):
                    parts.append(text)

            return "\n".join(parts).strip()

        return ""

    async def _extract_images_from_text(
        self,
        text: str,
        api_key: str,
    ) -> List[Tuple[str, bytes]]:
        images: List[Tuple[str, bytes]] = []

        text = text or ""

        # 有些接口会在 content 里返回 JSON 字符串
        json_candidates = self._find_json_candidates(text)

        for candidate in json_candidates:
            try:
                data = json.loads(candidate)
            except Exception:
                continue

            images.extend(await self._extract_images_from_response(data, api_key=api_key))

        # data:image/png;base64,...
        for data_url in self._find_data_urls(text):
            parsed = self._try_decode_image_base64(data_url)
            if parsed:
                images.append(parsed)

        # 普通 base64
        parsed = self._try_decode_image_base64(text.strip())
        if parsed:
            images.append(parsed)

        # markdown / 普通 URL
        for url in self._find_image_urls(text):
            try:
                img_bytes, img_format = await self._download_image(url, api_key=api_key)
                if img_bytes:
                    images.append((img_format, img_bytes))
            except Exception as e:
                logger.warning(f"[BestNAI] 下载 chat 图片失败 url={url}: {e}")

        return images

    def _find_json_candidates(self, text: str) -> List[str]:
        candidates: List[str] = []

        text = text.strip()

        if not text:
            return candidates

        if text.startswith("{") and text.endswith("}"):
            candidates.append(text)

        if text.startswith("[") and text.endswith("]"):
            candidates.append(text)

        fenced = re.findall(
            r"```(?:json)?\s*([\s\S]*?)\s*```",
            text,
            flags=re.IGNORECASE,
        )

        for item in fenced:
            item = item.strip()

            if item.startswith("{") or item.startswith("["):
                candidates.append(item)

        return candidates

    def _find_data_urls(self, text: str) -> List[str]:
        pattern = r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=\s]+"
        return [m.group(0).strip() for m in re.finditer(pattern, text)]

    def _find_image_urls(self, text: str) -> List[str]:
        urls: List[str] = []

        # markdown 图片
        for m in re.finditer(r"!\[[^\]]*\]\((https?://[^\s)]+)\)", text):
            url = m.group(1).strip()
            if url not in urls:
                urls.append(url)

        # 普通 URL
        for m in re.finditer(r"https?://[^\s\]>)\"']+", text):
            url = m.group(0).strip().rstrip(".,，。)")
            if url not in urls:
                urls.append(url)

        return urls

    def _try_decode_image_base64(self, value: str) -> Optional[Tuple[str, bytes]]:
        if not isinstance(value, str):
            return None

        text = value.strip()

        if not text:
            return None

        if text.startswith("data:image/"):
            m = re.match(
                r"data:image/([a-zA-Z0-9.+-]+);base64,(.+)",
                text,
                flags=re.DOTALL,
            )

            if not m:
                return None

            img_format = m.group(1).lower()
            b64 = m.group(2).strip()

        else:
            img_format = "png"
            b64 = text

        # 避免把普通文本误判成 base64
        if len(b64) < 100:
            return None

        b64 = re.sub(r"\s+", "", b64)

        if not re.fullmatch(r"[A-Za-z0-9+/=]+", b64):
            return None

        try:
            img_bytes = base64.b64decode(b64, validate=False)
        except Exception:
            return None

        if not self._looks_like_image(img_bytes):
            return None

        detected = self._detect_image_format(img_bytes)

        return detected, img_bytes

    def _looks_like_image(self, img_bytes: bytes) -> bool:
        if not img_bytes or len(img_bytes) < 16:
            return False

        return (
            img_bytes.startswith(b"\x89PNG\r\n\x1a\n")
            or img_bytes.startswith(b"\xff\xd8\xff")
            or img_bytes.startswith(b"RIFF")
            or img_bytes.startswith(b"GIF87a")
            or img_bytes.startswith(b"GIF89a")
        )

    def _detect_image_format(self, img_bytes: bytes) -> str:
        if img_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"

        if img_bytes.startswith(b"\xff\xd8\xff"):
            return "jpg"

        if img_bytes.startswith(b"RIFF"):
            return "webp"

        if img_bytes.startswith(b"GIF87a") or img_bytes.startswith(b"GIF89a"):
            return "gif"

        return "png"

    async def _download_image(
        self,
        url: str,
        api_key: str = "",
    ) -> Tuple[bytes, str]:
        headers = {
            "Accept": "image/*,*/*",
        }

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        timeout = aiohttp.ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status < 200 or resp.status >= 300:
                    text = await resp.text()
                    raise GenerationError(
                        f"下载图片失败 HTTP {resp.status}: {text[:200]}",
                        resp.status,
                    )

                content_type = resp.headers.get("Content-Type", "").lower()
                img_bytes = await resp.read()

        if "jpeg" in content_type or "jpg" in content_type:
            img_format = "jpg"
        elif "webp" in content_type:
            img_format = "webp"
        elif "gif" in content_type:
            img_format = "gif"
        else:
            img_format = self._detect_image_format(img_bytes)

        return img_bytes, img_format

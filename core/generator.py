from __future__ import annotations

import asyncio
import base64
import json
import random
import re
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from astrbot.api import logger

from .api_errors import describe_api_error
from ..constants import MAX_SEED, normalize_nai_seed
from ..models.config import GenerationConfig, PluginConfig


class GenerationResult(NamedTuple):
    """一次生图的产物。seed 要回传给前端展示与复现。"""

    images: List[Tuple[str, bytes]]
    seed: int


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
        self.timeout = 180

    @staticmethod
    def _endpoint(api_base: str, path: str) -> str:
        """拼接接口地址，api_base 未带 /v1 时自动补上。

        与 translator / safety / image_retagger 的拼接规则保持一致。
        """
        base = (api_base or "").rstrip("/")

        if not base.endswith("/v1"):
            base = f"{base}/v1"

        return f"{base}/{path.lstrip('/')}"

    async def generate(
        self,
        prompt: str,
        gen_config: GenerationConfig,
        seed: Optional[int] = None,
        api_url: str = "",
        api_key: str = "",
    ) -> "GenerationResult":
        # 模型分档后允许按次指定端点（如 /nai5 走 V5 提供商）；
        # 缺省回落插件主提供商
        base_url = (api_url or self.config.api_url).rstrip("/")
        access_key = (api_key or self.config.api_key).strip()

        if not base_url or not access_key:
            raise APIKeyError("生图接口提供商未就绪，请检查提供商的 API 地址与 Key")

        api_base = base_url

        # 种子在这里定一次，两条端点路径和 fallback 共用同一个值。
        # 以前两个方法各自随机，fallback 后拿到的图和日志里的种子对不上。
        resolved_seed = self._resolve_seed(seed)

        try:
            images = await self._generate_by_images_endpoint(
                api_base=api_base,
                api_key=access_key,
                prompt=prompt,
                gen_config=gen_config,
                seed=resolved_seed,
            )
            return GenerationResult(images=images, seed=resolved_seed)

        except GenerationError as e:
            if self._should_fallback_to_chat(e):
                logger.warning(
                    f"[BestNAI] /images/generations 不可用，尝试 fallback 到 /chat/completions：{e.message}"
                )

                images = await self._generate_by_chat_endpoint(
                    api_base=api_base,
                    api_key=access_key,
                    prompt=prompt,
                    gen_config=gen_config,
                    seed=resolved_seed,
                )
                return GenerationResult(images=images, seed=resolved_seed)

            raise

    @staticmethod
    def _resolve_seed(seed: Optional[int]) -> int:
        """指定了合法种子就复用，否则随机一个。"""
        value = normalize_nai_seed(seed)
        if value is not None:
            return value

        return random.randint(1, MAX_SEED)

    async def _generate_by_images_endpoint(
        self,
        api_base: str,
        api_key: str,
        prompt: str,
        gen_config: GenerationConfig,
        seed: int,
    ) -> List[Tuple[str, bytes]]:
        endpoint = self._endpoint(api_base, "images/generations")

        payload = gen_config.to_api_params(prompt)
        payload["seed"] = seed
        # Some OpenAI-compatible NAI relays document the same controls under
        # SD-style aliases. Standard servers ignore unknown extension fields;
        # relays that whitelist only these aliases can still preserve the
        # requested guidance and deterministic seed.
        payload["guidance_scale"] = float(gen_config.scale)
        payload["cfg_scale"] = float(gen_config.scale)
        payload["random_seed"] = seed

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

        images = await self._extract_images_from_response(data, api_key=api_key, api_base=api_base)

        if not images:
            raise GenerationError("API 未返回图片")

        return images

    async def _generate_by_chat_endpoint(
        self,
        api_base: str,
        api_key: str,
        prompt: str,
        gen_config: GenerationConfig,
        seed: int,
    ) -> List[Tuple[str, bytes]]:
        endpoint = self._endpoint(api_base, "chat/completions")

        user_payload = {
            "parameter_protocol": "novelai_generation_v1",
            "prompt": prompt,
            "model": gen_config.model,
            "size": f"{gen_config.width}x{gen_config.height}",
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

        # A few OpenAI-compatible image relays expose chat as their transport
        # but translate common SD names instead of the NovelAI ``scale`` /
        # ``seed`` names. Keep the canonical fields above and provide aliases
        # only in this text-protocol fallback; the native images endpoint is
        # never sent these extras.
        user_payload.update(
            {
                "guidance_scale": float(gen_config.scale),
                "cfg_scale": float(gen_config.scale),
                "random_seed": seed,
            }
        )

        if gen_config.negative_prompt:
            user_payload["negative_prompt"] = gen_config.negative_prompt

        if gen_config.uc_preset:
            user_payload["uc_preset"] = gen_config.uc_preset

        if gen_config.characters:
            user_payload["characters"] = gen_config.characters
            user_payload["use_coords"] = gen_config.use_coords
            user_payload["use_order"] = gen_config.use_order

        payload = {
            "model": gen_config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an image generation endpoint. The JSON object in the user message "
                        "is the authoritative NovelAI generation request. Preserve every supported "
                        "parameter exactly, especially model, width, height, steps, scale, sampler, "
                        "noise_schedule, seed, negative_prompt, cfg_rescale, and characters. "
                        "Do not silently replace supplied values with defaults. If this relay cannot "
                        "honor a parameter, return an explicit error instead of ignoring it. "
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
            f"size={gen_config.width}x{gen_config.height}, "
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

        images = await self._extract_images_from_response(data, api_key=api_key, api_base=api_base)

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

        except (asyncio.TimeoutError, TimeoutError) as e:
            raise ServerBusyError("生图请求超时，请稍后重试") from e

        except aiohttp.ClientError as e:
            raise GenerationError(f"网络请求失败：{e}") from e

        except Exception as e:
            raise GenerationError(f"请求生图接口失败：{e}") from e

    def _raise_for_status(self, status: int, message: str) -> None:
        msg = message or f"HTTP {status}"
        lowered = msg.lower()
        if any(
            marker in lowered
            for marker in (
                "cloudflare",
                "origin web server",
                "invalid or incomplete response",
                "bad gateway",
                "gateway time-out",
                "error 52",
            )
        ):
            msg = describe_api_error(msg, "生图")

        if status in (401, 403):
            raise APIKeyError(msg, status)

        if status == 429:
            lower = msg.lower()

            if any(x in lower for x in ["quota", "余额", "insufficient", "credit"]):
                raise QuotaExceededError(msg, status)

            raise RateLimitError(msg, status)

        if status in (500, 502, 503, 504, 520, 521, 522, 523, 524):
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

        # 404 / 405 / 501 表示该路由不存在或不被支持，值得改走 chat/completions。
        # 400 不算，它通常意味着参数有问题，重试 chat 也不会成功。
        status_match = status in (404, 405, 501)

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

        return status_match or keyword_match

    async def _extract_images_from_response(
        self,
        data: Any,
        api_key: str,
        api_base: str = "",
    ) -> List[Tuple[str, bytes]]:
        images: List[Tuple[str, bytes]] = []

        direct_images = self._extract_images_from_json_tree(data)

        for img_format, img_bytes in direct_images:
            if img_bytes:
                images.append((img_format, img_bytes))

        urls = self._extract_urls_from_json_tree(data)

        for url in urls:
            try:
                img_bytes, img_format = await self._download_image(url, api_key=api_key, api_base=api_base)
                if img_bytes:
                    images.append((img_format, img_bytes))
            except Exception as e:
                logger.warning(f"[BestNAI] 下载图片失败 url={url}: {e}")

        if images:
            return images

        content = self._extract_chat_content(data)

        if content:
            content_images = await self._extract_images_from_text(content, api_key=api_key, api_base=api_base)
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
        api_base: str = "",
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
                img_bytes, img_format = await self._download_image(url, api_key=api_key, api_base=api_base)
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

    def _is_api_host(self, url: str, api_base: str = "") -> bool:
        """判断 url 是否指向本次请求的生图 API 主机。

        模型输出里的链接是不可信的：`_find_image_urls` 会抓出任意 http(s) 地址，
        只有回到 API 自己的主机时才允许带上 Authorization 头，
        否则 API Key 会被送给模型指定的任意第三方。
        分模型提供商后以当次请求的端点为准，缺省回落主提供商。
        """
        try:
            target = urlparse(url)
            configured = urlparse(api_base or self.config.api_url or "")
        except Exception:
            return False

        if not target.hostname or not configured.hostname:
            return False

        def effective_port(parsed) -> int:
            if parsed.port:
                return parsed.port
            return 443 if parsed.scheme == "https" else 80

        return (
            target.scheme in ("http", "https")
            and target.hostname.lower() == configured.hostname.lower()
            and effective_port(target) == effective_port(configured)
        )

    async def _download_image(
        self,
        url: str,
        api_key: str = "",
        api_base: str = "",
    ) -> Tuple[bytes, str]:
        headers = {
            "Accept": "image/*,*/*",
        }

        if api_key and self._is_api_host(url, api_base):
            headers["Authorization"] = f"Bearer {api_key}"
        elif api_key:
            logger.info(
                f"[BestNAI] 图片链接不属于已配置的 API 主机，下载时不发送 API Key：{url}"
            )

        timeout = aiohttp.ClientTimeout(total=self.timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status < 200 or resp.status >= 300:
                    text = await resp.text()
                    raw = f"HTTP {resp.status}: {text[:200]}"
                    lowered = raw.lower()
                    if any(
                        marker in lowered
                        for marker in (
                            "cloudflare",
                            "origin web server",
                            "invalid or incomplete response",
                            "bad gateway",
                            "gateway time-out",
                            "error 52",
                        )
                    ):
                        raise GenerationError(describe_api_error(raw, "图片下载"), resp.status)
                    raise GenerationError(
                        f"下载图片失败 {raw}",
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

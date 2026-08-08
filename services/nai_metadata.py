"""读取 NovelAI 写在 PNG 里的生成参数。

NovelAI 把生成参数放在 PNG 的 tEXt 块里：`Comment` 是一段 JSON，
含 seed / steps / scale / sampler 等；`Description` 通常是正向提示词。

要点：这些信息**只在原始 PNG 里存在**。图片一旦被重新编码
（转 JPEG / WebP，或被平台压缩后重存），tEXt 块就没了。
所以只有画布上传原图这条路能读到，QQ 收到的图基本读不到。
"""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp
from PIL import Image as PILImage

try:  # Support both plugin-package imports and direct ``services`` imports.
    from ..constants import normalize_nai_seed
except ImportError:  # pragma: no cover - compatibility path for standalone tests
    from constants import normalize_nai_seed


# Comment JSON 里我们关心的数值字段
_INT_FIELDS = ("seed", "steps", "width", "height")
_FLOAT_FIELDS = ("scale", "cfg_rescale")


def _coerce_int(value: Any) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None

    return number if number > 0 else None


def _coerce_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    return number


def parse_nai_info(info: Dict[str, Any]) -> Dict[str, Any]:
    """从 PIL 的 image.info 里解析出 NovelAI 生成参数。

    解析不出来就返回空 dict，调用方按「没有元数据」处理即可。
    """
    if not isinstance(info, dict):
        return {}

    result: Dict[str, Any] = {}

    raw_comment = info.get("Comment")

    if isinstance(raw_comment, (bytes, bytearray)):
        try:
            raw_comment = raw_comment.decode("utf-8", errors="ignore")
        except Exception:
            raw_comment = ""

    if isinstance(raw_comment, str) and raw_comment.strip():
        try:
            comment = json.loads(raw_comment)
        except Exception:
            comment = None

        if isinstance(comment, dict):
            for key in _INT_FIELDS:
                number = (
                    normalize_nai_seed(comment.get(key))
                    if key == "seed"
                    else _coerce_int(comment.get(key))
                )
                if number is not None:
                    result[key] = number

            for key in _FLOAT_FIELDS:
                number = _coerce_float(comment.get(key))
                if number is not None:
                    result[key] = number

            for key in ("sampler", "noise_schedule"):
                value = comment.get(key)
                if isinstance(value, str) and value.strip():
                    result[key] = value.strip()

            for key in ("prompt", "uc"):
                value = comment.get(key)
                if isinstance(value, str) and value.strip():
                    result["prompt" if key == "prompt" else "negativePrompt"] = value.strip()

    # Comment 里没有 prompt 时退回 Description，NovelAI 两处都会写
    if "prompt" not in result:
        description = info.get("Description")
        if isinstance(description, str) and description.strip():
            result["prompt"] = description.strip()

    software = info.get("Software")
    if isinstance(software, str) and software.strip():
        result["software"] = software.strip()

    return result


def read_image_generation_info(path: str | Path) -> Dict[str, Any]:
    """读取图片文件里的生成参数，读不到返回空 dict。"""
    try:
        with PILImage.open(Path(path)) as image:
            # 非 PNG 一律没有 tEXt 块，省掉后续解析
            if str(image.format or "").upper() != "PNG":
                return {}
            return parse_nai_info(dict(image.info or {}))
    except Exception:
        return {}


async def read_image_generation_info_any(source: str | Path) -> Dict[str, Any]:
    """Read NovelAI metadata from a local file or a remote image URL.

    QQ adapters commonly expose an image as a URL, while the canvas upload
    path usually has a local file.  Keeping the URL fetch here lets both
    entry-points share the same metadata shortcut without making callers
    duplicate PNG parsing or block the event loop on local IO.
    """
    value = str(source or "").strip()
    if not value:
        return {}

    if not (value.startswith("http://") or value.startswith("https://")):
        return await asyncio.to_thread(read_image_generation_info, value)

    try:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "image/png,image/*;q=0.8,*/*;q=0.1"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(value, headers=headers) as response:
                if response.status < 200 or response.status >= 300:
                    return {}
                data = await response.read()

        with PILImage.open(BytesIO(data)) as image:
            if str(image.format or "").upper() != "PNG":
                return {}
            return parse_nai_info(dict(image.info or {}))
    except Exception:
        return {}

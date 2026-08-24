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
from typing import Any, Dict, List, Optional

import aiohttp
from PIL import Image as PILImage

try:  # Support both plugin-package imports and direct ``services`` imports.
    from ..constants import normalize_nai_seed
except ImportError:  # pragma: no cover - compatibility path for standalone tests
    from constants import normalize_nai_seed


# Comment JSON 里我们关心的数值字段
_INT_FIELDS = ("seed", "steps", "width", "height")
_FLOAT_FIELDS = ("scale", "cfg_rescale")
# V4+ 角色提示词数量上限，仅用于防御异常数据；正常图片远少于此
_MAX_CHAR_CAPTIONS = 16


def _parse_char_captions(comment: Dict[str, Any]) -> List[Dict[str, Any]]:
    """读取 V4+ 元数据里的角色提示词。

    NovelAI 把多角色提示词放在 ``v4_prompt.caption.char_captions[]``，
    每项的 ``char_caption`` 是该角色的提示词文本，``centers[0].x/y``
    是 0~1 的中心点坐标；负面提示词在 ``v4_negative_prompt`` 里有
    平行的同序数组。这里按索引对齐取文本与坐标。
    """
    v4_prompt = comment.get("v4_prompt")
    if not isinstance(v4_prompt, dict):
        return []

    caption = v4_prompt.get("caption")
    if not isinstance(caption, dict):
        return []

    raw_captions = caption.get("char_captions")
    if not isinstance(raw_captions, list):
        return []

    negative_captions: Any = None
    v4_negative = comment.get("v4_negative_prompt")
    if isinstance(v4_negative, dict) and isinstance(v4_negative.get("caption"), dict):
        negative_captions = v4_negative["caption"].get("char_captions")

    def negative_at(index: int) -> str:
        if not isinstance(negative_captions, list) or index >= len(negative_captions):
            return ""
        item = negative_captions[index]
        text = item.get("char_caption") if isinstance(item, dict) else item
        return text.strip() if isinstance(text, str) else ""

    result: List[Dict[str, Any]] = []
    for index, item in enumerate(raw_captions[:_MAX_CHAR_CAPTIONS]):
        text = item.get("char_caption") if isinstance(item, dict) else None
        if not isinstance(text, str) or not text.strip():
            continue

        center_x: Any = None
        center_y: Any = None
        if isinstance(item, dict) and isinstance(item.get("centers"), list) and item["centers"]:
            first = item["centers"][0]
            if isinstance(first, dict):
                center_x = first.get("x")
                center_y = first.get("y")

        entry: Dict[str, Any] = {
            "prompt": text.strip(),
            "negative": negative_at(index),
            "x": center_x,
            "y": center_y,
        }
        result.append(entry)

    return result


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

            char_captions = _parse_char_captions(comment)
            if char_captions:
                result["characterPrompts"] = char_captions
                v4_prompt = comment.get("v4_prompt")
                if isinstance(v4_prompt, dict):
                    result["characterUseCoords"] = bool(v4_prompt.get("use_coords", False))
                    result["characterUseOrder"] = bool(v4_prompt.get("use_order", True))

    # Comment 里没有 prompt 时退回 Description，NovelAI 两处都会写
    if "prompt" not in result:
        description = info.get("Description")
        if isinstance(description, str) and description.strip():
            result["prompt"] = description.strip()

    software = info.get("Software")
    if isinstance(software, str) and software.strip():
        result["software"] = software.strip()

    return result


def is_trusted_nai_generation_info(info: Dict[str, Any]) -> bool:
    """Return whether ``info['prompt']`` is credible NovelAI metadata.

    PNG ``Description`` is a generic text field used by many applications, so
    its presence alone must not bypass the vision retagger.  A valid seed is
    sufficient, as is an explicit NovelAI software marker.  For seedless NAI
    files, require at least two generation-specific fields and one strong NAI
    marker such as sampler, negative prompt, or noise schedule.
    """

    if not isinstance(info, dict) or not str(info.get("prompt") or "").strip():
        return False

    if normalize_nai_seed(info.get("seed")) is not None:
        return True

    software = str(info.get("software") or "").strip().casefold()
    if "novelai" in software or "novel ai" in software:
        return True

    generation_fields = {
        key
        for key in (
            "steps",
            "width",
            "height",
            "scale",
            "sampler",
            "noise_schedule",
            "negativePrompt",
        )
        if info.get(key) not in (None, "")
    }
    strong_fields = {"sampler", "noise_schedule", "negativePrompt"}
    return len(generation_fields) >= 2 and bool(generation_fields & strong_fields)


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

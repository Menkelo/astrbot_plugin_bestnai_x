from __future__ import annotations

import os
import re
from io import BytesIO
from typing import Callable, Dict, Tuple

import aiohttp
from PIL import Image as PILImage


def read_local_image_size(path: str) -> Tuple[int, int]:
    path = str(path or "").strip()

    if path.startswith("file://"):
        path = path[7:]

    path = path.replace("\\", "/")

    while path.startswith("//"):
        path = path[1:]

    if not os.path.isabs(path):
        path = os.path.abspath(path)

    if not os.path.exists(path):
        raise ValueError(f"图片文件不存在：{path}")

    with PILImage.open(path) as im:
        return int(im.width), int(im.height)


async def read_url_image_size(url: str) -> Tuple[int, int]:
    timeout = aiohttp.ClientTimeout(total=60)

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "image/*,*/*",
    }

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status < 200 or resp.status >= 300:
                text = await resp.text()
                raise ValueError(f"下载图片失败 HTTP {resp.status}: {text[:120]}")

            data = await resp.read()

    with PILImage.open(BytesIO(data)) as im:
        return int(im.width), int(im.height)


async def read_image_size_any(image_src: str) -> Tuple[int, int]:
    src = str(image_src or "").strip()

    if not src:
        raise ValueError("图片为空")

    if src.startswith("http://") or src.startswith("https://"):
        return await read_url_image_size(src)

    return read_local_image_size(src)


def infer_ratio_label_from_size(width: int, height: int) -> str:
    width = int(width)
    height = int(height)

    if width <= 0 or height <= 0:
        return "2:3"

    target = width / height

    candidates = {
        "16:9": 16 / 9,
        "9:16": 9 / 16,
        "4:3": 4 / 3,
        "3:4": 3 / 4,
        "3:2": 3 / 2,
        "2:3": 2 / 3,
        "1:1": 1.0,
    }

    best = min(candidates.items(), key=lambda item: abs(item[1] - target))

    return best[0]


def prompt_has_explicit_ratio(
    prompt: str,
    ratio_aliases: list[str],
    ratio_presets: Dict[str, Tuple[int, int]],
    normalize_ratio_label: Callable[[str], str],
) -> bool:
    text = (prompt or "").strip()

    if not text:
        return False

    if re.search(r"(?:^|\s)--(?:ratio|size|ar)\s+", text, flags=re.IGNORECASE):
        return True

    if re.search(
        r"(^|[\s,，;；])\d{2,5}\s*[x×]\s*\d{2,5}(?=$|[\s,，;；])",
        text,
    ):
        return True

    if re.search(
        r"(^|[\s,，;；])(?:16:9|9:16|4:3|3:4|3:2|2:3|1:1)(?=$|[\s,，;；])",
        text,
    ):
        return True

    for alias in ratio_aliases:
        pattern = r"(^|[\s,，;；])" + re.escape(alias) + r"(?=$|[\s,，;；])"

        if re.search(pattern, text, flags=re.IGNORECASE):
            return True

    for m in re.finditer(r"[\[【]([^\]】]+)[\]】]", text):
        candidate = m.group(1).strip()
        normalized = normalize_ratio_label(candidate)

        if candidate in ratio_presets or normalized in ratio_presets:
            return True

        if re.fullmatch(r"\d{2,5}\s*[x×]\s*\d{2,5}", candidate):
            return True

    return False

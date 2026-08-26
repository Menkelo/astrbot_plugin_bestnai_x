"""读取 NovelAI / SD WebUI 写在图片里的生成参数。

NovelAI PNG 把生成参数放在 PNG 的 tEXt 块里：`Comment` 是一段 JSON，
含 seed / steps / scale / sampler 等；`Description` 通常是正向提示词。
NovelAI 官方导出的 JPEG / WebP（新版默认下载格式）把同一段 JSON 放在
EXIF `UserComment`（37510）里，前 8 字节是字符集标记。

SD WebUI 生成的图则把 `prompt\nNegative prompt: ...\nSteps: ...` 三段式
参数文本写进 PNG tEXt `parameters` 或 JPEG/WebP 的 EXIF `UserComment`。
以上格式全部支持（参考 spell.novelai.dev 的解析口径）。

要点：这些信息**只在原图里存在**。图片一旦被重新编码且工具没有搬移
元数据（QQ 压缩转发的图基本如此），tEXt 块和 EXIF 就没了。
"""

from __future__ import annotations

import asyncio
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from PIL import ExifTags, Image as PILImage

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
    """从 PIL 的 image.info 里解析出 NovelAI / SD WebUI 生成参数。

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
            result = _apply_comment_json(comment)

    # Comment 里没有 prompt 时尝试 SD WebUI 的 parameters tEXt 块
    if "prompt" not in result:
        for key, value in info.items():
            if str(key).lower() == "parameters" and isinstance(value, str) and value.strip():
                result = _apply_sd_parameters(value.strip())
                break

    # 最后退回 Description，NovelAI PNG 两处都会写
    if "prompt" not in result:
        description = info.get("Description")
        if isinstance(description, str) and description.strip():
            result["prompt"] = description.strip()

    software = info.get("Software")
    if isinstance(software, str) and software.strip():
        result["software"] = software.strip()

    return result


def parse_user_comment_text(text: str) -> Dict[str, Any]:
    """解析 EXIF UserComment 文本：NovelAI JSON 或 SD WebUI 参数文本。

    NovelAI 官方导出的 JPEG / WebP 把与 PNG ``Comment`` 相同的 JSON 写进
    EXIF ``UserComment``；SD WebUI 导出的 JPEG / WebP 则写三段式参数文本。
    两者都在这里识别，其余内容（随意写的 EXIF 备注）不当作生成参数。
    """

    value = str(text or "").strip()
    if not value:
        return {}

    if value.startswith("{"):
        try:
            comment = json.loads(value)
        except Exception:
            comment = None
        if isinstance(comment, dict):
            return _apply_comment_json(comment)
        return {}

    if "Steps:" in value or "Negative prompt: " in value:
        return _apply_sd_parameters(value)

    return {}


def _apply_comment_json(comment: Dict[str, Any]) -> Dict[str, Any]:
    """把 NovelAI Comment JSON 转成统一的生成参数 dict。"""

    result: Dict[str, Any] = {}

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

    return result


_SD_NEGATIVE_MARKER = "Negative prompt: "
_SD_STEPS_MARKER = "Steps: "


def _apply_sd_parameters(text: str) -> Dict[str, Any]:
    """解析 SD WebUI 的三段式参数文本。

    ``<prompt>\nNegative prompt: <uc>\nSteps: 20, Sampler: ..., Seed: ...``
    只提取与 NovelAI 参数对应的字段；无法识别前两个标记时不当作参数文本。
    """

    value = str(text or "").strip()
    if not value:
        return {}

    neg_idx = value.find(_SD_NEGATIVE_MARKER)
    steps_idx = value.find(_SD_STEPS_MARKER)
    if neg_idx < 0 and steps_idx < 0:
        return {}

    result: Dict[str, Any] = {}

    prompt_end = min(
        idx for idx in (neg_idx, steps_idx, len(value)) if idx >= 0
    )
    prompt = value[:prompt_end].strip()
    if prompt:
        result["prompt"] = prompt

    if neg_idx >= 0:
        neg_end = steps_idx if steps_idx > neg_idx else len(value)
        negative = value[neg_idx + len(_SD_NEGATIVE_MARKER) : neg_end].strip()
        if negative:
            result["negativePrompt"] = negative

    if steps_idx >= 0:
        entries: Dict[str, str] = {}
        for chunk in value[steps_idx:].split(", "):
            if ": " in chunk:
                key, raw = chunk.split(": ", 1)
                entries[key.strip()] = raw.strip()

        steps = _coerce_int(entries.get("Steps"))
        if steps is not None:
            result["steps"] = steps

        scale = _coerce_float(entries.get("CFG scale"))
        if scale is not None:
            result["scale"] = scale

        seed = normalize_nai_seed(entries.get("Seed"))
        if seed is not None:
            result["seed"] = seed

        sampler = entries.get("Sampler")
        if sampler:
            result["sampler"] = sampler

        size = entries.get("Size")
        if isinstance(size, str) and "x" in size:
            width_raw, _, height_raw = size.partition("x")
            width = _coerce_int(width_raw)
            height = _coerce_int(height_raw)
            if width is not None:
                result["width"] = width
            if height is not None:
                result["height"] = height

    if not result.get("prompt"):
        return {}

    return result


def _decode_user_comment_bytes(data: bytes) -> str:
    """解码 EXIF UserComment：前 8 字节是字符集标记，其余是正文。"""

    if not data:
        return ""

    charset = data[:8]
    body = data[8:] if len(data) > 8 else b""

    def _strip(text: str) -> str:
        return text.strip("\x00 \ufeff").strip()

    # EXIF 规范的 UNICODE 标记后面跟 UTF-16 编码的正文
    if charset.startswith(b"UNICODE"):
        for encoding in ("utf-16-le", "utf-16-be"):
            try:
                return _strip(body.decode(encoding))
            except UnicodeDecodeError:
                continue
        return ""

    # 不带标记或 ASCII 标记的正文按 UTF-8 解；标记无法识别时保守从头解
    if charset.strip(b"\x00 ") not in (b"", b"ASCII"):
        body = data

    for encoding in ("utf-8", "utf-16-le"):
        try:
            return _strip(body.decode(encoding))
        except UnicodeDecodeError:
            continue
    return ""


def _read_exif_user_comment(image: PILImage.Image) -> str:
    """读 JPEG / WebP EXIF UserComment（tag 37510），读不到返回空串。"""

    try:
        exif = image.getexif()
        ifd = exif.get_ifd(ExifTags.IFD.Exif)
        raw = ifd.get(ExifTags.Base.UserComment)
    except Exception:
        return ""

    if raw is None:
        return ""
    if isinstance(raw, (bytes, bytearray)):
        return _decode_user_comment_bytes(bytes(raw))
    return str(raw or "").strip()


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
    """读取图片文件里的生成参数，读不到返回空 dict。

    PNG 走 tEXt 块（NovelAI Comment/Description、SD WebUI parameters）；
    JPEG / WebP 走 EXIF UserComment（NovelAI JSON 或 SD WebUI 参数文本，
    NovelAI 新版默认导出格式就在这里）。其余格式没有可读的元数据。
    """
    try:
        with PILImage.open(Path(path)) as image:
            return _parse_open_image(image)
    except Exception:
        return {}


def _parse_open_image(image: PILImage.Image) -> Dict[str, Any]:
    fmt = str(image.format or "").upper()
    if fmt == "PNG":
        return parse_nai_info(dict(image.info or {}))
    if fmt in ("JPEG", "WEBP"):
        return parse_user_comment_text(_read_exif_user_comment(image))
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
            return _parse_open_image(image)
    except Exception:
        return {}

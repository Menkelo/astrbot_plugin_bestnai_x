from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any, Dict


def _decode_cq_value(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("&amp;", "&")
    value = urllib.parse.unquote(value)
    return value.strip()


def _parse_cq_params(param_text: str) -> Dict[str, str]:
    result: Dict[str, str] = {}

    for part in str(param_text or "").split(","):
        if "=" not in part:
            continue

        k, v = part.split("=", 1)
        k = k.strip()
        v = _decode_cq_value(v)

        if k:
            result[k] = v

    return result


def _is_probably_usable_image_ref(value: str) -> bool:
    """
    判断一个图片引用是否可直接交给后续处理。

    可用：
    - http/https
    - file://
    - 绝对路径
    - 存在的相对路径

    不可用：
    - 只有文件名，例如 CD1CE4AD29B768255C886E43883DDA02.png
    """
    value = str(value or "").strip()

    if not value:
        return False

    low = value.lower()

    if low.startswith("http://") or low.startswith("https://"):
        return True

    if low.startswith("file://"):
        return True

    if os.path.isabs(value):
        return os.path.exists(value)

    # 相对路径只有在真实存在时才认为可用
    return os.path.exists(os.path.abspath(value))


def extract_cq_image_file(text: str) -> str:
    """
    从 CQ image 中提取图片。
    优先 url，其次 file。
    如果 file 只是裸文件名且本地不存在，则返回空，避免误判为 /AstrBot/xxx.png。
    """
    if not text:
        return ""

    # [CQ:image,file=xxx,url=http://xxx]
    for m in re.finditer(r"\[CQ:image,([^\]]+)\]", text, flags=re.IGNORECASE):
        params = _parse_cq_params(m.group(1))

        url = params.get("url") or params.get("file_url") or ""
        file = params.get("file") or ""

        if url and _is_probably_usable_image_ref(url):
            return url

        if file and _is_probably_usable_image_ref(file):
            return file

    return ""


def extract_image_from_text(text: str) -> str:
    if not text:
        return ""

    got = extract_cq_image_file(text)

    if got:
        return got

    # 普通 URL
    m = re.search(r"(https?://[^\s\]>'\"]+)", text)

    if m:
        url = m.group(1).strip().rstrip(".,，。)")
        if _is_probably_usable_image_ref(url):
            return url

    return ""


def _extract_image_from_image_dict(data: Dict[str, Any]) -> str:
    """
    从 image segment 的 data 里提取图片。
    优先 url，再 file/path。
    """
    if not isinstance(data, dict):
        return ""

    candidates = [
        data.get("url"),
        data.get("file_url"),
        data.get("image_url"),
        data.get("path"),
        data.get("file"),
    ]

    for item in candidates:
        img = str(item or "").strip().replace("%2C", ",")

        if img and _is_probably_usable_image_ref(img):
            return img

    return ""


def find_image_in_segments(obj: Any) -> str:
    if obj is None:
        return ""

    if isinstance(obj, dict):
        t = str(obj.get("type", obj.get("msg_type", ""))).lower()

        if t == "image":
            data = obj.get("data", obj)

            if isinstance(data, dict):
                img = _extract_image_from_image_dict(data)

                if img:
                    return img

            # 有些结构 image 字段直接在 obj 上
            img = _extract_image_from_image_dict(obj)

            if img:
                return img

        # 即使不是 type=image，也可能有嵌套 image/url
        for key in ("url", "file_url", "image_url", "path", "file"):
            val = obj.get(key)

            if isinstance(val, str):
                img = val.strip().replace("%2C", ",")

                if img and _is_probably_usable_image_ref(img):
                    # 避免把普通文本 file 字段误判
                    if key in ("url", "file_url", "image_url") or t == "image":
                        return img

        for v in obj.values():
            got = find_image_in_segments(v)

            if got:
                return got

        return ""

    if isinstance(obj, (list, tuple)):
        for it in obj:
            got = find_image_in_segments(it)

            if got:
                return got

        return ""

    return ""


def extract_image_from_event_best_effort(event) -> str:
    """
    尽量从 AstrBot event 中提取图片。

    优先级：
    1. 结构化消息段里的 url/path
    2. event/message_obj 的字符串形式中的 url
    3. message_str 里的 CQ image url
    4. message_str 里的普通 URL

    注意：
    不再把裸 file 名当本地路径返回。
    """
    # 先查结构化字段，直接消息图片通常这里能拿到 url
    for attr in [
        "message_obj",
        "message",
        "message_chain",
        "raw_message",
        "event_data",
        "reply",
        "quote",
    ]:
        if hasattr(event, attr):
            got = find_image_in_segments(getattr(event, attr))

            if got:
                return got

    # 再查结构化字段字符串，可能里面有 url=
    for attr in [
        "message_obj",
        "message",
        "message_chain",
        "raw_message",
        "event_data",
        "reply",
        "quote",
    ]:
        if hasattr(event, attr):
            try:
                s = str(getattr(event, attr))
                got = extract_image_from_text(s)

                if got:
                    return got

            except Exception:
                pass

    # 最后查 message_str
    raw = getattr(event, "message_str", "") or ""
    got = extract_image_from_text(raw)

    if got:
        return got

    return ""

from __future__ import annotations

import os
import re
import urllib.parse
from typing import Any, Dict


# 消息对象层级不会很深，超过就认定是环或异常结构，直接放弃
MAX_SEGMENT_DEPTH = 24


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


def _extract_image_from_object(obj: Any, depth: int = 0, seen: set | None = None) -> str:
    """从非 dict 对象（如 Image/Reply 组件）中提取图片引用。"""
    if obj is None:
        return ""

    type_name = str(getattr(obj, "type", "") or "").lower()

    for attr in ("url", "file_url", "image_url"):
        val = getattr(obj, attr, None)
        if isinstance(val, str) and val.strip():
            img = val.strip().replace("%2C", ",")
            if img and _is_probably_usable_image_ref(img):
                return img

    if type_name in ("image", "reply", "quote"):
        data = getattr(obj, "data", None)
        if data is not None:
            got = find_image_in_segments(data, depth + 1, seen)
            if got:
                return got

    for chain_attr in ("message_chain", "messages", "message"):
        chain = getattr(obj, chain_attr, None)
        if chain is not None:
            got = find_image_in_segments(chain, depth + 1, seen)
            if got:
                return got

    path_val = getattr(obj, "path", None) or getattr(obj, "file", None)
    if isinstance(path_val, str):
        img = path_val.strip().replace("%2C", ",")
        if img and _is_probably_usable_image_ref(img):
            return img

    try:
        obj_dict = vars(obj)
        return find_image_in_segments(obj_dict, depth + 1, seen)
    except TypeError:
        pass

    return ""


def find_image_in_segments(obj: Any, depth: int = 0, seen: set | None = None) -> str:
    if obj is None:
        return ""

    # 消息对象可能带反向引用，靠深度和 id 双重兜底，避免无限递归
    if depth > MAX_SEGMENT_DEPTH:
        return ""

    if seen is None:
        seen = set()

    if isinstance(obj, (dict, list, tuple)) or hasattr(obj, "__dict__"):
        marker = id(obj)
        if marker in seen:
            return ""
        seen.add(marker)

    if isinstance(obj, dict):
        t = str(obj.get("type", obj.get("msg_type", ""))).lower()

        if t == "image":
            data = obj.get("data", obj)

            if isinstance(data, dict):
                img = _extract_image_from_image_dict(data)

                if img:
                    return img

            img = _extract_image_from_image_dict(obj)

            if img:
                return img

        if t in ("reply", "quote"):
            data = obj.get("data", {})

            if isinstance(data, dict):
                nested_chain = data.get("message_chain") or data.get("message") or data.get("messages")

                if nested_chain:
                    got = find_image_in_segments(nested_chain, depth + 1, seen)

                    if got:
                        return got

        for key in ("url", "file_url", "image_url", "path", "file"):
            val = obj.get(key)

            if isinstance(val, str):
                img = val.strip().replace("%2C", ",")

                if img and _is_probably_usable_image_ref(img):
                    if key in ("url", "file_url", "image_url") or t == "image":
                        return img

        for v in obj.values():
            got = find_image_in_segments(v, depth + 1, seen)

            if got:
                return got

        return ""

    if isinstance(obj, (list, tuple)):
        for it in obj:
            got = find_image_in_segments(it, depth + 1, seen)

            if got:
                return got

        return ""

    return _extract_image_from_object(obj, depth, seen)


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

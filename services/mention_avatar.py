from __future__ import annotations

import re
from typing import Any


def qq_avatar_url(qq: str, size: int = 640) -> str:
    qq = str(qq or "").strip()

    if not qq:
        return ""

    return f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s={int(size)}"


def _extract_at_from_text(text: str) -> str:
    text = str(text or "")

    # OneBot / CQ:
    # [CQ:at,qq=123456]
    m = re.search(r"\[CQ:at,[^\]]*qq=(\d+|all)", text, flags=re.IGNORECASE)
    if m:
        qq = m.group(1)
        if qq != "all":
            return qq

    # 某些适配器 str(event) 后可能类似 dict
    patterns = [
        r"'type'\s*:\s*'at'.*?'qq'\s*:\s*'?(?P<qq>\d+)'?",
        r'"type"\s*:\s*"at".*?"qq"\s*:\s*"?(?P<qq>\d+)"?',
        r"'type'\s*:\s*'at'.*?'user_id'\s*:\s*'?(?P<qq>\d+)'?",
        r'"type"\s*:\s*"at".*?"user_id"\s*:\s*"?(?P<qq>\d+)"?',
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return m.group("qq")

    return ""


def _find_at_in_segments(obj: Any) -> str:
    if obj is None:
        return ""

    if isinstance(obj, dict):
        t = str(obj.get("type", obj.get("msg_type", ""))).lower()

        if t == "at":
            data = obj.get("data", obj)

            if isinstance(data, dict):
                qq = (
                    data.get("qq")
                    or data.get("user_id")
                    or data.get("uid")
                    or data.get("target")
                    or ""
                )

                qq = str(qq).strip()

                if qq and qq.isdigit():
                    return qq

        for v in obj.values():
            got = _find_at_in_segments(v)
            if got:
                return got

        return ""

    if isinstance(obj, (list, tuple)):
        for item in obj:
            got = _find_at_in_segments(item)
            if got:
                return got

        return ""

    return ""


def extract_mentioned_qq_from_event(event) -> str:
    """
    尽量从 AstrBot event 中提取第一个 @ 的 QQ。
    """
    raw = getattr(event, "message_str", "") or ""

    got = _extract_at_from_text(raw)
    if got:
        return got

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
            got = _find_at_in_segments(getattr(event, attr))
            if got:
                return got

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
                got = _extract_at_from_text(str(getattr(event, attr)))
                if got:
                    return got
            except Exception:
                pass

    return ""


def remove_mention_from_prompt(prompt: str, qq: str = "") -> str:
    """
    从 prompt 中移除 CQ at 文本，避免 @ 内容参与提示词。
    """
    text = str(prompt or "")

    text = re.sub(r"\[CQ:at,[^\]]*\]", " ", text, flags=re.IGNORECASE)

    if qq:
        text = text.replace(f"@{qq}", " ")

    text = re.sub(r"\s+", " ", text)

    return text.strip()

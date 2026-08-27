"""SD WebUI ⇄ NovelAI 提示词权重语法互转。

两边的权重方言不通用，直接把一边的提示词喂给另一边不会报错，只会
**静默失效**：NovelAI 把 SD 的 ``(tag:1.2)`` 当成字面括号加冒号，
SD 把 NovelAI 的 ``1.2::tag::`` 当成普通文本。

SD → NAI 的映射（与 NovelAI 官方 web 工具箱一致）：

    (x:1.05)  → {x}          官方 web 的 {} 恰好等价于 1.05 倍
    (x:0.95)  → [x]          0.952381 是 1/1.05，同样映射到 []
    (x:1.2)   → 1.2::x::     其余权重走显式记法
    (x)       → {x}          裸括号在 SD 里就是 1.1 倍，就近取 {}
    \\( \\)     → ( )          转义括号还原成字面字符

NAI → SD 是上面的逆向，字面括号重新转义回 ``\\(``。

移植自 Plana-App ``lib/core/util/prompt_convert.dart``，保留其括号配对
与递归展开逻辑，包括「括号不配对时原样输出」这一条。
"""

from __future__ import annotations

import re

# SD 的 (x:1.05) 与 NAI 的 {x} 等价，(x:1/1.05) 与 [x] 等价。
_BRACE_WEIGHT = 1.05
_BRACKET_WEIGHT = 1.0 / 1.05

_NUMBER_RE = re.compile(r"^\s*-?\d+(?:\.\d+)?\s*$")
_NAI_WEIGHT_RE = re.compile(r"(-?\d+(?:\.\d+)?)::")

_INLINE_TAG_RE = re.compile(r"<(?:lora|lyco|hypernet):[^>]+>", re.IGNORECASE)


def strip_inline_tags(text: str) -> str:
    """去掉 ``<lora:…>`` / ``<lyco:…>`` / ``<hypernet:…>`` 并收拾残留逗号。

    只动标签，不动权重语法——要不要转成 NAI 方言由调用方决定，在这里顺手
    转会让"原样展示图片里的提示词"这类需求拿不到原文。
    """
    value = _INLINE_TAG_RE.sub("", str(text or ""))
    value = re.sub(r",\s*,", ",", value)
    value = re.sub(r"^\s*,|,\s*$", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _format_weight(value: float) -> str:
    """按 JS Number 的字符串语义输出：整数去掉 .0，其余保留原样。"""
    if value == int(value):
        return str(int(value))
    return repr(value)


def _match_bracket(text: str, start: int, opening: str, closing: str) -> int:
    """返回与 ``text[start]`` 配对的右括号的下一个位置，不配对返回 -1。"""
    depth = 1
    index = start + 1
    length = len(text)

    while index < length and depth > 0:
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
        index += 1

    return index if depth == 0 else -1


def convert_sd_to_nai(text: str) -> str:
    """把 SD WebUI 的权重语法整串转成 NovelAI 方言。"""
    value = str(text or "")
    out: list[str] = []
    i = 0
    length = len(value)

    while i < length:
        char = value[i]

        if char == "\\" and i + 1 < length and value[i + 1] in "()":
            out.append(value[i + 1])
            i += 2
            continue

        if char == "(":
            end = _match_bracket(value, i, "(", ")")

            if end != -1:
                inner = value[i + 1 : end - 1]
                out.append(_convert_sd_group(inner))
                i = end
                continue

        elif char == "[":
            end = _match_bracket(value, i, "[", "]")

            if end != -1:
                out.append(f"[{convert_sd_to_nai(value[i + 1 : end - 1])}]")
                i = end
                continue

        out.append(char)
        i += 1

    return "".join(out)


def _convert_sd_group(inner: str) -> str:
    """转换一对 SD 圆括号的内容，按有无尾部权重分流。"""
    last_colon = inner.rfind(":")

    if last_colon > 0:
        right = inner[last_colon + 1 :]

        # 冒号也可能是 `artist:foo` 这种标签的一部分，只有右侧是纯数字
        # 才当权重解释。
        if _NUMBER_RE.match(right):
            weight = float(right.strip())
            content = convert_sd_to_nai(inner[:last_colon])

            if abs(weight - _BRACE_WEIGHT) < 0.001:
                return f"{{{content}}}"

            if abs(weight - _BRACKET_WEIGHT) < 0.001 or abs(weight - 0.95) < 0.001:
                return f"[{content}]"

            return f"{_format_weight(weight)}::{content}::"

    # 裸括号 (x) 在 SD 里是加权，映射到 NAI 的 {x}
    return f"{{{convert_sd_to_nai(inner)}}}"


def convert_nai_to_sd(text: str) -> str:
    """把 NovelAI 的权重语法整串转回 SD WebUI 方言。"""
    value = str(text or "")
    out: list[str] = []
    i = 0
    length = len(value)

    while i < length:
        char = value[i]

        if char.isdigit() or char == "-":
            match = _NAI_WEIGHT_RE.match(value, i)

            if match:
                after_number = match.end()
                end = value.find("::", after_number)

                if end != -1:
                    weight = float(match.group(1))
                    content = convert_nai_to_sd(value[after_number:end])
                    out.append(f"({content}:{_format_weight(weight)})")
                    i = end + 2
                    continue

        if char == "{":
            end = _match_bracket(value, i, "{", "}")

            if end != -1:
                content = convert_nai_to_sd(value[i + 1 : end - 1])
                out.append(f"({content}:{_BRACE_WEIGHT})")
                i = end
                continue

        elif char == "[":
            end = _match_bracket(value, i, "[", "]")

            if end != -1:
                out.append(f"[{convert_nai_to_sd(value[i + 1 : end - 1])}]")
                i = end
                continue

        if char in "()":
            out.append(f"\\{char}")
            i += 1
            continue

        out.append(char)
        i += 1

    return "".join(out)

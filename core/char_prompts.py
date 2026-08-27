"""NovelAI 多角色提示词的结构化载荷。

反推命中内嵌参数时读出的角色提示词（char_captions）在这里被规范化成
生图网关接受的扁平结构：

    characters = [{"prompt": "...", "negative_prompt": "", "position": "C3"}, ...]

``position`` 沿用原版 BestNAI 插件的五列网格记号（A-E 列、1-5 行），
由 NAI 元数据里的中心点坐标（0~1 小数）就近换算；没有坐标的角色按
角色数量套用原版插件的默认分配。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

MAX_CHAR_PROMPTS = 16
MAX_CHAR_PROMPT_LENGTH = 2000
_GRID_COLUMNS = "ABCDE"
_GRID_ROWS = 5
_POSITION_RE = re.compile(r"[A-E][1-5]")

# 与原版 BestNAI 插件保持一致的默认站位
DEFAULT_POSITIONS = {
    1: ["C3"],
    2: ["B3", "D3"],
    3: ["B3", "C3", "D3"],
    4: ["A3", "B3", "D3", "E3"],
}


def _clamp01(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return min(max(number, 0.0), 1.0)


def char_grid_position(x: Any, y: Any) -> str | None:
    """把 0~1 的中心点坐标换算成五列网格记号（如 C3）。"""
    fx = _clamp01(x)
    fy = _clamp01(y)
    if fx is None or fy is None:
        return None
    column = min(round(fx * 4), 4)
    row = min(round(fy * 4), 4) + 1
    return f"{_GRID_COLUMNS[column]}{row}"


def default_char_position(index: int, count: int) -> str:
    positions = DEFAULT_POSITIONS.get(count)
    if positions and index < len(positions):
        return positions[index]
    # 原版对 5 人以上没有预设，沿用居中列 C1..C5。网格只有五行，索引再大也不能
    # 往下溢出成 C6——那是个非法站位，会被网关以 400 打回。
    return f"C{min(int(index) + 1, _GRID_ROWS)}"


def is_valid_position(value: Any) -> bool:
    """站位是否落在 A~E 列、1~5 行的网格内。"""
    return bool(_POSITION_RE.fullmatch(str(value or "").strip().upper()))


def has_explicit_positions(raw: Any) -> bool:
    """原始输入里是否有人**明确指定**过合法站位。

    位置只有在 ``use_coords`` 为真时才生效，否则 NovelAI 按出场顺序排布、
    直接忽略坐标。而程序按人数自动分配的默认站位不算「用户意图」——为它
    打开 use_coords 会把本来好好的顺序排布换成一个谁也没要求的分区。
    """
    if not isinstance(raw, list):
        return False

    return any(
        isinstance(item, dict) and is_valid_position(item.get("position"))
        for item in raw[:MAX_CHAR_PROMPTS]
    )


def normalize_char_entries(raw: Any) -> List[Dict[str, str]]:
    """校验并规范化角色参数列表；非法输入一律丢弃而不是猜测。"""
    if not isinstance(raw, list):
        return []

    result: List[Dict[str, str]] = []
    for index, item in enumerate(raw[:MAX_CHAR_PROMPTS]):
        if not isinstance(item, dict):
            continue
        prompt = str(item.get("prompt") or item.get("caption") or "").strip()
        if not prompt:
            continue
        entry = {
            "prompt": prompt[:MAX_CHAR_PROMPT_LENGTH],
            "negative_prompt": str(
                item.get("negative_prompt") or item.get("negative") or ""
            ).strip()[:MAX_CHAR_PROMPT_LENGTH],
            "position": "",
        }
        explicit = str(item.get("position") or "").strip().upper()
        if is_valid_position(explicit):
            entry["position"] = explicit
        else:
            # 非法站位（"Z9"、"C6"）不能原样送出去：网关会以 400 拒绝整次
            # 请求，连带把其余角色一起废掉。退回坐标推算或默认站位。
            entry["position"] = (
                char_grid_position(item.get("x"), item.get("y"))
                or default_char_position(len(result), len(raw))
            )
        result.append(entry)

    return result

"""NovelAI 多角色提示词的结构化载荷。

反推命中内嵌参数时读出的角色提示词（``char_captions``）会被规范化成
插件内部统一的条目。条目保留 NovelAI 原始的 ``center`` 坐标，同时保留
旧中转网关使用的五列五行 ``position`` 表示：官方协议使用前者，中转协议
使用后者。这样不会为了兼容旧网关而损失官方元数据里的精确坐标。
"""

from __future__ import annotations

import math
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


def _unit_coordinate(value: Any) -> float | None:
    """读取一个严格位于 0~1 的坐标；非法值不参与官方载荷。"""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        return None
    return number


def normalize_char_center(value: Any) -> Dict[str, float] | None:
    """规范化 NovelAI 的单个 ``center`` 对象，非法坐标返回 ``None``。"""
    if not isinstance(value, dict):
        return None

    x = _unit_coordinate(value.get("x"))
    y = _unit_coordinate(value.get("y"))
    if x is None or y is None:
        return None
    return {"x": x, "y": y}


def _entry_center(item: Any) -> Dict[str, float] | None:
    """从元数据、官方条目或旧缓存条目中取出精确中心点。"""
    if not isinstance(item, dict):
        return None

    center = normalize_char_center(item.get("center"))
    if center is not None:
        return center

    centers = item.get("centers")
    if isinstance(centers, list):
        for candidate in centers:
            center = normalize_char_center(candidate)
            if center is not None:
                return center

    # nai_metadata.py 的内部兼容格式使用平铺的 x/y。
    return normalize_char_center({"x": item.get("x"), "y": item.get("y")})


def _first_text(item: Dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def char_grid_position(x: Any, y: Any) -> str | None:
    """把 0~1 的中心点坐标换算成五列网格记号（如 C3）。"""
    fx = _clamp01(x)
    fy = _clamp01(y)
    if fx is None or fy is None:
        return None
    column = min(round(fx * 4), 4)
    row = min(round(fy * 4), 4) + 1
    return f"{_GRID_COLUMNS[column]}{row}"


def char_grid_center(position: Any) -> Dict[str, float] | None:
    """把网格记号（如 C3）换算回 0~1 的中心点坐标，非法输入返回 None。

    ``char_grid_position`` 的反函数。走中转网关时这一步由网关代劳
    （已实测 ``B3`` 被翻成 ``{x: 0.3, y: 0.5}``），但 NovelAI 官方协议
    要的是 ``centers`` 里的小数坐标，得插件自己算。

    取格子中心而不是格子起点：五列均分后 B 列的中心是 ``(1 + 0.5) / 5``
    = 0.3，与网关的实测值一致，也能被 ``char_grid_position`` 原样读回。
    """
    text = str(position or "").strip().upper()
    if not _POSITION_RE.fullmatch(text):
        return None

    column = _GRID_COLUMNS.index(text[0])
    row = int(text[1]) - 1
    return {
        "x": (column + 0.5) / len(_GRID_COLUMNS),
        "y": (row + 0.5) / _GRID_ROWS,
    }


def char_entry_center(entry: Any) -> Dict[str, float] | None:
    """返回条目的精确中心，缺失时再由兼容网格站位推导。"""
    center = _entry_center(entry)
    if center is not None:
        return center
    if isinstance(entry, dict):
        return char_grid_center(entry.get("position"))
    return None


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


def normalize_char_entries(raw: Any) -> List[Dict[str, Any]]:
    """校验并规范化角色参数列表，同时保留有效的原始中心坐标。"""
    if not isinstance(raw, list):
        return []

    # 先筛掉无效角色再计算默认站位，避免一个坏条目改变后续角色的布局。
    candidates = []
    for item in raw[:MAX_CHAR_PROMPTS]:
        if not isinstance(item, dict):
            continue
        prompt = _first_text(item, ("prompt", "caption", "char_caption"))
        if not prompt:
            continue
        candidates.append((item, prompt))

    result: List[Dict[str, Any]] = []
    for index, (item, prompt) in enumerate(candidates):
        negative_prompt = _first_text(item, ("negative_prompt", "negative", "uc"))
        center = _entry_center(item)
        entry = {
            "prompt": prompt[:MAX_CHAR_PROMPT_LENGTH],
            "negative_prompt": negative_prompt[:MAX_CHAR_PROMPT_LENGTH],
            "position": "",
        }
        explicit = str(item.get("position") or "").strip().upper()
        if is_valid_position(explicit):
            entry["position"] = explicit
        else:
            # 非法站位（"Z9"、"C6"）不能原样送出去：网关会以 400 拒绝整次
            # 请求，连带把其余角色一起废掉。退回坐标推算或默认站位。
            entry["position"] = (
                char_grid_position(center["x"], center["y"])
                if center is not None
                else None
            ) or default_char_position(index, len(candidates))

        # ``center`` 是官方 char_captions 的真实坐标。只有输入确实提供了
        # 有效坐标时才写入，位置-only 的旧缓存仍保持原来的简洁形状。
        if center is not None:
            entry["center"] = center
        result.append(entry)

    return result


def automatic_char_layout(raw_entries: Any) -> tuple[bool, bool]:
    """Derive NovelAI's layout flags from the number of effective characters.

    A single character has no region to disambiguate and some relays reject
    ``use_coords=true`` unless at least two character prompts are enabled.
    Multiple characters always use their stored centers.
    """
    character_count = len(normalize_char_entries(raw_entries))
    use_coords = character_count >= 2
    return use_coords, not use_coords

"""NovelAI 多角色提示词的结构化载荷。

反推命中内嵌参数时读出的角色提示词（char_captions）在这里被规范化成
生图网关接受的扁平结构：

    characters = [{"prompt": "...", "negative_prompt": "", "position": "C3"}, ...]

``position`` 沿用原版 BestNAI 插件的五列网格记号（A-E 列、1-5 行），
由 NAI 元数据里的中心点坐标（0~1 小数）就近换算；没有坐标的角色按
角色数量套用原版插件的默认分配。
"""

from __future__ import annotations

from typing import Any, Dict, List

MAX_CHAR_PROMPTS = 16
MAX_CHAR_PROMPT_LENGTH = 2000
_GRID_COLUMNS = "ABCDE"

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
    return f"C{index + 1}"


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
        if explicit:
            entry["position"] = explicit
        else:
            entry["position"] = (
                char_grid_position(item.get("x"), item.get("y"))
                or default_char_position(len(result), len(raw))
            )
        result.append(entry)

    return result

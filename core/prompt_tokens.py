"""Small, dependency-free parser for NovelAI prompt segments.

NovelAI's numeric weight syntax uses commas inside a segment, for example
``1.2::character_tag, series_tag ::``.  Splitting every prompt on commas
silently corrupts that syntax, so the retag, translator, and metadata paths
share this parser instead of maintaining subtly different regexes.
"""

from __future__ import annotations

import re
from typing import List, Tuple


_WEIGHT_PREFIX_RE = re.compile(r"^-?\d+(?:\.\d+)?::")
_WEIGHTED_TOKEN_RE = re.compile(
    r"^\s*(-?\d+(?:\.\d+)?)::\s*(.*?)\s*::\s*$",
    re.DOTALL,
)


def split_prompt_tokens(prompt: str) -> List[str]:
    """Split top-level prompt segments while preserving weighted groups.

    Commas/semicolons/newlines inside a numeric ``weight:: ... ::`` group or
    balanced brackets are kept as part of that segment.  The returned tokens
    are trimmed but otherwise retain their original syntax.
    """

    text = str(prompt or "")
    tokens: List[str] = []
    buffer: List[str] = []
    weighted = False
    bracket_stack: List[str] = []
    quote = ""
    index = 0

    def flush() -> None:
        value = "".join(buffer).strip(" ,;\n\t")
        if value:
            tokens.append(value)
        buffer.clear()

    while index < len(text):
        if not weighted and not "".join(buffer).strip():
            match = _WEIGHT_PREFIX_RE.match(text[index:])
            if match:
                value = match.group(0)
                buffer.extend(value)
                index += len(value)
                weighted = True
                continue

        if weighted:
            if text.startswith("::", index):
                buffer.extend("::")
                index += 2
                weighted = False
                continue
            buffer.append(text[index])
            index += 1
            continue

        char = text[index]
        if quote:
            buffer.append(char)
            if char == quote and (index == 0 or text[index - 1] != "\\"):
                quote = ""
            index += 1
            continue

        if char in {'"', "'"}:
            quote = char
            buffer.append(char)
            index += 1
            continue

        if char in "([{":
            bracket_stack.append(char)
            buffer.append(char)
            index += 1
            continue

        if char in ")]}":
            if bracket_stack:
                bracket_stack.pop()
            buffer.append(char)
            index += 1
            continue

        if char in ",;\n" and not bracket_stack:
            flush()
            index += 1
            continue

        buffer.append(char)
        index += 1

    flush()
    return tokens


def weighted_token_parts(token: str) -> Tuple[str, List[str], bool]:
    """Return ``(weight, inner_tokens, is_weighted)`` for one segment."""

    value = str(token or "").strip()
    match = _WEIGHTED_TOKEN_RE.match(value)
    if not match:
        return "", [value] if value else [], False

    inner = split_prompt_tokens(match.group(2))
    return match.group(1), inner, True


def rebuild_weighted_token(weight: str, inner_tokens: List[str]) -> str:
    """Rebuild a numeric weight group in NAI's unambiguous spelling."""

    values = [str(item or "").strip(" ,;\n\t") for item in inner_tokens]
    values = [item for item in values if item]
    if not values:
        return ""
    # Keep a space before the closing delimiter.  Without it, a trailing
    # numeric tag such as ``year 2025`` can be parsed as a new weight.
    return f"{weight}::{', '.join(values)} ::"


def expand_prompt_tokens(prompt: str) -> List[str]:
    """Expand weighted groups into atomic tag-like segments."""

    expanded: List[str] = []
    for token in split_prompt_tokens(prompt):
        _, inner, weighted = weighted_token_parts(token)
        if weighted:
            expanded.extend(inner)
        else:
            expanded.append(token)
    return expanded


_COUNT_TOKEN_RE = re.compile(r"^(\d*)(boys?|girls?)$", re.IGNORECASE)


def _count_token_value(token: str) -> Tuple[str, int, bool] | None:
    """Return ``(family, count, has_explicit_number)`` for a pure count tag."""

    match = _COUNT_TOKEN_RE.match(str(token or "").strip())
    if not match:
        return None

    number, word = match.groups()
    family = "boy" if word.lower().startswith("boy") else "girl"
    count = int(number) if number else 1
    return family, max(count, 1), bool(number)


def normalize_count_tokens(prompt: str) -> str:
    """折叠同一性别家族里重复的人数标签，返回逗号拼接的新提示词。

    多角色图的还原文本常同时带全局计数（``1boy, 4girls``）和每个角色
    段落开头的裸计数（``boy`` / ``girl``）。叠加的计数信号会让模型多画人，
    因此需要归一：

    - 家族里有显式数字的计数（如 ``1boy``、``4girls``）视为全图总数，
      原样保留第一个，丢弃该家族其余所有计数；
    - 只有裸计数时视为各描述一个不同的人，求和后合并成一条
      （``girl, a, girl, b`` → ``2girls, a, b``）。

    权重组、括号与引号内的内容不参与判定，原样保留。
    """
    tokens = split_prompt_tokens(prompt)

    explicit_index: dict[str, int] = {}
    bare_values: dict[str, List[Tuple[int, int]]] = {}
    parsed: List[Tuple[str | None, int, bool] | None] = []
    for index, token in enumerate(tokens):
        weight, inner, weighted = weighted_token_parts(token)
        info = (
            _count_token_value(inner[0])
            if not weighted and len(inner) == 1
            else None
        )
        parsed.append(info)
        if info is None:
            continue
        family, count, has_number = info
        if has_number and family not in explicit_index:
            explicit_index[family] = index
        elif not has_number:
            bare_values.setdefault(family, []).append((index, count))

    totals: dict[str, tuple[int, int]] = {}
    for family, entries in bare_values.items():
        if family in explicit_index:
            continue
        total = sum(count for _, count in entries)
        if len(entries) > 1:
            totals[family] = (entries[0][0], total)

    kept: List[str] = []
    seen_families: set[str] = set()
    for index, token in enumerate(tokens):
        info = parsed[index]
        if info is None:
            kept.append(token)
            continue

        family, _count, _has_number = info

        if family in explicit_index:
            # 显式总数说了算：只保留第一处，其余同族计数全部丢弃
            if explicit_index[family] != index:
                continue
            kept.append(token)
            continue

        if family in totals:
            # 裸计数求和后合并进第一条
            if totals[family][0] != index:
                continue
            word = "boys" if family == "boy" else "girls"
            kept.append(f"{totals[family][1]}{word}")
            continue

        if family in seen_families:
            continue
        seen_families.add(family)
        kept.append(token)

    return ", ".join(kept)

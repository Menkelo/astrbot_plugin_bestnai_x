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

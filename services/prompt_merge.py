from __future__ import annotations

import re
from typing import Iterable

from .prompt_builder import apply_prompt_weight, normalize_prompt_ascii


_CATEGORY_PATTERNS = {
    "appearance": re.compile(
        r"(?:^|[_\s-])(hair|hairstyle|bangs|twintail|ponytail|braid|"
        r"eyes?|eyebrows?|eyelashes|skin|freckles|mole|horns?|animal_ears|"
        r"fox_ears|cat_ears|glasses|eyepatch|tail)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "clothing": re.compile(
        r"(?:^|[_\s-])(dress|uniform|school_uniform|shirt|blouse|skirt|"
        r"shorts|pants|trousers|jeans|jacket|coat|hoodie|sweater|cardigan|"
        r"swimsuit|bikini|apron|armor|kimono|yukata|socks?|stockings?|"
        r"shoes?|boots?|sandals?|gloves?|hat|cap|ribbon|necktie|bowtie)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "pose": re.compile(
        r"(?:^|[_\s-])(standing|sitting|kneeling|lying|walking|running|"
        r"jumping|dancing|squatting|crouching|leaning|bent_over|looking_at_viewer|"
        r"looking_away|holding|carrying|waving|arms_up|arms_crossed|hand_on_hip)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "expression": re.compile(
        r"(?:^|[_\s-])(smile|smiling|grin|laughing|crying|tears|angry|"
        r"sad|surprised|blush|blushing|expressionless|closed_eyes|open_mouth)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
}

_IDENTITY_MARKER = re.compile(
    r"(?:换成|改成|替换成|换为|改为|变成|角色(?:改成|换成|替换为|变为)|"
    r"replace(?:\s+the)?\s+(?:character|subject|person)?\s*(?:with|by)|"
    r"change(?:\s+the)?\s+(?:character|subject|person)?\s*(?:to|into)|"
    r"switch(?:\s+to|\s+the))\s*[:：]?\s*",
    re.IGNORECASE,
)

_CATEGORY_MARKERS = {
    "appearance": re.compile(
        r"(?:外观|发型|发色|瞳色|appearance|hairstyle|hair|eyes?)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "clothing": re.compile(
        r"(?:服装|衣服|穿着|衣着|换装|衣裳|outfit|clothing|clothes|dress)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "pose": re.compile(
        r"(?:动作|姿势|姿态|pose|action)\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "expression": re.compile(
        r"(?:表情|神态|expression)\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
}

_DIRECTIVE_WORDS = re.compile(
    r"(?:换成|改成|替换成|换为|改为|变成|角色|服装|衣服|穿着|衣着|换装|"
    r"动作|姿势|姿态|表情|神态|replace|change|switch|character|subject|"
    r"person|outfit|clothing|clothes|pose|action|expression|to|into|with|by)",
    re.IGNORECASE,
)

_GENERIC_SUBJECT_TAGS = {
    "1girl",
    "2girls",
    "3girls",
    "1boy",
    "2boys",
    "solo",
    "multiple_girls",
    "multiple_boys",
    "simple_background",
}


def _tokens(prompt: str) -> list[str]:
    cleaned = normalize_prompt_ascii(prompt or "")
    return [part.strip() for part in re.split(r"\s*,\s*", cleaned) if part.strip()]


def _key(token: str) -> str:
    value = normalize_prompt_ascii(token).strip(" ,")
    weighted = re.match(r"^-?\d+(?:\.\d+)?::\s*(.*?)\s*::$", value)
    if weighted:
        value = weighted.group(1).strip()
    return re.sub(r"\s+", " ", value).casefold()


def _category(token: str) -> str:
    key = _key(token)
    for category, pattern in _CATEGORY_PATTERNS.items():
        if pattern.search(key):
            return category
    return ""


def _has_category(tokens: Iterable[str], category: str) -> bool:
    return any(_category(token) == category for token in tokens)


def _extract_identity_override(text: str) -> str:
    match = _IDENTITY_MARKER.search(text or "")
    if not match:
        return ""
    tail = (text or "")[match.end():]
    # A sentence may continue with another instruction; keep only the first clause.
    tail = re.split(r"[,，。；;\n]|(?:\s+and\s+)|(?:\s+并且\s+)", tail, maxsplit=1)[0]
    return tail.strip(" \t:：")


def _extract_category_override(text: str, category: str) -> str:
    marker = _CATEGORY_MARKERS.get(category)
    if marker is None:
        return ""
    match = marker.search(text or "")
    if not match:
        return ""
    tail = (text or "")[match.end():]
    tail = re.split(r"[,，。；;\n]|(?:\s+and\s+)|(?:\s+并且\s+)", tail, maxsplit=1)[0]
    return tail.strip(" \t:：")


def merge_retag_prompt(
    translated_user_prompt: str,
    retag_prompt: str,
    *,
    original_user_prompt: str = "",
    source_character: str = "",
    source_series: str = "",
    weight_user: bool = True,
) -> str:
    """Merge image tags with user edits using category-level overrides.

    User edits are treated as an overlay. Explicit character replacement removes
    the source identity and identity-linked appearance/clothing tags; explicit
    clothing/pose/expression edits remove only that category from the image tags.
    """
    user_text = normalize_prompt_ascii(translated_user_prompt or "").strip()
    raw_user_text = original_user_prompt or user_text
    source_tokens = _tokens(retag_prompt)
    user_tokens = _tokens(user_text)

    translated_identity_tail = _extract_identity_override(user_text)
    raw_identity_tail = _extract_identity_override(raw_user_text)
    identity_tail = translated_identity_tail or (
        user_text if raw_identity_tail and user_text != raw_user_text else raw_identity_tail
    )
    identity_override = _tokens(identity_tail)
    category_overrides: dict[str, list[str]] = {}
    for category in ("appearance", "clothing", "pose", "expression"):
        translated_tail = _extract_category_override(user_text, category)
        raw_tail = _extract_category_override(raw_user_text, category)
        tail = translated_tail or (
            user_text if raw_tail and user_text != raw_user_text else raw_tail
        )
        if tail:
            category_overrides[category] = _tokens(tail)
        elif _has_category(user_tokens, category):
            category_overrides[category] = [token for token in user_tokens if _category(token) == category]

    remove_keys: set[str] = set()
    if identity_override:
        for token in (source_character, source_series):
            if _key(token):
                remove_keys.add(_key(token))
        # Character changes should not leave the old character's obvious visual
        # signature or clothing behind. Composition and background stay intact.
        for token in source_tokens:
            if _category(token) in {"appearance", "clothing"}:
                remove_keys.add(_key(token))

        # The retagger puts character/series first. Use this only as a fallback
        # for QQ/vision results where structured identity fields are unavailable.
        for token in source_tokens[:2]:
            key = _key(token)
            if (
                key
                and key not in _GENERIC_SUBJECT_TAGS
                and ("_" in key or key.isalpha())
            ):
                remove_keys.add(_key(token))

    for category in category_overrides:
        for token in source_tokens:
            if _category(token) == category:
                remove_keys.add(_key(token))

    seen = set(remove_keys)
    seen.update(_key(token) for token in user_tokens if _key(token))
    remaining: list[str] = []
    for token in source_tokens:
        key = _key(token)
        if key and key not in seen:
            seen.add(key)
            remaining.append(token)

    if identity_override or category_overrides:
        override_tokens = list(identity_override)
        for values in category_overrides.values():
            override_tokens.extend(values)

        cleaned_user_tokens = []
        override_keys = {_key(token) for token in override_tokens}
        for token in user_tokens:
            if _DIRECTIVE_WORDS.search(token):
                continue
            if _key(token) in override_keys:
                continue
            cleaned_user_tokens.append(token)
        user_tokens = override_tokens + cleaned_user_tokens

    user_keys = {_key(token) for token in user_tokens if _key(token)}
    remaining = [token for token in remaining if _key(token) not in user_keys]

    merged_user = ", ".join(user_tokens)
    if weight_user and merged_user:
        merged_user = apply_prompt_weight(merged_user)

    return ", ".join(part for part in (merged_user, ", ".join(remaining)) if part).strip(" ,")

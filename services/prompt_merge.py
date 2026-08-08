from __future__ import annotations

import re
from typing import Iterable

from ..core.prompt_tokens import (
    rebuild_weighted_token,
    split_prompt_tokens,
    weighted_token_parts,
)
from .prompt_builder import apply_prompt_weight, normalize_prompt_ascii


_CATEGORY_PATTERNS = {
    "appearance": re.compile(
        r"(?:^|[_\s-])(hair|hairstyle|bangs|twintail|ponytail|braid|"
        r"eyes?|eyebrows?|eyelashes|skin|freckles|mole|horns?|animal_ears|"
        r"fox_ears|cat_ears|glasses|eyepatch|tail|whiskers?|fangs?|"
        r"pointy_ears|colored_skin|dark_skin|pale_skin|facial_marks?|"
        r"heterochromia|wings?|makeup)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "clothing": re.compile(
        r"(?:^|[_\s-])(dress|uniform|school_uniform|shirt|blouse|skirt|"
        r"shorts|pants|trousers|jeans|jacket|coat|hoodie|sweater|cardigan|"
        r"swimsuit|bikini|apron|armor|kimono|yukata|socks?|stockings?|"
        r"shoes?|boots?|sandals?|gloves?|hat|cap|ribbon|necktie|bowtie|"
        r"sleeves?|bare_shoulders|collarbone|collar|hood|cloak|cape|vest|"
        r"overalls?|jumpsuit|romper|leotard|bodysuit|turtleneck|tank_top|"
        r"crop_top|underwear|lingerie|panties|bra|garter|thighhighs?|"
        r"maid|lolita|gothic|casual|formal|headband|hairband|earrings?|"
        r"necklace|choker|bracelet|ring|belt|off_shoulder|sailor_collar|"
        r"serafuku|pantyhose|bare_legs|bare_feet|suspenders?)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "pose": re.compile(
        r"(?:^|[_\s-])(standing|sitting|kneeling|lying|walking|running|"
        r"jumping|dancing|squatting|crouching|leaning|bent_over|looking_at_viewer|"
        r"looking_away|looking_back|from_behind|profile|reclining|on_back|"
        r"on_side|holding|carrying|waving|fighting|flying|arms_up|arms_crossed|"
        r"crossed_arms|hand_on_hip|hand_on_own_chest|head_tilt|spread_legs|"
        r"leg_up|one_leg_up|facing_viewer|hands_up|hands_on_hips|legs_crossed|"
        r"dynamic_pose|arm_up)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "expression": re.compile(
        r"(?:^|[_\s-])(smile|smiling|grin|laughing|crying|tears|angry|"
        r"sad|surprised|blush|blushing|expressionless|closed_eyes|open_mouth|"
        r"closed_mouth|smirk|frown|pout|wink|sleepy|half_closed_eyes)(?:$|[_\s-])",
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
    return split_prompt_tokens(cleaned)


def _atomic_tokens(token: str) -> list[str]:
    _, inner, weighted = weighted_token_parts(token)
    return inner if weighted else [str(token or "").strip()]


def _token_keys(token: str) -> set[str]:
    return {
        _key(part)
        for part in _atomic_tokens(token)
        if _key(part)
    }


def _key(token: str) -> str:
    value = normalize_prompt_ascii(token).strip(" ,")
    _, inner, weighted = weighted_token_parts(value)
    if weighted:
        return ", ".join(_key(part) for part in inner if _key(part))
    return re.sub(r"\s+", " ", value).casefold()


def _category_atom(token: str) -> str:
    key = _key(token)
    for category, pattern in _CATEGORY_PATTERNS.items():
        if pattern.search(key):
            return category
    return ""


def _categories(token: str) -> set[str]:
    return {
        category
        for category in (_category_atom(part) for part in _atomic_tokens(token))
        if category
    }


def _category(token: str) -> str:
    categories = _categories(token)
    for category in ("appearance", "clothing", "pose", "expression"):
        if category in categories:
            return category
    return ""


def _has_category(tokens: Iterable[str], category: str) -> bool:
    return any(category in _categories(token) for token in tokens)


def _filter_segment(
    token: str,
    *,
    remove_keys: set[str] | None = None,
    remove_categories: set[str] | None = None,
    used_keys: set[str] | None = None,
) -> str:
    """Remove atomic tags from one segment without breaking a weight group."""

    weight, atoms, weighted = weighted_token_parts(token)
    kept: list[str] = []
    forbidden = remove_keys or set()
    categories = remove_categories or set()

    for atom in atoms:
        key = _key(atom)
        if not key or key in forbidden or _category_atom(atom) in categories:
            continue
        if used_keys is not None and key in used_keys:
            continue
        kept.append(atom.strip(" ,;\n\t"))
        if used_keys is not None:
            used_keys.add(key)

    if not kept:
        return ""
    if weighted:
        return rebuild_weighted_token(weight, kept)
    return ", ".join(kept)


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
    user_character: str = "",
    user_series: str = "",
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
    if user_character:
        identity_override = [
            token
            for value in (user_character, user_series)
            for token in _tokens(str(value or ""))
        ]
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
        for token in (
            *_tokens(str(source_character or "")),
            *_tokens(str(source_series or "")),
        ):
            remove_keys.update(_token_keys(token))
        # Character changes should not leave the old character's obvious visual
        # signature or clothing behind. Composition and background stay intact.
        for token in source_tokens:
            for atom in _atomic_tokens(token):
                if _category_atom(atom) in {"appearance", "clothing"}:
                    remove_keys.add(_key(atom))

        # Legacy unstructured retag output may put character/series first. Keep
        # the fallback conservative: structured fields are authoritative, and
        # obvious appearance/pose/expression tags must never be guessed as IDs.
        if not source_character and not source_series:
            # Older cached/metadata results may not have structured identity
            # fields.  Remove up to two leading canonical-looking identity
            # tags, while skipping generic subject and visual tags.
            fallback_identity_count = 0
            for token in source_tokens[:6]:
                for atom in _atomic_tokens(token):
                    key = _key(atom)
                    if (
                        key
                        and fallback_identity_count < 2
                        and not _category_atom(atom)
                        and key not in _GENERIC_SUBJECT_TAGS
                        and "_" in key
                    ):
                        remove_keys.add(key)
                        fallback_identity_count += 1
                    if fallback_identity_count >= 2:
                        break

    category_remove_keys: set[str] = set()
    for category in category_overrides:
        for token in source_tokens:
            for atom in _atomic_tokens(token):
                if _category_atom(atom) == category:
                    category_remove_keys.add(_key(atom))
    remove_keys.update(category_remove_keys)

    seen = set(remove_keys)
    for token in user_tokens:
        seen.update(_token_keys(token))
    remaining: list[str] = []
    for token in source_tokens:
        filtered = _filter_segment(token, remove_keys=remove_keys, used_keys=seen)
        if filtered:
            remaining.append(filtered)

    if identity_override or category_overrides:
        override_tokens = list(identity_override)
        for values in category_overrides.values():
            override_tokens.extend(values)

        cleaned_user_tokens = []
        override_keys: set[str] = set()
        for token in override_tokens:
            override_keys.update(_token_keys(token))
        for token in user_tokens:
            if _DIRECTIVE_WORDS.search(token):
                continue
            filtered = _filter_segment(token, remove_keys=override_keys)
            if filtered:
                cleaned_user_tokens.append(filtered)
        user_tokens = override_tokens + cleaned_user_tokens

    user_keys: set[str] = set()
    for token in user_tokens:
        user_keys.update(_token_keys(token))
    remaining = [
        filtered
        for token in remaining
        if (filtered := _filter_segment(token, remove_keys=user_keys))
    ]

    merged_user = ", ".join(user_tokens)
    if weight_user and merged_user:
        merged_user = apply_prompt_weight(merged_user)

    return ", ".join(part for part in (merged_user, ", ".join(remaining)) if part).strip(" ,")

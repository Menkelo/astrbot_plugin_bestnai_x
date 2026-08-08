from __future__ import annotations

import re
from typing import Any, Dict, Iterable

from ..core.prompt_tokens import (
    rebuild_weighted_token,
    split_prompt_tokens,
    weighted_token_parts,
)
from .prompt_builder import apply_prompt_weight, normalize_prompt_ascii


_CATEGORY_PATTERNS = {
    "subject": re.compile(
        r"(?:^|[_\s-])(1girl|2girls|3girls|4girls|1boy|2boys|3boys|"
        r"4boys|solo|duo|trio|multiple_girls|multiple_boys|multiple|"
        r"animal|mecha|robot|monster|creature|furry)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "expression": re.compile(
        r"(?:^|[_\s-])(smile|smiling|grin|laughing|crying|tears|angry|"
        r"sad|surprised|blush|blushing|expressionless|closed_eyes|open_mouth|"
        r"closed_mouth|smirk|frown|pout|wink|sleepy|half_closed_eyes|serious|"
        r"serious_expression|determined|nervous|embarrassed|scared|confused|"
        r"pleased|annoyed|worried|seductive_smile)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "hair": re.compile(
        r"(?:^|[_\s-])(hair|hairstyle|bangs|twintails?|ponytails?|braids?|"
        r"ahoge|hair_bun|hair_ornament)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "eyes": re.compile(
        r"(?:^|[_\s-])(eyes?|eyebrows?|eyelashes|heterochromia)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "skin": re.compile(
        r"(?:^|[_\s-])(skin|colored_skin|dark_skin|pale_skin|freckles|"
        r"mole|facial_marks?|makeup)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "traits": re.compile(
        r"(?:^|[_\s-])(horns?|animal_ears|fox_ears|cat_ears|pointy_ears|"
        r"tail|whiskers?|fangs?|wings?)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "accessory": re.compile(
        r"(?:^|[_\s-])(glasses|eyepatch|hat|cap|ribbon|necktie|bowtie|"
        r"headband|hairband|earrings?|necklace|choker|bracelet|ring|belt|"
        r"brooch)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "clothing": re.compile(
        r"(?:^|[_\s-])(dress|uniform|school_uniform|shirt|blouse|skirt|"
        r"shorts|pants|trousers|jeans|jacket|coat|hoodie|sweater|cardigan|"
        r"swimsuit|bikini|apron|armor|kimono|yukata|sleeves?|bare_shoulders|"
        r"collarbone|collar|hood|cloak|cape|vest|overalls?|jumpsuit|romper|"
        r"leotard|bodysuit|turtleneck|tank_top|crop_top|underwear|lingerie|"
        r"panties|bra|garter|maid|lolita|gothic|casual|formal|off_shoulder|"
        r"sailor_collar|serafuku|suspenders?|frills?|lace|lace_trim|"
        r"clothing_cutout|cleavage_cutout|center_opening|detached_sleeves|"
        r"puffy_sleeves|juliet_sleeves|wide_sleeves|buttons?|zipper|pockets?)"
        r"(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "legwear": re.compile(
        r"(?:^|[_\s-])(socks?|stockings?|thighhighs?|pantyhose|bare_legs)"
        r"(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "footwear": re.compile(
        r"(?:^|[_\s-])(shoes?|boots?|sandals?|bare_feet)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "handwear": re.compile(
        r"(?:^|[_\s-])(gloves?|mittens?)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "pose": re.compile(
        r"(?:^|[_\s-])(standing|sitting|kneeling|lying|walking|running|"
        r"jumping|dancing|squatting|crouching|leaning|bent_over|reclining|"
        r"on_back|on_side|flying|spread_legs|leg_up|one_leg_up|legs_crossed|"
        r"dynamic_pose|on_one_knee|one_knee|all_fours|seiza|wariza|"
        r"indian_style|lotus_position|arched_back|bent_knees|legs_together|"
        r"feet_together|tiptoes|stretching|handstand|stance|contrapposto)"
        r"(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "gaze": re.compile(
        r"(?:^|[_\s-])(looking_at_viewer|looking_away|looking_back|"
        r"looking_up|looking_down|looking_to_the_side|looking_ahead|"
        r"from_behind|profile|facing_viewer|eye_contact)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "gesture": re.compile(
        r"(?:^|[_\s-])(holding|carrying|waving|fighting|arms_up|arms_crossed|"
        r"crossed_arms|hand_on_hip|hand_on_own_chest|head_tilt|hands_up|"
        r"hands_on_hips|arm_up)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "composition": re.compile(
        r"(?:^|[_\s-])(close[-_ ]up|upper_body|lower_body|cowboy_shot|"
        r"portrait|full_body|wide_shot|long_shot|medium_shot|headshot|"
        r"dutch_angle|from_above|from_below|from_side|front_view|side_view|"
        r"rear_view|profile_view|depth_of_field|foreshortening|"
        r"centered_composition|symmetrical_composition|rule_of_thirds|"
        r"dynamic_angle|fisheye|fisheye_lens|solo_focus|cropped|out_of_frame|"
        r"multiple_views)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "background": re.compile(
        r"(?:^|[_\s-])(background|simple_background|white_background|"
        r"black_background|gradient_background|indoors|outdoors|classroom|"
        r"school|bedroom|living_room|office|street|city|urban|forest|"
        r"beach|ocean|sea|mountain|park|garden|field|underwater|space)"
        r"(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "atmosphere": re.compile(
        r"(?:^|[_\s-])(sky|cloud|cloudy|sunset|sunrise|night|day|snow|rain|"
        r"winter|summer|autumn|spring|fog|mist)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "lighting": re.compile(
        r"(?:^|[_\s-])(lighting|light|soft_lighting|dramatic_lighting|"
        r"rim_lighting|backlighting|studio_lighting|cinematic_lighting|"
        r"volumetric_lighting|sunlight|moonlight|lens_flare|shadow|"
        r"high_contrast|low_contrast)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
    "style": re.compile(
        r"(?:^|[_\s-])(anime_style|manga_style|realistic|photorealistic|"
        r"watercolor|oil_painting|sketch|lineart|monochrome|pixel_art|"
        r"3d|cg|illustration|painting|rendering|abstract|anime_coloring|"
        r"official_art|game_cg|key_visual|concept_art|cel_shading|flat_color|"
        r"retro_artstyle|digital_media)(?:$|[_\s-])",
        re.IGNORECASE,
    ),
}

_IDENTITY_LINKED_CATEGORIES = {
    "hair",
    "eyes",
    "skin",
    "traits",
    "accessory",
    "clothing",
    "legwear",
    "footwear",
    "handwear",
}

_IDENTITY_MARKER = re.compile(
    r"(?:换成|改成|替换成|换为|改为|变成|角色(?:改成|换成|替换为|变为)|"
    r"(?<![A-Za-z0-9_])replace(?:\s+the)?\s+(?:character|subject|person)?\s*(?:with|by)|"
    r"(?<![A-Za-z0-9_])change(?:\s+the)?\s+(?:character|subject|person)?\s*(?:to|into)|"
    r"(?<![A-Za-z0-9_])switch(?:\s+to|\s+the))\s*[:：]?\s*",
    re.IGNORECASE,
)

_CATEGORY_MARKERS = {
    "hair": re.compile(
        r"(?:外观|发型|发色|头发|\b(?:appearance|hairstyle|hair)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "eyes": re.compile(
        r"(?:外观|瞳色|眼睛|眼神|\b(?:appearance|eyes?)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "skin": re.compile(
        r"(?:外观|肤色|皮肤|妆容|\b(?:appearance|skin|makeup)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "traits": re.compile(
        r"(?:外观|特征|耳朵|尾巴|翅膀|角|\b(?:appearance|traits?|ears?|tail|wings?|horns?)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "accessory": re.compile(
        r"(?:外观|饰品|配饰|眼镜|帽子|首饰|\b(?:appearance|accessory|accessories|glasses|hat)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "clothing": re.compile(
        r"(?:服装|衣服|穿着|衣着|换装|衣裳|\b(?:outfit|clothing|clothes|dress)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "legwear": re.compile(
        r"(?:袜子|丝袜|长袜|裤袜|腿部穿着|\b(?:legwear|socks?|stockings?|thighhighs?|pantyhose)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "footwear": re.compile(
        r"(?:鞋子|鞋|靴子|凉鞋|\b(?:footwear|shoes?|boots?|sandals?)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "handwear": re.compile(
        r"(?:手套|\b(?:handwear|gloves?|mittens?)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "pose": re.compile(
        r"(?:动作|姿势|姿态|\b(?:pose|action)\b)\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "gaze": re.compile(
        r"(?:动作|视线|朝向|目光|\b(?:gaze|looking|facing)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "gesture": re.compile(
        r"(?:动作|手势|手部动作|\b(?:gesture|action)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "expression": re.compile(
        r"(?:表情|神态|\bexpression\b)\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "composition": re.compile(
        r"(?:构图|镜头|视角|景别|\b(?:composition|camera|framing|shot)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "background": re.compile(
        r"(?:背景|场景|环境|\b(?:background|scene|environment)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "atmosphere": re.compile(
        r"(?:天气|时间|季节|氛围|天空|\b(?:weather|time|season|atmosphere|sky)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "lighting": re.compile(
        r"(?:光照|灯光|照明|\b(?:lighting|light)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "style": re.compile(
        r"(?:风格|画风|渲染|\b(?:style|rendering)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
    "subject": re.compile(
        r"(?:主体|人数|\b(?:subject|count)\b)"
        r"\s*(?:改成|换成|改为|换为|变成|to|into|:|：)?\s*",
        re.IGNORECASE,
    ),
}

_DIRECTIVE_WORDS = re.compile(
    r"(?:换成|改成|替换成|换为|改为|变成|角色|服装|衣服|穿着|衣着|换装|"
    r"动作|姿势|姿态|表情|神态|构图|镜头|视角|背景|场景|环境|光照|灯光|"
    r"风格|画风|人数|发型|发色|瞳色|肤色|饰品|袜子|鞋子|手套|视线|手势|"
    r"天气|时间|季节|(?<![A-Za-z0-9_])(?:replace|change|switch|character|"
    r"subject|person|outfit|clothing|clothes|legwear|footwear|handwear|pose|"
    r"action|gesture|gaze|expression|composition|camera|background|scene|"
    r"environment|atmosphere|lighting|style|count|to|into|with|by)"
    r"(?![A-Za-z0-9_]))",
    re.IGNORECASE,
)

_RETAG_MODE_ALIASES = {
    "edit": "edit",
    "replace": "edit",
    "改图": "edit",
    "修改": "edit",
    "replicate": "replicate",
    "copy": "replicate",
    "preserve": "replicate",
    "复刻": "replicate",
    "保留": "replicate",
}


def normalize_retag_mode(value: Any) -> str:
    """Normalize the two retag merge modes used by canvas and QQ flows."""

    key = str(value or "").strip().casefold()
    return _RETAG_MODE_ALIASES.get(key, "edit")


def extract_retag_mode(prompt: str) -> tuple[str, str]:
    """Read an optional ``--mode edit|replicate`` flag from a QQ prompt.

    The flag is deliberately explicit so ordinary words such as ``copy`` in a
    visual description are never consumed as a mode switch.
    """

    text = str(prompt or "")
    pattern = re.compile(
        r"(?<![^\s,，;；])--(?:retag-)?mode\s*(?:=|:|：|\s)\s*"
        r"(edit|replace|replicate|copy|preserve|改图|修改|复刻|保留)"
        r"(?=$|[\s,，;；])",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return "edit", text.strip()
    mode = normalize_retag_mode(match.group(1))
    cleaned = text[: match.start()] + " " + text[match.end() :]
    # Removing a flag between comma-separated tags can leave ``, ,`` behind.
    # Collapse adjacent separators, then trim punctuation at the prompt edges.
    cleaned = re.sub(r"\s*([,，;；])\s*(?:[,，;；]\s*)+", r"\1 ", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = cleaned.strip(" \t\r\n,，;；")
    return mode, cleaned

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
    for category in _CATEGORY_PATTERNS:
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


def _flatten_atoms(tokens: Iterable[str]) -> list[str]:
    values: list[str] = []
    for token in tokens:
        for atom in _atomic_tokens(token):
            value = str(atom or "").strip(" ,;\n\t")
            if value:
                values.append(value)
    return values


def _unique_atoms(tokens: Iterable[str]) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for atom in _flatten_atoms(tokens):
        key = _key(atom)
        if not key or key in seen:
            continue
        seen.add(key)
        values.append(atom)
    return values


def merge_retag_prompt_details(
    translated_user_prompt: str,
    retag_prompt: str,
    *,
    original_user_prompt: str = "",
    user_character: str = "",
    user_series: str = "",
    source_character: str = "",
    source_series: str = "",
    weight_user: bool = True,
    mode: str = "edit",
) -> Dict[str, Any]:
    """Merge image tags and return a structured conflict summary.

    ``edit`` treats plain user tags as category overrides. ``replicate`` keeps
    source categories unless the user writes an explicit replacement directive;
    a resolved character identity still counts as an explicit replacement.
    """
    merge_mode = normalize_retag_mode(mode)
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
    if user_character:
        identity_override = [
            token
            for value in (user_character, user_series)
            for token in _tokens(str(value or ""))
        ]
    elif identity_override:
        # Generic wording such as ``change to white_dress`` matches the same
        # verb used for a character replacement.  If every target atom is a
        # known visual category, route it to that category instead of deleting
        # the source character and its full visual signature.
        target_atoms = _unique_atoms(identity_override)
        target_categories = {
            category
            for atom in target_atoms
            if (category := _category_atom(atom))
        }
        has_uncategorized_target = any(not _category_atom(atom) for atom in target_atoms)
        if target_categories and not has_uncategorized_target:
            for category in target_categories:
                category_overrides[category] = [
                    atom for atom in target_atoms if _category_atom(atom) == category
                ]
            identity_override = []
    for category in _CATEGORY_PATTERNS:
        translated_tail = _extract_category_override(user_text, category)
        raw_tail = _extract_category_override(raw_user_text, category)
        tail = translated_tail or (
            user_text if raw_tail and user_text != raw_user_text else raw_tail
        )
        if tail:
            tail_tokens = _tokens(tail)
            tail_categories = {
                item
                for token in tail_tokens
                for item in _categories(token)
            }
            if not tail_categories or category in tail_categories:
                category_overrides[category] = tail_tokens
        if (
            category not in category_overrides
            and merge_mode == "edit"
            and _has_category(user_tokens, category)
        ):
            category_overrides[category] = [
                token for token in user_tokens if category in _categories(token)
            ]

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
                if _category_atom(atom) in _IDENTITY_LINKED_CATEGORIES:
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
        override_tokens: list[str] = []
        override_segment_keys: set[str] = set()
        for token in identity_override:
            key = _key(token)
            if key and key not in override_segment_keys:
                override_segment_keys.add(key)
                override_tokens.append(token)
        for values in category_overrides.values():
            for token in values:
                key = _key(token)
                if key and key not in override_segment_keys:
                    override_segment_keys.add(key)
                    override_tokens.append(token)

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

    merged_prompt = ", ".join(
        part for part in (merged_user, ", ".join(remaining)) if part
    ).strip(" ,")

    source_atoms = _flatten_atoms(source_tokens)
    user_atoms = _unique_atoms(user_tokens)
    source_keys = {_key(atom) for atom in source_atoms if _key(atom)}
    remaining_atoms = _unique_atoms(remaining)
    final_keys = {
        _key(atom)
        for atom in (*user_atoms, *remaining_atoms)
        if _key(atom)
    }
    added_atoms = [atom for atom in user_atoms if _key(atom) not in source_keys]
    retained_atoms: list[str] = []
    removed_atoms: list[str] = []
    duplicate_atoms: list[str] = []
    retained_seen: set[str] = set()
    removed_seen: set[str] = set()
    duplicate_seen: set[str] = set()
    source_seen: set[str] = set()
    for atom in source_atoms:
        key = _key(atom)
        if not key:
            continue
        if (key in user_keys or key in source_seen) and key not in duplicate_seen:
            duplicate_seen.add(key)
            duplicate_atoms.append(atom)
        source_seen.add(key)
        if key in final_keys and key not in retained_seen:
            retained_seen.add(key)
            retained_atoms.append(atom)
        elif key not in final_keys and key not in removed_seen:
            removed_seen.add(key)
            removed_atoms.append(atom)

    conflict_groups: dict[str, list[str]] = {}
    for atom in removed_atoms:
        category = _category_atom(atom) or "identity"
        conflict_groups.setdefault(category, []).append(atom)

    override_summary: dict[str, list[str]] = {}
    for category, values in category_overrides.items():
        category_atoms = [
            atom
            for atom in _unique_atoms(values)
            if category in _categories(atom)
        ]
        if category_atoms:
            override_summary[category] = category_atoms
    if identity_override:
        override_summary["identity"] = _unique_atoms(identity_override)

    return {
        "prompt": merged_prompt,
        "mode": merge_mode,
        "added": added_atoms,
        "removed": removed_atoms,
        "retained": retained_atoms,
        "duplicates": duplicate_atoms,
        "overrides": override_summary,
        "conflicts": conflict_groups,
    }


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
    mode: str = "edit",
) -> str:
    """Compatibility wrapper returning only the merged prompt string."""

    return str(
        merge_retag_prompt_details(
            translated_user_prompt,
            retag_prompt,
            original_user_prompt=original_user_prompt,
            user_character=user_character,
            user_series=user_series,
            source_character=source_character,
            source_series=source_series,
            weight_user=weight_user,
            mode=mode,
        )["prompt"]
    )

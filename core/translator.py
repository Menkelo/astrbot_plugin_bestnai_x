"""提示词翻译模块。

功能：
- 使用 LLM 将中文描述转换为 NovelAI / Danbooru 英文 tag。
- 支持 AstrBot 供应商对接。
- 优先使用 translator_provider_id 对应供应商。
- 翻译失败自动重试，默认最多 3 次。
- 支持 Danbooru 在线 tag 候选检索注入。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from .provider_utils import (
    ProviderRoutingError,
    call_provider,
    provider_model_of,
    response_text,
)
from .prompt_tokens import (
    expand_prompt_tokens,
    rebuild_weighted_token,
    split_prompt_tokens,
    weighted_token_parts,
)


SYSTEM_PROMPT = """
你是 NovelAI 4/4.5 提示词专家，精通 Danbooru 标签体系。
任务：把用户描述转换为紧凑、准确的英文 Danbooru / NovelAI tag 串。

输出规则：
- 只输出英文 tag，用英文逗号分隔；单行输出，不要解释、前缀或代码块。
- 禁止输出负面提示词。
- 禁止添加 masterpiece、best quality 等质量词。
- 不添加比例、尺寸或画幅控制 tag；这些由独立参数处理。
- 不添加输入中没有出现的视觉细节：不得臆造发色、发型、瞳色、服装、配饰、动作、表情、场景、天气、时间、光线、镜头或画风。
- 不为了凑数量扩写提示词；短输入保持短，不强行补足 tag。
- 相同概念只保留一个最准确的 tag，禁止同义词堆叠和重复。
- 已知二次元角色使用 Danbooru 角色名格式，如 hatsune_miku_(vocaloid)。角色身份必须以主搜索结果中的明确匹配为准；共现/related 候选不能替换用户明确指定的角色。
- 单人女性使用 solo, 1girl。
- 单人男性使用 solo, 1boy。
- 多人使用 2girls、2boys、1boy 1girl 等，不加 solo。
- 已知角色除非用户明确要求改变外貌，否则不要添加可能冲突的外貌 tag；不要添加 year 2025 等年份 tag。
- 只有用户明确表达强调或输入本身带权重时才使用 NovelAI 权重，格式必须正确，例如 {tag}, 1.2::tag::；不要任意给普通 tag 加权。
- 禁止输出中文。
""".strip()


def has_chinese(text: str) -> bool:
    """检测文本是否包含中文字符。"""

    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def normalize_translation_text(text: str) -> str:
    """Expand terse Chinese hair-color tags before sending them to an LLM.

    Some providers reject or mishandle two-character shorthand such as
    ``蓝发`` while translating the equivalent ``蓝头发`` reliably. This is
    request-only normalization; the original prompt remains unchanged in the
    canvas and cache metadata.
    """
    value = str(text or "")
    for color in ("蓝", "红", "黑", "白", "金", "棕", "紫", "粉", "绿"):
        value = value.replace(f"{color}发", f"{color}头发")
    return value


def resolve_translation_cache(
    prompt: str,
    requested_source: str,
    cached_source: str,
    cached_translation: str,
) -> Tuple[str, str, str]:
    """Resolve the Chinese segment, untranslated suffix, and reusable translation."""

    clean_prompt = str(prompt or "").strip()
    source = str(requested_source or "").strip()
    suffix = ""

    if not source or not has_chinese(source):
        source = clean_prompt
    elif clean_prompt == source:
        pass
    elif clean_prompt.startswith(f"{source},"):
        candidate_suffix = clean_prompt[len(source) :].strip(" ,")
        if has_chinese(candidate_suffix):
            source = clean_prompt
        else:
            suffix = candidate_suffix
    else:
        source = clean_prompt

    reusable = str(cached_translation or "").strip()
    if (
        str(cached_source or "").strip() != source
        or not reusable
        or has_chinese(reusable)
    ):
        reusable = ""

    return source, suffix, reusable


class TranslatorError(Exception):
    """翻译错误。"""

    pass


class TranslatedPrompt(str):
    """String result carrying deterministic Danbooru identity metadata."""

    character_tag: str
    series_tag: str

    def __new__(
        cls,
        value: str,
        character_tag: str = "",
        series_tag: str = "",
    ) -> "TranslatedPrompt":
        obj = str.__new__(cls, value or "")
        obj.character_tag = str(character_tag or "").strip()
        obj.series_tag = str(series_tag or "").strip()
        return obj


_SUBJECT_REPLACEMENT_VERB_RE = re.compile(
    r"(?:换成|改成|替换成|替换为|换为|改为|变成|replace|change|switch)",
    re.IGNORECASE,
)
_CHINESE_SUBJECT_REPLACEMENT_RE = re.compile(
    r"(?:换成|改成|替换成|替换为|换为|改为|变成)\s*(?P<target>[^,，。；;\n]+)",
    re.IGNORECASE,
)
_ENGLISH_SUBJECT_REPLACEMENT_RE = re.compile(
    r"\b(?:replace|change|switch)\s+"
    r"(?:(?:the\s+)?(?:character|subject|person)\s+)?"
    r"(?:(?:from|of)\s+)?"
    r"(?:(?P<old>[^,;\n]+?)\s+)?"
    r"(?:with|to|into|by)\s+(?P<target>[^,;\n]+)",
    re.IGNORECASE,
)
_SUBJECT_DIRECTIVE_RE = re.compile(
    r"^(?:请\s*)?(?:(?:我想|我希望|希望|想要|我要)\s*)?"
    r"(?:(?:把|将)\s*)?(?:(?:角色|人物|主角)\s*)?"
    r"(?:换成|改成|替换成|替换为|换为|改为|变成)\s*"
    r"|^(?:please\s*)?(?:replace|change|switch)\s+"
    r"(?:(?:the\s+)?(?:character|subject|person)\s*)?"
    r"(?:(?:with|to|into|by)\s*)?",
    re.IGNORECASE,
)
_IDENTITY_CONTEXT_RE = re.compile(
    r"(?:角色|人物|主角|character|subject|person)",
    re.IGNORECASE,
)
_NON_IDENTITY_DIRECTIVE_RE = re.compile(
    r"(?:外貌|发型|发色|头发|眼睛|瞳色|衣服|服装|穿着|裙子?|裤子?|鞋|袜|"
    r"动作|姿势|表情|服饰|装扮|appearance|hairstyle|hair|eyes?|outfit|"
    r"clothing|clothes|dress|uniform|pose|action|expression|background|scene)",
    re.IGNORECASE,
)

_DESCRIPTION_HINT_RE = re.compile(
    r"(?:头发|发色|发型|眼睛|瞳色|衣服|服装|裙|裤|鞋|袜|站立|坐着|"
    r"躺着|奔跑|动作|姿势|表情|微笑|哭|背景|场景|光照|镜头|视角|穿|"
    r"角色|人物|主角|女仆|泳装|海边|室内|户外|hair|eyes?|dress|uniform|maid|swimsuit|"
    r"standing|sitting|pose|background|lighting|outdoors?|indoors?)",
    re.IGNORECASE,
)

_ALIAS_SPLIT_RE = re.compile(r"[,，、;/|；]+")
_GENERIC_IDENTITY_ALIASES = {
    "girl",
    "girls",
    "boy",
    "boys",
    "character",
    "person",
    "teacher",
    "少女",
    "女孩",
    "男孩",
    "角色",
    "人物",
    "老师",
}
_PROTAGONIST_HINT_RE = re.compile(
    r"(?:女主角|男主角|主人公|主角|protagonist|main character)",
    re.IGNORECASE,
)


def _subject_query(text: str) -> str:
    value = str(text or "").strip()
    replacement_match = _CHINESE_SUBJECT_REPLACEMENT_RE.search(value)
    english_match = _ENGLISH_SUBJECT_REPLACEMENT_RE.search(value)

    target = ""
    if replacement_match:
        prefix = value[: replacement_match.start()]
        if _NON_IDENTITY_DIRECTIVE_RE.search(prefix[-32:]) and not _IDENTITY_CONTEXT_RE.search(
            prefix[-32:]
        ):
            return ""
        target = replacement_match.group("target")
    elif english_match:
        old = str(english_match.group("old") or "").strip()
        prefix = value[: english_match.start()]
        context = " ".join(part for part in (prefix, old) if part)
        if _NON_IDENTITY_DIRECTIVE_RE.search(context) and not _IDENTITY_CONTEXT_RE.search(
            context
        ):
            return ""
        target = english_match.group("target")
    elif _SUBJECT_REPLACEMENT_VERB_RE.search(value) and _NON_IDENTITY_DIRECTIVE_RE.search(
        value
    ):
        # Do not reinterpret "change outfit/pose/..." as a character change.
        return ""

    if target:
        value = target
    else:
        value = _SUBJECT_DIRECTIVE_RE.sub("", value, count=1)

    # Only truncate a clause after an explicit replacement target was
    # extracted.  For an ordinary description, keeping both sides of
    # "character A and character B" lets the resolver detect ambiguity rather
    # than silently selecting the first role.
    if target:
        value = re.split(r"(?:\s+and\s+|\s+并且\s+|\s+然后\s+)", value, maxsplit=1)[0]
    value = re.sub(
        r"^(?:please\s+)?(?:the\s+)?(?:character|subject|person)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = value.strip(" ,，。；;:：")
    if not value or len(value) > 96 or "\n" in value:
        return ""
    return value


def _normalized_alias(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def _safe_score(item: Dict, key: str = "score") -> float:
    if not isinstance(item, dict):
        return 0.0
    try:
        return float(item.get(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def _result_items(payload: Any) -> List[Dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return [item for item in payload["results"] if isinstance(item, dict)]
    return []


def _result_list(results: Any, key: str) -> List[Dict]:
    if not isinstance(results, dict):
        return []
    value = results.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _primary_aliases(item: Dict) -> List[str]:
    aliases = [str(item.get("tag") or "").strip()]
    cn_names = [
        part.strip()
        for part in _ALIAS_SPLIT_RE.split(str(item.get("cn_name") or ""))
        if part.strip()
    ]
    aliases.extend(cn_names)
    return list(dict.fromkeys(alias for alias in aliases if alias))


def _specific_alias(alias: str) -> bool:
    normalized = _normalized_alias(alias)
    if not normalized or normalized in {
        _normalized_alias(value) for value in _GENERIC_IDENTITY_ALIASES
    }:
        return False
    if re.search(r"[\u4e00-\u9fff]", alias):
        return len(normalized) >= 2
    return len(normalized) >= 3


def _alias_match_score(
    subject: str,
    alias: str,
    *,
    allow_prefix: bool,
    allow_contains: bool = False,
) -> int:
    subject_key = _normalized_alias(subject)
    alias_key = _normalized_alias(alias)
    if not subject_key or not alias_key or not _specific_alias(alias):
        return 0
    if subject_key == alias_key:
        return 1000 + len(alias_key)
    if allow_prefix and subject_key.startswith(alias_key):
        return 700 + len(alias_key)
    if allow_contains:
        if re.search(r"[\u4e00-\u9fff]", alias):
            if alias_key in subject_key:
                return 850 + len(alias_key)
        else:
            subject_fold = str(subject or "").casefold()
            alias_fold = str(alias or "").casefold()
            if re.search(
                rf"(?<![a-z0-9]){re.escape(alias_fold)}(?![a-z0-9])",
                subject_fold,
            ):
                return 850 + len(alias_key)
    return 0


def _cjk_variant_match_score(subject: str, alias: str) -> int:
    """Match a same-length CJK alias with one conservative variant/typo.

    The tags service may return a traditional-character alias such as
    ``遠坂凛`` while the user types the simplified ``远坂凛``.  This fallback
    is intentionally limited to same-length CJK strings and at most one
    differing character; broad fuzzy matching would reintroduce unrelated
    characters from the related-results list.
    """

    subject_value = str(subject or "").strip()
    alias_value = str(alias or "").strip()
    if (
        len(subject_value) < 2
        or len(subject_value) != len(alias_value)
        or not re.fullmatch(r"[\u3400-\u9fff]+", subject_value)
        or not re.fullmatch(r"[\u3400-\u9fff]+", alias_value)
    ):
        return 0

    differences = sum(left != right for left, right in zip(subject_value, alias_value))
    if differences > 1:
        return 0
    return 900 + len(subject_value) - differences


def _item_sources(item: Dict) -> List[str]:
    values = item.get("sources")
    if isinstance(values, str):
        sources = [values]
    elif isinstance(values, list):
        sources = [str(value or "").strip() for value in values]
    else:
        sources = []
    source = str(item.get("source") or "").strip()
    if source:
        sources.append(source)
    return [value for value in sources if value]


def _associated_series(character: Dict, copyrights: List[Dict]) -> Dict:
    source_keys = {_normalized_alias(value) for value in _item_sources(character)}
    source_keys.discard("")
    if not source_keys:
        return {}
    for item in copyrights:
        aliases = _primary_aliases(item)
        aliases.append(str(item.get("tag") or ""))
        if any(_normalized_alias(alias) in source_keys for alias in aliases if alias):
            return item
    return {}


def _character_aliases(character: Dict, copyrights: List[Dict]) -> List[str]:
    """Return aliases that identify the character rather than its work.

    Danbooru search results often copy the work title into a character's
    ``cn_name`` field (for example, every character from a series may list the
    same Chinese title).  Treating that shared title as a character alias
    makes a work-only query resolve to whichever character happened to be
    returned first.  Keep the canonical tag and character-specific aliases,
    while removing aliases also advertised by a copyright result.
    """
    copyright_aliases = {
        _normalized_alias(alias)
        for item in copyrights
        for alias in _primary_aliases(item)
        if _normalized_alias(alias)
    }
    return [
        alias
        for alias in _primary_aliases(character)
        if _normalized_alias(alias) not in copyright_aliases
    ]


def _tag_key(value: str) -> str:
    token = str(value or "").strip(" ,")
    _, inner, weighted = weighted_token_parts(token)
    if weighted:
        if len(inner) == 1:
            token = inner[0]
        else:
            return ", ".join(_tag_key(part) for part in inner if _tag_key(part))
    while len(token) >= 2 and (token[0], token[-1]) in {("{", "}"), ("[", "]")}:
        token = token[1:-1].strip()
    return re.sub(r"\s+", " ", token).casefold()


def tag_lookup_key(value: str) -> str:
    """Normalize a prompt atom and a canonical Danbooru tag to one key."""

    return re.sub(r"[\s_]+", "_", _tag_key(value)).strip("_")


def primary_cn_tag_name(value: str) -> str:
    """Return the first concise Chinese alias advertised by the tags site."""

    aliases = [
        part.strip()
        for part in _ALIAS_SPLIT_RE.split(str(value or ""))
        if part.strip()
    ]
    return next(
        (alias for alias in aliases if re.search(r"[\u4e00-\u9fff]", alias)),
        aliases[0] if aliases else "",
    )


def _prompt_tag_tokens(prompt: str) -> List[str]:
    """Return normalized, comma-separated prompt tokens for exact tag lookup."""
    return [token.strip() for token in expand_prompt_tokens(prompt) if token.strip()]


def _exact_prompt_identity(
    prompt: str,
    search_items: List[Dict],
    related_items: List[Dict],
) -> Tuple[str, str]:
    """Find canonical identity tags already present in an English prompt.

    This path is deliberately exact.  It is used for prompts read from PNG
    metadata, where the canonical character/copyright tags are already present
    and a semantic search would otherwise choose a nearby character.
    """
    tokens = _prompt_tag_tokens(prompt)
    token_keys = [_tag_key(token) for token in tokens]
    positions = {key: index for index, key in enumerate(token_keys) if key}
    if not positions:
        return "", ""

    all_items = [*search_items, *related_items]
    characters = []
    copyrights = []
    all_copyrights = []
    for order, item in enumerate(all_items):
        category = str(item.get("category") or "").casefold()
        if category == "copyright":
            all_copyrights.append(item)
        key = _tag_key(str(item.get("tag") or ""))
        if not key or key not in positions:
            continue
        entry = (positions[key], -_safe_score(item), -order, item)
        if category == "character":
            characters.append(entry)
        elif category == "copyright":
            copyrights.append(entry)

    matched_character_keys = {
        _tag_key(str(entry[3].get("tag") or ""))
        for entry in characters
        if _tag_key(str(entry[3].get("tag") or ""))
    }
    # A prompt can legitimately contain two named characters.  The metadata
    # fields carried by this plugin are singular, so do not silently choose
    # one and delete the other from a multi-character prompt.
    if len(matched_character_keys) > 1:
        return "", ""

    character = min(characters, key=lambda entry: entry[:3])[3] if characters else {}
    series = min(copyrights, key=lambda entry: entry[:3])[3] if copyrights else {}

    if character and not series:
        series = _associated_series(character, all_copyrights)

    return str(character.get("tag") or ""), str(series.get("tag") or "")


def prompt_has_tag(prompt: str, tag: str) -> bool:
    target = _tag_key(tag)
    if not target:
        return False
    return any(_tag_key(token) == target for token in expand_prompt_tokens(prompt))


def resolve_character_candidate(
    query: str,
    results: Dict[str, List[Dict]],
) -> Tuple[str, str]:
    """Resolve an explicitly matched character and its associated series."""
    search_items = _result_list(results, "search")
    related_items = _result_list(results, "related")

    # A replacement instruction may contain both the old and new canonical
    # names.  Resolve the extracted target, not the complete sentence, before
    # applying the shorter natural-language matcher.
    subject = _subject_query(query)
    exact_query = subject if subject and subject != str(query or "").strip() else query

    # A metadata prompt is usually a long English tag list.  Resolve exact
    # canonical tags before applying the shorter natural-language matcher.
    exact_character, exact_series = _exact_prompt_identity(
        exact_query,
        search_items,
        related_items,
    )
    if exact_character:
        return exact_character, exact_series

    if not subject:
        return "", ""

    all_items = [*search_items, *related_items]
    search_characters = [
        item
        for item in search_items
        if str(item.get("category") or "").casefold() == "character"
    ]
    related_characters = [
        item
        for item in related_items
        if str(item.get("category") or "").casefold() == "character"
    ]
    copyrights = [
        item
        for item in all_items
        if str(item.get("category") or "").casefold() == "copyright"
    ]

    def collect_direct_matches(characters: List[Dict], *, allow_cjk_variant: bool):
        matches = []
        for order, item in enumerate(characters):
            aliases = _character_aliases(item, copyrights)
            score = max(
                (
                    max(
                        _alias_match_score(
                            subject,
                            alias,
                            allow_prefix=True,
                            allow_contains=True,
                        ),
                        _cjk_variant_match_score(subject, alias)
                        if allow_cjk_variant
                        else 0,
                    )
                    for alias in aliases
                ),
                default=0,
            )
            if score:
                matches.append((score, _safe_score(item), -order, item))
        return matches

    # Related results frequently contain relationship aliases (for example,
    # Matou Sakura's entry can list Tohsaka Rin).  A direct hit from the main
    # search must always win over those related aliases.
    direct_matches = collect_direct_matches(
        search_characters,
        allow_cjk_variant=True,
    )
    if not direct_matches:
        direct_matches = collect_direct_matches(
            related_characters,
            allow_cjk_variant=False,
        )

    if direct_matches:
        matched_character_keys = {
            _tag_key(str(entry[3].get("tag") or ""))
            for entry in direct_matches
            if _tag_key(str(entry[3].get("tag") or ""))
        }
        strong_matches = [entry for entry in direct_matches if entry[0] >= 1000]
        if len(matched_character_keys) > 1 and len(strong_matches) != 1:
            # Multiple named roles in one request are ambiguous.  Leave the
            # source prompt intact instead of deleting one character because
            # it happened to sort first in the tags results.
            return "", ""
        candidates = strong_matches or direct_matches
        character = max(candidates, key=lambda entry: entry[:3])[3]
        series = _associated_series(character, copyrights)
        return str(character.get("tag") or ""), str(series.get("tag") or "")

    # No direct character hit: retain the existing series-level fallback below.
    allow_series_prefix = bool(_DESCRIPTION_HINT_RE.search(subject))
    series_matches = []
    for order, item in enumerate(copyrights):
        score = max(
            (
                _alias_match_score(
                    subject,
                    alias,
                    allow_prefix=allow_series_prefix,
                )
                for alias in _primary_aliases(item)
            ),
            default=0,
        )
        if score:
            series_matches.append((score, _safe_score(item), -order, item))

    if not series_matches:
        return "", ""

    series = max(series_matches, key=lambda entry: entry[:3])[3]
    series_score = _safe_score(series)
    competing_general = any(
        str(item.get("category") or "").casefold() == "general"
        and _safe_score(item) >= series_score
        and any(
            _alias_match_score(subject, alias, allow_prefix=allow_series_prefix)
            for alias in _primary_aliases(item)
        )
        for item in search_items
    )
    if competing_general:
        return "", ""

    series_key = _normalized_alias(str(series.get("tag") or ""))
    linked_characters = [
        item
        for item in related_items
        if str(item.get("category") or "").casefold() == "character"
        and series_key in {_normalized_alias(value) for value in _item_sources(item)}
    ]
    if not linked_characters:
        return "", ""

    character = max(
        enumerate(linked_characters),
        key=lambda entry: (
            bool(_PROTAGONIST_HINT_RE.search(str(entry[1].get("wiki") or ""))),
            -entry[0],
        ),
    )[1]
    return str(character.get("tag") or ""), str(series.get("tag") or "")


def apply_character_candidate(
    translated: str,
    character_tag: str,
    series_tag: str,
    results: Dict[str, List[Dict]],
) -> str:
    if not character_tag:
        return translated

    identity_items = [
        *_result_list(results, "search"),
        *_result_list(results, "related"),
    ]
    candidate_character_tags = {
        _tag_key(str(item.get("tag") or ""))
        for item in identity_items
        if str(item.get("category") or "").casefold() == "character"
    }
    candidate_series_tags = {
        _tag_key(str(item.get("tag") or ""))
        for item in identity_items
        if str(item.get("category") or "").casefold() == "copyright"
    }
    selected_character_key = _tag_key(character_tag)
    selected_series_key = _tag_key(series_tag)
    kept: List[str] = []
    seen_keys = set()
    for segment in split_prompt_tokens(str(translated or "")):
        weight, atoms, weighted = weighted_token_parts(segment)
        kept_atoms: List[str] = []
        for atom in atoms:
            token = atom.strip(" ,")
            key = _tag_key(token)
            if not token or key.replace("_", " ") == "year 2025":
                continue
            if key in candidate_character_tags and key != selected_character_key:
                continue
            if selected_series_key and key in candidate_series_tags and key != selected_series_key:
                continue
            if key in {selected_character_key, selected_series_key}:
                continue
            if key in seen_keys:
                continue
            kept_atoms.append(token)
            seen_keys.add(key)

        if not kept_atoms:
            continue
        kept.append(
            rebuild_weighted_token(weight, kept_atoms)
            if weighted
            else ", ".join(kept_atoms)
        )

    ordered = [character_tag]
    if series_tag:
        ordered.append(series_tag)
    ordered.extend(kept)
    return ", ".join(ordered)


class DanbooruTagRetriever:
    """Danbooru 在线 tag 候选检索器。"""

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def lookup_tags(self, tags: List[str]) -> Dict[str, Any]:
        """Resolve exact English tags and their Chinese names in one request."""

        requested: Dict[str, str] = {}
        for raw_tag in tags:
            key = tag_lookup_key(raw_tag)
            query_tag = _tag_key(raw_tag)
            if key and query_tag and key not in requested:
                requested[key] = query_tag
        empty: Dict[str, Any] = {"items": [], "translations": {}}
        if not requested:
            return empty

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(
                    f"{self.base_url}/api/search",
                    json={
                        "query": ", ".join(requested.values()),
                        "top_k": min(50, max(10, len(requested))),
                        "limit": min(500, max(80, len(requested) * 4)),
                        "popularity_weight": 0.0,
                        "show_nsfw": False,
                        "use_segmentation": True,
                        "target_layers": ["英文"],
                        "group_mode": "off",
                    },
                ) as resp:
                    if resp.status != 200:
                        return empty
                    payload = await resp.json()
        except Exception:
            return empty

        items: List[Dict[str, Any]] = []
        translations: Dict[str, str] = {}
        seen = set()
        for item in _result_items(payload):
            tag = str(item.get("tag") or "").strip()
            key = tag_lookup_key(tag)
            if not tag or key not in requested or key in seen:
                continue
            seen.add(key)
            clean_item = {
                "tag": tag,
                "cn_name": str(item.get("cn_name") or "").strip(),
                "category": str(item.get("category") or "General"),
                "source": str(item.get("source") or ""),
                "layer": str(item.get("layer") or ""),
                "sources": item.get("sources", []),
                "wiki": str(item.get("wiki") or ""),
            }
            items.append(clean_item)
            cn_name = primary_cn_tag_name(clean_item["cn_name"])
            if cn_name:
                translations[key] = cn_name

        return {"items": items, "translations": translations}

    async def retrieve(self, query: str) -> Dict[str, List[Dict]]:
        """检索语义匹配和共现推荐 tag。失败返回空结构。"""

        empty = {"search": [], "related": []}
        query = str(query or "").strip()

        if not query:
            return empty

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout)
            ) as session:
                async with session.post(
                    f"{self.base_url}/api/search",
                    json={
                        "query": query,
                        "top_k": 5,
                        "limit": 30,
                        "popularity_weight": 0.15,
                        "show_nsfw": False,
                        "use_segmentation": True,
                    },
                ) as resp:
                    if resp.status != 200:
                        return empty

                    search_data = await resp.json()

                search_results = []

                for item in _result_items(search_data):
                    tag = item.get("tag")
                    if not tag:
                        continue

                    search_results.append(
                        {
                            "tag": tag,
                            "cn_name": item.get("cn_name", ""),
                            "score": item.get("final_score", 0.0),
                            "category": item.get("category", "General"),
                            "source": item.get("source", ""),
                            "layer": item.get("layer", ""),
                            "sources": item.get("sources", []),
                            "wiki": item.get("wiki", ""),
                        }
                    )

                if not search_results:
                    return empty

                seed_tags = [r["tag"] for r in search_results[:8]]
                related_results = []

                async with session.post(
                    f"{self.base_url}/api/related",
                    json={"tags": seed_tags, "limit": 20, "show_nsfw": False},
                ) as resp:
                    if resp.status == 200:
                        related_data = await resp.json()
                        items = _result_items(related_data)
                        search_tag_set = {r["tag"] for r in search_results}

                        for item in items:
                            tag = item.get("tag")
                            if not tag or tag in search_tag_set:
                                continue

                            related_results.append(
                                {
                                    "tag": tag,
                                    "cn_name": item.get("cn_name", ""),
                                    "cooc_score": item.get(
                                        "cooc_score",
                                        item.get("score", item.get("final_score", 0.0)),
                                    ),
                                    "category": item.get("category", "General"),
                                    "source": item.get("source", ""),
                                    "layer": item.get("layer", ""),
                                    "sources": item.get("sources", []),
                                    "wiki": item.get("wiki", ""),
                                }
                            )

                return {
                    "search": search_results,
                    "related": related_results,
                }

        except Exception:
            return empty

    def format_candidates(self, results: Dict[str, List[Dict]]) -> str:
        """格式化为可注入 LLM 的文本块。"""

        search_items = _result_list(results, "search")
        related_items = _result_list(results, "related")

        if not search_items and not related_items:
            return ""

        lines = [
            "<tag_candidates>",
            "以下是从 Danbooru 数据库检索到的候选标签，仅供参考：",
            "",
        ]

        if search_items:
            lines.append("## 语义匹配")
            for item in search_items:
                cn = f"{item['cn_name']} → " if item.get("cn_name") else ""
                lines.append(
                    f"- {cn}{item['tag']} [{item['category']}] "
                    f"(相关度 {_safe_score(item):.2f})"
                )

        if related_items:
            lines.append("")
            lines.append("## 共现推荐")
            for item in related_items:
                cn = f"{item['cn_name']} → " if item.get("cn_name") else ""
                lines.append(
                    f"- {cn}{item['tag']} [{item['category']}] "
                    f"(共现度 {_safe_score(item, 'cooc_score'):.2f})"
                )

        lines += [
            "",
            "使用规则：",
            "- 主搜索区的明确角色/作品命中优先于共现推荐。",
            "- related / 共现推荐只能作为场景参考，不能把另一个角色当成用户指定角色。",
            "- 候选 tag 不完整时只翻译输入中明确出现的内容，不要臆造或凑数量。",
            "- 与描述不符的候选必须忽略。",
            "</tag_candidates>",
        ]

        return "\n".join(lines)


class PromptTranslator:
    """提示词翻译器。"""

    def __init__(self, config, context: Any = None):
        self.config = config
        self.context = context
        # translate() 失败时不抛异常，把最后一次异常留在这里，供上层拼失败原因
        self.last_error: Optional[Exception] = None
        self.last_character_tag = ""
        self.last_series_tag = ""

    async def translate(self, text: str, danbooru_api_url: str = "") -> str:
        """将中文描述翻译为英文提示词。

        失败时返回原文，由上层逻辑决定是否中断。
        """

        self.last_error = None
        self.last_character_tag = ""
        self.last_series_tag = ""

        if not self.config.enabled:
            return text

        if not has_chinese(text):
            return text

        if not self.config.is_configured():
            return text

        max_retries = int(getattr(self.config, "max_retries", 3) or 3)
        max_retries = max(1, min(max_retries, 5))

        last_error: Optional[Exception] = None

        request_text = normalize_translation_text(text)

        for attempt in range(1, max_retries + 1):
            try:
                translated = await self._call_llm(
                    request_text,
                    danbooru_api_url=danbooru_api_url,
                )
                return TranslatedPrompt(
                    translated,
                    character_tag=self.last_character_tag,
                    series_tag=self.last_series_tag,
                )

            except Exception as e:
                last_error = e

                try:
                    from astrbot.api import logger

                    logger.warning(
                        f"[BestNAI] 翻译失败，第 {attempt}/{max_retries} 次：{e}"
                    )
                except Exception:
                    pass

                if attempt < max_retries:
                    await asyncio.sleep(min(2 ** (attempt - 1), 5))

        try:
            from astrbot.api import logger

            logger.warning(f"[BestNAI] 翻译最终失败，使用原文: {last_error}")
        except Exception:
            pass

        self.last_error = last_error

        return text

    async def _call_llm(self, text: str, danbooru_api_url: str = "") -> str:
        """调用 LLM。"""

        system_prompt = (
            self.config.system_prompt.strip()
            if getattr(self.config, "system_prompt", "").strip()
            else SYSTEM_PROMPT
        )

        if getattr(self.config, "custom_prefix", "").strip():
            system_prompt = self.config.custom_prefix.strip() + "\n\n" + system_prompt

        tag_candidates_block = ""
        results: Dict[str, List[Dict]] = {"search": [], "related": []}

        if danbooru_api_url:
            try:
                retriever = DanbooruTagRetriever(base_url=danbooru_api_url, timeout=8.0)
                results = await retriever.retrieve(text)
                tag_candidates_block = retriever.format_candidates(results)

                if tag_candidates_block:
                    from astrbot.api import logger

                    logger.info(
                        f"[BestNAI] Danbooru 检索完成："
                        f"{len(results['search'])} 条语义匹配，"
                        f"{len(results['related'])} 条共现推荐"
                    )

            except Exception as e:
                try:
                    from astrbot.api import logger

                    logger.warning(f"[BestNAI] Danbooru 检索失败，跳过: {e}")
                except Exception:
                    pass

        final_system_prompt = system_prompt

        if tag_candidates_block:
            final_system_prompt = f"{system_prompt}\n\n{tag_candidates_block}"

        configured_provider_id = str(
            getattr(self.config, "provider_id", "") or ""
        ).strip()
        if not configured_provider_id:
            raise TranslatorError("翻译器未选择 AstrBot 提供商")

        # AstrBot owns endpoint construction, authentication, proxy handling,
        # model selection and request formatting.  Never reconstruct /v1 or a
        # provider-specific POST endpoint inside this plugin.
        try:
            provider_id, provider_obj, response = await call_provider(
                self.context,
                configured_provider_id,
                prompt=text,
                system_prompt=final_system_prompt,
                temperature=0.2,
                max_tokens=2000,
            )
        except ProviderRoutingError as exc:
            raise TranslatorError(str(exc)) from exc
        except Exception as exc:
            raise TranslatorError(f"调用翻译提供商失败：{exc}") from exc

        translated = self._clean_result(response_text(response))
        if not translated:
            raise TranslatorError(f"翻译提供商 {provider_id} 返回空内容")

        try:
            from astrbot.api import logger

            logger.info(
                f"[BestNAI] 使用 AstrBot 翻译供应商：{provider_id}，"
                f"model={provider_model_of(provider_obj) or '(当前模型)'}"
            )
        except Exception:
            pass

        character_tag, series_tag = resolve_character_candidate(text, results)
        self.last_character_tag = character_tag
        self.last_series_tag = series_tag
        return apply_character_candidate(
            translated,
            character_tag,
            series_tag,
            results,
        )

    def _clean_result(self, result: str) -> str:
        """清理模型输出。"""

        result = (result or "").strip()

        result = re.sub(
            r"^```(?:text|txt|markdown)?",
            "",
            result,
            flags=re.IGNORECASE,
        ).strip()

        result = re.sub(r"```$", "", result).strip()

        result = re.sub(
            r"^(prompt|tags|tag|英文提示词|提示词)\s*[:：]\s*",
            "",
            result,
            flags=re.IGNORECASE,
        ).strip()

        lines = [line.strip() for line in result.splitlines() if line.strip()]

        if len(lines) > 1:
            result = ", ".join(lines)

        result = result.strip("`\"' ")

        return result

"""提示词翻译模块。

功能：
- 使用 LLM 将中文描述转换为 NovelAI / Danbooru 英文 tag。
- 支持 AstrBot 供应商对接。
- 优先使用 translator_provider_id 对应供应商。
- 兼容 OpenAI API 格式。
- 兼容 Gemini 官方 generativelanguage.googleapis.com。
- 翻译失败自动重试，默认最多 3 次。
- 保留旧 translator_base_url / translator_api_key / translator_model 作为 fallback。
- 支持 Danbooru 在线 tag 候选检索注入。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import aiohttp

from .prompt_tokens import (
    expand_prompt_tokens,
    rebuild_weighted_token,
    split_prompt_tokens,
    weighted_token_parts,
)


SYSTEM_PROMPT = """
你是 NovelAI 4/4.5 提示词专家，精通 Danbooru 标签体系。
任务：把用户中文描述转换为高质量英文 Danbooru tag 串。

输出规则：
- 只输出英文 tag，用英文逗号分隔。
- 禁止解释、禁止前缀、禁止代码块。
- 禁止输出负面提示词。
- 禁止添加 masterpiece、best quality 等质量词。
- 已知二次元角色使用 Danbooru 角色名格式，如 hatsune_miku_(vocaloid)。
- 单人女性使用 solo, 1girl。
- 单人男性使用 solo, 1boy。
- 多人使用 2girls、2boys、1boy 1girl 等，不加 solo。
- 只有原创人物或用户明确要求现代年份风格时才添加 year 2025；已知角色名禁止添加年份 tag。
- 如果是原创人物，需要补充发色、发型、瞳色、服装、动作、表情、场景、光影。
- 如果是已知角色，除非用户明确要求改变外貌，否则不要额外补发色、发型、瞳色等容易冲突的外貌 tag。
- 使用 NovelAI 权重时，格式必须正确，例如 {tag}, 1.2::tag::。
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
    characters = [
        item
        for item in all_items
        if str(item.get("category") or "").casefold() == "character"
    ]
    copyrights = [
        item
        for item in all_items
        if str(item.get("category") or "").casefold() == "copyright"
    ]

    direct_matches = []
    for order, item in enumerate(characters):
        score = max(
            (
                _alias_match_score(
                    subject,
                    alias,
                    allow_prefix=True,
                    allow_contains=True,
                )
                for alias in _character_aliases(item, copyrights)
            ),
            default=0,
        )
        if score:
            direct_matches.append((score, _safe_score(item), -order, item))

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


@dataclass
class ResolvedProvider:
    """解析后的翻译供应商配置。"""

    name: str
    api_type: str
    base_url: str
    api_key: str
    model: str


class DanbooruTagRetriever:
    """Danbooru 在线 tag 候选检索器。"""

    def __init__(self, base_url: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

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
            "- 与用户描述相关的候选 tag 可优先采用。",
            "- 候选 tag 不完整时，用你自己的 Danbooru 知识补充。",
            "- 与描述不符的候选必须忽略。",
            "</tag_candidates>",
        ]

        return "\n".join(lines)


class PromptTranslator:
    """提示词翻译器。"""

    def __init__(self, config, context: Any = None):
        self.config = config
        self.context = context
        self.timeout = 60
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

    def _resolve_provider(self) -> ResolvedProvider:
        """解析翻译供应商。

        优先级：
        1. translator_provider_id 对应 AstrBot 供应商。
        2. 旧配置 translator_base_url / translator_api_key / translator_model。
        """

        provider_id = getattr(self.config, "provider_id", "") or ""

        if provider_id and self.context is not None:
            provider = self.context.get_provider_by_id(provider_id)

            if not provider:
                raise TranslatorError(f"找不到翻译供应商 ID: {provider_id}")

            p_conf = getattr(provider, "provider_config", {}) or {}

            base_url = (
                getattr(provider, "api_base", "")
                or p_conf.get("api_base")
                or p_conf.get("api_base_url")
                or p_conf.get("base_url")
                or "https://generativelanguage.googleapis.com"
            )
            base_url = str(base_url).rstrip("/")

            api_key = ""

            for k in ("key", "keys", "api_key", "access_token"):
                val = p_conf.get(k)

                if isinstance(val, str) and val.strip():
                    api_key = val.strip()
                    break

                if isinstance(val, list) and val:
                    for item in val:
                        if isinstance(item, str) and item.strip():
                            api_key = item.strip()
                            break

                    if api_key:
                        break

            model = (
                getattr(provider, "model", "")
                or p_conf.get("model")
                or getattr(self.config, "model", "")
                or "gpt-4o-mini"
            )
            model = str(model).strip()

            api_type = "openai"

            if "generativelanguage.googleapis.com" in base_url:
                api_type = "gemini"
            elif "aiplatform.googleapis.com" in base_url:
                api_type = "vertex"
            else:
                api_type = "openai"

            if not api_key and api_type != "vertex":
                raise TranslatorError(f"翻译供应商 {provider_id} 缺少 API Key")

            return ResolvedProvider(
                name=provider_id,
                api_type=api_type,
                base_url=base_url,
                api_key=api_key,
                model=model,
            )

        base_url = getattr(self.config, "base_url", "") or ""
        api_key = getattr(self.config, "api_key", "") or ""
        model = getattr(self.config, "model", "") or "gpt-4o-mini"

        if not base_url or not api_key:
            raise TranslatorError("翻译器未配置 provider_id，也未配置 base_url/api_key")

        base_url = base_url.rstrip("/")

        api_type = "gemini" if "generativelanguage.googleapis.com" in base_url else "openai"

        return ResolvedProvider(
            name="manual_translator",
            api_type=api_type,
            base_url=base_url,
            api_key=api_key,
            model=model,
        )

    async def _call_llm(self, text: str, danbooru_api_url: str = "") -> str:
        """调用 LLM。"""

        provider = self._resolve_provider()

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

        try:
            from astrbot.api import logger

            logger.info(
                f"[BestNAI] 使用翻译供应商：{provider.name} "
                f"type={provider.api_type}, model={provider.model}"
            )
        except Exception:
            pass

        if provider.api_type == "gemini":
            translated = await self._call_gemini(provider, final_system_prompt, text)

        elif provider.api_type == "vertex":
            raise TranslatorError(
                "当前 BestNAI 翻译器暂不直接支持 Vertex 供应商。"
                "请使用 OpenAI 兼容供应商或 Gemini API 供应商。"
            )

        else:
            translated = await self._call_openai_compatible(
                provider,
                final_system_prompt,
                text,
            )

        character_tag, series_tag = resolve_character_candidate(text, results)
        self.last_character_tag = character_tag
        self.last_series_tag = series_tag
        return apply_character_candidate(
            translated,
            character_tag,
            series_tag,
            results,
        )

    async def _call_openai_compatible(
        self,
        provider: ResolvedProvider,
        system_prompt: str,
        text: str,
    ) -> str:
        """调用 OpenAI 兼容接口。"""

        base = provider.base_url.rstrip("/")

        if base.endswith("/v1"):
            url = f"{base}/chat/completions"
        else:
            url = f"{base}/v1/chat/completions"

        payload = {
            "model": provider.model,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                body = await resp.text()

                if resp.status != 200:
                    raise TranslatorError(
                        f"OpenAI 兼容翻译接口返回 {resp.status}: {body[:300]}"
                    )

                try:
                    data = await resp.json(content_type=None)
                    result = data["choices"][0]["message"]["content"].strip()
                except Exception as e:
                    raise TranslatorError(f"解析 OpenAI 兼容翻译响应失败: {e}") from e

                return self._clean_result(result)

    async def _call_gemini(
        self,
        provider: ResolvedProvider,
        system_prompt: str,
        text: str,
    ) -> str:
        """调用 Gemini 官方 API。

        支持：
        - https://generativelanguage.googleapis.com
        - https://generativelanguage.googleapis.com/v1beta
        - https://generativelanguage.googleapis.com/v1
        """

        base = provider.base_url.rstrip("/")

        if base.endswith("/v1beta") or base.endswith("/v1"):
            url = f"{base}/models/{provider.model}:generateContent"
        else:
            url = f"{base}/v1beta/models/{provider.model}:generateContent"

        user_text = (
            f"{system_prompt}\n\n"
            f"用户输入：{text}\n\n"
            f"请只输出最终英文 Danbooru tag 串，不要解释。"
        )

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "text": user_text,
                        }
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2000,
            },
        }

        headers = {
            "Content-Type": "application/json",
            # 放在请求头而不是 URL query，避免 API Key 随异常消息进日志
            "x-goog-api-key": provider.api_key,
        }

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.timeout)
        ) as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                body = await resp.text()

                if resp.status != 200:
                    raise TranslatorError(
                        f"Gemini 翻译接口返回 {resp.status}: {body[:300]}"
                    )

                try:
                    data = await resp.json(content_type=None)
                    candidates = data.get("candidates", [])

                    if not candidates:
                        raise TranslatorError("Gemini 返回 candidates 为空")

                    parts = candidates[0].get("content", {}).get("parts", [])

                    result = "\n".join(
                        p.get("text", "") for p in parts if isinstance(p, dict)
                    ).strip()

                    if not result:
                        raise TranslatorError("Gemini 返回文本为空")

                    return self._clean_result(result)

                except TranslatorError:
                    raise
                except Exception as e:
                    raise TranslatorError(f"解析 Gemini 翻译响应失败: {e}") from e

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

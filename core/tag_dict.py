"""本地 Danbooru 标签表：校验、别名归一、中文直查、在线服务兜底。

在线标签服务（`danbooru_api_url`）做的是**语义检索**——`/api/search` 带
`top_k`、分词与热度加权，`/api/related` 给共现推荐。本地这张表做不了语义
检索，它只是一张 `tag → 热度 / 中文名 / 别名` 的查找表，所以定位是**垫在
在线服务下面**，不是替代它：

1. **校验**——LLM 翻译出来的 tag 常有幻觉（Danbooru 里根本不存在的词），
   拿 14 万条真实标签一比就能认出来
2. **归一**——`high_res` / `high_resolution` / `hires` 统一成 `highres`
3. **中文直查**——"双马尾"直接命中 `twintails`，不过 LLM 也不过网络
4. **兜底**——在线服务休眠或超时的那 30~60 秒里，标签注音仍然有中文名

表在首次使用时加载（约 0.6 秒、常驻约 38 MB）。加载失败一律降级成空表：
读不到词库只该让上面四件事失效，不该让生图失败。
"""

from __future__ import annotations

import asyncio
import re
import threading
from pathlib import Path
from typing import Dict, NamedTuple, Tuple

ASSET_PATH = Path(__file__).resolve().parent.parent / "assets" / "danbooru.tsv"

_CJK_RE = re.compile(r"[一-鿿]")


class TagTables(NamedTuple):
    """tag → (热度, 中文名串)、别名 → 主 tag、中文名 → 主 tag。"""

    tags: Dict[str, Tuple[int, str]]
    aliases: Dict[str, str]
    chinese: Dict[str, str]


_EMPTY = TagTables(tags={}, aliases={}, chinese={})

_tables: TagTables | None = None
_load_lock = threading.Lock()


def _log_warning(message: str) -> None:
    try:
        from astrbot.api import logger

        logger.warning(message)
    except Exception:
        pass


def _log_info(message: str) -> None:
    try:
        from astrbot.api import logger

        logger.info(message)
    except Exception:
        pass


def normalize_key(value: str) -> str:
    """把提示词原子与词库里的标准 tag 归一到同一个键。

    与 ``translator.tag_lookup_key`` 同口径：小写、空格与下划线统一成下划线。
    这里不复用那个函数是为了避免 translator ↔ tag_dict 的循环导入，两边的
    规则很短，各自实现比拆第三个模块更简单。
    """
    text = re.sub(r"\s+", " ", str(value or "").strip(" ,")).casefold()
    return re.sub(r"[\s_]+", "_", text).strip("_")


def _load_tables() -> TagTables:
    tags: Dict[str, Tuple[int, str]] = {}
    aliases: Dict[str, str] = {}
    chinese: Dict[str, str] = {}

    try:
        with ASSET_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 3:
                    continue

                tag = normalize_key(parts[0])
                if not tag:
                    continue

                popularity = int(parts[1]) if parts[1].isdigit() else 0
                cn_names = parts[2]
                tags[tag] = (popularity, cn_names)

                # 词库按热度降序排列，重复的别名/中文名保留先出现的那条，
                # 也就是更热门的那个 tag。
                if len(parts) > 3 and parts[3]:
                    for alias in parts[3].split(","):
                        key = normalize_key(alias)
                        if key and key not in aliases:
                            aliases[key] = tag

                for name in cn_names.split(","):
                    key = name.strip()
                    if key and key not in chinese:
                        chinese[key] = tag

    except FileNotFoundError:
        _log_warning(f"[BestNAI] 本地标签词库缺失：{ASSET_PATH}，校验与中文直查已停用")
        return _EMPTY
    except Exception as exc:  # pragma: no cover - 损坏的词库不该拖垮生图
        _log_warning(f"[BestNAI] 本地标签词库加载失败：{exc}")
        return _EMPTY

    _log_info(
        f"[BestNAI] 本地标签词库就绪：{len(tags)} 标签 / "
        f"{len(aliases)} 别名 / {len(chinese)} 中文名"
    )
    return TagTables(tags=tags, aliases=aliases, chinese=chinese)


def tables() -> TagTables:
    """返回词库，首次调用时同步加载。"""
    global _tables

    if _tables is None:
        with _load_lock:
            if _tables is None:
                _tables = _load_tables()

    return _tables


async def warm_up() -> None:
    """在工作线程里完成首次加载，避免 0.6 秒解析卡住事件循环。"""
    if _tables is None:
        await asyncio.to_thread(tables)


def is_known_tag(tag: str) -> bool:
    """该 tag 是否真实存在于 Danbooru（含别名）。词库缺失时一律返回 True。

    返回 True 表示"没有证据说它是假的"。词库读不到时不能把所有 tag 都判成
    幻觉，那会比不校验更糟。
    """
    data = tables()
    if not data.tags:
        return True

    key = normalize_key(tag)
    return bool(key) and (key in data.tags or key in data.aliases)


def canonical_tag(tag: str) -> str:
    """把别名归一到主 tag；本身就是主 tag 则原样返回；未收录返回空串。"""
    data = tables()
    key = normalize_key(tag)

    if not key:
        return ""
    if key in data.tags:
        return key
    return data.aliases.get(key, "")


def tag_for_chinese(text: str) -> str:
    """中文名直查主 tag，未收录返回空串。"""
    key = str(text or "").strip()
    if not key:
        return ""
    return tables().chinese.get(key, "")


def chinese_name(tag: str) -> str:
    """返回该 tag 的首选中文名，没有则返回空串。"""
    data = tables()
    key = canonical_tag(tag)

    if not key:
        return ""

    _, cn_names = data.tags.get(key, (0, ""))
    names = [part.strip() for part in str(cn_names).split(",") if part.strip()]

    return next(
        (name for name in names if _CJK_RE.search(name)),
        names[0] if names else "",
    )


_SERIES_SUFFIX_RE = re.compile(r"^(.+?)_\([^()]+\)$")


def strip_unknown_series_suffix(tag: str) -> str:
    """``X_(作品名)`` 查无此词、而裸名 ``X`` 存在时返回裸名，否则返回空串。

    Danbooru 的作品名后缀只用于消歧义，是**逐角色**的：``ganyu_(genshin_impact)``
    要带，``hatsune_miku`` 不带。翻译提示词长期让 LLM 一律加后缀，凡是不需要
    后缀的角色，产出的都是 NovelAI 不认识的词——模型直接忽略这个 token，角色
    静默崩掉，而且从提示词表面完全看不出来。

    只做「后缀形不存在 → 裸名存在」这一个方向。反方向（裸名补后缀）不做：
    ``rem`` 这类词补成 ``rem_(re:zero)`` 是凭空塞进一个角色，写错比不写严重。
    """
    data = tables()
    key = normalize_key(tag)

    if not key or key in data.tags or key in data.aliases:
        return ""

    match = _SERIES_SUFFIX_RE.match(key)
    if not match:
        return ""

    bare = match.group(1)

    return bare if bare in data.tags else ""

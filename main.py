from __future__ import annotations

import asyncio
import os
import re
from dataclasses import replace
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star

from PIL import Image as PILImage

from .constants import (
    PLUGIN_AUTHOR,
    PLUGIN_DISPLAY_NAME,
    PLUGIN_NAME,
    PLUGIN_REPO,
    PLUGIN_VERSION,
    normalize_nai_seed,
)
from .core.api_errors import describe_api_error, strip_error_subject
from .core.char_prompts import has_explicit_positions, normalize_char_entries
from .core.debug_trace import DebugTrace
from .core.generator import (
    APIKeyError,
    GenerationError,
    ImageGenerator,
    QuotaExceededError,
    RateLimitError,
    ServerBusyError,
)
from .core.image_retagger import ImageRetagError, ImageRetagger, strip_control_tags
from .core.prompt_tokens import expand_prompt_tokens, normalize_count_tokens
from .core.safety import SafetyModerator
from .core.translator import (
    apply_character_candidate,
    DanbooruTagRetriever,
    PromptTranslator,
    TranslatedPrompt,
    has_chinese,
    prompt_has_tag,
    resolve_character_candidate,
    resolve_translation_cache,
    tag_lookup_key,
)
from .image_store import send_image_best_effort
from .models.config import (
    MODEL_V45_FULL,
    MODEL_V5_FULL,
    SUPPORTED_SAMPLERS,
    GenerationConfig,
    PluginConfig,
    model_supports_cjk,
    resolve_model_choice,
)
from .services.artist_gallery import ArtistGalleryService
from .services.canvas import CanvasService
from .services.image_extract import extract_image_from_event_best_effort
from .services.image_ratio import (
    choose_ratio_source,
    clamp_to_pixel_budget,
    format_aspect_ratio,
    infer_ratio_label_from_size,
    prompt_has_explicit_ratio,
    MAX_TOTAL_PIXELS,
    RATIO_SOURCE_ARTIST,
    RATIO_SOURCE_IMAGE,
    read_image_size_any,
)
from .services.mention_avatar import (
    extract_mentioned_qq_from_event,
    qq_avatar_url,
    remove_mention_from_prompt,
)
from .services.prompt_builder import (
    apply_prompt_weight,
    cleanup_file,
    find_non_ascii_chars,
    normalize_prompt_ascii,
    PromptBuilder,
    save_image_to_temp,
)
from .services.prompt_merge import (
    MAX_RETAG_DROP_TAGS,
    RETAG_LAYER_CATEGORIES,
    extract_retag_mode,
    group_prompt_tags,
    merge_retag_prompt_details,
    normalize_retag_layer_categories,
)
from .services.nai_metadata import (
    is_trusted_nai_generation_info,
    read_image_generation_info,
    read_image_generation_info_any,
)
from .services.runtime_state import RuntimeStateService


SAFETY_BLOCK_REPLY = "⚠️ 未能通过安全检测，已拦截"

# 画布可手动调节的生图参数范围
# 步数上限锁在 28：NovelAI 的免费额度只在 ≤28 步时生效，超过就开始扣 Anlas。
MIN_STEPS = 1
MAX_STEPS = 28
MIN_SCALE = 1.0
MAX_SCALE = 10.0


def _unsupported_sampler_error(error: GenerationError) -> bool:
    """Whether a provider rejected only the sampler value.

    Relays differ in sampler support and often return this as a plain 400
    message.  The canvas should still generate with the configured default
    instead of exposing a permanent ``Unsupported sampler`` failure.
    """
    message = str(getattr(error, "message", error) or "").lower()
    return "unsupported sampler" in message or "sampler is not supported" in message


# NovelAI 4.5 / V5 compatible canvas presets. Every dimension is a 64 multiple
# and stays below the plugin's ~1.1 MP safety limit.
CANVAS_RATIO_PRESETS: Dict[str, Tuple[int, int]] = {
    "16:9": (1216, 704),
    "9:16": (704, 1216),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "3:2": (1216, 832),
    "2:3": (832, 1216),
    "1:1": (1024, 1024),
    "5:4": (960, 768),
    "4:5": (768, 960),
    "7:4": (1344, 768),
    "4:7": (768, 1344),
    "12:5": (1536, 640),
    "5:12": (640, 1536),
    "21:9": (1344, 576),
    "9:21": (576, 1344),
}


def _parse_size(size_str: str) -> Tuple[int, int]:
    try:
        text = str(size_str).strip().lower().replace("×", "x")
        parts = text.split("x")

        if len(parts) != 2:
            raise ValueError(f"无效的尺寸格式: {size_str}")

        width = int(parts[0].strip())
        height = int(parts[1].strip())

        if width <= 0 or height <= 0:
            raise ValueError(f"尺寸必须为正整数: {size_str}")

        return width, height

    except Exception as e:
        raise ValueError(f"解析尺寸失败: {size_str}") from e


def resolve_size_preset(size_input: str, presets: dict) -> Tuple[int, int]:
    value = str(size_input or "").strip()

    if value in presets:
        return presets[value]

    return _parse_size(value)


class BestNAIPlugin(Star):
    def __init__(self, context: Context, config: dict) -> None:
        super().__init__(context)

        self.context = context
        self.plugin_config = PluginConfig.from_dict(config)

        self.runtime_state = RuntimeStateService(PLUGIN_NAME)

        self._prune_persisted_artist_presets()

        self._resolve_image_provider()

        self.generator = ImageGenerator(self.plugin_config)
        self.safety = SafetyModerator(self.plugin_config.safety, context=self.context)
        self.image_retagger = ImageRetagger(
            self.plugin_config.image_retag,
            context=self.context,
            extra_control_tags=self.plugin_config.get_retag_control_prompts(),
        )

        self._generation_semaphore = asyncio.Semaphore(
            self.plugin_config.max_concurrency
        )

        self.ratio_presets = self._load_ratio_presets()
        self.default_ratio = self._load_default_ratio()

        self.prompt_builder = PromptBuilder(
            self.plugin_config,
            self._resolve_ratio_to_size,
        )

        self.artist_gallery = ArtistGalleryService(PLUGIN_NAME)
        self.canvas = CanvasService(
            PLUGIN_NAME,
            generate_callback=self._canvas_generate,
            config_callback=self._canvas_config,
            retag_callback=self._canvas_retag,
            tag_translation_callback=self._canvas_translate_tags,
        )

        api_source = (
            "NovelAI 官方接口"
            if getattr(self.plugin_config, "use_official_api", False)
            else (self.plugin_config.image_provider_id or "(未选择)")
        )

        artist_source = (
            self.plugin_config.artist_preset
            or self._get_default_artist_display_name()
        )

        logger.info(
            "[BestNAI] 已加载，"
            f"生图接口={api_source}，"
            f"API URL={self.plugin_config.api_url or '(未配置)'}，"
            f"生图并发上限={self.plugin_config.max_concurrency}，"
            f"安全审核={'开启' if self.plugin_config.safety.enabled else '关闭'}，"
            f"审核提供商={self.plugin_config.safety.provider_id or '(未选择)'}，"
            f"图片反推={'开启' if self.plugin_config.image_retag.enabled else '关闭'}，"
            f"反推提供商={self.plugin_config.image_retag.provider_id or '(未选择)'}，"
            f"配置默认画师预设={artist_source}，"
            f"模型={self.plugin_config.generation.model}，"
            f"默认比例={self.default_ratio}，"
            f"插件数据目录={self.artist_gallery.plugin_data_dir}"
        )

    async def initialize(self) -> None:
        self.canvas.register(self.context)
        logger.info("[BestNAI/Canvas] Infinite Canvas 页面 API 已注册")

    async def terminate(self) -> None:
        logger.info("[BestNAI] 已卸载")

    def _canvas_config(self) -> Dict[str, object]:
        self._ensure_image_provider_ready()

        ratios = []
        for name in CANVAS_RATIO_PRESETS:
            width, height = self.ratio_presets[name]
            ratios.append(
                {
                    "value": name,
                    "label": f"{width}×{height} · {name}",
                    "width": width,
                    "height": height,
                }
            )

        artists = [
            {"value": name, "label": name}
            for name in self.plugin_config.get_all_artist_slots_map().keys()
        ]

        return {
            "plugin": {
                "name": PLUGIN_DISPLAY_NAME,
                "version": PLUGIN_VERSION,
                "author": PLUGIN_AUTHOR,
                "repo": PLUGIN_REPO,
            },
            "configured": self.plugin_config.is_configured(),
            "model": self.plugin_config.generation.model,
            "models": [
                {"value": MODEL_V45_FULL, "label": "V4.5 Full"},
                {"value": MODEL_V5_FULL, "label": "V5 Full"},
            ],
            "defaultModel": MODEL_V45_FULL,
            "defaultRatio": self._normalize_ratio_label(self.default_ratio),
            "defaultArtist": self._get_default_artist_display_name(),
            "defaultSampler": self.plugin_config.generation.sampler,
            "samplers": [
                {"value": value, "label": value}
                for value in SUPPORTED_SAMPLERS
            ],
            "ratios": ratios,
            "artists": artists,
            "retagControlPrompts": self.plugin_config.get_retag_control_prompts(),
            "maxConcurrency": self.plugin_config.max_concurrency,
            "translatorEnabled": self.plugin_config.translator.enabled,
            "retagEnabled": self.plugin_config.image_retag.enabled,
            "retagConfigured": self.plugin_config.image_retag.enabled
            and self.plugin_config.image_retag.is_configured(),
        }

    def _with_debug(
        self,
        trace: DebugTrace,
        result: Dict[str, object],
    ) -> Dict[str, object]:
        """调试模式下把流水挂进返回体，同时原样打一份到后端日志。

        关着开关时 payload() 是 None，返回体一个字段都不多，接口保持原样。
        """
        debug = trace.payload()

        if debug is None:
            return result

        logger.info(trace.log_text())
        result["debug"] = debug

        return result

    async def _canvas_translate_tags(self, prompt: str) -> Dict[str, object]:
        """Return ordered Chinese names for the English tags shown in the viewer."""

        tags = [
            str(tag or "").strip()
            for tag in expand_prompt_tokens(prompt)
            if str(tag or "").strip()
        ][:320]
        translations: Dict[str, str] = {}
        api_url = str(
            getattr(self.plugin_config, "danbooru_api_url", "") or ""
        ).strip()
        if tags and api_url:
            retriever = DanbooruTagRetriever(base_url=api_url, timeout=8.0)
            lookup = await retriever.lookup_tags(tags)
            if isinstance(lookup, dict):
                translations = dict(lookup.get("translations") or {})

        return {
            "pairs": [
                {
                    "tag": tag,
                    "cnName": translations.get(tag_lookup_key(tag), ""),
                }
                for tag in tags
            ],
            "translations": translations,
        }

    async def _canvas_source_tag_details(
        self,
        prompt: str,
        *,
        character: str = "",
        series: str = "",
    ) -> Tuple[str, str, Dict[str, List[str]], Dict[str, str]]:
        """Group source tags and attach exact Chinese names from the tags site."""

        resolved_character = str(character or "").strip()
        resolved_series = str(series or "").strip()
        groups = group_prompt_tags(
            prompt,
            character=resolved_character,
            series=resolved_series,
        )
        tags = [tag for values in groups.values() for tag in values]
        translations: Dict[str, str] = {}
        api_url = str(
            getattr(self.plugin_config, "danbooru_api_url", "") or ""
        ).strip()
        if tags and api_url:
            retriever = DanbooruTagRetriever(base_url=api_url, timeout=8.0)
            lookup = await retriever.lookup_tags(tags)
            items = lookup.get("items") if isinstance(lookup, dict) else []
            translations = (
                dict(lookup.get("translations") or {})
                if isinstance(lookup, dict)
                else {}
            )
            candidate_character, candidate_series = resolve_character_candidate(
                prompt,
                {
                    "search": items if isinstance(items, list) else [],
                    "related": [],
                },
            )
            resolved_character = resolved_character or candidate_character
            resolved_series = resolved_series or candidate_series
            if resolved_character or resolved_series:
                groups = group_prompt_tags(
                    prompt,
                    character=resolved_character,
                    series=resolved_series,
                )

        return resolved_character, resolved_series, groups, translations

    async def _canvas_retag(
        self,
        image_path: str,
        user_hint: str,
        debug: bool = False,
        source_seed: Optional[int] = None,
        source_prompt_hint: str = "",
    ) -> Dict[str, object]:
        retag_config = self.plugin_config.image_retag
        trace = DebugTrace("canvas.retag", bool(debug))
        trace.note("手写提示词（仅用于后续生图）", user_hint or "(空)")

        # 先看图片自带的 NovelAI 生成参数。命中就不必让视觉模型猜了，
        # 原始 prompt 和种子一起用能真正还原这张图。
        # 注意：NAI PNG（tEXt）、NAI JPEG/WebP 导出（EXIF UserComment）、
        # SD WebUI parameters 都读得出来；QQ 压缩转发的图元数据已丢，读不到。
        with trace.stage("读原图内嵌参数"):
            source_info = await asyncio.to_thread(read_image_generation_info, image_path)

        retag_control_prompts = self.plugin_config.get_retag_control_prompts()
        embedded_seed = normalize_nai_seed(source_info.get("seed"))
        cached_seed = normalize_nai_seed(source_seed)
        source_seed = embedded_seed or cached_seed
        raw_embedded_prompt = strip_control_tags(
            str(source_info.get("prompt") or "").strip(),
            extra_control_tags=retag_control_prompts,
        )
        embedded_prompt = (
            raw_embedded_prompt
            if is_trusted_nai_generation_info(source_info)
            else ""
        )
        cached_prompt = strip_control_tags(
            str(source_prompt_hint or "").strip(),
            extra_control_tags=retag_control_prompts,
        )
        # A NovelAI prompt is useful even when a re-encoded PNG lost its seed.
        # The seed is needed for deterministic reproduction, but it is not
        # needed to avoid a second vision/tagging request.  Prefer embedded
        # metadata, then the source-image cache supplied by the canvas.
        source_prompt = embedded_prompt or cached_prompt
        from_metadata = bool(embedded_prompt)
        # V4+ 元数据可能带角色提示词（v4_prompt.caption.char_captions）。
        # 角色文本仍并回还原 tags（兼容不支持结构化字段的网关），
        # 并在生图前折叠重复的人数标签；同时固定透传结构化角色参数，
        # 由网关支持情况决定是否实际启用分区生成。
        char_prompts = (
            normalize_char_entries(source_info.get("characterPrompts"))
            if from_metadata
            else []
        )
        char_use_coords = bool(
            from_metadata and source_info.get("characterUseCoords") and char_prompts
        )
        char_use_order = bool(
            from_metadata
            and char_prompts
            and source_info.get("characterUseOrder", True)
        )
        char_tag_texts = [
            stripped
            for stripped in (
                strip_control_tags(
                    str(entry.get("prompt") or "").strip(),
                    extra_control_tags=retag_control_prompts,
                )
                for entry in char_prompts
            )
            if stripped
        ]
        # A canvas cache can fill either half of the pair (seed or prompt).
        # Keep the provenance separate so the diagnostics never claim that a
        # prompt came from PNG metadata when only the canvas cache had it.
        from_canvas_cache = bool(cached_prompt) and not from_metadata

        if source_prompt:
            source_label = (
                "画布缓存参数"
                if from_canvas_cache
                else "原图内嵌参数"
            )
            logger.info(
                f"[BestNAI/Canvas] 命中{source_label}，直接复用：seed={source_seed}"
            )

            # One exact tags-site request supplies both identity metadata and
            # the Chinese names shown beside the English source tags.
            with trace.stage("原图 Tags 中英检索"):
                (
                    source_character,
                    source_series,
                    tag_groups,
                    tag_translations,
                ) = await self._canvas_source_tag_details(source_prompt)

            # Return only image tags. The caller translates and weights the
            # current hand-written hint exactly once during generation.
            # NovelAI's official canvas keeps character captions in the
            # structured V4 payload and does not duplicate them in the base
            # prompt. Keep the flattened form only for legacy relay gateways.
            image_tags = (
                source_prompt
                if getattr(self.plugin_config, "use_official_api", False)
                else ", ".join(
                    part for part in (source_prompt, *char_tag_texts) if part
                )
            )

            trace.note(
                "走的分支",
                "命中画布缓存参数，未调用视觉模型"
                if from_canvas_cache
                else "命中原图内嵌参数，未调用视觉模型",
            )
            trace.note("手写提示词（不送反推）", user_hint or "(空)")
            trace.note("原图图片 tags", image_tags)
            if char_prompts:
                trace.note(
                    "原图角色提示词（char_captions）",
                    {
                        "characters": char_prompts,
                        "useCoords": char_use_coords,
                        "useOrder": char_use_order,
                    },
                )
            if from_canvas_cache:
                trace.note("画布缓存提示词", cached_prompt)
            trace.note(
                "原图角色",
                ", ".join(
                    part for part in (source_character, source_series) if part
                ) or "(未识别)",
            )
            trace.note(
                "可复用参数",
                {
                    "来源": source_label,
                    "seed": source_seed,
                    "steps": source_info.get("steps"),
                    "scale": source_info.get("scale"),
                },
            )

            return self._with_debug(
                trace,
                {
                    "prompt": image_tags,
                    "character": source_character,
                    "series": source_series,
                    "tagGroups": tag_groups,
                    "tagTranslations": tag_translations,
                    "ratio": self._ratio_from_generation_info(source_info, image_path),
                    "seed": source_seed,
                    "sourcePrompt": source_prompt,
                    "charPrompts": char_prompts,
                    "charUseCoords": char_use_coords,
                    "charUseOrder": char_use_order,
                    # 原图采样参数：前端缓存后随生图请求回传，缺省用插件配置
                    "steps": source_info.get("steps"),
                    "scale": source_info.get("scale"),
                    "cfgRescale": source_info.get("cfg_rescale"),
                    "noiseSchedule": str(source_info.get("noise_schedule") or ""),
                    "sampler": str(source_info.get("sampler") or ""),
                    "fromMetadata": from_metadata,
                    "fromCanvasCache": from_canvas_cache,
                },
            )

        if not retag_config.enabled:
            raise ValueError("图片反推功能未开启，请先在插件配置中启用")

        if not retag_config.is_configured():
            raise ValueError("图片反推功能未配置，请选择支持视觉输入的提供商")

        trace.note("走的分支", "原图无内嵌参数，调用视觉模型反推")
        trace.note(
            "反推提供商",
            {
                "provider": retag_config.provider_id or "(手动配置)",
            },
        )

        # The vision/tagger provider describes only the source image. User edits
        # are merged later by the shared category-aware prompt overlay.
        try:
            retag_result = await trace.timed(
                "反推",
                self.image_retagger.retag_details(image_path, debug=debug),
            )
        except ImageRetagError as exc:
            message = strip_error_subject(str(exc), "图片反推")
            raise ValueError(message or "图片反推失败") from exc

        prompt = str(retag_result.get("prompt") or "").strip()

        if not prompt:
            raise ValueError("图片反推结果为空")

        with trace.stage("原图 Tags 中英检索"):
            (
                retag_character,
                retag_series,
                tag_groups,
                tag_translations,
            ) = await self._canvas_source_tag_details(
                prompt,
                character=str(retag_result.get("character") or ""),
                series=str(retag_result.get("series") or ""),
            )

        trace.note("反推 tags", prompt)
        trace.note("手写提示词", user_hint or "(空)")

        ratio = ""
        try:
            width, height = await read_image_size_any(image_path)
            ratio = infer_ratio_label_from_size(width, height)
        except Exception as exc:
            logger.warning(f"[BestNAI/Canvas] 读取反推原图比例失败: {exc}")

        trace.note("推断比例", ratio or "(未识别)")

        return self._with_debug(
            trace,
            {
                "prompt": prompt,
                "character": retag_character,
                "series": retag_series,
                "tagGroups": tag_groups,
                "tagTranslations": tag_translations,
                "ratio": ratio,
                "seed": source_seed,
                "fromMetadata": False,
                "fromCanvasCache": False,
            },
        )

    async def _translate_canvas_hint(self, hint: str) -> str:
        """把画布上手写的中文提示词翻成英文，翻不了就原样返回。

        这里不报错：翻译器没开 / 没配时，原文会一路带到生成阶段，
        由那边给出「请先启用翻译器」之类的明确提示，行为和以前一致。
        """
        hint = (hint or "").strip()

        if not hint or not has_chinese(hint):
            return hint

        try:
            translated, reason = await self._translate_prompt_with_reason(
                hint,
                apply_safety_filter=False,
            )
        except Exception as exc:
            logger.warning(f"[BestNAI/Canvas] 反推附带的提示词翻译失败，保留原文: {exc}")
            return hint

        if not translated:
            logger.warning(f"[BestNAI/Canvas] 反推附带的提示词未译出，保留原文: {reason}")
            return hint

        return translated

    def _ratio_from_generation_info(
        self,
        info: Dict[str, object],
        image_path: str,
    ) -> str:
        width = info.get("width")
        height = info.get("height")

        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return infer_ratio_label_from_size(width, height)

        try:
            with PILImage.open(image_path) as image:
                return infer_ratio_label_from_size(image.width, image.height)
        except Exception as exc:
            logger.warning(f"[BestNAI/Canvas] 读取原图比例失败: {exc}")
            return ""

    async def _canvas_generate(
        self,
        payload: Dict[str, object],
    ) -> Tuple[List[Tuple[str, bytes]], Dict[str, object]]:
        prompt = str(payload.get("prompt") or "").strip()
        # 节点级模型选择：原始提示词等所有模式都跟随节点上的选择
        current_model = resolve_model_choice(
            payload.get("model") or MODEL_V45_FULL
        )
        retag_prompt = str(payload.get("retagPrompt") or "").strip()
        retag_character = str(payload.get("retagCharacter") or "").strip()
        retag_series = str(payload.get("retagSeries") or "").strip()
        retag_preserve_categories = normalize_retag_layer_categories(
            payload.get("retagPreserveCategories")
        )
        retag_drop_categories = normalize_retag_layer_categories(
            payload.get("retagDropCategories")
        )
        retag_preserve_categories.difference_update(retag_drop_categories)
        ordered_retag_preserve_categories = [
            category
            for category in RETAG_LAYER_CATEGORIES
            if category in retag_preserve_categories
        ]
        ordered_retag_drop_categories = [
            category
            for category in RETAG_LAYER_CATEGORIES
            if category in retag_drop_categories
        ]
        # 单条标签的移除清单：分类级移除的细粒度补充，同类其余标签不受影响。
        # 载荷来自客户端，先确认是列表——传字符串会被逐字符迭代成一堆单字。
        raw_retag_drop_tags = payload.get("retagDropTags")
        retag_drop_tags = [
            text
            for value in (raw_retag_drop_tags if isinstance(raw_retag_drop_tags, list) else [])
            if isinstance(value, str) and (text := value.strip())
        ][:MAX_RETAG_DROP_TAGS]
        if retag_character and not prompt_has_tag(retag_prompt, retag_character):
            # Do not trust stale structured metadata after an older retag
            # result was edited or migrated; the prompt itself is authoritative.
            retag_character = ""
        if retag_series and not prompt_has_tag(retag_prompt, retag_series):
            retag_series = ""
        ratio = str(payload.get("ratio") or self.default_ratio).strip()
        artist_name = str(payload.get("artist") or "").strip()
        raw_mode = bool(payload.get("raw", False))
        # 勾了原始提示词还想翻译中文时的逃生口。raw 的本意是"别给我加画师串和
        # 质量词、别做同类替换"，把中文翻译一起关掉是顺带的副作用——对写中文
        # 描述的人来说等于 raw 不可用。这个开关只放开翻译，其余 raw 语义不变。
        raw_translate = bool(payload.get("rawTranslate", False))

        if not prompt and not retag_prompt:
            raise ValueError("请输入提示词")

        if len(prompt) > 6000:
            raise ValueError("提示词不能超过 6000 个字符")

        if not self.plugin_config.is_configured():
            self._ensure_image_provider_ready()

        if not self.plugin_config.is_configured():
            raise ValueError("插件未配置生图提供商或手动 API")

        clean_prompt = prompt

        translated_prompt = ""
        working_prompt = clean_prompt
        translated_character = str(
            payload.get("cachedTranslationCharacter") or ""
        ).strip()
        translated_series = str(
            payload.get("cachedTranslationSeries") or ""
        ).strip()
        identity_checked = bool(translated_character)
        translation_cache_reused = False

        trace = DebugTrace("canvas.generate", bool(payload.get("debug")))
        trace.note("输入提示词", prompt)
        if retag_prompt:
            trace.note("反推标签（独立输入）", retag_prompt)
            trace.note(
                "反推标签图层",
                {
                    "锁定原图": ordered_retag_preserve_categories,
                    "移除原图": ordered_retag_drop_categories,
                    "移除标签": retag_drop_tags,
                },
            )

        # Raw canvas mode is literal: do not call the translator or Danbooru,
        # unless the node explicitly opted back into translation.
        if has_chinese(clean_prompt) and (not raw_mode or raw_translate):
            if raw_mode:
                trace.note("原始提示词模式", "已单独开启翻译")
            translation_source, untranslated_suffix, translated_source = (
                resolve_translation_cache(
                    clean_prompt,
                    str(payload.get("translationSource") or ""),
                    str(payload.get("cachedTranslationSource") or ""),
                    str(payload.get("cachedTranslation") or ""),
                )
            )
            translation_cache_reused = bool(translated_source)
            trace.note("送翻译的原文", translation_source or "(空)")
            trace.note(
                "翻译来源",
                "复用节点缓存" if translated_source else "本次调用翻译接口",
            )
            if not translated_source:
                tr_cfg = self.plugin_config.translator
                if not tr_cfg.enabled:
                    raise ValueError("检测到中文提示词，请先在插件配置中启用翻译器")
                if not tr_cfg.is_configured():
                    raise ValueError("翻译器未配置，请选择翻译提供商")
                with trace.stage("翻译"):
                    translated_source, failure_reason = (
                        await self._translate_prompt_with_reason(
                            translation_source,
                            apply_safety_filter=False,
                        )
                    )
                    translated_character = str(
                        getattr(translated_source, "character_tag", "") or ""
                    ).strip()
                    translated_series = str(
                        getattr(translated_source, "series_tag", "") or ""
                    ).strip()
                    identity_checked = True
                translated_source = translated_source or ""
                if not translated_source:
                    raise ValueError(failure_reason or "提示词翻译失败，请检查翻译提供商")
            if not translated_source:
                raise ValueError("提示词翻译失败，请检查翻译提供商")
            translated_prompt = ", ".join(
                part for part in (translated_source, untranslated_suffix) if part
            )
            working_prompt = translated_prompt
            trace.note("翻译结果", translated_source)
            if untranslated_suffix:
                trace.note("未参与翻译的英文部分", untranslated_suffix)
        else:
            translation_source = ""
            translated_source = ""
            translated_character = ""
            translated_series = ""
            identity_checked = False
            trace.note("翻译", "提示词无中文，未走翻译")

        # Retag tags are already English output from the single vision/tagging
        # request. Raw mode keeps both explicit inputs unchanged; normal mode
        # continues through the category-aware merge below.
        if retag_prompt:
            if raw_mode:
                # 用 working_prompt 而不是 clean_prompt：开了 raw 翻译时它就是
                # 译文，没开时两者相等，行为不变。
                working_prompt = ", ".join(
                    part for part in (working_prompt, retag_prompt) if part
                )
                trace.note("原始提示词图层", working_prompt)
            else:
                translated_user_prompt = translated_prompt or working_prompt
                if translated_user_prompt and (
                    translation_cache_reused or not identity_checked
                ):
                    # Cached identity metadata may have been produced by an older
                    # resolver. Re-check it for retag overlays so a fixed matcher
                    # takes effect without requiring the user to edit the node.
                    if translation_cache_reused:
                        translated_character = ""
                        translated_series = ""
                    with trace.stage("角色标签检索"):
                        (
                            translated_character,
                            translated_series,
                            identity_results,
                        ) = await self._resolve_prompt_identity_details(clean_prompt)
                    if translation_cache_reused and translated_character:
                        # A saved translation may come from an older resolver and
                        # still contain a wrong character candidate or ``year
                        # 2025``. Re-apply the current deterministic tag result
                        # before merging so stale cache data cannot reintroduce a
                        # second role beside the confirmed replacement.
                        translated_source = apply_character_candidate(
                            translated_source,
                            translated_character,
                            translated_series,
                            identity_results,
                        )
                        translated_user_prompt = ", ".join(
                            part
                            for part in (translated_source, untranslated_suffix)
                            if part
                        )
                    identity_checked = True
                    if translated_character:
                        trace.note(
                            "覆盖角色",
                            ", ".join(
                                part
                                for part in (translated_character, translated_series)
                                if part
                            ),
                        )
                merge_details = merge_retag_prompt_details(
                    translated_user_prompt,
                    retag_prompt,
                    original_user_prompt=prompt,
                    user_character=translated_character,
                    user_series=translated_series,
                    source_character=retag_character,
                    source_series=retag_series,
                    weight_user=True,
                    preserve_categories=retag_preserve_categories,
                    drop_categories=retag_drop_categories,
                    drop_tags=retag_drop_tags,
                )
                working_prompt = str(merge_details.get("prompt") or "")
                # 多角色还原文本常同时带全局计数和各段落裸计数，叠加会多画人
                normalized_prompt = normalize_count_tokens(working_prompt)
                if normalized_prompt != working_prompt:
                    trace.note("人数标签归一", normalized_prompt)
                    working_prompt = normalized_prompt
                trace.note("提示词冲突处理", merge_details)
                trace.note("合并后提示词", working_prompt)

        try:
            gen_config = self.prompt_builder.build_generation_config(
                ratio,
                apply_safe_negative=False,
            )
        except Exception as exc:
            raise ValueError(f"无效比例或尺寸：{ratio}") from exc

        gen_config = replace(
            gen_config,
            model=current_model,
            steps=self._clamp_steps(payload.get("steps"), gen_config.steps),
            scale=self._clamp_scale(payload.get("scale"), gen_config.scale),
        )

        # 反推命中内嵌参数时前端会回传原图采样参数，缺省保持插件配置；
        # 节点高级参数卡里的 cfg_rescale / Variety+ 优先级更高（见下方覆盖）
        try:
            cfg_rescale = float(payload.get("cfg_rescale"))
        except (TypeError, ValueError):
            cfg_rescale = gen_config.cfg_rescale
        cfg_rescale = min(max(cfg_rescale, 0.0), 1.0)
        noise_schedule = str(payload.get("noise_schedule") or "").strip()
        # 采样器同样来自原图内嵌参数。NAI 元数据里一直有它，之前解析完就丢了，
        # 于是"沿用原图参数"独独漏掉采样器这一项。
        source_sampler = str(payload.get("sampler") or "").strip()
        applied_source_params = {
            key: payload[key]
            for key in ("steps", "scale", "cfg_rescale", "noise_schedule", "sampler")
            if payload.get(key)
        }
        gen_config = replace(
            gen_config,
            cfg_rescale=cfg_rescale,
            noise_schedule=noise_schedule or gen_config.noise_schedule,
            sampler=source_sampler or gen_config.sampler,
        )
        if applied_source_params:
            trace.note("沿用原图采样参数", applied_source_params)

        # 节点高级参数卡：Variety+ 开关（提升构图/姿态多样性）
        if bool(payload.get("varietyPlus")):
            gen_config = replace(gen_config, variety_boost=True)
            trace.note("高级参数", "Variety+ 已开启")

        # 反推命中的多角色参数：结构化透传（固定开启，网关 400 时自动回退）
        raw_char_prompts = payload.get("retagCharPrompts")
        char_prompts = normalize_char_entries(raw_char_prompts)
        if char_prompts:
            # 站位只有在 use_coords 为真时才生效，否则 NovelAI 按出场顺序排布、
            # 忽略坐标。前端现在总会发送 retagUseCoords；它一旦存在就是权威值。
            # 只有旧版客户端完全没有这个字段时，才根据显式 position 兼容推断。
            # 不能把规范化过程中由 center 推导出的 B3/C3/D3 当成用户选择，
            # 否则会把官方元数据里的 use_coords=false 错误改成 true。
            use_coords = (
                bool(payload.get("retagUseCoords"))
                if "retagUseCoords" in payload
                else has_explicit_positions(raw_char_prompts)
            )
            # The canvas exposes these as one mutually-exclusive layout mode.
            # Prefer coordinates when a legacy workspace contains both flags.
            use_order = bool(payload.get("retagUseOrder", True)) and not use_coords
            gen_config = replace(
                gen_config,
                characters=char_prompts,
                use_coords=use_coords,
                use_order=use_order,
            )
            trace.note(
                "角色参数",
                {
                    "characters": char_prompts,
                    "useCoords": use_coords,
                    "useOrder": use_order,
                },
            )

        resolved_artist_name = ""
        artist_prompt = ""

        if raw_mode:
            gen_config = replace(gen_config, quality=False)
            final_prompt = working_prompt
        else:
            if artist_name == "__none__":
                artist_prompt = ""
            elif artist_name:
                resolved_artist_name, artist_prompt = self._find_artist_slot(artist_name)
                if not resolved_artist_name:
                    raise ValueError(f"画师预设不存在：{artist_name}")
            else:
                # 画布没有会话概念，用配置里的默认画师预设
                artist_prompt = self._get_effective_artist_prompt()
                resolved_artist_name = self._get_default_artist_display_name()

            final_prompt = self.prompt_builder.build_final_prompt(
                working_prompt,
                artist_prompt=artist_prompt,
                suffix=self.plugin_config.prompt_suffix or "",
            )

        if not final_prompt:
            raise ValueError("提示词清理后为空")

        trace.note("画师预设", resolved_artist_name or ("原始提示词模式" if raw_mode else "(无)"))
        trace.note("最终提示词", final_prompt)
        trace.note(
            "生图请求参数",
            {
                "model": gen_config.model,
                "width": gen_config.width,
                "height": gen_config.height,
                "steps": gen_config.steps,
                "scale": gen_config.scale,
                "seed": "由返回 PNG 元数据提供",
                "raw": raw_mode,
            },
        )

        # 信号量占用也算进耗时：并发满了在这儿排队，用户看到的就是"生图很慢"
        with trace.stage("生图"):
            async with self._generation_semaphore:
                api_url, api_key = self._provider_credentials_for_model(current_model)
                # Relays do not expose a common sampler capability endpoint.
                # Retry once with the configured default when a source image's
                # sampler is unknown to the selected relay, then retain the
                # existing one-time character-field fallback.
                sampler_fallback_used = False
                character_fallback_used = False
                while True:
                    try:
                        result = await self.generator.generate(
                            final_prompt,
                            gen_config,
                            seed=payload.get("seed"),
                            api_url=api_url,
                            api_key=api_key,
                        )
                        break
                    except GenerationError as exc:
                        if not sampler_fallback_used and _unsupported_sampler_error(exc):
                            configured_sampler = str(
                                self.plugin_config.generation.sampler
                                or "k_euler_ancestral"
                            ).strip()
                            fallback_sampler = (
                                configured_sampler
                                if configured_sampler != gen_config.sampler
                                else "k_euler_ancestral"
                            )
                            if fallback_sampler != gen_config.sampler:
                                sampler_fallback_used = True
                                logger.warning(
                                    "[BestNAI/Canvas] 网关不支持采样器 %s，回退到 %s",
                                    gen_config.sampler,
                                    fallback_sampler,
                                )
                                trace.note(
                                    "采样器回退",
                                    f"网关不支持 {gen_config.sampler}，已改用 {fallback_sampler}",
                                )
                                gen_config = replace(gen_config, sampler=fallback_sampler)
                                continue
                        # 网关若不认识 characters 参数会以 400 拒绝；
                        # 去掉角色参数重试一次，宁可丢分区也不要整次失败。
                        if (
                            not character_fallback_used
                            and gen_config.characters
                            and exc.status_code == 400
                        ):
                            character_fallback_used = True
                            logger.warning(
                                "[BestNAI/Canvas] 生图网关拒绝角色参数（400），已去除 characters 重试"
                            )
                            trace.note("角色参数回退", f"网关返回 400：{exc.message}")
                            gen_config = replace(gen_config, characters=[], use_coords=False)
                            continue
                        raise

        trace.note("返回种子", result.seed)
        trace.note("返回图片数", len(result.images))

        return result.images, self._with_debug(
            trace,
            {
                "sourcePrompt": prompt,
                "retagPrompt": retag_prompt,
                "cleanPrompt": clean_prompt,
                "translatedPrompt": working_prompt,
                "translationSource": translation_source,
                "translationResult": translated_source,
                "translationCharacter": translated_character,
                "translationSeries": translated_series,
                "finalPrompt": final_prompt,
                "ratio": self._display_ratio_label(
                    ratio,
                    gen_config.width,
                    gen_config.height,
                ),
                "width": gen_config.width,
                "height": gen_config.height,
                "artist": resolved_artist_name,
                "retagPreserveCategories": ordered_retag_preserve_categories,
                "retagDropCategories": ordered_retag_drop_categories,
                "retagDropTags": retag_drop_tags,
                "raw": raw_mode,
                "model": gen_config.model,
                "seed": result.seed,
                "steps": gen_config.steps,
                "scale": gen_config.scale,
            },
        )

    @staticmethod
    def _clamp_steps(value: object, default: int) -> int:
        try:
            steps = int(value)
        except (TypeError, ValueError):
            return default

        return max(MIN_STEPS, min(MAX_STEPS, steps))

    @staticmethod
    def _clamp_scale(value: object, default: float) -> float:
        try:
            scale = float(value)
        except (TypeError, ValueError):
            return default

        return max(MIN_SCALE, min(MAX_SCALE, scale))

    def _weighted_user_prompt(
        self,
        original_prompt: str,
        ratio_name: str,
        desc_part: str,
        artist_name: str,
        raw_mode: bool,
    ) -> str:
        """反推时给用户手写的描述加正向权重，比例与画师名原样保留。

        比例和画师名要留给下游正则解析，不能包进权重语法里。
        描述为空（用户只写了比例���画师名）时原样返回，不做任何改动。
        """
        weighted = apply_prompt_weight(desc_part)

        if not weighted or weighted == desc_part:
            return original_prompt

        parts = []

        if prompt_has_explicit_ratio(
            original_prompt,
            self._short_ratio_aliases(),
            self.ratio_presets,
            self._normalize_ratio_label,
        ) and ratio_name:
            parts.append(ratio_name)

        if artist_name and not raw_mode:
            parts.append(artist_name)

        parts.append(weighted)

        return " ".join(parts)

    def _prune_persisted_artist_presets(self) -> None:
        """启动时清掉指向已删除画师预设的会话记录。"""
        presets = self.plugin_config.get_all_artist_slots_map()

        removed = self.runtime_state.prune_artist_slots(presets.keys())

        if removed:
            logger.warning(
                f"[BestNAI] 已清除 {removed} 条指向不存在画师预设的会话记录"
            )

    @staticmethod
    def _session_id(event: AstrMessageEvent) -> str:
        """取会话标识，用于把默认画师预设隔离到每个群 / 私聊。"""
        for attr in ("unified_msg_origin", "session_id"):
            value = getattr(event, attr, "")

            if isinstance(value, str) and value.strip():
                return value.strip()

        return ""

    def _strip_command_prefix(self, text: str) -> str:
        text = (text or "").strip()

        text = re.sub(
            r"^\s*[\/／]?nai(?:\s+|$)",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        return text

    def _strip_named_command_prefix(self, text: str, command: str) -> str:
        text = (text or "").strip()
        command = re.escape(command)

        text = re.sub(
            rf"^\s*[\/／]?{command}(?:\s+|$)",
            "",
            text,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        return text

    def _extract_provider_credentials(self, provider_id: str) -> Tuple[str, str]:
        """从 AstrBot 提供商里读出 API Base 与 Key，读不到返回空串。"""
        if not provider_id:
            return "", ""

        try:
            provider = self.context.get_provider_by_id(provider_id)
        except Exception as e:
            logger.warning(f"[BestNAI] 获取生图接口提供商失败 provider_id={provider_id}: {e}")
            return "", ""

        if not provider:
            logger.warning(f"[BestNAI] 找不到生图接口提供商 ID: {provider_id}")
            return "", ""

        p_conf = getattr(provider, "provider_config", {}) or {}

        base_url = (
            getattr(provider, "api_base", "")
            or p_conf.get("api_base")
            or p_conf.get("api_base_url")
            or p_conf.get("base_url")
            or ""
        )

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

        if not base_url:
            logger.warning(f"[BestNAI] 生图接口提供商 {provider_id} 缺少 API Base")
            return "", ""

        if not api_key:
            logger.warning(f"[BestNAI] 生图接口提供商 {provider_id} 缺少 API Key")
            return "", ""

        return str(base_url).rstrip("/"), str(api_key)

    def _resolve_image_provider(self) -> None:
        """解析主（4.5/默认）与 V5 两个提供商槽位。

        生图模型不再跟随提供商配置，改由指令/画布节点显式决定；
        提供商槽位只负责端点与密钥。

        开启 NovelAI 官方接口时两个槽位一律不参与：端点与 Token 直接来自
        面板，4.5 与 V5 共用。凭据仍然落在 api_url / api_key 这一对字段上，
        所以 `_provider_credentials_for_model` 和各生图调用点不用区分模式。
        """
        if getattr(self.plugin_config, "use_official_api", False):
            self._resolve_official_api()
            return

        provider_id = getattr(self.plugin_config, "image_provider_id", "") or ""
        self.plugin_config.api_url = ""
        self.plugin_config.api_key = ""
        # 只有真正拿到接口配置才算就绪；否则每次生图前都会再试一次
        self._image_provider_resolved = False

        if not provider_id:
            logger.warning("[BestNAI] 未选择生图接口提供商")
        else:
            base_url, api_key = self._extract_provider_credentials(provider_id)
            if base_url and api_key:
                self.plugin_config.api_url = base_url
                self.plugin_config.api_key = api_key
                self._image_provider_resolved = True
                logger.info(
                    f"[BestNAI] 已使用生图接口提供商：{provider_id}，"
                    f"api_base={self.plugin_config.api_url}"
                )

        # V5 槽位：留空则复用主提供商，不算失败
        v5_provider_id = getattr(self.plugin_config, "image_provider_id_v5", "") or ""
        self.plugin_config.api_url_v5 = ""
        self.plugin_config.api_key_v5 = ""
        self._image_provider_v5_resolved = not v5_provider_id

        if v5_provider_id:
            v5_url, v5_key = self._extract_provider_credentials(v5_provider_id)
            if v5_url and v5_key:
                self.plugin_config.api_url_v5 = v5_url
                self.plugin_config.api_key_v5 = v5_key
                self._image_provider_v5_resolved = True
                logger.info(
                    f"[BestNAI] 已使用 V5 生图接口提供商：{v5_provider_id}，"
                    f"api_base={self.plugin_config.api_url_v5}"
                )

    def _not_configured_message(self) -> str:
        """未配置时给用户的提示，按当前接入方式给出对应的指引。"""
        if getattr(self.plugin_config, "use_official_api", False):
            return "❌ 插件未配置。\n请在插件配置中填写 NovelAI 官方接口地址与 Token。"
        return "❌ 插件未配置。\n请在插件配置中选择生图接口提供商。"

    def _resolve_official_api(self) -> None:
        """把面板上的官方端点与 Token 装进凭据字段。

        V5 槽位留空并直接标记为已就绪，于是
        `_provider_credentials_for_model` 会按既有的「V5 槽位为空就回落主
        槽位」逻辑把两档模型都送到同一个官方端点。
        """
        url = str(getattr(self.plugin_config, "official_api_url", "") or "").strip()
        token = str(getattr(self.plugin_config, "official_api_token", "") or "").strip()

        self.plugin_config.api_url = url
        self.plugin_config.api_key = token
        self.plugin_config.api_url_v5 = ""
        self.plugin_config.api_key_v5 = ""
        self._image_provider_resolved = bool(url and token)
        self._image_provider_v5_resolved = True

        if not url:
            logger.warning("[BestNAI] 已启用 NovelAI 官方接口，但未填写接口地址")
        elif not token:
            logger.warning("[BestNAI] 已启用 NovelAI 官方接口，但未填写 Token")
        else:
            logger.info(f"[BestNAI] 已启用 NovelAI 官方接口：api_base={url}")

    def _provider_credentials_for_model(self, model: str) -> Tuple[str, str]:
        """按本次请求的模型挑提供商：V5 优先专用槽位，缺省回落主槽位。

        官方接口模式下 V5 槽位恒为空，两档模型都会落到同一个官方端点。
        """
        if model_supports_cjk(model):
            cfg = self.plugin_config
            if cfg.api_url_v5 and cfg.api_key_v5:
                return cfg.api_url_v5, cfg.api_key_v5
            if getattr(self, "_image_provider_v5_resolved", False) is False:
                logger.warning(
                    "[BestNAI] V5 生图接口提供商未就绪/未配置，回落主提供商"
                )
        return self.plugin_config.api_url, self.plugin_config.api_key

    def _ensure_image_provider_ready(self) -> None:
        """
        Bot 重启时 AstrBot provider 可能晚于插件初始化完成。
        只要提供商还没真正解析成功，就在每次生图前再试一次，
        避免必须手动重载插件。
        """
        if not getattr(self, "_image_provider_resolved", False):
            logger.info("[BestNAI] 生图接口尚未就绪，尝试重新解析生图提供商")
            self._resolve_image_provider()
            return

        if not getattr(self, "_image_provider_v5_resolved", False):
            self._resolve_image_provider()

    def _load_ratio_presets(self) -> Dict[str, Tuple[int, int]]:
        base_presets = CANVAS_RATIO_PRESETS

        presets: Dict[str, Tuple[int, int]] = {}

        for name, size in base_presets.items():
            width, height = size
            presets[name] = size
            presets[f"{name} ({width}×{height})"] = size
            presets[f"{name} ({width}x{height})"] = size

        return presets

    def _load_default_ratio(self) -> str:
        raw_config = getattr(self.plugin_config, "raw_config", {}) or {}

        gen_conf = raw_config.get("generation_config", {}) or {}
        ratio_conf = raw_config.get("ratio_config", {}) or {}

        default_ratio = str(
            gen_conf.get(
                "default_ratio",
                ratio_conf.get("default_ratio", "2:3 (832×1216)"),
            )
            or "2:3 (832×1216)"
        ).strip()

        if default_ratio in self.ratio_presets:
            return default_ratio

        normalized = self._normalize_ratio_label(default_ratio)

        if normalized in self.ratio_presets:
            return normalized

        try:
            width, height = resolve_size_preset(default_ratio, self.ratio_presets)
            width, height = self._anchor_size_to_valid(width, height)
            return f"{width}x{height}"
        except Exception:
            logger.warning(f"[BestNAI] 默认比例 {default_ratio} 无效，回退为 2:3")
            return "2:3"

    def _normalize_ratio_label(self, value: str) -> str:
        value = (value or "").strip()

        alias_map = {
            "横屏": "16:9",
            "横图": "16:9",
            "横版": "16:9",
            "landscape": "16:9",
            "竖屏": "9:16",
            "竖图": "9:16",
            "竖版": "9:16",
            "portrait": "9:16",
            "方图": "1:1",
            "方形": "1:1",
            "square": "1:1",
        }

        lower = value.lower()

        for k, v in alias_map.items():
            if lower == k.lower():
                return v

        m = re.match(
            r"^(.+?)\s*[\(（]\s*\d+\s*[x×]\s*\d+\s*[\)）]\s*$",
            value,
        )

        if m:
            return m.group(1).strip()

        return value

    def _validate_size(self, width: int, height: int) -> Tuple[int, int]:
        width = int(width)
        height = int(height)

        if width <= 0 or height <= 0:
            raise ValueError("宽高必须为正整数")

        if width % 64 != 0 or height % 64 != 0:
            raise ValueError(f"尺寸必须是 64 的倍数，当前为 {width}x{height}")

        if width * height > MAX_TOTAL_PIXELS:
            raise ValueError(f"尺寸过大：{width}x{height}")

        return width, height

    def _anchor_size_to_valid(self, width: int, height: int) -> Tuple[int, int]:
        width = int(width)
        height = int(height)

        try:
            return self._validate_size(width, height)
        except Exception:
            pass

        if width <= 0 or height <= 0:
            return self.ratio_presets["2:3"]

        anchored_width, anchored_height = clamp_to_pixel_budget(width, height)

        logger.warning(
            f"[BestNAI] 输入尺寸 {width}x{height} 非法，已等比钳制到 "
            f"{anchored_width}x{anchored_height}"
            f"（{format_aspect_ratio(anchored_width, anchored_height)}）"
        )

        return anchored_width, anchored_height

    def _resolve_ratio_to_size(self, ratio_name_or_size: str) -> Tuple[int, int]:
        value = (ratio_name_or_size or "").strip() or self.default_ratio
        normalized = self._normalize_ratio_label(value)

        if value in self.ratio_presets:
            width, height = self.ratio_presets[value]
            return self._anchor_size_to_valid(width, height)

        if normalized in self.ratio_presets:
            width, height = self.ratio_presets[normalized]
            return self._anchor_size_to_valid(width, height)

        m = re.search(r"(\d{2,5})\s*[x×]\s*(\d{2,5})", value)

        if m:
            return self._anchor_size_to_valid(int(m.group(1)), int(m.group(2)))

        width, height = resolve_size_preset(value, self.ratio_presets)
        return self._anchor_size_to_valid(width, height)

    def _short_ratio_aliases(self) -> List[str]:
        return [
            "landscape",
            "portrait",
            "square",
            "横屏",
            "横图",
            "横版",
            "竖屏",
            "竖图",
            "竖版",
            "方图",
            "方形",
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "3:2",
            "2:3",
            "1:1",
            "5:4",
            "4:5",
            "7:4",
            "4:7",
            "12:5",
            "5:12",
            "21:9",
            "9:21",
        ]

    def _ratio_alias_pattern(self) -> re.Pattern:
        escaped = [
            re.escape(x)
            for x in sorted(self._short_ratio_aliases(), key=len, reverse=True)
        ]

        pattern = r"(^|[\s,，;；])(" + "|".join(escaped) + r")(?=$|[\s,，;；])"
        return re.compile(pattern, flags=re.IGNORECASE)

    def _extract_ratio_from_prompt(self, prompt: str) -> Tuple[str, str]:
        text = (prompt or "").strip()

        if not text:
            return "", self.default_ratio

        found_ratio = ""

        ratio_full_pattern = (
            r"(?:^|\s)--ratio\s+"
            r"(.+?\s*[\(（]\s*\d{2,5}\s*[x×]\s*\d{2,5}\s*[\)）])"
        )

        m_full = re.search(ratio_full_pattern, text, flags=re.IGNORECASE)

        if m_full:
            found_ratio = m_full.group(1).strip()
            text = text[: m_full.start()] + " " + text[m_full.end():]
        else:
            explicit_patterns = [
                r"(?:^|\s)--size\s+([^\s,，;；]+)",
                r"(?:^|\s)--ar\s+([^\s,，;；]+)",
                r"(?:^|\s)--ratio\s+([^\s,，;；]+)",
            ]

            for pattern in explicit_patterns:
                m = re.search(pattern, text, flags=re.IGNORECASE)

                if m:
                    found_ratio = m.group(1).strip()
                    text = re.sub(pattern, " ", text, count=1, flags=re.IGNORECASE)
                    break

        if not found_ratio:
            bracket_pattern = r"[\[【]([^\]】]+)[\]】]"

            for m in re.finditer(bracket_pattern, text):
                candidate = m.group(1).strip()
                normalized = self._normalize_ratio_label(candidate)

                if (
                    candidate in self.ratio_presets
                    or normalized in self.ratio_presets
                    or self._looks_like_size(candidate)
                ):
                    found_ratio = candidate
                    text = text[: m.start()] + " " + text[m.end():]
                    break

        if not found_ratio:
            ratio_match = re.search(r"(\d+[:：]\d+)", text)

            if ratio_match:
                raw_ratio = ratio_match.group(1).replace("：", ":")

                if raw_ratio in self.ratio_presets:
                    found_ratio = raw_ratio
                    text = text.replace(ratio_match.group(1), " ", 1)

        if not found_ratio:
            pattern = self._ratio_alias_pattern()
            m = pattern.search(text)

            if m:
                found_ratio = m.group(2).strip()
                prefix = m.group(1) or ""
                text = text[: m.start()] + prefix + text[m.end():]

        if not found_ratio:
            size_token_pattern = (
                r"(^|[\s,，;；])"
                r"(\d{2,5}\s*[x×]\s*\d{2,5})"
                r"(?=$|[\s,，;；])"
            )

            m = re.search(size_token_pattern, text, flags=re.IGNORECASE)

            if m:
                found_ratio = m.group(2).replace("×", "x").replace(" ", "")
                prefix = m.group(1) or ""
                text = text[: m.start()] + prefix + text[m.end():]

        ratio = self._normalize_ratio_label(found_ratio) if found_ratio else self.default_ratio

        return self._cleanup_prompt_text(text), ratio

    def _extract_artist_slot_from_prompt(self, prompt: str) -> Tuple[str, str, str]:
        text = (prompt or "").strip()

        if not text:
            return "", "", ""

        presets = self.plugin_config.get_all_artist_slots_map()

        if not presets:
            return text, "", ""

        names = sorted(presets.keys(), key=len, reverse=True)
        artist_prefix_words = ("画师预设", "画师", "预设", "artist", "preset")
        artist_name_separator = r"^[\s,，、;；:：|｜/／\\\-—=＝]+"

        def strip_artist_prefix(value: str) -> str:
            value = (value or "").strip()

            for prefix in artist_prefix_words:
                if value.lower() == prefix.lower():
                    return ""

                pattern = (
                    rf"^{re.escape(prefix)}"
                    rf"(?:[\s:：=＝]+|$)"
                )
                value = re.sub(
                    pattern,
                    "",
                    value,
                    count=1,
                    flags=re.IGNORECASE,
                ).strip()

            return value

        def consume_artist_name(value: str) -> Tuple[str, str, str]:
            value = strip_artist_prefix(value)

            if not value:
                return "", "", ""

            lower_value = value.lower()

            for name in names:
                name_lower = name.lower()

                if lower_value == name_lower:
                    return "", presets[name], name

                if lower_value.startswith(name_lower):
                    rest = value[len(name):]

                    if not rest:
                        return "", presets[name], name

                    if re.match(artist_name_separator, rest):
                        rest = re.sub(
                            artist_name_separator,
                            "",
                            rest,
                            count=1,
                        )
                        return self._cleanup_prompt_text(rest), presets[name], name

            return value, "", ""

        bracket_pattern = r"[\[【]([^\]】]+)[\]】]"

        for m in re.finditer(bracket_pattern, text):
            candidate = strip_artist_prefix(m.group(1).strip())

            for name in names:
                if candidate.lower() == name.lower():
                    artist_prompt = presets[name]
                    text = text[: m.start()] + " " + text[m.end():]
                    return self._cleanup_prompt_text(text), artist_prompt, name

        remaining, artist_prompt, artist_name = consume_artist_name(text)

        if artist_prompt:
            return remaining, artist_prompt, artist_name

        return text, "", ""

    def _find_artist_slot(self, name: str) -> Tuple[str, str]:
        name = (name or "").strip()

        if not name:
            return "", ""

        presets = self.plugin_config.get_all_artist_slots_map()

        if name in presets:
            return name, presets[name]

        lower_name = name.lower()

        for k, v in presets.items():
            if k.lower() == lower_name:
                return k, v

        return "", ""

    def _normalize_artist_switch_name(self, prompt: str) -> str:
        text = (prompt or "").strip()

        m = re.fullmatch(r"[\[【]([^\]】]+)[\]】]", text)

        if m:
            return m.group(1).strip()

        return text

    def _try_switch_artist_preset_command(
        self,
        prompt: str,
        session_id: str,
    ) -> Tuple[bool, str]:
        text = self._normalize_artist_switch_name(prompt)

        if not text:
            return False, ""

        reset_words = {
            "默认",
            "恢复默认",
            "配置默认",
            "清除画师预设",
            "取消画师预设",
            "重置画师预设",
        }

        if text in reset_words:
            if not session_id:
                return True, "无法识别当前会话，未能重置画师预设"

            saved = self.runtime_state.clear_artist_slot(session_id)

            if saved:
                return True, "已恢复本会话的配置默认画师预设"

            return True, "已恢复配置默认画师预设，但保存状态失败"

        slot_name, artist_prompt = self._find_artist_slot(text)

        if not slot_name or not artist_prompt:
            return False, ""

        if not session_id:
            return True, "无法识别当前会话，未能切换画师预设"

        saved = self.runtime_state.set_artist_slot(session_id, slot_name)

        if saved:
            return True, f"已切换本会话默认画师预设：{slot_name}（已保存）"

        return True, f"已切换本会话默认画师预设：{slot_name}（保存失败，重启后可能失效）"

    def _display_ratio_label(self, ratio_name_or_size: str, width: int, height: int) -> str:
        value = (ratio_name_or_size or "").strip()
        normalized = self._normalize_ratio_label(value)

        valid_ratios = set(CANVAS_RATIO_PRESETS)

        if normalized in valid_ratios:
            return normalized

        size_to_ratio = {size: name for name, size in CANVAS_RATIO_PRESETS.items()}

        size_key = (int(width), int(height))

        if size_key in size_to_ratio:
            return size_to_ratio[size_key]

        return f"{int(width)}x{int(height)}"

    def _get_default_artist_display_name(self) -> str:
        """配置里的默认画师预设名（不含任何会话级覆盖）。"""
        try:
            presets = self.plugin_config.get_artist_presets_map()

            if presets:
                return next(iter(presets.keys()))

        except Exception:
            pass

        return "未设置"

    def _get_session_artist_slot(self, session_id: str) -> str:
        """取本会话生效的画师预设名，没设过返回空。"""
        if not session_id:
            return ""

        slot_name = self.runtime_state.get_artist_slot(session_id)

        if not slot_name:
            return ""

        real_slot_name, _ = self._find_artist_slot(slot_name)

        return real_slot_name

    def _get_artist_display_name(
        self,
        artist_slot_name: str = "",
        session_id: str = "",
    ) -> str:
        if artist_slot_name:
            return artist_slot_name

        session_slot = self._get_session_artist_slot(session_id)

        if session_slot:
            return session_slot

        return self._get_default_artist_display_name()

    def _get_effective_artist_prompt(
        self,
        artist_prompt_override: str = "",
        session_id: str = "",
    ) -> str:
        if artist_prompt_override and artist_prompt_override.strip():
            return artist_prompt_override.strip()

        session_slot = self._get_session_artist_slot(session_id)

        if session_slot:
            _, artist_prompt = self._find_artist_slot(session_slot)

            if artist_prompt:
                return artist_prompt.strip()

        return self.plugin_config.get_effective_artist_prompt()

    def _format_generation_progress(
        self,
        ratio_name: str,
        gen_config: GenerationConfig,
        raw_mode: bool,
        progress_verb: str,
        artist_slot_name: str = "",
        session_id: str = "",
    ) -> str:
        ratio_display = self._display_ratio_label(
            ratio_name,
            gen_config.width,
            gen_config.height,
        )
        model_display = str(gen_config.model or MODEL_V45_FULL).strip()

        if raw_mode:
            return f"🎨 正在{progress_verb}（{ratio_display} | 原始提示词模式 | {model_display}）..."

        artist_display = self._get_artist_display_name(artist_slot_name, session_id)
        return f"🎨 正在{progress_verb}（{ratio_display} | 画师预设：{artist_display} | {model_display}）..."

    def _progress_message_for_prompt(
        self,
        prompt: str,
        raw_mode: bool,
        progress_verb: str,
        session_id: str = "",
        fallback_ratio: str = "",
        model: str = "",
    ) -> str:
        clean_prompt, ratio_name = self._extract_ratio_from_prompt(prompt)
        artist_prompt_override = ""
        artist_slot_name = ""
        user_specified_ratio = prompt_has_explicit_ratio(
            prompt,
            self._short_ratio_aliases(),
            self.ratio_presets,
            self._normalize_ratio_label,
        )
        artist_has_ratio = False

        if not raw_mode:
            clean_prompt, artist_prompt_override, artist_slot_name = (
                self._extract_artist_slot_from_prompt(clean_prompt)
            )
            artist_prompt = self._get_effective_artist_prompt(
                artist_prompt_override,
                session_id,
            )
            artist_has_ratio = bool(artist_prompt) and prompt_has_explicit_ratio(
                artist_prompt,
                self._short_ratio_aliases(),
                self.ratio_presets,
                self._normalize_ratio_label,
            )

            if not user_specified_ratio and artist_has_ratio:
                _, ratio_name = self._extract_ratio_from_prompt(artist_prompt)

        if not user_specified_ratio and not artist_has_ratio and fallback_ratio:
            ratio_name = fallback_ratio

        gen_config = self.prompt_builder.build_generation_config(ratio_name)
        if model:
            gen_config = replace(gen_config, model=resolve_model_choice(model))
        return self._format_generation_progress(
            ratio_name,
            gen_config,
            raw_mode,
            progress_verb,
            artist_slot_name,
            session_id,
        )

    def _looks_like_size(self, value: str) -> bool:
        return bool(re.fullmatch(r"\d{2,5}\s*[x×]\s*\d{2,5}", value.strip()))

    def _cleanup_prompt_text(self, text: str) -> str:
        text = text or ""
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s*[,，;；]\s*[,，;；]\s*", ", ", text)
        return text.strip(" ,，;；").strip()

    async def _resolve_prompt_identity(
        self,
        text: str,
        *,
        timeout: float = 8.0,
    ) -> Tuple[str, str]:
        """Resolve an English/unchanged retag overlay without invoking an LLM."""
        character, series, _results = await self._resolve_prompt_identity_details(
            text,
            timeout=timeout,
        )
        return character, series

    async def _resolve_prompt_identity_details(
        self,
        text: str,
        *,
        timeout: float = 8.0,
    ) -> Tuple[str, str, Dict[str, List[Dict]]]:
        """Resolve identity and retain candidates for cleaning stale translations."""
        query = str(text or "").strip()
        api_url = str(getattr(self.plugin_config, "danbooru_api_url", "") or "").strip()
        if not query or not api_url:
            return "", "", {"search": [], "related": []}

        retriever = DanbooruTagRetriever(base_url=api_url, timeout=timeout)
        results = await retriever.retrieve(query)
        character, series = resolve_character_candidate(query, results)
        if character:
            logger.info(
                f"[BestNAI] tags 站确认角色标签：{character}"
                f"{f'（{series}）' if series else ''}"
            )
        return character, series, results

    async def _translate_prompt(
        self,
        text: str,
        apply_safety_filter: bool = True,
    ) -> Optional[str]:
        """将中文提示词翻译为英文，可选应用 QQ 场景安全过滤。

        翻译失败，或启用过滤后结果为空时返回 None。
        """
        translated, _ = await self._translate_prompt_with_reason(
            text,
            apply_safety_filter=apply_safety_filter,
        )

        return translated

    async def _translate_prompt_with_reason(
        self,
        text: str,
        apply_safety_filter: bool = True,
    ) -> Tuple[Optional[str], str]:
        """同 _translate_prompt，另外返回一句能直接展示给用户的失败原因。

        原因为空串表示翻译成功。translate() 把上游异常吞掉、只返回原文，
        所以原因得从 translator.last_error 取：否则用户只看到「翻译失败」，
        分不清是被审核拦了、Key 过期了，还是余额没了。
        """
        text = (text or "").strip()

        if not text:
            return None, ""

        tr_cfg = self.plugin_config.translator

        if not tr_cfg.enabled:
            return None, "检测到中文提示词，请先在插件配置中启用翻译器"

        if not tr_cfg.is_configured():
            return None, "翻译器未配置，请选择翻译提供商"

        translator = PromptTranslator(tr_cfg, context=self.context)

        translated = await translator.translate(
            text,
            danbooru_api_url=self.plugin_config.danbooru_api_url,
        )

        if not translated or has_chinese(translated):
            if translator.last_error is not None:
                return None, describe_api_error(
                    str(translator.last_error),
                    "提示词翻译",
                    False,
                )

            return None, "翻译服务返回的仍然是中文，请检查翻译提供商选用的模型"

        if apply_safety_filter:
            translated_check = self.safety.check_prompt(translated)

            if translated_check.filtered_prompt != translated:
                logger.info(
                    f"[BestNAI/Safety] 已自动过滤翻译后 prompt：{translated_check.reason}"
                )
                translated = translated_check.filtered_prompt

        if not translated:
            return None, "翻译结果被安全过滤清空了，请换个说法再试"

        if translator.last_character_tag and not prompt_has_tag(
            str(translated), translator.last_character_tag
        ):
            translator.last_character_tag = ""
            translator.last_series_tag = ""

        return TranslatedPrompt(
            str(translated),
            character_tag=translator.last_character_tag,
            series_tag=translator.last_series_tag,
        ), ""

    async def _send_images(
        self,
        event: AstrMessageEvent,
        images: List[Tuple[str, bytes]],
    ) -> AsyncGenerator:
        if not images:
            yield event.plain_result("❌ API 未返回图片")
            return

        for idx, (img_format, img_bytes) in enumerate(images, start=1):
            temp_path: Optional[str] = None

            try:
                temp_path = save_image_to_temp(img_bytes, img_format or "png")
                yield event.chain_result([Image.fromFileSystem(temp_path)])

            except Exception as e:
                logger.error(f"[BestNAI] 发送图片失败 idx={idx}: {e}")
                yield event.plain_result(f"❌ 发送图片失败：{e}")

            finally:
                if temp_path:
                    cleanup_file(temp_path)

    async def _do_generate(
        self,
        event: AstrMessageEvent,
        prompt: str,
        raw_mode: bool = False,
        show_progress: bool = True,
        progress_verb: str = "生图",
        followup_messages: Optional[List[str]] = None,
        fallback_ratio: str = "",
        user_ratio_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        model: str = "",
        characters: Optional[List[Dict[str, object]]] = None,
        use_coords: bool = False,
        use_order: bool = True,
    ) -> AsyncGenerator:
        # 模型由指令显式决定（/nai=4.5、/nai5=V5、/nai0=面板选择），
        # 缺省沿用主配置
        current_model = resolve_model_choice(model) if model else self.plugin_config.generation.model
        if raw_mode:
            prompt = self._strip_named_command_prefix(prompt, "nai0")
        else:
            prompt = self._strip_command_prefix(prompt)

        session_id = self._session_id(event)

        if not prompt:
            yield event.plain_result("❌ 请提供提示词")
            return

        if not raw_mode:
            switched, switch_msg = self._try_switch_artist_preset_command(
                prompt,
                session_id,
            )

            if switched:
                logger.info(f"[BestNAI] {switch_msg}")
                yield event.plain_result(f"✅ {switch_msg}")
                return

        if not self.plugin_config.is_configured():
            self._ensure_image_provider_ready()

        if not self.plugin_config.is_configured():
            yield event.plain_result(self._not_configured_message())
            return

        ratio_intent_prompt = prompt if user_ratio_prompt is None else user_ratio_prompt
        user_specified_ratio = prompt_has_explicit_ratio(
            ratio_intent_prompt,
            self._short_ratio_aliases(),
            self.ratio_presets,
            self._normalize_ratio_label,
        )

        # QQ 图片反推会把视觉 tags 拼到生成提示词中。视觉 tags 里的
        # portrait / landscape / 1:1 等普通描述不能被当成用户手写比例，
        # 否则会错误覆盖按原图尺寸推断出的比例。
        if user_ratio_prompt is not None and not user_specified_ratio:
            clean_prompt = prompt
            ratio_name = self.default_ratio
        else:
            clean_prompt, ratio_name = self._extract_ratio_from_prompt(prompt)

        artist_prompt_override = ""
        artist_slot_name = ""

        if not raw_mode:
            clean_prompt, artist_prompt_override, artist_slot_name = (
                self._extract_artist_slot_from_prompt(clean_prompt)
            )

        effective_artist_prompt = ""
        artist_ratio_adopted = False

        artist_prompt_for_ratio = ""

        if not raw_mode:
            artist_prompt_for_ratio = self._get_effective_artist_prompt(
                artist_prompt_override,
                session_id,
            )

        artist_has_ratio = bool(artist_prompt_for_ratio) and prompt_has_explicit_ratio(
            artist_prompt_for_ratio,
            self._short_ratio_aliases(),
            self.ratio_presets,
            self._normalize_ratio_label,
        )

        ratio_source = choose_ratio_source(
            user_specified=user_specified_ratio,
            artist_has_ratio=artist_has_ratio,
            has_inferred_ratio=bool(fallback_ratio),
        )

        if ratio_source == RATIO_SOURCE_ARTIST:
            effective_artist_prompt, ratio_name = self._extract_ratio_from_prompt(
                artist_prompt_for_ratio
            )
            artist_ratio_adopted = True

            logger.info(
                f"[BestNAI] 用户未指定比例，从画师提示词提取比例：{ratio_name}"
            )

        elif ratio_source == RATIO_SOURCE_IMAGE:
            ratio_name = fallback_ratio

            logger.info(
                f"[BestNAI] 用户与画师串均未指定比例，使用输入图片推断的比例：{ratio_name}"
            )

        logger.info(
            f"[BestNAI] 解析后 prompt='{clean_prompt}', ratio='{ratio_name}', "
            f"artist_slot='{artist_slot_name}', "
            f"session_artist='{self._get_session_artist_slot(session_id)}', "
            f"raw_mode={raw_mode}"
        )

        if not clean_prompt:
            yield event.plain_result("❌ 请提供有效提示词，比例/尺寸或画师预设不能单独作为提示词")
            return

        if artist_slot_name:
            logger.info(f"[BestNAI] 本次使用画师预设：{artist_slot_name}")

        prompt_check = self.safety.check_prompt(clean_prompt)

        if prompt_check.filtered_prompt != clean_prompt:
            logger.info(
                f"[BestNAI/Safety] 已自动过滤 prompt：{prompt_check.reason}"
            )
            clean_prompt = prompt_check.filtered_prompt

        if not clean_prompt:
            yield event.plain_result("❌ 提示词过滤后为空，请补充安全的有效提示词")
            return

        try:
            gen_config: GenerationConfig = self.prompt_builder.build_generation_config(ratio_name)

            if raw_mode:
                gen_config = replace(
                    gen_config,
                    quality=False,
                )

            # 模型由指令决定（/nai=4.5、/nai5=V5、/nai0=面板选择）
            gen_config = replace(gen_config, model=current_model)

            character_entries = normalize_char_entries(characters)
            if character_entries:
                gen_config = replace(
                    gen_config,
                    characters=character_entries,
                    use_coords=bool(use_coords),
                    use_order=bool(use_order),
                )

        except Exception as e:
            yield event.plain_result(
                f"❌ 无效比例/尺寸：{ratio_name}\n"
                "可用比例：16:9、9:16、4:3、3:4、3:2、2:3、1:1、5:4、4:5、7:4、4:7、12:5、5:12、21:9、9:21，也可输入横屏、竖屏、方图\n"
                "也可以直接使用 1024x1024"
            )
            logger.warning(f"[BestNAI] 解析比例失败 ratio={ratio_name}: {e}")
            return

        if show_progress:
            yield event.plain_result(
                self._format_generation_progress(
                    ratio_name,
                    gen_config,
                    raw_mode,
                    progress_verb,
                    artist_slot_name,
                    session_id,
                )
            )

        if followup_messages:
            yield event.plain_result("\n\n".join(followup_messages))

        final_prompt = clean_prompt
        tr_cfg = self.plugin_config.translator

        # Raw mode is literal: send the user's text without translation or
        # Danbooru lookup.  Safety filtering still runs below as a separate
        # platform requirement.
        if has_chinese(clean_prompt) and not raw_mode:
            if not tr_cfg.enabled:
                yield event.plain_result(
                    "❌ 检测到中文提示词，但翻译功能未开启。请启用翻译器。"
                )
                return

            if not tr_cfg.is_configured():
                yield event.plain_result(
                    "❌ 翻译器未配置。请在 translator_config 中选择翻译提供商。"
                )
                return

            translated = await self._translate_prompt(clean_prompt)

            if not translated:
                yield event.plain_result("❌ 翻译失败，请检查翻译提供商配置。")
                return

            if tr_cfg.show_result:
                yield event.plain_result(f"🔎 翻译结果：\n{translated}")

            final_prompt = translated

        if raw_mode:
            # Keep the prompt byte-for-byte as entered (apart from the safety
            # filter that is applied after assembly below).
            final_prompt = clean_prompt

        else:
            artist_prompt = (
                effective_artist_prompt
                if artist_ratio_adopted
                else artist_prompt_for_ratio
            )

            final_prompt = self.prompt_builder.build_final_prompt(
                final_prompt,
                artist_prompt=artist_prompt,
                suffix=self.plugin_config.prompt_suffix or "",
            )

        # Run the QQ prompt filter again after translation, retag merging,
        # artist presets, and the quality suffix have all been assembled. This
        # closes the gap where a later-added English tag could bypass the
        # earlier user-input-only check.
        final_prompt_check = self.safety.check_prompt(final_prompt)
        if final_prompt_check.filtered_prompt != final_prompt:
            logger.info(
                f"[BestNAI/Safety] 已自动过滤最终 prompt：{final_prompt_check.reason}"
            )
            final_prompt = final_prompt_check.filtered_prompt

        if not final_prompt:
            if raw_mode and has_chinese(clean_prompt):
                yield event.plain_result(
                    "❌ 提示词清理后为空：中文提示词翻译结果为空，请检查翻译提供商，"
                    "或改用英文提示词"
                )
            else:
                yield event.plain_result("❌ 提示词清理后为空，请输入英文提示词或开启中文翻译")
            return

        try:
            if show_progress and self._generation_semaphore.locked():
                yield event.plain_result(
                    f"⏳ 当前生图任务排队中（并发上限 {self.plugin_config.max_concurrency}），请稍候..."
                )

            async with self._generation_semaphore:
                api_url, api_key = self._provider_credentials_for_model(current_model)
                try:
                    result = await self.generator.generate(
                        final_prompt,
                        gen_config,
                        seed=seed,
                        api_url=api_url,
                        api_key=api_key,
                    )
                except GenerationError as exc:
                    if not _unsupported_sampler_error(exc):
                        raise
                    fallback_sampler = str(
                        self.plugin_config.generation.sampler
                        or "k_euler_ancestral"
                    ).strip()
                    if fallback_sampler == gen_config.sampler:
                        raise
                    logger.warning(
                        "[BestNAI] 网关不支持采样器 %s，回退到 %s",
                        gen_config.sampler,
                        fallback_sampler,
                    )
                    result = await self.generator.generate(
                        final_prompt,
                        replace(gen_config, sampler=fallback_sampler),
                        seed=seed,
                        api_url=api_url,
                        api_key=api_key,
                    )

            images = result.images
            safe_images: List[Tuple[str, bytes]] = []

            if self.plugin_config.safety.enabled:
                for img_format, img_bytes in images:
                    audit = await self.safety.check_image(img_bytes)

                    if not audit.safe:
                        logger.warning(
                            f"[BestNAI/Safety] 图片审核未通过 source={audit.source}, reason={audit.reason}"
                        )
                        yield event.plain_result(SAFETY_BLOCK_REPLY)
                        return

                    safe_images.append((img_format, img_bytes))
            else:
                safe_images = images

            async for result in self._send_images(event, safe_images):
                yield result

        except APIKeyError as e:
            yield event.plain_result(f"❌ API Key 错误：{e.message}")

        except QuotaExceededError as e:
            yield event.plain_result(f"❌ {e.message}")

        except RateLimitError as e:
            yield event.plain_result(f"⏳ {e.message}")

        except ServerBusyError as e:
            yield event.plain_result(f"🔄 {e.message}")

        except GenerationError as e:
            logger.error(f"[BestNAI] 生成失败: {e}")
            yield event.plain_result(f"❌ 生成失败：{e.message}")

        except Exception as e:
            logger.exception(f"[BestNAI] 未知错误: {e}")
            yield event.plain_result("❌ 发生未知错误，请稍后重试")

    async def _handle_nai_command(
        self,
        event: AstrMessageEvent,
        command_name: str,
        raw_mode: bool = False,
        model: str = "",
    ) -> AsyncGenerator:
        # command_name 必须由调用方显式给出，不能有默认值：剥前缀的正则是
        # `nai(?:\s+|$)`，用 "nai" 去剥 "nai5 可爱 1girl" 匹配不上、原样返回，
        # 于是画师预设名匹配到的是 "nai5"。这个坑踩过一次，别再留默认值。
        if not model:
            model = (
                MODEL_V45_FULL
                if raw_mode
                else self.plugin_config.generation.model
            )

        prompt = self._strip_named_command_prefix(event.message_str, command_name)
        _, prompt = extract_retag_mode(prompt)

        image_src = extract_image_from_event_best_effort(event)

        mentioned_qq = ""

        if not image_src:
            mentioned_qq = extract_mentioned_qq_from_event(event)

            if mentioned_qq:
                image_src = qq_avatar_url(mentioned_qq, size=640)
                prompt = remove_mention_from_prompt(prompt, mentioned_qq)

                logger.info(
                    f"[BestNAI/ImageRetag] 检测到 @ 用户，使用 QQ 头像反推：qq={mentioned_qq}, url={image_src}"
                )

        if image_src:
            # Original NAI PNG/JPEG/WebP exports (and SD WebUI images) can
            # carry their own prompt and seed. Use
            # that deterministic path before requiring a vision retag
            # provider; QQ often exposes the image as a URL.
            source_info = await read_image_generation_info_any(image_src)
            source_seed = normalize_nai_seed(source_info.get("seed"))
            raw_source_prompt = strip_control_tags(
                str(source_info.get("prompt") or "").strip(),
                extra_control_tags=self.plugin_config.get_retag_control_prompts(),
            )
            # A prompt embedded in a NovelAI PNG remains useful even if a
            # re-encoder dropped the seed.  Skip the vision call whenever the
            # canonical source prompt is available; the seed is only used
            # later when deterministic reproduction is possible.
            metadata_retag = bool(raw_source_prompt) and is_trusted_nai_generation_info(
                source_info
            )
            source_prompt = raw_source_prompt if metadata_retag else ""
            source_char_prompts = (
                normalize_char_entries(source_info.get("characterPrompts"))
                if metadata_retag
                else []
            )
            source_char_use_coords = bool(
                metadata_retag
                and source_info.get("characterUseCoords")
                and source_char_prompts
            )
            source_char_use_order = bool(
                metadata_retag
                and source_char_prompts
                and source_info.get("characterUseOrder", True)
            )

            if not metadata_retag and not self.plugin_config.image_retag.enabled:
                yield event.plain_result(
                    "❌ 检测到图片或 @ 头像，但图片反推功能未开启。请在配置中启用“图片反推提示词”。"
                )
                return

            if not metadata_retag and not self.plugin_config.image_retag.is_configured():
                yield event.plain_result(
                    "❌ 图片反推功能未配置。请在 image_retag_config 中选择图片反推接口提供商。"
                )
                return

            if not self.plugin_config.is_configured():
                self._ensure_image_provider_ready()

            if not self.plugin_config.is_configured():
                yield event.plain_result(self._not_configured_message())
                return

            inferred_ratio = ""

            if not prompt_has_explicit_ratio(
                prompt,
                self._short_ratio_aliases(),
                self.ratio_presets,
                self._normalize_ratio_label,
            ):
                try:
                    img_w, img_h = await read_image_size_any(image_src)
                    inferred_ratio = infer_ratio_label_from_size(img_w, img_h)

                    logger.info(
                        f"[BestNAI/ImageRetag] 已根据输入图片尺寸推断比例：{img_w}x{img_h} -> {inferred_ratio}"
                    )

                except Exception as e:
                    logger.warning(f"[BestNAI/ImageRetag] 读取输入图片比例失败，使用默认比例: {e}")
                    inferred_ratio = ""

            try:
                retag_progress = self._progress_message_for_prompt(
                    prompt,
                    raw_mode,
                    "反推",
                    self._session_id(event),
                    fallback_ratio=inferred_ratio,
                    model=model,
                )
            except Exception as e:
                yield event.plain_result(
                    f"❌ 无效比例/尺寸：{prompt}\n"
                    "可用比例：16:9、9:16、4:3、3:4、3:2、2:3、1:1、5:4、4:5、7:4、4:7、12:5、5:12、21:9、9:21，也可输入横屏、竖屏、方图\n"
                    "也可以直接使用 1024x1024"
                )
                logger.warning(f"[BestNAI] 反推进度解析失败 prompt={prompt}: {e}")
                return

            yield event.plain_result(retag_progress)

            try:
                if metadata_retag:
                    source_character, source_series = await self._resolve_prompt_identity(
                        source_prompt,
                        timeout=3.0,
                    )
                    retag_result = {
                        "prompt": source_prompt,
                        "character": source_character,
                        "series": source_series,
                        "seed": source_seed,
                        "fromMetadata": True,
                        "charPrompts": source_char_prompts,
                        "charUseCoords": source_char_use_coords,
                        "charUseOrder": source_char_use_order,
                    }
                    logger.info(
                        f"[BestNAI/ImageRetag] QQ 图片读取 NovelAI 内嵌参数：seed={source_seed}"
                    )
                else:
                    retag_result = await self.image_retagger.retag_details(image_src)
                retag_prompt = str(retag_result.get("prompt") or "").strip()

            except ImageRetagError as e:
                message = strip_error_subject(str(e), "图片反推")
                yield event.plain_result(f"❌ 图片反推失败：{message or '接口没有返回错误信息'}")
                return

            retag_char_prompts = normalize_char_entries(
                retag_result.get("charPrompts")
                or retag_result.get("characterPrompts")
            )
            retag_use_coords = bool(
                retag_result.get("charUseCoords")
                or retag_result.get("characterUseCoords")
            )
            retag_use_order = bool(
                retag_result.get(
                    "charUseOrder",
                    retag_result.get("characterUseOrder", True),
                )
            )

            if not retag_prompt:
                yield event.plain_result("❌ 图片反推结果为空")
                return

            show_messages: List[str] = []

            if self.plugin_config.image_retag.show_result:
                title = "头像反推结果" if mentioned_qq else "反推结果"
                show_messages.append(f"🔎 {title}：\n{retag_prompt}")

            if prompt:
                ratio_prompt, ratio_name = self._extract_ratio_from_prompt(prompt)
                if raw_mode:
                    desc_part, artist_name = ratio_prompt, ""
                else:
                    desc_part, _, artist_name = self._extract_artist_slot_from_prompt(
                        ratio_prompt
                    )

                user_prompt_for_merge = desc_part
                user_character = ""
                user_series = ""

                if desc_part and has_chinese(desc_part) and not raw_mode:
                    tr_cfg = self.plugin_config.translator

                    if not tr_cfg.enabled:
                        yield event.plain_result(
                            "❌ 检测到中文提示词，但翻译功能未开启。请启用翻译器。"
                        )
                        return

                    if not tr_cfg.is_configured():
                        yield event.plain_result(
                            "❌ 翻译器未配置。请在 translator_config 中选择翻译提供商。"
                        )
                        return

                    translated = await self._translate_prompt(desc_part)

                    if not translated:
                        yield event.plain_result("❌ 翻译失败，请检查翻译提供商配置。")
                        return

                    if tr_cfg.show_result:
                        if show_messages:
                            show_messages[0] += f"\n{translated}"
                        else:
                            show_messages.append(f"🔎 翻译结果：\n{translated}")

                    user_prompt_for_merge = translated
                    user_character = str(
                        getattr(translated, "character_tag", "") or ""
                    ).strip()
                    user_series = str(
                        getattr(translated, "series_tag", "") or ""
                    ).strip()
                else:
                    user_prompt_for_merge = user_prompt_for_merge or ""
                    if desc_part and not raw_mode:
                        user_character, user_series = (
                            await self._resolve_prompt_identity(desc_part)
                        )

                if raw_mode:
                    # Raw mode is literal: do not translate, resolve identity,
                    # weight, deduplicate, or classify the user's text.
                    merged_prompt = ", ".join(
                        part for part in (desc_part, retag_prompt) if part
                    )
                else:
                    merge_details = merge_retag_prompt_details(
                        user_prompt_for_merge,
                        retag_prompt,
                        original_user_prompt=prompt,
                        user_character=user_character,
                        user_series=user_series,
                        source_character=str(retag_result.get("character") or ""),
                        source_series=str(retag_result.get("series") or ""),
                        weight_user=True,
                    )
                    merged_overlay = str(merge_details.get("prompt") or "")
                    if merge_details.get("conflicts"):
                        logger.info(
                            "[BestNAI/ImageRetag] 已处理提示词冲突："
                            f"{merge_details['conflicts']}"
                        )
                    controls = []
                    if prompt_has_explicit_ratio(
                        prompt,
                        self._short_ratio_aliases(),
                        self.ratio_presets,
                        self._normalize_ratio_label,
                    ) and ratio_name:
                        controls.append(ratio_name)
                    if artist_name:
                        controls.append(artist_name)
                    merged_prompt = ", ".join(
                        part for part in (*controls, merged_overlay) if part
                    )
            else:
                merged_prompt = retag_prompt

            # 推断出的比例不能拼进提示词：那样会被当成用户手写的比例，
            # 从而盖掉画师串里配置的比例。作为参数传下去，优先级低于画师串。
            async for result in self._do_generate(
                event=event,
                prompt=merged_prompt,
                raw_mode=raw_mode,
                show_progress=False,
                progress_verb="反推",
                followup_messages=show_messages,
                fallback_ratio=inferred_ratio,
                user_ratio_prompt=prompt,
                seed=source_seed if metadata_retag else None,
                model=model,
                characters=retag_char_prompts,
                use_coords=retag_use_coords,
                use_order=retag_use_order,
            ):
                yield result

            return

        if not prompt:
            if raw_mode:
                yield event.plain_result(
                    "❌ 请提供提示词，例如：/nai0 cat\n"
                    "nai0 不会追加画师串和质量提示词，但仍会沿用负面提示词。"
                )
            else:
                yield event.plain_result(
                    "❌ 请提供提示词，例如：/nai 海报 miku\n"
                    "也可以发送/回复图片后使用 /nai 进行图片反推生图，或使用 /nai @某人 以头像反推生图。"
                )
            return

        async for result in self._do_generate(
            event=event,
            prompt=prompt,
            raw_mode=raw_mode,
            model=model,
        ):
            yield result

    @filter.command("nai")
    async def cmd_nai(self, event: AstrMessageEvent) -> AsyncGenerator:
        """NAI 生图（4.5 模型）。用法：/nai 提示词；/nai + 图片 反推图片提示词后生图；/nai @某人 使用头像反推生图。"""
        async for result in self._handle_nai_command(
            event, raw_mode=False, model=MODEL_V45_FULL, command_name="nai"
        ):
            yield result

    @filter.command("nai5")
    async def cmd_nai5(self, event: AstrMessageEvent) -> AsyncGenerator:
        """NAI 生图（V5 模型）。用法：/nai5 提示词；支持中文自然语言提示。"""
        async for result in self._handle_nai_command(
            event, raw_mode=False, model=MODEL_V5_FULL, command_name="nai5"
        ):
            yield result

    @filter.command("nai0")
    async def cmd_nai0(self, event: AstrMessageEvent) -> AsyncGenerator:
        """NAI 4.5 原始提示词生图。"""
        async for result in self._handle_nai_command(
            event,
            raw_mode=True,
            model=MODEL_V45_FULL,
            command_name="nai0",
        ):
            yield result

    @filter.command("nai50")
    async def cmd_nai50(self, event: AstrMessageEvent) -> AsyncGenerator:
        """NAI V5 原始提示词生图。"""
        async for result in self._handle_nai_command(
            event,
            raw_mode=True,
            model=MODEL_V5_FULL,
            command_name="nai50",
        ):
            yield result

    @filter.command("画师画廊")
    async def cmd_artist_gallery(self, event: AstrMessageEvent) -> AsyncGenerator:
        """查看 BestNAI 画师预设画廊。"""
        presets = self.plugin_config.get_artist_presets_map()

        # 画廊要用 PIL 拼图，放线程里跑，别卡住整个 AstrBot 事件循环
        ok, result = await asyncio.to_thread(
            self.artist_gallery.build_or_get_gallery,
            presets,
        )

        if not ok:
            yield event.plain_result(f"❌ 生成画师画廊失败：{result}")
            return

        async for r in send_image_best_effort(event, result):
            yield r

    @filter.command("查看画师")
    async def cmd_view_artist_preset(self, event: AstrMessageEvent) -> AsyncGenerator:
        """查看指定画师预设的画师串和预览图。用法：/查看画师 预设名。"""
        raw = (event.message_str or "").strip()

        preset_name = re.sub(
            r"^\s*[\/／]?查看画师",
            "",
            raw,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        preset_name = self._normalize_artist_switch_name(preset_name)

        if not preset_name:
            yield event.plain_result("❌ 请提供画师预设名，例如：/查看画师 可爱")
            return

        real_key, artist_prompt = self._find_artist_slot(preset_name)

        if not real_key:
            available = "、".join(self.plugin_config.get_artist_presets_map().keys())
            if available:
                yield event.plain_result(f"❌ 找不到画师预设：{preset_name}\n可用预设：{available}")
            else:
                yield event.plain_result("❌ 当前没有配置画师预设")
            return

        preview_path = self.artist_gallery.get_preview_path(real_key)

        if preview_path:
            yield event.plain_result(
                f"🎨 画师预设：{real_key}\n"
                f"画师串：\n{artist_prompt}"
            )

            async for r in send_image_best_effort(event, preview_path):
                yield r

            return

        yield event.plain_result(
            f"🎨 画师预设：{real_key}\n"
            f"画师串：\n{artist_prompt}\n\n"
            f"🖼️ 暂未设置预览图，可发送或回复图片后使用：/设置画师 {real_key}"
        )

    @filter.command("设置画师")
    async def cmd_set_artist_gallery_image(self, event: AstrMessageEvent) -> AsyncGenerator:
        """设置画师预设画廊预览图。用法：发送或回复图片并输入 /设置画师 预设名。"""
        raw = (event.message_str or "").strip()

        preset_name = re.sub(
            r"^\s*[\/／]?设置画师",
            "",
            raw,
            count=1,
            flags=re.IGNORECASE,
        ).strip()

        if not preset_name:
            yield event.plain_result("❌ 请提供画师预设名，例如：/设置画师 可爱，并附带或回复一张图片")
            return

        real_key, _artist_prompt = self._find_artist_slot(preset_name)

        if not real_key:
            available = "、".join(self.plugin_config.get_artist_presets_map().keys())
            yield event.plain_result(f"❌ 找不到画师预设：{preset_name}\n可用预设：{available}")
            return

        img = extract_image_from_event_best_effort(event)

        if not img:
            yield event.plain_result(
                "❌ 未检测到图片。\n"
                "请把图片和命令放同一条消息，例如：图片 + /设置画师 可爱\n"
                "也可以回复图片后发送：/设置画师 可爱"
            )
            return

        # 预览图可能是 http 链接，下载走的是同步 urllib，必须放线程里
        ok = await asyncio.to_thread(self.artist_gallery.record_preview, real_key, img)

        if not ok:
            yield event.plain_result("❌ 画师预览图保存失败，请重试")
            return

        yield event.plain_result(f"✅ 已设置画师预设「{real_key}」的预览图")

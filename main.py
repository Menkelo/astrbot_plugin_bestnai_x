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
)
from .core.api_errors import describe_api_error
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
from .core.safety import SafetyModerator
from .core.translator import (
    DanbooruTagRetriever,
    PromptTranslator,
    TranslatedPrompt,
    has_chinese,
    prompt_has_tag,
    resolve_character_candidate,
    resolve_translation_cache,
)
from .image_store import send_image_best_effort
from .models.config import GenerationConfig, PluginConfig
from .services.artist_gallery import ArtistGalleryService
from .services.canvas import CanvasService
from .services.image_extract import extract_image_from_event_best_effort
from .services.image_ratio import (
    choose_ratio_source,
    infer_ratio_label_from_size,
    prompt_has_explicit_ratio,
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
from .services.prompt_merge import merge_retag_prompt
from .services.nai_metadata import read_image_generation_info, read_image_generation_info_any
from .services.runtime_state import RuntimeStateService


FIXED_MODEL = "nai-diffusion-4-5-full"
SAFETY_BLOCK_REPLY = "⚠️ 未能通过安全检测，已拦截"

# 画布可手动调节的生图参数范围
# 步数上限锁在 28：NovelAI 的免费额度只在 ≤28 步时生效，超过就开始扣 Anlas。
MIN_STEPS = 1
MAX_STEPS = 28
MIN_SCALE = 1.0
MAX_SCALE = 10.0

# NovelAI 4.5-compatible canvas presets. Every dimension is a 64 multiple and
# stays below the plugin's ~1.1 MP safety limit.
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


def _merge_canvas_retag_prompt(
    translated_user_prompt: str,
    retag_prompt: str,
    *,
    original_user_prompt: str = "",
    user_character: str = "",
    user_series: str = "",
    source_character: str = "",
    source_series: str = "",
) -> str:
    return merge_retag_prompt(
        translated_user_prompt,
        retag_prompt,
        original_user_prompt=original_user_prompt,
        user_character=user_character,
        user_series=user_series,
        source_character=source_character,
        source_series=source_series,
        weight_user=True,
    )


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
        )

        api_source = (
            "手动生图 API"
            if getattr(self.plugin_config, "use_manual_api", False)
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
            f"模型={FIXED_MODEL}，"
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
                    "label": f"{name} · {width}×{height}",
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
            "model": FIXED_MODEL,
            "defaultRatio": self._normalize_ratio_label(self.default_ratio),
            "defaultArtist": self._get_default_artist_display_name(),
            "ratios": ratios,
            "artists": artists,
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

    async def _canvas_retag(
        self,
        image_path: str,
        user_hint: str,
        debug: bool = False,
    ) -> Dict[str, object]:
        retag_config = self.plugin_config.image_retag
        trace = DebugTrace("canvas.retag", bool(debug))
        trace.note("手写提示词（仅用于后续生图）", user_hint or "(空)")

        # 先看图片自带的 NovelAI 生成参数。命中就不必让视觉模型猜了，
        # 原始 prompt 和种子一起用能真正还原这张图。
        # 注意元数据只存在于未经重编码的原始 PNG 里。
        with trace.stage("读原图内嵌参数"):
            source_info = await asyncio.to_thread(read_image_generation_info, image_path)

        source_seed = source_info.get("seed")
        source_prompt = strip_control_tags(str(source_info.get("prompt") or "").strip())

        if source_seed is not None and source_prompt:
            logger.info(
                f"[BestNAI/Canvas] 图片自带 NovelAI 参数，直接复用：seed={source_seed}"
            )

            # PNG metadata already contains the canonical prompt, but it does
            # not carry the structured character/series fields used by the
            # overlay merger.  Resolve exact tags once so replacing a role in
            # a metadata-backed image cannot leave the old identity behind.
            with trace.stage("原图角色标签检索"):
                source_character, source_series = (
                    await self._resolve_prompt_identity(source_prompt, timeout=3.0)
                )

            # Return only image tags. The caller translates and weights the
            # current hand-written hint exactly once during generation.
            image_tags = source_prompt

            trace.note("走的分支", "命中原图内嵌参数，未调用视觉模型")
            trace.note("手写提示词（不送反推）", user_hint or "(空)")
            trace.note("原图图片 tags", image_tags)
            trace.note(
                "原图角色",
                ", ".join(
                    part for part in (source_character, source_series) if part
                ) or "(未识别)",
            )
            trace.note(
                "原图内嵌参数",
                {
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
                    "ratio": self._ratio_from_generation_info(source_info, image_path),
                    "seed": source_seed,
                    "sourcePrompt": source_prompt,
                    "fromMetadata": True,
                    "steps": source_info.get("steps"),
                    "scale": source_info.get("scale"),
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
                # The selected provider owns the vision model.  Older config
                # versions exposed a model field on ImageRetagConfig, but the
                # current schema intentionally does not; never dereference it
                # directly when an external canvas image enters this branch.
                "model": getattr(retag_config, "model", "") or "(provider default)",
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
            raise ValueError(str(exc)) from exc

        prompt = str(retag_result.get("prompt") or "").strip()

        if not prompt:
            raise ValueError("图片反推结果为空")

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
                "character": str(retag_result.get("character") or ""),
                "series": str(retag_result.get("series") or ""),
                "ratio": ratio,
                "seed": source_seed,
                "fromMetadata": False,
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
        retag_prompt = str(payload.get("retagPrompt") or "").strip()
        retag_character = str(payload.get("retagCharacter") or "").strip()
        retag_series = str(payload.get("retagSeries") or "").strip()
        if retag_character and not prompt_has_tag(retag_prompt, retag_character):
            # Do not trust stale structured metadata after an older retag
            # result was edited or migrated; the prompt itself is authoritative.
            retag_character = ""
        if retag_series and not prompt_has_tag(retag_prompt, retag_series):
            retag_series = ""
        ratio = str(payload.get("ratio") or self.default_ratio).strip()
        artist_name = str(payload.get("artist") or "").strip()
        raw_mode = bool(payload.get("raw", False))

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

        if has_chinese(clean_prompt):
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
        # request. Merge them only after translating the user's prompt so the
        # translation provider never receives the mixed/weighted string.
        if retag_prompt:
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
                    translated_character, translated_series = (
                        await self._resolve_prompt_identity(clean_prompt)
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
            working_prompt = _merge_canvas_retag_prompt(
                translated_user_prompt,
                retag_prompt,
                original_user_prompt=prompt,
                user_character=translated_character,
                user_series=translated_series,
                source_character=retag_character,
                source_series=retag_series,
            )
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
            steps=self._clamp_steps(payload.get("steps"), gen_config.steps),
            scale=self._clamp_scale(payload.get("scale"), gen_config.scale),
        )

        resolved_artist_name = ""
        artist_prompt = ""

        if raw_mode:
            gen_config = replace(gen_config, quality=False)
            final_prompt = normalize_prompt_ascii(working_prompt)
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
                "model": FIXED_MODEL,
                "width": gen_config.width,
                "height": gen_config.height,
                "steps": gen_config.steps,
                "scale": gen_config.scale,
                "seed": payload.get("seed") or "(随机)",
                "raw": raw_mode,
            },
        )

        # 信号量占用也算进耗时：并发满了在这儿排队，用户看到的就是"生图很慢"
        with trace.stage("生图"):
            async with self._generation_semaphore:
                result = await self.generator.generate(
                    final_prompt,
                    gen_config,
                    seed=payload.get("seed"),
                )

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
                "raw": raw_mode,
                "model": FIXED_MODEL,
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

    def _resolve_image_provider(self) -> None:
        prefer_provider = bool(getattr(self.plugin_config, "prefer_provider", True))
        provider_id = getattr(self.plugin_config, "image_provider_id", "") or ""

        manual_api_url = (getattr(self.plugin_config, "api_url", "") or "").strip().rstrip("/")
        manual_api_key = (getattr(self.plugin_config, "api_key", "") or "").strip()

        self.plugin_config.use_manual_api = False
        # 只有真正拿到接口配置才算就绪；否则每次生图前都会再试一次
        self._image_provider_resolved = False

        if not prefer_provider:
            if manual_api_url and manual_api_key:
                self.plugin_config.api_url = manual_api_url
                self.plugin_config.api_key = manual_api_key
                self.plugin_config.use_manual_api = True
                self._image_provider_resolved = True

                logger.info(
                    f"[BestNAI] 已使用手动生图 API，模式=/chat/completions，api_base={self.plugin_config.api_url}"
                )
                return

            logger.warning("[BestNAI] 已关闭优先使用提供商，但未填写完整手动生图 API 地址/API Key")
            return

        if not provider_id:
            logger.warning("[BestNAI] 已开启优先使用提供商，但未选择生图接口提供商")
            self._warn_if_falling_back_to_manual(manual_api_url, manual_api_key)
            return

        try:
            provider = self.context.get_provider_by_id(provider_id)
        except Exception as e:
            logger.warning(f"[BestNAI] 获取生图接口提供商失败 provider_id={provider_id}: {e}")
            self._warn_if_falling_back_to_manual(manual_api_url, manual_api_key)
            return

        if not provider:
            logger.warning(f"[BestNAI] 找不到生图接口提供商 ID: {provider_id}")
            self._warn_if_falling_back_to_manual(manual_api_url, manual_api_key)
            return

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
            self._warn_if_falling_back_to_manual(manual_api_url, manual_api_key)
            return

        if not api_key:
            logger.warning(f"[BestNAI] 生图接口提供商 {provider_id} 缺少 API Key")
            self._warn_if_falling_back_to_manual(manual_api_url, manual_api_key)
            return

        self.plugin_config.api_url = str(base_url).rstrip("/")
        self.plugin_config.api_key = str(api_key)
        self.plugin_config.use_manual_api = False
        self._image_provider_resolved = True

        logger.info(
            f"[BestNAI] 已使用生图接口提供商：{provider_id}，api_base={self.plugin_config.api_url}"
        )

    def _warn_if_falling_back_to_manual(self, api_url: str, api_key: str) -> None:
        """提供商没解析出来、但配置里还留着手动 API 时提醒一句。

        这种情况下插件会拿旧的手动地址继续跑，容易被误认为提供商生效了。
        """
        if api_url and api_key:
            logger.warning(
                f"[BestNAI] 生图提供商未就绪，本次将改用配置中残留的手动 API：{api_url}。"
                "如果这不是你想要的，请清空手动 API 地址/Key，或关闭“优先使用提供商”。"
            )

    def _ensure_image_provider_ready(self) -> None:
        """
        Bot 重启时 AstrBot provider 可能晚于插件初始化完成。
        只要提供商还没真正解析成功，就在每次生图前再试一次，
        避免必须手动重载插件。
        """
        if getattr(self.plugin_config, "use_manual_api", False):
            return

        if getattr(self, "_image_provider_resolved", False):
            return

        logger.info("[BestNAI] 生图接口尚未就绪，尝试重新解析生图提供商")
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

        if width * height > 1_100_000:
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

        target_ratio = width / height
        target_area = width * height

        candidates = CANVAS_RATIO_PRESETS

        def score(item):
            _, (cw, ch) = item
            candidate_ratio = cw / ch
            candidate_area = cw * ch
            ratio_score = abs(candidate_ratio - target_ratio)
            area_score = abs(candidate_area - target_area) / max(target_area, 1)
            return ratio_score * 10 + area_score

        best_name, best_size = min(candidates.items(), key=score)

        logger.warning(
            f"[BestNAI] 输入尺寸 {width}x{height} 非法，"
            f"已锚定到 {best_name} {best_size[0]}x{best_size[1]}"
        )

        return best_size

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

        if raw_mode:
            return f"🎨 正在{progress_verb}（{ratio_display} | nai0 原始提示词模式）..."

        artist_display = self._get_artist_display_name(artist_slot_name, session_id)
        return f"🎨 正在{progress_verb}（{ratio_display} | 画师预设：{artist_display}）..."

    def _progress_message_for_prompt(
        self,
        prompt: str,
        raw_mode: bool,
        progress_verb: str,
        session_id: str = "",
        fallback_ratio: str = "",
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
        query = str(text or "").strip()
        api_url = str(getattr(self.plugin_config, "danbooru_api_url", "") or "").strip()
        if not query or not api_url:
            return "", ""

        retriever = DanbooruTagRetriever(base_url=api_url, timeout=timeout)
        results = await retriever.retrieve(query)
        character, series = resolve_character_candidate(query, results)
        if character:
            logger.info(
                f"[BestNAI] tags 站确认角色标签：{character}"
                f"{f'（{series}）' if series else ''}"
            )
        return character, series

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
    ) -> AsyncGenerator:
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
            yield event.plain_result(
                "❌ 插件未配置。\n"
                "请开启“优先使用提供商”并选择生图接口提供商，或关闭该开关后填写完整手动生图 API 地址/API Key。"
            )
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

        if has_chinese(clean_prompt):
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
            raw_before_clean = final_prompt
            final_prompt = normalize_prompt_ascii(final_prompt)

            removed_chars = find_non_ascii_chars(raw_before_clean)

            if removed_chars:
                logger.info(
                    f"[BestNAI/nai0] 已自动清理 prompt 中的非 ASCII 字符：{' '.join(removed_chars)}"
                )

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

        if not final_prompt:
            yield event.plain_result("❌ 提示词清理后为空，请输入英文提示词或开启中文翻译")
            return

        try:
            if show_progress and self._generation_semaphore.locked():
                yield event.plain_result(
                    f"⏳ 当前生图任务排队中（并发上限 {self.plugin_config.max_concurrency}），请稍候..."
                )

            async with self._generation_semaphore:
                result = await self.generator.generate(
                    final_prompt,
                    gen_config,
                    seed=seed,
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
        raw_mode: bool = False,
    ) -> AsyncGenerator:
        command_name = "nai0" if raw_mode else "nai"

        prompt = self._strip_named_command_prefix(event.message_str, command_name)

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
            # Original NovelAI PNGs can carry their own prompt and seed. Use
            # that deterministic path before requiring a vision retag
            # provider; QQ often exposes the image as a URL.
            source_info = await read_image_generation_info_any(image_src)
            source_seed = source_info.get("seed")
            source_prompt = strip_control_tags(
                str(source_info.get("prompt") or "").strip()
            )
            metadata_retag = source_seed is not None and bool(source_prompt)

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
                yield event.plain_result(
                    "❌ 插件未配置。\n"
                    "请开启“优先使用提供商”并选择生图接口提供商，或关闭该开关后填写完整手动生图 API 地址/API Key。"
                )
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
                    }
                    logger.info(
                        f"[BestNAI/ImageRetag] QQ 图片读取 NovelAI 内嵌参数：seed={source_seed}"
                    )
                else:
                    retag_result = await self.image_retagger.retag_details(image_src)
                retag_prompt = str(retag_result.get("prompt") or "").strip()

            except ImageRetagError as e:
                yield event.plain_result(f"❌ 图片反推失败：{e}")
                return

            if not retag_prompt:
                yield event.plain_result("❌ 图片反推结果为空")
                return

            show_messages: List[str] = []

            if self.plugin_config.image_retag.show_result:
                title = "头像反推结果" if mentioned_qq else "反推结果"
                show_messages.append(f"🔎 {title}：\n{retag_prompt}")

            if prompt:
                ratio_prompt, ratio_name = self._extract_ratio_from_prompt(prompt)
                desc_part, _, artist_name = self._extract_artist_slot_from_prompt(
                    ratio_prompt
                )

                user_prompt_for_merge = desc_part
                user_character = ""
                user_series = ""

                if desc_part and has_chinese(desc_part):
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
                    if desc_part:
                        user_character, user_series = (
                            await self._resolve_prompt_identity(desc_part)
                        )

                merged_overlay = merge_retag_prompt(
                    user_prompt_for_merge,
                    retag_prompt,
                    original_user_prompt=prompt,
                    user_character=user_character,
                    user_series=user_series,
                    source_character=str(retag_result.get("character") or ""),
                    source_series=str(retag_result.get("series") or ""),
                    weight_user=True,
                )
                controls = []
                if prompt_has_explicit_ratio(
                    prompt,
                    self._short_ratio_aliases(),
                    self.ratio_presets,
                    self._normalize_ratio_label,
                ) and ratio_name:
                    controls.append(ratio_name)
                if artist_name and not raw_mode:
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
        ):
            yield result

    @filter.command("nai")
    async def cmd_nai(self, event: AstrMessageEvent) -> AsyncGenerator:
        """NAI 生图。用法：/nai 提示词；/nai + 图片 反推图片提示词后生图；/nai @某人 使用头像反推生图。"""
        async for result in self._handle_nai_command(event, raw_mode=False):
            yield result

    @filter.command("nai0")
    async def cmd_nai0(self, event: AstrMessageEvent) -> AsyncGenerator:
        """NAI 原始提示词生图。不会追加画师串和质量提示词，但仍沿用负面提示词。"""
        async for result in self._handle_nai_command(event, raw_mode=True):
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

from __future__ import annotations

import os
import re
from dataclasses import replace
from typing import AsyncGenerator, Dict, List, Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.message_components import Image
from astrbot.api.star import Context, Star

from .core.generator import (
    APIKeyError,
    GenerationError,
    ImageGenerator,
    QuotaExceededError,
    RateLimitError,
    ServerBusyError,
)
from .core.image_retagger import ImageRetagError, ImageRetagger
from .core.safety import SafetyModerator
from .core.translator import PromptTranslator, has_chinese
from .image_store import send_image_best_effort
from .models.config import GenerationConfig, PluginConfig
from .services.artist_gallery import ArtistGalleryService
from .services.image_extract import extract_image_from_event_best_effort
from .services.image_ratio import (
    infer_ratio_label_from_size,
    prompt_has_explicit_ratio,
    read_image_size_any,
)
from .services.mention_avatar import (
    extract_mentioned_qq_from_event,
    qq_avatar_url,
    remove_mention_from_prompt,
)
from .services.prompt_builder import (
    cleanup_file,
    find_non_ascii_chars,
    normalize_prompt_ascii,
    PromptBuilder,
    save_image_to_temp,
)
from .services.runtime_state import RuntimeStateService


FIXED_MODEL = "nai-diffusion-4-5-full"
SAFETY_BLOCK_REPLY = "⚠️ 未能通过安全检测，已拦截"
PLUGIN_NAME = "astrbot_plugin_bestnai_x"


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

        self.runtime_artist_prompt_override = ""
        self.runtime_artist_slot_name = ""
        self._load_persisted_artist_preset()

        self._resolve_image_provider()

        self.generator = ImageGenerator(self.plugin_config)
        self.safety = SafetyModerator(self.plugin_config.safety, context=self.context)
        self.image_retagger = ImageRetagger(
            self.plugin_config.image_retag,
            context=self.context,
        )

        self.ratio_presets = self._load_ratio_presets()
        self.default_ratio = self._load_default_ratio()

        self.prompt_builder = PromptBuilder(
            self.plugin_config,
            self._resolve_ratio_to_size,
        )

        self.artist_gallery = ArtistGalleryService(PLUGIN_NAME)

        api_source = (
            "手动生图 API"
            if getattr(self.plugin_config, "use_manual_api", False)
            else (self.plugin_config.image_provider_id or "(未选择)")
        )

        artist_source = (
            self.runtime_artist_slot_name
            or self.plugin_config.artist_preset
            or self._get_default_artist_display_name()
        )

        logger.info(
            "[BestNAI] 已加载，"
            f"生图接口={api_source}，"
            f"API URL={self.plugin_config.api_url or '(未配置)'}，"
            f"安全审核={'开启' if self.plugin_config.safety.enabled else '关闭'}，"
            f"审核提供商={self.plugin_config.safety.provider_id or '(未选择)'}，"
            f"图片反推={'开启' if self.plugin_config.image_retag.enabled else '关闭'}，"
            f"反推提供商={self.plugin_config.image_retag.provider_id or '(未选择)'}，"
            f"画师预设={artist_source}，"
            f"模型={FIXED_MODEL}，"
            f"默认比例={self.default_ratio}，"
            f"插件数据目录={self.artist_gallery.plugin_data_dir}"
        )

    async def terminate(self) -> None:
        logger.info("[BestNAI] 已卸载")

    def _load_persisted_artist_preset(self) -> None:
        slot_name = self.runtime_state.get_default_artist_slot()

        if not slot_name:
            return

        real_slot_name, artist_prompt = self._find_artist_slot(slot_name)

        if not real_slot_name or not artist_prompt:
            logger.warning(
                f"[BestNAI] 已保存的默认画师预设不存在，已清除：{slot_name}"
            )
            self.runtime_state.clear_default_artist_slot()
            return

        self.runtime_artist_slot_name = real_slot_name
        self.runtime_artist_prompt_override = artist_prompt

        logger.info(f"[BestNAI] 已恢复默认画师预设：{real_slot_name}")

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

        if not prefer_provider:
            if manual_api_url and manual_api_key:
                self.plugin_config.api_url = manual_api_url
                self.plugin_config.api_key = manual_api_key
                self.plugin_config.use_manual_api = True

                logger.info(
                    f"[BestNAI] 已使用手动生图 API，模式=/chat/completions，api_base={self.plugin_config.api_url}"
                )
                return

            logger.warning("[BestNAI] 已关闭优先使用提供商，但未填写完整手动生图 API 地址/API Key")
            return

        if not provider_id:
            logger.warning("[BestNAI] 已开启优先使用提供商，但未选择生图接口提供商")
            return

        try:
            provider = self.context.get_provider_by_id(provider_id)
        except Exception as e:
            logger.warning(f"[BestNAI] 获取生图接口提供商失败 provider_id={provider_id}: {e}")
            return

        if not provider:
            logger.warning(f"[BestNAI] 找不到生图接口提供商 ID: {provider_id}")
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
            return

        if not api_key:
            logger.warning(f"[BestNAI] 生图接口提供商 {provider_id} 缺少 API Key")
            return

        self.plugin_config.api_url = str(base_url).rstrip("/")
        self.plugin_config.api_key = str(api_key)
        self.plugin_config.use_manual_api = False

        logger.info(
            f"[BestNAI] 已使用生图接口提供商：{provider_id}，api_base={self.plugin_config.api_url}"
        )

    def _ensure_image_provider_ready(self) -> None:
        """
        Bot 重启时 AstrBot provider 可能晚于插件初始化完成。
        如果启动阶段没拿到 provider，这里在首次生图前再解析一次，
        避免必须手动重载插件。
        """
        if self.plugin_config.is_configured():
            return

        if getattr(self.plugin_config, "use_manual_api", False):
            return

        logger.info("[BestNAI] 生图接口尚未就绪，尝试重新解析生图提供商")
        self._resolve_image_provider()

    def _load_ratio_presets(self) -> Dict[str, Tuple[int, int]]:
        base_presets: Dict[str, Tuple[int, int]] = {
            "16:9": (1216, 704),
            "9:16": (704, 1216),
            "4:3": (1024, 768),
            "3:4": (768, 1024),
            "3:2": (1216, 832),
            "2:3": (832, 1216),
            "1:1": (1024, 1024),
        }

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

        candidates = {
            "16:9": (1216, 704),
            "9:16": (704, 1216),
            "4:3": (1024, 768),
            "3:4": (768, 1024),
            "3:2": (1216, 832),
            "2:3": (832, 1216),
            "1:1": (1024, 1024),
        }

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

    def _try_switch_artist_preset_command(self, prompt: str) -> Tuple[bool, str]:
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
            self.runtime_artist_prompt_override = ""
            self.runtime_artist_slot_name = ""

            saved = self.runtime_state.clear_default_artist_slot()

            if saved:
                return True, "已恢复配置默认画师预设，并清除已保存的默认预设"

            return True, "已恢复配置默认画师预设，但保存状态失败"

        slot_name, artist_prompt = self._find_artist_slot(text)

        if not slot_name or not artist_prompt:
            return False, ""

        self.runtime_artist_prompt_override = artist_prompt
        self.runtime_artist_slot_name = slot_name

        saved = self.runtime_state.set_default_artist_slot(slot_name)

        if saved:
            return True, f"已切换默认画师预设：{slot_name}（已保存）"

        return True, f"已切换默认画师预设：{slot_name}（保存失败，重启后可能失效）"

    def _display_ratio_label(self, ratio_name_or_size: str, width: int, height: int) -> str:
        value = (ratio_name_or_size or "").strip()
        normalized = self._normalize_ratio_label(value)

        valid_ratios = {
            "16:9",
            "9:16",
            "4:3",
            "3:4",
            "3:2",
            "2:3",
            "1:1",
        }

        if normalized in valid_ratios:
            return normalized

        size_to_ratio = {
            (1216, 704): "16:9",
            (704, 1216): "9:16",
            (1024, 768): "4:3",
            (768, 1024): "3:4",
            (1216, 832): "3:2",
            (832, 1216): "2:3",
            (1024, 1024): "1:1",
        }

        size_key = (int(width), int(height))

        if size_key in size_to_ratio:
            return size_to_ratio[size_key]

        return f"{int(width)}x{int(height)}"

    def _get_default_artist_display_name(self) -> str:
        try:
            if self.runtime_artist_slot_name:
                return self.runtime_artist_slot_name

            presets = self.plugin_config.get_artist_presets_map()

            if presets:
                return next(iter(presets.keys()))

        except Exception:
            pass

        return "未设置"

    def _get_artist_display_name(self, artist_slot_name: str = "") -> str:
        if artist_slot_name:
            return artist_slot_name

        if self.runtime_artist_slot_name:
            return self.runtime_artist_slot_name

        return self._get_default_artist_display_name()

    def _get_effective_artist_prompt(self, artist_prompt_override: str = "") -> str:
        if artist_prompt_override and artist_prompt_override.strip():
            return artist_prompt_override.strip()

        if self.runtime_artist_prompt_override:
            return self.runtime_artist_prompt_override.strip()

        return self.plugin_config.get_effective_artist_prompt()

    def _looks_like_size(self, value: str) -> bool:
        return bool(re.fullmatch(r"\d{2,5}\s*[x×]\s*\d{2,5}", value.strip()))

    def _cleanup_prompt_text(self, text: str) -> str:
        text = text or ""
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s*[,，;；]\s*[,，;；]\s*", ", ", text)
        return text.strip(" ,，;；").strip()

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
    ) -> AsyncGenerator:
        if raw_mode:
            prompt = self._strip_named_command_prefix(prompt, "nai0")
        else:
            prompt = self._strip_command_prefix(prompt)

        if not prompt:
            yield event.plain_result("❌ 请提供提示词")
            return

        if not raw_mode:
            switched, switch_msg = self._try_switch_artist_preset_command(prompt)

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

        clean_prompt, ratio_name = self._extract_ratio_from_prompt(prompt)

        artist_prompt_override = ""
        artist_slot_name = ""

        if not raw_mode:
            clean_prompt, artist_prompt_override, artist_slot_name = (
                self._extract_artist_slot_from_prompt(clean_prompt)
            )

        logger.info(
            f"[BestNAI] 解析后 prompt='{clean_prompt}', ratio='{ratio_name}', "
            f"artist_slot='{artist_slot_name}', runtime_artist='{self.runtime_artist_slot_name}', "
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
                "可用比例：16:9、9:16、4:3、3:4、3:2、2:3、1:1，也可输入横屏、竖屏、方图\n"
                "也可以直接使用 1024x1024"
            )
            logger.warning(f"[BestNAI] 解析比例失败 ratio={ratio_name}: {e}")
            return

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

            translator = PromptTranslator(
                self.plugin_config.translator,
                context=self.context,
            )

            translated = await translator.translate(
                clean_prompt,
                danbooru_api_url=(
                    self.plugin_config.danbooru_api_url
                    if self.plugin_config.danbooru_tag_search
                    else ""
                ),
            )

            if not translated or has_chinese(translated):
                yield event.plain_result("❌ 翻译失败，请检查翻译提供商配置。")
                return

            translated_check = self.safety.check_prompt(translated)

            if translated_check.filtered_prompt != translated:
                logger.info(
                    f"[BestNAI/Safety] 已自动过滤翻译后 prompt：{translated_check.reason}"
                )
                translated = translated_check.filtered_prompt

            if not translated:
                yield event.plain_result("❌ 提示词过滤后为空，请补充安全的有效提示词")
                return

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
            artist_prompt = self._get_effective_artist_prompt(artist_prompt_override)

            final_prompt = self.prompt_builder.build_final_prompt(
                final_prompt,
                artist_prompt=artist_prompt,
                suffix=self.plugin_config.prompt_suffix or "",
            )

        if not final_prompt:
            yield event.plain_result("❌ 提示词清理后为空，请输入英文提示词或开启中文翻译")
            return

        ratio_display = self._display_ratio_label(
            ratio_name,
            gen_config.width,
            gen_config.height,
        )

        if raw_mode:
            yield event.plain_result(
                f"🎨 正在生图（{ratio_display} | nai0 原始提示词模式）..."
            )
        else:
            artist_display = self._get_artist_display_name(artist_slot_name)

            yield event.plain_result(
                f"🎨 正在生图（{ratio_display} | 画师预设：{artist_display}）..."
            )

        try:
            images = await self.generator.generate(final_prompt, gen_config)

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
            if not self.plugin_config.image_retag.enabled:
                yield event.plain_result(
                    "❌ 检测到图片或 @ 头像，但图片反推功能未开启。请在配置中启用“图片反推提示词”。"
                )
                return

            if not self.plugin_config.image_retag.is_configured():
                yield event.plain_result(
                    "❌ 图片反推功能未配置。请在 image_retag_config 中选择图片反推接口提供商。"
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

            if mentioned_qq:
                yield event.plain_result("🔍 正在反推该用户头像提示词...")
            else:
                yield event.plain_result("🔍 正在反推图片提示词...")

            try:
                retag_prompt = await self.image_retagger.retag(
                    image_src,
                    user_hint=prompt,
                )

            except ImageRetagError as e:
                yield event.plain_result(f"❌ 图片反推失败：{e}")
                return

            if not retag_prompt:
                yield event.plain_result("❌ 图片反推结果为空")
                return

            if self.plugin_config.image_retag.show_result:
                title = "头像反推结果" if mentioned_qq else "反推结果"
                yield event.plain_result(f"🔎 {title}：\n{retag_prompt}")

            if prompt:
                merged_prompt = f"{prompt}, {retag_prompt}"
            else:
                merged_prompt = retag_prompt

            if inferred_ratio:
                merged_prompt = f"{merged_prompt} {inferred_ratio}"

            async for result in self._do_generate(
                event=event,
                prompt=merged_prompt,
                raw_mode=raw_mode,
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

        ok, result = self.artist_gallery.build_or_get_gallery(presets)

        if not ok:
            yield event.plain_result(f"❌ 生成画师画廊失败：{result}")
            return

        async for r in send_image_best_effort(event, result):
            yield r

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

        ok = self.artist_gallery.record_preview(real_key, img)

        if not ok:
            yield event.plain_result("❌ 画师预览图保存失败，请重试")
            return

        yield event.plain_result(f"✅ 已设置画师预设「{real_key}」的预览图")

"""Optional per-node parameters used when recreating an image from its metadata."""
from dataclasses import replace
from typing import Any

try:
    from ..core.novelai_api import UC_PRESET_CODES
except ImportError:  # Standalone service tests.
    from core.novelai_api import UC_PRESET_CODES


def apply_canvas_generation_overrides(config: Any, payload: dict) -> Any:
    updates = {}
    if "negative_prompt" in payload:
        negative = payload["negative_prompt"]
        if not isinstance(negative, str) or len(negative) > 6000:
            raise ValueError("负面提示词必须是 6000 字以内的文本")
        updates["negative_prompt"] = negative.strip()
    if isinstance(payload.get("quality"), bool):
        updates["quality"] = payload["quality"]
    if payload.get("uc_preset") not in (None, ""):
        preset = str(payload["uc_preset"]).strip().lower()
        codes = {str(code): name for name, code in UC_PRESET_CODES.items()}
        preset = codes.get(preset, preset)
        if preset not in UC_PRESET_CODES:
            raise ValueError("无法识别负面提示词预设")
        updates["uc_preset"] = preset
    if payload.get("image_format") not in (None, ""):
        image_format = str(payload["image_format"]).strip().lower()
        if image_format == "jpeg":
            image_format = "jpg"
        if image_format not in {"png", "jpg", "webp"}:
            raise ValueError("生成图片格式仅支持 PNG、JPEG 和 WebP")
        updates["image_format"] = image_format
    return replace(config, **updates) if updates else config

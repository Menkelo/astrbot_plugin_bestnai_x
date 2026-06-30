"""数据模型模块 - BestNAI 插件。"""

from dataclasses import dataclass, field
from typing import Optional

from constants import (
    DEFAULT_IMAGE_FORMAT,
    DEFAULT_MODEL,
    DEFAULT_N_SAMPLES,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_NOISE_SCHEDULE,
    DEFAULT_QUALITY_TAGS,
    DEFAULT_SAMPLER,
    DEFAULT_SCALE,
    DEFAULT_STEPS,
    DEFAULT_UC_PRESET,
)


@dataclass
class GenerationParams:
    """图片生成请求参数。

    Attributes:
        prompt: 正向提示词。
        width: 图片宽度（像素）。
        height: 图片高度（像素）。
        steps: 生成步数。
        scale: CFG Scale（引导系数）。
        negative_prompt: 负向提示词。
        sampler: 采样器名称。
        noise_schedule: 噪声调度策略。
        quality_tags: 质量标签（自动附加）。
        uc_preset: 负面提示词预设编号。
        n_samples: 每次生成数量。
        seed: 随机种子（-1 表示随机）。
        image_format: 输出格式（png / jpeg）。
        model: 使用的模型名称。
    """

    prompt: str
    width: int = 832
    height: int = 1216
    steps: int = DEFAULT_STEPS
    scale: float = DEFAULT_SCALE
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    sampler: str = DEFAULT_SAMPLER
    noise_schedule: str = DEFAULT_NOISE_SCHEDULE
    quality_tags: str = DEFAULT_QUALITY_TAGS
    uc_preset: int = DEFAULT_UC_PRESET
    n_samples: int = DEFAULT_N_SAMPLES
    seed: int = -1
    image_format: str = DEFAULT_IMAGE_FORMAT
    model: str = DEFAULT_MODEL

    @property
    def size_str(self) -> str:
        """返回格式化的分辨率字符串。

        Returns:
            如 '832x1216' 的字符串。
        """
        return f"{self.width}x{self.height}"

    @property
    def total_pixels(self) -> int:
        """返回总像素数。

        Returns:
            宽度乘以高度的结果。
        """
        return self.width * self.height

    def to_api_payload(self, api_url: str, api_key: str) -> dict:
        """构建 API 请求体。

        Args:
            api_url: API 地址（仅用于记录，不在此使用）。
            api_key: API 密钥（仅用于记录，不在此使用）。

        Returns:
            可直接传给 aiohttp 的请求体字典。
        """
        import json
        import random

        actual_seed = self.seed if self.seed >= 0 else random.randint(0, 2**32 - 1)

        content_dict = {
            "prompt": self.prompt,
            "size": self.size_str,
            "steps": self.steps,
            "scale": self.scale,
            "sampler": self.sampler,
            "negative_prompt": self.negative_prompt,
            "quality": self.quality_tags,
            "uc_preset": self.uc_preset,
            "noise_schedule": self.noise_schedule,
            "n_samples": self.n_samples,
            "seed": actual_seed,
            "image_format": self.image_format,
        }

        return {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(content_dict, ensure_ascii=False),
                }
            ],
        }


@dataclass
class PluginConfig:
    """插件配置数据类。

    Attributes:
        api_url: BestNAI API 地址。
        api_key: BestNAI API 密钥。
        model: 使用的模型名称。
        default_size: 默认分辨率字符串，格式为 'WxH'。
        default_steps: 默认生成步数。
        default_scale: 默认 CFG Scale。
        user_cooldown: 用户冷却时间（秒）。
        timeout: HTTP 请求超时时间（秒）。
    """

    api_url: str = ""
    api_key: str = ""
    model: str = DEFAULT_MODEL
    default_size: str = "832x1216"
    default_steps: int = DEFAULT_STEPS
    default_scale: float = DEFAULT_SCALE
    user_cooldown: int = 30
    timeout: int = 90

    @classmethod
    def from_dict(cls, data: dict) -> "PluginConfig":
        """从字典中构建配置对象。

        Args:
            data: 插件配置字典（来自 AstrBot 框架）。

        Returns:
            PluginConfig 实例。
        """
        return cls(
            api_url=data.get("api_url", ""),
            api_key=data.get("api_key", ""),
            model=data.get("model", DEFAULT_MODEL),
            default_size=data.get("default_size", "832x1216"),
            default_steps=int(data.get("default_steps", DEFAULT_STEPS)),
            default_scale=float(data.get("default_scale", DEFAULT_SCALE)),
            user_cooldown=int(data.get("user_cooldown", 30)),
            timeout=int(data.get("timeout", 90)),
        )

    @property
    def masked_api_url(self) -> str:
        """返回遮蔽密钥的 API 地址（安全显示）。

        Returns:
            不含敏感信息的 API 地址。
        """
        return self.api_url if self.api_url else "(未配置)"

    @property
    def masked_api_key(self) -> str:
        """返回部分遮蔽的 API 密钥。

        Returns:
            只显示前4位和后4位，中间用 **** 遮蔽。
        """
        if not self.api_key:
            return "(未配置)"
        if len(self.api_key) <= 8:
            return "****"
        return f"{self.api_key[:4]}****{self.api_key[-4:]}"

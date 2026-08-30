"""常量定义模块 - BestNAI 插件特异版。

特异版说明：
- 生图模型跟随接口提供商配置，默认 nai-diffusion-4-5-full
- 生图接口使用 /v1/images/generations

生图参数（模型、步数、CFG、尺寸预设、负面提示词等）统一定义在
models/config.py，不在这里重复，避免两处数值对不上。
"""

# 插件基本信息
PLUGIN_NAME = "astrbot_plugin_bestnai_x"
PLUGIN_DISPLAY_NAME = "NAI Diffusion X"
PLUGIN_VERSION = "4.2.0"
PLUGIN_AUTHOR = "Menkelo"
PLUGIN_REPO = "https://github.com/Menkelo/astrbot_plugin_bestnai_x"

# NovelAI seeds are unsigned 32-bit values.  Keeping this in one shared
# module prevents the generator, canvas persistence, and library from silently
# disagreeing about valid seeds above 2^31-1.
MAX_SEED = 4_294_967_295


def normalize_nai_seed(value: object) -> int | None:
    """Return a valid NovelAI seed, or ``None`` for malformed input.

    JSON clients occasionally send seeds as strings.  Accept integer strings
    and integral numeric values, but reject booleans and fractional numbers so
    a malformed value cannot be silently truncated into a different seed.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            return None
    try:
        seed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return seed if 1 <= seed <= MAX_SEED else None

"""常量定义模块 - BestNAI 插件特异版。

特异版说明：
- 仅支持 nai-diffusion-4-5-full
- 生图接口使用 /v1/images/generations

生图参数（模型、步数、CFG、尺寸预设、负面提示词等）统一定义在
models/config.py，不在这里重复，避免两处数值对不上。
"""

# 插件基本信息
PLUGIN_NAME = "astrbot_plugin_bestnai_x"
PLUGIN_DISPLAY_NAME = "NAI Diffusion X"
PLUGIN_VERSION = "3.3.3"
PLUGIN_AUTHOR = "Menkelo"
PLUGIN_REPO = "https://github.com/Menkelo/astrbot_plugin_bestnai_x"

# NovelAI seeds are unsigned 32-bit values.  Keeping this in one shared
# module prevents the generator, canvas persistence, and library from silently
# disagreeing about valid seeds above 2^31-1.
MAX_SEED = 4_294_967_295

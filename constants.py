"""常量定义模块 - BestNAI 插件特异版。

特异版说明：
- 仅支持 nai-diffusion-4-5-full
- 生图接口使用 /v1/images/generations
"""

# 插件基本信息
PLUGIN_NAME = "astrbot_plugin_bestnai"
PLUGIN_VERSION = "2.2.1-special-45"

# API 相关
DEFAULT_MODEL = "nai-diffusion-4-5-full"
DEFAULT_SIZE = "832x1216"
DEFAULT_STEPS = 23
DEFAULT_SCALE = 5.0
DEFAULT_SAMPLER = "k_euler_ancestral"
DEFAULT_NOISE_SCHEDULE = "karras"
DEFAULT_QUALITY_TAGS = (
    "best quality, amazing quality, very aesthetic, absurdres"
)
DEFAULT_NEGATIVE_PROMPT = (
    "lowres, {bad}, error, fewer, extra, missing, worst quality, "
    "jpeg artifacts, bad quality, watermark, unfinished, displeasing, "
    "chromatic aberration, signature, extra digits, artistic error, "
    "username, scan, [abstract]"
)
DEFAULT_UC_PRESET = 3
DEFAULT_IMAGE_FORMAT = "png"
DEFAULT_N_SAMPLES = 1

# 免费限制
FREE_MAX_PIXELS = 1_048_576
FREE_MAX_STEPS = 28

# 用户体验
DEFAULT_USER_COOLDOWN = 30
DEFAULT_TIMEOUT = 90

# 消息模板
MSG_GENERATING = "🎨 生成中，请稍候..."
MSG_COOLDOWN = "⏳ 冷却中，还需等待 {seconds} 秒"
MSG_API_KEY_MISSING = "❌ 未配置 API 密钥，请联系管理员"
MSG_API_URL_MISSING = "❌ 未配置 API 地址，请联系管理员"
MSG_UNKNOWN_ERROR = "❌ 生成失败：{error}"
MSG_TIMEOUT_ERROR = "❌ 请求超时，请稍后重试"
MSG_HTTP_ERROR = "❌ API 请求失败 (HTTP {status})：{message}"
MSG_PARSE_ERROR = "❌ 解析响应失败：{error}"
MSG_SIZE_INVALID = "❌ 分辨率格式无效，请使用如 832x1216 的格式"
MSG_STEPS_INVALID = "❌ steps 必须是正整数"
MSG_STEPS_FREE_LIMIT = "⚠️ 免费模式下 steps 不能超过 {max_steps}，已自动调整为 {max_steps}"
MSG_PIXELS_FREE_LIMIT = (
    "⚠️ 免费模式下图片面积不能超过 {max_pixels} 像素，请缩小分辨率"
)

# ──── 尺寸预设 ────────────────────────────────────────────────────────────────
# 预设名 -> (宽, 高)
SIZE_PRESETS: dict = {
    "竖图": (832, 1216),
    "横图": (1216, 832),
    "方图": (1024, 1024),
    "小竖图": (512, 768),
    "小横图": (768, 512),
    "小方图": (640, 640),
    "大竖图": (1024, 1536),
    "大横图": (1536, 1024),
}

# ──── 模型版本映射 ────────────────────────────────────────────────────────────
# 特异版：只允许 4.5，且固定为 Full 模型
VERSION_MODELS: dict = {
    "4.5": "nai-diffusion-4-5-full",
}

# 特异版不切 Curated。
# 为了兼容 main.py 中的 VERSION_MODELS_CURATED.get(...)，所有键都映射到 full。
VERSION_MODELS_CURATED: dict = {
    "3": "nai-diffusion-4-5-full",
    "4": "nai-diffusion-4-5-full",
    "4.5": "nai-diffusion-4-5-full",
}

# NSFW 自动追加的负面提示词
NSFW_NEGATIVE_TAGS = "nsfw, explicit, nude, naked"

# /nai 子命令关键词列表（按优先级排列，用于路由判断）
NAI_SUBCOMMANDS = {
    "set", "size", "nsfw", "pt", "on", "off", "撤回", "help", "status", "cfg"
}

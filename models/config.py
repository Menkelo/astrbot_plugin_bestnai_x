from dataclasses import dataclass, field
from typing import Dict, List, Optional


MODEL_V45_FULL = "nai-diffusion-4-5-full"
# NovelAI 官方 2026-08 发布的 V5 Full，生成参数与 V4.5 Full 一致
# （832x1216 起步、Euler Ancestral、Karras）。生图模型跟随接口提供商
# 配置的模型名，未配置时回退 MODEL_V45_FULL。
MODEL_V5_FULL = "nai-diffusion-5-full"
SUPPORTED_MODELS = (MODEL_V45_FULL, MODEL_V5_FULL)

# NovelAI samplers accepted by current V4+/V5 endpoints.  Keep this list in
# one place so the config schema, canvas selector and API payload stay aligned.
SUPPORTED_SAMPLERS = (
    "k_euler_ancestral",
    "k_euler",
    "k_dpmpp_2s_ancestral",
    "k_dpmpp_2m_sde",
    "k_dpmpp_2m_sde_exponential",
    "k_dpmpp_2m_sde_karras",
    "k_dpmpp_sde",
    "k_dpmpp_sde_karras",
    "ddim",
    "ddim_v2",
    "k_lms",
    "k_heun",
    "k_dpm_2",
    "k_dpm_2_ancestral",
)

FIXED_MODEL = MODEL_V45_FULL
DEFAULT_QUALITY_STRING = "best quality, amazing quality, very aesthetic, absurdres"


def model_supports_cjk(model: str) -> bool:
    """V5 官方原生支持中/日文提示词；V4.x 及以下只吃 ASCII 标签。

    决定两件事：中文提示是否必须先翻译，以及提交前要不要做
    非 ASCII 清理。
    """
    return "diffusion-5" in str(model or "").lower()


def resolve_model_choice(raw) -> str:
    """把下拉/节点里的模型选择解析成受支持的模型 ID，非法值回退默认。"""
    value = str(raw or "").strip()
    return value if value in SUPPORTED_MODELS else FIXED_MODEL


# Variety+ 在中转网关（Tuercha 系）的方言里就叫 variety_boost，网关自己把它
# 翻成 NovelAI 的 skip_cfg_above_sigma=58。已探测确认：发 variety_boost=true，
# 返回图的元数据里 skip_cfg_above_sigma=58.0；而直接发 skip_cfg_above_sigma
# 会被网关当未知字段静默丢弃（未知字段一律 200 但无效果）。
def model_supports_variety_boost(model: str) -> bool:
    """V5 的官方能力表里 skip_cfg_above_sigma 不可用，请求清洗会直接删掉它。

    V4.x 才认这个参数。带着它请求 V5 除了让载荷变脏没有别的作用。
    """
    return "diffusion-5" not in str(model or "").lower()

DEFAULT_QUALITY_STRING = "best quality, amazing quality, very aesthetic, absurdres"
DEFAULT_NEGATIVE_PROMPT = "lowres, bad anatomy, bad hands, text, error, missing fingers"
DEFAULT_DANBOORU_API_URL = "https://sakizuki-danboorusearch.hf.space"
# NovelAI 官方生图主机。自建或第三方站点在配置面板里改成自己的地址。
DEFAULT_OFFICIAL_API_URL = "https://image.novelai.net"

DEFAULT_ARTIST_PRESET_LIST = [
    "可爱:artist:ciloranko , [artist:sho_(sho_lwlw)], [[artist:tianliang_duohe_fangdongye]],[[[[[[artist:kani_biimu]]]]]]",
    "幼态:artist: ciloranko, [artist: tianliang duohe fangdongye], [artist: sho_(sho_lwlw)], [artist: baku-p], [artist:tsubasa_tsubasa], [[artist:as109]], [[artist:rhasta]]",
    "水彩:{hokori sakuni}, {ciloranko}, {ke-ta}, {houkisei},{kedama milk}",
    "海报:artist:ciloranko, {artist:menthako}, {artist:tianliang duohe fangdongye}, [artist:sho (sho lwlw)], [artist:baku-p], [[[artist:tsubasa tsubasa]]], artist: kemo camotli",
    "鲜艳色彩:[artist:ningen_mame], {{{ciloranko}}}, [artist:sho_(sho_lwlw)], [[artist:rhasta]], [artist:wlop], [artist:ke-ta]",
]


@dataclass
class GenerationConfig:
    model: str = FIXED_MODEL
    width: int = 832
    height: int = 1216
    steps: int = 28
    scale: float = 7.0
    sampler: str = "k_euler_ancestral"
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT
    quality: bool = True
    uc_preset: str = "light"
    noise_schedule: str = "karras"
    image_format: str = "png"
    cfg_rescale: float = 0.0
    variety_boost: bool = False
    characters: list = field(default_factory=list)
    use_coords: bool = False
    use_order: bool = True
    # 结构化角色参数：已实测确认中转网关放行 characters 与 use_coords，
    # position "B3" 会被翻成 NAI 的 centers {x:0.3, y:0.5}。use_coords 仍默认
    # 关闭——它只在用户明确指定站位时才该打开，否则按出场顺序排布。

    @classmethod
    def from_plugin_config(cls, config: dict) -> "GenerationConfig":
        gen_conf = config.get("generation_config", {}) or {}
        prompt_conf = config.get("prompt_config", {}) or {}

        return cls(
            model=FIXED_MODEL,
            width=832,
            height=1216,
            steps=28,
            scale=7.0,
            sampler=gen_conf.get("sampler", "k_euler_ancestral"),
            negative_prompt=prompt_conf.get(
                "negative_prompt",
                DEFAULT_NEGATIVE_PROMPT,
            ),
            quality=True,
        )

    @classmethod
    def for_version(
        cls,
        version: str,
        config: dict,
        base: "GenerationConfig",
    ) -> "GenerationConfig":
        from dataclasses import replace

        gen_conf = config.get("generation_config", {}) or {}
        prompt_conf = config.get("prompt_config", {}) or {}

        # 模型跟随 base（即配置面板的选择），不在这里强制回 4.5。
        return replace(
            base,
            steps=28,
            scale=7.0,
            sampler=gen_conf.get("sampler", base.sampler),
            negative_prompt=prompt_conf.get(
                "negative_prompt",
                base.negative_prompt,
            ),
        )


@dataclass
class TranslatorConfig:
    enabled: bool = False
    provider_id: str = ""
    show_progress: bool = False
    show_result: bool = False
    system_prompt: str = ""
    custom_prefix: str = ""
    max_retries: int = 3

    def is_configured(self) -> bool:
        return bool(self.provider_id)


@dataclass
class SafetyConfig:
    enabled: bool = False
    provider_id: str = ""
    prompt_block_enabled: bool = True
    prompt_block_words: Optional[List[str]] = None


@dataclass
class ImageRetagConfig:
    enabled: bool = False
    provider_id: str = ""
    show_result: bool = False

    def is_configured(self) -> bool:
        return bool(self.provider_id)


@dataclass
class PluginConfig:
    image_provider_id: str = ""
    api_url: str = ""
    api_key: str = ""
    # V5 专用提供商槽位：留空时 /nai5 与 V5 画布节点回落主提供商
    image_provider_id_v5: str = ""
    api_url_v5: str = ""
    api_key_v5: str = ""
    # NovelAI 官方协议直连。开启后上面两个提供商槽位一律不生效，
    # 4.5 与 V5 共用同一个端点与 Token。
    use_official_api: bool = False
    official_api_url: str = DEFAULT_OFFICIAL_API_URL
    official_api_token: str = ""
    # /nai0 的模型选择（面板·生图接口配置）；画布模型由节点各自选择
    nai0_model: str = FIXED_MODEL
    max_concurrency: int = 1

    user_cooldown: int = 0
    save_images: bool = False
    save_dir: str = ""
    auto_recall: bool = False
    auto_recall_delay: int = 30

    generation: GenerationConfig = field(default_factory=GenerationConfig)
    translator: TranslatorConfig = field(default_factory=TranslatorConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    image_retag: ImageRetagConfig = field(default_factory=ImageRetagConfig)

    artist_presets: List[str] = field(default_factory=lambda: DEFAULT_ARTIST_PRESET_LIST.copy())

    artist_preset: str = "可爱"
    artist_source: str = ""
    custom_artist_preset: str = ""
    saved_custom_artist_presets: List[str] = field(default_factory=list)
    default_artist_preset: str = ""

    prompt_suffix: str = DEFAULT_QUALITY_STRING

    danbooru_api_url: str = ""
    retag_show_source: bool = False

    raw_config: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, config: dict) -> "PluginConfig":
        api_conf = config.get("api_config", {}) or {}
        gen_conf = config.get("generation_config", {}) or {}
        tr_conf = config.get("translator_config", {}) or {}
        prompt_conf = config.get("prompt_config", {}) or {}
        safety_conf = config.get("safety_config", {}) or {}
        image_retag_conf = config.get("image_retag_config", {}) or {}

        # max_concurrency 在 _conf_schema.json 里属于 generation_config，
        # 另外两个位置只是为了兼容手写配置。
        raw_max_concurrency = gen_conf.get(
            "max_concurrency",
            api_conf.get("max_concurrency", config.get("max_concurrency", 1)),
        )

        try:
            max_concurrency = int(raw_max_concurrency or 1)
        except (TypeError, ValueError):
            max_concurrency = 1

        if max_concurrency < 1:
            max_concurrency = 1

        image_provider_id = (
            _extract_provider_id(api_conf.get("provider_id"))
            or _extract_provider_id(config.get("image_provider_id"))
            or _extract_provider_id(config.get("provider_id"))
        )

        image_provider_id_v5 = _extract_provider_id(api_conf.get("provider_id_v5"))

        translator_provider_id = (
            _extract_provider_id(tr_conf.get("provider_id"))
            or _extract_provider_id(config.get("translator_provider_id"))
        )

        safety_provider_id = (
            _extract_provider_id(safety_conf.get("provider_id"))
            or _extract_provider_id(config.get("safety_provider_id"))
        )

        image_retag_provider_id = (
            _extract_provider_id(image_retag_conf.get("provider_id"))
            or _extract_provider_id(config.get("image_retag_provider_id"))
        )

        raw_artist_presets = _normalize_string_list(
            prompt_conf.get("artist_presets", [])
        )
        raw_prompt_block_words = safety_conf.get("prompt_block_words")
        prompt_block_words = (
            None
            if raw_prompt_block_words is None
            else _normalize_string_list(raw_prompt_block_words)
        )

        if not raw_artist_presets:
            raw_artist_presets = DEFAULT_ARTIST_PRESET_LIST.copy()

        first_artist_name = _first_artist_preset_name(raw_artist_presets) or "可爱"

        return cls(
            image_provider_id=image_provider_id,
            # 生图 API 地址与 Key 只从已选择的 AstrBot 提供商解析，
            # 不再读取旧版插件配置中的手填字段。
            api_url="",
            api_key="",
            image_provider_id_v5=image_provider_id_v5,
            api_url_v5="",
            api_key_v5="",
            use_official_api=bool(api_conf.get("use_official_api", False)),
            official_api_url=str(
                api_conf.get("official_api_url", DEFAULT_OFFICIAL_API_URL) or ""
            ).strip(),
            official_api_token=str(api_conf.get("official_api_token", "") or "").strip(),
            nai0_model=resolve_model_choice(api_conf.get("nai0_model")),
            max_concurrency=max_concurrency,
            generation=GenerationConfig.from_plugin_config(config),
            translator=TranslatorConfig(
                enabled=bool(
                    tr_conf.get(
                        "enabled",
                        config.get("translator_enabled", False),
                    )
                ),
                provider_id=translator_provider_id,
                show_progress=False,
                show_result=bool(tr_conf.get("show_result", False)),
                system_prompt="",
                custom_prefix="",
                max_retries=3,
            ),
            safety=SafetyConfig(
                enabled=bool(safety_conf.get("enabled", False)),
                provider_id=safety_provider_id,
                prompt_block_enabled=bool(safety_conf.get("prompt_block_enabled", True)),
                prompt_block_words=prompt_block_words,
            ),
            image_retag=ImageRetagConfig(
                enabled=bool(image_retag_conf.get("enabled", False)),
                provider_id=image_retag_provider_id,
                show_result=bool(image_retag_conf.get("show_result", False)),
            ),
            artist_presets=raw_artist_presets,
            artist_preset=first_artist_name,
            artist_source="",
            custom_artist_preset="",
            saved_custom_artist_presets=[],
            default_artist_preset="",
            prompt_suffix=prompt_conf.get(
                "quality_prompt",
                prompt_conf.get("prompt_suffix", DEFAULT_QUALITY_STRING),
            ),
            # Danbooru 检索服务内嵌，不开放配置
            danbooru_api_url=DEFAULT_DANBOORU_API_URL,
            retag_show_source=False,
            raw_config=config,
        )

    def get_generation_config_for_version(self, version: str) -> GenerationConfig:
        return GenerationConfig.for_version("4.5", self.raw_config, self.generation)

    def get_artist_presets_map(self) -> Dict[str, str]:
        result: Dict[str, str] = {}

        for item in self.artist_presets or []:
            if not isinstance(item, str):
                continue

            text = item.strip()

            if not text or ":" not in text:
                continue

            name, prompt = text.split(":", 1)
            name = name.strip()
            prompt = prompt.strip()

            if name and prompt:
                result[name] = prompt

        return result

    def get_all_artist_slots_map(self) -> Dict[str, str]:
        return self.get_artist_presets_map()

    def get_effective_artist_prompt(self) -> str:
        presets = self.get_artist_presets_map()

        if not presets:
            return ""

        first_name = next(iter(presets.keys()))
        return presets.get(first_name, "")

    def get_retag_control_prompts(self) -> List[str]:
        """Return configured prompt fragments that must stay out of retag tags.

        Retagging describes the source image, while the normal generation
        pipeline appends the selected artist preset and quality suffix later.
        Supplying every configured fragment lets the metadata and vision paths
        remove bare artist tags such as ``{hokori sakuni}`` as well as explicit
        ``artist:...`` controls before they are merged back into a prompt.
        """
        prompts = [
            str(prompt).strip()
            for prompt in self.get_all_artist_slots_map().values()
            if str(prompt).strip()
        ]
        suffix = str(self.prompt_suffix or "").strip()
        if suffix:
            prompts.append(suffix)
        return prompts

    def get_saved_artist_presets_map(self) -> Dict[str, str]:
        return self.get_artist_presets_map()

    def get_saved_artist_prompt(self, name: str) -> str:
        name = (name or "").strip()

        if not name:
            return ""

        presets = self.get_artist_presets_map()

        if name in presets:
            return presets[name]

        lower_name = name.lower()

        for k, v in presets.items():
            if k.lower() == lower_name:
                return v

        return ""

    def get_artist_prompt(self, preset_name: str) -> str:
        return self.get_saved_artist_prompt(preset_name)

    def is_configured(self) -> bool:
        return bool(self.api_url and self.api_key)


def _extract_provider_id(raw) -> str:
    if raw is None:
        return ""

    if isinstance(raw, str):
        return raw.strip()

    if isinstance(raw, dict):
        for k in ("id", "provider_id", "value", "key"):
            v = raw.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

    if isinstance(raw, list) and raw:
        first = raw[0]

        if isinstance(first, str):
            return first.strip()

        if isinstance(first, dict):
            for k in ("id", "provider_id", "value", "key"):
                v = first.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()

    return ""


def _normalize_string_list(raw) -> List[str]:
    if raw is None:
        return []

    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]

    if isinstance(raw, str):
        text = raw.strip()

        if not text:
            return []

        return [line.strip() for line in text.splitlines() if line.strip()]

    return []


def _first_artist_preset_name(items: List[str]) -> str:
    for item in items or []:
        if not isinstance(item, str):
            continue

        text = item.strip()

        if not text or ":" not in text:
            continue

        name, _ = text.split(":", 1)
        name = name.strip()

        if name:
            return name

    return ""

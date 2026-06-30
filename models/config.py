from dataclasses import dataclass, field
from typing import Dict, List, Tuple


FIXED_MODEL = "nai-diffusion-4-5-full"
DEFAULT_QUALITY_STRING = "best quality, amazing quality, very aesthetic, absurdres"
DEFAULT_NEGATIVE_PROMPT = "lowres, bad anatomy, bad hands, text, error, missing fingers"

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

        return replace(
            base,
            model=FIXED_MODEL,
            steps=28,
            scale=7.0,
            sampler=gen_conf.get("sampler", base.sampler),
            negative_prompt=prompt_conf.get(
                "negative_prompt",
                base.negative_prompt,
            ),
        )

    def to_api_params(self, prompt: str) -> dict:
        if isinstance(self.quality, str):
            quality_value = self.quality
        elif self.quality:
            quality_value = DEFAULT_QUALITY_STRING
        else:
            quality_value = ""

        params = {
            "model": FIXED_MODEL,
            "prompt": prompt,
            "size": f"{self.width}x{self.height}",
            "steps": 28,
            "scale": 7.0,
            "sampler": self.sampler,
            "quality": quality_value,
            "noise_schedule": self.noise_schedule,
            "image_format": self.image_format,
            "n_samples": 1,
            "response_format": "b64_json",
        }

        if self.negative_prompt:
            params["negative_prompt"] = self.negative_prompt

        if self.uc_preset:
            params["uc_preset"] = self.uc_preset

        if self.cfg_rescale != 0.0:
            params["cfg_rescale"] = self.cfg_rescale

        if self.variety_boost:
            params["variety_boost"] = self.variety_boost

        if self.characters:
            params["characters"] = self.characters
            params["use_coords"] = self.use_coords
            params["use_order"] = self.use_order

        return params


@dataclass
class TranslatorConfig:
    enabled: bool = False
    provider_id: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = "gpt-4o-mini"
    show_progress: bool = False
    show_result: bool = False
    system_prompt: str = ""
    custom_prefix: str = ""
    max_retries: int = 3

    def is_configured(self) -> bool:
        if self.provider_id:
            return True
        return bool(self.base_url and self.api_key)

    def masked_api_key(self) -> str:
        if self.provider_id:
            return f"提供商：{self.provider_id}"

        if not self.api_key:
            return "(未配置)"

        if len(self.api_key) <= 8:
            return "****"

        return f"{self.api_key[:4]}****{self.api_key[-4:]}"


@dataclass
class SafetyConfig:
    enabled: bool = True
    provider_id: str = ""
    prompt_block_enabled: bool = True
    unsafe_reply: str = "⚠️ 未能通过安全检测，已拦截"


@dataclass
class ImageRetagConfig:
    enabled: bool = False
    provider_id: str = ""
    show_result: bool = False

    def is_configured(self) -> bool:
        return bool(self.provider_id)


@dataclass
class PluginConfig:
    prefer_provider: bool = True
    image_provider_id: str = ""
    api_url: str = ""
    api_key: str = ""
    use_manual_api: bool = False

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
    danbooru_tag_search: bool = False
    retag_show_source: bool = False

    raw_config: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, config: dict) -> "PluginConfig":
        api_conf = config.get("api_config", {}) or {}
        tr_conf = config.get("translator_config", {}) or {}
        prompt_conf = config.get("prompt_config", {}) or {}
        dan_conf = config.get("danbooru_config", {}) or {}
        safety_conf = config.get("safety_config", {}) or {}
        image_retag_conf = config.get("image_retag_config", {}) or {}

        prefer_provider = bool(api_conf.get("prefer_provider", True))

        image_provider_id = (
            _extract_provider_id(api_conf.get("provider_id"))
            or _extract_provider_id(config.get("image_provider_id"))
            or _extract_provider_id(config.get("provider_id"))
        )

        manual_api_url = str(
            api_conf.get("api_url")
            or config.get("api_url")
            or ""
        ).strip().rstrip("/")

        manual_api_key = _extract_api_key(
            api_conf.get("api_key")
            or config.get("api_key")
            or ""
        )

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

        if not raw_artist_presets:
            raw_artist_presets = DEFAULT_ARTIST_PRESET_LIST.copy()

        first_artist_name = _first_artist_preset_name(raw_artist_presets) or "可爱"

        return cls(
            prefer_provider=prefer_provider,
            image_provider_id=image_provider_id,
            api_url=manual_api_url,
            api_key=manual_api_key,
            use_manual_api=False,
            generation=GenerationConfig.from_plugin_config(config),
            translator=TranslatorConfig(
                enabled=bool(
                    tr_conf.get(
                        "enabled",
                        config.get("translator_enabled", False),
                    )
                ),
                provider_id=translator_provider_id,
                base_url="",
                api_key="",
                model="gpt-4o-mini",
                show_progress=False,
                show_result=False,
                system_prompt="",
                custom_prefix="",
                max_retries=3,
            ),
            safety=SafetyConfig(
                enabled=bool(safety_conf.get("enabled", True)),
                provider_id=safety_provider_id,
                prompt_block_enabled=bool(safety_conf.get("prompt_block_enabled", True)),
                unsafe_reply=safety_conf.get(
                    "unsafe_reply",
                    "⚠️ 未能通过安全检测，已拦截",
                ),
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
            danbooru_api_url=str(dan_conf.get("api_url", "")).rstrip("/"),
            danbooru_tag_search=bool(dan_conf.get("tag_search", False)),
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

    def masked_api_key(self) -> str:
        if self.api_url and self.api_key:
            return "手动生图 API"

        if self.image_provider_id:
            return f"提供商：{self.image_provider_id}"

        if not self.api_key:
            return "(未配置)"

        if len(self.api_key) <= 8:
            return "****"

        return f"{self.api_key[:4]}****{self.api_key[-4:]}"


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


def _extract_api_key(raw) -> str:
    if raw is None:
        return ""

    if isinstance(raw, str):
        return raw.strip()

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                return item.strip()

    if isinstance(raw, dict):
        for k in ("key", "api_key", "value", "access_token"):
            v = raw.get(k)
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


def _parse_size(size_str: str) -> Tuple[int, int]:
    try:
        parts = size_str.lower().replace("×", "x").split("x")

        if len(parts) != 2:
            raise ValueError(f"无效的分辨率格式: {size_str}")

        width = int(parts[0].strip())
        height = int(parts[1].strip())

        if width <= 0 or height <= 0:
            raise ValueError(f"分辨率必须为正整数: {size_str}")

        return width, height

    except (ValueError, AttributeError) as e:
        raise ValueError(f"解析分辨率失败: {size_str}") from e


def resolve_size_preset(size_input: str, presets: dict) -> Tuple[int, int]:
    size_input = size_input.strip()

    if size_input in presets:
        return presets[size_input]

    return _parse_size(size_input)

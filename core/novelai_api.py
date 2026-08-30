"""NovelAI 官方协议（``/ai/generate-image``）的请求载荷与响应解包。

和中转网关那条路（``core/generator.py`` 的 ``_generate_by_chat_endpoint``）
比，官方协议是另一套东西：字段名不同，提示词分散在 ``input`` 与
``parameters.negative_prompt``，多角色要双写，响应是 ZIP 而不是 JSON。

**字段名未经联网核实。** 写这个模块时官方文档不可达。仓库里唯一的一手证据
是 ``services/nai_metadata.py``——它解析的是 NovelAI **写回图片**的参数 JSON，
证实了 ``v4_prompt`` / ``v4_negative_prompt`` / ``char_captions`` / ``centers``
这套结构确实存在，但证明不了**请求体**的顶层形状。

所以：拿不准的键名全部集中在下面的「待实测」常量区。服务端返回 400 时会点名
出错字段，对着改常量即可，不必翻 ``build_generate_payload`` 的函数体。
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Any, Dict, List, Optional

from .char_prompts import char_grid_center
from ..constants import normalize_nai_seed
from ..models.config import GenerationConfig, model_supports_variety_boost

# --------------------------------------------------------------------------
# 待实测常量区：服务端 400 点名哪个字段，就改这里
# --------------------------------------------------------------------------

# 顶层动作。文生图是 "generate"，img2img / inpaint 另有取值，本插件不涉及。
ACTION_GENERATE = "generate"

# parameters 的结构版本号。**实测 3 被拒**：服务端回
# "Unsupported value for parameters.params_version."，说明字段本身认识、
# 只是取值不在允许集合里。而插件并不需要钉住协议版本，所以默认不发这个键，
# 让服务端用它自己的默认值。
#
# 若某个站点确实要求它，报错会变成「缺少 params_version」——那时把这里设成
# 具体整数即可。用 tools/probe_novelai.py 可以一次性试出合法取值。
PARAMS_VERSION: Optional[int] = None

# uc 预设在官方协议里是**整数枚举**，而网关方言收的是 "light" 这样的字符串。
UC_PRESET_CODES: Dict[str, int] = {
    "heavy": 0,
    "light": 1,
    "human_focus": 2,
    "none": 3,
}
DEFAULT_UC_PRESET_CODE = UC_PRESET_CODES["light"]

# Variety+ 的官方原生名与取值。网关方言把它叫 variety_boost 并自行翻译；
# 原生名发给网关反而会被当未知字段丢掉（见 tools/probe_gateway.py 的实测结论）。
VARIETY_PLUS_SIGMA = 58.0

# 一次请求出几张图。与网关路径的 n_samples 保持一致。
N_SAMPLES = 1

_ZIP_MAGIC = b"PK\x03\x04"


def _uc_preset_code(value: Any) -> int:
    """把 uc 预设名转成官方的整数枚举，认不出来的一律按 light。"""
    return UC_PRESET_CODES.get(str(value or "").strip().lower(), DEFAULT_UC_PRESET_CODE)


def _char_captions(entries: List[Dict[str, str]], key: str) -> List[Dict[str, Any]]:
    """构造 ``v4_prompt`` / ``v4_negative_prompt`` 里的角色提示词数组。

    正负两边必须**同序等长**：``services/nai_metadata.py`` 读回来时就是按下标
    对齐正负角色提示词的，少一项会让后面的角色全部错位。所以负面为空时也要
    留一个空字符串占位，而不是跳过。
    """
    captions: List[Dict[str, Any]] = []

    for entry in entries:
        caption: Dict[str, Any] = {"char_caption": entry.get(key, "")}
        center = char_grid_center(entry.get("position"))
        if center is not None:
            # 注意是复数 centers 且为数组——单角色也要包一层。
            caption["centers"] = [center]
        captions.append(caption)

    return captions


def build_generate_payload(
    prompt: str,
    gen_config: GenerationConfig,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """把插件的生图参数翻成 NovelAI 官方请求体。

    纯函数，不碰网络——因为字段名要靠服务端报错来迭代，能单测的形状越多，
    改一个键名的代价就越小。
    """
    parameters: Dict[str, Any] = {
        "width": int(gen_config.width),
        "height": int(gen_config.height),
        "scale": float(gen_config.scale),
        "sampler": gen_config.sampler,
        "steps": int(gen_config.steps),
        "n_samples": N_SAMPLES,
        "noise_schedule": gen_config.noise_schedule,
        "cfg_rescale": float(gen_config.cfg_rescale),
        "ucPreset": _uc_preset_code(gen_config.uc_preset),
        # 插件自己把质量词拼进了提示词（prompt_config.quality_prompt），
        # 再让 NovelAI 追加一遍就重复了。
        "qualityToggle": False,
        "negative_prompt": gen_config.negative_prompt or "",
    }

    normalized_seed = normalize_nai_seed(seed)
    if normalized_seed is not None:
        parameters["seed"] = normalized_seed

    if PARAMS_VERSION is not None:
        parameters["params_version"] = PARAMS_VERSION

    # Variety+：V5 的能力表里没有这个参数，带上只会让载荷变脏。
    if gen_config.variety_boost and model_supports_variety_boost(gen_config.model):
        parameters["skip_cfg_above_sigma"] = VARIETY_PLUS_SIGMA

    entries = [entry for entry in (gen_config.characters or []) if isinstance(entry, dict)]

    # 站位坐标只在 use_coords 为真时生效，否则 NovelAI 按出场顺序排布。
    # 这个键在 v4_prompt 里是确定的（元数据可证），parameters 层则是照
    # 官方客户端的形状补的：宁可多发一个键，也不要坐标被静默忽略——
    # 那是「出图了但站位不对」这种不报错的失败。
    parameters["use_coords"] = bool(gen_config.use_coords)
    parameters["use_order"] = bool(gen_config.use_order)

    # V4+ 的提示词结构。本插件支持的两个模型（4.5-full / 5-full）都是 V4+，
    # 所以无条件带上。
    # TODO(待实测): V5 是否沿用 v4_prompt 这个键名尚未证实。若 V5 另有
    # v5_prompt 之类的结构，症状是「照常出图但多角色分区失效」——不报错，
    # 只能靠看图发现。
    parameters["v4_prompt"] = {
        "caption": {
            "base_caption": prompt,
            "char_captions": _char_captions(entries, "prompt"),
        },
        "use_coords": bool(gen_config.use_coords),
        "use_order": bool(gen_config.use_order),
    }
    parameters["v4_negative_prompt"] = {
        "caption": {
            "base_caption": gen_config.negative_prompt or "",
            "char_captions": _char_captions(entries, "negative_prompt"),
        },
    }

    if entries:
        # 和 v4_prompt.caption.char_captions 同序双写。两处都要填——前者是
        # 提示词本身，后者是 NovelAI 排版时读的角色表。
        parameters["characterPrompts"] = [
            {
                "prompt": entry.get("prompt", ""),
                "uc": entry.get("negative_prompt", ""),
                "center": char_grid_center(entry.get("position"))
                or {"x": 0.5, "y": 0.5},
                "enabled": True,
            }
            for entry in entries
        ]

    return {
        "input": prompt,
        "model": gen_config.model,
        "action": ACTION_GENERATE,
        "parameters": parameters,
    }


def extract_image_blobs(data: bytes) -> List[bytes]:
    """从官方响应里取出图片字节流。

    官方接口返回的是一个 ZIP（里面是 image_0.png……）。但第三方站点未必照做，
    所以裸图片字节直接原样返回。**这里不判断内容是不是图片**——那是
    ``ImageGenerator`` 的 ``_looks_like_image`` / ``_detect_image_format``
    的活，放在这里会和它重复一份魔数表。
    """
    if not data:
        return []

    if not data.startswith(_ZIP_MAGIC):
        return [data]

    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            # 按名字排序，保证 image_0 / image_1 的顺序稳定
            return [
                archive.read(name)
                for name in sorted(archive.namelist())
                if not name.endswith("/")
            ]
    except Exception:
        # 损坏的 ZIP 交给调用方当「没返回图片」处理并报错，
        # 不要在这里把原始字节当图片糊弄过去。
        return []

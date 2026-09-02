from __future__ import annotations

import asyncio
import json
import logging
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))

astrbot_module = types.ModuleType("astrbot")
astrbot_api_module = types.ModuleType("astrbot.api")
astrbot_api_module.logger = logging.getLogger("test.variety_boost")
astrbot_module.api = astrbot_api_module
sys.modules.setdefault("astrbot", astrbot_module)
sys.modules.setdefault("astrbot.api", astrbot_api_module)

from astrbot_plugin_bestnai_x.core.generator import (  # noqa: E402
    GenerationError,
    ImageGenerator,
)
from astrbot_plugin_bestnai_x.models.config import (  # noqa: E402
    MODEL_V45_FULL,
    MODEL_V5_FULL,
    GenerationConfig,
    PluginConfig,
)


def chat_user_payload(gen_config: GenerationConfig) -> dict:
    """跑一次真实的 chat 生图路径，把发出去的 NAI JSON 截下来。

    Variety+ 曾经只出现在一个生产无调用点的方法和系统提示词的字段清单里，
    真正发出的 user_payload 里一个字节都没有。断言必须落在实际载荷上，
    否则这个空转还会再回来一次。
    """

    generator = ImageGenerator(PluginConfig.from_dict({}))
    captured: dict = {}

    async def fake_post_json(endpoint: str, api_key: str, payload: dict) -> dict:
        captured["payload"] = payload
        return {}

    generator._post_json = fake_post_json

    async def run() -> None:
        await generator._generate_by_chat_endpoint(
            api_base="https://relay.example/v1",
            api_key="test-key",
            prompt="1girl",
            gen_config=gen_config,
            seed=None,
        )

    # 载荷截获后没有图片可解析，这里必然抛错；我们要的是 captured。
    try:
        asyncio.run(run())
    except GenerationError:
        pass

    return json.loads(captured["payload"]["messages"][1]["content"])


class VarietyBoostPayloadTest(unittest.TestCase):
    def test_single_character_chat_payload_uses_order_mode(self) -> None:
        gen_config = replace(
            GenerationConfig(),
            characters=[{"prompt": "ganyu", "position": "B2"}],
            use_coords=True,
            use_order=False,
        )

        user_payload = chat_user_payload(gen_config)

        self.assertIs(user_payload["use_coords"], False)
        self.assertIs(user_payload["use_order"], True)
        self.assertIs(user_payload["v4_prompt"]["use_coords"], False)
        self.assertIs(user_payload["v4_prompt"]["use_order"], True)

    def test_chat_payload_keeps_relay_compatibility_and_native_centers(self) -> None:
        gen_config = replace(
            GenerationConfig(),
            negative_prompt="global uc",
            characters=[
                {
                    "char_caption": "sunna",
                    "uc": "bad hands",
                    "centers": [{"x": 0.202, "y": 0.453}],
                },
                {
                    "char_caption": "aria",
                    "centers": [{"x": 0.518, "y": 0.424}],
                },
            ],
            use_coords=True,
            use_order=False,
        )

        user_payload = chat_user_payload(gen_config)

        self.assertEqual(
            user_payload["characters"],
            [
                {"prompt": "sunna", "negative_prompt": "bad hands", "position": "B3"},
                {"prompt": "aria", "negative_prompt": "", "position": "C3"},
            ],
        )
        self.assertIs(user_payload["use_coords"], True)
        self.assertIs(user_payload["use_order"], False)
        self.assertEqual(
            [
                item["centers"][0]
                for item in user_payload["v4_prompt"]["caption"]["char_captions"]
            ],
            [{"x": 0.202, "y": 0.453}, {"x": 0.518, "y": 0.424}],
        )
        self.assertEqual(
            [
                item["centers"][0]
                for item in user_payload["v4_negative_prompt"]["caption"]["char_captions"]
            ],
            [{"x": 0.202, "y": 0.453}, {"x": 0.518, "y": 0.424}],
        )

    def test_variety_boost_sends_the_gateway_dialect_field(self) -> None:
        # 已探测：发 variety_boost=true，返回图的元数据里
        # skip_cfg_above_sigma=58.0 —— 网关自己做了这层翻译。
        gen_config = replace(
            GenerationConfig(), model=MODEL_V45_FULL, variety_boost=True
        )

        user_payload = chat_user_payload(gen_config)

        self.assertIs(user_payload.get("variety_boost"), True)

    def test_disabled_variety_boost_omits_the_field(self) -> None:
        gen_config = replace(
            GenerationConfig(), model=MODEL_V45_FULL, variety_boost=False
        )

        user_payload = chat_user_payload(gen_config)

        self.assertNotIn("variety_boost", user_payload)

    def test_v5_never_sends_variety_boost(self) -> None:
        # V5 的能力表里没有 skip_cfg_above_sigma，网关翻译过去也会被清洗掉。
        gen_config = replace(
            GenerationConfig(), model=MODEL_V5_FULL, variety_boost=True
        )

        user_payload = chat_user_payload(gen_config)

        self.assertNotIn("variety_boost", user_payload)

    def test_raw_nai_field_name_is_never_sent(self) -> None:
        # 已探测：网关把未知字段静默丢弃，直接发 NAI 原生的
        # skip_cfg_above_sigma 等于没发。要发的是网关方言 variety_boost。
        gen_config = replace(
            GenerationConfig(), model=MODEL_V45_FULL, variety_boost=True
        )

        user_payload = chat_user_payload(gen_config)

        self.assertNotIn("skip_cfg_above_sigma", user_payload)


if __name__ == "__main__":
    unittest.main()

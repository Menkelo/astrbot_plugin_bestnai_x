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
    VARIETY_SKIP_CFG_SIGMA,
    GenerationConfig,
    PluginConfig,
)


def chat_user_payload(gen_config: GenerationConfig) -> dict:
    """跑一次真实的 chat 生图路径，把发出去的 NAI JSON 截下来。

    Variety+ 曾经只出现在 to_api_params()（生产无调用点）和系统提示词的
    字段清单里，真正发出的 user_payload 里一个字节都没有。断言必须落在
    实际载荷上，否则这个空转还会再回来一次。
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
    def test_variety_boost_sends_skip_cfg_above_sigma(self) -> None:
        gen_config = replace(
            GenerationConfig(), model=MODEL_V45_FULL, variety_boost=True
        )

        user_payload = chat_user_payload(gen_config)

        self.assertEqual(
            user_payload.get("skip_cfg_above_sigma"), VARIETY_SKIP_CFG_SIGMA
        )

    def test_disabled_variety_boost_omits_the_field(self) -> None:
        gen_config = replace(
            GenerationConfig(), model=MODEL_V45_FULL, variety_boost=False
        )

        user_payload = chat_user_payload(gen_config)

        self.assertNotIn("skip_cfg_above_sigma", user_payload)

    def test_v5_never_sends_skip_cfg_above_sigma(self) -> None:
        # V5 的能力表里没有这个参数，官方请求清洗会删掉它。
        gen_config = replace(
            GenerationConfig(), model=MODEL_V5_FULL, variety_boost=True
        )

        user_payload = chat_user_payload(gen_config)

        self.assertNotIn("skip_cfg_above_sigma", user_payload)

    def test_legacy_variety_boost_key_is_never_sent(self) -> None:
        # `variety_boost` 不是 NovelAI 的字段名，发出去等于没发。
        gen_config = replace(
            GenerationConfig(), model=MODEL_V45_FULL, variety_boost=True
        )

        user_payload = chat_user_payload(gen_config)

        self.assertNotIn("variety_boost", user_payload)

    def test_api_params_uses_the_same_field(self) -> None:
        gen_config = replace(
            GenerationConfig(), model=MODEL_V45_FULL, variety_boost=True
        )

        params = gen_config.to_api_params("1girl")

        self.assertEqual(params.get("skip_cfg_above_sigma"), VARIETY_SKIP_CFG_SIGMA)
        self.assertNotIn("variety_boost", params)


if __name__ == "__main__":
    unittest.main()

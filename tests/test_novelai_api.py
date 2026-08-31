from __future__ import annotations

import asyncio
import json
import logging
import sys
import types
import unittest
import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path


workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

# core/generator.py 在导入期就要这两个模块，但本测试只碰纯函数、端点拼接
# 与分派逻辑，不发真实请求。
sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
astrbot_module = sys.modules.setdefault("astrbot", types.ModuleType("astrbot"))
astrbot_api_module = sys.modules.setdefault(
    "astrbot.api", types.ModuleType("astrbot.api")
)
astrbot_api_module.logger = logging.getLogger("test.novelai_api")
astrbot_module.api = astrbot_api_module

from astrbot_plugin_bestnai_x.core.char_prompts import (  # noqa: E402
    char_grid_center,
    char_grid_position,
)
from astrbot_plugin_bestnai_x.core.generator import (  # noqa: E402
    APIKeyError,
    GenerationError,
    ImageGenerator,
)
from astrbot_plugin_bestnai_x.core.novelai_api import (  # noqa: E402
    UC_PRESET_CODES,
    VARIETY_PLUS_SIGMA,
    build_generate_payload,
    extract_image_blobs,
)
from astrbot_plugin_bestnai_x.models.config import (  # noqa: E402
    DEFAULT_OFFICIAL_API_URL,
    MODEL_V45_FULL,
    MODEL_V5_FULL,
    GenerationConfig,
    PluginConfig,
)


ROOT = Path(__file__).resolve().parents[1]

BASE = GenerationConfig(
    model=MODEL_V45_FULL,
    negative_prompt="lowres, bad hands",
)

TWO_CHARACTERS = [
    {"prompt": "hatsune miku", "negative_prompt": "bad hands", "position": "B3"},
    {"prompt": "kagamine rin", "negative_prompt": "", "position": "D3"},
]


class CharGridCenterTest(unittest.TestCase):
    """网格记号 → 归一化坐标。走官方协议时这一步没有网关代劳。"""

    def test_matches_the_gateway_observed_mapping(self) -> None:
        # models/config.py 记录的实测值：网关把 B3 翻成 {x:0.3, y:0.5}
        self.assertEqual(char_grid_center("B3"), {"x": 0.3, "y": 0.5})
        self.assertEqual(char_grid_center("C3"), {"x": 0.5, "y": 0.5})
        self.assertEqual(char_grid_center("D3"), {"x": 0.7, "y": 0.5})

    def test_round_trips_through_char_grid_position_for_every_cell(self) -> None:
        for column in "ABCDE":
            for row in range(1, 6):
                position = f"{column}{row}"
                with self.subTest(position=position):
                    center = char_grid_center(position)
                    self.assertEqual(
                        char_grid_position(center["x"], center["y"]), position
                    )

    def test_tolerates_case_and_whitespace(self) -> None:
        self.assertEqual(char_grid_center(" b3 "), {"x": 0.3, "y": 0.5})

    def test_rejects_anything_outside_the_grid(self) -> None:
        for value in ("C6", "F1", "Z9", "C", "3C", "", None, 33):
            with self.subTest(value=value):
                self.assertIsNone(char_grid_center(value))


class BuildPayloadTest(unittest.TestCase):
    def test_top_level_shape(self) -> None:
        payload = build_generate_payload("1girl, solo", BASE)

        self.assertEqual(
            set(payload), {"input", "model", "action", "parameters"}
        )
        self.assertEqual(payload["input"], "1girl, solo")
        self.assertEqual(payload["model"], MODEL_V45_FULL)
        self.assertEqual(payload["action"], "generate")

    def test_core_parameters_follow_the_generation_config(self) -> None:
        gen_config = replace(
            BASE,
            width=1216,
            height=832,
            steps=23,
            scale=6.5,
            sampler="k_euler",
            noise_schedule="native",
            cfg_rescale=0.4,
        )

        parameters = build_generate_payload("1girl", gen_config)["parameters"]

        self.assertEqual(parameters["width"], 1216)
        self.assertEqual(parameters["height"], 832)
        self.assertEqual(parameters["steps"], 23)
        self.assertEqual(parameters["scale"], 6.5)
        self.assertEqual(parameters["sampler"], "k_euler")
        self.assertEqual(parameters["noise_schedule"], "native")
        self.assertEqual(parameters["cfg_rescale"], 0.4)
        self.assertEqual(parameters["n_samples"], 1)
        self.assertEqual(parameters["negative_prompt"], "lowres, bad hands")

    def test_params_version_is_not_sent_by_default(self) -> None:
        # 实测发 3 被服务端拒掉（Unsupported value for parameters.params_version），
        # 而插件不需要钉住协议版本，交给服务端用自己的默认值
        parameters = build_generate_payload("1girl", BASE)["parameters"]

        self.assertNotIn("params_version", parameters)

    def test_uc_preset_is_sent_as_an_integer_code(self) -> None:
        # 网关方言收字符串 "light"，官方协议收整数
        for name, code in UC_PRESET_CODES.items():
            with self.subTest(name=name):
                payload = build_generate_payload("1girl", replace(BASE, uc_preset=name))
                self.assertEqual(payload["parameters"]["ucPreset"], code)

    def test_unknown_uc_preset_falls_back_to_light(self) -> None:
        payload = build_generate_payload("1girl", replace(BASE, uc_preset="nonsense"))
        self.assertEqual(payload["parameters"]["ucPreset"], UC_PRESET_CODES["light"])

    def test_quality_toggle_is_off(self) -> None:
        # 插件已经把质量词拼进提示词，再让 NovelAI 追加一遍就重复了
        payload = build_generate_payload("1girl", BASE)
        self.assertIs(payload["parameters"]["qualityToggle"], False)

    def test_seed_is_omitted_unless_explicitly_valid(self) -> None:
        for value in (None, 0, "abc", -1, True):
            with self.subTest(value=value):
                payload = build_generate_payload("1girl", BASE, seed=value)
                self.assertNotIn("seed", payload["parameters"])

        payload = build_generate_payload("1girl", BASE, seed=3405988762)
        self.assertEqual(payload["parameters"]["seed"], 3405988762)

    def test_variety_plus_uses_the_native_field_on_v45(self) -> None:
        payload = build_generate_payload("1girl", replace(BASE, variety_boost=True))
        parameters = payload["parameters"]

        self.assertEqual(parameters["skip_cfg_above_sigma"], VARIETY_PLUS_SIGMA)
        # variety_boost 是中转网关的方言，官方协议不认
        self.assertNotIn("variety_boost", parameters)

    def test_variety_plus_is_dropped_on_v5(self) -> None:
        # V5 的能力表里没有 skip_cfg_above_sigma
        gen_config = replace(BASE, model=MODEL_V5_FULL, variety_boost=True)
        parameters = build_generate_payload("1girl", gen_config)["parameters"]

        self.assertNotIn("skip_cfg_above_sigma", parameters)

    def test_variety_plus_absent_when_switched_off(self) -> None:
        parameters = build_generate_payload("1girl", BASE)["parameters"]
        self.assertNotIn("skip_cfg_above_sigma", parameters)


class CharacterPayloadTest(unittest.TestCase):
    @staticmethod
    def _parameters(**overrides) -> dict:
        gen_config = replace(BASE, characters=TWO_CHARACTERS, **overrides)
        return build_generate_payload("2girls", gen_config)["parameters"]

    def test_character_prompts_and_char_captions_stay_in_the_same_order(self) -> None:
        parameters = self._parameters()

        captions = parameters["v4_prompt"]["caption"]["char_captions"]
        self.assertEqual(
            [item["char_caption"] for item in captions],
            ["hatsune miku", "kagamine rin"],
        )
        self.assertEqual(
            [item["prompt"] for item in parameters["characterPrompts"]],
            ["hatsune miku", "kagamine rin"],
        )

    def test_centers_are_converted_from_grid_positions(self) -> None:
        parameters = self._parameters()

        captions = parameters["v4_prompt"]["caption"]["char_captions"]
        # v4_prompt 用复数 centers 且是数组，characterPrompts 用单数 center
        self.assertEqual(captions[0]["centers"], [{"x": 0.3, "y": 0.5}])
        self.assertEqual(captions[1]["centers"], [{"x": 0.7, "y": 0.5}])
        self.assertEqual(
            parameters["characterPrompts"][0]["center"], {"x": 0.3, "y": 0.5}
        )
        self.assertEqual(
            parameters["v4_negative_prompt"]["caption"]["char_captions"][1]["centers"],
            [{"x": 0.7, "y": 0.5}],
        )

    def test_official_centers_are_not_quantized_to_grid(self) -> None:
        raw_entries = [
            {
                "char_caption": "sunna_(zenless_zone_zero),upper body",
                "uc": "bad hands",
                "centers": [{"x": 0.202, "y": 0.453}],
            },
            {
                "char_caption": "aria_(zenless_zone_zero),upper body",
                "centers": [{"x": 0.518, "y": 0.424}],
            },
            {
                "char_caption": "nangong_yu,upper body",
                "centers": [{"x": 0.814, "y": 0.467}],
            },
        ]
        parameters = build_generate_payload(
            "3girls",
            replace(BASE, characters=raw_entries, use_coords=True),
        )["parameters"]

        expected_centers = [
            {"x": 0.202, "y": 0.453},
            {"x": 0.518, "y": 0.424},
            {"x": 0.814, "y": 0.467},
        ]
        self.assertEqual(
            [item["centers"][0] for item in parameters["v4_prompt"]["caption"]["char_captions"]],
            expected_centers,
        )
        self.assertEqual(
            [item["centers"][0] for item in parameters["v4_negative_prompt"]["caption"]["char_captions"]],
            expected_centers,
        )
        self.assertEqual(
            [item["center"] for item in parameters["characterPrompts"]],
            expected_centers,
        )
        self.assertEqual(
            parameters["characterPrompts"][0]["uc"], "bad hands"
        )
        self.assertTrue(
            all("enabled" not in item for item in parameters["characterPrompts"])
        )

    def test_negative_captions_keep_a_placeholder_so_indexes_stay_aligned(self) -> None:
        # 第二个角色没有负面词；跳过它会让后面的角色整体错位
        captions = self._parameters()["v4_negative_prompt"]["caption"]["char_captions"]

        self.assertEqual(
            [item["char_caption"] for item in captions], ["bad hands", ""]
        )

    def test_base_captions_carry_the_main_prompts(self) -> None:
        parameters = self._parameters()

        self.assertEqual(parameters["v4_prompt"]["caption"]["base_caption"], "2girls")
        self.assertEqual(
            parameters["v4_negative_prompt"]["caption"]["base_caption"],
            "lowres, bad hands",
        )

    def test_use_coords_and_use_order_are_written_in_both_places(self) -> None:
        parameters = self._parameters(use_coords=True, use_order=False)

        self.assertIs(parameters["use_coords"], True)
        self.assertNotIn("use_order", parameters)
        self.assertIs(parameters["v4_prompt"]["use_coords"], True)
        self.assertIs(parameters["v4_prompt"]["use_order"], False)

    def test_without_characters_the_caption_arrays_are_empty_not_missing(self) -> None:
        parameters = build_generate_payload("1girl", BASE)["parameters"]

        self.assertEqual(parameters["v4_prompt"]["caption"]["char_captions"], [])
        self.assertEqual(
            parameters["v4_negative_prompt"]["caption"]["char_captions"], []
        )
        self.assertNotIn("characterPrompts", parameters)

    def test_malformed_entries_are_dropped(self) -> None:
        gen_config = replace(BASE, characters=["nope", None, {"prompt": "ok"}])
        parameters = build_generate_payload("1girl", gen_config)["parameters"]

        self.assertEqual(len(parameters["characterPrompts"]), 1)
        self.assertEqual(
            len(parameters["v4_prompt"]["caption"]["char_captions"]), 1
        )

    def test_entry_without_a_position_still_gets_a_center(self) -> None:
        # 缺站位不能让 characterPrompts 少一个键，否则和 char_captions 对不上
        gen_config = replace(BASE, characters=[{"prompt": "solo girl"}])
        parameters = build_generate_payload("1girl", gen_config)["parameters"]

        self.assertEqual(
            parameters["characterPrompts"][0]["center"], {"x": 0.5, "y": 0.5}
        )
        self.assertEqual(
            parameters["v4_prompt"]["caption"]["char_captions"][0]["centers"],
            [{"x": 0.5, "y": 0.5}],
        )
        self.assertEqual(
            parameters["v4_negative_prompt"]["caption"]["char_captions"][0]["centers"],
            [{"x": 0.5, "y": 0.5}],
        )
        self.assertEqual(parameters["v4_negative_prompt"]["legacy_uc"], False)


def _zip_of(members: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class ExtractImageBlobsTest(unittest.TestCase):
    def test_reads_every_member_in_name_order(self) -> None:
        data = _zip_of({"image_1.png": b"second", "image_0.png": b"first"})

        self.assertEqual(extract_image_blobs(data), [b"first", b"second"])

    def test_bare_image_bytes_pass_through(self) -> None:
        # 第三方站点未必打包，裸图片字节要原样交出去
        raw = b"\x89PNG\r\n\x1a\n" + b"body"

        self.assertEqual(extract_image_blobs(raw), [raw])

    def test_directory_entries_are_skipped(self) -> None:
        data = _zip_of({"folder/": b"", "folder/image_0.png": b"first"})

        self.assertEqual(extract_image_blobs(data), [b"first"])

    def test_corrupt_zip_returns_empty(self) -> None:
        # 有 ZIP 魔数但内容是垃圾：交给调用方当「没返回图片」报错，
        # 不要把原始字节当图片糊弄过去
        self.assertEqual(extract_image_blobs(b"PK\x03\x04" + b"\x00" * 64), [])

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(extract_image_blobs(b""), [])


class OfficialEndpointTest(unittest.TestCase):
    def test_appends_the_official_path(self) -> None:
        self.assertEqual(
            ImageGenerator._official_endpoint("https://image.novelai.net"),
            "https://image.novelai.net/ai/generate-image",
        )

    def test_tolerates_a_trailing_slash(self) -> None:
        self.assertEqual(
            ImageGenerator._official_endpoint("https://my.site/"),
            "https://my.site/ai/generate-image",
        )

    def test_does_not_double_append_a_full_url(self) -> None:
        full = "https://my.site/ai/generate-image"
        self.assertEqual(ImageGenerator._official_endpoint(full), full)

    def test_never_inserts_the_v1_prefix(self) -> None:
        # 官方协议没有 /v1 这一层，复用 _endpoint 会拼错
        self.assertNotIn("/v1", ImageGenerator._official_endpoint("https://my.site"))


class OfficialModeWiringTest(unittest.TestCase):
    def test_generate_dispatches_to_the_official_path_only(self) -> None:
        config = PluginConfig(
            use_official_api=True,
            api_url="https://my.site",
            api_key="pst-token",
        )
        generator = ImageGenerator(config)
        calls: list[dict] = []

        async def fake_official(**kwargs):
            calls.append(kwargs)
            return [("png", b"payload")]

        async def relay_path(**kwargs):
            raise AssertionError("官方模式不该走中转网关的路径")

        generator._generate_by_official_endpoint = fake_official
        generator._generate_by_chat_endpoint = relay_path
        generator._generate_by_images_endpoint = relay_path

        result = asyncio.run(generator.generate("1girl", GenerationConfig()))

        self.assertEqual(result.images, [("png", b"payload")])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["api_base"], "https://my.site")
        self.assertEqual(calls[0]["api_key"], "pst-token")
        # 普通生图不强制请求 seed，种子以返回 PNG 的元数据为准
        self.assertIsNone(calls[0]["seed"])

    def test_relay_mode_is_untouched_by_the_switch(self) -> None:
        config = PluginConfig(api_url="https://gateway.test", api_key="sk-x")
        generator = ImageGenerator(config)
        calls: list[dict] = []

        async def fake_chat(**kwargs):
            calls.append(kwargs)
            return [("png", b"payload")]

        async def official_path(**kwargs):
            raise AssertionError("未开开关时不该走官方协议")

        generator._generate_by_chat_endpoint = fake_chat
        generator._generate_by_official_endpoint = official_path

        asyncio.run(generator.generate("1girl", GenerationConfig()))

        self.assertEqual(len(calls), 1)

    def test_missing_token_reports_the_official_mode_error(self) -> None:
        generator = ImageGenerator(PluginConfig(use_official_api=True))

        with self.assertRaises(APIKeyError) as ctx:
            asyncio.run(generator.generate("1girl", GenerationConfig()))

        self.assertIn("官方接口", str(ctx.exception))

    def test_non_image_200_body_is_surfaced_in_the_error(self) -> None:
        # 站点把错误塞进 200 响应时，正文必须冒到报错里——
        # 否则「靠报错定位字段名」就没线索了
        config = PluginConfig(
            use_official_api=True,
            api_url="https://my.site",
            api_key="pst-token",
        )
        generator = ImageGenerator(config)

        async def fake_post(**kwargs):
            return b'{"message":"unknown field: ucPreset"}'

        generator._post_binary = fake_post

        with self.assertRaises(GenerationError) as ctx:
            asyncio.run(generator.generate("1girl", GenerationConfig()))

        self.assertIn("unknown field: ucPreset", str(ctx.exception))


class OfficialConfigTest(unittest.TestCase):
    def test_plugin_config_reads_the_official_fields(self) -> None:
        config = PluginConfig.from_dict(
            {
                "api_config": {
                    "use_official_api": True,
                    "official_api_url": "  https://my.site  ",
                    "official_api_token": "  pst-abc  ",
                }
            }
        )

        self.assertTrue(config.use_official_api)
        self.assertEqual(config.official_api_url, "https://my.site")
        self.assertEqual(config.official_api_token, "pst-abc")

    def test_switch_defaults_to_off(self) -> None:
        config = PluginConfig.from_dict({})

        self.assertFalse(config.use_official_api)
        self.assertEqual(config.official_api_url, DEFAULT_OFFICIAL_API_URL)
        self.assertEqual(config.official_api_token, "")

    def test_conf_schema_exposes_the_official_fields(self) -> None:
        schema = json.loads((ROOT / "_conf_schema.json").read_text(encoding="utf-8"))
        items = schema["api_config"]["items"]

        self.assertEqual(items["use_official_api"]["type"], "bool")
        self.assertIs(items["use_official_api"]["default"], False)
        self.assertEqual(
            items["official_api_url"]["default"], DEFAULT_OFFICIAL_API_URL
        )
        self.assertEqual(items["official_api_token"]["default"], "")

    def test_main_routes_official_mode_through_the_shared_credential_fields(self) -> None:
        source = (ROOT / "main.py").read_text(encoding="utf-8")

        # 官方模式必须早退，不再去解析两个提供商槽位
        self.assertIn("def _resolve_official_api", source)
        self.assertIn("self._resolve_official_api()", source)
        # V5 槽位留空并标记就绪，两档模型才会都落到同一个官方端点
        self.assertIn("self._image_provider_v5_resolved = True", source)


if __name__ == "__main__":
    unittest.main()

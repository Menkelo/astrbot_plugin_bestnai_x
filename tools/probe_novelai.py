"""试探 NovelAI 官方协议里某个字段的合法取值。

**原理和 tools/probe_gateway.py 一样：拿校验错误说话，不出图。** 官方接口的
字段校验失败一律 400 且不生成图片，也就不花 Anlas。只有整个载荷都合法时才
会真出一张图——脚本一旦拿到 200 就立刻停下，并告诉你花了额度。

载荷直接调用 ``core/novelai_api.build_generate_payload``，也就是生产路径本身，
不另写一份，免得两边漂移。

用法：

    export BESTNAI_OFFICIAL_URL="https://你的站点"
    export BESTNAI_OFFICIAL_TOKEN="pst-..."

    python tools/probe_novelai.py                       # 发一次生产载荷，看当前第一个报错
    python tools/probe_novelai.py params_version        # 试 omit/1/2/3/4/5
    python tools/probe_novelai.py params_version 1 7 9  # 只试这几个取值
    BESTNAI_MODEL=nai-diffusion-5-full python tools/probe_novelai.py   # 换模型档

已知结论（2026-08-30 实测）：
    params_version = 3   被拒（"Unsupported value for parameters.params_version"）
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import aiohttp

workspace_dir = Path(__file__).resolve().parents[2]
if str(workspace_dir) not in sys.path:
    sys.path.insert(0, str(workspace_dir))

from astrbot_plugin_bestnai_x.core.novelai_api import (  # noqa: E402
    build_generate_payload,
)
from astrbot_plugin_bestnai_x.models.config import (  # noqa: E402
    MODEL_V45_FULL,
    GenerationConfig,
)


TIMEOUT = 180
OMIT = "__omit__"
DEFAULT_VALUES: List[Any] = [OMIT, 1, 2, 3, 4, 5]
PROMPT = "1girl"


def endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    path = "/ai/generate-image"
    return base if base.endswith(path) else f"{base}{path}"


def production_payload() -> Dict[str, Any]:
    model = os.environ.get("BESTNAI_MODEL", "").strip() or MODEL_V45_FULL
    return build_generate_payload(PROMPT, GenerationConfig(model=model))


def payload_with(field: str, value: Any) -> Dict[str, Any]:
    payload = production_payload()
    parameters = payload["parameters"]

    if value == OMIT:
        parameters.pop(field, None)
    else:
        parameters[field] = value

    return payload


def error_message(text: str) -> str:
    """从错误响应里挖出人话，挖不到就返回原文截断。"""
    try:
        data = json.loads(text)
    except Exception:
        return text.strip()[:200]

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            data = {**data, **error}
        elif isinstance(error, str) and error.strip():
            return error.strip()

        for key in ("message", "msg", "detail", "reason"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return text.strip()[:200]


async def send(
    session: aiohttp.ClientSession,
    url: str,
    token: str,
    payload: Dict[str, Any],
) -> tuple[int, str]:
    try:
        async with session.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        ) as response:
            status = response.status
            if status == 200:
                body = await response.read()
                return status, f"出图了（{len(body)} 字节）——该载荷通过了全部校验"
            return status, error_message(await response.text())
    except Exception as exc:
        return 0, f"请求失败：{exc}"


def parse_value(raw: str) -> Any:
    if raw == OMIT or raw.lower() in ("omit", "none", "null"):
        return OMIT
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


async def main() -> int:
    api_base = os.environ.get("BESTNAI_OFFICIAL_URL", "").strip()
    token = os.environ.get("BESTNAI_OFFICIAL_TOKEN", "").strip()

    if not api_base or not token:
        print(
            "请先设置 BESTNAI_OFFICIAL_URL 与 BESTNAI_OFFICIAL_TOKEN",
            file=sys.stderr,
        )
        return 2

    url = endpoint(api_base)
    args = sys.argv[1:]
    field = args[0] if args else ""
    values = [parse_value(raw) for raw in args[1:]] or DEFAULT_VALUES

    print(f"探测端点：{url}")
    print(f"模型：{production_payload()['model']}\n")

    timeout = aiohttp.ClientTimeout(total=TIMEOUT)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        if not field:
            # 不指定字段：原样发一次生产载荷，看当前卡在哪
            print("发送当前生产载荷：")
            print(json.dumps(production_payload(), ensure_ascii=False, indent=2))
            status, message = await send(session, url, token, production_payload())
            print(f"\nHTTP {status}：{message}")
            if status == 200:
                print("\n本次出图 1 张。")
            return 0

        print(f"待测字段：parameters.{field}")
        print(f"{'取值':<12} {'状态':<8} 说明")
        print("-" * 92)

        for value in values:
            label = "(不发送)" if value == OMIT else str(value)
            status, message = await send(
                session, url, token, payload_with(field, value)
            )

            if status == 200:
                print(f"{label:<12} {'✅ 通过':<8} {message}")
                print(f"\n找到合法取值：{label}。本次出图 1 张。")
                print(f"把 core/novelai_api.py 里的常量改成它即可。")
                return 0

            marker = "❌" if field in message else "⚠️"
            print(f"{label:<12} {'HTTP ' + str(status):<8} {marker} {message[:70]}")

        print(
            "\n没有取值通过。若报错已经不再点名该字段，说明它已经合法，"
            "卡点换到了别的字段——用那个字段名重跑一次。"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

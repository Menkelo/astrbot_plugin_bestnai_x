"""探测中转网关到底认哪些 NovelAI 字段。

**原理：拿非法值试探，不出图。** 网关会逐字段校验并在 400 里点名出错的字段
（`{"param": "use_coords", "code": "REQUEST_VALIDATION_ERROR"}`）。所以给某个
字段塞一个必然非法的值：

- 回 400 且点名该字段 → 网关认识它，**在白名单内**
- 回 200（照常出图）    → 网关根本没校验它，**当未知字段丢掉了**

白名单内的字段一律不出图，也就不花额度。只有被丢弃的字段会真出一张图——
这正是判定它被丢弃的依据。脚本会在最后告诉你花了几张。

对照组 `totally_made_up_field` 必然是「被丢弃」，用来确认判定逻辑本身没跑偏。

已知结论（2026-08-28 对 api.tuercha.com 实测）：
    variety_boost / use_coords / characters / seed / cfg_rescale / uc_preset  在白名单内
    skip_cfg_above_sigma（NAI 原生名）                                        被丢弃

用法：

    export BESTNAI_API_URL="https://你的网关/v1"
    export BESTNAI_API_KEY="sk-..."
    python tools/probe_gateway.py                    # 测默认字段表
    python tools/probe_gateway.py reference_image_multiple vibe_strength

基础载荷形状对齐 core/generator.py 的 `user_payload`，那里是生产路径的唯一
真相；改了那边，这里也要跟着改。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Tuple

import aiohttp

MODEL = "nai-diffusion-4-5-full"
TIMEOUT = 180

# 一个既不是数字、也不是布尔、也不是数组的值：无论字段期望什么类型都非法
INVALID = "__probe_invalid__"

DEFAULT_FIELDS: List[str] = [
    "variety_boost",
    "skip_cfg_above_sigma",
    "use_coords",
    "characters",
    "seed",
    "cfg_rescale",
    "uc_preset",
    "totally_made_up_field",  # 对照组：必然被丢弃
]

BASE_PAYLOAD: Dict[str, Any] = {
    "prompt": "1girl",
    "size": [832, 1216],
    "width": 832,
    "height": 1216,
    "steps": 28,
    "scale": 7.0,
    "sampler": "k_euler_ancestral",
    "noise_schedule": "karras",
    "image_format": "png",
    "n_samples": 1,
}

SYSTEM_MESSAGE = (
    "You are an image generation endpoint. The JSON object in the user message "
    "is the authoritative NovelAI generation request."
)


def endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/chat/completions"


async def probe_field(
    session: aiohttp.ClientSession,
    url: str,
    api_key: str,
    field: str,
) -> Tuple[str, str]:
    """返回 (判定, 佐证文本)。"""

    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {
                "role": "user",
                "content": json.dumps(
                    {**BASE_PAYLOAD, field: INVALID}, ensure_ascii=False
                ),
            },
        ],
        "stream": False,
    }

    try:
        async with session.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
        ) as response:
            status = response.status
            text = await response.text()
    except Exception as exc:
        return "?", f"请求失败：{exc}"

    if status == 200:
        return "dropped", "HTTP 200——字段未被校验，出了一张图"

    if status == 400:
        try:
            message = json.loads(text)["error"]["message"]
        except Exception:
            message = text[:150]

        # 点名该字段才算数：报的可能是别的字段的错
        if field in text:
            return "accepted", message

        return "?", f"400 但没点名该字段：{message}"

    return "?", f"HTTP {status}：{text[:120]}"


async def main() -> int:
    api_base = os.environ.get("BESTNAI_API_URL", "").strip()
    api_key = os.environ.get("BESTNAI_API_KEY", "").strip()

    if not api_base or not api_key:
        print("请先设置 BESTNAI_API_URL 与 BESTNAI_API_KEY", file=sys.stderr)
        return 2

    fields = sys.argv[1:] or DEFAULT_FIELDS
    url = endpoint(api_base)

    print(f"探测端点：{url}")
    print(f"待测字段：{len(fields)} 个\n")
    print(f"{'字段':<26} {'判定':<12} 佐证")
    print("-" * 92)

    spent = 0

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=TIMEOUT)
    ) as session:
        for field in fields:
            verdict, evidence = await probe_field(session, url, api_key, field)

            if verdict == "accepted":
                label = "✅ 在白名单"
            elif verdict == "dropped":
                label = "❌ 被丢弃"
                spent += 1
            else:
                label = "⚠️ 判不了"

            print(f"{field:<26} {label:<12} {evidence[:110]}")

    print(f"\n本次出图 {spent} 张（只有被丢弃的字段会真出图）。")

    if "totally_made_up_field" in fields:
        print("对照组 totally_made_up_field 应当是「被丢弃」，否则判定逻辑有问题。")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

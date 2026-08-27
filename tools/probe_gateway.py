"""探测中转网关到底把哪些 NovelAI 字段透传给了上游。

**为什么一次请求就够。** NovelAI 会把它实际采用的整套生成参数写回 PNG 的
`Comment` 块。所以只要发一个带上全部待测字段的请求，再读回图里的 Comment，
就能逐个字段比对「我发的」和「NAI 收到的」——网关吞掉的字段会在返回值里
维持默认（通常是 null 或 false），透传的则会带上我们发的值。

不必固定 seed 出两张图做像素比对，也就不用为一次探测烧两次额度。

用法（在装了 astrbot 的机器上跑，只依赖 aiohttp）：

    export BESTNAI_API_URL="https://你的网关/v1"
    export BESTNAI_API_KEY="sk-..."
    python tools/probe_gateway.py

载荷形状与 core/generator.py:201 的 `user_payload` 保持一致——那里是生产
路径的唯一真相，这个脚本改了那边也要跟着改。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
from io import BytesIO
from typing import Any, Dict

import aiohttp

MODEL = "nai-diffusion-4-5-full"
TIMEOUT = 180

# 待测字段：键是发出去的字段名，值是我们发的探测值。
# 返回的 Comment 里若该字段等于探测值 → 透传；若是 null/默认 → 被吞。
PROBE_FIELDS: Dict[str, Any] = {
    # Variety+ 的真实字段。3.9.8 改成发这个，但一直没验证过是否生效。
    "skip_cfg_above_sigma": 58,
    # 角色分区生成的开关。它决定上次砍掉的位置网格值不值得复活。
    "use_coords": True,
    # 这两个插件一直在发，用作对照组：它们要是也被吞，说明白名单极窄。
    "cfg_rescale": 0.7,
    "noise_schedule": "native",
}

BASE_PAYLOAD: Dict[str, Any] = {
    "prompt": "1girl, solo, twintails, best quality",
    "size": [832, 1216],
    "width": 832,
    "height": 1216,
    "steps": 28,
    "scale": 7.0,
    "sampler": "k_euler_ancestral",
    "image_format": "png",
    "n_samples": 1,
    "negative_prompt": "lowres, bad anatomy",
    # 两个角色，好让 use_coords 有意义
    "characters": [
        {"prompt": "1girl, red hair", "negative_prompt": "", "position": "B3"},
        {"prompt": "1girl, blue hair", "negative_prompt": "", "position": "D3"},
    ],
    "use_order": True,
}

SYSTEM_MESSAGE = (
    "You are an image generation endpoint. The JSON object in the user message "
    "is the authoritative NovelAI generation request. Preserve every field exactly. "
    "Generate one image and return image URL, markdown image, data URL, or base64."
)


def endpoint(api_base: str) -> str:
    base = api_base.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return f"{base}/chat/completions"


def extract_image_bytes(data: Any) -> bytes:
    """从响应里挖出第一张图的字节。base64 / data URL 两种形态都认。"""
    blob = json.dumps(data)

    for match in re.finditer(r"[A-Za-z0-9+/]{200,}={0,2}", blob):
        try:
            raw = base64.b64decode(match.group(0), validate=True)
        except Exception:
            continue
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return raw

    return b""


def read_comment(png: bytes) -> Dict[str, Any]:
    """读 PNG tEXt 里的 NovelAI Comment JSON。"""
    from PIL import Image

    with Image.open(BytesIO(png)) as image:
        raw = (image.info or {}).get("Comment")

    if not isinstance(raw, str):
        return {}

    try:
        parsed = json.loads(raw)
    except Exception:
        return {}

    return parsed if isinstance(parsed, dict) else {}


def lookup(comment: Dict[str, Any], field: str) -> Any:
    """字段可能在顶层，也可能落在 v4_prompt 里（use_coords 就是）。"""
    if field in comment:
        return comment[field]

    nested = comment.get("v4_prompt")
    if isinstance(nested, dict) and field in nested:
        return nested[field]

    return "<缺失>"


async def main() -> int:
    api_base = os.environ.get("BESTNAI_API_URL", "").strip()
    api_key = os.environ.get("BESTNAI_API_KEY", "").strip()

    if not api_base or not api_key:
        print("请先设置 BESTNAI_API_URL 与 BESTNAI_API_KEY", file=sys.stderr)
        return 2

    payload = {**BASE_PAYLOAD, **PROBE_FIELDS}
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_MESSAGE},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        "stream": False,
    }

    print(f"探测端点：{endpoint(api_base)}")
    print(f"发出字段：{', '.join(PROBE_FIELDS)}\n")

    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=TIMEOUT)
    ) as session:
        async with session.post(
            endpoint(api_base),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=body,
        ) as resp:
            text = await resp.text()

            if resp.status < 200 or resp.status >= 300:
                print(f"HTTP {resp.status}：{text[:500]}", file=sys.stderr)
                return 1

            try:
                data = json.loads(text)
            except Exception:
                print(f"返回非 JSON：{text[:500]}", file=sys.stderr)
                return 1

    png = extract_image_bytes(data)

    if not png:
        print("没能从响应里解析出 PNG，无法判定。原始响应前 800 字：", file=sys.stderr)
        print(text[:800], file=sys.stderr)
        return 1

    comment = read_comment(png)

    if not comment:
        print("返回的图里没有 Comment 元数据——网关很可能重新编码了图片，", file=sys.stderr)
        print("这条路探测不了，只能改用固定 seed 出两张图做像素比对。", file=sys.stderr)
        return 1

    print(f"{'字段':<24} {'发出值':<14} {'NAI 实收':<14} 结论")
    print("-" * 68)

    for field, sent in PROBE_FIELDS.items():
        got = lookup(comment, field)
        verdict = "✅ 透传" if got == sent else "❌ 被吞 / 被改写"
        print(f"{field:<24} {str(sent):<14} {str(got):<14} {verdict}")

    print(f"\n返回的 seed：{comment.get('seed', '<缺失>')}")
    print("完整 Comment 已写入 probe_comment.json")

    with open("probe_comment.json", "w", encoding="utf-8") as handle:
        json.dump(comment, handle, ensure_ascii=False, indent=2)

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

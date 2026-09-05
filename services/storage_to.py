"""storage.to 匿名图床上传。

storage.to 没有公开 API（/docs/api 被 Cloudflare 挡），以下链路由前端
upload-client 逆向得出，与网页版行为一致：

    POST /api/upload/init-batch   声明文件 -> 小文件直接返回 R2 presigned 直传地址
    PUT   <presigned url>         上传原图（网络不稳需重试）
    POST /api/upload/confirm-batch 确认 -> 返回最终短链与过期时间

全程匿名（X-Visitor-Token 只是前端生成的随机标识，服务端不校验身份）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional, Tuple

import aiohttp

logger = logging.getLogger("astrbot")

STORAGE_TO_BASE = "https://storage.to"

# NAS 国际链路间歇丢包（实测 SSL 中途断连），PUT 直传必须重试
UPLOAD_PUT_RETRIES = 5
UPLOAD_PUT_RETRY_DELAY = 3.0

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
}


class StorageToError(Exception):
    """storage.to 上传失败。"""


def _content_type_for(fmt: str) -> str:
    ext = (fmt or "").lower().lstrip(".")
    return CONTENT_TYPES.get(ext, "application/octet-stream")


async def upload_image_to_storage(
    data: bytes,
    filename: str,
    content_type: str = "",
    proxy: Optional[str] = None,
) -> Tuple[str, str]:
    """上传单张图片到 storage.to。

    Args:
        data: 图片原始字节。
        filename: 展示用文件名（影响落地页标题）。
        content_type: 缺省按文件扩展名推断。
        proxy: http 代理地址，留空直连（NAS 直连不通时需走代理）。

    Returns:
        (最终短链 URL, 过期时间 ISO 字符串)。

    Raises:
        StorageToError: 任一环节失败。
    """
    if not data:
        raise StorageToError("图片内容为空，无法上传")

    content_type = content_type or _content_type_for(filename.rsplit(".", 1)[-1])
    token = uuid.uuid4().hex
    json_headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Visitor-Token": token,
    }

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=90)) as session:
            # 1) 声明文件，拿直传地址
            try:
                async with session.post(
                    f"{STORAGE_TO_BASE}/api/upload/init-batch",
                    headers=json_headers,
                    json={
                        "files": [
                            {
                                "filename": filename,
                                "content_type": content_type,
                                "size": len(data),
                            }
                        ]
                    },
                    proxy=proxy,
                ) as resp:
                    init_body = await resp.json(content_type=None)
            except Exception as e:  # noqa: BLE001
                raise StorageToError(
                    f"init-batch 请求失败: {type(e).__name__}: {str(e)[:150]}"
                ) from e

            r0 = (init_body.get("results") or {}).get("0") or {}
            if not r0.get("success") or not r0.get("upload_url"):
                raise StorageToError(
                    "init-batch 未返回直传地址: "
                    + json.dumps(init_body, ensure_ascii=False)[:250]
                )
            upload_url = r0["upload_url"]
            r2_key = str(r0.get("r2_key") or "")

            # 2) PUT 直传（间歇性 SSL 断连，失败重试）
            put_ok = False
            put_status = 0
            for attempt in range(1, UPLOAD_PUT_RETRIES + 1):
                try:
                    async with session.put(
                        upload_url,
                        data=data,
                        headers={"Content-Type": content_type},
                        proxy=proxy,
                        timeout=aiohttp.ClientTimeout(total=150),
                    ) as resp:
                        put_status = resp.status
                        if resp.status in (200, 201, 204):
                            put_ok = True
                            break
                        text = (await resp.text()).strip()
                    logger.warning(
                        "[BestNAI/StorageTo] PUT 第 %d 次 HTTP %d: %s",
                        attempt,
                        put_status,
                        text[:150],
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(
                        "[BestNAI/StorageTo] PUT 第 %d 次失败: %s",
                        attempt,
                        type(e).__name__,
                    )
                if attempt < UPLOAD_PUT_RETRIES:
                    await asyncio.sleep(UPLOAD_PUT_RETRY_DELAY)
            if not put_ok:
                raise StorageToError(
                    f"上传直传地址多次失败（最后 HTTP {put_status}，网络不稳）"
                )

            # 3) 确认并取回最终链接
            try:
                async with session.post(
                    f"{STORAGE_TO_BASE}/api/upload/confirm-batch",
                    headers=json_headers,
                    json={
                        "files": [
                            {
                                "filename": filename,
                                "size": len(data),
                                "content_type": content_type,
                                "r2_key": r2_key,
                            }
                        ],
                        "upload_speed": None,
                    },
                    proxy=proxy,
                ) as resp:
                    confirm_body = await resp.json(content_type=None)
            except Exception as e:  # noqa: BLE001
                raise StorageToError(
                    f"confirm 请求失败: {type(e).__name__}: {str(e)[:150]}"
                ) from e

            res0 = (confirm_body.get("results") or {}).get("0") or {}
            file_info = res0.get("file") or {}
            if not res0.get("success") or not file_info.get("url"):
                raise StorageToError(
                    "confirm 未返回链接: "
                    + json.dumps(confirm_body, ensure_ascii=False)[:250]
                )
            return str(file_info["url"]), str(file_info.get("expires_at") or "")
    except aiohttp.ClientError as e:
        raise StorageToError(f"网络错误: {type(e).__name__}: {str(e)[:150]}") from e

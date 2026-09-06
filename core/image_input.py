from __future__ import annotations

import asyncio
import base64
import binascii
import re
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import url2pathname

import aiohttp
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 30_000_000
VISION_MAX_SIDE = 2048
VISION_MAX_BYTES = 8 * 1024 * 1024
MAX_ANIMATION_FRAME_SCAN = 12
FORMAT_EXTENSIONS = {
    "PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp", "GIF": ".gif",
    "BMP": ".bmp", "TIFF": ".tiff", "ICO": ".ico", "AVIF": ".avif",
}
IMAGE_MIME_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".webp": "image/webp", ".gif": "image/gif", ".bmp": "image/bmp",
    ".tif": "image/tiff", ".tiff": "image/tiff", ".ico": "image/x-icon",
    ".avif": "image/avif",
}
SUPPORTED_FORMATS_TEXT = "PNG、JPEG、WebP、GIF、BMP、TIFF、ICO 和 AVIF"


class ImageInputError(ValueError):
    """A user-readable failure before any vision-provider request is made."""


def _check_data_size(data: bytes) -> bytes:
    if not data:
        raise ImageInputError("图片内容为空，请重新发送或上传图片")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageInputError("图片不能超过 15 MB")
    return data


def _read_local_bytes(source: str) -> bytes:
    if source.lower().startswith("file://"):
        parsed = urlsplit(source.replace("\\", "/"))
        source = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            source = (
                parsed.netloc + source
                if re.fullmatch(r"[A-Za-z]:", parsed.netloc)
                else f"//{parsed.netloc}{source}"
            )
    try:
        with Path(source).open("rb") as handle:
            return _check_data_size(handle.read(MAX_IMAGE_BYTES + 1))
    except FileNotFoundError as exc:
        raise ImageInputError("图片文件不存在，请重新发送或上传图片") from exc
    except OSError as exc:
        raise ImageInputError("无法读取图片文件，请重新上传图片") from exc


def _decode_base64_image(source: str) -> bytes:
    if source.lower().startswith("base64://"):
        encoded = source[9:]
    else:
        header, separator, encoded = source.partition(",")
        if not separator or not header.lower().endswith(";base64"):
            raise ImageInputError("图片 Data URL 必须使用 Base64 编码")
    # Check the encoded length before allocating a decoded copy.
    if len(encoded) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ImageInputError("图片不能超过 15 MB")
    try:
        return _check_data_size(base64.b64decode(encoded, validate=True))
    except (binascii.Error, ValueError) as exc:
        if isinstance(exc, ImageInputError):
            raise
        raise ImageInputError("图片 Base64 数据无效，请重新发送或上传图片") from exc


async def read_image_bytes(source: str | Path) -> bytes:
    """Read original bytes with the same limit for QQ, uploads and inline images.

    Content-Type and filename extensions are deliberately not trusted. Only
    generic image-download headers are sent; provider credentials stay with
    AstrBot's provider adapter.
    """
    value = str(source or "").strip()
    if not value:
        raise ImageInputError("图片为空")
    lowered = value.lower()
    if lowered.startswith(("data:", "base64://")):
        return await asyncio.to_thread(_decode_base64_image, value)
    if not lowered.startswith(("http://", "https://")):
        return await asyncio.to_thread(_read_local_bytes, value)

    try:
        timeout = aiohttp.ClientTimeout(total=45)
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*;q=0.1"}
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(value, headers=headers) as response:
                if response.status < 200 or response.status >= 300:
                    raise ImageInputError(
                        f"下载图片失败（HTTP {response.status}），链接可能已失效或被拦截，请重新发送图片"
                    )
                if response.content_length and response.content_length > MAX_IMAGE_BYTES:
                    raise ImageInputError("图片不能超过 15 MB")
                data = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    if len(data) + len(chunk) > MAX_IMAGE_BYTES:
                        raise ImageInputError("图片不能超过 15 MB")
                    data.extend(chunk)
        return _check_data_size(bytes(data))
    except ImageInputError:
        raise
    except (asyncio.TimeoutError, TimeoutError) as exc:
        raise ImageInputError("下载图片超时，请重新发送图片或检查网络连接") from exc
    except aiohttp.ClientError as exc:
        # URLs can contain temporary QQ credentials; do not echo them in errors.
        raise ImageInputError("下载图片失败，请检查网络连接或重新发送图片") from exc


def _check_dimensions(image: Image.Image) -> None:
    width, height = image.size
    if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
        raise ImageInputError("图片尺寸无效或像素数超过 3000 万限制")


def _read_static_frame(
    data: bytes, *, max_side: int | None = None,
) -> tuple[Image.Image, str, int, tuple[int, int]]:
    """Decode a detached RGB(A) frame, preserving the original file and metadata."""
    _check_data_size(data)
    try:
        with Image.open(BytesIO(data)) as original:
            source_format = str(original.format or "").upper()
            if source_format not in FORMAT_EXTENSIONS:
                raise ImageInputError(f"仅支持 {SUPPORTED_FORMATS_TEXT} 图片")
            _check_dimensions(original)
            original.verify()
        # verify() consumes some decoders, and is not a substitute for load().
        with Image.open(BytesIO(data)) as original:
            original_size = original.size
            if original.getexif().get(274) in {5, 6, 7, 8}:
                original_size = (original.height, original.width)
            if max_side:
                original.draft("RGB", (max_side, max_side))
            frame_index = 0
            # For animations, skip fully transparent opening frames. Seek in
            # order so Pillow applies the GIF/WebP disposal/compositing rules.
            # TIFF is a document: always use its first page, even if transparent.
            scan_limit = MAX_ANIMATION_FRAME_SCAN if source_format in {"GIF", "PNG", "WEBP", "AVIF"} else 1
            for index in range(scan_limit):
                try:
                    original.seek(index)
                except EOFError:
                    break
                _check_dimensions(original)
                original.load()
                visible = True
                if "A" in original.getbands() or "transparency" in original.info:
                    with original.convert("RGBA") as rgba:
                        visible = rgba.getchannel("A").getbbox() is not None
                frame_index = index
                if visible:
                    break
            original.seek(frame_index)
            frame = ImageOps.exif_transpose(original)
            if frame.mode.startswith("I;16"):
                # Direct I;16 -> RGB conversion clips values above 255 to
                # white. Preserve the full 16-bit tonal range before RGB.
                with frame.convert("I") as integer_frame:
                    normalized = integer_frame.point(lambda value: value * (255 / 65535)).convert("L")
                frame.close()
                frame = normalized
            has_alpha = "A" in frame.getbands() or "transparency" in frame.info
            mode = "RGBA" if has_alpha else "RGB"
            if frame.mode != mode:
                converted = frame.convert(mode)
                frame.close()
                frame = converted
            # Do not copy PNG text, EXIF or ICC blobs into the provider payload.
            frame.info.clear()
            return frame, source_format, frame_index, original_size
    except ImageInputError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageInputError("图片尺寸无效或像素数超过 3000 万限制") from exc
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        if b"ftyp" in data[:16]:
            brands = data[8:64].lower()
            if b"avif" in brands or b"avis" in brands:
                raise ImageInputError("无法解码 AVIF 图片，请升级 Pillow 或先转换为 PNG/JPEG") from exc
            if any(brand in brands for brand in (b"heic", b"heix", b"heif", b"mif1")):
                raise ImageInputError("当前环境不支持 HEIC/HEIF，请先转换为 PNG/JPEG") from exc
        raise ImageInputError(
            "内容不是有效图片或图片已损坏；链接可能返回了网页或错误内容，请重新发送或上传图片"
        ) from exc


def inspect_image(data: bytes) -> tuple[str, int, int]:
    frame, source_format, _, _ = _read_static_frame(data)
    try:
        return source_format, frame.width, frame.height
    finally:
        frame.close()


@dataclass(frozen=True)
class StaticImage:
    data: bytes
    source_format: str
    original_size: tuple[int, int]
    size: tuple[int, int]
    frame_index: int


def static_png(
    data: bytes,
    *,
    max_side: int = VISION_MAX_SIDE,
    max_bytes: int = VISION_MAX_BYTES,
) -> StaticImage:
    frame, source_format, frame_index, original_size = _read_static_frame(data, max_side=max_side)
    try:
        frame.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        while True:
            output = BytesIO()
            frame.save(output, format="PNG")
            encoded = output.getvalue()
            if len(encoded) <= max_bytes:
                return StaticImage(encoded, source_format, original_size, frame.size, frame_index)
            if max(frame.size) <= 64:
                raise ImageInputError("图片转换后仍超过接口大小限制，请缩小图片后重试")
            frame.thumbnail(
                (max(1, int(frame.width * 0.75)), max(1, int(frame.height * 0.75))),
                Image.Resampling.LANCZOS,
            )
    finally:
        frame.close()


@asynccontextmanager
async def vision_image_path(source: str | Path):
    """Keep a validated static PNG alive until the awaited provider call finishes."""
    data = await read_image_bytes(source)
    prepared = await asyncio.to_thread(static_png, data)
    with tempfile.TemporaryDirectory(prefix="bestnai-retag-") as temporary:
        path = Path(temporary) / "image.png"
        path.write_bytes(prepared.data)
        yield str(path)

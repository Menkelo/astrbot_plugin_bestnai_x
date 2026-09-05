"""小番茄混淆兼容实现。

算法与 https://xiaofanqiehunxiao.com/ 使用的前端实现一致：沿 Gilbert
Curve 遍历像素，并以黄金比例偏移量进行可逆置换。结果编码为无损 PNG，
并搬运 NovelAI 元数据到 PNG tEXt 块，方便继续读取。
"""

from __future__ import annotations

import json
from array import array
from io import BytesIO
from math import floor, sqrt

from PIL import ExifTags, Image, PngImagePlugin


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def _gilbert_curve(width: int, height: int) -> tuple[array, array]:
    """Generate Gilbert Curve coordinates in the website's order."""
    xs: array = array("i")
    ys: array = array("i")

    def append_line(x: int, y: int, dx: int, dy: int, length: int) -> None:
        sx = _sign(dx)
        sy = _sign(dy)
        for _ in range(length):
            xs.append(x)
            ys.append(y)
            x += sx
            y += sy

    def walk(x: int, y: int, dx: int, dy: int, ax: int, ay: int) -> None:
        major = abs(dx + dy)
        minor = abs(ax + ay)
        sx = _sign(dx)
        sy = _sign(dy)
        sax = _sign(ax)
        say = _sign(ay)

        if minor == 1:
            append_line(x, y, dx, dy, major)
            return
        if major == 1:
            append_line(x, y, ax, ay, minor)
            return

        half_dx = floor(dx / 2)
        half_dy = floor(dy / 2)
        half_ax = floor(ax / 2)
        half_ay = floor(ay / 2)
        half_major = abs(half_dx + half_dy)
        half_minor = abs(half_ax + half_ay)

        if 2 * major > 3 * minor:
            if half_major % 2 and major > 2:
                half_dx += sx
                half_dy += sy
            walk(x, y, half_dx, half_dy, ax, ay)
            walk(x + half_dx, y + half_dy, dx - half_dx, dy - half_dy, ax, ay)
            return

        if half_minor % 2 and minor > 2:
            half_ax += sax
            half_ay += say
        walk(x, y, half_ax, half_ay, half_dx, half_dy)
        walk(x + half_ax, y + half_ay, dx, dy, ax - half_ax, ay - half_ay)
        walk(
            x + (dx - sx) + (half_ax - sax),
            y + (dy - sy) + (half_ay - say),
            -half_ax,
            -half_ay,
            -(dx - half_dx),
            -(dy - half_dy),
        )

    if width >= height:
        walk(0, 0, width, 0, 0, height)
    else:
        walk(0, 0, 0, height, width, 0)

    return xs, ys


def obfuscate_image_bytes(image_bytes: bytes, key: float = 1.0) -> bytes:
    """Apply the Xiaofanqie pixel permutation and return metadata-bearing PNG."""
    if not image_bytes:
        raise ValueError("图片内容为空，无法混淆")

    try:
        key = float(key)
    except (TypeError, ValueError):
        key = 1.0
    if not 0 < key < 1.618:
        raise ValueError("小番茄混淆密钥必须大于 0 且小于 1.618")

    with Image.open(BytesIO(image_bytes)) as source:
        source.load()
        width, height = source.size
        total = width * height
        xs, ys = _gilbert_curve(width, height)
        if len(xs) != total:
            raise ValueError("Gilbert 曲线像素数量与图片尺寸不一致")

        has_alpha = "A" in source.getbands()
        source_pixels = source.convert("RGBA" if has_alpha else "RGB")
        pixels = source_pixels.load()
        output = Image.new(source_pixels.mode, (width, height))
        output_pixels = output.load()
        # JavaScript Math.round / Java Math.round round positive half values up;
        # Python round uses bankers rounding, so spell out the equivalent.
        offset = floor(((sqrt(5) - 1) / 2) * total * key + 0.5)

        for index in range(total):
            src_x = xs[index]
            src_y = ys[index]
            dst_index = (index + offset) % total
            output_pixels[xs[dst_index], ys[dst_index]] = pixels[src_x, src_y]

        encoded = BytesIO()
        pnginfo = PngImagePlugin.PngInfo()
        for name, value in source.info.items():
            if name in {"Comment", "icc_profile", "exif", "transparency"}:
                continue
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            if isinstance(value, str) and value:
                pnginfo.add_text(str(name), value)

        metadata = source.info.get("Comment")
        if isinstance(metadata, bytes):
            metadata = metadata.decode("utf-8", errors="ignore")
        if isinstance(metadata, str) and metadata.strip():
            try:
                json.loads(metadata)
            except Exception:
                metadata = ""

        # Carry an existing JPEG/WebP EXIF UserComment into PNG Comment.
        exif = source.getexif()
        if not metadata:
            try:
                user_comment = exif.get_ifd(ExifTags.IFD.Exif).get(
                    ExifTags.Base.UserComment
                )
                metadata = (
                    user_comment.decode("utf-8", errors="ignore")
                    if isinstance(user_comment, bytes)
                    else str(user_comment or "")
                )
            except Exception:
                metadata = ""
        if metadata:
            try:
                json.loads(metadata)
                pnginfo.add_text("Comment", metadata)
            except Exception:
                pass

        output.save(encoded, format="PNG", pnginfo=pnginfo, compress_level=0)
        return encoded.getvalue()


def deobfuscate_image_bytes(image_bytes: bytes, key: float = 1.0) -> bytes:
    """逆置换：把 Gilbert Curve 混淆过的 PNG 还原为原图。

    混淆时 output[curve[i + offset]] = source[curve[i]]，
    因此还原时 output[curve[i]] = input[curve[i + offset]]。
    与 obfuscate_image_bytes 使用同一把密钥（插件发送副本固定 key=1.0，
    与小番茄网页版默认一致），输出无损 PNG 并保留 NovelAI 元数据。
    """
    if not image_bytes:
        raise ValueError("图片内容为空，无法解混淆")

    try:
        key = float(key)
    except (TypeError, ValueError):
        key = 1.0
    if not 0 < key < 1.618:
        raise ValueError("小番茄混淆密钥必须大于 0 且小于 1.618")

    with Image.open(BytesIO(image_bytes)) as source:
        source.load()
        width, height = source.size
        total = width * height
        xs, ys = _gilbert_curve(width, height)
        if len(xs) != total:
            raise ValueError("Gilbert 曲线像素数量与图片尺寸不一致")

        has_alpha = "A" in source.getbands()
        source_pixels = source.convert("RGBA" if has_alpha else "RGB")
        pixels = source_pixels.load()
        output = Image.new(source_pixels.mode, (width, height))
        output_pixels = output.load()
        offset = floor(((sqrt(5) - 1) / 2) * total * key + 0.5)

        for index in range(total):
            dst_x = xs[index]
            dst_y = ys[index]
            src_index = (index + offset) % total
            output_pixels[dst_x, dst_y] = pixels[xs[src_index], ys[src_index]]

        encoded = BytesIO()
        pnginfo = PngImagePlugin.PngInfo()
        for name, value in source.info.items():
            if name in {"Comment", "icc_profile", "exif", "transparency"}:
                continue
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            if isinstance(value, str) and value:
                pnginfo.add_text(str(name), value)

        metadata = source.info.get("Comment")
        if isinstance(metadata, bytes):
            metadata = metadata.decode("utf-8", errors="ignore")
        if isinstance(metadata, str) and metadata.strip():
            try:
                json.loads(metadata)
            except Exception:
                metadata = ""
        if metadata:
            try:
                json.loads(metadata)
                pnginfo.add_text("Comment", metadata)
            except Exception:
                pass

        output.save(encoded, format="PNG", pnginfo=pnginfo, compress_level=0)
        return encoded.getvalue()

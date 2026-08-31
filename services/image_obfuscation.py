"""本地图片混淆工具。

混淆只作用于发送副本，不会修改生成结果在内存中的原始字节。使用 Pillow
把图像缩小后再用最近邻插值放大，形成稳定的马赛克效果，不依赖外部网站，
也不会把图片传出当前进程。
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image


def obfuscate_image_bytes(image_bytes: bytes, block_size: int = 16) -> bytes:
    """Return a pixelated copy of an image.

    ``block_size`` is the approximate size of one mosaic block in pixels. The
    alpha channel is preserved for images that have transparency.
    """
    if not image_bytes:
        raise ValueError("图片内容为空，无法混淆")

    try:
        block = max(2, min(int(block_size), 128))
    except (TypeError, ValueError):
        block = 16

    with Image.open(BytesIO(image_bytes)) as source:
        source.load()
        has_alpha = "A" in source.getbands()
        if has_alpha:
            image = source.convert("RGBA")
        else:
            image = source.convert("RGB")

        small_width = max(1, (image.width + block - 1) // block)
        small_height = max(1, (image.height + block - 1) // block)
        pixelated = image.resize(
            (small_width, small_height),
            resample=Image.Resampling.BOX,
        ).resize(
            image.size,
            resample=Image.Resampling.NEAREST,
        )

        output = BytesIO()
        output_format = (source.format or "PNG").upper()
        if output_format == "JPG":
            output_format = "JPEG"
        save_kwargs = {}
        if output_format == "JPEG":
            # JPEG cannot encode alpha; flatten transparencies against white.
            if pixelated.mode == "RGBA":
                background = Image.new("RGB", pixelated.size, "white")
                background.paste(pixelated, mask=pixelated.getchannel("A"))
                pixelated = background
            save_kwargs = {"quality": 95, "optimize": True}
        elif output_format not in {"PNG", "WEBP", "GIF", "BMP", "TIFF"}:
            output_format = "PNG"

        pixelated.save(output, format=output_format, **save_kwargs)
        return output.getvalue()


import os

try:
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


COPYRIGHT_FONT_SIZE_1 = 60
COPYRIGHT_FONT_SIZE_2 = 40
COPYRIGHT_SAFE_HEIGHT = 180

GAP = 8
MASONRY_COL_W = 220
MASONRY_TITLE_H = 34
MASONRY_CARD_PAD = 6
MASONRY_MIN_IMG_H = 90
MASONRY_MAX_IMG_H = 360
BOTTOM_PAD = 20

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
]


def _log(msg: str):
    print(f"[BestNAI.gallery_renderer] {msg}")


def _get_font(size: int):
    if not PIL_AVAILABLE:
        _log("Pillow 不可用，无法加载字体")
        return None

    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                f = ImageFont.truetype(p, size=size)
                _log(f"字体加载成功: path={p}, size={size}")
                return f
            except Exception as e:
                _log(f"字体加载失败: path={p}, size={size}, err={e}")

    _log(f"所有候选字体不可用，回退默认字体，size请求={size}")

    try:
        return ImageFont.load_default()
    except Exception as e:
        _log(f"load_default失败: {e}")
        return None


def _fit_text(draw: "ImageDraw.ImageDraw", text: str, font, max_w: int) -> str:
    if not text:
        return ""

    t = text

    while t:
        bbox = draw.textbbox((0, 0), t, font=font)

        if (bbox[2] - bbox[0]) <= max_w:
            return t

        t = t[:-1]

    return ""


def _normalize_local_path(preview: str) -> str:
    if not preview:
        return ""

    p = preview[7:] if preview.lower().startswith("file://") else preview
    p = os.path.abspath(p)

    return p if os.path.exists(p) else ""


def _draw_top_copyright(draw, canvas_w: int, font_big, font_small):
    line1 = "Menkelo"
    line2 = "astrbot_plugin_bestnai_x"

    f1 = font_big
    f2 = font_small or font_big

    safe_h = COPYRIGHT_SAFE_HEIGHT
    left = 16
    line_gap = 8

    b1 = draw.textbbox((0, 0), line1, font=f1)
    b2 = draw.textbbox((0, 0), line2, font=f2)

    h1 = b1[3] - b1[1]
    h2 = b2[3] - b2[1]

    block_h = h1 + line_gap + h2
    top_y = max(0, (safe_h - block_h) // 2)

    y1 = top_y
    y2 = y1 + h1 + line_gap

    draw.text((left, y1), line1, fill=(95, 95, 95), font=f1)
    draw.text((left, y2), line2, fill=(120, 120, 120), font=f2)

    return safe_h


def _build_masonry(
    keys,
    preview_map,
    output_dir,
    cols=5,
    bottom_pad=BOTTOM_PAD,
    output_name="artist_gallery.jpg",
):
    gap = GAP
    col_w = MASONRY_COL_W
    title_h = MASONRY_TITLE_H
    card_pad = MASONRY_CARD_PAD
    min_img_h = MASONRY_MIN_IMG_H
    max_img_h = MASONRY_MAX_IMG_H

    canvas_w = cols * col_w + (cols + 1) * gap

    font = _get_font(22)
    small_font = _get_font(18)
    top_font = _get_font(COPYRIGHT_FONT_SIZE_1)
    top_small = _get_font(COPYRIGHT_FONT_SIZE_2)

    content_start_y = COPYRIGHT_SAFE_HEIGHT
    col_heights = [content_start_y + gap for _ in range(cols)]
    placements = []

    for key in keys:
        p = _normalize_local_path(preview_map.get(key, ""))

        if p:
            try:
                with Image.open(p) as im:
                    w, h = im.size

                h_img = int((col_w - card_pad * 2) * (h / max(w, 1)))
            except Exception:
                h_img = 160
        else:
            h_img = 140

        h_img = max(min_img_h, min(max_img_h, h_img))
        h_card = card_pad + h_img + 6 + title_h + card_pad

        c = min(range(cols), key=lambda i: col_heights[i])
        x = gap + c * (col_w + gap)
        y = col_heights[c]

        placements.append((key, x, y, col_w, h_img, h_card, p))

        col_heights[c] += h_card + gap

    canvas_h = max(col_heights) + bottom_pad
    bg = Image.new("RGB", (canvas_w, canvas_h), (235, 235, 235))
    draw = ImageDraw.Draw(bg)

    _draw_top_copyright(draw, canvas_w, top_font or font, top_small or small_font or font)

    for key, x, y, w, h_img, h_card, p in placements:
        draw.rectangle(
            [x, y, x + w, y + h_card],
            fill=(245, 245, 245),
            outline=(175, 175, 175),
            width=2,
        )

        ix1, iy1 = x + card_pad, y + card_pad
        ix2, iy2 = x + w - card_pad, y + card_pad + h_img

        draw.rectangle(
            [ix1, iy1, ix2, iy2],
            fill=(225, 225, 225),
            outline=(190, 190, 190),
            width=1,
        )

        pasted = False

        if p:
            try:
                with Image.open(p).convert("RGB") as im:
                    fitted = ImageOps.contain(im, (ix2 - ix1, iy2 - iy1))
                    px = ix1 + ((ix2 - ix1) - fitted.width) // 2
                    py = iy1 + ((iy2 - iy1) - fitted.height) // 2
                    bg.paste(fitted, (px, py))
                    pasted = True
            except Exception:
                pasted = False

        if not pasted:
            mark = "NO PREVIEW"
            f = small_font or font
            bbox = draw.textbbox((0, 0), mark, font=f)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(
                (
                    ix1 + (ix2 - ix1 - tw) // 2,
                    iy1 + (iy2 - iy1 - th) // 2,
                ),
                mark,
                fill=(140, 140, 140),
                font=f,
            )

        tfont = small_font or font
        title = _fit_text(draw, key, tfont, w - 10)
        bbox = draw.textbbox((0, 0), title, font=tfont)
        tw, _th = bbox[2] - bbox[0], bbox[3] - bbox[1]

        draw.text(
            (x + (w - tw) // 2, iy2 + 8),
            title,
            fill=(35, 35, 35),
            font=tfont,
        )

    out = os.path.join(output_dir, output_name)
    bg.save(out, quality=92)
    _log(f"画廊生成完成: {out}")

    return out


def build_gallery_image(
    presets: dict,
    preview_map: dict,
    output_dir: str,
    sort_key,
    mode: str = "masonry",
    cols: int = 5,
    max_count: int = 999999,
    safe_top: int = 0,
    safe_bottom: int = 0,
    output_name: str = "artist_gallery.jpg",
) -> str:
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow 未安装")

    os.makedirs(output_dir, exist_ok=True)

    keys = sorted(list(presets.keys()), key=sort_key)

    if max_count > 0:
        keys = keys[:max_count]

    if not keys:
        raise RuntimeError("无预设可展示")

    cols = max(1, min(int(cols), 10))

    _log(
        f"开始生成画廊: mode=masonry, cols={cols}, max_count={max_count}, "
        f"copyright_sizes=({COPYRIGHT_FONT_SIZE_1},{COPYRIGHT_FONT_SIZE_2}), "
        f"safe_h={COPYRIGHT_SAFE_HEIGHT}"
    )

    return _build_masonry(
        keys=keys,
        preview_map=preview_map,
        output_dir=output_dir,
        cols=cols,
        bottom_pad=BOTTOM_PAD,
        output_name=output_name,
    )

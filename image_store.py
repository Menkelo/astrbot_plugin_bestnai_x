import os
import hashlib
import urllib.request
import urllib.parse


def _safe_ext_from_name(name: str) -> str:
    ext = os.path.splitext(name)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
        return ext
    return ".png"


def local_path_from_any(image: str) -> str:
    if not image:
        return ""

    img = image.strip()
    low = img.lower()

    if low.startswith("file://"):
        p = img[7:]
    elif low.startswith("http://") or low.startswith("https://"):
        return ""
    else:
        p = img

    p = p.replace("\\", "/")

    while p.startswith("//"):
        p = p[1:]

    if not os.path.isabs(p):
        p = os.path.abspath(p)

    return p


def persist_preview_image(image: str, preview_dir: str) -> str:
    """
    统一持久化为本地文件，返回本地绝对路径。
    - http/https: 下载
    - file:// / 本地路径: 复制
    """
    img = (image or "").strip()

    if not img:
        return ""

    os.makedirs(preview_dir, exist_ok=True)

    try:
        low = img.lower()

        if low.startswith("http://") or low.startswith("https://"):
            parsed = urllib.parse.urlparse(img)
            ext = _safe_ext_from_name(parsed.path or "")
            file_id = hashlib.md5(img.encode("utf-8")).hexdigest()[:16]
            dst = os.path.join(preview_dir, f"preview_{file_id}{ext}")

            with urllib.request.urlopen(img, timeout=20) as resp:
                data = resp.read()

            with open(dst, "wb") as f:
                f.write(data)

            return os.path.abspath(dst)

        src = img[7:] if low.startswith("file://") else img
        src = src.replace("\\", "/")

        while src.startswith("//"):
            src = src[1:]

        if not os.path.isabs(src):
            src = os.path.abspath(src)

        if not os.path.exists(src):
            return ""

        ext = _safe_ext_from_name(src)
        file_id = hashlib.md5(
            (src + str(os.path.getmtime(src))).encode("utf-8")
        ).hexdigest()[:16]

        dst = os.path.join(preview_dir, f"preview_{file_id}{ext}")

        with open(src, "rb") as rf, open(dst, "wb") as wf:
            wf.write(rf.read())

        return os.path.abspath(dst)

    except Exception:
        return ""


def to_cq_image(image: str) -> str:
    img = (image or "").strip()

    if not img:
        return ""

    low = img.lower()

    if low.startswith("http://") or low.startswith("https://") or low.startswith("file://"):
        file_part = img
    else:
        abs_path = os.path.abspath(img).replace("\\", "/")

        if not abs_path.startswith("/"):
            abs_path = "/" + abs_path

        file_part = f"file://{abs_path}"

    file_part = file_part.replace(",", "%2C")

    return f"[CQ:image,file={file_part}]"


async def send_image_best_effort(event, image: str):
    """
    通用发图：
    1) raw_result(CQ)
    2) image_result
    3) plain_result(CQ)
    """
    img = (image or "").strip()

    if not img:
        yield event.plain_result("❌ 图片为空")
        return

    p = local_path_from_any(img)

    if p and (not os.path.exists(p)):
        yield event.plain_result("⚠️ 图片文件不存在")
        return

    cq = to_cq_image(img)

    raw_result_fn = getattr(event, "raw_result", None)

    if callable(raw_result_fn):
        try:
            yield raw_result_fn(cq)
            return
        except Exception:
            pass

    image_result_fn = getattr(event, "image_result", None)

    if callable(image_result_fn):
        try:
            yield image_result_fn(img)
            return
        except Exception:
            pass

    yield event.plain_result(cq)

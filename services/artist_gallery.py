from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Dict, Tuple

from astrbot.api import logger

from ..gallery_renderer import PIL_AVAILABLE, build_gallery_image
from ..image_store import persist_preview_image


PLUGIN_NAME = "astrbot_plugin_bestnai_x"


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def get_astrbot_plugin_data_dir(plugin_name: str) -> Path:
    current = Path(__file__).resolve()

    for parent in current.parents:
        if parent.name == "data":
            return parent / "plugin_data" / plugin_name

    return current.parents[3] / "data" / "plugin_data" / plugin_name


class ArtistGalleryService:
    def __init__(self, plugin_name: str = PLUGIN_NAME) -> None:
        self.plugin_name = plugin_name

        self.plugin_data_dir = get_astrbot_plugin_data_dir(plugin_name)
        self.artist_preview_dir = self.plugin_data_dir / "artist_previews"
        self.artist_gallery_dir = self.plugin_data_dir / "artist_gallery"

        ensure_dir(self.plugin_data_dir)
        ensure_dir(self.artist_preview_dir)
        ensure_dir(self.artist_gallery_dir)

        self.artist_preview_config_path = self.plugin_data_dir / "artist_preview_map.json"
        self.artist_preview_map: Dict[str, str] = {}

        self.load_preview_map()

    @staticmethod
    def is_cjk(ch: str) -> bool:
        code = ord(ch)
        return (0x4E00 <= code <= 0x9FFF) or (0x3400 <= code <= 0x4DBF)

    def key_sort_tuple(self, text: str):
        s = (text or "").strip()

        if not s:
            return (3, "")

        first = s[0]

        if self.is_cjk(first):
            return (0, s)

        if first.isalpha() and first.isascii():
            return (1, s.lower())

        return (2, s.lower())

    def load_preview_map(self) -> None:
        self.artist_preview_map = {}

        try:
            if self.artist_preview_config_path.exists():
                with open(self.artist_preview_config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if isinstance(data, dict):
                    for k, v in data.items():
                        if isinstance(k, str) and isinstance(v, str) and k.strip() and v.strip():
                            self.artist_preview_map[k.strip()] = v.strip()

        except Exception as e:
            logger.warning(f"[BestNAI] 读取画师预览配置失败: {e}")

    def save_preview_map(self) -> bool:
        try:
            ensure_dir(self.plugin_data_dir)

            with open(self.artist_preview_config_path, "w", encoding="utf-8") as f:
                json.dump(
                    self.artist_preview_map,
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

            return True

        except Exception as e:
            logger.error(f"[BestNAI] 保存画师预览配置失败: {e}")
            return False

    def gallery_image_path(self) -> str:
        return str(self.artist_gallery_dir / "artist_gallery.jpg")

    def gallery_meta_path(self) -> str:
        return str(self.artist_gallery_dir / "gallery_meta.json")

    def calc_fingerprint(self, presets: Dict[str, str]) -> str:
        keys = sorted(presets.keys(), key=self.key_sort_tuple)

        items = [f"mode=masonry|cols=5|max=all|plugin={self.plugin_name}"]

        for k in keys:
            prompt = presets.get(k, "")
            p = self.artist_preview_map.get(k, "")
            p_abs = os.path.abspath(p) if p else ""

            if p_abs and os.path.exists(p_abs):
                st = os.stat(p_abs)
                sig = f"{st.st_mtime_ns}:{st.st_size}"
            else:
                sig = "no_file"

            items.append(f"{k}\n{prompt}\n{p_abs}\n{sig}")

        raw = "\n---\n".join(items).encode("utf-8", errors="ignore")

        return hashlib.md5(raw).hexdigest()

    def record_preview(self, real_key: str, image: str) -> bool:
        if not real_key or not image:
            return False

        stable = persist_preview_image(image, str(self.artist_preview_dir))

        if not stable:
            return False

        self.artist_preview_map[real_key] = stable

        return self.save_preview_map()

    def build_or_get_gallery(self, presets: Dict[str, str]) -> Tuple[bool, str]:
        """
        Returns:
            (ok, image_path_or_error)
        """
        if not PIL_AVAILABLE:
            return False, "未安装 Pillow，请先安装: pip install pillow"

        if not presets:
            return False, "当前没有画师预设"

        ensure_dir(self.artist_gallery_dir)

        img_path = self.gallery_image_path()
        meta_path = self.gallery_meta_path()

        fp_now = self.calc_fingerprint(presets)
        fp_old = ""

        try:
            if os.path.exists(meta_path):
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                    fp_old = meta.get("fingerprint", "")
        except Exception:
            fp_old = ""

        if fp_old == fp_now and os.path.exists(img_path):
            return True, img_path

        try:
            out = build_gallery_image(
                presets=presets,
                preview_map=self.artist_preview_map,
                output_dir=str(self.artist_gallery_dir),
                sort_key=self.key_sort_tuple,
                mode="masonry",
                cols=5,
                max_count=999999,
                output_name="artist_gallery.jpg",
            )

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"fingerprint": fp_now},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )

            return True, out

        except Exception as e:
            logger.exception(f"[BestNAI] 生成画师画廊失败: {e}")
            return False, str(e)

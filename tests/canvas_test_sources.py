from pathlib import Path


def canvas_source(page_root: Path) -> str:
    """Static wiring checks span the maintained ES modules; browser tests cover behavior."""
    names = ("canvas.js", "image-viewer.js", "asset-library.js", "character-editor.js", "generation-params.js", "asset-cache.js")
    return "\n".join((page_root / name).read_text(encoding="utf-8") for name in names)

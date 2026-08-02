from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE_ROOT = ROOT / "pages" / "canvas"
BRIDGE_SDK = '<script src="/api/plugin/page/bridge-sdk.js"></script>'


class CanvasPageBridgeTest(unittest.TestCase):
    def test_manager_loads_bridge_before_page_script(self) -> None:
        html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(BRIDGE_SDK, html)
        self.assertLess(html.index(BRIDGE_SDK), html.index('<script src="./manager.js"></script>'))

    def test_editor_loads_bridge_before_page_script(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor_script = '<script type="module" src="./canvas.js"></script>'
        self.assertIn(BRIDGE_SDK, html)
        self.assertLess(html.index(BRIDGE_SDK), html.index(editor_script))

    def test_page_scripts_wait_for_delayed_bridge(self) -> None:
        manager = (PAGE_ROOT / "manager.js").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        self.assertIn("while(!window.AstrBotPluginPage", manager)
        self.assertIn("while (!window.AstrBotPluginPage", editor)

    def test_editor_only_opens_drop_overlay_for_files(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        self.assertIn('includes("Files")', editor)
        self.assertIn("if (!dataTransferHasFiles(event.dataTransfer))", editor)
        self.assertIn('window.addEventListener("dragend", clearDropOverlay)', editor)

    def test_editor_only_allows_prompt_text_selection_and_copy(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        self.assertIn('document.addEventListener("dragstart"', editor)
        self.assertIn('document.addEventListener("selectstart"', editor)
        self.assertIn('document.addEventListener("copy"', editor)
        self.assertIn('targetElement?.closest(".prompt-text")', editor)
        self.assertIn('document.activeElement?.closest?.(".prompt-text")', editor)
        self.assertIn(".prompt-text {", styles)
        self.assertIn("user-select: none;", styles)


if __name__ == "__main__":
    unittest.main()

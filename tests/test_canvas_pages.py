from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PAGE_ROOT = ROOT / "pages" / "canvas"
BRIDGE_SDK = '<script src="/api/plugin/page/bridge-sdk.js"></script>'


class CanvasPageBridgeTest(unittest.TestCase):
    def test_entry_redirects_directly_to_editor(self) -> None:
        html = (PAGE_ROOT / "index.html").read_text(encoding="utf-8")
        entry = (PAGE_ROOT / "entry.js").read_text(encoding="utf-8")

        self.assertIn('<script src="./entry.js"></script>', html)
        self.assertNotIn("manager.js", html)
        self.assertIn('new URL("./editor.html"', entry)
        self.assertIn("window.location.replace", entry)

    def test_editor_loads_bridge_before_page_script(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor_script = '<script type="module" src="./canvas.js"></script>'
        self.assertIn(BRIDGE_SDK, html)
        self.assertLess(html.index(BRIDGE_SDK), html.index(editor_script))

    def test_page_scripts_wait_for_delayed_bridge(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
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

    def test_editor_double_click_creates_prompt_without_creation_menu(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertNotIn('id="createMenu"', html)
        self.assertNotIn('id="zoomBadge"', html)
        self.assertNotIn(".create-menu", styles)
        self.assertNotIn(".zoom-badge", styles)
        self.assertIn(
            "addNode(createPromptNode(clientToWorld(event.clientX, event.clientY)))",
            editor,
        )
        self.assertIn(
            'event.target.closest(".node, button, .link-hit, .link-delete, .minimap, .asset-panel")',
            editor,
        )

    def test_editor_persists_resized_notes_and_fits_image_nodes(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        self.assertIn("height: node.height || 0", editor)
        self.assertIn("function attachNoteResize", editor)
        self.assertIn("node.height = clamp", editor)
        self.assertIn("data.nodes.map(normalizeLoadedNodeDimensions)", editor)
        self.assertIn("function fittedImageNodeWidth", editor)

    def test_editor_manages_projects_without_a_workspace_gate(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        self.assertIn('id="projectMenuBtn"', html)
        self.assertIn('id="newProjectBtn"', html)
        self.assertIn('id="projectList"', html)
        self.assertNotIn("backToManagerBtn", html)
        self.assertIn("async function createCanvasProject", editor)
        self.assertIn("async function deleteCanvasProject", editor)
        self.assertNotIn("请先从项目工作台选择或创建画布", editor)

    def test_image_nodes_retag_then_generate_and_leave_library_explicit(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        service = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")

        self.assertIn("function retagAndGenerateFromImage", editor)
        self.assertIn("if (!state.config.retagConfigured)", editor)
        self.assertIn("retagFromNode(node.id, true)", editor)
        self.assertIn("if (succeeded && generateAfter) await generateFromNode(id)", editor)
        self.assertIn('bridge.apiPost("canvas/library/image/delete"', editor)
        generate_body = service.split("    async def generate(self)", 1)[1].split(
            "    async def retag(self)", 1
        )[0]
        upload_body = service.split("    async def upload_asset(self)", 1)[1].split(
            "    async def get_asset(self)", 1
        )[0]
        self.assertNotIn("add_image_to_library", generate_body)
        self.assertNotIn("add_image_to_library", upload_body)


if __name__ == "__main__":
    unittest.main()

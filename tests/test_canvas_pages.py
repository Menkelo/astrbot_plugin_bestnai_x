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
        self.assertIn('targetElement?.closest(".prompt-text, .translated-prompt-text")', editor)
        self.assertIn('document.activeElement?.closest?.(".prompt-text, .translated-prompt-text")', editor)
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

    def test_editor_persists_resized_notes_and_prompts_and_fits_image_nodes(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        self.assertIn("height: node.height || 0", editor)
        self.assertIn("function attachNodeResize", editor)
        self.assertIn('if (node.type === "prompt")', editor)
        self.assertIn("height: 360", editor)
        self.assertIn("node.height = clamp", editor)
        self.assertIn("data.nodes.map(normalizeLoadedNodeDimensions)", editor)
        self.assertIn("function fittedImageNodeWidth", editor)

    def test_editor_caches_images_across_undo_and_redo(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("assetCache: new Map()", editor)
        self.assertIn("function cacheImageAsset", editor)
        self.assertIn("function hydrateImageAsset", editor)
        self.assertIn("if (node.type === \"image\") hydrateImageAsset(node)", editor)
        self.assertIn("background: transparent;", styles)

    def test_editor_manages_projects_without_a_workspace_gate(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        self.assertIn('id="projectMenuBtn"', html)
        self.assertIn('id="newProjectBtn"', html)
        self.assertIn('id="projectList"', html)
        self.assertNotIn("backToManagerBtn", html)
        self.assertIn("async function createCanvasProject", editor)
        self.assertIn("async function deleteCanvasProject", editor)
        self.assertIn("async function switchCanvas", editor)
        self.assertIn('bridge.apiGet("canvas/workspace", { id: canvas.id })', editor)
        self.assertNotIn("window.location.href =", editor)
        self.assertNotIn("请先从项目工作台选择或创建画布", editor)

    def test_prompt_nodes_retag_then_generate_and_leave_library_explicit(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        service = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")

        self.assertNotIn("function retagAndGenerateFromImage", editor)
        self.assertNotIn('makeAction("scan-search", "反推并生成"', editor)
        self.assertIn("if (!state.config.retagConfigured)", editor)
        self.assertIn("retagFromNode(node.id, true)", editor)
        self.assertIn("function runPromptNode(id)", editor)
        self.assertIn("? retagFromNode(id, true)", editor)
        self.assertIn('document.createTextNode(node.status === "retagging" ? "反推中…" : "反推")', editor)
        self.assertIn("promptOverride: mergedPrompt", editor)
        self.assertIn('retagged ? "反推图片" : "生成结果"', editor)
        self.assertIn("function mergeRetagPrompt", editor)
        self.assertIn("const mergedPrompt = mergeRetagPrompt(basePrompt, retagPrompt)", editor)
        self.assertIn("retagMergedPrompt: mergedPrompt", editor)
        self.assertIn('translatedSummary.textContent = "英文 tags"', editor)
        self.assertIn("translatedPrompt: result.meta?.translatedPrompt", editor)
        self.assertNotIn('label: "不使用画师预设"', editor)
        self.assertIn('if (node.artist === "__none__") node.artist = ""', editor)
        self.assertIn('bridge.apiPost("canvas/library/image/delete"', editor)
        generate_body = service.split("    async def generate(self)", 1)[1].split(
            "    async def retag(self)", 1
        )[0]
        upload_body = service.split("    async def upload_asset(self)", 1)[1].split(
            "    async def get_asset(self)", 1
        )[0]
        self.assertNotIn("add_image_to_library", generate_body)
        self.assertNotIn("add_image_to_library", upload_body)

    def test_image_nodes_have_fullscreen_viewer(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn('id="imageViewer"', html)
        self.assertIn('makeAction("maximize-2", "放大查看"', editor)
        self.assertIn("function openImageViewer", editor)
        self.assertIn(".image-viewer {", styles)

    def test_plugin_metadata_and_astrbot_compatibility_are_exposed(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('src="./plugin-logo.webp"', html)
        self.assertIn('id="pluginRepoLink"', html)
        self.assertIn('>项目地址</a>', html)
        self.assertIn('astrbot_version: ">=4.26.0"', metadata)
        self.assertIn("最低要求：AstrBot `4.26.0`", readme)

    def test_editor_uses_one_topbar_with_health_status_and_aligned_ports(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn('class="topbar panel"', html)
        self.assertIn('id="connectionIndicator"', html)
        self.assertIn('class="plugin-title-row"', html)
        self.assertNotIn('class="panel canvas-nav"', html)
        self.assertNotIn('class="panel toolbar"', html)
        self.assertIn('bridge.apiGet("canvas/health")', editor)
        self.assertIn(".connection-indicator.online", styles)
        self.assertIn(".connection-indicator.offline", styles)
        self.assertIn("left: -22px;", styles)
        self.assertIn("right: -22px;", styles)

    def test_qq_retag_uses_detailed_retag_progress(self) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertNotIn('yield event.plain_result("🎨 正在生图，请稍候...")', main)
        self.assertIn('progress_verb: str = "生图"', main)
        self.assertIn('progress_verb="反推"', main)
        self.assertIn('f"🎨 正在{progress_verb}（{ratio_display} | 画师预设：{artist_display}）..."', main)
        self.assertIn("followup_messages=show_messages", main)
        self.assertLess(
            main.index('f"🎨 正在{progress_verb}（{ratio_display} | 画师预设：{artist_display}）..."'),
            main.index('yield event.plain_result("\\n\\n".join(followup_messages))'),
        )

    def test_repository_link_only_targets_a_new_tab(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        self.assertIn('id="pluginRepoLink"', html)
        self.assertIn('target="_blank"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertIn('window.open(els.pluginRepoLink.href, "_blank")', editor)
        self.assertNotIn("window.location.assign(repo)", editor)


if __name__ == "__main__":
    unittest.main()

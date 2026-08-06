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

    def test_editor_only_opens_drop_overlay_for_supported_images(self) -> None:
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
        self.assertIn(
            'targetElement?.closest(".prompt-text, .image-viewer-copy-text, .clipboard-copy-buffer")',
            editor,
        )
        self.assertIn(
            'document.activeElement?.closest?.(".prompt-text, .image-viewer-copy-text, .clipboard-copy-buffer")',
            editor,
        )
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

    def test_editor_persists_resized_notes_prompts_and_images(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("height: node.height || 0", editor)
        self.assertIn("function attachNodeResize", editor)
        self.assertIn("function attachImageNodeResize", editor)
        self.assertIn("userResized: true", editor)
        # 英文 tags 折叠面板已移除，随之而来的展开态布局问题一并消失
        self.assertNotIn("translatedPromptExpanded", editor)
        self.assertNotIn("translated-expanded", styles)
        self.assertNotIn("translated-prompt-panel", styles)
        self.assertNotIn("--prompt-editor-height", editor)
        self.assertIn('? 450 : 300', editor)
        self.assertIn("min-height: 450px;", (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8"))
        self.assertIn("resize: none;", (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8"))
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
        self.assertIn('class="project-switcher toolbar-project-switcher"', html)
        self.assertLess(html.index('id="clearBtn"'), html.index('id="projectMenuBtn"'))
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
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        service = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")

        self.assertNotIn("function retagAndGenerateFromImage", editor)
        self.assertNotIn('makeAction("scan-search", "反推并生成"', editor)
        self.assertIn("if (!cachedRetag && !state.config.retagConfigured)", editor)
        self.assertNotIn("retagFromNode(node.id, true)", editor)
        self.assertIn("function runPromptNode(id)", editor)
        self.assertIn("? retagFromNode(id, true)", editor)
        self.assertNotIn('document.createTextNode("反推")', editor)
        self.assertNotIn(".retag-btn", styles)
        self.assertIn("commands.append(generate)", editor)
        self.assertNotIn('document.createTextNode(node.status === "retagging"', editor)
        self.assertIn("promptOverride: mergedPrompt", editor)
        self.assertIn("function mergeRetagPrompt", editor)
        self.assertIn("const mergedPrompt = mergeRetagPrompt(basePrompt, retagPrompt)", editor)
        self.assertIn("retagMergedPrompt: mergedPrompt", editor)
        self.assertIn("function cachedRetagResult", editor)
        self.assertIn("const result = cachedRetag || await bridge.apiPost", editor)
        self.assertIn("retagAssetId: sourceImage.assetId", editor)
        self.assertIn('"正在复用已保存的反推结果…"', editor)
        prompt_input = editor.split('prompt.addEventListener("input"', 1)[1].split(
            'prompt.addEventListener("keydown"', 1
        )[0]
        self.assertNotIn("retagPrompt: _retagPrompt", prompt_input)
        self.assertIn("translationSource: _translationSource", prompt_input)
        # 英文 tags 只读框已删除，但翻译结果仍要留在 meta 里供复用
        self.assertNotIn("translated-prompt-text", editor)
        self.assertIn("translatedPrompt: result.meta?.translatedPrompt", editor)
        self.assertIn("cachedTranslationSource: node.meta?.translationSource", editor)
        self.assertIn("cachedTranslation: node.meta?.translationResult", editor)
        self.assertIn("translationSource: result.meta?.translationSource", editor)
        self.assertIn("translationResult: result.meta?.translationResult", editor)
        retag_body = editor.split("async function retagFromNode", 1)[1].split(
            "async function ensureAssetLoaded", 1
        )[0]
        self.assertNotIn("node.ratio = result.ratio", retag_body)
        self.assertIn('"正在复用英文 tags 并生成图片…"', editor)
        self.assertNotIn('label: "不使用画师预设"', editor)
        self.assertIn('if (node.artist === "__none__") node.artist = ""', editor)
        self.assertIn('bridge.apiPost("canvas/library/image/delete"', editor)
        delete_body = editor.split("function deleteNodes(ids)", 1)[1].split(
            "function deleteNode(id)", 1
        )[0]
        self.assertNotIn("canvas/library/image/delete", delete_body)
        self.assertNotIn("state.library.images", delete_body)
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
        self.assertIn('id="imageViewerPrompt"', html)
        self.assertIn('id="imageViewerTags"', html)
        self.assertNotIn('id="imageViewerCaption"', html)
        self.assertNotIn('id="imageViewerArtist"', html)
        self.assertNotIn('id="imageViewerDimensions"', html)
        self.assertNotIn('id="imageViewerClose"', html)
        self.assertNotIn('makeAction("maximize-2", "放大查看"', editor)
        self.assertIn('data-copy-target="imageViewerPrompt"', html)
        self.assertIn('data-copy-target="imageViewerTags"', html)
        self.assertIn("function openImageViewer", editor)
        download_body = editor.split("async function downloadImage", 1)[1].split(
            "function openImageViewer", 1
        )[0]
        self.assertIn('bridge.download(', download_body)
        self.assertIn('"canvas/asset/download"', download_body)
        self.assertNotIn("response.blob()", download_body)
        self.assertNotIn("URL.createObjectURL", download_body)
        self.assertNotIn('target = "_blank"', download_body)
        self.assertIn("if (canvasGenerationActive())", download_body)
        self.assertIn("生图或反推期间暂不可下载", download_body)
        self.assertIn("function canvasGenerationActive()", editor)
        self.assertIn('downloadLocked ? "locked" : ""', editor)
        self.assertIn('downloadAction.setAttribute("aria-disabled"', editor)
        self.assertIn(".node-action.locked", styles)
        self.assertIn('frame.addEventListener("click", () => openImageViewer(node))', editor)
        self.assertIn('!event.target.closest("#imageViewerImage, .image-viewer-details")', editor)
        self.assertIn("function copyViewerText", editor)
        self.assertIn("function isPureEnglishPrompt", editor)
        self.assertIn("els.imageViewerPromptSection.hidden", editor)
        self.assertIn(".image-viewer {", styles)
        self.assertIn(".image-viewer-copy[hidden]", styles)
        self.assertNotIn(".image-viewer-heading", styles)
        self.assertNotIn("#imageViewerArtist", styles)
        self.assertIn("scrollbar-width: thin;", styles)
        self.assertIn(".image-viewer-copy p::-webkit-scrollbar-thumb", styles)
        self.assertIn(".image-viewer-copy p::-webkit-scrollbar-button", styles)
        self.assertIn("user-select: text;", styles)

    def test_library_preloads_and_uses_click_preview_with_drag_placement(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertNotIn('class="asset-tabs"', html)
        self.assertNotIn("data-asset-tab", html)
        self.assertNotIn("data-asset-layout", html)
        self.assertNotIn('id="assetSearch"', html)
        self.assertNotIn('id="assetArtistFilter"', html)
        self.assertNotIn('id="assetRatioFilter"', html)
        self.assertNotIn('id="assetSourceFilter"', html)
        self.assertNotIn('id="assetSort"', html)
        self.assertNotIn('id="assetThumbSize"', html)
        self.assertNotIn('<strong>素材库</strong>', html)
        self.assertIn("function preloadLibraryImages()", editor)
        self.assertIn("preloadLibraryImages();", editor)
        self.assertIn("ensureLibraryImageData(item)", editor)
        self.assertIn("openLibraryImageViewer(item);", editor)
        self.assertIn("function attachLibraryImageDrag", editor)
        self.assertIn("isCanvasDropPoint(endEvent.clientX, endEvent.clientY)", editor)
        self.assertIn("placeImageAssetOnCanvas(", editor)
        self.assertIn("clientToWorld(endEvent.clientX, endEvent.clientY)", editor)
        self.assertNotIn('card.addEventListener("click", () => addImageAssetToCanvas(item))', editor)
        self.assertIn('thumb.style.aspectRatio = `${item.width} / ${item.height}`', editor)
        self.assertIn("renderImageAssetCard(item, els.assetGrid)", editor)
        self.assertIn("object-fit: contain;", styles)
        self.assertIn("object-fit: cover;", styles)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", styles)
        # 三列对齐靠 CSS 自己算：卡片正方形、左右留一样的边、缩略图脱离文档流
        self.assertIn("aspect-ratio: 1;", styles)
        self.assertIn("padding: 0 3px;", styles)
        self.assertNotIn("--asset-card-height", styles)
        self.assertNotIn("updateAssetGridMetrics", editor)
        self.assertIn("function alignAssetPanel()", editor)
        self.assertIn("function alignedPanelEdges()", editor)
        self.assertIn("buttonRect.left", editor)
        self.assertIn('els.assetPanel.style.width = `${right - left}px`', editor)
        self.assertIn("topbarRect.bottom - viewportRect.top + gap", editor)
        self.assertIn("viewportRect.bottom - minimapRect.top + gap", editor)
        self.assertIn("max-width: calc(100vw - 24px);", styles)
        self.assertNotIn(".asset-image-remove {", styles)
        self.assertIn('id="assetSelectModeBtn"', html)
        self.assertIn('id="assetLibraryCount"', html)
        self.assertIn('id="assetDeleteCancel"', html)
        self.assertIn('id="assetDeleteConfirm"', html)
        self.assertLess(html.index('id="assetDeleteConfirm"'), html.index('id="assetDeleteCancel"'))
        self.assertIn('<span>多选</span>', html)
        self.assertNotIn('id="assetDeleteToggle"', html)
        self.assertNotIn(".asset-delete-toggle", styles)
        self.assertLess(html.index('id="assetGrid"'), html.index('class="asset-delete-toolbar"'))
        self.assertIn("selectedAssetIds: new Set()", editor)
        self.assertIn("function deleteSelectedLibraryAssets()", editor)
        self.assertIn('els.assetLibraryCount.textContent = `已收录 ${items.length} 张`', editor)
        delete_mode_body = editor.split("function setAssetDeleteMode", 1)[1].split(
            "function updateAssetDeleteControls", 1
        )[0]
        self.assertNotIn("renderAssetLibrary()", delete_mode_body)
        self.assertIn('card.classList.remove("selected")', delete_mode_body)
        self.assertIn('els.assetSelectModeBtn.setAttribute("aria-pressed"', delete_mode_body)
        self.assertIn('canvas/library/image/delete', editor)
        self.assertIn(".asset-select-indicator", styles)
        self.assertIn(".asset-panel.delete-mode .asset-image-card.selected", styles)
        self.assertNotIn('name.className = "asset-card-name"', editor)
        self.assertIn("align-self: start;", styles)
        self.assertIn(".asset-grid.empty", styles)
        self.assertNotIn("ASSET_UI_KEY", editor)
        self.assertIn("ASSET_RENDER_BATCH", editor)
        self.assertIn("new IntersectionObserver", editor)
        self.assertIn("rootMargin: \"240px 0px\"", editor)
        self.assertNotIn('id="assetPanelClose"', html)
        self.assertIn('id="imageViewerPlaceBtn"', html)
        self.assertIn("viewerLibraryAsset: null", editor)
        self.assertIn('event.pointerType === "touch"', editor)
        self.assertIn("{ libraryAsset: item }", editor)
        self.assertIn("els.imageViewerPlaceBtn.addEventListener", editor)
        self.assertIn("const placed = await placeImageAssetOnCanvas(item, worldCenter())", editor)
        self.assertIn("if (!placed) return", editor)
        place_body = editor.split("async function placeImageAssetOnCanvas", 1)[1].split(
            "async function saveImageToLibrary", 1
        )[0]
        self.assertNotIn("setAssetPanel(false)", place_body)

    def test_artist_badges_and_generation_buttons_have_stable_layout(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        service = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")

        self.assertIn("function artistDisplayName", editor)
        self.assertIn('artist: result.meta?.artist || ""', editor)
        self.assertIn('artist: node.meta?.artist || ""', editor)
        self.assertIn('artist: item.artist || ""', editor)
        self.assertIn('artistBadge.className = "image-artist-badge"', editor)
        self.assertNotIn('artistBadge.className = "node-artist-badge"', editor)
        self.assertNotIn(".node-artist-badge", styles)
        self.assertIn("min-width: 64px;", styles)
        self.assertIn("white-space: nowrap;", styles)
        self.assertNotIn("flex: 0 0 72px;", styles)
        self.assertIn('"artist": _short_text(raw_meta.get("artist"), 120)', service)

    def test_clicked_nodes_move_to_front_and_image_labels_keep_source_prompt(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        self.assertIn("function bringNodeToFront", editor)
        self.assertIn("state.nodes.splice(index, 1)", editor)
        self.assertIn("els.nodeLayer.appendChild(current)", editor)
        self.assertIn('makeNodeShell(node, node.title || "生成结果")', editor)
        self.assertIn('title: `${retagged ? "反推图片" : "生成结果"}', editor)
        self.assertIn(
            'prompt: node.prompt?.trim() || node.title || (retagged ? "反推图片" : "生成结果")',
            editor,
        )
        self.assertIn("tags: result.meta?.translatedPrompt || workingPrompt", editor)
        self.assertIn("retagged,", editor)
        self.assertIn('source: node.meta?.retagged ? "retagged" : "generated"', editor)

    def test_new_prompt_nodes_inherit_last_ratio_and_artist(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        service = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")

        self.assertIn('const PROMPT_DEFAULTS_KEY = "bestnaiInfiniteCanvasPromptDefaults"', editor)
        self.assertIn("function loadPromptDefaults(preferences = {})", editor)
        self.assertIn("function rememberPromptDefaults(updates)", editor)
        self.assertIn("ratio: state.promptDefaults.ratio", editor)
        self.assertIn("artist: state.promptDefaults.artist", editor)
        self.assertIn("rememberPromptDefaults({ ratio: value })", editor)
        self.assertIn("rememberPromptDefaults({ artist: value })", editor)
        self.assertIn('bridge.apiGet("canvas/preferences")', editor)
        self.assertIn('bridge.apiPost("canvas/preferences", payload)', editor)
        self.assertIn("preferences?.lastCanvasId", editor)
        self.assertIn("function persistCanvasPreferences()", editor)
        self.assertIn("def load_preferences(self)", service)
        self.assertIn("def save_preferences(self, payload", service)
        self.assertIn("const artistOptions = canvasArtistOptions()", editor)
        self.assertNotIn("`默认 · ${state.config.defaultArtist", editor)

    def test_generation_avoids_existing_nodes_and_text_inputs_keep_native_undo(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("function findOpenGeneratedPosition", editor)
        self.assertIn("function findNextGeneratedPosition", editor)
        self.assertIn("const latestEdge = [...state.connections].reverse().find", editor)
        self.assertIn("x: latestImage.x + 56", editor)
        self.assertIn("y: latestImage.y - 36", editor)
        self.assertIn("const position = findNextGeneratedPosition(", editor)
        self.assertIn("function rectanglesOverlap", editor)
        self.assertIn("estimatedImageNodeHeight(imageNodeWidth, sourceWidth, sourceHeight)", editor)
        self.assertIn("x: position.x", editor)
        self.assertIn("y: position.y", editor)
        self.assertIn("const editing = !!target?.closest", editor)
        self.assertIn("if (editing) return;", editor)
        self.assertNotIn('id="saveSelectedPromptBtn"', html)
        self.assertNotIn("saveSelectedPrompt", editor)
        self.assertNotIn(".asset-save-prompt", styles)

    def test_asset_library_owns_wheel_and_drag_preview_tracks_grab_point(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("function nodeEditorOwnsWheel(target)", editor)
        self.assertIn('els.assetPanel.addEventListener("wheel"', editor)
        self.assertIn("event.stopPropagation();", editor)
        self.assertIn("grabOffsetX: event.clientX - cardRect.left", editor)
        self.assertIn("grabOffsetY: event.clientY - cardRect.top", editor)
        self.assertIn("ghost.style.width = `${start.cardWidth}px`", editor)
        self.assertIn("moveEvent.clientX - start.grabOffsetX", editor)
        self.assertIn("moveEvent.clientY - start.grabOffsetY", editor)
        self.assertIn("overscroll-behavior: contain;", styles)
        ghost_styles = styles.split(".asset-drag-ghost {", 1)[1].split("}", 1)[0]
        self.assertNotIn("width: 180px", ghost_styles)
        self.assertNotIn("transform: scale", ghost_styles)

    def test_plugin_metadata_and_astrbot_compatibility_are_exposed(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('src="./plugin-logo.webp"', html)
        self.assertNotIn('id="pluginRepoLink"', html)
        self.assertIn('astrbot_version: ">=4.26.0"', metadata)
        self.assertIn("最低要求：AstrBot `4.26.0`", readme)

    def test_editor_uses_one_topbar_with_health_status_and_aligned_ports(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn('class="topbar panel"', html)
        topbar_start = html.index('class="topbar panel"')
        toast_position = html.index('id="toastRegion"')
        board_start = html.index('id="board"')
        self.assertLess(topbar_start, toast_position)
        self.assertLess(board_start, toast_position)
        self.assertIn('id="connectionIndicator"', html)
        self.assertIn('class="plugin-title-row"', html)
        self.assertLess(html.index('id="pluginVersion"'), html.index('id="connectionIndicator"'))
        self.assertNotIn('class="panel canvas-nav"', html)
        self.assertNotIn('class="panel toolbar"', html)
        self.assertIn('bridge.apiGet("canvas/health")', editor)
        self.assertIn(".connection-indicator.online", styles)
        self.assertIn(".connection-indicator.offline", styles)
        self.assertIn("overflow: visible;", styles)
        self.assertIn(".plugin-meta > span:not(.connection-indicator)", styles)
        self.assertIn("left: -22px;", styles)
        self.assertIn("right: -22px;", styles)
        toast_styles = styles.split(".toast-region {", 1)[1].split("}", 1)[0]
        self.assertIn("position: fixed;", toast_styles)
        self.assertIn("z-index: 1100;", toast_styles)
        self.assertIn("top: 50%;", toast_styles)
        self.assertIn("left: 50%;", toast_styles)
        self.assertIn("transform: translate(-50%, -50%);", toast_styles)
        self.assertNotIn("right: 24px;", toast_styles)
        toast_body = editor.split("function toast(message", 1)[1].split("function setConnectionState", 1)[0]
        self.assertIn("els.toastRegion.replaceChildren(item)", toast_body)
        self.assertNotIn("els.toastRegion.appendChild(item)", toast_body)
        self.assertIn("function alignToastRegion()", editor)
        image_viewer_styles = styles.split(".image-viewer {", 1)[1].split("}", 1)[0]
        self.assertIn("z-index: 1000;", image_viewer_styles)

    def test_project_menu_matches_toolbar_and_asset_panel_geometry(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn('class="tool-btn icon-only project-menu-trigger"', html)
        self.assertIn('aria-controls="projectMenu"', html)
        self.assertIn('event.target.closest(".project-switcher, .project-menu")', editor)
        self.assertIn("if (next && els.assetPanel.classList.contains(\"open\")) setAssetPanel(false)", editor)
        self.assertIn("if (open && !els.projectMenu.hidden) setProjectMenu(false)", editor)
        self.assertIn("function alignProjectMenu()", editor)
        self.assertIn("const { topbarRect, left, right } = alignedPanelEdges()", editor)
        self.assertIn('els.projectMenu.style.top = `${topbarRect.bottom + 14}px`', editor)
        self.assertIn('els.projectMenu.style.width = `${right - left}px`', editor)
        project_menu_styles = styles.split(".project-menu {", 1)[1].split("}", 1)[0]
        self.assertIn("position: fixed;", project_menu_styles)
        self.assertIn("border-radius: 16px;", project_menu_styles)

    def test_mobile_toolbar_keeps_actions_and_canvas_supports_pinch_zoom(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        mobile_styles = styles.split("@media (max-width: 620px) {", 1)[1].split(
            "@media (prefers-reduced-motion", 1
        )[0]
        self.assertIn('id="mobileAssetLibraryBtn"', html)
        self.assertIn(
            '"identity identity identity identity identity identity identity asset project"',
            mobile_styles,
        )
        self.assertIn('"tools tools tools tools tools tools tools tools tools"', mobile_styles)
        self.assertIn("#assetLibraryBtn", mobile_styles)
        self.assertIn("display: none;", mobile_styles)
        self.assertIn('document.querySelectorAll("#assetLibraryBtn, #mobileAssetLibraryBtn")', editor)
        self.assertIn("overflow-x: auto;", mobile_styles)
        self.assertIn("-webkit-overflow-scrolling: touch;", mobile_styles)
        self.assertIn("grid-template-columns: repeat(9, minmax(28px, 1fr));", mobile_styles)
        self.assertIn("display: contents;", mobile_styles)
        self.assertIn("justify-self: center;", mobile_styles)
        self.assertIn("place-items: center;", mobile_styles)
        landscape_styles = styles.split(
            "@media (orientation: landscape) and (max-height: 620px) and (max-width: 1400px) {",
            1,
        )[1].split("@media (max-width: 620px) {", 1)[0]
        self.assertIn("overflow: visible;", landscape_styles)
        self.assertIn("flex: 0 0 auto;", landscape_styles)
        self.assertIn("--compact-tool-size: clamp(32px, 4vw, 38px);", landscape_styles)
        self.assertIn("min-width: var(--compact-tool-size);", landscape_styles)
        self.assertNotIn(".toolbar-fixed .tool-btn:not(#fitBtn)", mobile_styles)
        self.assertIn("const canvasTouchPointers = new Map()", editor)
        self.assertIn("function beginCanvasPinch()", editor)
        self.assertIn('mode: "pinch"', editor)
        self.assertIn("canvasTouchGesture.startScale * distance / canvasTouchGesture.startDistance", editor)
        self.assertIn('event.pointerType === "touch"', editor)
        self.assertIn('els.viewport.addEventListener("pointermove", handleCanvasTouchMove)', editor)
        self.assertIn('els.viewport.addEventListener("pointercancel", handleCanvasTouchEnd)', editor)
        self.assertIn('class="empty-state-desktop"', html)
        self.assertIn('class="empty-state-mobile"', html)
        self.assertIn(".asset-image-card {", mobile_styles)
        self.assertIn("touch-action: pan-y;", mobile_styles)
        self.assertIn("backdrop-filter: none;", mobile_styles)
        self.assertIn("function scheduleViewportProjection()", editor)
        self.assertIn("function scheduleCanvasProjection()", editor)
        self.assertIn("function scheduleConnectionRender()", editor)
        self.assertIn('window.matchMedia("(max-width: 620px)").matches', editor)
        self.assertIn("const width = element?.offsetWidth || node.width || 320", editor)
        self.assertIn("const height = element?.offsetHeight || node.height || 260", editor)

    def test_prompt_editors_own_wheel_scrolling_and_logo_is_round(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        wheel_owner = editor.split("function nodeEditorOwnsWheel", 1)[1].split(
            'els.viewport.addEventListener("wheel"', 1
        )[0]
        self.assertIn(".prompt-text", wheel_owner)
        self.assertIn(".note-text", wheel_owner)
        self.assertIn('.closest(".node.selected")', wheel_owner)
        wheel_body = editor.split('els.viewport.addEventListener("wheel"', 1)[1].split(
            'els.assetPanel.addEventListener("wheel"', 1
        )[0]
        self.assertIn("nodeEditorOwnsWheel(event.target)", wheel_body)
        prompt_styles = styles.split(".prompt-text {\n  min-height:", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-y: auto;", prompt_styles)
        self.assertIn("overscroll-behavior: contain;", prompt_styles)
        logo_styles = styles.split(".canvas-mark {", 1)[1].split("}", 1)[0]
        self.assertIn("border-radius: 999px;", logo_styles)

    def test_quick_toolbar_is_icon_only(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        toolbar = html.split('id="quickToolbar"', 1)[1].split("</nav>", 1)[0]
        items = toolbar.split('class="toolbar-items"', 1)[1].split("</div>", 1)[0]

        # 工具栏只留图标，文字标签靠 title / aria-label 提供
        self.assertNotIn("<span>", items)
        for button_id, label in (
            ("addImageBtn", "上传图片"),
            ("addPromptBtn", "添加提示词节点"),
            ("addNoteBtn", "添加备注节点"),
            ("assetLibraryBtn", "素材库"),
        ):
            with self.subTest(button=button_id):
                self.assertIn(f'id="{button_id}"', items)
                self.assertIn(f'aria-label="{label}"', items)
        self.assertEqual(items.count("icon-only"), 4)

        # 图标固定 16px 且不参与压缩，最小按钮 28px 也放得下
        icon_styles = styles.split(".tool-btn svg {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 16px;", icon_styles)
        self.assertIn("flex: 0 0 auto;", icon_styles)

        # 右键菜单仍保留文字，那里没有空间压力
        self.assertIn('id="contextAddImageBtn"', html)
        self.assertIn("<span>图片</span>", html)

    def test_prompt_card_bottom_hint_stays_inside_the_card(self) -> None:
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        # .node 是 overflow: visible（端口要露出卡片），所以裁剪必须落在 node-body
        node_styles = styles.split(".node {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: visible;", node_styles)
        body_styles = styles.split(".prompt-node .node-body {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: hidden;", body_styles)

        # 收缩时由文本框让出空间（行首锚定，避免匹配到 translated-expanded 的覆盖规则）
        prompt_styles = styles.split("\n.prompt-text {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: 0;", prompt_styles)
        self.assertIn("flex: 1 1 auto;", prompt_styles)

        # 底部四块都不参与压缩，不会被挤出卡片
        for selector in (
            ".prompt-options {",
            ".node-footer {",
            ".node-status {",
        ):
            with self.subTest(selector=selector):
                block = styles.split(selector, 1)[1].split("}", 1)[0]
                self.assertIn("flex: 0 0 auto;", block)

        # 状态行是共用的：快捷键提示、已连接原图提示、报错都走这里，
        # 长文案必须截断，否则会把卡片撑破
        status_styles = styles.split(".node-status {", 1)[1].split("}", 1)[0]
        self.assertIn("-webkit-line-clamp: 2;", status_styles)
        self.assertIn("overflow: hidden;", status_styles)
        self.assertIn("overflow-wrap: anywhere;", status_styles)

        # 展开英文 tags 后缩小卡片同样不能溢出：面板和只读框都要可压缩
        advanced_styles = styles.split(".prompt-advanced {", 1)[1].split("}", 1)[0]
        self.assertIn("flex: 0 0 auto;", advanced_styles)
        self.assertIn("min-height: 0;", advanced_styles)

    def test_generation_does_not_interrupt_prompt_typing(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        # 生成完成会重渲染，整层 replaceChildren 把焦点和光标一起清掉
        self.assertIn("function captureEditingFocus", editor)
        self.assertIn("function restoreEditingFocus", editor)
        render_nodes = editor.split("function renderNodes() {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn("const editing = captureEditingFocus();", render_nodes)
        self.assertIn("restoreEditingFocus(editing);", render_nodes)
        self.assertLess(
            render_nodes.index("const editing = captureEditingFocus();"),
            render_nodes.index("els.nodeLayer.replaceChildren();"),
        )
        self.assertIn("field.setSelectionRange(snapshot.start, snapshot.end)", editor)

        # 输入法组字期间连重建都不能做，光标恢复救不回未上屏的内容
        self.assertIn("setupCompositionGuard();", editor)
        render_all = editor.split("function renderAll() {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn("if (state.composing) {", render_all)
        self.assertIn("state.renderPending = true;", render_all)
        guard = editor.split("function setupCompositionGuard() {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn('"compositionstart"', guard)
        self.assertIn('"compositionend"', guard)
        # 组字中途节点被移除不会有 compositionend，靠 focusout 兜底
        self.assertIn('"focusout"', guard)
        self.assertIn("if (state.renderPending) renderAll();", guard)

    def test_plugin_version_has_no_hardcoded_fallback(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")

        # 版本号只能来自后端，写死兜底值会在后端没返回时显示成过期的假版本
        self.assertNotRegex(editor, r'plugin\.version \|\| "\d')
        self.assertIn('const pluginVersion = String(plugin.version || "").trim()', editor)
        self.assertIn("els.pluginVersion.hidden = !pluginVersion", editor)
        self.assertIn('<span id="pluginVersion" hidden></span>', html)

        version_line = next(
            line for line in html.splitlines() if 'id="pluginVersion"' in line
        )
        self.assertNotRegex(version_line, r"v\d+\.\d+")

    def test_logo_easter_egg_needs_three_quick_clicks(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("function setupLogoEasterEgg()", editor)
        self.assertIn("setupLogoEasterEgg();", editor)

        body = editor.split("function setupLogoEasterEgg() {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn("if (clicks < 3)", body)
        self.assertIn("祝你天天开心！", body)
        # 隔太久要重新计数，避免几次无关的点击攒够三下
        self.assertIn("RESET_DELAY", body)
        self.assertIn("clicks = 0;", body)
        # 动画进行中不重复叠加，结束后自动清理 class
        self.assertIn('mark.classList.contains("celebrate")', body)
        self.assertIn('"animationend"', body)
        self.assertIn("{ once: true }", body)

        self.assertIn(".canvas-mark.celebrate {", styles)
        self.assertIn("@keyframes canvas-mark-celebrate {", styles)
        keyframes = styles.split("@keyframes canvas-mark-celebrate {", 1)[1].split(
            "\n}", 1
        )[0]
        self.assertIn("rotate(1turn)", keyframes)

    def test_middle_mouse_pans_and_context_menu_adds_nodes(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn('id="canvasContextMenu"', html)
        self.assertIn('id="contextAddImageBtn"', html)
        self.assertIn('<span>图片</span>', html)
        self.assertNotIn('<span>上传节点</span>', html)
        self.assertIn('event.pointerType === "mouse" && event.button === 1', editor)
        self.assertIn("if (middlePan) event.preventDefault()", editor)
        self.assertIn('state.contextMenuPoint = clientToWorld(event.clientX, event.clientY)', editor)
        self.assertIn('document.getElementById("contextAddPromptBtn")', editor)
        self.assertIn('addNode(createPromptNode(point))', editor)
        self.assertIn('addNode(createNoteNode(point))', editor)
        menu_styles = styles.split(".canvas-context-menu {", 1)[1].split("}", 1)[0]
        self.assertIn("position: fixed;", menu_styles)
        self.assertIn("border-radius: 18px;", menu_styles)

    def test_character_preservation_is_removed(self) -> None:
        retagger = (ROOT / "core" / "image_retagger.py").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        service = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")

        # 角色保持已由种子方案取代，前后端都不该再有残留
        for text in ("keep_character", "character_name"):
            with self.subTest(backend=text):
                self.assertNotIn(text, retagger)
        for text in ("characterKeep", "characterName", "keepCharacter"):
            with self.subTest(frontend=text):
                self.assertNotIn(text, editor)
        self.assertNotIn(".character-keep-row", styles)
        self.assertNotIn("keepCharacter", service)

        # 角色识别本身保留：那是反推提示词的固定第一步
        self.assertIn("Step 1 - Identify the character", retagger)

    def test_qq_retag_uses_detailed_retag_progress(self) -> None:
        main = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertNotIn('yield event.plain_result("🎨 正在生图，请稍候...")', main)
        self.assertIn('progress_verb: str = "生图"', main)
        self.assertIn('progress_verb="反推"', main)
        self.assertIn("def _format_generation_progress", main)
        self.assertIn("followup_messages=show_messages", main)
        image_branch = main.split("        if image_src:", 1)[1].split(
            "        if not prompt:", 1
        )[0]
        self.assertIn("yield event.plain_result(retag_progress)", image_branch)
        self.assertIn("show_progress=False", image_branch)
        self.assertLess(
            image_branch.index("yield event.plain_result(retag_progress)"),
            image_branch.index("img_w, img_h = await read_image_size_any"),
        )
        self.assertLess(
            image_branch.index("yield event.plain_result(retag_progress)"),
            image_branch.index("retag_prompt = await self.image_retagger.retag"),
        )


if __name__ == "__main__":
    unittest.main()

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
            'targetElement?.closest(".prompt-text, .note-text, .image-viewer-copy-text, .clipboard-copy-buffer")',
            editor,
        )
        self.assertIn(
            'document.activeElement?.closest?.(".prompt-text, .note-text, .image-viewer-copy-text, .clipboard-copy-buffer")',
            editor,
        )
        self.assertIn("selectionInTextSurface", editor)
        self.assertIn('targetElement?.closest(".debug-body, .operation-log-list")', editor)
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
            '".node, button, .link-hit, .link-delete, .asset-panel, .debug-bar",',
            editor,
        )
        self.assertNotIn("minimap", html)
        self.assertNotIn("minimap", editor)
        self.assertNotIn("minimap", styles)

    def test_canvas_uses_cad_style_left_selection_and_middle_pan(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("AutoCAD-style window selection", editor)
        self.assertIn("const middlePan = event.pointerType === \"mouse\" && event.button === 1", editor)
        self.assertIn("const toggle = !!(event.ctrlKey || event.metaKey)", editor)
        self.assertIn("const additive = !!event.shiftKey", editor)
        self.assertIn("selectNode(node.id, { toggle: true })", editor)
        self.assertIn("selectNode(node.id, { additive: true })", editor)
        self.assertIn("finishBoxSelection(startWorld, endEvent", editor)
        self.assertIn(".selection-box.crossing", styles)

    def test_mobile_toolbar_keeps_clear_action_on_the_same_row(self) -> None:
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        mobile = styles.split("@media (max-width: 620px) {", 1)[1].split(
            "@media (prefers-reduced-motion", 1
        )[0]
        toolbar = mobile.split(".toolbar {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid;", toolbar)
        self.assertIn("grid-template-columns: minmax(0, 3fr) minmax(0, 7fr);", toolbar)
        self.assertIn("flex: 0 0 clamp(28px, 8vw, 32px);", mobile)
        self.assertIn("grid-template-columns: repeat(10, minmax(28px, 1fr));", mobile)

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
        self.assertIn("Do not gate this action on the vision-provider flag", editor)
        self.assertNotIn("retagFromNode(node.id, true)", editor)
        self.assertIn("function runPromptNode(id)", editor)
        self.assertIn("? retagFromNode(id, true)", editor)
        self.assertNotIn('document.createTextNode("反推")', editor)
        self.assertNotIn(".retag-btn", styles)
        self.assertIn("commands.append(generate)", editor)
        self.assertNotIn('document.createTextNode(node.status === "retagging"', editor)
        self.assertNotIn("promptOverride", editor)
        self.assertNotIn("function mergeRetagPrompt", editor)
        self.assertIn("retagPrompt: requestRetagPrompt", editor)
        self.assertIn('retagPrompt: node.meta?.retagPrompt || ""', editor)
        self.assertNotIn("retagMode", editor)
        self.assertNotIn('"复刻（保留原图）"', editor)
        self.assertNotIn('"反推模式"', editor)
        self.assertNotIn("prompt-mode-field", styles)
        self.assertNotIn('"retagMode":', service)
        self.assertIn("function cachedRetagResult", editor)
        self.assertIn("cachedRetagResult(node, sourceImage, basePrompt)", editor)
        # The cached tag result describes the source image, so editing the
        # handwritten overlay must not invalidate it or call the vision model
        # a second time.  ``retagBasePrompt`` remains a migration/debug field,
        # but it is intentionally not part of the cache-hit predicate.
        self.assertNotIn(
            'String(meta.retagBasePrompt || "") !== String(basePrompt || "")',
            editor,
        )
        self.assertIn("Retagging describes the source image", editor)
        retag_body = editor.split("async function retagFromNode", 1)[1].split(
            "async function ensureAssetLoaded", 1
        )[0]
        self.assertNotIn("userHint:", retag_body)
        self.assertIn("const result = cachedRetag || await bridge.apiPost", editor)
        self.assertIn("retagAssetId: sourceImage.assetId", editor)
        self.assertIn('"正在复用已保存的反推结果…"', editor)
        prompt_input = editor.split('prompt.addEventListener("input"', 1)[1].split(
            'prompt.addEventListener("keydown"', 1
        )[0]
        self.assertNotIn("retagPrompt: _retagPrompt", prompt_input)
        self.assertIn("clearTranslationCache(node)", prompt_input)
        # 英文 tags 只读框已删除，但翻译结果仍要留在 meta 里供复用
        self.assertNotIn("translated-prompt-text", editor)
        self.assertIn("translatedPrompt: result.meta?.translatedPrompt", editor)
        self.assertIn("cachedTranslationSource: node.meta?.translationSource", editor)
        self.assertIn("cachedTranslation: node.meta?.translationResult", editor)
        self.assertIn("translationSource: result.meta?.translationSource", editor)
        self.assertIn("translationResult: result.meta?.translationResult", editor)
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

    def test_retag_tag_layers_are_an_attached_card_and_affect_generation(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        service = (ROOT / "services" / "canvas.py").read_text(encoding="utf-8")
        main = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("function makeRetagLayerCard", editor)
        render = editor.split("function renderPromptNode(node)", 1)[1].split(
            "const DEBUG_SECTIONS", 1
        )[0]
        self.assertIn("makeRetagLayerCard(node, sourceImage, element)", render)
        self.assertIn("element.appendChild(retagLayerCard)", render)
        self.assertNotIn("body.appendChild(retagLayerCard)", render)
        self.assertIn('document.createTextNode("原图标签图层")', editor)
        self.assertNotIn('document.createTextNode("原图标签图层 / Source tags")', editor)
        self.assertIn('["auto", "自动"]', editor)
        self.assertIn('["preserve", "锁定"]', editor)
        self.assertIn('["drop", "移除"]', editor)
        self.assertIn("retagPreserveCategories: retagLayerCategories.preserve", editor)
        self.assertIn("retagDropCategories: retagLayerCategories.drop", editor)
        self.assertIn("retagTagGroups: normalizeRetagTagGroups(result?.tagGroups)", editor)
        self.assertIn("retagTagTranslations: normalizeRetagTagTranslations(result?.tagTranslations)", editor)
        self.assertIn("function normalizeRetagTagTranslations", editor)
        self.assertIn("bilingualRetagTagText(tag, tagTranslations)", editor)
        self.assertIn("retagTagGroups: _retagTagGroups", editor)
        self.assertIn("retagTagTranslations: _retagTagTranslations", editor)
        self.assertIn("retagLayerModes: _retagLayerModes", editor)
        self.assertIn("retagLayerExpanded: open", editor)
        self.assertIn("setOpen(node.meta?.retagLayerExpanded === true)", editor)
        self.assertNotIn("expandedRetagLayers", editor)
        self.assertIn('if (retagLayer) return !!retagLayer.closest(".node.selected")', editor)
        self.assertIn("if (isNodeSelected(node.id)) event.stopPropagation();", editor)
        self.assertIn("function collapseRetagLayers()", editor)
        self.assertIn(
            "void retagFromNode(destination, false, { automatic: true });",
            editor,
        )
        self.assertIn("retagLayerExpanded: _retagLayerExpanded", editor)
        self.assertIn("retagLayerExpanded: node.meta?.retagLayerExpanded === true", editor)
        self.assertNotIn("expandLayer", editor)
        self.assertIn("function beginRetagRequest(node, sourceImage)", editor)
        self.assertIn("function retagRequestStillMatchesSource(node, token, assetId)", editor)
        self.assertIn(
            "if (!retagRequestStillMatchesSource(node, requestToken, sourceAssetId)) return false;",
            editor,
        )
        self.assertIn('recordOperation("自动反推跳过", message, "warning")', editor)

        card = styles.split(".retag-layer-card {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", card)
        self.assertIn("top: calc(100% + 11px);", card)
        body = styles.split(".retag-layer-body {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-y: auto;", body)
        self.assertIn("overscroll-behavior: contain;", body)

        self.assertIn('raw_meta.get("retagTagGroups")', service)
        self.assertIn('raw_meta.get("retagTagTranslations")', service)
        self.assertIn('raw_meta.get("tagTranslations")', service)
        self.assertIn('raw_meta.get("retagLayerModes")', service)
        self.assertIn('raw_meta.get("retagLayerExpanded", False)', service)
        self.assertIn('payload.get("retagPreserveCategories")', main)
        self.assertIn('payload.get("retagDropCategories")', main)
        self.assertIn("preserve_categories=retag_preserve_categories", main)
        self.assertIn("drop_categories=retag_drop_categories", main)
        self.assertIn("await retriever.lookup_tags(tags)", main)
        self.assertIn('"tagTranslations": tag_translations', main)
        self.assertIn("tag_translation_callback=self._canvas_translate_tags", main)
        self.assertIn("async def _canvas_translate_tags", main)

    def test_image_nodes_have_fullscreen_viewer(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        main = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn('id="imageViewer"', html)
        self.assertIn('class="image-viewer layout-bottom"', html)
        self.assertIn('class="image-viewer-image-frame"', html)
        self.assertIn('id="imageViewerDetails"', html)
        self.assertIn('id="imageViewerDetailsToggle"', html)
        self.assertIn('id="imageViewerTags"', html)
        self.assertNotIn('id="imageViewerChineseTags"', html)
        self.assertNotIn('id="imageViewerPrompt"', html)
        self.assertNotIn('id="imageViewerPromptSection"', html)
        self.assertNotIn("提示词 / Prompt", html)
        self.assertIn("Prompt Tags / 提示词标签", html)
        self.assertNotIn("<span>Tags 标签</span>", html)
        self.assertIn('aria-label="折叠 Prompt Tags"', html)
        self.assertNotIn("中文 Tags / Chinese Tags", html)
        self.assertIn('class="image-viewer-tag-grid" role="group" aria-label="可复制的 Prompt Tags" data-copy-text=""', html)
        self.assertNotIn('id="imageViewerCaption"', html)
        self.assertNotIn('id="imageViewerArtist"', html)
        self.assertNotIn('id="imageViewerDimensions"', html)
        self.assertNotIn('id="imageViewerClose"', html)
        self.assertNotIn('makeAction("maximize-2", "放大查看"', editor)
        self.assertIn('data-copy-target="imageViewerTags"', html)
        self.assertNotIn('data-copy-target="imageViewerChineseTags"', html)
        self.assertNotIn('data-copy-target="imageViewerPrompt"', html)
        self.assertIn("function openImageViewer", editor)
        self.assertIn("function preferredImageViewerLayout", editor)
        self.assertIn("function applyImageViewerLayout", editor)
        self.assertIn('window.matchMedia("(max-width: 760px)").matches', editor)
        self.assertIn('return window.innerWidth >= 1100 ? "side" : "bottom"', editor)
        self.assertIn("els.imageViewerImage.naturalWidth", editor)
        self.assertIn("setImageViewerDetailsCollapsed", editor)
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
        self.assertIn('frame.setAttribute("aria-label", "放大图片并查看 Tags")', editor)
        self.assertNotIn("放大图片并查看提示词", editor)
        self.assertIn("function imageViewerPointHitsRenderedImage", editor)
        self.assertIn("function syncImageViewerFrameSize", editor)
        self.assertIn("function scheduleImageViewerFrameSync", editor)
        self.assertIn("viewerBottomLayoutLock: null", editor)
        self.assertIn("function lockImageViewerBottomLayout", editor)
        self.assertIn("function clearImageViewerBottomLayoutLock", editor)
        self.assertIn("function applyImageViewerBottomLayoutLock", editor)
        self.assertIn("lockImageViewerBottomLayout();", editor)
        self.assertIn("if (applyImageViewerBottomLayoutLock()) return;", editor)
        self.assertIn('frame.style.width = `${frameWidth}px`', editor)
        self.assertIn('frame.style.height = `${frameHeight}px`', editor)
        self.assertIn('els.imageViewerDetails.style.width = `${frameWidth}px`', editor)
        self.assertIn('els.imageViewerDetails.style.maxWidth = `${frameWidth}px`', editor)
        self.assertIn("syncImageViewerFrameSize(true)", editor)
        self.assertIn(
            'event.target.closest(".image-viewer-details, .image-viewer-place-btn")',
            editor,
        )
        self.assertIn("imageViewerPointHitsRenderedImage(event.clientX, event.clientY)", editor)
        self.assertIn("function copyViewerText", editor)
        self.assertNotIn("function isPureEnglishPrompt", editor)
        self.assertIn("function hydrateImageViewerChineseTags", editor)
        self.assertIn("function renderImageViewerTags", editor)
        self.assertIn("function stripImageViewerControlTags", editor)
        self.assertIn("function splitImageViewerPromptTokens", editor)
        self.assertIn("function imageViewerWeightedTokenParts", editor)
        self.assertIn("const tags = stripImageViewerControlTags(", editor)
        self.assertIn('meta.tags || meta.finalPrompt || "",', editor)
        self.assertIn('meta.artist || "",', editor)
        self.assertIn("retagControlPrompts: []", editor)
        self.assertIn('"retagControlPrompts": self.plugin_config.get_retag_control_prompts()', main)
        self.assertIn('bridge.apiPost("canvas/tags/translate", { tags })', editor)
        self.assertNotIn("els.imageViewerChineseTags", editor)
        self.assertIn("els.imageViewerTags.dataset.copyText = rawTags", editor)
        self.assertIn("target?.dataset.copyText?.trim()", editor)
        self.assertIn('chip.textContent = cnName ? `${tag} / ${cnName}` : tag', editor)
        self.assertIn('const chip = document.createElement("button")', editor)
        self.assertIn("chip.dataset.copyText = tag", editor)
        self.assertIn('chip.setAttribute("aria-label", `复制英文 Tag：${tag}`)', editor)
        self.assertIn('copyPlainText(tag, `复制英文 Tag：${tag}`', editor)
        self.assertIn(".image-viewer {", styles)
        viewer_stage = styles.split("\n.image-viewer-stage {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%;", viewer_stage)
        self.assertIn("max-width: 1600px;", viewer_stage)
        self.assertIn("height: 100%;", viewer_stage)
        self.assertIn("min-height: 0;", viewer_stage)
        self.assertIn("grid-template-rows: minmax(0, 1fr) auto;", viewer_stage)
        image_frame_html = html.split('class="image-viewer-image-frame"', 1)[1].split("</div>", 1)[0]
        self.assertIn('id="imageViewerPlaceBtn"', image_frame_html)
        image_frame = styles.split("\n.image-viewer-image-frame {", 1)[1].split("}", 1)[0]
        self.assertIn("position: relative;", image_frame)
        self.assertIn("height: 100%;", image_frame)
        self.assertIn("min-height: 0;", image_frame)
        self.assertIn("overflow: hidden;", image_frame)
        viewer_image = styles.split("\n.image-viewer-stage img {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 100%;", viewer_image)
        self.assertIn("height: 100%;", viewer_image)
        self.assertIn("min-width: 0;", viewer_image)
        self.assertIn("min-height: 0;", viewer_image)
        self.assertIn("object-fit: contain;", viewer_image)
        self.assertIn("border-radius: 12px;", viewer_image)
        viewer_details = styles.split("\n.image-viewer-details {", 1)[1].split("}", 1)[0]
        self.assertIn("border-radius: 12px;", viewer_details)
        self.assertIn("align-content: start;", viewer_details)
        self.assertIn("scrollbar-color: rgba(148, 163, 184, .42) transparent;", viewer_details)
        self.assertIn("scrollbar-gutter: auto;", viewer_details)
        self.assertIn("scrollbar-width: thin;", viewer_details)
        self.assertNotIn("calc(100vh - 300px)", styles)
        self.assertNotIn("calc(100vh - 310px)", styles)
        bottom_viewer = styles.split(".image-viewer.layout-bottom .image-viewer-stage {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex;", bottom_viewer)
        self.assertIn("flex-direction: column;", bottom_viewer)
        self.assertIn("justify-content: center;", bottom_viewer)
        bottom_frame = styles.split(".image-viewer.layout-bottom .image-viewer-image-frame {", 1)[1].split("}", 1)[0]
        self.assertIn("flex: 0 1 auto;", bottom_frame)
        self.assertIn(".image-viewer.layout-side .image-viewer-stage", styles)
        side_viewer = styles.split(".image-viewer.layout-side .image-viewer-stage {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex;", side_viewer)
        self.assertIn("width: fit-content;", side_viewer)
        self.assertIn("max-width: 100%;", side_viewer)
        self.assertIn("height: 100%;", side_viewer)
        self.assertIn("align-items: stretch;", side_viewer)
        self.assertIn("gap: 12px;", side_viewer)
        side_frame = styles.split(".image-viewer.layout-side .image-viewer-image-frame {", 1)[1].split("}", 1)[0]
        self.assertIn("aspect-ratio: var(--viewer-image-aspect, 2 / 3);", side_frame)
        self.assertIn("flex: 0 1 auto;", side_frame)
        side_details = styles.split(".image-viewer.layout-side .image-viewer-details {", 1)[1].split("}", 1)[0]
        self.assertIn("display: flex;", side_details)
        self.assertIn("flex-direction: column;", side_details)
        self.assertIn("align-self: stretch;", side_details)
        place_button = styles.split("\n.image-viewer-place-btn {", 1)[1].split("}", 1)[0]
        self.assertIn("position: absolute;", place_button)
        self.assertIn("bottom: 16px;", place_button)
        self.assertIn("min-width: 112px;", place_button)
        self.assertIn("height: 30px;", place_button)
        self.assertIn("background: rgba(248, 250, 252, .68);", place_button)
        self.assertIn("transform: translateX(-50%);", place_button)
        self.assertIn(".image-viewer-details-toggle {", styles)
        details_toggle = styles.split("\n.image-viewer-details-toggle {", 1)[1].split("}", 1)[0]
        self.assertIn("min-height: 22px;", details_toggle)
        self.assertIn("justify-content: flex-end;", details_toggle)
        self.assertIn(".image-viewer-details.collapsed .image-viewer-copy", styles)
        self.assertIn(".image-viewer-copy[hidden]", styles)
        self.assertIn(".image-viewer-tag-grid {", styles)
        self.assertIn(".image-viewer-tag-chip {", styles)
        self.assertIn(".image-viewer-tag-chip.bilingual", styles)
        tag_chip = styles.split("\n.image-viewer-tag-chip {", 1)[1].split("}", 1)[0]
        self.assertIn("cursor: pointer;", tag_chip)
        self.assertIn("appearance: none;", tag_chip)
        self.assertIn(".image-viewer-tag-chip:focus-visible", styles)
        self.assertNotIn(".image-viewer-heading", styles)
        self.assertNotIn("#imageViewerArtist", styles)
        self.assertIn("scrollbar-width: thin;", styles)
        self.assertIn(".image-viewer-tag-grid::-webkit-scrollbar-thumb", styles)
        self.assertIn(".image-viewer-tag-grid::-webkit-scrollbar-button", styles)
        self.assertIn(".image-viewer-details::-webkit-scrollbar-thumb", styles)
        self.assertIn(".image-viewer-details::-webkit-scrollbar-button", styles)
        mobile_styles = styles.split("@media (max-width: 620px) {", 1)[1].split(
            "@media (prefers-reduced-motion", 1
        )[0]
        mobile_bottom_details = mobile_styles.split(
            ".image-viewer.layout-bottom .image-viewer-details {", 1
        )[1].split("}", 1)[0]
        self.assertIn("min-height: min(38vh, 300px);", mobile_bottom_details)
        self.assertIn("max-height: min(38vh, 300px);", mobile_bottom_details)
        tag_grid = styles.split("\n.image-viewer-tag-grid {", 1)[1].split("}", 1)[0]
        self.assertIn("-webkit-user-select: none;", tag_grid)
        self.assertIn("user-select: none;", tag_grid)
        self.assertNotIn("user-select: text;", tag_grid)
        self.assertNotIn(".raw-toggle:focus-within::after", styles)
        self.assertIn(".raw-toggle:has(input:focus-visible)::after", styles)
        self.assertIn('raw.addEventListener("click", (event) => {', editor)
        self.assertIn("if (event.detail > 0) raw.blur();", editor)

    def test_library_preloads_and_uses_click_preview_without_direct_drag(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        zip_utils = (PAGE_ROOT / "zip-utils.js").read_text(encoding="utf-8")

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
        self.assertIn("function attachLibraryImagePreview", editor)
        self.assertNotIn("function attachLibraryImageDrag", editor)
        self.assertNotIn("function isCanvasDropPoint", editor)
        preview_body = editor.split("function attachLibraryImagePreview", 1)[1].split(
            "async function openLibraryImageViewer", 1
        )[0]
        self.assertIn("openLibraryImageViewer(item);", preview_body)
        self.assertNotIn('addEventListener("pointerdown"', preview_body)
        self.assertIn("placeImageAssetOnCanvas(", editor)
        self.assertNotIn('card.addEventListener("click", () => addImageAssetToCanvas(item))', editor)
        self.assertIn('thumb.style.aspectRatio = `${item.width} / ${item.height}`', editor)
        self.assertIn("renderImageAssetCard(item, els.assetGrid)", editor)
        # 桌面端和移动端都使用同一个全宽素材库，不再有紧凑/展开两套布局。
        self.assertNotIn("compact-layout", styles)
        self.assertIn("grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));", styles)
        self.assertIn("object-fit: contain;", styles)
        # 卡片按面板实宽计算固定高度，网格行保持 auto，让懒加载提示不会占满整张卡片。
        asset_grid = styles.split(".asset-grid {", 1)[1].split("}", 1)[0]
        self.assertIn("padding: 8px;", asset_grid)
        self.assertIn("border-radius: var(--asset-panel-inner-radius);", asset_grid)
        self.assertIn("scrollbar-gutter: auto;", asset_grid)
        asset_empty = styles.split(".asset-empty {", 1)[1].split("}", 1)[0]
        self.assertIn("padding: 8px;", asset_empty)
        self.assertIn("border-radius: var(--asset-panel-inner-radius);", asset_empty)
        self.assertIn("grid-auto-rows: auto;", styles)
        self.assertIn("height: var(--asset-card-height, 148px);", styles)
        self.assertIn("function updateAssetGridMetrics()", editor)
        self.assertIn('els.assetGrid.querySelectorAll(".asset-stack-card").length', editor)
        self.assertIn("Math.max(minimumColumns, Math.min(stackCount, 6))", editor)
        self.assertIn('els.assetGrid.style.gridAutoRows = `${Math.ceil(exactTileWidth)}px`', editor)
        self.assertIn('els.assetGrid.style.removeProperty("grid-auto-rows")', editor)
        self.assertIn('els.assetGrid.style.setProperty("--asset-card-height"', editor)
        self.assertIn("window.requestAnimationFrame(updateAssetGridMetrics);", editor)
        self.assertIn('card.title = "点击预览"', editor)
        self.assertIn('id="assetRefreshBtn"', html)
        self.assertIn("assetRefreshBtn", editor)
        self.assertNotIn("asset-card-footer", editor)
        self.assertNotIn("asset-thumb-source", editor)
        self.assertNotIn("asset-card-name", styles)
        self.assertIn("asset-artist-badge", editor)
        image_card_body = editor.split("function renderImageAssetCard", 1)[1].split(
            "function attachLibraryImagePreview", 1
        )[0]
        self.assertNotIn("asset-artist-badge", image_card_body)
        image_thumb = styles.split(".asset-image-card .asset-thumb img {", 1)[1].split("}", 1)[0]
        self.assertIn("object-fit: cover;", image_thumb)
        self.assertIn("const debugRect", editor)
        self.assertIn("closeImageViewer();", editor)
        self.assertIn("const nodeHeight = estimatedImageNodeHeight(nodeWidth, item.width, item.height);", editor)
        self.assertIn("point.y - nodeHeight / 2", editor)
        self.assertIn(
            "normalizeNaiSeed(node.meta?.seed) || normalizeNaiSeed(node.meta?.retagSeed)",
            editor,
        )
        self.assertIn("function alignAssetPanel()", editor)
        self.assertIn("function alignedPanelEdges()", editor)
        self.assertIn("buttonRect.left", editor)
        self.assertIn('els.assetPanel.style.width = `${Math.max(0, panelRight - panelLeft)}px`', editor)
        self.assertIn("topbarRect.bottom - viewportRect.top + gap", editor)
        align_body = editor.split("function alignAssetPanel()", 1)[1].split(
            "function updateAssetGridMetrics", 1
        )[0]
        self.assertIn("panelLeft - viewportRect.left", align_body)
        self.assertIn("const panelRight = Math.min(viewportRect.right - 12, topbarRect.right);", align_body)
        self.assertIn("const panelLeft = Math.max(viewportRect.left + 12, topbarRect.left);", align_body)
        self.assertNotIn("minimapRect", align_body)
        self.assertIn("alignDebugBar();", editor)
        self.assertIn("function alignDebugBar()", editor)
        self.assertIn("new ResizeObserver(scheduleOverlayAlignment)", editor)
        self.assertIn('document.body.classList.toggle("asset-library-open", open)', editor)
        asset_library_topbar = styles.split(".asset-library-open .topbar {", 1)[1].split("}", 1)[0]
        self.assertIn("box-shadow: none;", asset_library_topbar)
        self.assertNotIn("body.asset-library-open .minimap", styles)
        self.assertIn("width: auto;", styles.split(".asset-panel {", 1)[1].split("}", 1)[0])
        self.assertIn("max-width: none;", styles.split(".asset-panel {", 1)[1].split("}", 1)[0])
        self.assertNotIn(".asset-image-remove {", styles)
        self.assertIn('id="assetSelectModeBtn"', html)
        self.assertIn('id="assetLibraryCount"', html)
        self.assertIn('id="assetViewAllBtn"', html)
        self.assertNotIn('id="assetViewFavoritesBtn"', html)
        self.assertIn('id="assetViewRecentBtn"', html)
        self.assertIn('id="assetAllCount"', html)
        self.assertNotIn('id="assetFavoritesCount"', html)
        self.assertIn('id="assetRecentCount"', html)
        self.assertIn('id="assetStackTrail"', html)
        self.assertIn('id="assetStackTrailLabel"', html)
        self.assertIn("返回全部素材", html)
        self.assertNotIn('id="assetExpandBtn"', html)
        self.assertIn('id="assetPlaceSelectedBtn"', html)
        self.assertIn('id="assetArchiveSelectedBtn"', html)
        self.assertIn('id="assetDeleteCancel"', html)
        self.assertIn('id="assetDeleteConfirm"', html)
        self.assertLess(html.index('id="assetPlaceSelectedBtn"'), html.index('id="assetArchiveSelectedBtn"'))
        self.assertLess(html.index('id="assetArchiveSelectedBtn"'), html.index('id="assetDeleteConfirm"'))
        self.assertLess(html.index('id="assetDeleteConfirm"'), html.index('id="assetDeleteCancel"'))
        self.assertIn('id="assetDeleteModal"', html)
        self.assertIn('id="assetDeleteModalTitle"', html)
        self.assertIn('id="assetDeleteModalText"', html)
        self.assertIn('id="confirmAssetDeleteBtn"', html)
        self.assertIn('id="cancelAssetDeleteBtn"', html)
        asset_delete_modal = html.split('id="assetDeleteModal"', 1)[1].split("</section>", 1)[0]
        self.assertLess(
            asset_delete_modal.index('id="confirmAssetDeleteBtn"'),
            asset_delete_modal.index('id="cancelAssetDeleteBtn"'),
        )
        clear_modal = html.split('id="clearModal"', 1)[1].split("</section>", 1)[0]
        self.assertLess(clear_modal.index('id="confirmClearBtn"'), clear_modal.index('id="cancelClearBtn"'))
        self.assertIn('<span>多选</span>', html)
        self.assertNotIn('id="assetDeleteToggle"', html)
        self.assertNotIn(".asset-delete-toggle", styles)
        self.assertLess(html.index('id="assetGrid"'), html.index('class="asset-delete-toolbar"'))
        self.assertIn("selectedAssetIds: new Set()", editor)
        self.assertIn("placingAssets: false", editor)
        self.assertIn("archivingAssets: false", editor)
        self.assertIn("pendingAssetDeleteIds: []", editor)
        self.assertIn("function toggleAssetGroupSelection", editor)
        self.assertIn("toggleAssetGroupSelection(card, group);", editor)
        self.assertIn("async function placeSelectedLibraryAssetsOnCanvas()", editor)
        self.assertIn("async function archiveSelectedLibraryAssets()", editor)
        self.assertIn("els.assetPlaceSelectedBtn.hidden = primaryView", editor)
        self.assertIn("function deleteSelectedLibraryAssets()", editor)
        self.assertIn("function openAssetDeleteModal()", editor)
        self.assertIn("function closeAssetDeleteModal", editor)
        self.assertIn('els.assetDeleteConfirm.addEventListener("click", openAssetDeleteModal)', editor)
        self.assertIn('els.confirmAssetDeleteBtn.addEventListener("click", deleteSelectedLibraryAssets)', editor)
        self.assertIn("const ids = [...state.pendingAssetDeleteIds]", editor)
        self.assertIn("未被画布引用的原图文件可能一并清理", editor)
        self.assertIn("ASSET_LIBRARY_PREFS_KEY", editor)
        self.assertIn("function updateAssetLibraryModeUI()", editor)
        self.assertNotIn("function toggleAssetFavorite(item)", editor)
        self.assertNotIn("assetFavorites", editor)
        self.assertIn("function markAssetRecent(item", editor)
        self.assertIn("function renderAssetStackCard(group", editor)
        self.assertIn("function closeAssetStack()", editor)
        self.assertIn('els.assetStackTrail?.addEventListener("click"', editor)
        self.assertNotIn("function renderAssetStackBack", editor)
        self.assertNotIn("renderAssetStackBack(group, els.assetGrid)", editor)
        self.assertIn('label: "原始提示词"', editor)
        self.assertNotIn('label: "未分类"', editor)
        self.assertIn('detail: "未标注画师"', editor)
        self.assertIn("const stackView = groups.length > 0", editor)
        self.assertIn("groups.forEach((group) => renderAssetStackCard(group, els.assetGrid))", editor)
        self.assertIn('els.assetLibraryCount.textContent = state.assetLibraryView === "all"', editor)
        delete_mode_body = editor.split("function setAssetDeleteMode", 1)[1].split(
            "function updateAssetDeleteControls", 1
        )[0]
        self.assertNotIn("renderAssetLibrary()", delete_mode_body)
        self.assertIn('card.classList.remove("selected")', delete_mode_body)
        self.assertIn('els.assetSelectModeBtn.setAttribute("aria-pressed"', delete_mode_body)
        self.assertIn('canvas/library/image/delete', editor)
        self.assertIn(".asset-select-indicator", styles)
        self.assertIn(".asset-delete-buttons", styles)
        self.assertIn(".asset-place-selected", styles)
        self.assertIn(".asset-archive-selected", styles)
        place_selected = styles.split("\n.asset-place-selected {", 1)[1].split("}", 1)[0]
        archive_selected = styles.split("\n.asset-archive-selected {", 1)[1].split("}", 1)[0]
        self.assertIn("background: #fffbeb;", place_selected)
        self.assertIn("color: #a16207;", place_selected)
        self.assertIn("background: #f0fdf4;", archive_selected)
        self.assertIn("color: #15803d;", archive_selected)
        self.assertIn(".asset-panel.delete-mode .asset-image-card.selected", styles)
        self.assertIn(".asset-panel.delete-mode .asset-stack-card.selected", styles)
        self.assertIn(".asset-stack-card {", styles)
        asset_stack_card = styles.split("\n.asset-stack-card {", 1)[1].split("}", 1)[0]
        self.assertIn("height: 100%;", asset_stack_card)
        asset_stack_count = styles.split("\n.asset-stack-count {", 1)[1].split("}", 1)[0]
        self.assertIn("top: auto;", asset_stack_count)
        self.assertIn("bottom: 10px;", asset_stack_count)
        self.assertIn(".asset-stack-trail {", styles)
        self.assertNotIn(".asset-stack-back {", styles)
        asset_trail = styles.split("\n.asset-stack-trail {", 1)[1].split("}", 1)[0]
        self.assertIn("display: inline-flex;", asset_trail)
        self.assertIn("cursor: pointer;", asset_trail)
        self.assertIn("max-width: 100%;", asset_trail)
        self.assertIn('classList.toggle("stack-open", !!group)', editor)
        stack_open_trail = styles.split(
            ".asset-library-modes.stack-open .asset-stack-trail {", 1
        )[1].split("}", 1)[0]
        self.assertIn("width: 100%;", stack_open_trail)
        self.assertIn("flex: 1 1 100%;", stack_open_trail)
        hidden_asset_trail = styles.split("\n.asset-stack-trail[hidden] {", 1)[1].split("}", 1)[0]
        self.assertIn("display: none;", hidden_asset_trail)
        self.assertIn(".asset-stack-cover::before", styles)
        self.assertIn(".asset-artist-badge {", styles)
        self.assertNotIn(".asset-favorite-btn {", styles)
        self.assertNotIn('name.className = "asset-card-name"', editor)
        self.assertIn("align-self: start;", styles)
        self.assertIn(".asset-grid.empty", styles)
        self.assertNotIn("ASSET_UI_KEY", editor)
        self.assertIn("ASSET_RENDER_BATCH", editor)
        self.assertIn("new IntersectionObserver", editor)
        self.assertIn("rootMargin: \"240px 0px\"", editor)
        self.assertNotIn('id="assetPanelClose"', html)
        self.assertIn('id="imageViewerPlaceBtn"', html)
        self.assertIn(".image-viewer-place-btn {", styles)
        self.assertIn("display: inline-flex;", styles)
        self.assertIn("viewerLibraryAsset: null", editor)
        self.assertIn('{ libraryAsset: item, operationLabel: "预览素材" }', editor)
        self.assertIn("els.imageViewerPlaceBtn.addEventListener", editor)
        self.assertIn("els.assetPlaceSelectedBtn.addEventListener", editor)
        self.assertIn("els.assetArchiveSelectedBtn.addEventListener", editor)
        self.assertIn("const placed = await placeImageAssetOnCanvas(item, worldCenter())", editor)
        self.assertIn("if (!placed) return", editor)
        place_body = editor.split("async function placeImageAssetOnCanvas", 1)[1].split(
            "async function saveImageToLibrary", 1
        )[0]
        self.assertNotIn("setAssetPanel(false)", place_body)
        node_factory = editor.split("function createLibraryImageNode", 1)[1].split(
            "function selectedLibraryAssetsInDisplayOrder", 1
        )[0]
        self.assertIn("seed: normalizeNaiSeed(item.seed)", node_factory)
        self.assertIn('retagged: item.source === "retagged"', node_factory)
        batch_place_body = editor.split("async function placeSelectedLibraryAssetsOnCanvas", 1)[1].split(
            "async function placeImageAssetOnCanvas", 1
        )[0]
        self.assertEqual(batch_place_body.count("pushHistory();"), 1)
        self.assertIn("Math.min(4, Math.ceil(Math.sqrt(layout.length)))", batch_place_body)
        self.assertIn("state.nodes.push(...nodes)", batch_place_body)
        self.assertIn("rowStartX = center.x - rowWidth / 2", batch_place_body)
        archive_body = editor.split("async function archiveSelectedLibraryAssets", 1)[1].split(
            "async function placeSelectedLibraryAssetsOnCanvas", 1
        )[0]
        archive_filename_body = editor.split("function libraryArchiveFilename", 1)[1].split(
            "async function archiveSelectedLibraryAssets", 1
        )[0]
        self.assertNotIn("bestnai", archive_filename_body.lower())
        self.assertIn('const label = groups.length === 1', archive_filename_body)
        self.assertIn('return `${label}_${dateStamp}_${timeStamp}.zip`', archive_filename_body)
        self.assertIn('name: "library-manifest.json"', archive_body)
        self.assertIn("uniqueZipPath(", archive_body)
        self.assertIn("downloadBlob(createZipBlob(entries)", archive_body)
        self.assertIn("export function createZipBlob", zip_utils)
        self.assertIn("export function decodeDataUrl", zip_utils)
        self.assertIn("export function uniqueZipPath", zip_utils)
        self.assertNotIn("asset-thumb-seed", editor)
        self.assertNotIn(".asset-thumb-seed", styles)
        self.assertNotIn(".asset-image-card::before", styles)

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
        open_position = editor.split("function findOpenGeneratedPosition", 1)[1].split(
            "function findNextGeneratedPosition", 1
        )[0]
        self.assertIn("const horizontalGap = 64", open_position)
        self.assertIn("candidate.x = Math.max(", open_position)
        self.assertNotIn("candidate.y = Math.max", open_position)
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
        self.assertIn('id="board" class="board" tabindex="-1"', html)
        self.assertIn("function focusCanvasSurface()", editor)
        self.assertIn('if (event.pointerType !== "touch") focusCanvasSurface();', editor)
        self.assertIn("deleteNodes(selectedNodeIds());\n    focusCanvasSurface();", editor)
        self.assertNotIn('id="saveSelectedPromptBtn"', html)
        self.assertNotIn("saveSelectedPrompt", editor)
        self.assertNotIn(".asset-save-prompt", styles)

    def test_asset_library_owns_wheel_and_has_no_direct_drag_ghost(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("function nodeEditorOwnsWheel(target)", editor)
        self.assertIn('els.assetPanel.addEventListener("wheel"', editor)
        self.assertIn("event.stopPropagation();", editor)
        self.assertNotIn("grabOffsetX: event.clientX - cardRect.left", editor)
        self.assertNotIn("grabOffsetY: event.clientY - cardRect.top", editor)
        self.assertNotIn("asset-drag-ghost", editor)
        self.assertNotIn(".asset-drag-ghost {", styles)
        self.assertIn("overscroll-behavior: contain;", styles)

    def test_plugin_metadata_and_astrbot_compatibility_are_exposed(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        metadata = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
        constants = (ROOT / "constants.py").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('src="./plugin-logo.webp"', html)
        self.assertNotIn('id="pluginRepoLink"', html)
        self.assertIn("version: 3.3.8", metadata)
        self.assertIn('PLUGIN_VERSION = "3.3.8"', constants)
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
        self.assertIn('id="assetLibraryBtn"', html)
        self.assertIn('data-lucide="images"', html)
        self.assertIn(
            '"identity identity identity identity identity identity identity identity asset project"',
            mobile_styles,
        )
        self.assertIn('"tools tools tools tools tools tools tools tools tools tools"', mobile_styles)
        self.assertIn("#assetLibraryBtn", mobile_styles)
        self.assertIn("display: none;", mobile_styles)
        mobile_asset_active = mobile_styles.split("#mobileAssetLibraryBtn.active {", 1)[1].split("}", 1)[0]
        self.assertIn("background: var(--soft-2);", mobile_asset_active)
        self.assertIn("[els.assetLibraryBtn, els.mobileAssetLibraryBtn]", editor)
        self.assertIn("overflow-x: auto;", mobile_styles)
        self.assertIn("-webkit-overflow-scrolling: touch;", mobile_styles)
        self.assertIn("grid-template-columns: repeat(10, minmax(28px, 1fr));", mobile_styles)
        self.assertIn("grid-template-columns: minmax(0, 3fr) minmax(0, 7fr);", mobile_styles)
        self.assertIn(
            "grid-template-columns: minmax(0, 3fr) minmax(0, 2fr) minmax(0, 2fr);",
            mobile_styles,
        )
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", mobile_styles)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", mobile_styles)
        self.assertIn("#fitBtn {", mobile_styles)
        self.assertIn("grid-column: 1;", mobile_styles)
        self.assertIn("#undoBtn {", mobile_styles)
        self.assertIn("grid-column: 2;", mobile_styles)
        self.assertIn("#redoBtn {", mobile_styles)
        self.assertIn("grid-column: 3;", mobile_styles)
        self.assertIn("justify-self: center;", mobile_styles)
        self.assertIn("flex: 0 0 clamp(28px, 8vw, 32px);", mobile_styles)
        self.assertNotIn("display: contents;", mobile_styles)
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

    def test_canvas_scroll_is_state_driven_and_debug_body_owns_wheel(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("overflow: clip;", styles)
        self.assertIn('els.viewport.addEventListener("scroll", resetNativeCanvasScroll', editor)
        self.assertIn("event.stopPropagation();", editor.split(
            'els.debugBar?.addEventListener("wheel"', 1
        )[1].split("});", 1)[0])
        self.assertIn(
            'els.debugBar?.addEventListener("pointerdown", (event) => event.stopPropagation())',
            editor,
        )
        debug_body = styles.split(".debug-body {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-y: auto;", debug_body)
        self.assertIn("overscroll-behavior: contain;", debug_body)
        self.assertIn("-webkit-user-select: text;", debug_body)
        self.assertIn("user-select: text;", debug_body)

    def test_retag_cache_is_independent_of_handwritten_overlay(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        cache_body = editor.split("function cachedRetagResult", 1)[1].split(
            "function runPromptNode", 1
        )[0]
        input_body = editor.split('prompt.addEventListener("input"', 1)[1].split(
            'prompt.addEventListener("keydown"', 1
        )[0]

        self.assertNotIn("retagBasePrompt", cache_body)
        self.assertIn("clearTranslationCache(node);", input_body)
        self.assertNotIn("clearRetagCache(node);", input_body)
        self.assertIn("seed: retagged ? reusableRetagSeed(node) : undefined", editor)
        self.assertIn("The seed belongs to the source image", editor)

    def test_debug_bar_is_a_persistent_aligned_recorder(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        debug = styles.split(".debug-bar {", 1)[1].split("}", 1)[0]
        self.assertIn("bottom: 24px;", debug)
        self.assertIn("flex-direction: column-reverse;", debug)
        body = styles.split(".debug-bar-body {", 1)[1].split("}", 1)[0]
        self.assertIn("border-width: 0 0 1px;", body)
        render = editor.split("function renderDebugBar() {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        self.assertIn("els.debugBar.hidden = false;", render)
        self.assertIn('`操作记录 · ${latestText}`', render)
        self.assertIn("const OPERATION_LOG_KEY", editor)
        self.assertIn("persistOperationLog()", editor)
        self.assertIn("function alignDebugBar()", editor)
        self.assertIn("topbarRect.left - viewportRect.left", editor)
        self.assertIn('recordOperation(\n          "移动节点"', editor)
        self.assertIn('"调整节点大小",', editor)
        self.assertIn('recordOperation("调整图片大小"', editor)
        self.assertIn('`${state.selectedIds.length} 个节点`', editor)

    def test_canvas_uses_only_the_blank_background(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertNotIn('id="gridStyleBtn"', html)
        self.assertNotIn('id="gridStyleLabel"', html)
        self.assertNotIn("GRID_STYLE_KEY", editor)
        self.assertNotIn("GRID_STYLE_ORDER", editor)
        self.assertNotIn("applyGridStyle", editor)
        self.assertNotIn("cycleGridStyle", editor)
        self.assertNotIn("grid-style-", styles)
        board = styles.split(".board {", 1)[1].split("}", 1)[0]
        self.assertIn("background-image: none;", board)
        self.assertNotIn("radial-gradient", board)
        viewport = editor.split("function renderViewport()", 1)[1].split("}", 1)[0]
        self.assertNotIn("backgroundPosition", viewport)
        self.assertNotIn("backgroundSize", viewport)

    def test_minimap_is_removed_from_the_canvas(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertNotIn('id="minimap"', html)
        self.assertNotIn('id="minimapToggleBtn"', html)
        self.assertNotIn("minimap", html)
        self.assertNotIn("minimap", editor)
        self.assertNotIn("minimap", styles)
        self.assertIn('id="canvasArrangeBtn"', html)
        self.assertIn(".arrange-selection-btn", styles)

    def test_debug_bar_groups_prompt_merge_details(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn("function makeDebugMergeSummary(details, translations = {})", editor)
        self.assertIn('head.textContent = "提示词冲突处理"', editor)
        self.assertNotIn('"提示词冲突处理 / Prompt merge"', editor)
        self.assertIn('appendDebugTagGroup(section, "新增提示词", details.added', editor)
        self.assertIn('appendDebugTagGroup(section, "删除冲突", details.removed', editor)
        self.assertIn('appendDebugTagGroup(section, "保留原图", details.retained', editor)
        self.assertIn('appendDebugTagGroup(section, "重复去重", details.duplicates', editor)
        self.assertIn('["added", "新增", details.added]', editor)
        self.assertIn('["removed", "删除", details.removed]', editor)
        self.assertIn('["retained", "保留", details.retained]', editor)
        self.assertIn('["duplicates", "去重", details.duplicates]', editor)
        self.assertIn('identity: "角色"', editor)
        self.assertIn('clothing: "服装"', editor)
        self.assertNotIn('identity: "角色 / Identity"', editor)
        self.assertIn("bilingualRetagTagText(tag, translations)", editor)
        self.assertIn("item.className = `debug-merge-count is-${tone}`", editor)
        self.assertIn(".debug-merge-summary {", styles)
        self.assertIn(".debug-merge-category-row {", styles)
        merge_summary = styles.split(".debug-merge-summary {", 1)[1].split("}", 1)[0]
        merge_count = styles.split(".debug-merge-count {", 1)[1].split("}", 1)[0]
        merge_tag = styles.split(".debug-merge-tag {", 1)[1].split("}", 1)[0]
        self.assertIn("--debug-merge-radius: 8px;", merge_summary)
        self.assertIn("border-radius: var(--debug-merge-radius);", merge_summary)
        self.assertIn("border-radius: var(--debug-merge-radius);", merge_count)
        self.assertIn("border-radius: var(--debug-merge-radius);", merge_tag)
        for tone in ("added", "removed", "retained", "duplicates"):
            with self.subTest(tone=tone):
                self.assertIn(f".debug-merge-count.is-{tone} {{", styles)
                self.assertIn(f".debug-merge-group.is-{tone} .debug-merge-tag", styles)
                self.assertNotIn(f".debug-merge-group.is-{tone} .debug-merge-group-label", styles)

    def test_debug_bar_follows_prompt_selection_without_full_render(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        selection = editor.split("function setSelection(ids", 1)[1].split(
            "\nfunction ", 1
        )[0]
        render = editor.split("function renderDebugBar() {", 1)[1].split(
            "\nfunction ", 1
        )[0]
        recorder = editor.split("function recordRunDebug", 1)[1].split(
            "\nfunction ", 1
        )[0]

        self.assertIn("state.selectedId =", selection)
        self.assertIn("recordOperation(", selection)
        self.assertIn("if (els.debugBar) renderDebugBar();", editor)
        self.assertIn('selectedNode?.type === "image"', render)
        self.assertIn("linkedPrompts", render)
        self.assertIn(
            "linkedPrompts.find((item) => item.id === state.lastDebugNodeId)",
            render,
        )
        self.assertIn("lastDebugNodeId", render)
        self.assertIn("state.lastDebugNodeId = node.id;", recorder)

    def test_source_image_seed_and_tags_are_recovered_for_library_round_trip(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        self.assertIn("sourceImage.meta =", editor)
        self.assertIn("tags: retagPrompt,", editor)
        self.assertNotIn("tags: sourceImage.meta?.tags || retagPrompt", editor)
        self.assertIn("linkedRetag.retagPrompt", editor)
        self.assertIn("normalizeNaiSeed(node?.meta?.seed)", editor)
        self.assertIn("normalizeNaiSeed(item.seed)", editor)
        self.assertIn("meta.tags || meta.finalPrompt || meta.retagPrompt", editor)

    def test_removing_or_replacing_image_source_clears_retag_cache(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        delete_body = editor.split("function deleteConnection", 1)[1].split(
            "function duplicateNode", 1
        )[0]
        replace_body = editor.split("function attachConnectionPort", 1)[1].split(
            "function renderViewport", 1
        )[0]

        self.assertIn("clearRetagCache(target);", delete_body)
        self.assertIn("clearRetagCache(destinationNode);", replace_body)
        self.assertIn("source-specific retag state", editor)

    def test_quick_toolbar_is_icon_only(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        toolbar = html.split('id="quickToolbar"', 1)[1].split("</nav>", 1)[0]
        items = toolbar.split('class="toolbar-items toolbar-create-tools"', 1)[1].split("</div>", 1)[0]

        # 工具栏只留图标，文字标签靠 title / aria-label 提供
        self.assertNotIn("<span>", items)
        for button_id, label in (
            ("addImageBtn", "上传图片"),
            ("addPromptBtn", "添加提示词节点"),
            ("addNoteBtn", "添加备注节点"),
        ):
            with self.subTest(button=button_id):
                self.assertIn(f'id="{button_id}"', items)
                self.assertIn(f'aria-label="{label}"', items)
        self.assertEqual(items.count("icon-only"), 3)
        self.assertNotIn('id="assetLibraryBtn"', items)
        self.assertIn('class="toolbar-group toolbar-history-group"', toolbar)
        self.assertIn('class="toolbar-group toolbar-workspace-group"', toolbar)
        self.assertIn('class="toolbar-group toolbar-system-group"', toolbar)
        self.assertLess(toolbar.index('id="undoBtn"'), toolbar.index('id="assetLibraryBtn"'))
        self.assertLess(toolbar.index('id="assetLibraryBtn"'), toolbar.index('id="debugModeBtn"'))

        create_styles = styles.split(".toolbar-create-tools {", 1)[1].split("}", 1)[0]
        self.assertIn("display: none;", create_styles)
        mobile = styles.split("@media (max-width: 620px) {", 1)[1].split(
            "@media (prefers-reduced-motion", 1
        )[0]
        mobile_create = mobile.split(".toolbar-create-tools {", 1)[1].split("}", 1)[0]
        self.assertIn("display: grid;", mobile_create)
        toolbar_styles = styles.split(".toolbar {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow: visible;", toolbar_styles)

        # 图标固定 16px 且不参与压缩，最小按钮 28px 也放得下
        icon_styles = styles.split(".tool-btn svg {", 1)[1].split("}", 1)[0]
        self.assertIn("width: 16px;", icon_styles)
        self.assertIn("flex: 0 0 auto;", icon_styles)

        # 右键菜单仍保留文字，那里没有空间压力
        self.assertIn('id="contextAddImageBtn"', html)
        self.assertIn("<span>图片</span>", html)

    def test_prompt_card_bottom_hint_stays_inside_the_card(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
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

        self.assertNotIn(".prompt-advanced", styles)
        self.assertNotIn("function makeAdvancedPanel", editor)

    def test_resized_portrait_images_grow_with_their_width(self) -> None:
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")
        frame = styles.split(".image-preview-wrap {", 1)[1].split("}", 1)[0]
        image = styles.split(".image-preview-wrap img {", 1)[1].split("}", 1)[0]

        self.assertNotIn("max-height", frame)
        self.assertNotIn("max-height", image)
        self.assertIn("width: 100%;", image)
        self.assertIn("height: auto;", image)

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
        context_menu = editor.split(
            'els.viewport.addEventListener("contextmenu"', 1
        )[1].split("function dataTransferHasFiles", 1)[0]
        self.assertIn('const nodeElement = target?.closest(".node")', context_menu)
        self.assertIn("setNodeContextMenu(true, node, event.clientX, event.clientY)", context_menu)
        self.assertLess(
            context_menu.index('const nodeElement = target?.closest(".node")'),
            context_menu.index("setCanvasContextMenu(true"),
        )
        menu_styles = styles.split(".canvas-context-menu {", 1)[1].split("}", 1)[0]
        self.assertIn("position: fixed;", menu_styles)
        self.assertIn("border-radius: 18px;", menu_styles)

    def test_node_context_menu_matches_node_type_actions(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        styles = (PAGE_ROOT / "canvas.css").read_text(encoding="utf-8")

        self.assertIn('id="nodeContextMenu"', html)
        self.assertIn('id="nodeContextDuplicate"', html)
        self.assertIn('id="nodeContextDelete"', html)
        self.assertIn('id="nodeContextSaveImage"', html)
        self.assertIn('id="nodeContextDownloadImage"', html)
        self.assertEqual(html.count("data-image-only"), 2)
        node_menu = html.split('id="nodeContextMenu"', 1)[1].split("</div>", 1)[0]
        self.assertLess(node_menu.index('id="nodeContextSaveImage"'), node_menu.index('id="nodeContextDownloadImage"'))
        self.assertLess(node_menu.index('id="nodeContextDownloadImage"'), node_menu.index('id="nodeContextDuplicate"'))
        self.assertLess(node_menu.index('id="nodeContextDuplicate"'), node_menu.index('id="nodeContextDelete"'))
        self.assertIn('const imageNode = node.type === "image"', editor)
        self.assertIn('querySelectorAll("[data-image-only]")', editor)
        self.assertIn('duplicateNode(node.id)', editor)
        self.assertIn('deleteNode(node.id)', editor)
        self.assertIn('await saveImageToLibrary(node)', editor)
        self.assertIn('await downloadImage(node)', editor)
        self.assertIn(".canvas-context-menu button.danger {", styles)
        self.assertIn(".canvas-context-menu button:disabled {", styles)

        self.assertIn('id="selectionContextMenu"', html)
        self.assertIn('id="selectionContextArrange"', html)
        self.assertIn('id="selectionContextDelete"', html)
        self.assertIn('<span>整理选中</span>', html)
        self.assertIn('<span>删除选中</span>', html)
        context_menu = editor.split(
            'els.viewport.addEventListener("contextmenu"', 1
        )[1].split("function dataTransferHasFiles", 1)[0]
        self.assertIn("if (selectedNodeIds().length >= 2)", context_menu)
        self.assertIn("setSelectionContextMenu(true, event.clientX, event.clientY)", context_menu)
        self.assertLess(
            context_menu.index("if (selectedNodeIds().length >= 2)"),
            context_menu.index('const nodeElement = target?.closest(".node")'),
        )

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
        self.assertIn("extract_retag_mode", main)
        self.assertIn("_, prompt = extract_retag_mode(prompt)", main)
        self.assertIn("merge_retag_prompt_details", main)
        self.assertNotIn("mode=retag_mode", main)
        self.assertNotIn("retag_mode, prompt", main)
        self.assertIn("def _format_generation_progress", main)
        self.assertIn("followup_messages=show_messages", main)
        image_branch = main.split("        if image_src:", 1)[1].split(
            "        if not prompt:", 1
        )[0]
        self.assertIn("yield event.plain_result(retag_progress)", image_branch)
        self.assertIn("show_progress=False", image_branch)
        self.assertLess(
            image_branch.index("img_w, img_h = await read_image_size_any"),
            image_branch.index("yield event.plain_result(retag_progress)"),
        )
        self.assertLess(
            image_branch.index("yield event.plain_result(retag_progress)"),
            image_branch.index("retag_result = await self.image_retagger.retag_details"),
        )


class StudioPageTest(unittest.TestCase):
    """仿 NovelAI 的 Studio 工作区（studio.html / studio.css / studio.js）。"""

    def test_studio_loads_bridge_before_page_script(self) -> None:
        html = (PAGE_ROOT / "studio.html").read_text(encoding="utf-8")
        studio_script = '<script type="module" src="./studio.js"></script>'
        self.assertIn(BRIDGE_SDK, html)
        self.assertLess(html.index(BRIDGE_SDK), html.index(studio_script))
        self.assertIn('<link rel="stylesheet" href="./studio.css" />', html)
        self.assertIn('<script src="./vendor/lucide.js"></script>', html)

    def test_studio_script_waits_for_delayed_bridge(self) -> None:
        studio = (PAGE_ROOT / "studio.js").read_text(encoding="utf-8")
        self.assertIn("while (!window.AstrBotPluginPage", studio)

    def test_studio_uses_canvas_backend_routes(self) -> None:
        studio = (PAGE_ROOT / "studio.js").read_text(encoding="utf-8")
        self.assertIn('bridge.apiPost("canvas/generate"', studio)
        self.assertIn('bridge.apiGet("canvas/library"', studio)
        self.assertIn('bridge.apiGet("canvas/health"', studio)
        self.assertIn('bridge.apiGet("canvas/config"', studio)

    def test_studio_sends_extended_generation_params(self) -> None:
        studio = (PAGE_ROOT / "studio.js").read_text(encoding="utf-8")
        self.assertIn("negativePrompt", studio)
        self.assertIn("noiseSchedule", studio)
        self.assertIn("cfgRescale", studio)
        self.assertIn("sampler", studio)

    def test_studio_uses_dark_theme(self) -> None:
        styles = (PAGE_ROOT / "studio.css").read_text(encoding="utf-8")
        self.assertIn("color-scheme: dark", styles)

    def test_studio_hidden_attribute_beats_display_rules(self) -> None:
        # 查看器/加载层等浮层用 hidden 属性隐藏；若 display 规则压过 [hidden]，
        # 它们会从页面加载起就一直盖在界面上。
        styles = (PAGE_ROOT / "studio.css").read_text(encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", styles)

    def test_studio_and_editor_can_switch_to_each_other(self) -> None:
        html = (PAGE_ROOT / "editor.html").read_text(encoding="utf-8")
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        studio = (PAGE_ROOT / "studio.js").read_text(encoding="utf-8")
        self.assertIn('id="studioSwitchBtn"', html)
        self.assertIn('new URL("./studio.html"', editor)
        self.assertIn('new URL("./editor.html"', studio)

    def test_workspace_switch_forwards_auth_query_and_hash(self) -> None:
        # AstrBot 页面认证参数在 query 里，切换工作区必须原样转发，
        # 否则目标页面所有 bridge 请求都会返回「未授权」。
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        studio = (PAGE_ROOT / "studio.js").read_text(encoding="utf-8")
        for name, source in (("canvas.js", editor), ("studio.js", studio)):
            with self.subTest(page=name):
                self.assertIn("target.search = window.location.search;", source)
                self.assertIn("target.hash = window.location.hash;", source)

    def test_studio_handoff_places_image_node_on_canvas(self) -> None:
        editor = (PAGE_ROOT / "canvas.js").read_text(encoding="utf-8")
        studio = (PAGE_ROOT / "studio.js").read_text(encoding="utf-8")
        self.assertIn("bestnaiStudioHandoff", studio)
        self.assertIn("consumeStudioHandoff", editor)
        self.assertIn("await consumeStudioHandoff();", editor)

    def test_studio_uses_lucide_icons_and_toasts(self) -> None:
        html = (PAGE_ROOT / "studio.html").read_text(encoding="utf-8")
        studio = (PAGE_ROOT / "studio.js").read_text(encoding="utf-8")
        self.assertIn("data-lucide=", html)
        self.assertIn("lucide.createIcons", studio)
        self.assertIn('id="toastRegion"', html)


if __name__ == "__main__":
    unittest.main()

import { AssetCache } from "./asset-cache.js?v=4.6.34";
// Canvas component with explicit dependencies; no build step required.
export function createAssetLibrary({
  ASSET_LIBRARY_PREFS_KEY,
  ASSET_RECENT_LIMIT,
  ASSET_RENDER_BATCH,
  addNode,
  alignDebugBar,
  alignedPanelEdges,
  bridge,
  clamp,
  createZipBlob,
  decodeDataUrl,
  downloadBlob,
  els,
  encodeZipText,
  estimatedImageNodeHeight,
  findNode,
  fittedImageNodeWidth,
  hydrateImageGenerationMeta,
  icon,
  imageExtension,
  imageGenerationMeta,
  normalizeNaiSeed,
  normalizeRetagTagTranslations,
  openImageViewer,
  pushHistory,
  recordOperation,
  refreshIcons,
  renderAll,
  safeZipName,
  scheduleSave,
  setCanvasContextMenu,
  setDebugBarOpen,
  setNodeContextMenu,
  setProjectMenu,
  setSelection,
  setSelectionContextMenu,
  sourceImageSeed,
  state,
  toast,
  uid,
  uniqueZipPath,
  updateImageViewerSaveButton,
  worldCenter
}) {
  function persistAssetLibraryPreferences() {
    try {
      localStorage.setItem(ASSET_LIBRARY_PREFS_KEY, JSON.stringify({
        recent: state.assetRecent.slice(0, ASSET_RECENT_LIMIT),
        view: state.assetLibraryView,
      }));
    } catch (_) {
      // Embedded webviews may disable local storage; the in-memory state still works.
    }
  }

  function reconcileAssetLibraryPreferences() {
    const validIds = new Set((state.library.images || []).map((item) => String(item?.id || "")).filter(Boolean));
    const recent = state.assetRecent.filter((id) => validIds.has(id));
    const changed = recent.length !== state.assetRecent.length;
    state.assetRecent = recent;
    if (changed) persistAssetLibraryPreferences();
  }

  function assetLibraryVisibleItems() {
    const items = state.library.images || [];
    if (state.assetLibraryView === "all") return items;
    const byId = new Map(items.map((item) => [String(item?.id || ""), item]));
    return state.assetRecent.map((id) => byId.get(id)).filter(Boolean);
  }

  function assetLibraryStackViewGroups() {
    if (state.assetLibraryView !== "all" || state.assetStackKey) return [];
    return assetLibraryGroups(assetLibraryVisibleItems());
  }

  function assetGroupForItem(item) {
    const artist = String(item?.artist || "").trim();
    if (artist) {
      return {
        key: `artist:${artist.replace(/\s+/g, " ").toLocaleLowerCase()}`,
        label: artist,
        detail: "画师合集",
        unassigned: false,
      };
    }
    return {
      key: "artist:__unassigned__",
      label: "原始提示词",
      detail: "未标注画师",
      unassigned: true,
    };
  }

  function assetLibraryGroups(items) {
    const groups = new Map();
    (items || []).forEach((item) => {
      const group = assetGroupForItem(item);
      if (!groups.has(group.key)) groups.set(group.key, { ...group, items: [] });
      groups.get(group.key).items.push(item);
    });
    return [...groups.values()].sort((left, right) => Number(left.unassigned) - Number(right.unassigned));
  }

  function updateAssetLibraryModeUI() {
    const total = (state.library.images || []).length;
    const visible = assetLibraryVisibleItems().length;
    if (els.assetLibraryCount) {
      els.assetLibraryCount.textContent = state.assetLibraryView === "all"
        ? `已收录 ${total} 张`
        : `${visible} / ${total} 张`;
    }
    if (els.assetAllCount) els.assetAllCount.textContent = String(total);
    if (els.assetRecentCount) els.assetRecentCount.textContent = String(state.assetRecent.length);
    [
      [els.assetViewAllBtn, "all"],
      [els.assetViewRecentBtn, "recent"],
    ].forEach(([button, view]) => {
      if (!button) return;
      const active = state.assetLibraryView === view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    if (els.assetStackTrail) {
      const group = state.assetStackKey
        ? assetLibraryGroups(state.library.images).find((item) => item.key === state.assetStackKey)
        : null;
      els.assetStackTrail.hidden = !group;
      els.assetStackTrail.closest(".asset-library-modes")?.classList.toggle("stack-open", !!group);
      const label = group ? `返回全部素材 · ${group.label}` : "返回全部素材";
      if (els.assetStackTrailLabel) els.assetStackTrailLabel.textContent = label;
      els.assetStackTrail.title = label;
      els.assetStackTrail.setAttribute("aria-label", label);
    }
  }

  function setAssetLibraryView(view) {
    if (!["all", "recent"].includes(view)) return;
    if (state.assetDeleteMode) setAssetDeleteMode(false);
    state.assetLibraryView = view;
    state.assetStackKey = "";
    persistAssetLibraryPreferences();
    renderAssetLibrary();
    recordOperation("切换素材视图", view === "recent" ? "最近使用" : "全部素材");
  }

  function closeAssetStack() {
    const group = state.assetStackKey
      ? assetLibraryGroups(state.library.images).find((item) => item.key === state.assetStackKey)
      : null;
    if (!group) return;
    if (state.assetDeleteMode) setAssetDeleteMode(false);
    state.assetStackKey = "";
    updateAssetLibraryModeUI();
    renderAssetLibrary();
    recordOperation("收起素材堆", group.label);
  }

  function markAssetRecent(item, { render = true } = {}) {
    const id = String(item?.id || "").trim();
    if (!id) return;
    state.assetRecent = [id, ...state.assetRecent.filter((itemId) => itemId !== id)]
      .slice(0, ASSET_RECENT_LIMIT);
    persistAssetLibraryPreferences();
    updateAssetLibraryModeUI();
    if (render && state.assetLibraryView === "recent" && els.assetPanel.classList.contains("open")) {
      renderAssetLibrary();
    }
  }

  const previews = new AssetCache((id) => bridge.apiGet("canvas/asset", { id, preview: 1 }));
  const thumbnails = new AssetCache((id) => bridge.apiGet("canvas/asset/thumbnail", { id }), {
    maxEntries: 160, maxBytes: 8 * 1024 * 1024, concurrency: 4,
  });
  let thumbnailObserver = null;
  const thumbnailTasks = new WeakMap();

  function setLibraryData(library) {
    state.library = {
      images: (Array.isArray(library?.images) ? library.images : []).map((source) => {
        const item = { ...source };
        if (item.dataUrl) previews.remember(item.id, { dataUrl: item.dataUrl });
        delete item.dataUrl;
        return item;
      }),
      prompts: Array.isArray(library?.prompts) ? library.prompts : [],
    };
    reconcileAssetLibraryPreferences();
  }

  async function ensureLibraryImageData(item) {
    if (!item?.id) throw new Error("图片素材 ID 无效");
    if (item.dataUrl) {
      previews.remember(item.id, { dataUrl: item.dataUrl });
      delete item.dataUrl;
    }
    return (await previews.get(item.id)).dataUrl;
  }

  function observeThumbnail(target, load) {
    if (typeof IntersectionObserver === "undefined") {
      queueMicrotask(() => { if (target.isConnected) load(); });
      return;
    }
    if (!thumbnailObserver) {
      thumbnailObserver = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          thumbnailObserver.unobserve(entry.target);
          if (entry.target.isConnected) thumbnailTasks.get(entry.target)?.();
        });
      }, { root: els.assetGrid, rootMargin: "180px" });
    }
    thumbnailTasks.set(target, load);
    thumbnailObserver.observe(target);
  }

  async function loadLibrary(render = true) {
    try {
      const library = await bridge.apiGet("canvas/library");
      setLibraryData(library);
      if (render) renderAssetLibrary();
      return true;
    } catch (error) {
      toast(error.message || "素材库读取失败", "error");
      return false;
    }
  }

  function setAssetPanel(open) {
    setSelectionContextMenu(false);
    if (open) {
      setCanvasContextMenu(false);
      setNodeContextMenu(false);
      // 打开素材库时收起调试信息，避免两块大面板互相遮挡
      setDebugBarOpen(false);
    }
    if (open && !els.projectMenu.hidden) setProjectMenu(false);
    els.assetPanel.classList.toggle("open", open);
    document.body.classList.toggle("asset-library-open", open);
    [els.assetLibraryBtn, els.mobileAssetLibraryBtn].forEach((button) => {
      button.classList.toggle("active", open);
      button.setAttribute("aria-expanded", String(open));
    });
    if (!open) {
      if (els.imageViewer.hidden && state.viewerPendingLibraryAsset) {
        state.viewerOpenSequence = (state.viewerOpenSequence || 0) + 1;
        state.viewerPendingLibraryAsset = null;
      }
      thumbnailObserver?.disconnect();
      setAssetDeleteMode(false);
      recordOperation("关闭素材库");
      return;
    }
    alignAssetPanel();
    renderAssetLibrary();
    recordOperation("打开素材库", `已收录 ${state.library.images.length} 张素材`);
  }

  function setAssetDeleteMode(enabled) {
    const changed = state.assetDeleteMode !== !!enabled;
    state.assetDeleteMode = !!enabled;
    if (!state.assetDeleteMode) {
      state.selectedAssetIds.clear();
      els.assetGrid.querySelectorAll(".asset-card.selected").forEach((card) => {
        card.classList.remove("selected");
        card.setAttribute("aria-selected", "false");
      });
    }
    els.assetPanel.classList.toggle("delete-mode", state.assetDeleteMode);
    els.assetSelectModeBtn.classList.toggle("active", state.assetDeleteMode);
    els.assetSelectModeBtn.setAttribute("aria-pressed", String(state.assetDeleteMode));
    updateAssetDeleteControls();
    if (changed) recordOperation(state.assetDeleteMode ? "进入素材多选" : "退出素材多选");
  }

  function selectedAssetGroupCount(groups = assetLibraryStackViewGroups()) {
    return groups.filter((group) => (
      group.items.length > 0 && group.items.every((item) => state.selectedAssetIds.has(item.id))
    )).length;
  }

  function updateAssetDeleteControls() {
    const itemCount = state.selectedAssetIds.size;
    const groups = assetLibraryStackViewGroups();
    const primaryView = state.assetLibraryView === "all" && !state.assetStackKey;
    const groupCount = selectedAssetGroupCount(groups);
    const busy = state.deletingAssets || state.placingAssets || state.archivingAssets;
    els.assetDeleteActions.hidden = !state.assetDeleteMode;
    els.assetDeleteCount.textContent = primaryView ? `已选 ${groupCount} 组` : `已选 ${itemCount} 项`;
    els.assetPlaceSelectedBtn.hidden = primaryView;
    els.assetPlaceSelectedBtn.disabled = itemCount === 0 || busy;
    els.assetPlaceSelectedBtn.querySelector("span").textContent = state.placingAssets ? "加入中…" : "加入画布";
    els.assetArchiveSelectedBtn.disabled = itemCount === 0 || busy;
    els.assetArchiveSelectedBtn.querySelector("span").textContent = state.archivingAssets ? "压缩中…" : "压缩";
    els.assetDeleteConfirm.disabled = itemCount === 0 || busy;
    els.assetDeleteConfirm.querySelector("span").textContent = state.deletingAssets ? "删除中…" : "删除";
    els.assetDeleteCancel.disabled = busy;
    els.assetSelectModeBtn.disabled = busy;
  }

  function toggleAssetSelection(card, assetId) {
    if (state.selectedAssetIds.has(assetId)) state.selectedAssetIds.delete(assetId);
    else state.selectedAssetIds.add(assetId);
    card.classList.toggle("selected", state.selectedAssetIds.has(assetId));
    card.setAttribute("aria-selected", String(state.selectedAssetIds.has(assetId)));
    updateAssetDeleteControls();
  }

  function toggleAssetGroupSelection(card, group) {
    const ids = group.items.map((item) => item.id);
    const selected = ids.length > 0 && ids.every((id) => state.selectedAssetIds.has(id));
    ids.forEach((id) => {
      if (selected) state.selectedAssetIds.delete(id);
      else state.selectedAssetIds.add(id);
    });
    card.classList.toggle("selected", !selected);
    card.setAttribute("aria-selected", String(!selected));
    updateAssetDeleteControls();
  }

  function closeAssetDeleteModal({ restoreFocus = true, force = false } = {}) {
    if (state.deletingAssets && !force) return;
    els.assetDeleteModal.hidden = true;
    state.pendingAssetDeleteIds = [];
    els.confirmAssetDeleteBtn.disabled = false;
    els.confirmAssetDeleteBtn.textContent = "删除";
    els.cancelAssetDeleteBtn.disabled = false;
    if (restoreFocus && state.assetDeleteMode) els.assetDeleteConfirm.focus();
  }

  function openAssetDeleteModal() {
    const ids = [...state.selectedAssetIds];
    if (!ids.length || state.deletingAssets || state.placingAssets || state.archivingAssets) return;
    const primaryView = state.assetLibraryView === "all" && !state.assetStackKey;
    const groupCount = selectedAssetGroupCount();
    state.pendingAssetDeleteIds = ids;
    els.assetDeleteModalTitle.textContent = primaryView ? "删除所选素材堆？" : "删除所选图片？";
    els.assetDeleteModalText.textContent = primaryView
      ? `将从素材库删除 ${groupCount} 个素材堆中的 ${ids.length} 张图片。未被画布引用的原图文件可能一并清理，此操作无法撤销。`
      : `将从素材库删除 ${ids.length} 张图片。未被画布引用的原图文件可能一并清理，此操作无法撤销。`;
    els.assetDeleteModal.hidden = false;
    els.cancelAssetDeleteBtn.focus();
  }

  async function deleteSelectedLibraryAssets() {
    const ids = [...state.pendingAssetDeleteIds];
    if (!ids.length || state.deletingAssets || state.placingAssets || state.archivingAssets) return;
    state.deletingAssets = true;
    els.confirmAssetDeleteBtn.disabled = true;
    els.confirmAssetDeleteBtn.textContent = "删除中…";
    els.cancelAssetDeleteBtn.disabled = true;
    updateAssetDeleteControls();
    try {
      await Promise.all(ids.map((id) => bridge.apiPost("canvas/library/image/delete", { id })));
      state.library.images = state.library.images.filter((item) => !ids.includes(item.id));
      reconcileAssetLibraryPreferences();
      closeAssetDeleteModal({ restoreFocus: false, force: true });
      setAssetDeleteMode(false);
      renderAssetLibrary();
      toast(`已删除 ${ids.length} 项素材`);
      recordOperation("删除素材", `${ids.length} 项`, "success");
    } catch (error) {
      recordOperation("删除素材失败", error.message || "批量删除失败", "error");
      toast(error.message || "批量删除素材失败", "error");
    } finally {
      state.deletingAssets = false;
      if (!els.assetDeleteModal.hidden) {
        els.confirmAssetDeleteBtn.disabled = false;
        els.confirmAssetDeleteBtn.textContent = "删除";
        els.cancelAssetDeleteBtn.disabled = false;
      }
      updateAssetDeleteControls();
    }
  }

  function renderAssetLibrary() {
    thumbnailObserver?.disconnect();
    thumbnailObserver = null;
    state.libraryRenderCleanup?.();
    state.libraryRenderCleanup = null;
    state.libraryRenderObserver?.disconnect();
    state.libraryRenderObserver = null;
    reconcileAssetLibraryPreferences();
    if (state.assetStackKey && !assetLibraryGroups(state.library.images).some((group) => group.key === state.assetStackKey)) {
      state.assetStackKey = "";
    }
    const items = assetLibraryVisibleItems();
    const groups = assetLibraryStackViewGroups();
    const stackView = groups.length > 0;
    updateAssetLibraryModeUI();
    els.assetGrid.replaceChildren();
    els.assetGrid.scrollTop = 0;
    els.assetGrid.className = `asset-grid${stackView ? " asset-stack-grid" : ""}`;
    els.assetGrid.classList.toggle("empty", items.length === 0);
    els.assetEmpty.classList.toggle("visible", items.length === 0);
    const emptyLabels = {
      all: "暂无图片素材",
      recent: "还没有最近使用的素材",
    };
    els.assetEmpty.querySelector("span").textContent = emptyLabels[state.assetLibraryView] || emptyLabels.all;

    if (items.length) {
      if (stackView) {
        groups.forEach((group) => renderAssetStackCard(group, els.assetGrid));
      } else {
        const group = state.assetStackKey
          ? assetLibraryGroups(state.library.images).find((candidate) => candidate.key === state.assetStackKey)
          : null;
        if (group) {
          renderAssetBatch(group.items, 0);
        } else {
          renderAssetBatch(items, 0);
        }
      }
    }
    updateAssetGridMetrics();
    updateAssetDeleteControls();
    window.requestAnimationFrame(updateAssetGridMetrics);
    refreshIcons(els.assetPanel);
  }

  function renderAssetStackCard(group, container = els.assetGrid) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "asset-card asset-stack-card";
    card.dataset.stackKey = group.key;
    const selected = group.items.length > 0
      && group.items.every((item) => state.selectedAssetIds.has(item.id));
    card.classList.toggle("selected", selected);
    card.setAttribute("aria-selected", String(selected));
    card.title = `展开${group.label}素材堆`;
    card.setAttribute("aria-label", `展开${group.label}素材堆，共 ${group.items.length} 张`);

    const cover = document.createElement("span");
    cover.className = "asset-stack-cover";
    group.items.slice(0, 3).forEach((item, index) => {
      const className = `asset-stack-thumb asset-stack-thumb-${index + 1}`;
      const placeholder = document.createElement("span");
      placeholder.className = `${className} is-loading`;
      cover.appendChild(placeholder);
      observeThumbnail(placeholder, () => {
        thumbnails.get(item.id).then(({ dataUrl }) => {
          if (!placeholder.isConnected) return;
          const image = document.createElement("img");
          image.alt = item.name || `${group.label}素材`;
          image.draggable = false;
          image.className = className;
          image.src = dataUrl;
          placeholder.replaceWith(image);
        }).catch(() => placeholder.classList.add("is-broken"));
      });
    });
    const count = document.createElement("span");
    count.className = "asset-stack-count";
    count.textContent = `${group.items.length} 张`;
    cover.appendChild(count);
    const artistBadge = document.createElement("span");
    artistBadge.className = "asset-artist-badge asset-stack-artist";
    artistBadge.textContent = group.label;
    artistBadge.title = group.unassigned ? "未标注画师" : `画师：${group.label}`;
    cover.appendChild(artistBadge);
    const selectIndicator = document.createElement("span");
    selectIndicator.className = "asset-select-indicator";
    selectIndicator.setAttribute("aria-hidden", "true");
    selectIndicator.appendChild(icon("check"));
    cover.appendChild(selectIndicator);
    card.appendChild(cover);
    card.addEventListener("click", () => {
      if (state.assetDeleteMode) {
        toggleAssetGroupSelection(card, group);
        return;
      }
      state.assetStackKey = group.key;
      updateAssetLibraryModeUI();
      renderAssetLibrary();
      recordOperation("展开素材堆", `${group.label} · ${group.items.length} 张`);
    });
    container.appendChild(card);
  }

  function renderAssetBatch(items, start) {
    const end = Math.min(items.length, start + ASSET_RENDER_BATCH);
    items.slice(start, end).forEach((item) => renderImageAssetCard(item, els.assetGrid));
    if (end >= items.length) {
      refreshIcons(els.assetGrid);
      return;
    }
    const sentinel = document.createElement("div");
    sentinel.className = "asset-load-sentinel";
    sentinel.textContent = `继续加载 ${items.length - end} 项…`;
    els.assetGrid.appendChild(sentinel);
    const loadNextBatch = () => {
      const gridRect = els.assetGrid.getBoundingClientRect();
      const sentinelRect = sentinel.getBoundingClientRect();
      if (sentinelRect.top > gridRect.bottom + 240) return;
      state.libraryRenderCleanup?.();
      state.libraryRenderCleanup = null;
      state.libraryRenderObserver = null;
      sentinel.remove();
      renderAssetBatch(items, end);
    };
    const onAssetScroll = () => loadNextBatch();
    state.libraryRenderObserver = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) loadNextBatch();
    }, { root: els.assetGrid, rootMargin: "240px 0px" });
    state.libraryRenderCleanup = () => {
      state.libraryRenderObserver?.disconnect();
      els.assetGrid.removeEventListener("scroll", onAssetScroll);
    };
    els.assetGrid.addEventListener("scroll", onAssetScroll, { passive: true });
    state.libraryRenderObserver.observe(sentinel);
    refreshIcons(els.assetGrid);
  }

  function alignAssetPanel() {
    alignDebugBar();
    const { topbarRect } = alignedPanelEdges();
    const viewportRect = els.viewport.getBoundingClientRect();
    const debugRect = !els.debugBar.hidden
      ? els.debugBar.getBoundingClientRect()
      : { height: 0 };
    const gap = 14;
    // The library is intentionally one large surface on every device.  Align
    // both edges with the top bar so desktop no longer falls back to the old
    // narrow three-column drawer.
    const panelLeft = Math.max(viewportRect.left + 12, topbarRect.left);
    const panelRight = Math.min(viewportRect.right - 12, topbarRect.right);
    els.assetPanel.style.left = `${panelLeft - viewportRect.left}px`;
    els.assetPanel.style.width = `${Math.max(0, panelRight - panelLeft)}px`;
    els.assetPanel.style.top = `${topbarRect.bottom - viewportRect.top + gap}px`;
    const bottomOffsets = [12];
    // Keep the library above the bottom diagnostics bar when both overlays are open.
    if (debugRect.height > 0) {
      bottomOffsets.push(viewportRect.bottom - debugRect.top + gap);
    }
    els.assetPanel.style.bottom = `${Math.max(...bottomOffsets)}px`;
  }

  function updateAssetGridMetrics() {
    if (!els.assetPanel.classList.contains("open")) return;
    const styles = window.getComputedStyle(els.assetGrid);
    const horizontalPadding = parseFloat(styles.paddingLeft) + parseFloat(styles.paddingRight);
    const columnGap = parseFloat(styles.columnGap) || 0;
    const availableWidth = Math.max(0, els.assetGrid.clientWidth - horizontalPadding);
    const stackView = els.assetGrid.classList.contains("asset-stack-grid");
    const minTile = stackView
      ? (window.innerWidth <= 620 ? 150 : window.innerWidth <= 980 ? 190 : 210)
      : (window.innerWidth <= 620 ? 132 : 156);
    const minimumColumns = window.innerWidth <= 620 ? 2 : 3;
    const stackCount = stackView
      ? els.assetGrid.querySelectorAll(".asset-stack-card").length
      : 0;
    const maximumColumns = stackView
      ? Math.max(minimumColumns, Math.min(stackCount, 6))
      : 10;
    const columns = clamp(
      Math.floor((availableWidth + columnGap) / (minTile + columnGap)),
      minimumColumns,
      maximumColumns,
    );
    els.assetGrid.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
    const exactTileWidth = Math.max(
      96,
      (availableWidth - columnGap * (columns - 1)) / columns,
    );
    const tileWidth = Math.floor(exactTileWidth);
    if (stackView) {
      els.assetGrid.style.gridAutoRows = `${Math.ceil(exactTileWidth)}px`;
      els.assetGrid.style.removeProperty("--asset-card-height");
      return;
    }
    els.assetGrid.style.removeProperty("grid-auto-rows");
    const tileHeight = clamp(Math.round(tileWidth * 0.86), 148, 248);
    els.assetGrid.style.setProperty("--asset-card-height", `${tileHeight}px`);
  }

  function renderImageAssetCard(item, container = els.assetGrid) {
    const card = document.createElement("article");
    card.className = "asset-card asset-image-card";
    card.title = "点击预览";
    card.dataset.assetId = item.id;
    card.classList.toggle("selected", state.selectedAssetIds.has(item.id));
    card.setAttribute("aria-selected", String(state.selectedAssetIds.has(item.id)));
    const thumb = document.createElement("div");
    thumb.className = "asset-thumb";
    if (item.width && item.height) thumb.style.aspectRatio = `${item.width} / ${item.height}`;
    const loading = document.createElement("span");
    loading.className = "asset-thumb-loading";
    loading.textContent = "读取缩略图…";
    const image = document.createElement("img");
    image.alt = item.name || "图片素材";
    image.draggable = false;
    image.hidden = true;
    image.addEventListener("load", () => {
      image.hidden = false;
      loading.hidden = true;
    });
    image.addEventListener("error", () => {
      image.hidden = true;
      loading.hidden = false;
      loading.textContent = "图片读取失败";
    });
    thumb.append(loading, image);
    const selected = document.createElement("span");
    selected.className = "asset-select-indicator";
    selected.setAttribute("aria-hidden", "true");
    selected.appendChild(icon("check"));
    thumb.appendChild(selected);
    observeThumbnail(thumb, () => {
      thumbnails.get(item.id).then(({ dataUrl }) => {
        if (image.isConnected) image.src = dataUrl;
      }).catch(() => {
        if (loading.isConnected) loading.textContent = "缩略图读取失败，点击可重试预览";
      });
    });
    card.appendChild(thumb);
    attachLibraryImagePreview(card, item);
    container.appendChild(card);
  }

  function attachLibraryImagePreview(card, item) {
    card.addEventListener("click", () => {
      if (state.assetDeleteMode) {
        toggleAssetSelection(card, item.id);
        return;
      }
      openLibraryImageViewer(item);
    });
  }

  async function openLibraryImageViewer(item, { preserveState = false } = {}) {
    const sequence = state.viewerOpenSequence = (state.viewerOpenSequence || 0) + 1;
    state.viewerPendingLibraryAsset = item;
    try {
      const dataUrl = await ensureLibraryImageData(item);
      if (sequence !== state.viewerOpenSequence) return;
      markAssetRecent(item);
      openImageViewer(createLibraryImageNode(item, 0, 0, undefined, dataUrl), {
        libraryAsset: item, operationLabel: "预览素材", preserveState,
      });
    } catch (error) {
      if (sequence !== state.viewerOpenSequence) return;
      state.viewerPendingLibraryAsset = null;
      recordOperation("预览素材失败", error.message || "图片素材读取失败", "error");
      toast(error.message || "图片素材读取失败", "error");
    }
  }

  function createLibraryImageNode(item, x, y, nodeWidth = fittedImageNodeWidth(item.width, item.height), dataUrl = "") {
    return {
      id: uid("image"),
      type: "image",
      x,
      y,
      width: nodeWidth,
      title: item.name || "素材图片",
      assetId: item.id,
      dataUrl,
      createdAt: new Date().toISOString(),
      meta: {
        ...imageGenerationMeta(item.generationMeta),
        prompt: item.prompt || item.name || "素材图片",
        tags: item.tags || "",
        tagTranslations: normalizeRetagTagTranslations(item.tagTranslations),
        artist: item.artist || "",
        width: item.width,
        height: item.height,
        ratio: item.ratio || "",
        seed: normalizeNaiSeed(item.seed),
        retagged: item.source === "retagged",
        source: item.source || "",
        sourceFormat: item.format || "",
      },
    };
  }

  function selectedLibraryAssetsInDisplayOrder() {
    const group = state.assetStackKey
      ? assetLibraryGroups(state.library.images).find((candidate) => candidate.key === state.assetStackKey)
      : null;
    const visibleItems = group?.items || assetLibraryVisibleItems();
    const ordered = visibleItems.filter((item) => state.selectedAssetIds.has(item.id));
    const included = new Set(ordered.map((item) => item.id));
    state.library.images.forEach((item) => {
      if (state.selectedAssetIds.has(item.id) && !included.has(item.id)) ordered.push(item);
    });
    return ordered;
  }

  function libraryArchiveFilename(items) {
    const groups = assetLibraryGroups(items);
    const date = new Date();
    const dateStamp = [
      date.getFullYear(),
      String(date.getMonth() + 1).padStart(2, "0"),
      String(date.getDate()).padStart(2, "0"),
    ].join("-");
    const timeStamp = [
      String(date.getHours()).padStart(2, "0"),
      String(date.getMinutes()).padStart(2, "0"),
      String(date.getSeconds()).padStart(2, "0"),
    ].join("-");
    const label = groups.length === 1 ? safeZipName(groups[0].label, "素材") : "素材";
    return `${label}_${dateStamp}_${timeStamp}.zip`;
  }

  async function archiveSelectedLibraryAssets() {
    const items = selectedLibraryAssetsInDisplayOrder();
    if (!items.length || state.deletingAssets || state.placingAssets || state.archivingAssets) return;
    state.archivingAssets = true;
    updateAssetDeleteControls();
    try {
      const usedPaths = new Set(["library-manifest.json"]);
      const entries = [];
      const manifest = [];
      // Decode one original at a time; don't retain all base64 strings alongside the ZIP bytes.
      for (let index = 0; index < items.length; index += 1) {
        const item = items[index];
        try {
          const original = await bridge.apiGet("canvas/asset", { id: item.id });
          const decoded = decodeDataUrl(original.dataUrl);
          const group = assetGroupForItem(item);
          const path = uniqueZipPath(group.label, item.name || item.id || `asset-${index + 1}`, imageExtension(decoded.mimeType), usedPaths);
          entries.push({ name: path, bytes: decoded.bytes });
          manifest.push({
            id: item.id, file: path, name: item.name || "", artist: item.artist || "",
            prompt: item.prompt || "", tags: item.tags || "", ratio: item.ratio || "",
            seed: normalizeNaiSeed(item.seed), source: item.source || "",
            width: item.width || 0, height: item.height || 0, size: decoded.bytes.length,
            generationMeta: imageGenerationMeta(item.generationMeta),
          });
        } catch (error) {
          manifest.push({ id: item.id, name: item.name || "", skipped: true,
            reason: String(error?.message || error || "图片素材读取失败").slice(0, 160) });
        }
      }
      if (!entries.length) throw new Error("所选素材均无法读取，未生成压缩包");
      entries.push({
        name: "library-manifest.json",
        bytes: encodeZipText(JSON.stringify({ exportedAt: new Date().toISOString(), assets: manifest }, null, 2)),
      });
      downloadBlob(createZipBlob(entries), libraryArchiveFilename(items));
      const skipped = manifest.filter((item) => item.skipped).length;
      recordOperation(
        "压缩素材",
        skipped ? `${entries.length - 1} 项成功，${skipped} 项跳过` : `${entries.length - 1} 项`,
        skipped ? "warning" : "success",
      );
      setAssetDeleteMode(false);
      toast(skipped ? `压缩包已保存，跳过 ${skipped} 项异常素材` : `已压缩 ${entries.length - 1} 项素材`);
    } catch (error) {
      recordOperation("压缩素材失败", error.message || "压缩包生成失败", "error");
      toast(error.message || "压缩素材失败", "error");
    } finally {
      state.archivingAssets = false;
      updateAssetDeleteControls();
    }
  }

  async function placeSelectedLibraryAssetsOnCanvas() {
    const items = selectedLibraryAssetsInDisplayOrder();
    if (!items.length || state.deletingAssets || state.placingAssets || state.archivingAssets) return;
    state.placingAssets = true;
    updateAssetDeleteControls();
    try {
      const loaded = await Promise.allSettled(items.map((item) => ensureLibraryImageData(item)));
      const readyItems = items.filter((_, index) => loaded[index].status === "fulfilled");
      const dataById = new Map(items.flatMap((item, index) => loaded[index].status === "fulfilled" ? [[item.id, loaded[index].value]] : []));
      if (!readyItems.length) {
        throw loaded.find((result) => result.status === "rejected")?.reason || new Error("图片素材读取失败");
      }
      // 缺 seed 的条目先尝试从 PNG 元数据回填，卡片左下角才能显示种子
      await Promise.allSettled(readyItems.map((item) => recoverLibraryImageSeed(item)));

      const layout = readyItems.map((item) => {
        const width = fittedImageNodeWidth(item.width, item.height);
        return {
          item,
          width,
          height: estimatedImageNodeHeight(width, item.width, item.height),
        };
      });
      const columns = Math.min(4, Math.ceil(Math.sqrt(layout.length)));
      const rows = Math.ceil(layout.length / columns);
      const maxWidth = Math.max(...layout.map((entry) => entry.width));
      const maxHeight = Math.max(...layout.map((entry) => entry.height));
      const horizontalGap = 56;
      const verticalGap = 56;
      const totalHeight = rows * maxHeight + (rows - 1) * verticalGap;
      const center = worldCenter();
      const startY = center.y - totalHeight / 2;
      const nodes = layout.map((entry, index) => {
        const row = Math.floor(index / columns);
        const column = index % columns;
        const rowCount = Math.min(columns, layout.length - row * columns);
        const rowWidth = rowCount * maxWidth + (rowCount - 1) * horizontalGap;
        const rowStartX = center.x - rowWidth / 2;
        const x = rowStartX + column * (maxWidth + horizontalGap) + (maxWidth - entry.width) / 2;
        const y = startY + row * (maxHeight + verticalGap) + (maxHeight - entry.height) / 2;
        return createLibraryImageNode(entry.item, x, y, entry.width, dataById.get(entry.item.id));
      });

      pushHistory();
      state.nodes.push(...nodes);
      setSelection(nodes.map((node) => node.id), nodes[0].id);
      [...readyItems].reverse().forEach((item) => markAssetRecent(item, { render: false }));
      renderAll();
      scheduleSave();

      const failedCount = items.length - readyItems.length;
      recordOperation(
        "批量放入画布",
        failedCount ? `${nodes.length} 项成功，${failedCount} 项读取失败` : `${nodes.length} 项`,
        failedCount ? "warning" : "success",
      );
      setAssetPanel(false);
      toast(failedCount ? `已放入 ${nodes.length} 项，${failedCount} 项读取失败` : `已放入 ${nodes.length} 项素材`);
    } catch (error) {
      recordOperation("批量放入画布失败", error.message || "添加图片素材失败", "error");
      toast(error.message || "批量加入画布失败", "error");
    } finally {
      state.placingAssets = false;
      updateAssetDeleteControls();
    }
  }

  const recoveringSeedAssetIds = new Set();

  async function recoverLibraryImageSeed(item) {
    // 旧版本收录的素材可能没存 seed；放入画布前让后端读一次 PNG 内嵌元数据补上。
    // 失败静默：标签继续显示名称，不阻塞放置流程。
    const assetId = String(item?.id || "");
    if (!assetId || normalizeNaiSeed(item.seed)) return;
    if (recoveringSeedAssetIds.has(assetId)) return;
    recoveringSeedAssetIds.add(assetId);
    try {
      const result = await bridge.apiPost("canvas/library/image/recover", { id: assetId });
      const seed = normalizeNaiSeed(result?.image?.seed);
      if (seed) item.seed = seed;
    } catch (_) {
      // 图片被重新编码后元数据已丢失，读不到种子属正常情况
    } finally {
      recoveringSeedAssetIds.delete(assetId);
    }
  }

  async function placeImageAssetOnCanvas(item, point = worldCenter()) {
    try {
      const dataUrl = await ensureLibraryImageData(item);
      await recoverLibraryImageSeed(item);
      markAssetRecent(item, { render: false });
      const nodeWidth = fittedImageNodeWidth(item.width, item.height);
      const nodeHeight = estimatedImageNodeHeight(nodeWidth, item.width, item.height);
      addNode(createLibraryImageNode(
        item,
        point.x - nodeWidth / 2,
        point.y - nodeHeight / 2,
        nodeWidth,
        dataUrl,
      ));
      recordOperation("放入画布", item.name || "素材图片", "success");
      return true;
    } catch (error) {
      recordOperation("放入画布失败", error.message || "添加图片素材失败", "error");
      toast(error.message || "添加图片素材失败", "error");
      return false;
    }
  }

  async function saveImageToLibrary(node) {
    if (!node?.assetId || state.savingLibraryAssetIds.has(node.assetId)) return;
    state.savingLibraryAssetIds.add(node.assetId);
    updateImageViewerSaveButton();
    try {
      await hydrateImageGenerationMeta(node);
      const linkedPrompt = state.connections
        .filter((edge) => edge.source === node.id && findNode(edge.target)?.type === "prompt")
        .map((edge) => findNode(edge.target))
        .find((candidate) => candidate?.meta?.retagAssetId === node.assetId);
      const linkedRetag = linkedPrompt?.meta || {};
      const seed = sourceImageSeed(node) || normalizeNaiSeed(linkedRetag.retagSeed);
      const result = await bridge.apiPost("canvas/library/image/add", {
        assetId: node.assetId,
        name: node.title || node.meta?.prompt || "画布图片",
        source: node.meta?.retagged ? "retagged" : "generated",
        prompt: node.meta?.prompt || "",
        tags: node.meta?.finalPrompt || node.meta?.tags || linkedRetag.retagPrompt || "",
        tagTranslations: normalizeRetagTagTranslations(
          node.meta?.tagTranslations || linkedRetag.retagTagTranslations,
        ),
        artist: node.meta?.artist || "",
        ratio: node.meta?.ratio || linkedRetag.retagRatio || "",
        // A source image may only reveal its seed during the retag pass; keep
        // that value when the image itself is later collected into the library.
        seed,
        generationMeta: imageGenerationMeta(node.meta),
      });
      const image = { ...result.image };
      previews.remember(image.id, { dataUrl: node.dataUrl });
      state.library.images = [image, ...state.library.images.filter((item) => item.id !== image.id)];
      reconcileAssetLibraryPreferences();
      if (els.assetPanel.classList.contains("open")) renderAssetLibrary();
      toast("图片已保存到素材库");
      recordOperation("收录素材", node.title || "画布图片", "success");
    } catch (error) {
      recordOperation("收录素材失败", error.message || "图片保存失败", "error");
      toast(error.message || "图片保存失败", "error");
    } finally {
      state.savingLibraryAssetIds.delete(node.assetId);
      updateImageViewerSaveButton();
    }
  }


  return {
    setAssetLibraryView,
    closeAssetStack,
    setLibraryData,
    loadLibrary,
    setAssetPanel,
    setAssetDeleteMode,
    closeAssetDeleteModal,
    openAssetDeleteModal,
    deleteSelectedLibraryAssets,
    alignAssetPanel,
    updateAssetGridMetrics,
    openLibraryImageViewer,
    archiveSelectedLibraryAssets,
    placeSelectedLibraryAssetsOnCanvas,
    placeImageAssetOnCanvas,
    saveImageToLibrary
  };
}

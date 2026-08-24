import {
  createZipBlob,
  decodeDataUrl,
  downloadBlob,
  encodeZipText,
  imageExtension,
  safeZipName,
  uniqueZipPath,
} from "./zip-utils.js";

let bridge = null;

async function getBridge() {
  const deadline = Date.now() + 5000;
  while (!window.AstrBotPluginPage && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!window.AstrBotPluginPage) {
    throw new Error("AstrBot 页面桥接加载失败，请刷新插件页面");
  }
  const pageBridge = window.AstrBotPluginPage;
  await pageBridge.ready();
  return pageBridge;
}
const pageParams = new URLSearchParams(window.location.search);
let canvasId = pageParams.get("id") || "";
let projectId = pageParams.get("project") || "default";

const els = {
  viewport: document.getElementById("board"),
  world: document.getElementById("world"),
  nodeLayer: document.getElementById("nodes"),
  paths: document.getElementById("links"),
  linkControls: document.getElementById("linkControls"),
  empty: document.getElementById("emptyState"),
  pluginDisplayName: document.getElementById("pluginDisplayName"),
  pluginVersion: document.getElementById("pluginVersion"),
  pluginAuthor: document.getElementById("pluginAuthor"),
  canvasMark: document.querySelector(".canvas-mark"),
  connectionIndicator: document.getElementById("connectionIndicator"),
  undoBtn: document.getElementById("undoBtn"),
  redoBtn: document.getElementById("redoBtn"),
  imageInput: document.getElementById("imageInput"),
  workspaceInput: document.getElementById("workspaceInput"),
  toastRegion: document.getElementById("toastRegion"),
  selectionBox: document.getElementById("selectionBox"),
  arrangeSelectionBtn: document.getElementById("canvasArrangeBtn"),
  imageViewer: document.getElementById("imageViewer"),
  imageViewerImageFrame: document.querySelector(".image-viewer-image-frame"),
  imageViewerImage: document.getElementById("imageViewerImage"),
  imageViewerDetails: document.getElementById("imageViewerDetails"),
  imageViewerDetailsToggle: document.getElementById("imageViewerDetailsToggle"),
  imageViewerTags: document.getElementById("imageViewerTags"),
  imageViewerPlaceBtn: document.getElementById("imageViewerPlaceBtn"),
  assetLibraryBtn: document.getElementById("assetLibraryBtn"),
  mobileAssetLibraryBtn: document.getElementById("mobileAssetLibraryBtn"),
  assetPanel: document.getElementById("assetPanel"),
  debugModeBtn: document.getElementById("debugModeBtn"),
  debugBar: document.getElementById("debugBar"),
  debugBarToggle: document.getElementById("debugBarToggle"),
  debugBarSummary: document.getElementById("debugBarSummary"),
  debugBarBody: document.getElementById("debugBarBody"),
  assetGrid: document.getElementById("assetGrid"),
  assetEmpty: document.getElementById("assetEmpty"),
  assetLibraryCount: document.getElementById("assetLibraryCount"),
  assetViewAllBtn: document.getElementById("assetViewAllBtn"),
  assetViewRecentBtn: document.getElementById("assetViewRecentBtn"),
  assetAllCount: document.getElementById("assetAllCount"),
  assetRecentCount: document.getElementById("assetRecentCount"),
  assetStackTrail: document.getElementById("assetStackTrail"),
  assetStackTrailLabel: document.getElementById("assetStackTrailLabel"),
  assetRefreshBtn: document.getElementById("assetRefreshBtn"),
  assetSelectModeBtn: document.getElementById("assetSelectModeBtn"),
  assetDeleteActions: document.getElementById("assetDeleteActions"),
  assetDeleteCount: document.getElementById("assetDeleteCount"),
  assetPlaceSelectedBtn: document.getElementById("assetPlaceSelectedBtn"),
  assetArchiveSelectedBtn: document.getElementById("assetArchiveSelectedBtn"),
  assetDeleteCancel: document.getElementById("assetDeleteCancel"),
  assetDeleteConfirm: document.getElementById("assetDeleteConfirm"),
  assetDeleteModal: document.getElementById("assetDeleteModal"),
  assetDeleteModalTitle: document.getElementById("assetDeleteModalTitle"),
  assetDeleteModalText: document.getElementById("assetDeleteModalText"),
  confirmAssetDeleteBtn: document.getElementById("confirmAssetDeleteBtn"),
  cancelAssetDeleteBtn: document.getElementById("cancelAssetDeleteBtn"),
  projectMenuBtn: document.getElementById("projectMenuBtn"),
  projectMenu: document.getElementById("projectMenu"),
  projectList: document.getElementById("projectList"),
  newProjectRow: document.getElementById("newProjectRow"),
  newProjectInput: document.getElementById("newProjectInput"),
  canvasContextMenu: document.getElementById("canvasContextMenu"),
  nodeContextMenu: document.getElementById("nodeContextMenu"),
  selectionContextMenu: document.getElementById("selectionContextMenu"),
};

const OPERATION_LOG_KEY = "bestnaiCanvasOperationLog";
const RECORDER_OPEN_KEY = "bestnaiCanvasRecorderOpen";
const ASSET_LIBRARY_PREFS_KEY = "bestnaiCanvasAssetLibraryPrefs";
const ASSET_RECENT_LIMIT = 24;
const OPERATION_LOG_LIMIT = 240;
const OPERATION_VISIBLE_LIMIT = 100;

function normalizeAssetIdList(value, limit = ASSET_RECENT_LIMIT) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map((item) => String(item || "").trim()).filter(Boolean))].slice(0, limit);
}

function loadAssetLibraryPreferences() {
  try {
    const raw = JSON.parse(localStorage.getItem(ASSET_LIBRARY_PREFS_KEY) || "{}");
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    return {
      recent: normalizeAssetIdList(raw.recent),
      view: ["all", "recent"].includes(raw.view) ? raw.view : "all",
    };
  } catch (_) {
    return {};
  }
}

const INITIAL_ASSET_LIBRARY_PREFERENCES = loadAssetLibraryPreferences();

function maskOperationSecrets(value) {
  return String(value || "")
    .replace(/(authorization["']?\s*[:=]\s*)(?:bearer\s+)?["']?([^\s,;}"']+)["']?/gi, "$1***")
    .replace(/((?:api[_-]?key|access[_-]?token|token)["']?\s*[:=]\s*)["']?([^\s,;}"']+)["']?/gi, "$1***")
    .replace(/([?&](?:key|token|api_key)=)([^&\s]+)/gi, "$1***");
}

function loadOperationLog() {
  try {
    const raw = JSON.parse(localStorage.getItem(OPERATION_LOG_KEY) || "[]");
    if (!Array.isArray(raw)) return [];
    return raw
      .filter((entry) => entry && typeof entry === "object")
      .slice(-OPERATION_LOG_LIMIT)
      .map((entry, index) => ({
        id: Number.isInteger(entry.id) && entry.id > 0 ? entry.id : index + 1,
        timestamp: String(entry.timestamp || new Date().toISOString()),
        action: String(entry.action || "操作").replace(/\s+/g, " ").trim().slice(0, 120),
        detail: maskOperationSecrets(entry.detail).replace(/\s+/g, " ").trim().slice(0, 360),
        level: ["info", "success", "warning", "error"].includes(entry.level)
          ? entry.level
          : "info",
      }));
  } catch (_) {
    return [];
  }
}

const INITIAL_OPERATION_LOG = loadOperationLog();
const INITIAL_OPERATION_SEQUENCE = INITIAL_OPERATION_LOG.reduce(
  (max, entry) => Math.max(max, Number(entry.id) || 0),
  0,
);

const state = {
  config: {
    configured: false,
    ratios: [],
    artists: [],
    retagControlPrompts: [],
    defaultRatio: "2:3",
    defaultArtist: "",
    retagEnabled: false,
    retagConfigured: false,
  },
  nodes: [],
  connections: [],
  viewport: { x: 160, y: 120, scale: 1 },
  selectedId: "",
  selectedIds: [],
  saveTimer: null,
  saving: false,
  savePromise: null,
  healthTimer: null,
  healthChecking: false,
  history: [],
  future: [],
  restoring: false,
  composing: false,
  renderPending: false,
  connectionDrag: null,
  pendingUploadPoint: null,
  library: { images: [], prompts: [] },
  libraryAssetPromises: new Map(),
  libraryPreloadPromise: null,
  libraryRenderObserver: null,
  libraryRenderCleanup: null,
  assetLibraryView: INITIAL_ASSET_LIBRARY_PREFERENCES.view || "all",
  assetStackKey: "",
  assetRecent: INITIAL_ASSET_LIBRARY_PREFERENCES.recent || [],
  assetDeleteMode: false,
  selectedAssetIds: new Set(),
  deletingAssets: false,
  placingAssets: false,
  archivingAssets: false,
  pendingAssetDeleteIds: [],
  canvases: [],
  pendingDeleteCanvasId: "",
  currentCanvasTitle: "未命名项目",
  assetCache: new Map(),
  promptDefaults: { ratio: "", artist: "" },
  debugEnabled: (() => {
    try { return localStorage.getItem("bestnaiCanvasDebug") === "1"; } catch (_) { return false; }
  })(),
  // The recorder is a persistent CAD-like command line.  The detailed trace
  // switch only controls diagnostic payloads; the operation history remains
  // available even when detailed debug mode is off.
  debugBarOpen: (() => {
    try { return localStorage.getItem(RECORDER_OPEN_KEY) === "1"; } catch (_) { return false; }
  })(),
  operationLog: INITIAL_OPERATION_LOG,
  operationSequence: INITIAL_OPERATION_SEQUENCE,
  lastDebugNodeId: "",
  preferencesSaveChain: Promise.resolve(),
  layoutObserver: null,
  layoutAlignFrame: 0,
  viewportRecordTimer: null,
  contextMenuPoint: null,
  contextMenuNodeId: "",
  viewerLibraryAsset: null,
  viewerImageDimensions: { width: 0, height: 0 },
  viewerFrameSyncHandle: 0,
  viewerBottomLayoutLock: null,
  viewerTagLookupSequence: 0,
  viewerTagTranslationCache: new Map(),
  retagRequestSequence: 0,
  retagRequests: new Map(),
};

const MAX_HISTORY = 40;
function debugModeEnabled() {
  return !!state.debugEnabled;
}

const LAST_CANVAS_KEY = "bestnaiInfiniteCanvasId";
const PROMPT_DEFAULTS_KEY = "bestnaiInfiniteCanvasPromptDefaults";
const ASSET_RENDER_BATCH = 48;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const uid = (prefix) => `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
function icon(name, className = "") {
  const element = document.createElement("i");
  element.dataset.lucide = name;
  if (className) element.className = className;
  return element;
}

function refreshIcons(root = document) {
  if (window.lucide?.createIcons) {
    window.lucide.createIcons({ root, attrs: { "stroke-width": 1.8 } });
  }
}

function formatOperationTime(timestamp) {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString([], { hour12: false });
}

function operationText(value, fallback = "") {
  return String(value ?? fallback).replace(/\s+/g, " ").trim().slice(0, 360);
}

function persistOperationLog() {
  try {
    localStorage.setItem(OPERATION_LOG_KEY, JSON.stringify(state.operationLog.slice(-OPERATION_LOG_LIMIT)));
  } catch (_) {
    // Private browsing and embedded webviews may disable local storage.
  }
}

function recordOperation(action, detail = "", level = "info") {
  const entry = {
    id: ++state.operationSequence,
    timestamp: new Date().toISOString(),
    action: operationText(action, "操作").slice(0, 120),
    // Error messages can contain a query-string key when a provider fails.
    // Keep the local recorder useful without turning it into a secret cache.
    detail: maskOperationSecrets(operationText(detail)),
    level: ["info", "success", "warning", "error"].includes(level) ? level : "info",
  };
  state.operationLog.push(entry);
  if (state.operationLog.length > OPERATION_LOG_LIMIT) {
    state.operationLog.splice(0, state.operationLog.length - OPERATION_LOG_LIMIT);
  }
  persistOperationLog();
  if (els.debugBar) renderDebugBar();
}

function clearOperationLog() {
  state.operationLog = [];
  state.operationSequence = 0;
  persistOperationLog();
  recordOperation("记录器已清空", "新的操作会继续追加");
}

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

function toast(message, type = "info") {
  alignToastRegion();
  const item = document.createElement("div");
  item.className = `toast${type === "error" ? " error" : ""}`;
  item.textContent = String(message || "操作失败");
  item.title = item.textContent;
  item.setAttribute("role", type === "error" ? "alert" : "status");
  els.toastRegion.replaceChildren(item);
  window.setTimeout(() => item.remove(), 3600);
}

function alignToastRegion() {
  const rect = document.querySelector(".topbar").getBoundingClientRect();
  els.toastRegion.style.top = `${(rect.top + rect.bottom) / 2}px`;
}

// 彩蛋：连点三次 logo 转一圈
function setupLogoEasterEgg() {
  const mark = els.canvasMark;
  if (!mark) return;
  const RESET_DELAY = 1200;
  let clicks = 0;
  let resetTimer = 0;
  mark.addEventListener("click", () => {
    window.clearTimeout(resetTimer);
    clicks += 1;
    if (clicks < 3) {
      // 三次要连着点，隔太久就重新数
      resetTimer = window.setTimeout(() => { clicks = 0; }, RESET_DELAY);
      return;
    }
    clicks = 0;
    if (mark.classList.contains("celebrate")) return;
    mark.classList.add("celebrate");
    mark.addEventListener(
      "animationend",
      () => mark.classList.remove("celebrate"),
      { once: true },
    );
    toast("祝你天天开心！");
  });
}

function setConnectionState(status) {
  const online = status === "online";
  const label = online
    ? "服务连接正常"
    : status === "offline"
      ? "服务连接中断"
      : "正在检测服务连接";
  els.connectionIndicator.classList.toggle("online", online);
  els.connectionIndicator.classList.toggle("offline", status === "offline");
  els.connectionIndicator.classList.toggle("checking", status === "checking");
  els.connectionIndicator.setAttribute("aria-label", label);
  els.connectionIndicator.title = label;
}

async function checkConnection() {
  if (state.healthChecking) return false;
  if (!navigator.onLine) {
    setConnectionState("offline");
    return false;
  }
  state.healthChecking = true;
  try {
    await Promise.race([
      bridge.apiGet("canvas/health"),
      new Promise((_, reject) => {
        window.setTimeout(() => reject(new Error("连接检测超时")), 5000);
      }),
    ]);
    setConnectionState("online");
    return true;
  } catch (_) {
    setConnectionState("offline");
    return false;
  } finally {
    state.healthChecking = false;
  }
}

function startHealthMonitor() {
  window.clearInterval(state.healthTimer);
  setConnectionState("checking");
  checkConnection();
  state.healthTimer = window.setInterval(checkConnection, 15_000);
}

function setProjectMenu(open) {
  const next = !!open;
  setSelectionContextMenu(false);
  if (next) {
    setCanvasContextMenu(false);
    setNodeContextMenu(false);
  }
  if (next && els.assetPanel.classList.contains("open")) setAssetPanel(false);
  els.projectMenu.hidden = !next;
  els.projectMenuBtn.setAttribute("aria-expanded", String(next));
  els.projectMenuBtn.classList.toggle("active", next);
  if (next) alignProjectMenu();
  if (!next) {
    els.newProjectRow.hidden = true;
    els.newProjectInput.value = "";
    state.pendingDeleteCanvasId = "";
  }
}

function setCanvasContextMenu(open, clientX = 0, clientY = 0) {
  const next = !!open;
  if (next) {
    setNodeContextMenu(false);
    setSelectionContextMenu(false);
  }
  els.canvasContextMenu.hidden = !next;
  if (!next) {
    state.contextMenuPoint = null;
    return;
  }
  const margin = 12;
  const width = els.canvasContextMenu.offsetWidth;
  const height = els.canvasContextMenu.offsetHeight;
  els.canvasContextMenu.style.left = `${clamp(clientX, margin, window.innerWidth - width - margin)}px`;
  els.canvasContextMenu.style.top = `${clamp(clientY, margin, window.innerHeight - height - margin)}px`;
}

function setNodeContextMenu(open, node = null, clientX = 0, clientY = 0) {
  const next = !!open && !!node;
  if (next) {
    setCanvasContextMenu(false);
    setSelectionContextMenu(false);
  }
  els.nodeContextMenu.hidden = !next;
  if (!next) {
    state.contextMenuNodeId = "";
    return;
  }

  state.contextMenuNodeId = node.id;
  const imageNode = node.type === "image";
  els.nodeContextMenu.querySelectorAll("[data-image-only]").forEach((item) => {
    item.hidden = !imageNode;
  });
  const download = document.getElementById("nodeContextDownloadImage");
  const downloadLocked = imageNode && canvasGenerationActive();
  download.disabled = downloadLocked;
  download.title = downloadLocked ? "生图期间暂不可下载" : "下载图片";
  download.setAttribute("aria-disabled", String(downloadLocked));

  const margin = 12;
  const width = els.nodeContextMenu.offsetWidth;
  const height = els.nodeContextMenu.offsetHeight;
  els.nodeContextMenu.style.left = `${clamp(clientX, margin, window.innerWidth - width - margin)}px`;
  els.nodeContextMenu.style.top = `${clamp(clientY, margin, window.innerHeight - height - margin)}px`;
}

function setSelectionContextMenu(open, clientX = 0, clientY = 0) {
  const next = !!open && selectedNodeIds().length >= 2;
  if (next) {
    setCanvasContextMenu(false);
    setNodeContextMenu(false);
  }
  els.selectionContextMenu.hidden = !next;
  if (!next) return;

  const margin = 12;
  const width = els.selectionContextMenu.offsetWidth;
  const height = els.selectionContextMenu.offsetHeight;
  els.selectionContextMenu.style.left = `${clamp(clientX, margin, window.innerWidth - width - margin)}px`;
  els.selectionContextMenu.style.top = `${clamp(clientY, margin, window.innerHeight - height - margin)}px`;
}

function alignedPanelEdges() {
  const topbarRect = document.querySelector(".topbar").getBoundingClientRect();
  const buttonRect = els.assetLibraryBtn.getBoundingClientRect();
  const right = Math.min(topbarRect.right, window.innerWidth - 12);
  const left = window.innerWidth <= 620
    ? 12
    : clamp(buttonRect.left, 12, right - 240);
  return { topbarRect, left, right };
}

function alignProjectMenu() {
  const { topbarRect, left, right } = alignedPanelEdges();
  els.projectMenu.style.top = `${topbarRect.bottom + 14}px`;
  els.projectMenu.style.left = `${left}px`;
  els.projectMenu.style.width = `${right - left}px`;
}

function alignDebugBar() {
  const topbar = document.querySelector(".topbar");
  if (!topbar || !els.viewport || !els.debugBar) return;
  const topbarRect = topbar.getBoundingClientRect();
  const viewportRect = els.viewport.getBoundingClientRect();
  // The board owns the HUD, while the status bar may wrap or change margins
  // at a responsive breakpoint. Calculate both offsets from actual rectangles
  // instead of duplicating the CSS margins in a second place.
  const left = clamp(topbarRect.left - viewportRect.left, 12, Math.max(12, viewportRect.width - 120));
  const right = clamp(viewportRect.right - topbarRect.right, 12, Math.max(12, viewportRect.width - 120));
  els.debugBar.style.left = `${left}px`;
  els.debugBar.style.right = `${right}px`;
}

function alignOverlayPanels() {
  alignDebugBar();
  if (els.assetPanel.classList.contains("open")) {
    alignAssetPanel();
    updateAssetGridMetrics();
  }
  if (!els.projectMenu.hidden) alignProjectMenu();
}

function scheduleOverlayAlignment() {
  if (state.layoutAlignFrame) return;
  state.layoutAlignFrame = window.requestAnimationFrame(() => {
    state.layoutAlignFrame = 0;
    alignOverlayPanels();
  });
}

function setupOverlayAlignment() {
  alignOverlayPanels();
  if (typeof ResizeObserver === "undefined") return;
  const topbar = document.querySelector(".topbar");
  if (!topbar || !els.viewport) return;
  state.layoutObserver?.disconnect();
  state.layoutObserver = new ResizeObserver(scheduleOverlayAlignment);
  state.layoutObserver.observe(topbar);
  state.layoutObserver.observe(els.viewport);
}

function projectIconButton(iconName, title, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `project-menu-icon${className ? ` ${className}` : ""}`;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.appendChild(icon(iconName));
  return button;
}

function renderProjectMenu() {
  els.projectList.replaceChildren();
  state.canvases.forEach((canvas) => {
    const row = document.createElement("div");
    row.className = `project-row${canvas.id === canvasId ? " active" : ""}`;
    row.dataset.canvasId = canvas.id;

    const select = document.createElement("button");
    select.type = "button";
    select.className = "project-row-main";
    select.append(icon(canvas.id === canvasId ? "folder-open" : "folder"));
    const name = document.createElement("span");
    name.className = "project-row-name";
    name.textContent = canvas.title || "未命名项目";
    select.appendChild(name);
    select.addEventListener("click", () => navigateToCanvas(canvas));

    const actions = document.createElement("span");
    actions.className = "project-row-actions";
    if (state.pendingDeleteCanvasId === canvas.id) {
      const label = document.createElement("span");
      label.className = "project-delete-label";
      label.textContent = "确认删除?";
      const confirm = projectIconButton("check", "确认删除", "danger");
      const cancel = projectIconButton("x", "取消");
      confirm.addEventListener("click", () => deleteCanvasProject(canvas.id));
      cancel.addEventListener("click", () => {
        state.pendingDeleteCanvasId = "";
        renderProjectMenu();
      });
      actions.append(label, confirm, cancel);
    } else {
      const remove = projectIconButton("trash-2", "删除项目", "danger");
      remove.addEventListener("click", () => {
        state.pendingDeleteCanvasId = canvas.id;
        renderProjectMenu();
      });
      actions.appendChild(remove);
    }
    row.append(select, actions);
    els.projectList.appendChild(row);
  });
  refreshIcons(els.projectList);
}

function rememberCurrentCanvas() {
  try {
    localStorage.setItem(LAST_CANVAS_KEY, canvasId);
  } catch (_) {
    // The current browser may disable local storage.
  }
  persistCanvasPreferences();
}

function updateCanvasUrl() {
  const currentUrl = new URL(window.location.href);
  currentUrl.searchParams.set("id", canvasId);
  currentUrl.searchParams.set("project", projectId);
  window.history.replaceState(null, "", currentUrl);
}

async function flushWorkspace() {
  if (!canvasId) return;
  window.clearTimeout(state.saveTimer);
  state.saveTimer = null;
  if (state.savePromise) await state.savePromise;
  await saveWorkspace();
  window.clearTimeout(state.saveTimer);
  state.saveTimer = null;
}

async function switchCanvas(canvas, { saveCurrent = true } = {}) {
  if (!canvas?.id) throw new Error("项目不存在");
  if (canvas.id === canvasId && saveCurrent) {
    setProjectMenu(false);
    return;
  }

  // A library preview/expanded panel belongs to the current canvas view.  Do
  // not carry it (or its selected/deleting state) into another workspace.
  closeImageViewer();
  if (els.assetPanel.classList.contains("open")) setAssetPanel(false);
  setCanvasContextMenu(false);
  setNodeContextMenu(false);
  if (saveCurrent && canvasId) await flushWorkspace();

  const workspace = await bridge.apiGet("canvas/workspace", { id: canvas.id });
  canvasId = canvas.id;
  projectId = canvas.projectId || "default";
  state.currentCanvasTitle = canvas.title || "未命名项目";
  state.nodes = Array.isArray(workspace?.nodes)
    ? workspace.nodes.map(normalizeLoadedNodeDimensions)
    : [];
  state.connections = Array.isArray(workspace?.connections) ? workspace.connections : [];
  state.lastDebugNodeId = "";
  state.viewport = workspace?.viewport || { x: 160, y: 120, scale: 1 };
  state.selectedId = "";
  state.selectedIds = [];
  state.history = [];
  state.future = [];
  state.connectionDrag = null;
  rememberCurrentCanvas();
  updateCanvasUrl();
  document.title = `${state.currentCanvasTitle} · ${state.config.plugin?.name || "BestNAI"}`;
  setProjectMenu(false);
  renderAll();
  renderProjectMenu();
  recordOperation("切换项目", state.currentCanvasTitle);
}

async function navigateToCanvas(canvas) {
  try {
    await switchCanvas(canvas);
  } catch (error) {
    toast(error.message || "切换项目失败", "error");
  }
}

async function createCanvasProject() {
  const title = els.newProjectInput.value.trim() || "新项目";
  try {
    const result = await bridge.apiPost("canvas/canvases/create", {
      title,
      projectId: projectId || "default",
    });
    if (!result?.canvas?.id) throw new Error("创建项目失败");
    state.canvases.push(result.canvas);
    await switchCanvas(result.canvas);
    recordOperation("创建项目", title, "success");
  } catch (error) {
    recordOperation("创建项目失败", error.message || "创建项目失败", "error");
    toast(error.message || "创建项目失败", "error");
  }
}

async function deleteCanvasProject(id) {
  try {
    await bridge.apiPost("canvas/canvases/delete", { id });
    state.canvases = state.canvases.filter((canvas) => canvas.id !== id);
    state.pendingDeleteCanvasId = "";
    if (id !== canvasId) {
      renderProjectMenu();
      toast("项目已删除");
      recordOperation("删除项目", id, "success");
      return;
    }
    let next = state.canvases[0];
    if (!next) {
      const result = await bridge.apiPost("canvas/canvases/create", {
        title: "新项目",
        projectId: "default",
      });
      next = result?.canvas;
      if (next?.id) state.canvases.push(next);
    }
    if (!next?.id) throw new Error("无法创建新的项目");
    await switchCanvas(next, { saveCurrent: false });
    toast("项目已删除");
    recordOperation("删除项目", id, "success");
  } catch (error) {
    recordOperation("删除项目失败", error.message || "删除项目失败", "error");
    toast(error.message || "删除项目失败", "error");
    renderProjectMenu();
  }
}

function serializableWorkspace() {
  return {
    version: 1,
    viewport: { ...state.viewport },
    nodes: state.nodes.map((node) => ({
      id: node.id,
      type: node.type,
      x: node.x,
      y: node.y,
      width: node.width,
      height: node.height || 0,
      title: node.title || "",
      prompt: node.prompt || "",
      note: node.note || "",
      ratio: node.ratio || "",
      artist: node.artist || "",
      raw: !!node.raw,
      assetId: node.assetId || "",
      createdAt: node.createdAt || "",
      meta: node.meta || {},
    })),
    connections: state.connections.map((item) => ({ ...item })),
  };
}

function snapshot() {
  return JSON.stringify({
    ...serializableWorkspace(),
    selectedId: state.selectedId,
    selectedIds: [...state.selectedIds],
  });
}

function pushHistory() {
  if (state.restoring) return;
  state.history.push(snapshot());
  if (state.history.length > MAX_HISTORY) state.history.shift();
  state.future = [];
  updateHistoryButtons();
}

function restoreSnapshot(raw) {
  const data = JSON.parse(raw);
  state.restoring = true;
  state.nodes = Array.isArray(data.nodes)
    ? data.nodes.map(normalizeLoadedNodeDimensions)
    : [];
  state.connections = Array.isArray(data.connections) ? data.connections : [];
  state.lastDebugNodeId = "";
  state.viewport = data.viewport || { x: 160, y: 120, scale: 1 };
  state.selectedId = data.selectedId || "";
  state.selectedIds = Array.isArray(data.selectedIds) ? data.selectedIds : (state.selectedId ? [state.selectedId] : []);
  state.restoring = false;
  renderAll();
  scheduleSave();
}

function undo() {
  if (!state.history.length) return;
  state.future.push(snapshot());
  restoreSnapshot(state.history.pop());
  updateHistoryButtons();
  recordOperation("撤销", "恢复上一步画布状态");
}

function redo() {
  if (!state.future.length) return;
  state.history.push(snapshot());
  restoreSnapshot(state.future.pop());
  updateHistoryButtons();
  recordOperation("重做", "恢复下一步画布状态");
}

function updateHistoryButtons() {
  els.undoBtn.disabled = state.history.length === 0;
  els.redoBtn.disabled = state.future.length === 0;
}

function scheduleSave(delay = 500) {
  if (state.restoring) return;
  window.clearTimeout(state.saveTimer);
  state.saveTimer = window.setTimeout(saveWorkspace, delay);
}

async function saveWorkspace() {
  if (state.saving) {
    scheduleSave(700);
    return state.savePromise;
  }
  // 定时器已经触发，待保存标记要清掉，否则 saveTimer 会一直为真，
  // 判断不出还有没有没落盘的改动
  state.saveTimer = null;
  const targetCanvasId = canvasId;
  const payload = serializableWorkspace();
  state.saving = true;
  state.savePromise = bridge.apiPost("canvas/workspace", { canvasId: targetCanvasId, ...payload });
  try {
    await state.savePromise;
  } catch (error) {
    toast(error.message, "error");
  } finally {
    state.saving = false;
    state.savePromise = null;
  }
}

function suggestedNodeCenter(width) {
  const selected = findNode(state.selectedId);
  if (!selected) return worldCenter();
  return {
    x: selected.x + (selected.width || 320) + 100 + width / 2,
    y: selected.y + 150,
  };
}

function createPromptNode(point = null) {
  const center = point || suggestedNodeCenter(320);
  return {
    id: uid("prompt"),
    type: "prompt",
    x: center.x - 160,
    y: center.y - 170,
    width: 320,
    height: 360,
    title: "提示词节点",
    prompt: "",
    ratio: state.promptDefaults.ratio || state.config.defaultRatio || "2:3",
    artist: state.promptDefaults.artist,
    raw: false,
    createdAt: new Date().toISOString(),
  };
}

function optionValue(item) {
  return typeof item === "string" ? item : String(item?.value || "");
}

function hasOptionValue(items, value) {
  return (items || []).some((item) => optionValue(item) === value);
}

function canvasArtistOptions() {
  const artists = [...(state.config.artists || [])];
  const configuredArtist = String(state.config.defaultArtist || "").trim();
  const configuredOption = artists.find(
    (item) => item.value === configuredArtist || item.label === configuredArtist,
  );
  if (configuredArtist && !configuredOption) {
    artists.unshift({ value: "", label: configuredArtist });
  }
  if (!artists.length) artists.push({ value: "", label: "配置画师预设" });
  return artists;
}

function normalizedArtistSelection(value) {
  const options = canvasArtistOptions();
  const selected = String(value || "");
  if (selected && hasOptionValue(options, selected)) return selected;
  const configuredArtist = String(state.config.defaultArtist || "").trim();
  const configuredOption = options.find(
    (item) => item.value === configuredArtist || item.label === configuredArtist,
  );
  if (!selected && configuredOption) return configuredOption.value;
  if (hasOptionValue(options, selected)) return selected;
  return optionValue(options[0]);
}

function loadPromptDefaults(preferences = {}) {
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(PROMPT_DEFAULTS_KEY) || "{}");
  } catch (_) {
    stored = {};
  }
  const persisted = {
    ratio: String(preferences.ratio || stored.ratio || ""),
    artist: String(preferences.artist || stored.artist || ""),
  };
  const fallbackRatio = state.config.defaultRatio
    || optionValue(state.config.ratios?.[0])
    || "2:3";
  state.promptDefaults = {
    ratio: hasOptionValue(state.config.ratios, persisted.ratio) ? persisted.ratio : fallbackRatio,
    artist: normalizedArtistSelection(persisted.artist),
  };
}

function persistCanvasPreferences() {
  if (!bridge || !canvasId) return;
  const payload = {
    lastCanvasId: canvasId,
    ratio: state.promptDefaults.ratio || "",
    artist: state.promptDefaults.artist || "",
  };
  state.preferencesSaveChain = state.preferencesSaveChain
    .catch(() => undefined)
    .then(() => bridge.apiPost("canvas/preferences", payload))
    .catch((error) => console.warn("Canvas preferences save failed", error));
}

function rememberPromptDefaults(updates) {
  state.promptDefaults = { ...state.promptDefaults, ...updates };
  try {
    localStorage.setItem(PROMPT_DEFAULTS_KEY, JSON.stringify(state.promptDefaults));
  } catch (_) {
    // The current browser may disable local storage.
  }
  persistCanvasPreferences();
}

function createNoteNode(point = null) {
  const center = point || suggestedNodeCenter(260);
  return {
    id: uid("note"),
    type: "note",
    x: center.x - 130,
    y: center.y - 100,
    width: 260,
    height: 232,
    title: "备注",
    note: "",
    createdAt: new Date().toISOString(),
  };
}

function addNode(node) {
  pushHistory();
  state.nodes.push(node);
  setSelection([node.id], node.id);
  recordOperation("添加节点", node.type === "image" ? "图片" : node.type === "note" ? "备注" : "提示词");
  renderAll();
  scheduleSave();
}

function findNode(id) {
  return state.nodes.find((node) => node.id === id);
}

function selectedNodeIds() {
  return state.selectedIds.filter((id) => !!findNode(id));
}

function isNodeSelected(id) {
  return state.selectedIds.includes(id);
}

function setSelection(ids, primaryId = "") {
  setSelectionContextMenu(false);
  const previous = state.selectedIds.join(",");
  const previousPrimary = state.selectedId;
  state.selectedIds = [...new Set(ids)].filter((id) => !!findNode(id));
  state.selectedId = state.selectedIds.includes(primaryId)
    ? primaryId
    : state.selectedIds[state.selectedIds.length - 1] || "";
  updateSelectionControls();
  const next = state.selectedIds.join(",");
  if (previous !== next || previousPrimary !== state.selectedId) {
    const selected = findNode(state.selectedId);
    const detail = state.selectedIds.length > 1
      ? `${state.selectedIds.length} 个节点`
      : selected?.title || `${state.selectedIds.length} 个节点`;
    // recordOperation refreshes the recorder, so selection and diagnostics
    // move together without rebuilding the canvas or rendering the bar twice.
    recordOperation(
      state.selectedIds.length > 1 ? "多选节点" : state.selectedIds.length ? "选择节点" : "取消选择",
      detail,
    );
  }
}

function clearSelection() {
  setSelection([]);
}

function updateSelectionControls() {
  const multiSelected = selectedNodeIds().length >= 2;
  els.arrangeSelectionBtn.classList.toggle("visible", multiSelected);
  document.body.classList.toggle("multi-selection-active", multiSelected);
}

function deleteNodes(ids) {
  const deleteIds = new Set(ids.filter((id) => !!findNode(id)));
  if (!deleteIds.size) return;
  pushHistory();
  if (deleteIds.has(state.contextMenuNodeId)) setNodeContextMenu(false);
  setSelectionContextMenu(false);
  // Removing an image also removes its source-specific retag state from any
  // prompt that survives the deletion. Otherwise the orphaned prompt can
  // reuse tags/seed from an image that is no longer connected to it.
  state.connections.forEach((edge) => {
    if (!deleteIds.has(edge.source) || deleteIds.has(edge.target)) return;
    const source = findNode(edge.source);
    const target = findNode(edge.target);
    if (source?.type === "image" && target?.type === "prompt") {
      clearRetagCache(target);
      target.statusText = "";
    }
  });
  state.nodes = state.nodes.filter((node) => !deleteIds.has(node.id));
  state.connections = state.connections.filter(
    (edge) => !deleteIds.has(edge.source) && !deleteIds.has(edge.target),
  );
  clearSelection();
  recordOperation("删除节点", `已删除 ${deleteIds.size} 个节点`);
  renderAll();
  scheduleSave();
}

function deleteNode(id) {
  deleteNodes([id]);
}

function deleteConnection(sourceId, targetId) {
  const index = state.connections.findIndex(
    (edge) => edge.source === sourceId && edge.target === targetId,
  );
  if (index < 0) return;
  pushHistory();
  state.connections.splice(index, 1);
  const source = findNode(sourceId);
  const target = findNode(targetId);
  if (source?.type === "image" && target?.type === "prompt") {
    clearRetagCache(target);
    target.statusText = "";
  }
  renderAll();
  scheduleSave();
  toast("已删除连线");
  recordOperation("删除连线", `${sourceId} → ${targetId}`);
}

function duplicateNode(id) {
  const source = findNode(id);
  if (!source) return;
  pushHistory();
  const copy = {
    ...source,
    id: uid(source.type),
    x: source.x + 36,
    y: source.y + 36,
    createdAt: new Date().toISOString(),
    status: "",
    error: "",
  };
  state.nodes.push(copy);
  setSelection([copy.id], copy.id);
  recordOperation("复制节点", source.type === "image" ? "图片" : source.type === "note" ? "备注" : "提示词");
  renderAll();
  scheduleSave();
}

function selectNode(id, mode = false) {
  if (!findNode(id)) return;
  // ``true`` is kept as a backwards-compatible shorthand for toggle mode.
  // New call sites use named modes so Shift (add) and Ctrl/Cmd (toggle) do
  // not accidentally share the same behavior.
  const options = typeof mode === "boolean" ? { toggle: mode } : (mode || {});
  if (options.toggle) {
    const next = new Set(selectedNodeIds());
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelection([...next], next.has(id) ? id : "");
  } else if (options.additive) {
    const next = new Set(selectedNodeIds());
    next.add(id);
    setSelection([...next], id);
  } else {
    if (state.selectedIds.length === 1 && isNodeSelected(id)) return;
    setSelection([id], id);
  }
  document.querySelectorAll(".node.selected").forEach((node) => node.classList.remove("selected"));
  selectedNodeIds().forEach((selectedId) => {
    document.querySelector(`[data-node-id="${CSS.escape(selectedId)}"]`)?.classList.add("selected");
  });
  renderConnections();
}

function makeAction(iconName, title, action, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `node-action${className ? ` ${className}` : ""}`;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.appendChild(icon(iconName));
  button.addEventListener("pointerdown", (event) => event.stopPropagation());
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    action();
  });
  return button;
}

function makeNodeShell(node, label) {
  const element = document.createElement("article");
  element.className = `node ${node.type}-node${isNodeSelected(node.id) ? " selected" : ""}${node.status === "generating" ? " generating" : ""}`;
  element.dataset.nodeId = node.id;
  element.style.left = `${node.x}px`;
  element.style.top = `${node.y}px`;
  element.style.width = `${node.width || 320}px`;

  const handle = document.createElement("header");
  handle.className = "node-head";
  const nodeLabel = document.createElement("span");
  nodeLabel.className = "node-title-wrap";
  const kind = document.createElement("span");
  kind.className = "node-type-icon";
  kind.appendChild(icon({ prompt: "text-cursor-input", image: "image", note: "notebook-pen" }[node.type] || "box"));
  const text = document.createElement("span");
  text.className = "node-title";
  text.textContent = label;
  nodeLabel.append(kind, text);

  const actions = document.createElement("span");
  actions.className = "node-actions";
  actions.append(
    makeAction("copy", "复制节点", () => duplicateNode(node.id)),
    makeAction("x", "删除节点", () => deleteNode(node.id), "delete"),
  );
  handle.append(nodeLabel, actions);
  element.appendChild(handle);
  element.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    bringNodeToFront(node.id, element);
    if (event.ctrlKey || event.metaKey) selectNode(node.id, { toggle: true });
    else if (event.shiftKey) selectNode(node.id, { additive: true });
    else if (!isNodeSelected(node.id)) selectNode(node.id);
  });
  attachNodeDrag(handle, element, node);
  return element;
}

function artistDisplayName(node) {
  if (!node || node.raw) return "";
  if (node.type === "image") return String(node.meta?.artist || "").trim();
  if (node.artist) {
    const option = (state.config.artists || []).find((item) => item.value === node.artist);
    return String(option?.label || node.artist).trim();
  }
  return String(state.config.defaultArtist || "").trim();
}

function bringNodeToFront(id, element = null) {
  const index = state.nodes.findIndex((node) => node.id === id);
  if (index < 0 || index === state.nodes.length - 1) return;
  const [node] = state.nodes.splice(index, 1);
  state.nodes.push(node);
  const current = element || document.querySelector(`[data-node-id="${CSS.escape(id)}"]`);
  if (current?.parentElement === els.nodeLayer) els.nodeLayer.appendChild(current);
  scheduleSave(800);
}

function renderPromptNode(node) {
  const element = makeNodeShell(node, node.title || "提示词节点");
  element.style.height = `${node.height || 360}px`;
  const sourceImage = sourceImageForPrompt(node.id);
  const body = document.createElement("div");
  body.className = "node-body";

  const prompt = document.createElement("textarea");
  prompt.className = "prompt-text";
  prompt.placeholder = "描述画面，支持中文自动翻译或 NAI tags…";
  prompt.value = node.prompt || "";
  prompt.maxLength = 6000;
  let promptEdited = false;
  prompt.addEventListener("input", () => {
    node.prompt = prompt.value;
    promptEdited = true;
    node.error = "";
    clearDebugTrace(node);
    // Translation depends on the handwritten text, but image retagging does
    // not.  Keep the source tags/seed cached so changing an overlay prompt
    // never sends the same image to the tagger a second time.
    clearTranslationCache(node);
    scheduleSave();
  });
  prompt.addEventListener("blur", () => {
    if (!promptEdited) return;
    promptEdited = false;
    const length = String(node.prompt || "").trim().length;
    recordOperation("编辑提示词", `${node.title || "提示词节点"} · ${length} 字`);
  });
  prompt.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      runPromptNode(node.id);
    }
  });

  const options = document.createElement("div");
  options.className = "prompt-options";
  const ratioField = makeSelectField("画幅", state.config.ratios, node.ratio, (value) => {
    node.ratio = value;
    // 手动选过画幅后，首次链接图片的自动对齐不再生效
    node.meta = { ...(node.meta || {}), ratioManual: true };
    clearDebugTrace(node);
    rememberPromptDefaults({ ratio: value });
    scheduleSave();
    recordOperation("修改画幅", `${node.title || "提示词节点"} · ${value || "默认"}`);
  });
  const artistOptions = canvasArtistOptions();
  const artistField = makeSelectField("画师", artistOptions, node.artist, (value) => {
    node.artist = value;
    clearDebugTrace(node);
    rememberPromptDefaults({ artist: value });
    scheduleSave();
    recordOperation("修改画师", `${node.title || "提示词节点"} · ${value || "无预设"}`);
  });
  options.append(ratioField, artistField);
  const footer = document.createElement("div");
  footer.className = "node-footer";
  const rawLabel = document.createElement("label");
  rawLabel.className = "raw-toggle";
  rawLabel.dataset.tooltip = "不使用画师预设和质量词，按原始英文 NAI tags 生成；普通负面提示词仍然生效。";
  const raw = document.createElement("input");
  raw.type = "checkbox";
  raw.checked = !!node.raw;
  raw.addEventListener("change", () => {
    node.raw = raw.checked;
    clearDebugTrace(node);
    scheduleSave();
    recordOperation("切换原始提示词", raw.checked ? "开启" : "关闭");
  });
  raw.addEventListener("click", (event) => {
    if (event.detail > 0) raw.blur();
  });
  rawLabel.append(raw, document.createTextNode("原始提示词"));

  const commands = document.createElement("div");
  commands.className = "node-commands";

  const generate = document.createElement("button");
  generate.type = "button";
  generate.className = "generate-btn";
  generate.disabled = !!node.status || !state.config.configured;
  generate.append(icon("wand-sparkles"), document.createTextNode("生成"));
  generate.title = state.config.configured
    ? (sourceImage ? "反推原图并生成图片 (Ctrl+Enter)" : "生成图片 (Ctrl+Enter)")
    : "请先配置生图提供商";
  generate.addEventListener("pointerdown", (event) => event.stopPropagation());
  generate.addEventListener("click", (event) => {
    event.stopPropagation();
    runPromptNode(node.id);
  });
  commands.append(generate);
  footer.append(rawLabel, commands);

  const status = document.createElement("div");
  status.className = `node-status${node.error ? " error" : ""}`;
  status.textContent = node.error
    || node.statusText
    || (sourceImage ? "已连接原图，生成时自动反推" : "Ctrl + Enter 快速生成");

  const inputPort = document.createElement("span");
  inputPort.className = "port in";
  attachConnectionPort(inputPort, node.id, "in");
  const outputPort = document.createElement("span");
  outputPort.className = "port out";
  attachConnectionPort(outputPort, node.id, "out");
  element.append(body, inputPort, outputPort);
  body.append(prompt, options, footer, status);
  const retagLayerCard = makeRetagLayerCard(node, sourceImage, element);
  if (retagLayerCard) element.appendChild(retagLayerCard);
  const resizeHandle = document.createElement("span");
  resizeHandle.className = "node-resize-handle";
  resizeHandle.setAttribute("aria-hidden", "true");
  attachNodeResize(resizeHandle, element, node);
  element.appendChild(resizeHandle);
  return element;
}

const DEBUG_SECTIONS = [
  // 调试栏标题保持中文；中英双语只用于下面的提示词标签分类。
  { key: "retag", label: "反推" },
  { key: "generate", label: "生图" },
];

const DEBUG_MERGE_NOTE_KEYS = ["提示词冲突处理", "mergeDetails", "promptMerge"];
const DEBUG_CATEGORY_LABELS = {
  identity: "角色",
  subject: "主体数量",
  hair: "发型",
  eyes: "眼睛",
  skin: "皮肤妆容",
  traits: "身体特征",
  accessory: "配饰",
  clothing: "服装",
  legwear: "腿部穿着",
  footwear: "鞋子",
  handwear: "手套",
  pose: "姿势",
  gaze: "视线",
  gesture: "动作手势",
  expression: "表情",
  composition: "构图",
  background: "背景",
  atmosphere: "氛围天气",
  lighting: "光照",
  style: "风格",
  other: "其他细节",
};

const RETAG_LAYER_CATEGORY_ORDER = Object.freeze([
  "identity",
  "subject",
  "expression",
  "hair",
  "eyes",
  "skin",
  "traits",
  "accessory",
  "clothing",
  "legwear",
  "footwear",
  "handwear",
  "pose",
  "gaze",
  "gesture",
  "composition",
  "background",
  "atmosphere",
  "lighting",
  "style",
  "other",
]);

function normalizeRetagTagGroups(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result = {};
  const seen = new Set();
  RETAG_LAYER_CATEGORY_ORDER.forEach((category) => {
    const rawTags = Array.isArray(value[category]) ? value[category] : [];
    const tags = [];
    rawTags.slice(0, 64).forEach((rawTag) => {
      const tag = String(rawTag || "").trim().slice(0, 160);
      const key = tag.toLocaleLowerCase();
      if (!tag || seen.has(key)) return;
      seen.add(key);
      tags.push(tag);
    });
    if (tags.length) result[category] = tags;
  });
  return result;
}

function retagTagLookupKey(value) {
  let tag = String(value || "").trim().replace(/^[,;\s]+|[,;\s]+$/g, "");
  while (
    tag.length >= 2
    && ((tag.startsWith("{") && tag.endsWith("}"))
      || (tag.startsWith("[") && tag.endsWith("]")))
  ) {
    tag = tag.slice(1, -1).trim();
  }
  return tag.toLocaleLowerCase().replace(/[\s_]+/g, "_").replace(/^_+|_+$/g, "");
}

function normalizeRetagTagTranslations(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result = {};
  Object.entries(value).slice(0, 320).forEach(([rawTag, rawName]) => {
    const key = retagTagLookupKey(rawTag);
    const name = String(rawName || "").trim().slice(0, 160);
    if (key && name) result[key] = name;
  });
  return result;
}

// 与后端 core/char_prompts.normalize_char_entries 的边界保持一致
const MAX_CHAR_PROMPTS = 16;

function normalizeCharPromptEntries(value) {
  if (!Array.isArray(value)) return [];
  const result = [];
  for (const item of value.slice(0, MAX_CHAR_PROMPTS)) {
    if (!item || typeof item !== "object") continue;
    const prompt = String(item.prompt ?? item.caption ?? "").trim().slice(0, 2000);
    if (!prompt) continue;
    const entry = {
      prompt,
      negative_prompt: String(item.negative_prompt ?? item.negative ?? "").trim().slice(0, 2000),
      position: String(item.position || "").trim().toUpperCase(),
    };
    result.push(entry);
  }
  return result;
}

function bilingualRetagTagText(tag, translations) {
  const name = translations[retagTagLookupKey(tag)] || "";
  return name ? `${tag} / ${name}` : tag;
}

function normalizeRetagLayerModes(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result = {};
  RETAG_LAYER_CATEGORY_ORDER.forEach((category) => {
    const mode = String(value[category] || "").toLowerCase();
    if (["auto", "preserve", "drop"].includes(mode)) result[category] = mode;
  });
  return result;
}

function retagLayerMode(node, category) {
  const mode = normalizeRetagLayerModes(node?.meta?.retagLayerModes)[category];
  return mode === "preserve" || mode === "drop" ? mode : "auto";
}

function retagLayerCategoryLists(node) {
  const groups = normalizeRetagTagGroups(node?.meta?.retagTagGroups);
  const categories = Object.keys(groups);
  return {
    preserve: categories.filter((category) => retagLayerMode(node, category) === "preserve"),
    drop: categories.filter((category) => retagLayerMode(node, category) === "drop"),
  };
}

function collapseRetagLayers() {
  let changed = false;
  state.nodes.forEach((node) => {
    if (node.type !== "prompt" || node.meta?.retagLayerExpanded !== true) return;
    node.meta = { ...(node.meta || {}), retagLayerExpanded: false };
    changed = true;
  });
  if (changed) scheduleSave();
  return changed;
}

function makeRetagLayerCard(node, sourceImage, nodeElement) {
  if (!sourceImage) return null;
  const groups = normalizeRetagTagGroups(node?.meta?.retagTagGroups);
  const tagTranslations = normalizeRetagTagTranslations(node?.meta?.retagTagTranslations);
  const entries = RETAG_LAYER_CATEGORY_ORDER
    .filter((category) => Array.isArray(groups[category]) && groups[category].length)
    .map((category) => [category, groups[category]]);
  if (!entries.length) return null;

  const card = document.createElement("aside");
  card.className = "retag-layer-card";
  card.dataset.nodeId = node.id;
  card.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
    bringNodeToFront(node.id, nodeElement);
    if (!isNodeSelected(node.id)) selectNode(node.id);
  });

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "retag-layer-toggle";
  toggle.setAttribute("aria-expanded", "false");
  const title = document.createElement("span");
  title.className = "retag-layer-title";
  title.append(icon("layers-3"), document.createTextNode("原图标签图层"));
  const summary = document.createElement("span");
  summary.className = "retag-layer-summary";
  const chevron = icon("chevron-down", "retag-layer-chevron");
  toggle.append(title, summary, chevron);

  const body = document.createElement("div");
  body.className = "retag-layer-body";
  body.hidden = true;
  const help = document.createElement("p");
  help.className = "retag-layer-help";
  help.textContent = "自动按改图规则覆盖同类原图标签；锁定会保留原图分类；移除只删除原图标签，手写同类标签仍可加入。";
  body.appendChild(help);

  const refreshSummary = () => {
    const lists = retagLayerCategoryLists(node);
    const parts = [`${entries.length} 类`];
    if (lists.preserve.length) parts.push(`锁定 ${lists.preserve.length}`);
    if (lists.drop.length) parts.push(`移除 ${lists.drop.length}`);
    summary.textContent = parts.join(" · ");
  };

  entries.forEach(([category, tags]) => {
    const row = document.createElement("section");
    row.className = "retag-layer-row";
    const rowHead = document.createElement("div");
    rowHead.className = "retag-layer-row-head";
    const label = document.createElement("span");
    label.className = "retag-layer-label";
    label.textContent = DEBUG_CATEGORY_LABELS[category] || category;
    const modeGroup = document.createElement("span");
    modeGroup.className = "retag-layer-modes";
    modeGroup.setAttribute("role", "group");
    modeGroup.setAttribute("aria-label", `${label.textContent}处理方式`);
    const modeButtons = [];
    [
      ["auto", "自动"],
      ["preserve", "锁定"],
      ["drop", "移除"],
    ].forEach(([mode, modeLabel]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `retag-layer-mode is-${mode}`;
      button.textContent = modeLabel;
      button.title = mode === "auto"
        ? "按改图逻辑自动覆盖冲突分类"
        : mode === "preserve"
          ? "保留这一类原图标签，即使手写提示词与其冲突"
          : "移除这一类原图标签；手写的新标签不受影响";
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        if (retagLayerMode(node, category) === mode) return;
        pushHistory();
        const nextModes = normalizeRetagLayerModes(node.meta?.retagLayerModes);
        if (mode === "auto") delete nextModes[category];
        else nextModes[category] = mode;
        node.meta = { ...(node.meta || {}), retagLayerModes: nextModes };
        clearDebugTrace(node);
        modeButtons.forEach(({ element, value }) => {
          const active = value === mode;
          element.classList.toggle("active", active);
          element.setAttribute("aria-pressed", String(active));
        });
        refreshSummary();
        scheduleSave();
      });
      modeButtons.push({ element: button, value: mode });
      modeGroup.appendChild(button);
    });
    const currentMode = retagLayerMode(node, category);
    modeButtons.forEach(({ element, value }) => {
      const active = value === currentMode;
      element.classList.toggle("active", active);
      element.setAttribute("aria-pressed", String(active));
    });
    rowHead.append(label, modeGroup);

    const tagList = document.createElement("div");
    tagList.className = "retag-layer-tags";
    tags.forEach((tag) => {
      const chip = document.createElement("code");
      chip.className = "retag-layer-tag";
      chip.textContent = bilingualRetagTagText(tag, tagTranslations);
      chip.title = chip.textContent;
      tagList.appendChild(chip);
    });
    row.append(rowHead, tagList);
    body.appendChild(row);
  });

  const setOpen = (open) => {
    card.classList.toggle("open", open);
    body.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  };
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = !card.classList.contains("open");
    node.meta = { ...(node.meta || {}), retagLayerExpanded: open };
    setOpen(open);
    scheduleSave();
  });
  body.addEventListener("wheel", (event) => {
    if (isNodeSelected(node.id)) event.stopPropagation();
  }, { passive: true });
  refreshSummary();
  setOpen(node.meta?.retagLayerExpanded === true);
  card.append(toggle, body);
  return card;
}

function formatDebugMs(ms) {
  const value = Number(ms) || 0;
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

function formatDebugValue(value) {
  if (value === null || value === undefined) return "(无)";
  if (Array.isArray(value)) {
    return value.map((item) => formatDebugValue(item)).join(", ");
  }
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${key}=${formatDebugValue(item)}`)
      .join("  ");
  }
  return String(value);
}

function debugMergeDetails(run) {
  const notes = run?.notes;
  if (!notes || typeof notes !== "object") return null;
  for (const key of DEBUG_MERGE_NOTE_KEYS) {
    const value = notes[key];
    if (value && typeof value === "object" && !Array.isArray(value)) return value;
  }
  return null;
}

function isDebugMergeNote(key) {
  return DEBUG_MERGE_NOTE_KEYS.includes(String(key));
}

function debugMergeValues(value) {
  return Array.isArray(value)
    ? value.map((item) => String(item || "").trim()).filter(Boolean)
    : [];
}

function debugLayerCategoryLabels(value) {
  return debugMergeValues(value).map(
    (category) => DEBUG_CATEGORY_LABELS[category] || category,
  );
}

function appendDebugTagGroup(parent, label, values, className = "", translations = {}) {
  const tags = debugMergeValues(values);
  if (!tags.length) return;

  const group = document.createElement("div");
  group.className = `debug-merge-group${className ? ` ${className}` : ""}`;
  const title = document.createElement("span");
  title.className = "debug-merge-group-label";
  title.textContent = label;
  group.appendChild(title);

  const tagList = document.createElement("div");
  tagList.className = "debug-merge-tags";
  const visible = tags.slice(0, 40);
  visible.forEach((tag) => {
    const chip = document.createElement("code");
    chip.className = "debug-merge-tag";
    chip.textContent = bilingualRetagTagText(tag, translations);
    chip.title = chip.textContent;
    tagList.appendChild(chip);
  });
  if (tags.length > visible.length) {
    const more = document.createElement("span");
    more.className = "debug-merge-more";
    more.textContent = `+${tags.length - visible.length}`;
    tagList.appendChild(more);
  }
  group.appendChild(tagList);
  parent.appendChild(group);
}

function appendDebugCategoryGroups(parent, label, values, className = "", translations = {}) {
  if (!values || typeof values !== "object" || Array.isArray(values)) return;
  const entries = Object.entries(values).filter(([, tags]) => debugMergeValues(tags).length);
  if (!entries.length) return;

  const wrapper = document.createElement("div");
  wrapper.className = `debug-merge-category-block${className ? ` ${className}` : ""}`;
  const title = document.createElement("span");
  title.className = "debug-merge-group-label";
  title.textContent = label;
  wrapper.appendChild(title);
  entries.forEach(([category, tags]) => {
    const row = document.createElement("div");
    row.className = "debug-merge-category-row";
    const name = document.createElement("span");
    name.className = "debug-merge-category-name";
    name.textContent = DEBUG_CATEGORY_LABELS[category] || category;
    row.appendChild(name);
    const list = document.createElement("div");
    list.className = "debug-merge-tags";
    debugMergeValues(tags).slice(0, 40).forEach((tag) => {
      const chip = document.createElement("code");
      chip.className = "debug-merge-tag";
      chip.textContent = bilingualRetagTagText(tag, translations);
      chip.title = chip.textContent;
      list.appendChild(chip);
    });
    row.appendChild(list);
    wrapper.appendChild(row);
  });
  parent.appendChild(wrapper);
}

function makeDebugMergeSummary(details, translations = {}) {
  if (!details || typeof details !== "object") return null;
  const section = document.createElement("section");
  section.className = "debug-merge-summary";

  const head = document.createElement("div");
  head.className = "debug-merge-head";
  head.textContent = "提示词冲突处理";
  section.appendChild(head);

  const counts = document.createElement("div");
  counts.className = "debug-merge-counts";
  [
    ["added", "新增", details.added],
    ["removed", "删除", details.removed],
    ["retained", "保留", details.retained],
    ["duplicates", "去重", details.duplicates],
  ].forEach(([tone, label, values]) => {
    const item = document.createElement("span");
    item.className = `debug-merge-count is-${tone}`;
    item.textContent = `${label} ${debugMergeValues(values).length}`;
    counts.appendChild(item);
  });
  section.appendChild(counts);

  appendDebugTagGroup(section, "新增提示词", details.added, "is-added", translations);
  appendDebugTagGroup(section, "删除冲突", details.removed, "is-removed", translations);
  appendDebugTagGroup(section, "保留原图", details.retained, "is-retained", translations);
  appendDebugTagGroup(section, "重复去重", details.duplicates, "is-duplicates", translations);
  appendDebugTagGroup(
    section,
    "锁定图层",
    debugLayerCategoryLabels(details.preserveCategories),
    "is-retained",
  );
  appendDebugTagGroup(
    section,
    "移除图层",
    debugLayerCategoryLabels(details.dropCategories),
    "is-removed",
  );
  appendDebugCategoryGroups(section, "覆盖分类", details.overrides, "is-overrides", translations);
  appendDebugCategoryGroups(section, "冲突分类", details.conflicts, "is-conflicts", translations);
  return section;
}

function debugMergePlainText(details, translations = {}) {
  if (!details || typeof details !== "object") return [];
  const lines = ["  提示词冲突处理"];
  [
    ["新增提示词", details.added],
    ["删除冲突", details.removed],
    ["保留原图", details.retained],
    ["重复去重", details.duplicates],
  ].forEach(([label, values]) => {
    const tags = debugMergeValues(values).map((tag) => bilingualRetagTagText(tag, translations));
    if (tags.length) lines.push(`    ${label}: ${tags.join(", ")}`);
  });
  [
    ["锁定图层", details.preserveCategories],
    ["移除图层", details.dropCategories],
  ].forEach(([label, values]) => {
    const categories = debugLayerCategoryLabels(values);
    if (categories.length) lines.push(`    ${label}: ${categories.join(", ")}`);
  });
  [
    ["覆盖分类", details.overrides],
    ["冲突分类", details.conflicts],
  ].forEach(([label, groups]) => {
    if (!groups || typeof groups !== "object" || Array.isArray(groups)) return;
    Object.entries(groups).forEach(([category, values]) => {
      const tags = debugMergeValues(values).map((tag) => bilingualRetagTagText(tag, translations));
      if (tags.length) {
        lines.push(`    ${label} · ${DEBUG_CATEGORY_LABELS[category] || category}: ${tags.join(", ")}`);
      }
    });
  });
  return lines;
}

function debugPlainText(runs, translations = {}) {
  const lines = [];
  runs.forEach(({ label, run }) => {
    lines.push(`${label} 总耗时 ${run.totalMs}ms`);
    (run.stages || []).forEach((stage) => {
      lines.push(`  · ${stage.name} ${stage.ms}ms${stage.error ? ` · 失败：${stage.error}` : ""}`);
    });
    lines.push(...debugMergePlainText(debugMergeDetails(run), translations));
    Object.entries(run.notes || {}).forEach(([key, value]) => {
      if (isDebugMergeNote(key)) return;
      lines.push(`  ${key}: ${formatDebugValue(value)}`);
    });
    lines.push("");
  });
  return lines.join("\n").trim();
}

function debugRunsForNode(node) {
  if (!node) return [];
  const namedRuns = DEBUG_SECTIONS
    .map((section) => ({ label: section.label, run: node.meta?.debug?.[section.key] }))
    .filter((item) => item.run && typeof item.run === "object");
  if (namedRuns.length) return namedRuns;

  // Compatibility with workspaces saved by early debug builds, where one
  // trace was stored directly under ``meta.debug`` instead of being grouped
  // as ``retag`` / ``generate``.
  const legacyRun = node.meta?.debug;
  if (!legacyRun || typeof legacyRun !== "object") return [];
  if (!(legacyRun.scope || legacyRun.stages || legacyRun.notes)) return [];
  return [{
    label: String(legacyRun.scope || "").includes("retag") ? "反推" : "生图",
    run: legacyRun,
  }];
}

/** 调试模式专用：状态栏自己负责折叠，这里只渲染实际流水内容。 */
function makeDebugPanel(node) {
  const runs = debugRunsForNode(node);

  if (!debugModeEnabled() || !runs.length) return null;

  const body = document.createElement("div");
  body.className = "debug-body";
  const tagTranslations = normalizeRetagTagTranslations(node.meta?.retagTagTranslations);

  runs.forEach(({ label, run }) => {
    const section = document.createElement("section");
    section.className = "debug-run";

    const head = document.createElement("div");
    head.className = "debug-run-head";
    head.textContent = `${label} · ${formatDebugMs(run.totalMs)}`;
    section.appendChild(head);

    const stages = (run.stages || [])
      .map((stage) => `${stage.name} ${formatDebugMs(stage.ms)}`)
      .join(" · ");
    if (stages) {
      const line = document.createElement("div");
      line.className = "debug-stages";
      line.textContent = stages;
      section.appendChild(line);
    }

    (run.stages || []).filter((stage) => stage.error).forEach((stage) => {
      const line = document.createElement("div");
      line.className = "debug-error";
      line.textContent = `${stage.name} 失败：${stage.error}`;
      section.appendChild(line);
    });

    const mergeDetails = debugMergeDetails(run);
    const mergeSummary = makeDebugMergeSummary(mergeDetails, tagTranslations);
    if (mergeSummary) section.appendChild(mergeSummary);

    Object.entries(run.notes || {}).filter(([key]) => !isDebugMergeNote(key)).forEach(([key, value]) => {
      const row = document.createElement("div");
      row.className = "debug-row";
      const name = document.createElement("span");
      name.className = "debug-key";
      name.textContent = key;
      const text = document.createElement("span");
      text.className = "debug-value";
      text.textContent = formatDebugValue(value);
      row.append(name, text);
      section.appendChild(row);
    });

    body.appendChild(section);
  });

  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "debug-copy";
  copy.textContent = "复制全部";
  copy.addEventListener("click", (event) => {
    event.stopPropagation();
    copyPlainText(debugPlainText(runs, tagTranslations), "复制调试信息");
  });
  body.appendChild(copy);

  return body;
}

function makeOperationLogPanel() {
  const section = document.createElement("section");
  section.className = "operation-log-panel";

  const head = document.createElement("div");
  head.className = "operation-log-head";
  head.textContent = `操作记录 · ${state.operationLog.length}`;
  section.appendChild(head);

  const list = document.createElement("div");
  list.className = "operation-log-list";
  const entries = state.operationLog.slice(-OPERATION_VISIBLE_LIMIT).reverse();
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "operation-log-empty";
    empty.textContent = "暂无操作记录";
    list.appendChild(empty);
  } else {
    entries.forEach((entry) => {
      const row = document.createElement("div");
      row.className = `operation-log-entry is-${entry.level}`;
      const time = document.createElement("time");
      time.className = "operation-log-time";
      time.dateTime = entry.timestamp;
      time.textContent = formatOperationTime(entry.timestamp);
      const action = document.createElement("strong");
      action.className = "operation-log-action";
      action.textContent = entry.action;
      row.append(time, action);
      if (entry.detail) {
        const detail = document.createElement("span");
        detail.className = "operation-log-detail";
        detail.textContent = entry.detail;
        detail.title = entry.detail;
        row.appendChild(detail);
      }
      list.appendChild(row);
    });
  }
  section.appendChild(list);
  return section;
}

function setDebugBarOpen(open) {
  state.debugBarOpen = !!open;
  try { localStorage.setItem(RECORDER_OPEN_KEY, state.debugBarOpen ? "1" : "0"); } catch (_) { /* ignore */ }
  els.debugBarToggle?.setAttribute("aria-expanded", String(state.debugBarOpen));
  els.debugBarToggle?.setAttribute("aria-label", state.debugBarOpen ? "收起操作记录" : "展开操作记录");
  els.debugBar?.classList.toggle("open", state.debugBarOpen);
  els.debugBarBody?.toggleAttribute("hidden", !state.debugBarOpen);
  const chevron = els.debugBarToggle?.querySelector(".debug-bar-chevron");
  chevron?.classList.toggle("rotated", state.debugBarOpen);
  alignDebugBar();
  if (els.assetPanel.classList.contains("open")) {
    window.requestAnimationFrame(() => {
      alignAssetPanel();
      updateAssetGridMetrics();
    });
  }
}

function renderDebugBar() {
  if (!els.debugBar) return;
  // The command-line recorder is always present.  The debug switch controls
  // only the expensive/verbose provider trace shown below the operation log.
  els.debugBar.hidden = false;
  const selectedNode = findNode(state.selectedId);
  const candidates = debugModeEnabled() ? [...state.nodes].reverse() : [];
  const linkedPrompts = selectedNode?.type === "image"
    && debugModeEnabled()
    ? state.connections
      .filter((edge) => edge.source === selectedNode.id || edge.target === selectedNode.id)
      .map((edge) => findNode(edge.source === selectedNode.id ? edge.target : edge.source))
      .filter((item) => item?.type === "prompt" && item.meta?.debug)
    : [];
  const linkedPrompt = linkedPrompts.find((item) => item.id === state.lastDebugNodeId)
    || linkedPrompts[0]
    || null;
  const lastDebugNode = findNode(state.lastDebugNodeId);
  // When a prompt is selected, the bar belongs to that prompt even before it
  // has a trace. Falling through to another node would show stale diagnostics
  // immediately after the user edits the selected prompt or switches mode.
  const node = selectedNode?.type === "prompt"
    ? selectedNode
    : linkedPrompt
      || (lastDebugNode?.meta?.debug ? lastDebugNode : null)
      || candidates.find((item) => item?.meta?.debug);
  const runs = debugRunsForNode(node);
  const total = runs.reduce((sum, item) => sum + (Number(item.run.totalMs) || 0), 0);
  const mergeDetails = runs.map(({ run }) => debugMergeDetails(run)).find(Boolean);
  const conflictCount = mergeDetails
    ? debugMergeValues(mergeDetails.removed).length
    : 0;
  const latest = state.operationLog[state.operationLog.length - 1];
  const latestText = latest
    ? `${latest.action}${latest.detail ? ` · ${latest.detail}` : ""}`
    : "就绪";
  els.debugBarSummary.textContent = node && runs.length
    ? `调试信息 · ${formatDebugMs(total)} · ${node.title || "提示词节点"}`
      + (mergeDetails && conflictCount ? ` · 冲突 ${conflictCount}` : "")
    : `操作记录 · ${latestText}`;
  els.debugBarBody.replaceChildren();
  els.debugBarBody.appendChild(makeOperationLogPanel());
  if (debugModeEnabled()) {
    const panel = makeDebugPanel(node);
    if (panel) {
      els.debugBarBody.appendChild(panel);
    } else {
      const empty = document.createElement("div");
      empty.className = "debug-empty";
      empty.textContent = "运行生成或反推后，这里会显示详细调试信息";
      els.debugBarBody.appendChild(empty);
    }
  } else {
    const empty = document.createElement("div");
    empty.className = "debug-empty";
    empty.textContent = "详细调试模式未开启；点击顶部调试按钮查看生成链路";
    els.debugBarBody.appendChild(empty);
  }
  setDebugBarOpen(state.debugBarOpen);
  refreshIcons(els.debugBar);
}

function makeSelectField(label, items, value, onChange) {
  const field = document.createElement("label");
  field.className = "field-label";
  const caption = document.createElement("span");
  caption.textContent = label;
  const select = document.createElement("select");
  select.className = "node-select";
  (items || []).forEach((item) => {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    select.appendChild(option);
  });
  select.value = value || "";
  select.addEventListener("change", () => onChange(select.value));
  field.append(caption, select);
  return field;
}

function renderImageNode(node) {
  hydrateImageAsset(node);
  const element = makeNodeShell(node, node.title || "生成结果");
  const actions = element.querySelector(".node-actions");
  const downloadLocked = canvasGenerationActive();
  const downloadAction = makeAction(
    "download",
    downloadLocked ? "生图期间暂不可下载" : "下载图片",
    () => downloadImage(node),
    downloadLocked ? "locked" : "",
  );
  downloadAction.setAttribute("aria-disabled", String(downloadLocked));
  actions.insertBefore(downloadAction, actions.firstChild);
  actions.insertBefore(
    makeAction("bookmark-plus", "保存到素材库", () => saveImageToLibrary(node)),
    actions.firstChild,
  );

  const frame = document.createElement("div");
  frame.className = "image-preview-wrap";
  frame.tabIndex = 0;
  frame.setAttribute("role", "button");
  frame.setAttribute("aria-label", "放大图片并查看 Tags");
  frame.title = "点击放大图片并查看 Tags";
  const imageArtist = artistDisplayName(node);
  if (imageArtist) {
    const artistBadge = document.createElement("span");
    artistBadge.className = "image-artist-badge";
    artistBadge.textContent = imageArtist;
    artistBadge.title = `画师预设：${imageArtist}`;
    frame.appendChild(artistBadge);
  }
  frame.addEventListener("click", () => openImageViewer(node));
  frame.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openImageViewer(node);
  });
  if (node.dataUrl) {
    cacheImageAsset(node);
    const image = document.createElement("img");
    image.src = node.dataUrl;
    image.alt = node.title || "画布图片";
    image.draggable = false;
    frame.appendChild(image);
  } else {
    const loading = document.createElement("div");
    loading.className = "image-loading";
    loading.textContent = node.assetError ? "图片读取失败" : "正在读取图片…";
    frame.appendChild(loading);
    ensureAssetLoaded(node);
  }

  const meta = document.createElement("div");
  meta.className = "image-meta";
  const title = document.createElement("strong");
  // 种子比提示词更有用：提示词在卡片里本来就看得到，种子是唯一能复现这张图的信息
  const seed = normalizeNaiSeed(node.meta?.seed) || normalizeNaiSeed(node.meta?.retagSeed);
  title.textContent = seed ? `seed ${seed}` : (node.title || "图片资源");
  title.title = seed ? `种子 ${seed}（点击图片可查看完整提示词）` : title.textContent;
  const detail = document.createElement("span");
  const size = node.meta?.width && node.meta?.height ? `${node.meta.width}×${node.meta.height}` : "原始尺寸";
  detail.textContent = `${size}${node.meta?.ratio ? ` · ${node.meta.ratio}` : ""}`;
  meta.append(title, detail);

  const inputPort = document.createElement("span");
  inputPort.className = "port in";
  attachConnectionPort(inputPort, node.id, "in");
  const outputPort = document.createElement("span");
  outputPort.className = "port out";
  attachConnectionPort(outputPort, node.id, "out");
  const body = document.createElement("div");
  body.className = "node-body";
  body.append(frame, meta);
  const resizeHandle = document.createElement("span");
  resizeHandle.className = "node-resize-handle image-resize-handle";
  resizeHandle.setAttribute("aria-hidden", "true");
  attachImageNodeResize(resizeHandle, element, node);
  element.append(body, inputPort, outputPort, resizeHandle);
  return element;
}

function renderNoteNode(node) {
  const element = makeNodeShell(node, node.title || "备注");
  element.style.height = `${node.height || 232}px`;
  const body = document.createElement("div");
  body.className = "node-body";
  const note = document.createElement("textarea");
  note.className = "note-text";
  note.placeholder = "记录构图方向、迭代想法或待办…";
  note.value = node.note || "";
  note.maxLength = 6000;
  let noteEdited = false;
  note.addEventListener("input", () => {
    node.note = note.value;
    noteEdited = true;
    scheduleSave();
  });
  note.addEventListener("blur", () => {
    if (!noteEdited) return;
    noteEdited = false;
    recordOperation("编辑备注", `${node.title || "备注"} · ${String(node.note || "").trim().length} 字`);
  });
  body.appendChild(note);
  const resizeHandle = document.createElement("span");
  resizeHandle.className = "node-resize-handle";
  resizeHandle.setAttribute("aria-hidden", "true");
  attachNodeResize(resizeHandle, element, node);
  element.append(body, resizeHandle);
  return element;
}

// 可编辑字段用 class 定位，节点重建后靠它把焦点找回来
const EDITABLE_FIELD_CLASSES = ["prompt-text", "note-text"];

function captureEditingFocus() {
  const active = document.activeElement;
  const host = active?.closest?.("[data-node-id]");
  if (!host) return null;
  const field = EDITABLE_FIELD_CLASSES.find((name) => active.classList?.contains(name));
  if (!field) return null;
  return {
    nodeId: host.dataset.nodeId,
    field,
    start: active.selectionStart,
    end: active.selectionEnd,
    scrollTop: active.scrollTop,
  };
}

function restoreEditingFocus(snapshot) {
  if (!snapshot?.nodeId) return;
  const host = els.nodeLayer.querySelector(`[data-node-id="${CSS.escape(snapshot.nodeId)}"]`);
  const field = host?.querySelector(`.${snapshot.field}`);
  if (!field) return;
  field.focus({ preventScroll: true });
  try {
    field.setSelectionRange(snapshot.start, snapshot.end);
  } catch (_) {
    // 某些输入类型不支持选区，忽略即可
  }
  field.scrollTop = snapshot.scrollTop;
}

function renderNodes() {
  // 生成完成等异步流程会触发重渲染。整层 replaceChildren 会把正在输入的
  // 焦点和光标一起清掉，所以先记下来再还原。
  const editing = captureEditingFocus();
  els.nodeLayer.replaceChildren();
  state.nodes.forEach((node) => {
    let element;
    if (node.type === "prompt") element = renderPromptNode(node);
    else if (node.type === "image") element = renderImageNode(node);
    else element = renderNoteNode(node);
    els.nodeLayer.appendChild(element);
  });
  els.empty.classList.toggle("hidden", state.nodes.length > 0);
  refreshIcons(els.nodeLayer);
  restoreEditingFocus(editing);
}

function connectionPath(x1, y1, x2, y2) {
  const curve = Math.max(70, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}`;
}

function nodePortPoint(node, role) {
  const element = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
  const width = element?.offsetWidth || node.width || 320;
  const height = element?.offsetHeight || node.height || 260;
  return {
    x: role === "out" ? node.x + width : node.x,
    y: node.y + height / 2,
  };
}

function fittedImageNodeWidth(width, height) {
  const sourceWidth = Number(width);
  const sourceHeight = Number(height);
  if (!Number.isFinite(sourceWidth) || !Number.isFinite(sourceHeight) || sourceWidth <= 0 || sourceHeight <= 0) {
    return 300;
  }
  const scale = Math.min(420 / sourceWidth, 360 / sourceHeight);
  return clamp(Math.round(sourceWidth * scale) + 20, 220, 440);
}

function cacheImageAsset(node) {
  if (!node?.assetId || !node.dataUrl) return;
  state.assetCache.delete(node.assetId);
  state.assetCache.set(node.assetId, {
    dataUrl: node.dataUrl,
    width: node.meta?.width || 0,
    height: node.meta?.height || 0,
  });
  while (state.assetCache.size > 48) {
    state.assetCache.delete(state.assetCache.keys().next().value);
  }
}

function hydrateImageAsset(node) {
  if (node?.type !== "image" || node.dataUrl || !node.assetId) return false;
  const cached = state.assetCache.get(node.assetId);
  if (!cached?.dataUrl) return false;
  node.dataUrl = cached.dataUrl;
  node.assetError = "";
  node.meta = {
    ...(node.meta || {}),
    width: node.meta?.width || cached.width,
    height: node.meta?.height || cached.height,
  };
  return true;
}

function normalizeLoadedNodeDimensions(node) {
  if (node.type === "prompt") {
    node.width = clamp(Number(node.width) || 320, 280, 640);
    node.height = clamp(Number(node.height) || 360, 300, 800);
    if (node.artist === "__none__") node.artist = "";
    node.artist = normalizedArtistSelection(node.artist);
  }
  if (node.type === "note") {
    node.width = clamp(Number(node.width) || 260, 220, 640);
    node.height = clamp(Number(node.height) || 232, 180, 800);
  }
  if (
    node.type === "image"
    && !node.meta?.userResized
    && (!node.width || [260, 300].includes(Math.round(node.width)))
  ) {
    node.width = fittedImageNodeWidth(node.meta?.width, node.meta?.height);
  }
  if (node.type === "image") hydrateImageAsset(node);
  return node;
}

function appendConnectionPath(x1, y1, x2, y2, className, edge = null) {
  const pathData = connectionPath(x1, y1, x2, y2);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", pathData);
  path.setAttribute("class", className);
  els.paths.appendChild(path);

  if (!edge) return;

  const source = findNode(edge.source);
  const target = findNode(edge.target);
  const label = `删除 ${source?.title || "来源节点"} 到 ${target?.title || "目标节点"} 的连线`;
  const remove = (event) => {
    event.preventDefault();
    event.stopPropagation();
    deleteConnection(edge.source, edge.target);
  };

  const hitPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  hitPath.setAttribute("d", pathData);
  hitPath.setAttribute("class", "link-hit");
  hitPath.setAttribute("aria-label", `${label}（双击）`);
  hitPath.addEventListener("pointerdown", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  hitPath.addEventListener("dblclick", remove);

  const control = document.createElement("button");
  control.type = "button";
  control.className = `link-delete${className.includes("active") ? " visible" : ""}`;
  control.style.left = `${(x1 + x2) / 2}px`;
  control.style.top = `${(y1 + y2) / 2}px`;
  control.title = label;
  control.setAttribute("aria-label", label);
  control.appendChild(icon("x"));

  const setHovered = (hovered) => {
    path.classList.toggle("hover", hovered);
    control.classList.toggle("visible", hovered || className.includes("active"));
  };
  hitPath.addEventListener("pointerenter", () => setHovered(true));
  hitPath.addEventListener("pointerleave", () => setHovered(false));
  control.addEventListener("pointerenter", () => setHovered(true));
  control.addEventListener("pointerleave", () => setHovered(false));
  control.addEventListener("pointerdown", (event) => {
    event.stopPropagation();
  });
  control.addEventListener("click", remove);
  control.addEventListener("dblclick", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });
  els.paths.appendChild(hitPath);
  els.linkControls.appendChild(control);
}

function renderConnections() {
  els.paths.replaceChildren();
  els.linkControls.replaceChildren();
  const selected = new Set(selectedNodeIds());
  state.connections.forEach((edge) => {
    const source = findNode(edge.source);
    const target = findNode(edge.target);
    if (!source || !target) return;
    const start = nodePortPoint(source, "out");
    const end = nodePortPoint(target, "in");
    appendConnectionPath(
      start.x,
      start.y,
      end.x,
      end.y,
      `link-path${selected.has(source.id) || selected.has(target.id) ? " active" : ""}`,
      edge,
    );
  });

  const drag = state.connectionDrag;
  if (!drag) {
    refreshIcons(els.linkControls);
    return;
  }
  const node = findNode(drag.nodeId);
  if (!node) return;
  const anchor = nodePortPoint(node, drag.role);
  const start = drag.role === "out" ? anchor : drag.point;
  const end = drag.role === "out" ? drag.point : anchor;
  appendConnectionPath(start.x, start.y, end.x, end.y, "link-path preview");
  refreshIcons(els.linkControls);
}

function connectionAllowed(sourceId, targetId) {
  const source = findNode(sourceId);
  const target = findNode(targetId);
  return !!source && !!target && (
    (source.type === "image" && target.type === "prompt")
    || (source.type === "prompt" && target.type === "image")
  );
}

function compatibleConnectionPort(element, nodeId, role) {
  const port = element?.closest?.(".port");
  if (!port || port.dataset.role === role || port.dataset.nodeId === nodeId) return null;
  const source = role === "out" ? nodeId : port.dataset.nodeId;
  const target = role === "out" ? port.dataset.nodeId : nodeId;
  if (!connectionAllowed(source, target)) return null;
  return port;
}

function attachConnectionPort(port, nodeId, role) {
  port.dataset.nodeId = nodeId;
  port.dataset.role = role;
  port.title = role === "out" ? "拖到输入端口以连接节点" : "拖到输出端口以连接节点";
  port.setAttribute("aria-label", port.title);

  port.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    selectNode(nodeId);
    state.connectionDrag = {
      nodeId,
      role,
      point: clientToWorld(event.clientX, event.clientY),
    };
    document.body.classList.add("connecting-nodes");
    renderConnections();

    const clearTarget = () => {
      document.querySelectorAll(".port.connection-target").forEach((item) => {
        item.classList.remove("connection-target");
      });
    };

    const move = (moveEvent) => {
      if (!state.connectionDrag) return;
      state.connectionDrag.point = clientToWorld(moveEvent.clientX, moveEvent.clientY);
      clearTarget();
      const target = compatibleConnectionPort(
        document.elementFromPoint(moveEvent.clientX, moveEvent.clientY),
        nodeId,
        role,
      );
      target?.classList.add("connection-target");
      scheduleConnectionRender();
    };

    const finish = (endEvent, cancelled = false) => {
      const target = cancelled
        ? null
        : compatibleConnectionPort(
            document.elementFromPoint(endEvent.clientX, endEvent.clientY),
            nodeId,
            role,
          );
      clearTarget();
      document.body.classList.remove("connecting-nodes");
      state.connectionDrag = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", cancel);

      if (target) {
        const source = role === "out" ? nodeId : target.dataset.nodeId;
        const destination = role === "out" ? target.dataset.nodeId : nodeId;
        const exists = state.connections.some(
          (edge) => edge.source === source && edge.target === destination,
        );
        if (!exists) {
          pushHistory();
          const isImageToPrompt =
            findNode(source)?.type === "image" && findNode(destination)?.type === "prompt";
          // A prompt can have only one image source; detect whether this link
          // is its first one before the filter below drops any previous edge.
          const isFirstImageLink =
            isImageToPrompt
            && !state.connections.some(
              (edge) => edge.target === destination && findNode(edge.source)?.type === "image",
            );
          if (findNode(destination)?.type === "prompt") {
            const destinationNode = findNode(destination);
            state.connections = state.connections.filter(
              (edge) => edge.target !== destination || findNode(edge.source)?.type !== "image",
            );
            // A prompt can have only one image source. Drop the previous
            // source-specific retag/translation cache when replacing it so a
            // later generation cannot display or persist stale tags.
            clearRetagCache(destinationNode);
            if (destinationNode) destinationNode.statusText = "";
          }
          state.connections.push({ source, target: destination });
          // 首次链接图片时把画幅向被反推图看齐（用户手动选过画幅则不动）
          if (isFirstImageLink) {
            alignPromptRatioToImage(findNode(destination), findNode(source));
          }
          scheduleSave();
          recordOperation("连接节点", `${findNode(source)?.title || source} → ${findNode(destination)?.title || destination}`);
          renderAll();
          if (isImageToPrompt) {
            void retagFromNode(destination, false, { automatic: true });
          }
          return;
        }
      }
      renderConnections();
    };

    const end = (endEvent) => finish(endEvent);
    const cancel = (cancelEvent) => finish(cancelEvent, true);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", cancel);
  });
}

function closestRatioPreset(width, height) {
  // 按对数差找长宽比最接近的预设，避免大尺寸图偏向极端比例
  const imageWidth = Number(width);
  const imageHeight = Number(height);
  if (!(imageWidth > 0) || !(imageHeight > 0)) return "";

  let bestValue = "";
  let bestDiff = Number.POSITIVE_INFINITY;
  for (const preset of Array.isArray(state.config.ratios) ? state.config.ratios : []) {
    const presetWidth = Number(preset?.width);
    const presetHeight = Number(preset?.height);
    if (!(presetWidth > 0) || !(presetHeight > 0)) continue;
    const diff = Math.abs(Math.log(imageWidth / imageHeight / (presetWidth / presetHeight)));
    if (diff < bestDiff) {
      bestDiff = diff;
      bestValue = String(preset.value || "");
    }
  }
  return bestValue;
}

function alignPromptRatioToImage(promptNode, imageNode) {
  // 首次链接图片时的画幅自动对齐：用户手动选过画幅（ratioManual）则不动
  if (!promptNode || !imageNode) return;
  if (promptNode.meta?.ratioManual) return;

  const preset = closestRatioPreset(imageNode.meta?.width, imageNode.meta?.height);
  if (!preset || preset === promptNode.ratio) return;

  promptNode.ratio = preset;
  scheduleSave();
  recordOperation("对齐画幅", `${promptNode.title || "提示词节点"} · ${preset}（跟随被反推图）`);
}

function renderViewport() {
  resetNativeCanvasScroll();
  const { x, y, scale } = state.viewport;
  els.world.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
}

let viewportProjectionFrame = 0;
let canvasProjectionFrame = 0;
let connectionRenderFrame = 0;

function scheduleViewportProjection() {
  if (viewportProjectionFrame) return;
  viewportProjectionFrame = window.requestAnimationFrame(() => {
    viewportProjectionFrame = 0;
    renderViewport();
  });
}

function scheduleCanvasProjection() {
  if (canvasProjectionFrame) return;
  canvasProjectionFrame = window.requestAnimationFrame(() => {
    canvasProjectionFrame = 0;
    renderConnections();
  });
}

function scheduleConnectionRender() {
  if (connectionRenderFrame) return;
  connectionRenderFrame = window.requestAnimationFrame(() => {
    connectionRenderFrame = 0;
    renderConnections();
  });
}

function renderAll() {
  // 中文/日文输入法组字期间重建 DOM 会直接把未上屏的内容打断，
  // 光标恢复也救不回来，所以整个渲染推迟到组字结束。
  if (state.composing) {
    state.renderPending = true;
    return;
  }
  state.renderPending = false;
  renderViewport();
  renderNodes();
  requestAnimationFrame(() => {
    renderConnections();
  });
  updateHistoryButtons();
  updateSelectionControls();
  renderDebugBar();
}

function setupCompositionGuard() {
  els.nodeLayer.addEventListener("compositionstart", () => {
    state.composing = true;
  });
  const finish = () => {
    if (!state.composing) return;
    state.composing = false;
    if (state.renderPending) renderAll();
  };
  els.nodeLayer.addEventListener("compositionend", finish);
  // 组字中途节点被移除时不会有 compositionend，兜一下底
  els.nodeLayer.addEventListener("focusout", finish);
}

function attachNodeDrag(handle, element, node) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button")) return;
    event.preventDefault();
    event.stopPropagation();

    if (event.ctrlKey || event.metaKey) {
      selectNode(node.id, { toggle: true });
      if (!isNodeSelected(node.id)) return;
    } else if (event.shiftKey) {
      selectNode(node.id, { additive: true });
    } else if (!isNodeSelected(node.id)) {
      selectNode(node.id);
    }
    bringNodeToFront(node.id, element);

    const group = selectedNodeIds().map((id) => {
      const selectedNode = findNode(id);
      return {
        node: selectedNode,
        x: selectedNode.x,
        y: selectedNode.y,
        element: document.querySelector(`[data-node-id="${CSS.escape(id)}"]`),
      };
    });
    const start = { x: event.clientX, y: event.clientY };
    let moved = false;

    const move = (moveEvent) => {
      const dx = (moveEvent.clientX - start.x) / state.viewport.scale;
      const dy = (moveEvent.clientY - start.y) / state.viewport.scale;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      if (!moved) {
        moved = true;
        pushHistory();
        document.body.classList.add("dragging-nodes");
        group.forEach((item) => item.element?.classList.add("dragging"));
      }
      group.forEach((item) => {
        item.node.x = item.x + dx;
        item.node.y = item.y + dy;
        if (item.element) {
          item.element.style.left = `${item.node.x}px`;
          item.element.style.top = `${item.node.y}px`;
        }
      });
      scheduleCanvasProjection();
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      document.body.classList.remove("dragging-nodes");
      group.forEach((item) => item.element?.classList.remove("dragging"));
      if (moved) {
        scheduleSave();
        recordOperation(
          "移动节点",
          group.length > 1 ? `${group.length} 个节点` : node.title || "未命名节点",
        );
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  });
}

function attachNodeResize(handle, element, node) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    selectNode(node.id);
    bringNodeToFront(node.id, element);
    const start = {
      x: event.clientX,
      y: event.clientY,
      width: node.width || element.offsetWidth || (node.type === "prompt" ? 320 : 260),
      height: node.height || element.offsetHeight || (node.type === "prompt" ? 360 : 232),
    };
    let moved = false;
    const move = (moveEvent) => {
      const dx = (moveEvent.clientX - start.x) / state.viewport.scale;
      const dy = (moveEvent.clientY - start.y) / state.viewport.scale;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      if (!moved) {
        moved = true;
        pushHistory();
      }
      const promptMinimumHeight = window.matchMedia("(max-width: 620px)").matches ? 450 : 300;
      node.width = clamp(Math.round(start.width + dx), node.type === "prompt" ? 280 : 220, 640);
      node.height = clamp(
        Math.round(start.height + dy),
        node.type === "prompt" ? promptMinimumHeight : 180,
        800,
      );
      element.style.width = `${node.width}px`;
      element.style.height = `${node.height}px`;
      scheduleCanvasProjection();
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      if (moved) {
        scheduleSave();
        recordOperation(
          "调整节点大小",
          `${node.title || "未命名节点"} · ${Math.round(node.width)}×${Math.round(node.height)}`,
        );
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  });
}

function attachImageNodeResize(handle, element, node) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    selectNode(node.id);
    bringNodeToFront(node.id, element);
    const start = {
      x: event.clientX,
      y: event.clientY,
      width: node.width || element.offsetWidth || 260,
      height: element.offsetHeight || 300,
    };
    let moved = false;
    const move = (moveEvent) => {
      const dx = (moveEvent.clientX - start.x) / state.viewport.scale;
      const dy = (moveEvent.clientY - start.y) / state.viewport.scale;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      if (!moved) {
        moved = true;
        pushHistory();
      }
      const diagonalDelta = Math.abs(dx) >= Math.abs(dy)
        ? dx
        : dy * (start.width / Math.max(1, start.height));
      node.width = clamp(Math.round(start.width + diagonalDelta), 180, 640);
      node.meta = { ...(node.meta || {}), userResized: true };
      element.style.width = `${node.width}px`;
      scheduleCanvasProjection();
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      if (moved) {
        scheduleSave();
        recordOperation("调整图片大小", `${node.title || "图片"} · 宽 ${Math.round(node.width)}px`);
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  });
}

function clientToWorld(clientX, clientY) {
  const rect = els.viewport.getBoundingClientRect();
  return {
    x: (clientX - rect.left - state.viewport.x) / state.viewport.scale,
    y: (clientY - rect.top - state.viewport.y) / state.viewport.scale,
  };
}

function worldCenter() {
  const rect = els.viewport.getBoundingClientRect();
  return clientToWorld(rect.left + rect.width / 2, rect.top + rect.height / 2);
}

function focusCanvasSurface() {
  if (document.activeElement === els.viewport) return;
  els.viewport.focus({ preventScroll: true });
}

function nodeRect(node) {
  const element = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
  return {
    x: node.x,
    y: node.y,
    width: node.width || 320,
    height: node.height || element?.offsetHeight || estimatedImageNodeHeight(
      node.width,
      node.meta?.width,
      node.meta?.height,
    ),
  };
}

function estimatedImageNodeHeight(nodeWidth, sourceWidth, sourceHeight) {
  const width = Number(nodeWidth) || 300;
  const imageWidth = Number(sourceWidth);
  const imageHeight = Number(sourceHeight);
  if (!Number.isFinite(imageWidth) || !Number.isFinite(imageHeight) || imageWidth <= 0 || imageHeight <= 0) {
    return 280;
  }
  const previewHeight = Math.min(720, Math.max(1, width - 20) * imageHeight / imageWidth);
  return Math.ceil(previewHeight + 96);
}

function rectanglesOverlap(first, second, gap = 36) {
  return first.x < second.x + second.width + gap
    && first.x + first.width + gap > second.x
    && first.y < second.y + second.height + gap
    && first.y + first.height + gap > second.y;
}

function findOpenGeneratedPosition(sourceNode, width, height) {
  const horizontalGap = 64;
  const candidate = {
    x: sourceNode.x + (sourceNode.width || 320) + horizontalGap,
    y: sourceNode.y,
    width,
    height,
  };
  const occupied = state.nodes
    .filter((node) => node.id !== sourceNode.id)
    .map(nodeRect);
  for (let attempt = 0; attempt < occupied.length + 1; attempt += 1) {
    const collisions = occupied.filter((rect) => rectanglesOverlap(candidate, rect));
    if (!collisions.length) return { x: candidate.x, y: candidate.y };
    // The first result belongs beside its prompt. When that lane is occupied,
    // continue to the right instead of sending the image far down the canvas.
    candidate.x = Math.max(
      candidate.x + horizontalGap,
      ...collisions.map((rect) => rect.x + rect.width + horizontalGap),
    );
  }
  return { x: candidate.x, y: candidate.y };
}

function findNextGeneratedPosition(sourceNode, width, height) {
  const latestEdge = [...state.connections].reverse().find((edge) => (
    edge.source === sourceNode.id && findNode(edge.target)?.type === "image"
  ));
  const latestImage = latestEdge ? findNode(latestEdge.target) : null;
  if (!latestImage) return findOpenGeneratedPosition(sourceNode, width, height);
  return {
    x: latestImage.x + 56,
    y: latestImage.y - 36,
  };
}

function finishBoxSelection(
  startWorld,
  endEvent,
  {
    startClientX = endEvent.clientX,
    additive = false,
    toggle = false,
    baseSelection = [],
  } = {},
) {
  const endWorld = clientToWorld(endEvent.clientX, endEvent.clientY);
  const minX = Math.min(startWorld.x, endWorld.x);
  const minY = Math.min(startWorld.y, endWorld.y);
  const maxX = Math.max(startWorld.x, endWorld.x);
  const maxY = Math.max(startWorld.y, endWorld.y);
  // AutoCAD-style window selection: left-to-right selects nodes fully inside
  // the rectangle; right-to-left selects every node the rectangle crosses.
  const crossing = endEvent.clientX < startClientX;
  const ids = state.nodes.filter((node) => {
    const rect = nodeRect(node);
    if (crossing) {
      return rect.x < maxX
        && rect.x + rect.width > minX
        && rect.y < maxY
        && rect.y + rect.height > minY;
    }
    return rect.x >= minX
      && rect.x + rect.width <= maxX
      && rect.y >= minY
      && rect.y + rect.height <= maxY;
  }).map((node) => node.id);
  const base = new Set(baseSelection.filter((id) => !!findNode(id)));
  if (toggle) {
    ids.forEach((id) => {
      if (base.has(id)) base.delete(id);
      else base.add(id);
    });
  } else if (additive) {
    ids.forEach((id) => base.add(id));
  } else {
    base.clear();
    ids.forEach((id) => base.add(id));
  }
  const selected = [...base];
  const primary = ids[ids.length - 1] || selected[selected.length - 1] || "";
  setSelection(selected, primary);
  renderAll();
}

function resetNativeCanvasScroll() {
  if (!els.viewport.scrollLeft && !els.viewport.scrollTop) return;
  els.viewport.scrollLeft = 0;
  els.viewport.scrollTop = 0;
}

// Chromium may still attempt focus-driven scrolling for an ``overflow: clip``
// element in older embedded builds. The infinite world is navigated only by
// state.viewport, so any native board scroll is always accidental.
els.viewport.addEventListener("scroll", resetNativeCanvasScroll, { passive: true });

function arrangeSelectedNodes() {
  const nodes = selectedNodeIds().map(findNode).filter(Boolean);
  if (nodes.length < 2) return;
  pushHistory();
  const items = nodes.map((node) => ({ node, rect: nodeRect(node) }))
    .sort((a, b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x);
  const startX = Math.min(...items.map((item) => item.rect.x));
  const startY = Math.min(...items.map((item) => item.rect.y));
  const columns = Math.ceil(Math.sqrt(items.length));
  const cellWidth = Math.max(...items.map((item) => item.rect.width)) + 56;
  const cellHeight = Math.max(...items.map((item) => item.rect.height)) + 56;
  items.forEach((item, index) => {
    item.node.x = startX + (index % columns) * cellWidth;
    item.node.y = startY + Math.floor(index / columns) * cellHeight;
  });
  renderAll();
  scheduleSave();
  toast(`已整理 ${items.length} 个节点`);
  recordOperation("整理选中", `${items.length} 个节点`);
}

function setZoom(nextScale, clientX, clientY) {
  const rect = els.viewport.getBoundingClientRect();
  const anchorX = clientX ?? rect.left + rect.width / 2;
  const anchorY = clientY ?? rect.top + rect.height / 2;
  const world = clientToWorld(anchorX, anchorY);
  const scale = clamp(nextScale, 0.1, 4);
  state.viewport.scale = scale;
  state.viewport.x = anchorX - rect.left - world.x * scale;
  state.viewport.y = anchorY - rect.top - world.y * scale;
  renderViewport();
  scheduleSave(800);
  window.clearTimeout(state.viewportRecordTimer);
  state.viewportRecordTimer = window.setTimeout(() => {
    state.viewportRecordTimer = null;
    recordOperation("缩放画布", `${Math.round(scale * 100)}%`);
  }, 420);
}

function fitView() {
  if (!state.nodes.length) {
    pushHistory();
    state.viewport = { x: 160, y: 120, scale: 1 };
    renderAll();
    scheduleSave();
    recordOperation("适配视图", "画布恢复默认视图");
    return;
  }
  pushHistory();
  const rect = els.viewport.getBoundingClientRect();
  const minX = Math.min(...state.nodes.map((node) => node.x));
  const minY = Math.min(...state.nodes.map((node) => node.y));
  const maxX = Math.max(...state.nodes.map((node) => node.x + (node.width || 320)));
  const maxY = Math.max(...state.nodes.map((node) => {
    const element = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
    return node.y + (element?.offsetHeight || 280);
  }));
  const contentWidth = Math.max(1, maxX - minX);
  const contentHeight = Math.max(1, maxY - minY);
  const scale = clamp(Math.min((rect.width - 170) / contentWidth, (rect.height - 120) / contentHeight), 0.15, 1.2);
  state.viewport.scale = scale;
  state.viewport.x = (rect.width - contentWidth * scale) / 2 - minX * scale;
  state.viewport.y = (rect.height - contentHeight * scale) / 2 - minY * scale;
  renderAll();
  scheduleSave();
  recordOperation("适配视图", `已显示 ${state.nodes.length} 个节点`);
}

async function generateFromNode(id, {
  retagged = false,
  retagPrompt = "",
} = {}) {
  const node = findNode(id);
  if (!node || node.status) return;
  const basePrompt = node.prompt?.trim() || "";
  const workingPrompt = basePrompt;
  const requestRetagPrompt = retagged
    ? String(retagPrompt || node.meta?.retagPrompt || "").trim()
    : "";
  if (!workingPrompt && !requestRetagPrompt) {
    node.error = "请输入提示词";
    recordOperation("生成失败", "提示词为空", "warning");
    renderAll();
    return;
  }
  const translationSource = retagged ? basePrompt : workingPrompt;
  const canReuseTranslation = /[\u4e00-\u9fff]/.test(translationSource)
    && node.meta?.translationSource === translationSource
    && !!node.meta?.translationResult;
  node.status = "generating";
  node.error = "";
  node.statusText = canReuseTranslation
    ? "正在复用英文 tags 并生成图片…"
    : /[\u4e00-\u9fff]/.test(workingPrompt)
      ? "正在翻译并生成图片…"
      : "正在生成图片…";
  recordOperation(retagged ? "反推并生成" : "生成图片", node.title || "提示词节点");
  renderAll();
  try {
    const retagLayerCategories = retagged
      ? retagLayerCategoryLists(node)
      : { preserve: [], drop: [] };
    const result = await bridge.apiPost("canvas/generate", {
      prompt: workingPrompt,
      retagPrompt: requestRetagPrompt,
      retagCharacter: retagged ? String(node.meta?.retagCharacter || "").trim() : "",
      retagSeries: retagged ? String(node.meta?.retagSeries || "").trim() : "",
      ratio: node.ratio,
      artist: node.artist,
      retagPreserveCategories: retagLayerCategories.preserve,
      retagDropCategories: retagLayerCategories.drop,
      raw: !!node.raw,
      translationSource,
      cachedTranslationSource: node.meta?.translationSource || "",
      cachedTranslation: node.meta?.translationResult || "",
      cachedTranslationCharacter: node.meta?.translationCharacter || "",
      cachedTranslationSeries: node.meta?.translationSeries || "",
      debug: debugModeEnabled(),
      retagCharPrompts: retagged ? normalizeCharPromptEntries(node.meta?.retagCharPrompts) : [],
      retagUseCoords: retagged ? !!node.meta?.retagUseCoords : false,
      // 命中过内嵌参数时沿用原图采样参数；缺省时后端用插件配置默认值
      steps: node.meta?.retagSteps || undefined,
      scale: node.meta?.retagScale || undefined,
      cfgRescale: node.meta?.retagCfgRescale || undefined,
      noiseSchedule: node.meta?.retagNoiseSchedule || undefined,
      // 原图自带种子时沿用它，配合原图 prompt 才能真正还原这张图
      // A seed collected from an image belongs to the retag flow.  If the
      // source connection was removed, a plain prompt generation must not
      // silently inherit that old seed.
      seed: retagged ? reusableRetagSeed(node) : undefined,
    });
    const assets = Array.isArray(result?.assets) ? result.assets : [];
    if (!assets.length) throw new Error("服务未返回图片");
    pushHistory();
    node.meta = {
      ...(node.meta || {}),
      translatedPrompt: result.meta?.translatedPrompt || requestRetagPrompt || "",
      translationSource: result.meta?.translationSource || "",
      translationResult: result.meta?.translationResult || "",
      translationCharacter: result.meta?.translationCharacter || "",
      translationSeries: result.meta?.translationSeries || "",
    };
    recordRunDebug(node, "generate", result.meta?.debug);
    const createdIds = [];
    assets.forEach((asset) => {
      const sourceWidth = asset.width || result.meta?.width;
      const sourceHeight = asset.height || result.meta?.height;
      const imageNodeWidth = fittedImageNodeWidth(sourceWidth, sourceHeight);
      const position = findNextGeneratedPosition(
        node,
        imageNodeWidth,
        estimatedImageNodeHeight(imageNodeWidth, sourceWidth, sourceHeight),
      );
      const imageNode = {
        id: uid("image"),
        type: "image",
        x: position.x,
        y: position.y,
        width: imageNodeWidth,
        title: `${retagged ? "反推图片" : "生成结果"} ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
        assetId: asset.id,
        dataUrl: asset.dataUrl,
        createdAt: new Date().toISOString(),
        meta: {
          prompt: node.prompt?.trim() || node.title || (retagged ? "反推图片" : "生成结果"),
          tags: result.meta?.translatedPrompt || workingPrompt,
          tagTranslations: normalizeRetagTagTranslations(node.meta?.retagTagTranslations),
          artist: result.meta?.artist || "",
          ratio: result.meta?.ratio || node.ratio,
          retagged,
          width: sourceWidth,
          height: sourceHeight,
          finalPrompt: result.meta?.finalPrompt || "",
          seed: normalizeNaiSeed(result.meta?.seed),
          steps: result.meta?.steps || 0,
          scale: result.meta?.scale || 0,
        },
      };
      state.nodes.push(imageNode);
      state.connections.push({ source: node.id, target: imageNode.id });
      createdIds.push(imageNode.id);
    });
    setSelection(createdIds, createdIds[createdIds.length - 1]);
    node.statusText = retagged
      ? `反推完成 · 已合并提示词并生成 ${assets.length} 张图片`
      : `已生成 ${assets.length} 张图片`;
    toast("生成完成");
    recordOperation("生成完成", `已生成 ${assets.length} 张图片`, "success");
    renderAll();
    scheduleSave();
  } catch (error) {
    node.error = error.message || "生成失败";
    recordOperation("生成失败", node.error, "error");
    toast(node.error, "error");
    renderAll();
  } finally {
    node.status = "";
    renderAll();
  }
}

function sourceImageForPrompt(promptId) {
  const edge = state.connections.find((item) => {
    if (item.target !== promptId) return false;
    return findNode(item.source)?.type === "image";
  });
  return edge ? findNode(edge.source) : null;
}

function beginRetagRequest(node, sourceImage) {
  const token = ++state.retagRequestSequence;
  state.retagRequests.set(node.id, {
    token,
    assetId: String(sourceImage?.assetId || ""),
  });
  return token;
}

function isLatestRetagRequest(node, token) {
  return findNode(node?.id) === node
    && state.retagRequests.get(node.id)?.token === token;
}

function retagRequestStillMatchesSource(node, token, assetId) {
  return isLatestRetagRequest(node, token)
    && String(sourceImageForPrompt(node.id)?.assetId || "") === String(assetId || "");
}

function clearRetagCache(node) {
  if (state.lastDebugNodeId === node?.id) state.lastDebugNodeId = "";
  const {
    retagAssetId: _retagAssetId,
    retagRatio: _retagRatio,
    retagBasePrompt: _retagBasePrompt,
    retagPrompt: _retagPrompt,
    retagCharacter: _retagCharacter,
    retagSeries: _retagSeries,
    retagSeed: _retagSeed,
    retagSeedPrompt: _retagSeedPrompt,
    retagSeedRatio: _retagSeedRatio,
    retagSeedArtist: _retagSeedArtist,
    retagSeedRaw: _retagSeedRaw,
    retagFromMetadata: _retagFromMetadata,
    retagFromCanvasCache: _retagFromCanvasCache,
    retagTagGroups: _retagTagGroups,
    retagTagTranslations: _retagTagTranslations,
    retagLayerModes: _retagLayerModes,
    retagLayerExpanded: _retagLayerExpanded,
    retagCharPrompts: _retagCharPrompts,
    retagUseCoords: _retagUseCoords,
    retagSteps: _retagSteps,
    retagScale: _retagScale,
    retagCfgRescale: _retagCfgRescale,
    retagNoiseSchedule: _retagNoiseSchedule,
    translatedPrompt: _translatedPrompt,
    translationSource: _translationSource,
    translationResult: _translationResult,
    translationCharacter: _translationCharacter,
    translationSeries: _translationSeries,
    debug: _debug,
    ...meta
  } = node.meta || {};
  node.meta = meta;
}

function clearTranslationCache(node) {
  if (!node?.meta) return;
  const {
    translatedPrompt: _translatedPrompt,
    translationSource: _translationSource,
    translationResult: _translationResult,
    translationCharacter: _translationCharacter,
    translationSeries: _translationSeries,
    ...meta
  } = node.meta;
  node.meta = meta;
}

function clearRetagSeed(node) {
  if (!node?.meta) return;
  const {
    retagSeed: _retagSeed,
    retagSeedPrompt: _retagSeedPrompt,
    retagSeedRatio: _retagSeedRatio,
    retagSeedArtist: _retagSeedArtist,
    retagSeedRaw: _retagSeedRaw,
    ...meta
  } = node.meta;
  node.meta = meta;
}

function clearDebugTrace(node) {
  if (!node?.meta?.debug) return;
  if (state.lastDebugNodeId === node.id) state.lastDebugNodeId = "";
  const { debug: _debug, ...meta } = node.meta;
  node.meta = meta;
  if (debugModeEnabled()) renderDebugBar();
}

function normalizeNaiSeed(value) {
  if (value === null || value === undefined || typeof value === "boolean") return 0;
  if (typeof value === "string" && !/^\d+$/.test(value.trim())) return 0;
  const seed = Number(value);
  return Number.isInteger(seed) && seed >= 1 && seed <= 4_294_967_295 ? seed : 0;
}

function boundedMetaNumber(value, min, max) {
  const number = Number(value);
  return Number.isFinite(number) && number >= min && number <= max ? number : 0;
}

function sourceImageSeed(node) {
  return normalizeNaiSeed(node?.meta?.seed) || normalizeNaiSeed(node?.meta?.retagSeed);
}

function sourceImageRetagPrompt(node) {
  const meta = node?.meta || {};
  // A filename stored in ``meta.prompt`` is not a reliable NovelAI prompt.
  // Only use fields that are explicitly populated with generation tags; if
  // none exist, the backend can still inspect embedded PNG metadata or fall
  // back to the vision provider instead of bypassing it with a filename.  A
  // seed is optional here: re-encoded PNGs may retain the prompt but lose the
  // seed, and the prompt alone is still enough to skip a redundant retag call.
  return String(meta.tags || meta.finalPrompt || meta.retagPrompt || "").trim();
}

function reusableRetagSeed(node) {
  const meta = node?.meta || {};
  const seed = normalizeNaiSeed(meta.retagSeed);
  if (!seed) return undefined;

  // The seed belongs to the source image, not to the handwritten overlay.
  // Keep it when the user replaces a character, outfit, pose, ratio, or
  // artist preset; NovelAI uses the same initial noise to preserve a useful
  // composition direction while still allowing the prompt to change.
  return seed;
}

function cachedRetagResult(node, sourceImage, basePrompt) {
  if (!node || !sourceImage?.assetId) return null;
  const meta = node.meta || {};
  const tagGroups = normalizeRetagTagGroups(meta.retagTagGroups);
  if (
    !meta.retagPrompt
    || meta.retagAssetId !== sourceImage.assetId
    || !Object.keys(tagGroups).length
  ) return null;
  const cachedSeed = normalizeNaiSeed(meta.retagSeed);
  // A legacy workspace may have cached tags but no seed even though the
  // source image now carries one (for example after restoring it from the
  // library).  Refresh once through the backend so the deterministic path can
  // recover that seed instead of silently generating with a random one.
  if (!cachedSeed && sourceImageSeed(sourceImage) && sourceImageRetagPrompt(sourceImage)) {
    return null;
  }
  // Retagging describes the source image, not the handwritten overlay.  A
  // prompt edit must therefore keep this result reusable instead of sending
  // the same image to the tagger again.  ``basePrompt`` remains part of the
  // seed fingerprint and is refreshed when the cached result is applied.
  return {
    prompt: String(meta.retagPrompt).trim(),
    ratio: String(meta.retagRatio || "").trim(),
    character: String(meta.retagCharacter || "").trim(),
    series: String(meta.retagSeries || "").trim(),
    seed: cachedSeed,
    fromMetadata: !!meta.retagFromMetadata,
    fromCanvasCache: !!meta.retagFromCanvasCache,
    tagGroups,
    tagTranslations: normalizeRetagTagTranslations(meta.retagTagTranslations),
    charPrompts: normalizeCharPromptEntries(meta.retagCharPrompts),
    charUseCoords: !!meta.retagUseCoords,
    steps: boundedMetaNumber(meta.retagSteps, 1, 200),
    scale: boundedMetaNumber(meta.retagScale, 0.1, 100),
    cfgRescale: boundedMetaNumber(meta.retagCfgRescale, 0, 100),
    noiseSchedule: String(meta.retagNoiseSchedule || "").trim(),
  };
}

function runPromptNode(id) {
  // 每次手动运行都从空白开始记，否则上一轮的反推流水会跟这一轮的生图混在一起
  const node = findNode(id);
  clearDebugTrace(node);
  return sourceImageForPrompt(id)
    ? retagFromNode(id, true)
    : generateFromNode(id);
}

function recordRunDebug(node, stage, payload) {
  if (!debugModeEnabled() || !payload || typeof payload !== "object" || Array.isArray(payload)) return;
  node.meta = {
    ...(node.meta || {}),
    debug: { ...(node.meta?.debug || {}), [stage]: payload || null },
  };
  state.lastDebugNodeId = node.id;
}

async function retagFromNode(
  id,
  generateAfter = false,
  { automatic = false } = {},
) {
  const node = findNode(id);
  if (!node || (node.status && !(automatic && node.status === "retagging"))) return false;

  const sourceImage = sourceImageForPrompt(id);
  if (!sourceImage?.assetId) {
    node.error = "请先把原图连接到提示词节点左侧";
    recordOperation("反推失败", node.error, "warning");
    renderAll();
    return false;
  }
  const sourceAssetId = String(sourceImage.assetId);
  const requestToken = beginRetagRequest(node, sourceImage);

  const basePrompt = node.prompt?.trim() || "";
  const cachedRetag = cachedRetagResult(node, sourceImage, basePrompt);
  // Do not gate this action on the vision-provider flag. A PNG generated by
  // NovelAI can be retagged from its embedded prompt/seed and only needs the
  // tags-site lookup; the backend will still return a clear configuration
  // error for ordinary images when no vision provider is available.

  node.status = "retagging";
  node.error = "";
  node.statusText = cachedRetag
    ? "正在复用已保存的反推结果…"
    : "正在反推原图提示词…";
  recordOperation("反推原图", cachedRetag ? "复用已保存结果" : "提取原图 tags");
  renderAll();

  let succeeded = false;
  try {
    const sourceSeed = sourceImageSeed(sourceImage);
    const result = cachedRetag || await bridge.apiPost("canvas/retag", {
      assetId: sourceImage.assetId,
      debug: debugModeEnabled(),
      seed: sourceSeed || undefined,
      sourcePrompt: sourceImageRetagPrompt(sourceImage),
    });
    if (!retagRequestStillMatchesSource(node, requestToken, sourceAssetId)) return false;
    const retagPrompt = String(result?.prompt || "").trim();
    if (!retagPrompt) throw new Error("反推服务未返回提示词");
    const recoveredSeed = normalizeNaiSeed(result?.seed);

    pushHistory();
    node.meta = {
      ...(node.meta || {}),
      retagBasePrompt: basePrompt,
      retagPrompt,
      retagCharacter: String(result?.character || "").trim(),
      retagSeries: String(result?.series || "").trim(),
      retagAssetId: sourceImage.assetId,
      retagRatio: result.ratio || "",
      retagSeed: recoveredSeed,
      retagSeedPrompt: basePrompt,
      retagSeedRatio: node.ratio || "",
      retagSeedArtist: node.artist || "",
      retagSeedRaw: !!node.raw,
      retagFromMetadata: !!result.fromMetadata,
      retagFromCanvasCache: !!result.fromCanvasCache,
      retagTagGroups: normalizeRetagTagGroups(result?.tagGroups),
      retagTagTranslations: normalizeRetagTagTranslations(result?.tagTranslations),
      // V4+ 内嵌参数里的多角色提示词，结构化透传给生图网关
      retagCharPrompts: normalizeCharPromptEntries(result?.charPrompts),
      retagUseCoords: !!result?.charUseCoords,
      // 命中内嵌参数时沿用原图的采样参数（steps/scale/cfg_rescale/噪声计划）
      retagSteps: result.fromMetadata
        ? boundedMetaNumber(result?.steps, 1, 200)
        : 0,
      retagScale: result.fromMetadata
        ? boundedMetaNumber(result?.scale, 0.1, 100)
        : 0,
      retagCfgRescale: result.fromMetadata
        ? boundedMetaNumber(result?.cfgRescale, 0, 100)
        : 0,
      retagNoiseSchedule: result.fromMetadata
        ? String(result?.noiseSchedule || "").trim()
        : "",
      retagLayerExpanded: node.meta?.retagLayerExpanded === true,
      translatedPrompt: retagPrompt,
    };
    // Keep the source image self-describing after the first retag.  This is
    // important for uploaded/re-encoded images whose PNG metadata is absent:
    // saving that image to the library and placing it back later must still
    // carry the recovered seed and canonical tags.
    sourceImage.meta = {
      ...(sourceImage.meta || {}),
      ...(recoveredSeed ? { seed: recoveredSeed } : {}),
      // The backend result has already removed artist/quality controls and is
      // authoritative over legacy node metadata.  Keeping an older non-empty
      // value here would make the same dirty tags reappear after a library
      // round trip.
      tags: retagPrompt,
      tagTranslations: normalizeRetagTagTranslations(result?.tagTranslations),
      ratio: result?.ratio || sourceImage.meta?.ratio || "",
    };
    recordRunDebug(node, "retag", result.debug);
    node.statusText = result.fromMetadata
      ? `已读取原图内嵌参数 · 种子 ${recoveredSeed || "未知"}`
      : result.fromCanvasCache
        ? `已复用画布保存参数 · 种子 ${recoveredSeed || "未知"}`
        : "已提取原图 tags，准备生成";
    toast(
      result.fromMetadata
        ? "已读取原图内嵌的 NovelAI 参数"
        : result.fromCanvasCache
          ? "已复用画布保存的 NovelAI 参数"
          : (cachedRetag ? "已复用反推结果" : "原图 tags 已提取"),
    );
    scheduleSave();
    succeeded = true;
    recordOperation("反推完成", result.fromMetadata ? "读取内嵌参数" : "提取 tags 完成", "success");
  } catch (error) {
    if (!retagRequestStillMatchesSource(node, requestToken, sourceAssetId)) return false;
    const message = error.message || "图片反推失败";
    if (automatic) {
      node.error = "";
      node.statusText = "";
      recordOperation("自动反推跳过", message, "warning");
    } else {
      node.error = message;
      recordOperation("反推失败", node.error, "error");
      toast(node.error, "error");
    }
  } finally {
    if (isLatestRetagRequest(node, requestToken)) {
      state.retagRequests.delete(node.id);
      if (node.status === "retagging") node.status = "";
      renderAll();
    }
  }
  if (succeeded && generateAfter) {
    await generateFromNode(id, {
      retagged: true,
      retagPrompt: node.meta?.retagPrompt || "",
    });
  }
  return succeeded;
}

async function ensureAssetLoaded(node) {
  if (hydrateImageAsset(node)) return;
  if (!node.assetId || node.dataUrl || node.assetLoading || node.assetError) return;
  node.assetLoading = true;
  let dimensionsChanged = false;
  try {
    const result = await bridge.apiGet("canvas/asset", { id: node.assetId });
    node.dataUrl = result.dataUrl;
    node.meta = {
      ...(node.meta || {}),
      width: node.meta?.width || result.width,
      height: node.meta?.height || result.height,
    };
    cacheImageAsset(node);
    if (
      !node.meta?.userResized
      && (!node.width || [260, 300].includes(Math.round(node.width)))
    ) {
      node.width = fittedImageNodeWidth(node.meta.width, node.meta.height);
      dimensionsChanged = true;
    }
  } catch (error) {
    node.assetError = error.message || "图片读取失败";
  } finally {
    node.assetLoading = false;
    const current = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
    if (current) {
      const replacement = renderImageNode(node);
      current.replaceWith(replacement);
      requestAnimationFrame(() => {
        renderConnections();
      });
    }
    if (dimensionsChanged) scheduleSave(800);
  }
}

function canvasGenerationActive() {
  return state.nodes.some((item) => item.status === "generating" || item.status === "retagging");
}

async function downloadImage(node) {
  if (canvasGenerationActive()) {
    toast("生图或反推期间暂不可下载", "error");
    return;
  }
  if (!node.assetId) {
    toast("图片仍在读取，请稍后重试", "error");
    return;
  }
  try {
    const mime = /^data:image\/([^;,]+)/i.exec(node.dataUrl || "")?.[1]?.toLowerCase() || "png";
    const extension = mime === "jpeg" ? "jpg" : mime;
    await bridge.download(
      "canvas/asset/download",
      { id: node.assetId },
      `bestnai-${node.assetId}.${extension}`,
    );
    recordOperation("下载图片", node.title || node.assetId, "success");
  } catch (error) {
    recordOperation("下载图片失败", error.message || "图片下载失败", "error");
    toast(error.message || "图片下载失败", "error");
  }
}

function preferredImageViewerLayout(width, height) {
  const imageWidth = Number(width) || 0;
  const imageHeight = Number(height) || 0;
  if (!imageWidth || !imageHeight || window.matchMedia("(max-width: 760px)").matches) return "bottom";
  const aspect = imageWidth / imageHeight;
  if (aspect < .92) return "side";
  if (aspect > 1.12) return "bottom";
  return window.innerWidth >= 1100 ? "side" : "bottom";
}

function applyImageViewerLayout(width, height) {
  clearImageViewerBottomLayoutLock(true);
  const imageWidth = Number(width) || els.imageViewerImage.naturalWidth || 0;
  const imageHeight = Number(height) || els.imageViewerImage.naturalHeight || 0;
  if (imageWidth && imageHeight) {
    state.viewerImageDimensions = { width: imageWidth, height: imageHeight };
    els.imageViewer.style.setProperty("--viewer-image-aspect", `${imageWidth} / ${imageHeight}`);
  } else {
    els.imageViewer.style.removeProperty("--viewer-image-aspect");
  }
  const layout = preferredImageViewerLayout(imageWidth, imageHeight);
  els.imageViewer.classList.toggle("layout-side", layout === "side");
  els.imageViewer.classList.toggle("layout-bottom", layout === "bottom");
  els.imageViewer.dataset.layout = layout;
  scheduleImageViewerFrameSync();
}

function clearImageViewerBottomLayoutLock(resetGeometry = false) {
  state.viewerBottomLayoutLock = null;
  els.imageViewerDetails.style.removeProperty("height");
  els.imageViewerDetails.style.removeProperty("min-height");
  els.imageViewerDetails.style.removeProperty("max-height");
  if (!resetGeometry) return;
  els.imageViewerImageFrame?.style.removeProperty("width");
  els.imageViewerImageFrame?.style.removeProperty("height");
  els.imageViewerDetails.style.removeProperty("width");
  els.imageViewerDetails.style.removeProperty("max-width");
}

function applyImageViewerBottomLayoutLock() {
  const lock = state.viewerBottomLayoutLock;
  const frame = els.imageViewerImageFrame;
  if (!lock || !frame) return false;
  frame.style.width = `${lock.frameWidth}px`;
  frame.style.height = `${lock.frameHeight}px`;
  els.imageViewerDetails.style.width = `${lock.detailsWidth}px`;
  els.imageViewerDetails.style.maxWidth = `${lock.detailsWidth}px`;
  els.imageViewerDetails.style.height = `${lock.detailsHeight}px`;
  els.imageViewerDetails.style.minHeight = `${lock.detailsHeight}px`;
  els.imageViewerDetails.style.maxHeight = `${lock.detailsHeight}px`;
  return true;
}

function lockImageViewerBottomLayout() {
  if (els.imageViewer.hidden || !els.imageViewer.classList.contains("layout-bottom")) return;
  const frame = els.imageViewerImageFrame;
  if (!frame) return;
  const frameRect = frame.getBoundingClientRect();
  const detailsRect = els.imageViewerDetails.getBoundingClientRect();
  if (!frameRect.width || !frameRect.height || !detailsRect.width || !detailsRect.height) return;
  state.viewerBottomLayoutLock = {
    frameWidth: frameRect.width,
    frameHeight: frameRect.height,
    detailsWidth: detailsRect.width,
    detailsHeight: detailsRect.height,
  };
  applyImageViewerBottomLayoutLock();
}

function syncImageViewerFrameSize(settling = false) {
  const frame = els.imageViewerImageFrame;
  if (!frame) return;
  if (els.imageViewer.hidden || !els.imageViewer.classList.contains("layout-bottom")) {
    clearImageViewerBottomLayoutLock(true);
    return;
  }
  if (applyImageViewerBottomLayoutLock()) return;
  frame.style.removeProperty("width");
  frame.style.removeProperty("height");

  const imageWidth = Number(state.viewerImageDimensions.width)
    || Number(els.imageViewerImage.naturalWidth)
    || 0;
  const imageHeight = Number(state.viewerImageDimensions.height)
    || Number(els.imageViewerImage.naturalHeight)
    || 0;
  if (!imageWidth || !imageHeight) return;

  const stage = frame.closest(".image-viewer-stage");
  if (!stage) return;
  const stageRect = stage.getBoundingClientRect();
  const detailsRect = els.imageViewerDetails.getBoundingClientRect();
  const stageStyles = window.getComputedStyle(stage);
  const rowGap = parseFloat(stageStyles.rowGap || stageStyles.gap) || 0;
  const maxWidth = Math.max(0, stageRect.width);
  const maxHeight = Math.max(0, stageRect.height - detailsRect.height - rowGap);
  if (!maxWidth || !maxHeight) return;

  const scale = Math.min(maxWidth / imageWidth, maxHeight / imageHeight);
  const frameWidth = imageWidth * scale;
  const frameHeight = imageHeight * scale;
  const previousDetailsWidth = parseFloat(els.imageViewerDetails.style.width) || 0;
  frame.style.width = `${frameWidth}px`;
  frame.style.height = `${frameHeight}px`;
  els.imageViewerDetails.style.width = `${frameWidth}px`;
  els.imageViewerDetails.style.maxWidth = `${frameWidth}px`;

  // Changing the Tags width can alter chip wrapping and therefore its height.
  // Run one settling pass so the image still uses the exact remaining space.
  if (!settling && Math.abs(previousDetailsWidth - frameWidth) > .5) {
    window.requestAnimationFrame(() => syncImageViewerFrameSize(true));
  }
}

function scheduleImageViewerFrameSync() {
  if (state.viewerFrameSyncHandle) {
    window.cancelAnimationFrame(state.viewerFrameSyncHandle);
  }
  state.viewerFrameSyncHandle = window.requestAnimationFrame(() => {
    state.viewerFrameSyncHandle = 0;
    syncImageViewerFrameSize();
  });
}

function setImageViewerDetailsCollapsed(collapsed) {
  clearImageViewerBottomLayoutLock(true);
  const next = !!collapsed;
  els.imageViewerDetails.classList.toggle("collapsed", next);
  els.imageViewerDetailsToggle.setAttribute("aria-expanded", String(!next));
  const toggleLabel = next ? "展开 Prompt Tags" : "折叠 Prompt Tags";
  els.imageViewerDetailsToggle.setAttribute("aria-label", toggleLabel);
  els.imageViewerDetailsToggle.title = toggleLabel;
  scheduleImageViewerFrameSync();
}

function imageViewerPointHitsRenderedImage(clientX, clientY) {
  const image = els.imageViewerImage;
  const rect = image.getBoundingClientRect();
  const naturalWidth = Number(image.naturalWidth) || Number(state.viewerImageDimensions.width) || 0;
  const naturalHeight = Number(image.naturalHeight) || Number(state.viewerImageDimensions.height) || 0;
  if (!rect.width || !rect.height || !naturalWidth || !naturalHeight) {
    return (
      clientX >= rect.left
      && clientX <= rect.right
      && clientY >= rect.top
      && clientY <= rect.bottom
    );
  }
  const scale = Math.min(rect.width / naturalWidth, rect.height / naturalHeight);
  const renderedWidth = naturalWidth * scale;
  const renderedHeight = naturalHeight * scale;
  const left = rect.left + (rect.width - renderedWidth) / 2;
  const top = rect.top + (rect.height - renderedHeight) / 2;
  return (
    clientX >= left
    && clientX <= left + renderedWidth
    && clientY >= top
    && clientY <= top + renderedHeight
  );
}

const IMAGE_VIEWER_CONTROL_TAGS = new Set([
  "best quality",
  "amazing quality",
  "very aesthetic",
  "absurdres",
  "masterpiece",
  "high quality",
  "ultra detailed",
  "highres",
  "score_9",
  "score_8_up",
  "score_7_up",
  "score_6_up",
  "rating:safe",
  "rating:general",
  "rating:questionable",
  "rating:explicit",
]);

function splitImageViewerPromptTokens(prompt) {
  const text = String(prompt || "");
  const tokens = [];
  let buffer = "";
  let weighted = false;
  let quote = "";
  const bracketStack = [];
  let index = 0;

  const flush = () => {
    const value = buffer.trim().replace(/^[,;\s]+|[,;\s]+$/g, "");
    if (value) tokens.push(value);
    buffer = "";
  };

  while (index < text.length) {
    if (!weighted && !buffer.trim()) {
      const weightPrefix = /^-?\d+(?:\.\d+)?::/.exec(text.slice(index));
      if (weightPrefix) {
        buffer += weightPrefix[0];
        index += weightPrefix[0].length;
        weighted = true;
        continue;
      }
    }

    if (weighted) {
      if (text.startsWith("::", index)) {
        buffer += "::";
        index += 2;
        weighted = false;
        continue;
      }
      buffer += text[index];
      index += 1;
      continue;
    }

    const character = text[index];
    if (quote) {
      buffer += character;
      if (character === quote && text[index - 1] !== "\\") quote = "";
      index += 1;
      continue;
    }
    if (character === '"' || character === "'") {
      quote = character;
      buffer += character;
      index += 1;
      continue;
    }
    if ("([{".includes(character)) {
      bracketStack.push(character);
      buffer += character;
      index += 1;
      continue;
    }
    if (")]}".includes(character)) {
      if (bracketStack.length) bracketStack.pop();
      buffer += character;
      index += 1;
      continue;
    }
    if (",;\n".includes(character) && !bracketStack.length) {
      flush();
      index += 1;
      continue;
    }
    buffer += character;
    index += 1;
  }
  flush();
  return tokens;
}

function imageViewerWeightedTokenParts(token) {
  const value = String(token || "").trim();
  const match = /^\s*(-?\d+(?:\.\d+)?)::\s*([\s\S]*?)\s*::\s*$/.exec(value);
  if (!match) return { weight: "", atoms: value ? [value] : [], weighted: false };
  return {
    weight: match[1],
    atoms: splitImageViewerPromptTokens(match[2]),
    weighted: true,
  };
}

function imageViewerControlTagKey(value) {
  return String(value || "")
    .toLocaleLowerCase()
    .replace(/[\[\]{}()]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function imageViewerConfiguredControlKeys(extraControlPrompts = []) {
  const configuredPrompts = Array.isArray(state.config.retagControlPrompts)
    ? state.config.retagControlPrompts
    : [state.config.retagControlPrompts];
  const additionalPrompts = Array.isArray(extraControlPrompts)
    ? extraControlPrompts
    : [extraControlPrompts];
  const keys = new Set();
  [...configuredPrompts, ...additionalPrompts].forEach((prompt) => {
    splitImageViewerPromptTokens(prompt).forEach((segment) => {
      imageViewerWeightedTokenParts(segment).atoms.forEach((atom) => {
        const key = imageViewerControlTagKey(atom).replace(/^[,;\s]+|[,;\s]+$/g, "");
        if (key) keys.add(key);
      });
    });
  });
  return keys;
}

function imageViewerTagIsControl(token, configuredKeys) {
  const lowered = String(token || "").trim().toLocaleLowerCase();
  const plain = imageViewerControlTagKey(token);
  return (
    lowered.includes("artist:")
    || /\bartist(?:_|\s)/.test(lowered)
    || configuredKeys.has(plain)
    || IMAGE_VIEWER_CONTROL_TAGS.has(plain)
    || ["quality", "aesthetic", "absurdres"].some((phrase) => plain.includes(phrase))
    || /^(?:rating|score)\s*[:_]/.test(plain)
  );
}

function stripImageViewerControlTags(tags, extraControlPrompts = []) {
  const configuredKeys = imageViewerConfiguredControlKeys(extraControlPrompts);
  const kept = [];
  const seen = new Set();
  splitImageViewerPromptTokens(tags).forEach((segment) => {
    const { weight, atoms, weighted } = imageViewerWeightedTokenParts(segment);
    const filtered = [];
    atoms.forEach((rawToken) => {
      const token = String(rawToken || "").trim().replace(/^[,;\s]+|[,;\s]+$/g, "");
      const key = imageViewerControlTagKey(token);
      if (!token || !key || imageViewerTagIsControl(token, configuredKeys) || seen.has(key)) return;
      seen.add(key);
      filtered.push(token);
    });
    if (!filtered.length) return;
    kept.push(weighted ? `${weight}::${filtered.join(", ")} ::` : filtered.join(", "));
  });
  return kept.join(", ").trim().replace(/^[,;\s]+|[,;\s]+$/g, "");
}

function imageViewerAtomicTags(tags) {
  return splitImageViewerPromptTokens(tags)
    .flatMap((segment) => imageViewerWeightedTokenParts(segment).atoms)
    .map((tag) => String(tag || "").trim())
    .filter(Boolean);
}

function imageViewerTagKeys(tags) {
  return imageViewerAtomicTags(tags)
    .map(retagTagLookupKey)
    .filter(Boolean);
}

function imageViewerTagEntries(pairs, translations = {}, tags = "") {
  const normalizedTranslations = normalizeRetagTagTranslations(translations);
  const source = Array.isArray(pairs) && pairs.length
    ? pairs.map((item) => String(item?.tag || "").trim()).filter(Boolean)
    : imageViewerAtomicTags(tags);
  const pairNames = new Map(
    (Array.isArray(pairs) ? pairs : [])
      .map((item) => [
        retagTagLookupKey(item?.tag),
        String(item?.cnName || "").trim(),
      ])
      .filter(([key]) => key),
  );
  return source.slice(0, 320).map((tag) => {
    const key = retagTagLookupKey(tag);
    return {
      tag,
      cnName: pairNames.get(key) || normalizedTranslations[key] || "",
    };
  });
}

function renderImageViewerTags(tags, pairs = [], translations = {}) {
  const rawTags = String(tags || "").trim();
  els.imageViewerTags.dataset.copyText = rawTags;
  els.imageViewerTags.replaceChildren();
  scheduleImageViewerFrameSync();
  const entries = imageViewerTagEntries(pairs, translations, rawTags);
  if (!entries.length) {
    const empty = document.createElement("span");
    empty.className = "image-viewer-tag-empty";
    empty.textContent = "暂无英文 Tags 记录 / No English Tags yet";
    els.imageViewerTags.appendChild(empty);
    return;
  }
  entries.forEach(({ tag, cnName }) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "image-viewer-tag-chip";
    chip.dataset.copyText = tag;
    chip.textContent = cnName ? `${tag} / ${cnName}` : tag;
    chip.title = `复制英文 Tag：${tag}`;
    chip.setAttribute("aria-label", `复制英文 Tag：${tag}`);
    chip.classList.toggle("bilingual", !!cnName);
    chip.addEventListener("click", async (event) => {
      event.stopPropagation();
      await copyPlainText(tag, `复制英文 Tag：${tag}`, () => chip.focus({ preventScroll: true }));
    });
    els.imageViewerTags.appendChild(chip);
  });
}

async function hydrateImageViewerChineseTags(node, tags, lookupSequence) {
  const initialTranslations = normalizeRetagTagTranslations(
    node?.meta?.tagTranslations || node?.meta?.retagTagTranslations,
  );
  renderImageViewerTags(tags, [], initialTranslations);
  const tagKeys = imageViewerTagKeys(tags);
  if (tagKeys.length && tagKeys.every((key) => initialTranslations[key])) return;

  try {
    let result = state.viewerTagTranslationCache.get(tags);
    if (!result) {
      result = await bridge.apiPost("canvas/tags/translate", { tags });
      if (state.viewerTagTranslationCache.size >= 80) {
        state.viewerTagTranslationCache.delete(
          state.viewerTagTranslationCache.keys().next().value,
        );
      }
      state.viewerTagTranslationCache.set(tags, result);
    }
    if (lookupSequence !== state.viewerTagLookupSequence || els.imageViewer.hidden) return;
    const translations = {
      ...initialTranslations,
      ...normalizeRetagTagTranslations(result?.translations),
    };
    // Freeze the already-visible English layout before longer bilingual chips
    // are inserted. New content then scrolls inside the Tags surface instead
    // of feeding back into image sizing and moving both columns/rows.
    lockImageViewerBottomLayout();
    renderImageViewerTags(tags, result?.pairs, translations);
    if (Object.keys(translations).length) {
      node.meta = { ...(node.meta || {}), tagTranslations: translations };
      if (findNode(node.id) === node) scheduleSave();
      if (state.viewerLibraryAsset) {
        state.viewerLibraryAsset.tagTranslations = translations;
      }
    }
  } catch (_) {
    // The English chips are already visible; a tags-site outage should not
    // replace them with an error state or interrupt image preview.
  }
}

function openImageViewer(node, { libraryAsset = null, operationLabel = "打开图片预览" } = {}) {
  if (!node?.dataUrl) {
    toast("图片仍在读取，请稍后重试", "error");
    return;
  }
  const meta = node.meta || {};
  state.viewerImageDimensions = {
    width: Number(meta.width) || 0,
    height: Number(meta.height) || 0,
  };
  applyImageViewerLayout(state.viewerImageDimensions.width, state.viewerImageDimensions.height);
  setImageViewerDetailsCollapsed(false);
  els.imageViewerImage.src = node.dataUrl;
  els.imageViewerImage.alt = node.title || "画布图片";
  const tags = stripImageViewerControlTags(
    meta.tags || meta.finalPrompt || "",
    meta.artist || "",
  );
  renderImageViewerTags(tags);
  state.viewerLibraryAsset = libraryAsset;
  const lookupSequence = ++state.viewerTagLookupSequence;
  els.imageViewerPlaceBtn.hidden = !libraryAsset;
  els.imageViewer.hidden = false;
  els.imageViewer.focus({ preventScroll: true });
  scheduleImageViewerFrameSync();
  if (tags) void hydrateImageViewerChineseTags(node, tags, lookupSequence);
  recordOperation(operationLabel, node.title || "图片");
}

function closeImageViewer() {
  const wasOpen = !els.imageViewer.hidden;
  state.viewerTagLookupSequence += 1;
  els.imageViewer.hidden = true;
  els.imageViewerImage.removeAttribute("src");
  renderImageViewerTags("");
  setImageViewerDetailsCollapsed(false);
  state.viewerImageDimensions = { width: 0, height: 0 };
  applyImageViewerLayout(0, 0);
  state.viewerLibraryAsset = null;
  els.imageViewerPlaceBtn.hidden = true;
  if (wasOpen) recordOperation("关闭图片预览");
}

async function ensureLibraryImageData(item) {
  if (item?.dataUrl) return item.dataUrl;
  if (!item?.id) throw new Error("图片素材 ID 无效");
  if (state.libraryAssetPromises.has(item.id)) {
    return state.libraryAssetPromises.get(item.id);
  }
  const pending = bridge.apiGet("canvas/asset", { id: item.id }).then((payload) => {
    item.dataUrl = payload.dataUrl;
    cacheImageAsset({
      assetId: item.id,
      dataUrl: item.dataUrl,
      meta: { width: item.width, height: item.height },
    });
    return item.dataUrl;
  }).finally(() => {
    state.libraryAssetPromises.delete(item.id);
  });
  state.libraryAssetPromises.set(item.id, pending);
  return pending;
}

function preloadLibraryImages() {
  if (state.libraryPreloadPromise) return state.libraryPreloadPromise;
  const queue = state.library.images.filter((item) => !item.dataUrl);
  let cursor = 0;
  const worker = async () => {
    while (cursor < queue.length) {
      const item = queue[cursor];
      cursor += 1;
      try {
        await ensureLibraryImageData(item);
      } catch (_) {
        // Individual broken assets should not block the rest of the library.
      }
    }
  };
  const workers = Array.from({ length: Math.min(4, queue.length) }, worker);
  state.libraryPreloadPromise = Promise.allSettled(workers).finally(() => {
    state.libraryPreloadPromise = null;
  });
  return state.libraryPreloadPromise;
}

async function loadLibrary(render = true) {
  try {
    const library = await bridge.apiGet("canvas/library");
    state.library = {
      images: Array.isArray(library?.images) ? library.images : [],
      prompts: Array.isArray(library?.prompts) ? library.prompts : [],
    };
    reconcileAssetLibraryPreferences();
    preloadLibraryImages();
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
  }
  if (open && !els.projectMenu.hidden) setProjectMenu(false);
  els.assetPanel.classList.toggle("open", open);
  document.body.classList.toggle("asset-library-open", open);
  [els.assetLibraryBtn, els.mobileAssetLibraryBtn].forEach((button) => {
    button.classList.toggle("active", open);
    button.setAttribute("aria-expanded", String(open));
  });
  if (!open) {
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
    const image = document.createElement("img");
    image.alt = item.name || `${group.label}素材`;
    image.draggable = false;
    image.className = `asset-stack-thumb asset-stack-thumb-${index + 1}`;
    if (item.dataUrl) image.src = item.dataUrl;
    else ensureLibraryImageData(item).then((dataUrl) => {
      if (image.isConnected) image.src = dataUrl;
    }).catch(() => {
      image.classList.add("is-broken");
    });
    cover.appendChild(image);
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
  loading.textContent = "预加载中…";
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
  if (item.dataUrl) image.src = item.dataUrl;
  else ensureLibraryImageData(item).then((dataUrl) => {
    if (image.isConnected) image.src = dataUrl;
  }).catch(() => {
    if (loading.isConnected) loading.textContent = "图片读取失败";
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

async function openLibraryImageViewer(item) {
  try {
    await ensureLibraryImageData(item);
    markAssetRecent(item);
    openImageViewer({
      dataUrl: item.dataUrl,
      title: item.name || "图片素材",
      meta: {
        prompt: item.prompt || "",
        tags: item.tags || "",
        tagTranslations: normalizeRetagTagTranslations(item.tagTranslations),
        artist: item.artist || "",
        width: item.width,
        height: item.height,
        ratio: item.ratio || "",
        seed: normalizeNaiSeed(item.seed),
      },
      }, { libraryAsset: item, operationLabel: "预览素材" });
  } catch (error) {
    recordOperation("预览素材失败", error.message || "图片素材读取失败", "error");
    toast(error.message || "图片素材读取失败", "error");
  }
}

function createLibraryImageNode(item, x, y, nodeWidth = fittedImageNodeWidth(item.width, item.height)) {
  return {
    id: uid("image"),
    type: "image",
    x,
    y,
    width: nodeWidth,
    title: item.name || "素材图片",
    assetId: item.id,
    dataUrl: item.dataUrl,
    createdAt: new Date().toISOString(),
    meta: {
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
    const loaded = await Promise.allSettled(items.map((item) => ensureLibraryImageData(item)));
    const usedPaths = new Set(["library-manifest.json"]);
    const entries = [];
    const manifest = [];
    loaded.forEach((result, index) => {
      const item = items[index];
      if (result.status === "rejected") {
        manifest.push({
          id: item.id,
          name: item.name || "",
          skipped: true,
          reason: String(result.reason?.message || result.reason || "图片素材读取失败").slice(0, 160),
        });
        return;
      }
      try {
        const decoded = decodeDataUrl(item.dataUrl);
        const group = assetGroupForItem(item);
        const path = uniqueZipPath(
          group.label,
          item.name || item.id || `asset-${index + 1}`,
          imageExtension(decoded.mimeType),
          usedPaths,
        );
        entries.push({ name: path, bytes: decoded.bytes });
        manifest.push({
          id: item.id,
          file: path,
          name: item.name || "",
          artist: item.artist || "",
          prompt: item.prompt || "",
          tags: item.tags || "",
          ratio: item.ratio || "",
          seed: normalizeNaiSeed(item.seed),
          source: item.source || "",
          width: item.width || 0,
          height: item.height || 0,
          size: decoded.bytes.length,
        });
      } catch (error) {
        manifest.push({
          id: item.id,
          name: item.name || "",
          skipped: true,
          reason: String(error?.message || error || "图片素材解析失败").slice(0, 160),
        });
      }
    });
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
      return createLibraryImageNode(entry.item, x, y, entry.width);
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
    await ensureLibraryImageData(item);
    await recoverLibraryImageSeed(item);
    markAssetRecent(item, { render: false });
    const nodeWidth = fittedImageNodeWidth(item.width, item.height);
    const nodeHeight = estimatedImageNodeHeight(nodeWidth, item.width, item.height);
    addNode(createLibraryImageNode(
      item,
      point.x - nodeWidth / 2,
      point.y - nodeHeight / 2,
      nodeWidth,
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
  if (!node?.assetId) return;
  try {
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
      tags: node.meta?.tags || node.meta?.finalPrompt || linkedRetag.retagPrompt || "",
      tagTranslations: normalizeRetagTagTranslations(
        node.meta?.tagTranslations || linkedRetag.retagTagTranslations,
      ),
      artist: node.meta?.artist || "",
      ratio: node.meta?.ratio || linkedRetag.retagRatio || "",
      // A source image may only reveal its seed during the retag pass; keep
      // that value when the image itself is later collected into the library.
      seed,
    });
    const image = { ...result.image, dataUrl: node.dataUrl };
    state.library.images = [image, ...state.library.images.filter((item) => item.id !== image.id)];
    reconcileAssetLibraryPreferences();
    if (els.assetPanel.classList.contains("open")) renderAssetLibrary();
    toast("图片已保存到素材库");
    recordOperation("收录素材", node.title || "画布图片", "success");
  } catch (error) {
    recordOperation("收录素材失败", error.message || "图片保存失败", "error");
    toast(error.message || "图片保存失败", "error");
  }
}

function isSupportedImageFile(file) {
  const type = String(file?.type || "").toLowerCase();
  if (type.startsWith("image/")) return true;
  // Desktop drag-and-drop providers occasionally omit MIME metadata.  The
  // backend still verifies the actual bytes, so an extension fallback keeps
  // those legitimate image drops usable without weakening server validation.
  return /\.(?:png|jpe?g|webp|gif)$/i.test(String(file?.name || ""));
}

async function uploadFiles(files, point = worldCenter()) {
  const images = [...files].filter(isSupportedImageFile);
  if (!images.length) {
    toast("请选择 PNG、JPEG、WebP 或 GIF 图片", "error");
    return;
  }
  for (let index = 0; index < images.length; index += 1) {
    try {
      const asset = await bridge.upload("canvas/upload", images[index]);
      const nodeWidth = fittedImageNodeWidth(asset.width, asset.height);
      const nodeHeight = estimatedImageNodeHeight(nodeWidth, asset.width, asset.height);
      const node = {
        id: uid("image"),
        type: "image",
        x: point.x + index * 34 - nodeWidth / 2,
        y: point.y + index * 34 - nodeHeight / 2,
        width: nodeWidth,
        title: images[index].name,
        assetId: asset.id,
        dataUrl: asset.dataUrl,
        createdAt: new Date().toISOString(),
        meta: { prompt: images[index].name, width: asset.width, height: asset.height },
      };
      addNode(node);
      recordOperation("上传图片", images[index].name, "success");
    } catch (error) {
      recordOperation("上传图片失败", `${images[index].name}：${error.message}`, "error");
      toast(`${images[index].name}：${error.message}`, "error");
    }
  }
}

async function loadInitialState() {
  bridge = await getBridge();
  const [config, canvasList, library, preferences] = await Promise.all([
    bridge.apiGet("canvas/config"),
    bridge.apiGet("canvas/canvases"),
    bridge.apiGet("canvas/library"),
    bridge.apiGet("canvas/preferences"),
  ]);
  state.canvases = Array.isArray(canvasList?.canvases) ? canvasList.canvases : [];
  state.config = { ...state.config, ...(config || {}) };
  let savedDebug = null;
  try { savedDebug = localStorage.getItem("bestnaiCanvasDebug"); } catch (_) { /* ignore */ }
  state.debugEnabled = savedDebug === "1";
  els.debugModeBtn?.setAttribute("aria-pressed", String(debugModeEnabled()));
  els.debugModeBtn?.classList.toggle("active", debugModeEnabled());
  const debugLabel = debugModeEnabled() ? "关闭详细调试模式" : "开启详细调试模式";
  els.debugModeBtn?.setAttribute("aria-label", debugLabel);
  if (els.debugModeBtn) els.debugModeBtn.title = debugLabel;
  loadPromptDefaults(preferences || {});
  const plugin = state.config.plugin || {};
  els.pluginDisplayName.textContent = plugin.name || "NAI Diffusion X";
  // 版本号只有后端能提供，拿不到就留空。写死一个兜底版本号只会显示成过期的假信息
  const pluginVersion = String(plugin.version || "").trim();
  els.pluginVersion.textContent = pluginVersion ? `v${pluginVersion}` : "";
  els.pluginVersion.hidden = !pluginVersion;
  els.pluginAuthor.textContent = plugin.author || "Menkelo";
  let canvasMeta = state.canvases.find((item) => item.id === canvasId);
  if (!canvasMeta) {
    let rememberedId = String(preferences?.lastCanvasId || "");
    try {
      rememberedId ||= localStorage.getItem(LAST_CANVAS_KEY) || "";
    } catch (_) {
      // The current browser may disable local storage.
    }
    canvasMeta = state.canvases.find((item) => item.id === rememberedId)
      || state.canvases[0];
  }
  if (!canvasMeta) {
    const result = await bridge.apiPost("canvas/canvases/create", {
      title: "默认项目",
      projectId: "default",
    });
    canvasMeta = result?.canvas;
    if (!canvasMeta?.id) throw new Error("初始化项目失败");
    state.canvases.push(canvasMeta);
  }
  state.library = {
    images: Array.isArray(library?.images) ? library.images : [],
    prompts: Array.isArray(library?.prompts) ? library.prompts : [],
  };
  reconcileAssetLibraryPreferences();
  preloadLibraryImages();
  await switchCanvas(canvasMeta, { saveCurrent: false });
  startHealthMonitor();
}

const canvasTouchPointers = new Map();
let canvasTouchGesture = null;

function canvasTouchPair() {
  const entries = [...canvasTouchPointers.entries()];
  return entries.length >= 2 ? entries.slice(0, 2) : null;
}

function beginCanvasPinch() {
  const pair = canvasTouchPair();
  if (!pair) return;
  const [[firstId, first], [secondId, second]] = pair;
  const midpoint = {
    x: (first.x + second.x) / 2,
    y: (first.y + second.y) / 2,
  };
  canvasTouchGesture = {
    mode: "pinch",
    pointerIds: [firstId, secondId],
    startDistance: Math.max(1, Math.hypot(second.x - first.x, second.y - first.y)),
    startScale: state.viewport.scale,
    world: clientToWorld(midpoint.x, midpoint.y),
  };
}

function handleCanvasTouchStart(event) {
  event.preventDefault();
  canvasTouchPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  try {
    els.viewport.setPointerCapture(event.pointerId);
  } catch (_) {
    // Some embedded mobile browsers do not expose pointer capture.
  }
  els.viewport.classList.add("panning");
  if (canvasTouchPointers.size === 1) {
    collapseRetagLayers();
    clearSelection();
    document.querySelectorAll(".node.selected").forEach((node) => node.classList.remove("selected"));
    requestAnimationFrame(renderConnections);
    canvasTouchGesture = {
      mode: "pan",
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      viewportX: state.viewport.x,
      viewportY: state.viewport.y,
    };
  } else if (canvasTouchPointers.size === 2) {
    beginCanvasPinch();
  }
}

function handleCanvasTouchMove(event) {
  if (!canvasTouchPointers.has(event.pointerId)) return;
  event.preventDefault();
  canvasTouchPointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
  if (canvasTouchPointers.size >= 2) {
    if (canvasTouchGesture?.mode !== "pinch") beginCanvasPinch();
    const [firstId, secondId] = canvasTouchGesture.pointerIds;
    const first = canvasTouchPointers.get(firstId);
    const second = canvasTouchPointers.get(secondId);
    if (!first || !second) {
      beginCanvasPinch();
      return;
    }
    const midpoint = {
      x: (first.x + second.x) / 2,
      y: (first.y + second.y) / 2,
    };
    const distance = Math.max(1, Math.hypot(second.x - first.x, second.y - first.y));
    const rect = els.viewport.getBoundingClientRect();
    const scale = clamp(
      canvasTouchGesture.startScale * distance / canvasTouchGesture.startDistance,
      0.1,
      4,
    );
    state.viewport.scale = scale;
    state.viewport.x = midpoint.x - rect.left - canvasTouchGesture.world.x * scale;
    state.viewport.y = midpoint.y - rect.top - canvasTouchGesture.world.y * scale;
    scheduleViewportProjection();
    return;
  }
  if (canvasTouchGesture?.mode !== "pan" || canvasTouchGesture.pointerId !== event.pointerId) return;
  state.viewport.x = canvasTouchGesture.viewportX + event.clientX - canvasTouchGesture.startX;
  state.viewport.y = canvasTouchGesture.viewportY + event.clientY - canvasTouchGesture.startY;
  scheduleViewportProjection();
}

function handleCanvasTouchEnd(event) {
  if (!canvasTouchPointers.has(event.pointerId)) return;
  event.preventDefault();
  canvasTouchPointers.delete(event.pointerId);
  try {
    if (els.viewport.hasPointerCapture(event.pointerId)) {
      els.viewport.releasePointerCapture(event.pointerId);
    }
  } catch (_) {
    // Pointer capture may already have been released by the browser.
  }
  if (canvasTouchPointers.size >= 2) {
    beginCanvasPinch();
    return;
  }
  if (canvasTouchPointers.size === 1) {
    const [[pointerId, point]] = canvasTouchPointers.entries();
    canvasTouchGesture = {
      mode: "pan",
      pointerId,
      startX: point.x,
      startY: point.y,
      viewportX: state.viewport.x,
      viewportY: state.viewport.y,
    };
    return;
  }
  canvasTouchGesture = null;
  els.viewport.classList.remove("panning");
  scheduleSave(800);
  recordOperation("平移画布", "触控视图");
}

els.viewport.addEventListener("pointerdown", (event) => {
  const middlePan = event.pointerType === "mouse" && event.button === 1;
  if (
    (event.button !== 0 && !middlePan)
    || (!middlePan && event.target.closest(
      ".node, button, .link-hit, .link-delete, .asset-panel, .debug-bar",
    ))
  ) return;

  if (middlePan) event.preventDefault();
  if (event.pointerType !== "touch") focusCanvasSurface();
  setCanvasContextMenu(false);
  setNodeContextMenu(false);
  setSelectionContextMenu(false);
  if (middlePan) setProjectMenu(false);

  if (event.pointerType === "touch") {
    handleCanvasTouchStart(event);
    return;
  }

  // Desktop follows the familiar CAD interaction model: middle-drag pans,
  // wheel zooms, a plain left click selects/clears, and a left drag on empty
  // canvas creates a selection window. Ctrl/Cmd toggles selection; Shift adds
  // to it. This keeps node dragging on the header untouched.
  if (!middlePan) {
    event.preventDefault();
    event.stopPropagation();
    setProjectMenu(false);
    const viewportRect = els.viewport.getBoundingClientRect();
    const startWorld = clientToWorld(event.clientX, event.clientY);
    const startX = event.clientX - viewportRect.left;
    const startY = event.clientY - viewportRect.top;
    const additive = !!event.shiftKey;
    const toggle = !!(event.ctrlKey || event.metaKey);
    const baseSelection = selectedNodeIds();
    let moved = false;

    els.viewport.setPointerCapture(event.pointerId);
    const updateSelectionBox = (moveEvent) => {
      const currentX = moveEvent.clientX - viewportRect.left;
      const currentY = moveEvent.clientY - viewportRect.top;
      if (!moved && Math.hypot(currentX - startX, currentY - startY) < 4) return;
      moved = true;
      els.selectionBox.classList.add("visible");
      els.selectionBox.classList.toggle("crossing", currentX < startX);
      els.selectionBox.classList.toggle("window", currentX >= startX);
      els.selectionBox.style.left = `${Math.min(startX, currentX)}px`;
      els.selectionBox.style.top = `${Math.min(startY, currentY)}px`;
      els.selectionBox.style.width = `${Math.abs(currentX - startX)}px`;
      els.selectionBox.style.height = `${Math.abs(currentY - startY)}px`;
    };
    const endSelection = (endEvent) => {
      if (els.viewport.hasPointerCapture(endEvent.pointerId)) {
        els.viewport.releasePointerCapture(endEvent.pointerId);
      }
      els.selectionBox.classList.remove("visible", "crossing", "window");
      els.viewport.removeEventListener("pointermove", updateSelectionBox);
      els.viewport.removeEventListener("pointerup", endSelection);
      els.viewport.removeEventListener("pointercancel", endSelection);
      if (endEvent.type === "pointercancel") return;
      if (moved) {
        finishBoxSelection(startWorld, endEvent, {
          startClientX: event.clientX,
          additive,
          toggle,
          baseSelection,
        });
      } else if (!additive && !toggle) {
        collapseRetagLayers();
        clearSelection();
        renderAll();
      }
    };
    els.viewport.addEventListener("pointermove", updateSelectionBox);
    els.viewport.addEventListener("pointerup", endSelection);
    els.viewport.addEventListener("pointercancel", endSelection);
    return;
  }

  // Middle-button panning remains available while the left button is reserved
  // for CAD-style selection windows.
  const start = { x: event.clientX, y: event.clientY, vx: state.viewport.x, vy: state.viewport.y };
  els.viewport.classList.add("panning");
  els.viewport.setPointerCapture(event.pointerId);
  const move = (moveEvent) => {
    state.viewport.x = start.vx + moveEvent.clientX - start.x;
    state.viewport.y = start.vy + moveEvent.clientY - start.y;
    scheduleViewportProjection();
  };
  const end = () => {
    els.viewport.classList.remove("panning");
    els.viewport.removeEventListener("pointermove", move);
    els.viewport.removeEventListener("pointerup", end);
    els.viewport.removeEventListener("pointercancel", end);
    scheduleSave(800);
    recordOperation("平移画布", "鼠标中键拖动");
  };
  els.viewport.addEventListener("pointermove", move);
  els.viewport.addEventListener("pointerup", end);
  els.viewport.addEventListener("pointercancel", end);
});

els.viewport.addEventListener("pointermove", handleCanvasTouchMove);
els.viewport.addEventListener("pointerup", handleCanvasTouchEnd);
els.viewport.addEventListener("pointercancel", handleCanvasTouchEnd);

function nodeEditorOwnsWheel(target) {
  const targetElement = target instanceof Element ? target : target?.parentElement;
  if (!targetElement) return false;
  if (targetElement.closest(".asset-panel, .image-viewer-details, .debug-bar")) return true;
  const retagLayer = targetElement.closest(".retag-layer-card");
  if (retagLayer) return !!retagLayer.closest(".node.selected");
  const editor = targetElement.closest(".prompt-text, .note-text");
  return !!editor?.closest(".node.selected");
}

els.viewport.addEventListener("wheel", (event) => {
  if (nodeEditorOwnsWheel(event.target)) return;
  // 平移进行中忽略滚轮：中键平移按拖拽起点的快照绝对覆写偏移，
  // 滚轮缩放刚写入的偏移会被下一次 pointermove 冲掉（scale 却保留新值），
  // 画面就会整体错位。捏合缩放同理依赖连续手势，期间也不接受滚轮。
  if (els.viewport.classList.contains("panning")) {
    event.preventDefault();
    return;
  }
  event.preventDefault();
  const factor = Math.exp(-event.deltaY * 0.0015);
  setZoom(state.viewport.scale * factor, event.clientX, event.clientY);
}, { passive: false });

els.assetPanel.addEventListener("wheel", (event) => {
  event.stopPropagation();
}, { passive: true });

els.debugBar?.addEventListener("wheel", (event) => {
  event.stopPropagation();
}, { passive: true });

// The diagnostics HUD is an interactive surface of its own. Keep pointer
// gestures (including text drag-selection) from reaching the canvas' CAD
// selection/pan handlers.
els.debugBar?.addEventListener("pointerdown", (event) => event.stopPropagation());
els.debugBar?.addEventListener("dblclick", (event) => event.stopPropagation());

els.viewport.addEventListener("dblclick", (event) => {
  if (event.target.closest(
    ".node, button, .link-hit, .link-delete, .asset-panel, .debug-bar",
  )) return;
  event.preventDefault();
  addNode(createPromptNode(clientToWorld(event.clientX, event.clientY)));
});

els.viewport.addEventListener("contextmenu", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  // Text controls keep the browser's native edit/copy menu.
  if (target?.closest("textarea, input, select, [contenteditable='true']")) return;
  // Overlay surfaces own their own interaction and are not blank canvas.
  if (target?.closest(
    ".topbar, .asset-panel, .debug-bar, .image-viewer, .project-menu",
  )) return;
  // A multi-selection is one editing target. Right-clicking either a selected
  // node or blank canvas must keep that selection intact and expose only the
  // operations that apply to the whole set.
  if (selectedNodeIds().length >= 2) {
    event.preventDefault();
    event.stopPropagation();
    setProjectMenu(false);
    setSelectionContextMenu(true, event.clientX, event.clientY);
    return;
  }
  const nodeElement = target?.closest(".node");
  if (nodeElement) {
    const node = findNode(nodeElement.dataset.nodeId);
    event.preventDefault();
    event.stopPropagation();
    if (!node) return;
    setProjectMenu(false);
    if (!isNodeSelected(node.id)) selectNode(node.id);
    else setSelection(selectedNodeIds(), node.id);
    setNodeContextMenu(true, node, event.clientX, event.clientY);
    return;
  }
  if (target?.closest("button, .link-hit, .link-delete")) {
    event.preventDefault();
    event.stopPropagation();
    setNodeContextMenu(false);
    setCanvasContextMenu(false);
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  setProjectMenu(false);
  setNodeContextMenu(false);
  if (els.assetPanel.classList.contains("open")) setAssetPanel(false);
  state.contextMenuPoint = clientToWorld(event.clientX, event.clientY);
  setCanvasContextMenu(true, event.clientX, event.clientY);
});

function dataTransferHasFiles(dataTransfer) {
  return Array.from(dataTransfer?.types || []).includes("Files")
    || Number(dataTransfer?.files?.length || 0) > 0;
}

function clearDropOverlay() {
  els.viewport.classList.remove("drag-over");
}

function isSelectableTextTarget(target) {
  const targetElement = target instanceof Element ? target : target?.parentElement;
  const selection = window.getSelection?.();
  const selectionNodes = selection
    ? [selection.anchorNode, selection.focusNode]
    : [];
  const selectionInTextSurface = selectionNodes.some((node) => {
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    return element?.closest?.(
      ".prompt-text, .note-text, .image-viewer-copy-text, .clipboard-copy-buffer, .debug-body, .operation-log-list",
    );
  });
  return !!(
    targetElement?.closest(".prompt-text, .note-text, .image-viewer-copy-text, .clipboard-copy-buffer")
    || targetElement?.closest(".debug-body, .operation-log-list")
    || document.activeElement?.closest?.(".prompt-text, .note-text, .image-viewer-copy-text, .clipboard-copy-buffer")
    || document.activeElement?.closest?.(".debug-body, .operation-log-list")
    || selectionInTextSurface
  );
}

document.addEventListener("dragstart", (event) => {
  event.preventDefault();
  clearDropOverlay();
});
document.addEventListener("selectstart", (event) => {
  if (!isSelectableTextTarget(event.target)) event.preventDefault();
});
document.addEventListener("copy", (event) => {
  if (!isSelectableTextTarget(event.target)) event.preventDefault();
});
document.addEventListener("cut", (event) => {
  if (!isSelectableTextTarget(event.target)) event.preventDefault();
});

els.viewport.addEventListener("dragover", (event) => {
  if (!dataTransferHasFiles(event.dataTransfer)) {
    clearDropOverlay();
    return;
  }
  event.preventDefault();
  event.dataTransfer.dropEffect = "copy";
  els.viewport.classList.add("drag-over");
});
els.viewport.addEventListener("dragleave", (event) => {
  if (!els.viewport.contains(event.relatedTarget)) clearDropOverlay();
});
els.viewport.addEventListener("drop", (event) => {
  const hasFiles = dataTransferHasFiles(event.dataTransfer);
  clearDropOverlay();
  if (!hasFiles) return;
  event.preventDefault();
  uploadFiles(event.dataTransfer.files, clientToWorld(event.clientX, event.clientY));
});
window.addEventListener("dragend", clearDropOverlay);
window.addEventListener("drop", clearDropOverlay, true);
window.addEventListener("blur", clearDropOverlay);

document.getElementById("addPromptBtn").addEventListener("click", () => addNode(createPromptNode()));
document.getElementById("addNoteBtn").addEventListener("click", () => addNode(createNoteNode()));
document.getElementById("addImageBtn").addEventListener("click", () => {
  state.pendingUploadPoint = null;
  els.imageInput.click();
});
document.getElementById("contextAddImageBtn").addEventListener("click", () => {
  const point = state.contextMenuPoint || worldCenter();
  setCanvasContextMenu(false);
  state.pendingUploadPoint = point;
  els.imageInput.click();
});
document.getElementById("contextAddPromptBtn").addEventListener("click", () => {
  const point = state.contextMenuPoint || worldCenter();
  setCanvasContextMenu(false);
  addNode(createPromptNode(point));
});
document.getElementById("contextAddNoteBtn").addEventListener("click", () => {
  const point = state.contextMenuPoint || worldCenter();
  setCanvasContextMenu(false);
  addNode(createNoteNode(point));
});
document.getElementById("nodeContextDuplicate").addEventListener("click", () => {
  const node = findNode(state.contextMenuNodeId);
  setNodeContextMenu(false);
  if (node) duplicateNode(node.id);
});
document.getElementById("nodeContextDelete").addEventListener("click", () => {
  const node = findNode(state.contextMenuNodeId);
  setNodeContextMenu(false);
  if (node) deleteNode(node.id);
});
document.getElementById("nodeContextSaveImage").addEventListener("click", async () => {
  const node = findNode(state.contextMenuNodeId);
  setNodeContextMenu(false);
  if (node?.type === "image") await saveImageToLibrary(node);
});
document.getElementById("nodeContextDownloadImage").addEventListener("click", async () => {
  const node = findNode(state.contextMenuNodeId);
  setNodeContextMenu(false);
  if (node?.type === "image") await downloadImage(node);
});
document.getElementById("selectionContextArrange").addEventListener("click", () => {
  setSelectionContextMenu(false);
  arrangeSelectedNodes();
});
document.getElementById("selectionContextDelete").addEventListener("click", () => {
  const ids = selectedNodeIds();
  setSelectionContextMenu(false);
  deleteNodes(ids);
});
document.getElementById("fitBtn").addEventListener("click", fitView);
els.debugModeBtn?.addEventListener("click", () => {
  const next = !state.debugEnabled;
  state.debugEnabled = next;
  try { localStorage.setItem("bestnaiCanvasDebug", state.debugEnabled ? "1" : "0"); } catch (_) { /* ignore */ }
  els.debugModeBtn.setAttribute("aria-pressed", String(debugModeEnabled()));
  els.debugModeBtn.classList.toggle("active", debugModeEnabled());
  const debugLabel = next ? "关闭详细调试模式" : "开启详细调试模式";
  els.debugModeBtn.title = debugLabel;
  els.debugModeBtn.setAttribute("aria-label", debugLabel);
  recordOperation(
    next ? "开启调试模式" : "关闭调试模式",
    next ? "详细诊断已显示在画布底部" : "详细诊断已关闭，操作记录仍会保留",
  );
  renderDebugBar();
  renderAll();
});
els.debugBarToggle?.addEventListener("click", () => setDebugBarOpen(!state.debugBarOpen));
document.getElementById("debugLogClearBtn")?.addEventListener("click", (event) => {
  event.stopPropagation();
  clearOperationLog();
});
els.undoBtn.addEventListener("click", undo);
els.redoBtn.addEventListener("click", redo);
els.arrangeSelectionBtn.addEventListener("click", arrangeSelectedNodes);
els.projectMenuBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  setProjectMenu(els.projectMenu.hidden);
  if (!els.projectMenu.hidden) renderProjectMenu();
});
document.getElementById("newProjectBtn").addEventListener("click", () => {
  els.newProjectRow.hidden = false;
  els.newProjectInput.focus();
});
document.getElementById("confirmNewProjectBtn").addEventListener("click", createCanvasProject);
document.getElementById("cancelNewProjectBtn").addEventListener("click", () => {
  els.newProjectRow.hidden = true;
  els.newProjectInput.value = "";
});
els.newProjectInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    createCanvasProject();
  } else if (event.key === "Escape") {
    event.preventDefault();
    els.newProjectRow.hidden = true;
    els.newProjectInput.value = "";
  }
});
document.addEventListener("pointerdown", (event) => {
  if (!els.projectMenu.hidden && !event.target.closest(".project-switcher, .project-menu")) {
    setProjectMenu(false);
  }
  if (!els.canvasContextMenu.hidden && !event.target.closest(".canvas-context-menu")) {
    setCanvasContextMenu(false);
  }
  if (!els.nodeContextMenu.hidden && !event.target.closest(".node-context-menu")) {
    setNodeContextMenu(false);
  }
  if (!els.selectionContextMenu.hidden && !event.target.closest(".selection-context-menu")) {
    setSelectionContextMenu(false);
  }
});
[els.assetLibraryBtn, els.mobileAssetLibraryBtn].forEach((button) => {
  button.addEventListener("click", () => {
    setAssetPanel(!els.assetPanel.classList.contains("open"));
  });
});
document.querySelectorAll("[data-library-view]").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    setAssetLibraryView(button.dataset.libraryView);
  });
});
els.assetStackTrail?.addEventListener("click", (event) => {
  event.stopPropagation();
  closeAssetStack();
});
els.assetRefreshBtn?.addEventListener("click", async (event) => {
  event.stopPropagation();
  if (els.assetRefreshBtn.disabled) return;
  els.assetRefreshBtn.disabled = true;
  els.assetRefreshBtn.classList.add("spinning");
  recordOperation("刷新素材库");
  try {
    const refreshed = await loadLibrary(true);
    recordOperation(
      refreshed ? "素材库已刷新" : "素材库刷新失败",
      refreshed ? `已收录 ${state.library.images.length} 张素材` : "读取服务失败",
      refreshed ? "success" : "error",
    );
  } finally {
    els.assetRefreshBtn.disabled = false;
    els.assetRefreshBtn.classList.remove("spinning");
    refreshIcons(els.assetRefreshBtn);
  }
});
els.assetSelectModeBtn.addEventListener("click", () => setAssetDeleteMode(true));
els.assetPlaceSelectedBtn.addEventListener("click", placeSelectedLibraryAssetsOnCanvas);
els.assetArchiveSelectedBtn.addEventListener("click", archiveSelectedLibraryAssets);
els.assetDeleteCancel.addEventListener("click", () => setAssetDeleteMode(false));
els.assetDeleteConfirm.addEventListener("click", openAssetDeleteModal);
els.confirmAssetDeleteBtn.addEventListener("click", deleteSelectedLibraryAssets);
els.cancelAssetDeleteBtn.addEventListener("click", () => closeAssetDeleteModal());
els.assetDeleteModal.addEventListener("pointerdown", (event) => {
  if (event.target === els.assetDeleteModal) closeAssetDeleteModal();
});

els.imageInput.addEventListener("change", () => {
  uploadFiles(els.imageInput.files, state.pendingUploadPoint || worldCenter());
  state.pendingUploadPoint = null;
  els.imageInput.value = "";
});

document.getElementById("exportBtn").addEventListener("click", async () => {
  await saveWorkspace();
  try {
    await bridge.download("canvas/workspace/export", { id: canvasId }, `${state.currentCanvasTitle || "bestnai-canvas"}.json`);
    recordOperation("导出工作区", state.currentCanvasTitle, "success");
  } catch (error) {
    recordOperation("导出工作区失败", error.message || "导出失败", "error");
    toast(error.message, "error");
  }
});

document.getElementById("importBtn").addEventListener("click", () => els.workspaceInput.click());
els.workspaceInput.addEventListener("change", async () => {
  const file = els.workspaceInput.files?.[0];
  els.workspaceInput.value = "";
  if (!file) return;
  try {
    const workspace = JSON.parse(await file.text());
    if (!Array.isArray(workspace.nodes) || !Array.isArray(workspace.connections)) {
      throw new Error("文件不是有效的画布工作区");
    }
    pushHistory();
    state.nodes = (workspace.nodes || []).map(normalizeLoadedNodeDimensions);
    state.connections = workspace.connections || [];
    state.lastDebugNodeId = "";
    state.viewport = workspace.viewport || state.viewport;
    clearSelection();
    renderAll();
    scheduleSave(0);
    toast("工作区导入完成");
    recordOperation("导入工作区", `${state.nodes.length} 个节点`, "success");
  } catch (error) {
    recordOperation("导入工作区失败", error.message || "导入失败", "error");
    toast(error.message, "error");
  }
});

const clearModal = document.getElementById("clearModal");
document.getElementById("clearBtn").addEventListener("click", () => {
  if (!state.nodes.length) return;
  clearModal.hidden = false;
  document.getElementById("cancelClearBtn").focus();
});
document.getElementById("cancelClearBtn").addEventListener("click", () => {
  clearModal.hidden = true;
});
document.getElementById("confirmClearBtn").addEventListener("click", () => {
  clearModal.hidden = true;
  const count = state.nodes.length;
  deleteNodes(state.nodes.map((node) => node.id));
  recordOperation("清空画布", `${count} 个节点`);
});
clearModal.addEventListener("pointerdown", (event) => {
  if (event.target === clearModal) clearModal.hidden = true;
});

els.imageViewerPlaceBtn.addEventListener("click", async () => {
  const item = state.viewerLibraryAsset;
  if (!item) return;
  els.imageViewerPlaceBtn.disabled = true;
  const placed = await placeImageAssetOnCanvas(item, worldCenter());
  els.imageViewerPlaceBtn.disabled = false;
  if (!placed) return;
  closeImageViewer();
  setAssetPanel(false);
  toast("已放入画布");
});
els.imageViewerImage.addEventListener("load", () => {
  if (els.imageViewer.hidden) return;
  applyImageViewerLayout(els.imageViewerImage.naturalWidth, els.imageViewerImage.naturalHeight);
});
els.imageViewerDetailsToggle.addEventListener("click", () => {
  setImageViewerDetailsCollapsed(!els.imageViewerDetails.classList.contains("collapsed"));
});
els.imageViewer.addEventListener("pointerdown", (event) => {
  if (
    event.button !== 0
    || event.target.closest(".image-viewer-details, .image-viewer-place-btn")
  ) return;
  if (imageViewerPointHitsRenderedImage(event.clientX, event.clientY)) return;
  closeImageViewer();
});
document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", () => copyViewerText(button.dataset.copyTarget, button.title));
});

async function copyViewerText(targetId, label) {
  const target = document.getElementById(targetId);
  const text = target?.dataset.copyText?.trim() || target?.textContent?.trim() || "";
  if (!text || text.startsWith("暂无")) {
    toast("没有可复制的内容", "error");
    return;
  }
  await copyPlainText(text, label, () => els.imageViewer.focus({ preventScroll: true }));
}

async function copyPlainText(text, label, refocus) {
  const value = String(text || "").trim();
  if (!value) {
    toast("没有可复制的内容", "error");
    return;
  }
  try {
    const buffer = document.createElement("textarea");
    buffer.className = "clipboard-copy-buffer";
    buffer.value = value;
    buffer.style.position = "fixed";
    buffer.style.opacity = "0";
    document.body.appendChild(buffer);
    buffer.focus();
    buffer.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } finally {
      buffer.remove();
      refocus?.();
    }
    if (!copied) {
      if (!navigator.clipboard?.writeText) throw new Error("浏览器拒绝复制");
      await navigator.clipboard.writeText(value);
    }
    toast(`${label || "内容"}成功`);
  } catch (_) {
    toast("复制失败，请拖动选择文字后复制", "error");
  }
}

document.addEventListener("keydown", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const editing = !!target?.closest("textarea, input, select, [contenteditable='true']");
  if (event.key === "Escape") {
    if (!els.assetDeleteModal.hidden) {
      closeAssetDeleteModal();
      return;
    }
    if (!clearModal.hidden) {
      clearModal.hidden = true;
      return;
    }
    if (!els.imageViewer.hidden) {
      closeImageViewer();
      return;
    }
    if (!els.canvasContextMenu.hidden) {
      setCanvasContextMenu(false);
      return;
    }
    if (!els.nodeContextMenu.hidden) {
      setNodeContextMenu(false);
      return;
    }
    if (!els.selectionContextMenu.hidden) {
      setSelectionContextMenu(false);
      return;
    }
    if (!els.projectMenu.hidden) {
      setProjectMenu(false);
      return;
    }
    if (els.assetPanel.classList.contains("open")) {
      setAssetPanel(false);
      return;
    }
    if (!editing) {
      clearSelection();
      renderAll();
    }
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    saveWorkspace();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    if (editing) return;
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key === "0") {
    event.preventDefault();
    fitView();
    return;
  }
  if (!editing && (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "a") {
    event.preventDefault();
    const ids = state.nodes.map((node) => node.id);
    setSelection(ids, ids[ids.length - 1] || "");
    renderAll();
    return;
  }
  if (!editing && (event.key === "Delete" || event.key === "Backspace") && selectedNodeIds().length) {
    event.preventDefault();
    deleteNodes(selectedNodeIds());
    focusCanvasSurface();
  }
});

window.addEventListener("resize", () => {
  setCanvasContextMenu(false);
  setNodeContextMenu(false);
  setSelectionContextMenu(false);
  alignToastRegion();
  scheduleOverlayAlignment();
  if (!els.imageViewer.hidden) {
    applyImageViewerLayout(state.viewerImageDimensions.width, state.viewerImageDimensions.height);
    scheduleImageViewerFrameSync();
  }
});
window.addEventListener("online", checkConnection);
window.addEventListener("offline", () => setConnectionState("offline"));
function flushPendingSave() {
  if (!state.saveTimer) return false;
  window.clearTimeout(state.saveTimer);
  state.saveTimer = null;
  saveWorkspace();
  return true;
}

// 切标签、最小化、关页面都会先触发 visibilitychange，
// 在这里落盘比等到 beforeunload 可靠得多——浏览器会取消 unload 期间的异步请求
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flushPendingSave();
});

window.addEventListener("beforeunload", (event) => {
  window.clearInterval(state.healthTimer);
  if (!state.saveTimer && !state.saving) return;
  // 还有改动没写完，与其静默丢失，不如让浏览器提示一下
  flushPendingSave();
  event.preventDefault();
  event.returnValue = "";
});

renderDebugBar();
refreshIcons();
setupOverlayAlignment();
setupLogoEasterEgg();
setupCompositionGuard();
loadInitialState().catch((error) => {
  setConnectionState("offline");
  toast(error.message, "error");
  renderAll();
});

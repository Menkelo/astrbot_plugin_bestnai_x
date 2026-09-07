import { createCharacterEditor } from "./character-editor.js?v=4.6.32";
import { createImageViewer } from "./image-viewer.js?v=4.6.32";
import { createAssetLibrary } from "./asset-library.js?v=4.6.32";
import {
  createZipBlob,
  decodeDataUrl,
  downloadBlob,
  encodeZipText,
  imageExtension,
  safeZipName,
  uniqueZipPath,
} from "./zip-utils.js?v=4.6.32";
import { ADV_RANGES, effectiveParameter, generationParameterPayload, hasParameterValue } from "./generation-params.js?v=4.6.32";

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
  imageViewerFoldBtn: document.getElementById("imageViewerFoldBtn"),
  imageViewerTags: document.getElementById("imageViewerTags"),
  imageViewerTitle: document.getElementById("imageViewerTitle"),
  imageViewerMeta: document.getElementById("imageViewerMeta"),
  imageViewerNegativeSection: document.getElementById("imageViewerNegativeSection"),
  imageViewerNegative: document.getElementById("imageViewerNegative"),
  imageViewerCharactersSection: document.getElementById("imageViewerCharactersSection"),
  imageViewerCharacters: document.getElementById("imageViewerCharacters"),
  imageViewerNoteSection: document.getElementById("imageViewerNoteSection"),
  imageViewerNote: document.getElementById("imageViewerNote"),
  imageViewerCopyAllBtn: document.getElementById("imageViewerCopyAllBtn"),
  imageViewerDownloadBtn: document.getElementById("imageViewerDownloadBtn"),
  imageViewerSaveBtn: document.getElementById("imageViewerSaveBtn"),
  imageViewerReuseBtn: document.getElementById("imageViewerReuseBtn"),
  imageViewerPrevBtn: document.getElementById("imageViewerPrevBtn"),
  imageViewerNextBtn: document.getElementById("imageViewerNextBtn"),
  imageViewerStage: document.getElementById("imageViewerStage"),
  imageViewerThumbs: document.getElementById("imageViewerThumbs"),
  imageViewerPlaceBtn: document.getElementById("imageViewerPlaceBtn"),
  imageViewerFilterToggle: document.getElementById("imageViewerFilterToggle"),
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

const OPERATION_VISIBLE_LIMIT = 9;
const IMPORTANT_OPERATION_ACTIONS = new Set([
  "记录器已清空",
  "切换项目",
  "创建项目",
  "创建项目失败",
  "删除项目",
  "删除项目失败",
  "撤销",
  "重做",
  "添加节点",
  "删除节点",
  "复制节点",
  "连接节点",
  "删除连线",
  "生成图片",
  "反推并生成",
  "生成完成",
  "生成失败",
  "部分生成失败",
  "反推原图",
  "反推完成",
  "反推失败",
  "自动反推跳过",
  "上传图片",
  "上传图片失败",
  "下载图片",
  "下载图片失败",
  "导入工作区",
  "导入工作区失败",
  "导出工作区",
  "导出工作区失败",
  "清空画布",
  "删除素材",
  "删除素材失败",
  "放入画布",
  "放入画布失败",
  "批量放入画布",
  "批量放入画布失败",
  "收录素材",
  "收录素材失败",
  "压缩素材",
  "压缩素材失败",
]);

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
    defaultSampler: "k_euler_ancestral",
    samplers: [],
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
  promptDefaults: { ratio: "", artist: "", model: "" },
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
  viewerNodeId: "",
  viewerNavItems: [],
  viewerImageDimensions: { width: 0, height: 0 },
  viewerFrameSyncHandle: 0,
  viewerBottomLayoutLock: null,
  viewerTagLookupSequence: 0,
  viewerTagTranslationCache: new Map(),
  // 正向 tags 过滤开关：默认关闭＝完整展示原始 tags；打开＝只看过滤后的内容标签
  viewerShowFilteredTags: false,
  viewerTagsFull: "",
  viewerTagsFiltered: "",
  viewerNodeRef: null,
  viewerInfoSequence: 0,
  imageParamsCache: new Map(),
  savingLibraryAssetIds: new Set(),
  retagRequestSequence: 0,
  retagRequests: new Map(),
};

const MAX_HISTORY = 40;
const PROMPT_MIN_WIDTH = 320;
const PROMPT_MAX_WIDTH = 480;
const PROMPT_MIN_HEIGHT = 430;
const PROMPT_MAX_HEIGHT = 800;
function debugModeEnabled() {
  return !!state.debugEnabled;
}

const LAST_CANVAS_KEY = "bestnaiInfiniteCanvasId";
const PROMPT_DEFAULTS_KEY = "bestnaiInfiniteCanvasPromptDefaults";
const ASSET_RENDER_BATCH = 48;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const uid = (prefix) => `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
// lucide 的 createIcons 扫的是 [data-lucide]，而它生成的 SVG 自己也带这个
// 属性——于是每调用一次，已经转换好的图标都会被原地重建一遍。renderNodes
// 又是整层 replaceChildren，同一个图标在一次渲染里要解析几十次。
// 首次转换后在这里留一份成品，之后直接克隆；克隆体不带 data-lucide，
// 既省掉重复解析，也不会再被后续扫描捡起来重做。
const iconCache = new Map();

function icon(name, className = "") {
  const cached = iconCache.get(name);
  if (cached) {
    const clone = cached.cloneNode(true);
    if (className) clone.classList.add(...className.split(/\s+/).filter(Boolean));
    return clone;
  }
  const element = document.createElement("i");
  element.dataset.lucide = name;
  if (className) element.className = className;
  return element;
}

function cacheRenderedIcons(scope) {
  if (!scope?.querySelectorAll) return;
  scope.querySelectorAll("svg[data-lucide]").forEach((svg) => {
    const name = svg.getAttribute("data-lucide");
    svg.removeAttribute("data-lucide");
    if (!name || iconCache.has(name)) return;
    const template = svg.cloneNode(true);
    // 模板只留 lucide 自己的 class，调用方的自定义 class 由 icon() 再追加，
    // 否则第一个用到该图标的调用点会把它的 class 焊进所有后续克隆里。
    template.setAttribute("class", `lucide lucide-${name}`);
    template.removeAttribute("data-lucide");
    iconCache.set(name, template);
  });
}

function refreshIcons(root = document) {
  if (window.lucide?.createIcons) {
    window.lucide.createIcons({ root, attrs: { "stroke-width": 1.8 } });
  }
  cacheRenderedIcons(root === document ? document.body : root);
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

function isImportantOperation(entry) {
  return entry?.level !== "info" || IMPORTANT_OPERATION_ACTIONS.has(entry?.action);
}

function importantOperationEntries() {
  return state.operationLog.filter(isImportantOperation);
}

function clearOperationLog() {
  state.operationLog = [];
  state.operationSequence = 0;
  persistOperationLog();
  recordOperation("记录器已清空", "新的操作会继续追加");
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
  const expandedViewer = !els.imageViewer.hidden && !els.imageViewer.classList.contains("folded");
  const stage = expandedViewer ? els.imageViewerStage.getBoundingClientRect() : null;
  const width = stage?.width || window.innerWidth;
  const left = stage?.width ? stage.left : 0;
  els.toastRegion.style.left = `${left + width / 2}px`;
  els.toastRegion.style.maxWidth = `${Math.max(0, width - 24)}px`;
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
  alignToastRegion();
  alignDebugBar();
  if (els.assetPanel.classList.contains("open")) {
    alignAssetPanel();
    updateAssetGridMetrics();
  }
  if (!els.projectMenu.hidden) alignProjectMenu();
  scheduleAttachedPanelLayout();
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
  // 预览舞台会随信息栏开合改变宽度；已有通知也要跟随动画和窗口尺寸。
  state.layoutObserver.observe(els.imageViewerStage);
  state.layoutObserver.observe(els.debugBar);
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
      model: node.model || "",
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
  const center = point || suggestedNodeCenter(380);
  const adv = state.promptDefaults;
  return {
    id: uid("prompt"),
    type: "prompt",
    x: center.x - 190,
    y: center.y - 200,
    width: 380,
    height: 430,
    title: "提示词节点",
    prompt: "",
    ratio: adv.ratio || state.config.defaultRatio || "2:3",
    artist: adv.artist,
    // 画幅/画师/模型跟随上一张卡片；张数不跟随（始终 1 张）。
    // 高级参数刻意不跟随：它写进的是 meta.steps 这一层，而优先级是
    // meta.steps > meta.retagSteps > 默认值——跟随值会永久盖住反推读到的
    // 原图参数，出现"读到了 28 步，滑条却是上一张的 20"。新卡片留空，
    // 让滑条按 原图参数 → 默认值（28 / 7 / 0，Variety+ 关）回落。
    model: adv.model || state.config.defaultModel || "nai-diffusion-4-5-full",
    raw: false,
    createdAt: new Date().toISOString(),
    meta: {},
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
    model: String(preferences.model || stored.model || ""),
  };
  const fallbackRatio = state.config.defaultRatio
    || optionValue(state.config.ratios?.[0])
    || "2:3";
  const fallbackModel = state.config.defaultModel || "nai-diffusion-4-5-full";
  state.promptDefaults = {
    ratio: hasOptionValue(state.config.ratios, persisted.ratio) ? persisted.ratio : fallbackRatio,
    artist: normalizedArtistSelection(persisted.artist),
    model: hasOptionValue(state.config.models, persisted.model) ? persisted.model : fallbackModel,
  };
}

function persistCanvasPreferences() {
  if (!bridge || !canvasId) return;
  const payload = {
    lastCanvasId: canvasId,
    ratio: state.promptDefaults.ratio || "",
    artist: state.promptDefaults.artist || "",
    model: state.promptDefaults.model || "",
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
  // 只调整层级，不在 pointerdown 中搬动 DOM，以免丢失焦点或吞掉后续 click。
  const order = new Map(state.nodes.map((item, position) => [item.id, position + 2]));
  for (const current of els.nodeLayer.children) {
    current.style.setProperty("--node-z", String(order.get(current.dataset.nodeId) || 2));
  }
  scheduleSave(800);
}

function renderPromptNode(node) {
  const element = makeNodeShell(node, node.title || "提示词节点");
  element.style.height = `${node.height || 430}px`;
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
  const ratioOptions = [...(state.config.ratios || [])];
  if (/^\d{2,5}x\d{2,5}$/.test(node.ratio || "") && !hasOptionValue(ratioOptions, node.ratio)) {
    ratioOptions.push({ value: node.ratio, label: `${node.ratio.replace("x", "×")}（复用）` });
  }
  const ratioField = makeSelectField("画幅", ratioOptions, node.ratio, (value) => {
    node.ratio = value;
    // 手动选过画幅后，首次链接图片的自动对齐不再生效
    node.meta = { ...(node.meta || {}), ratioManual: true };
    clearDebugTrace(node);
    rememberPromptDefaults({ ratio: value });
    scheduleSave();
    recordOperation("修改画幅", `${node.title || "提示词节点"} · ${value || "默认"}`);
    // 角色预览的画幅来自节点本身；立即重绘才能让竖/横画幅同步更新。
    renderAll();
  });
  const artistOptions = canvasArtistOptions();
  const artistField = makeSelectField("画师", artistOptions, node.artist, (value) => {
    node.artist = value;
    clearDebugTrace(node);
    rememberPromptDefaults({ artist: value });
    scheduleSave();
    recordOperation("修改画师", `${node.title || "提示词节点"} · ${value || "无预设"}`);
  });
  const modelOptions = (state.config.models || []).slice();
  if (!modelOptions.length) {
    modelOptions.push(
      { value: "nai-diffusion-4-5-full", label: "V4.5 Full" },
      { value: "nai-diffusion-5-full", label: "V5 Full" },
    );
  }
  const modelField = makeSelectField(
    "模型",
    modelOptions,
    node.model || state.config.defaultModel,
    (value) => {
      node.model = value;
      rememberPromptDefaults({ model: value });
      clearDebugTrace(node);
      // 重建高级参数卡：Variety+ 是否可用取决于模型。复用同一个构造函数，
      // 可见性、勾选态、摘要三处一次对齐；折叠状态存在 node.meta 里不会丢。
      const staleAdvCard = element.querySelector(".node-attach-stack > .adv-card");
      if (staleAdvCard) {
        const freshAdvCard = makeAdvancedParamsCard(node, element);
        if (freshAdvCard) staleAdvCard.replaceWith(freshAdvCard);
      }
      scheduleSave();
      recordOperation("切换模型", `${node.title || "提示词节点"} · ${value}`);
    },
  );
  const countField = makeSelectField(
    "张数",
    [1, 2, 3, 4].map((n) => ({ value: String(n), label: `${n} 张` })),
    String(clamp(Math.round(Number(node.meta?.count)) || 1, 1, 4)),
    (value) => {
      node.meta = { ...(node.meta || {}), count: clamp(parseInt(value, 10) || 1, 1, 4) };
      scheduleSave();
    },
  );
  // 第一行画幅/画师，第二行模型/张数
  options.append(ratioField, artistField, modelField, countField);

  const footer = document.createElement("div");
  footer.className = "node-footer";
  const rawLabel = document.createElement("label");
  rawLabel.className = "raw-toggle";
  rawLabel.dataset.tooltip = "不追加画师预设和质量词，按你写的内容原样生成；负面提示词仍然生效。中文默认不翻译，需要时用右边的「翻译」单独开启。";
  const raw = document.createElement("input");
  raw.type = "checkbox";
  raw.checked = !!node.raw;

  // 原始提示词模式默认连中文翻译一起关掉。对写中文描述的人来说那等于 raw
  // 不可用，所以给一个只放开翻译的逃生口——画师串和质量词仍然不加。
  const rawTranslateLabel = document.createElement("label");
  rawTranslateLabel.className = "raw-toggle raw-translate";
  rawTranslateLabel.dataset.tooltip = "原始提示词模式下仍然把中文翻译成 NAI tags；画师预设和质量词依旧不会追加。";
  const rawTranslate = document.createElement("input");
  rawTranslate.type = "checkbox";
  rawTranslate.checked = !!node.meta?.rawTranslate;
  rawTranslate.addEventListener("change", () => {
    node.meta = { ...(node.meta || {}), rawTranslate: rawTranslate.checked };
    clearDebugTrace(node);
    scheduleSave();
    recordOperation("切换原始提示词翻译", rawTranslate.checked ? "开启" : "关闭");
  });
  rawTranslate.addEventListener("click", (event) => {
    if (event.detail > 0) rawTranslate.blur();
  });
  rawTranslateLabel.append(rawTranslate, document.createTextNode("翻译"));
  const syncRawTranslate = () => {
    rawTranslateLabel.hidden = !raw.checked;
  };
  syncRawTranslate();

  raw.addEventListener("change", () => {
    node.raw = raw.checked;
    syncRawTranslate();
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
  footer.append(rawLabel, rawTranslateLabel, commands);

  const status = document.createElement("div");
  status.className = `node-status${node.error ? " error" : ""}`;
  status.textContent = node.error?.split("\n\n诊断信息：")[0]
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
  if (node.error) {
    const diagnostic = document.createElement("button");
    diagnostic.type = "button";
    diagnostic.className = "node-diagnostic-copy";
    diagnostic.textContent = "复制诊断信息";
    diagnostic.addEventListener("pointerdown", (event) => event.stopPropagation());
    diagnostic.addEventListener("click", () => copyPlainText(maskOperationSecrets(node.error), "复制诊断信息"));
    body.appendChild(diagnostic);
  }
  // 角色模块常驻在提示词卡片上方；高级参数和原图标签仍挂在下方。
  const advCard = makeAdvancedParamsCard(node, element);
  const retagLayerResult = makeRetagLayerCard(node, sourceImage, element);
  const retagLayerCard = retagLayerResult && "card" in retagLayerResult
    ? retagLayerResult.card
    : retagLayerResult;
  const retagCharacterCard = retagLayerResult?.characterCard || null;
  if (retagCharacterCard) {
    const roleStack = document.createElement("div");
    roleStack.className = "node-role-stack";
    roleStack.appendChild(retagCharacterCard);
    element.appendChild(roleStack);
  }
  if (advCard || retagLayerCard) {
    const stack = document.createElement("div");
    stack.className = "node-attach-stack";
    if (advCard) stack.appendChild(advCard);
    if (retagLayerCard) stack.appendChild(retagLayerCard);
    element.appendChild(stack);
  }
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

function normalizeCharCoordinate(value) {
  if (typeof value === "boolean" || value === null || value === undefined || value === "") {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number <= 1 ? number : null;
}

function normalizeCharCenter(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const x = normalizeCharCoordinate(value.x);
  const y = normalizeCharCoordinate(value.y);
  return x === null || y === null ? null : { x, y };
}

function charPromptCenter(item) {
  if (!item || typeof item !== "object") return null;
  let center = normalizeCharCenter(item.center);
  if (center) return center;
  if (Array.isArray(item.centers)) {
    for (const candidate of item.centers) {
      center = normalizeCharCenter(candidate);
      if (center) return center;
    }
  }
  return normalizeCharCenter({ x: item.x, y: item.y });
}

function firstCharPromptText(item, keys) {
  for (const key of keys) {
    if (typeof item?.[key] === "string" && item[key].trim()) return item[key].trim();
  }
  return "";
}

function normalizeCharPromptEntries(value, { keepEmpty = false } = {}) {
  if (!Array.isArray(value)) return [];
  const result = [];
  for (const item of value.slice(0, MAX_CHAR_PROMPTS)) {
    if (!item || typeof item !== "object") continue;
    const prompt = firstCharPromptText(item, ["prompt", "caption", "char_caption"]).slice(0, 2000);
    if (!prompt && !keepEmpty) continue;
    const entry = {
      prompt,
      negative_prompt: firstCharPromptText(item, ["negative_prompt", "negative", "uc"]).slice(0, 2000),
      position: "",
    };
    const center = charPromptCenter(item);
    if (center) {
      // Metadata-derived positions are only relay compatibility values; the
      // exact center is authoritative and must not be mistaken for a user's
      // explicit grid selection on the next generate request.
      entry.center = center;
    } else {
      const position = String(item.position || "").trim().toUpperCase();
      if (/^[A-E][1-5]$/.test(position)) entry.position = position;
    }
    result.push(entry);
  }
  return result;
}

function normalizeRetagCharIndexes(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(
    value
      .map((item) => Number(item))
      .filter((item) => Number.isInteger(item) && item >= 0 && item < MAX_CHAR_PROMPTS),
  )].sort((left, right) => left - right);
}

function retagCharDisabledIndexes(node) {
  return normalizeRetagCharIndexes(node?.meta?.retagCharDisabled);
}

function retagCharEnabled(node, index) {
  return !retagCharDisabledIndexes(node).includes(index);
}

function activeRetagCharPromptEntries(node) {
  const disabled = new Set(retagCharDisabledIndexes(node));
  const rawEntries = Array.isArray(node?.meta?.retagCharPrompts)
    ? node.meta.retagCharPrompts
    : [];
  return rawEntries
    .filter((_, index) => !disabled.has(index))
    .map((item) => normalizeCharPromptEntries([item])[0])
    .filter(Boolean);
}

function automaticRetagCharLayout(node) {
  const entries = activeRetagCharPromptEntries(node);
  const useCoords = entries.length >= 2;
  return { entries, useCoords, useOrder: !useCoords };
}

function charGridCenter(position) {
  const match = String(position || "").trim().toUpperCase().match(/^([A-E])([1-5])$/);
  if (!match) return null;
  return {
    x: ("ABCDE".indexOf(match[1]) + 0.5) / 5,
    y: (Number(match[2]) - 0.5) / 5,
  };
}

function editableCharCenter(item) {
  return charPromptCenter(item) || charGridCenter(item?.position) || { x: 0.5, y: 0.5 };
}

function cloneCharPromptEntry(item) {
  const center = editableCharCenter(item);
  return {
    prompt: String(item?.prompt || ""),
    negative_prompt: String(item?.negative_prompt || ""),
    position: "",
    center: { x: center.x, y: center.y },
  };
}

function centerDistance(left, right) {
  return Math.hypot(left.x - right.x, left.y - right.y);
}

function randomCharacterCenter(existing) {
  const minimumDistance = 0.16;
  let best = { x: 0.5, y: 0.5 };
  let bestDistance = -1;
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const candidate = {
      x: 0.08 + Math.random() * 0.84,
      y: 0.10 + Math.random() * 0.80,
    };
    const distance = existing.length
      ? Math.min(...existing.map((center) => centerDistance(candidate, center)))
      : Infinity;
    if (distance > bestDistance) {
      best = candidate;
      bestDistance = distance;
    }
    if (distance >= minimumDistance) return candidate;
  }
  return best;
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

// 单条标签的移除清单。分类级「移除」是整类一刀切，这里补的是「同类里只想
// 去掉某几条」——反推出 blue_eyes, closed_eyes 时只划掉后者。
function retagDroppedTags(node) {
  const raw = node?.meta?.retagDropTags;
  if (!Array.isArray(raw)) return [];
  const seen = new Set();
  const result = [];
  raw.forEach((value) => {
    const text = String(value ?? "").trim();
    if (!text) return;
    const key = text.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    result.push(text);
  });
  return result;
}

function isRetagTagDropped(node, tag) {
  const key = String(tag ?? "").trim().toLowerCase();
  return !!key && retagDroppedTags(node).some((value) => value.toLowerCase() === key);
}

function toggleRetagDroppedTag(node, tag) {
  const text = String(tag ?? "").trim();
  if (!text) return false;
  const current = retagDroppedTags(node);
  const key = text.toLowerCase();
  const next = current.filter((value) => value.toLowerCase() !== key);
  const dropped = next.length === current.length;
  if (dropped) next.push(text);
  node.meta = { ...(node.meta || {}), retagDropTags: next };
  return dropped;
}

function collapseRetagLayers() {
  let changed = false;
  state.nodes.forEach((node) => {
    if (node.type !== "prompt") return;
    // 标签图层与高级参数卡都随空白处点击收起
    if (
      node.meta?.retagLayerExpanded === true
      || node.meta?.retagCharacterExpanded === true
      || node.meta?.advParamsExpanded === true
    ) {
      node.meta = {
        ...(node.meta || {}),
        retagLayerExpanded: false,
        retagCharacterExpanded: false,
        advParamsExpanded: false,
      };
      changed = true;
    }
  });
  if (changed) scheduleSave();
  return changed;
}

// 与后端 models/config.py 的 model_supports_variety_boost() 保持一致：
// V5 的官方能力表里没有 skip_cfg_above_sigma，请求清洗会直接把它删掉。
// 既然点了不生效，UI 上就不该摆着这个开关。
function modelSupportsVariety(model) {
  return !String(model || "").toLowerCase().includes("diffusion-5");
}

// 高级参数的取值范围，与后端 MIN/MAX_STEPS、MIN/MAX_SCALE 和 cfg_rescale
// 的钳制口径一一对应。滑条、反推带回的原图参数、缓存复用三处共用这一份：
// 原图 50 步会被后端 _clamp_steps 钳成 28，前端若按更宽的范围原样收下，
// 就会出现滑条卡在 28、数字标签写 50、实际发 28 的四处对不上。
function makeAdvancedParamsCard(node, nodeElement) {
  const card = document.createElement("aside");
  card.className = "retag-layer-card adv-card";
  const hasReusedParams = node.meta?.generationSeed != null || node.meta?.negativePrompt != null;
  card.classList.toggle("has-reused-parameters", hasReusedParams);
  card.dataset.nodeId = node.id;
  card.addEventListener("pointerdown", (event) => {
    // 中键拖动要继续冒泡到画布，让附加卡片区域也能平移画布。
    if (event.button === 1) return;
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
  title.append(icon("sliders-horizontal"), document.createTextNode("高级参数"));
  const summary = document.createElement("span");
  summary.className = "retag-layer-summary";
  const chevron = icon("chevron-down", "retag-layer-chevron");
  toggle.append(title, summary, chevron);
  // 标题按钮只切换展开状态。
  toggle.addEventListener("pointerdown", (event) => {
    if (event.button !== 1) event.stopPropagation();
  });

  const body = document.createElement("div");
  body.className = "retag-layer-body";
  body.hidden = true;

  body.addEventListener("wheel", (event) => {
    if (hasReusedParams && scrollContainerConsumesWheel(body, event)) event.stopPropagation();
  }, { passive: true });

  const effectiveValue = (key, retagKey, fallback) =>
    effectiveParameter(node.meta, key, retagKey, fallback);

  // Variety+ 只对 V4.x 有效。切到 V5 时不清 node.meta.varietyBoost——
  // 那样来回切模型会把用户的设置吃掉；只是藏起来、并且不计入摘要。
  const varietySupported = modelSupportsVariety(node.model || state.config.defaultModel);

  const refreshSummary = () => {
    const parts = [
      `步数 ${effectiveValue("steps", "retagSteps", 28)}`,
      `引导 ${effectiveValue("scale", "retagScale", 7)}`,
      `Rescale ${effectiveValue("cfgRescale", "retagCfgRescale", 0)}`,
    ];
    const sampler = effectiveValue("sampler", "retagSampler", state.config.defaultSampler || "k_euler_ancestral");
    if (sampler) parts.push(String(sampler));
    if (varietySupported && node.meta?.varietyBoost) parts.push("Variety+");
    summary.textContent = parts.join(" · ");
  };

  // 滑条：实时显示生效值；手写值标 • 并可 ↺ 一键回落
  const advSlider = (label, key, retagKey, min, max, step, tooltip, fallback, format) => {
    const field = document.createElement("div");
    field.className = "adv-field";

    const head = document.createElement("div");
    head.className = "adv-field-head";
    const caption = document.createElement("span");
    caption.className = "adv-caption";
    caption.textContent = label;
    // 说明挂在标题两个字上，不挂整个 field：field 包着 ↺ 按钮，两层都带
    // 气泡的话悬停 ↺ 会同时弹出两个（原生 title 时代是后者盖前者，看不出来）。
    if (hasReusedParams) caption.title = tooltip;
    else caption.dataset.tooltip = tooltip;
    caption.tabIndex = 0;
    const value = document.createElement("span");
    value.className = "adv-value";
    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "adv-reset";
    reset.textContent = "↺";
    reset.dataset.tooltip = "清除手动设置，回落原图参数/默认值";
    head.append(caption, value, reset);

    const slider = document.createElement("input");
    slider.type = "range";
    slider.className = "adv-slider";
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(step);

    const paint = () => {
      const effective = effectiveValue(key, retagKey, fallback);
      const manual = hasParameterValue(key, node.meta?.[key]);
      slider.value = String(effective);
      value.textContent = `${format(effective)}${manual ? " •" : ""}`;
      value.classList.toggle("manual", manual);
    };
    slider.addEventListener("input", () => {
      node.meta = { ...(node.meta || {}), [key]: Number(slider.value) };
      paint();
      refreshSummary();
      clearDebugTrace(node);
    });
    slider.addEventListener("change", () => {
      // 不再写入跟随默认：滑条改的是 meta.steps 这一层，把它记成新卡片的
      // 初值会永久盖住反推读到的原图参数。这里只落盘当前节点。
      scheduleSave();
    });
    reset.addEventListener("click", () => {
      if (node.meta && node.meta[key] !== undefined) {
        const { [key]: _dropped, ...meta } = node.meta;
        node.meta = meta;
      }
      paint();
      refreshSummary();
      clearDebugTrace(node);
      scheduleSave();
    });

    paint();
    field.append(head, slider);
    return field;
  };
  // 命中原图内嵌参数时，把"到底沿用了什么"直接写出来。步数/引导/Rescale 的
  // 滑条已经落到原图值上，但采样器和噪声计划没有对应控件，不写出来用户根本
  // 看不出反推有没有把参数带过来。
  const sourceNote = document.createElement("p");
  sourceNote.className = "adv-source-note";
  const sourceParts = [
    ["retagSteps", "步数"],
    ["retagScale", "引导"],
    ["retagCfgRescale", "Rescale"],
    ["retagSampler", "采样器"],
    ["retagNoiseSchedule", "噪声"],
  ]
    .map(([key, label]) => (node.meta?.[key] ? `${label} ${node.meta[key]}` : ""))
    .filter(Boolean);
  sourceNote.textContent = sourceParts.length
    ? `已沿用原图参数：${sourceParts.join(" · ")}`
    : "";
  sourceNote.hidden = !sourceParts.length;
  sourceNote.dataset.tooltip = "反推命中原图内嵌参数时自动沿用；拖动滑条即可覆盖，↺ 回落原图值";

  const advRow = document.createElement("div");
  advRow.className = "adv-row";
  advRow.append(
    advSlider(
      "步数",
      "steps",
      "retagSteps",
      ADV_RANGES.steps.min,
      ADV_RANGES.steps.max,
      1,
      "采样步数：迭代精修次数。低步数出图快适合试构图，过高收益递减；≤28 步 Opus 免费",
      28,
      (v) => String(Math.round(v)),
    ),
    advSlider(
      "引导",
      "scale",
      "retagScale",
      ADV_RANGES.scale.min,
      ADV_RANGES.scale.max,
      0.1,
      "提示词引导强度（Prompt Guidance / CFG）：越高越贴合提示词、细节更锐，过高会过饱和；V4.5/V5 建议 5-7",
      7,
      (v) => v.toFixed(1),
    ),
    advSlider(
      "Rescale",
      "cfgRescale",
      "retagCfgRescale",
      ADV_RANGES.cfgRescale.min,
      ADV_RANGES.cfgRescale.max,
      0.05,
      "CFG Rescale：抑制高引导下的色彩过曝（deepfried 观感），常用 0-0.3",
      0,
      (v) => v.toFixed(2),
    ),
  );
  const varietyLabel = document.createElement("label");
  varietyLabel.className = "raw-toggle adv-variety";
  varietyLabel.hidden = !varietySupported;
  varietyLabel.dataset.tooltip = "Variety+：提升构图与姿态多样性，缓解高引导下出图雷同；默认关闭";
  const variety = document.createElement("input");
  variety.type = "checkbox";
  variety.checked = !!node.meta?.varietyBoost;
  variety.addEventListener("change", () => {
    node.meta = { ...(node.meta || {}), varietyBoost: variety.checked };
    refreshSummary();
    clearDebugTrace(node);
    scheduleSave();
  });
  varietyLabel.append(variety, document.createTextNode("Variety+"));

  const configuredSamplers = Array.isArray(state.config.samplers) ? state.config.samplers.slice() : [];
  const samplerItems = configuredSamplers.length
    ? configuredSamplers
    : [
      "k_euler_ancestral", "k_euler", "k_dpmpp_2s_ancestral",
      "k_dpmpp_2m_sde", "k_dpmpp_2m_sde_exponential",
      "k_dpmpp_2m_sde_karras", "k_dpmpp_sde", "k_dpmpp_sde_karras",
      "ddim", "ddim_v2", "k_lms", "k_heun", "k_dpm_2", "k_dpm_2_ancestral",
    ].map((value) => ({ value, label: value }));
  samplerItems.unshift({ value: "", label: "跟随原图 / 默认" });
  const effectiveSampler = String(
    effectiveValue("sampler", "retagSampler", state.config.defaultSampler || "k_euler_ancestral") || "",
  );
  if (effectiveSampler && !samplerItems.some((item) => String(item.value) === effectiveSampler)) {
    samplerItems.push({ value: effectiveSampler, label: `${effectiveSampler}（原图）` });
  }
  const samplerField = makeSelectField(
    "采样器",
    samplerItems,
    String(node.meta?.sampler || ""),
    (value) => {
      const nextSampler = String(value || "").trim();
      if (nextSampler) {
        node.meta = { ...(node.meta || {}), sampler: nextSampler };
      } else if (node.meta?.sampler) {
        const { sampler: _sampler, ...meta } = node.meta;
        node.meta = meta;
      }
      refreshSummary();
      clearDebugTrace(node);
      scheduleSave();
    },
  );
  samplerField.classList.add("adv-sampler-field");

  const setOpen = (open) => {
    card.classList.toggle("open", open);
    body.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    scheduleAttachedPanelLayout();
  };
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = !card.classList.contains("open");
    node.meta = { ...(node.meta || {}), advParamsExpanded: open };
    setOpen(open);
    scheduleSave();
  });

  body.append(sourceNote, advRow, samplerField, varietyLabel);
  if (hasReusedParams) {
    const reuse = document.createElement("details");
    reuse.className = "reused-parameters";
    reuse.open = true;
    const label = document.createElement("summary");
    label.textContent = "复用参数";
    reuse.appendChild(label);
    const seedLabel = document.createElement("label");
    seedLabel.textContent = "种子（留空则随机）";
    const seed = document.createElement("input");
    seed.className = "generation-seed-text";
    seed.inputMode = "numeric";
    seed.maxLength = 10;
    seed.value = normalizeNaiSeed(node.meta.generationSeed) || "";
    seed.setAttribute("aria-label", "生成种子");
    seed.addEventListener("input", () => {
      node.meta = { ...node.meta, generationSeed: normalizeNaiSeed(seed.value) || 0 };
      scheduleSave();
    });
    seedLabel.appendChild(seed);
    reuse.appendChild(seedLabel);
    if (node.meta.negativePrompt != null) {
      const negativeLabel = document.createElement("label");
      negativeLabel.textContent = "负面提示词";
      const negative = document.createElement("textarea");
      negative.className = "negative-prompt-text";
      negative.rows = 3;
      negative.maxLength = 6000;
      negative.value = node.meta.negativePrompt;
      negative.setAttribute("aria-label", "节点负面提示词");
      negative.addEventListener("input", () => {
        node.meta = { ...node.meta, negativePrompt: negative.value };
        scheduleSave();
      });
      negativeLabel.appendChild(negative);
      reuse.appendChild(negativeLabel);
    }
    const extras = [
      node.meta.noiseSchedule ? `噪声：${node.meta.noiseSchedule}` : "",
      node.meta.ucPreset != null ? `UC：${node.meta.ucPreset}` : "",
      node.meta.imageFormat ? `格式：${node.meta.imageFormat}` : "",
    ].filter(Boolean).join(" · ");
    if (extras) {
      const note = document.createElement("p");
      note.className = "adv-source-note";
      note.textContent = extras;
      reuse.appendChild(note);
    }
    body.appendChild(reuse);
  }
  refreshSummary();
  setOpen(node.meta?.advParamsExpanded === true);
  card.append(toggle, body);
  return card;
}

function scrollContainerConsumesWheel(container, event) {
  if (event.ctrlKey || event.metaKey) return false;
  if (!container || container.scrollHeight <= container.clientHeight + 1) return false;
  const maxScroll = container.scrollHeight - container.clientHeight;
  if (event.deltaY < 0) return container.scrollTop > 0;
  if (event.deltaY > 0) return container.scrollTop < maxScroll - 1;
  return false;
}

function attachedPanelViewportBounds() {
  const viewport = els.viewport.getBoundingClientRect();
  const toolbar = document.querySelector(".topbar")?.getBoundingClientRect();
  const recorder = els.debugBar?.getBoundingClientRect();
  const top = Math.max(viewport.top, toolbar?.bottom || 0) + 12;
  let bottom = Math.min(window.innerHeight, viewport.bottom) - 16;
  if (recorder?.height && !els.debugBar.hidden) bottom = Math.min(bottom, recorder.top - 10);
  return { top, bottom };
}

function fitReusedParametersToViewport(card, body, bounds = attachedPanelViewportBounds()) {
  if (!card?.isConnected || !body || body.hidden) return;
  const scale = Number(state.viewport.scale) || 1;
  const available = bounds.bottom - body.getBoundingClientRect().top;
  // DOM rectangles use screen pixels; max-height belongs to the scaled
  // world. Measure from the body (not the header), then convert once.
  body.style.maxHeight = `${Math.max(100, Math.min(620, available / scale))}px`;
}

let attachedPanelFrame = 0;
let attachedPanelObserver = null;
const PANEL_SCROLL_TARGETS = ".retag-layer-body, .retag-character-editor-popover";

function updateAttachedPanelLayout() {
  if (attachedPanelFrame) cancelAnimationFrame(attachedPanelFrame);
  attachedPanelFrame = 0;
  const bounds = attachedPanelViewportBounds();
  // Tag and character bodies keep their fixed CSS height limit.
  els.nodeLayer.querySelectorAll(".adv-card.has-reused-parameters.open").forEach((card) => {
    fitReusedParametersToViewport(card, card.querySelector(".retag-layer-body"), bounds);
  });
  els.nodeLayer.querySelectorAll(".retag-character-editor-popover:not([hidden])").forEach((editor) => {
    positionCharacterEditor(editor.closest(".retag-character-card"), editor);
  });
}

function scheduleAttachedPanelLayout() {
  if (attachedPanelFrame) return;
  attachedPanelFrame = requestAnimationFrame(updateAttachedPanelLayout);
}

function observeAttachedPanels() {
  if (typeof ResizeObserver === "undefined") return;
  attachedPanelObserver ||= new ResizeObserver(scheduleAttachedPanelLayout);
  attachedPanelObserver.disconnect();
  const targets = new Set();
  els.nodeLayer.querySelectorAll(
    ".node-attach-stack, .node-role-stack, .retag-character-editor-popover",
  ).forEach((element) => {
    targets.add(element);
    targets.add(element.closest(".node"));
  });
  targets.forEach((element) => { if (element) attachedPanelObserver.observe(element); });
}

function panelScrollKey(element) {
  const card = element.closest(".retag-layer-card");
  const kind = element.classList.contains("retag-character-editor-popover")
    ? `editor:${element.querySelector(".retag-character-row.is-active textarea")?.dataset.characterIndex || ""}`
    : card?.classList.contains("adv-card") ? "advanced"
      : card?.classList.contains("retag-character-card") ? "characters" : "tags";
  return `${card?.dataset.nodeId}:${kind}`;
}

function capturePanelScrollPositions() {
  return new Map([...els.nodeLayer.querySelectorAll(PANEL_SCROLL_TARGETS)]
    .filter((element) => !element.hidden)
    .map((element) => [panelScrollKey(element), { top: element.scrollTop, left: element.scrollLeft }]));
}

function restorePanelScrollPositions(positions) {
  els.nodeLayer.querySelectorAll(PANEL_SCROLL_TARGETS).forEach((element) => {
    const position = positions.get(panelScrollKey(element));
    if (!position || element.hidden) return;
    element.scrollTop = position.top;
    element.scrollLeft = position.left;
  });
}

function makeRetagLayerCard(node, sourceImage, nodeElement) {
  const characterCard = makeCharacterCard(node, sourceImage, nodeElement);
  const groups = normalizeRetagTagGroups(node?.meta?.retagTagGroups);
  const tagTranslations = normalizeRetagTagTranslations(node?.meta?.retagTagTranslations);
  const entries = RETAG_LAYER_CATEGORY_ORDER
    .filter((category) => Array.isArray(groups[category]) && groups[category].length)
    .map((category) => [category, groups[category]]);
  const card = document.createElement("aside");
  card.className = "retag-layer-card";
  card.dataset.nodeId = node.id;
  card.addEventListener("pointerdown", (event) => {
    // 中键拖动要继续冒泡到画布，让附加卡片区域也能平移画布。
    if (event.button === 1) return;
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
  title.append(icon("layers-3"), document.createTextNode("原图标签"));
  const summary = document.createElement("span");
  summary.className = "retag-layer-summary";
  const chevron = icon("chevron-down", "retag-layer-chevron");
  toggle.append(title, summary, chevron);

  const body = document.createElement("div");
  body.className = "retag-layer-body";
  body.hidden = true;
  // 原图标签较多、确实出现滚动条时才把滚轮留给自身滚动；内容不足以溢出
  // 时不拦截，让滚轮继续交给画布缩放。这里只阻止冒泡，不 preventDefault，
  // 原生滚动条和触控板惯性滚动都能正常工作。
  body.addEventListener("wheel", (event) => {
    if (scrollContainerConsumesWheel(body, event)) event.stopPropagation();
  }, { passive: true });
  const help = document.createElement("p");
  help.className = "retag-layer-help";
  help.textContent = "自动按改图规则覆盖同类原图标签；锁定会保留原图分类；移除只删除原图标签，手写同类标签仍可加入。点单条标签可单独划掉它。";
  body.appendChild(help);

  const refreshSummary = () => {
    const lists = retagLayerCategoryLists(node);
    const parts = [`${entries.length} 类`];
    if (lists.preserve.length) parts.push(`锁定 ${lists.preserve.length}`);
    if (lists.drop.length) parts.push(`移除 ${lists.drop.length}`);
    const droppedTags = retagDroppedTags(node).length;
    if (droppedTags) parts.push(`划掉 ${droppedTags} 条`);
    summary.textContent = parts.join(" · ");

  };



  const tools = document.createElement("div");
  tools.className = "retag-layer-tools";
  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "retag-layer-tool";
  copyButton.textContent = "复制全部";
  copyButton.title = "复制未被划掉的原图标签（逗号分隔）";
  copyButton.addEventListener("click", (event) => {
    event.stopPropagation();
    const text = entries
      .flatMap(([, categoryTags]) => categoryTags)
      .filter((tag) => !isRetagTagDropped(node, tag))
      .join(", ");
    copyPlainText(text, "复制原图标签");
  });
  const restoreButton = document.createElement("button");
  restoreButton.type = "button";
  restoreButton.className = "retag-layer-tool";
  restoreButton.textContent = "恢复划掉";
  restoreButton.title = "取消所有单条标签的移除标记";
  restoreButton.addEventListener("click", (event) => {
    event.stopPropagation();
    if (!retagDroppedTags(node).length) return;
    pushHistory();
    node.meta = { ...(node.meta || {}), retagDropTags: [] };
    clearDebugTrace(node);
    scheduleSave();
    renderNodes();
  });
  tools.append(copyButton, restoreButton);
  body.appendChild(tools);

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
      // 用 button 而不是 code：这是可操作元素，键盘也要能到达
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "retag-layer-tag";
      const display = bilingualRetagTagText(tag, tagTranslations);
      chip.textContent = display;
      const syncChip = () => {
        const dropped = isRetagTagDropped(node, tag);
        chip.classList.toggle("is-dropped", dropped);
        chip.setAttribute("aria-pressed", String(dropped));
        chip.title = dropped
          ? `${display}\n已移除，点击恢复`
          : `${display}\n点击移除这一条原图标签`;
      };
      syncChip();
      chip.addEventListener("click", (event) => {
        event.stopPropagation();
        pushHistory();
        // 存原始标签而不是双语显示文本，后端要按它比对
        toggleRetagDroppedTag(node, tag);
        syncChip();
        refreshSummary();
        clearDebugTrace(node);
        scheduleSave();
      });
      tagList.appendChild(chip);
    });
    row.append(rowHead, tagList);
    body.appendChild(row);
  });

  const setOpen = (open) => {
    card.classList.toggle("open", open);
    body.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    scheduleAttachedPanelLayout();
  };
  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = !card.classList.contains("open");
    node.meta = { ...(node.meta || {}), retagLayerExpanded: open };
    setOpen(open);
    scheduleSave();
  });
  refreshSummary();
  setOpen(node.meta?.retagLayerExpanded === true);
  card.append(toggle, body);
  refreshSummary();
  return { card: entries.length ? card : null, characterCard };
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
  head.textContent = "操作记录";
  section.appendChild(head);

  const list = document.createElement("div");
  list.className = "operation-log-list";
  const entries = importantOperationEntries().slice(-OPERATION_VISIBLE_LIMIT).reverse();
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
  scheduleAttachedPanelLayout();
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
  const latest = [...state.operationLog].reverse().find(isImportantOperation);
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

// 自定义下拉。原生 select 展开后的列表由系统绘制，样式化不了，也不跟随
// 画布缩放。这里用触发按钮 + 单例浮层替掉它。
//
// 浮层做成全局单例而不是每个字段一份：renderNodes 每次都整层重建，节点一多
// 就是几十份浮层 DOM 白白重建。浮层挂在 body 上用 fixed 定位，这样不受节点
// 的 transform / overflow 影响。
const selectMenu = {
  element: null,
  trigger: null,
  items: [],
  activeIndex: -1,
  onPick: null,
};

function ensureSelectMenu() {
  if (selectMenu.element) return selectMenu.element;
  const menu = document.createElement("div");
  menu.className = "node-select-menu";
  menu.id = "nodeSelectMenu";
  menu.setAttribute("role", "listbox");
  menu.hidden = true;
  menu.addEventListener("pointerdown", (event) => event.stopPropagation());
  document.body.appendChild(menu);
  selectMenu.element = menu;
  return menu;
}

function selectMenuOpen() {
  return !!selectMenu.element && !selectMenu.element.hidden;
}

function closeSelectMenu() {
  if (!selectMenuOpen()) return;
  selectMenu.element.hidden = true;
  selectMenu.element.replaceChildren();
  selectMenu.trigger?.setAttribute("aria-expanded", "false");
  selectMenu.trigger?.removeAttribute("aria-activedescendant");
  selectMenu.trigger?.classList.remove("open");
  selectMenu.trigger = null;
  selectMenu.items = [];
  selectMenu.activeIndex = -1;
  selectMenu.onPick = null;
}

function highlightSelectMenu(index) {
  const options = [...selectMenu.element.children];
  if (!options.length) return;
  const next = ((Number(index) || 0) % options.length + options.length) % options.length;
  selectMenu.activeIndex = next;
  options.forEach((option, i) => option.classList.toggle("active", i === next));
  // 不用 scrollIntoView：它可能连带滚动页面/画布，打开长画师列表时会出现
  // 瞬间“弹一下”。只调整浮层自己的 scrollTop，避免任何外部布局跳动。
  const option = options[next];
  const optionTop = option.offsetTop;
  const optionBottom = optionTop + option.offsetHeight;
  const visibleTop = selectMenu.element.scrollTop;
  const visibleBottom = visibleTop + selectMenu.element.clientHeight;
  // 鼠标预选时，部分露出的选项不要立刻把整层菜单“弹”一下；只有选项
  // 完全跑出可视区域后才滚动，避免长画师列表跟着指针不断跳动。
  if (optionBottom <= visibleTop) {
    selectMenu.element.scrollTop = optionTop;
  } else if (optionTop >= visibleBottom) {
    selectMenu.element.scrollTop = optionBottom - selectMenu.element.clientHeight;
  }
  selectMenu.trigger?.setAttribute("aria-activedescendant", options[next].id);
}

function placeSelectMenu(trigger) {
  const menu = selectMenu.element;
  const rect = trigger.getBoundingClientRect();
  if (!rect.width || !rect.height || !trigger.isConnected) {
    closeSelectMenu();
    return;
  }
  // 浮层挂在 body 上，脱离 world 的 transform；从当前提示词卡片的实际
  // 渲染尺寸计算比例，让浮层跟随卡片本身，而不是依赖全局画布缩放状态。
  const card = trigger.closest(".node");
  const cardRect = card?.getBoundingClientRect?.();
  const cardScaleX = cardRect?.width && card?.offsetWidth
    ? cardRect.width / card.offsetWidth
    : 1;
  const cardScaleY = cardRect?.height && card?.offsetHeight
    ? cardRect.height / card.offsetHeight
    : cardScaleX;
  const scale = clamp((cardScaleX + cardScaleY) / 2, 0.1, 4);
  // 宽度严格跟随当前字段；不再加屏幕/浮层最小宽度，避免缩小画布后菜单
  // 比对应的画幅/画师/模型/张数字段宽出一大截并覆盖旁边内容。
  const width = Math.max(rect.width / scale, 1);
  menu.style.width = `${width}px`;
  menu.style.transformOrigin = "top left";
  menu.style.transform = `scale(${scale})`;
  const visualWidth = width * scale;
  const maxLeft = Math.max(12, window.innerWidth - visualWidth - 12);
  menu.style.left = `${Math.max(12, Math.min(rect.left, maxLeft))}px`;
  // 先量高度再决定往下还是往上开
  const height = menu.getBoundingClientRect().height;
  const below = window.innerHeight - rect.bottom;
  menu.style.top = below < height + 16 && rect.top > height + 16
    ? `${rect.top - height - 6}px`
    : `${rect.bottom + 6}px`;
}

function openSelectMenu(trigger, items, value, onPick) {
  const menu = ensureSelectMenu();
  closeSelectMenu();
  selectMenu.trigger = trigger;
  selectMenu.items = items;
  selectMenu.onPick = onPick;

  const options = items.map((item, index) => {
    const option = document.createElement("button");
    option.type = "button";
    option.id = `nodeSelectOption_${index}`;
    option.className = "node-select-option";
    option.tabIndex = -1;
    option.setAttribute("role", "option");
    const selected = String(item.value) === String(value);
    option.setAttribute("aria-selected", String(selected));
    option.classList.toggle("selected", selected);
    const text = document.createElement("span");
    text.textContent = item.label;
    option.append(text);
    if (selected) option.append(icon("check", "node-select-check"));
    option.addEventListener("click", () => {
      const pick = selectMenu.onPick;
      // 原生 select 会立即把当前值显示在控件里；自定义按钮也要在回调
      // 触发重绘之前同步更新，否则用户会看到旧选项停留在按钮上。
      if (selectMenu.trigger) {
        selectMenu.trigger.textContent = item.label;
        selectMenu.trigger.setAttribute("aria-activedescendant", option.id);
      }
      closeSelectMenu();
      pick?.(item.value);
    });
    option.addEventListener("pointerenter", () => highlightSelectMenu(index));
    return option;
  });
  menu.replaceChildren(...options);
  menu.hidden = false;
  refreshIcons(menu);
  trigger.setAttribute("aria-expanded", "true");
  trigger.classList.add("open");
  placeSelectMenu(trigger);
  const selectedIndex = items.findIndex((item) => String(item.value) === String(value));
  highlightSelectMenu(selectedIndex < 0 ? 0 : selectedIndex);
}

function makeSelectField(label, items, value, onChange) {
  const field = document.createElement("div");
  field.className = "field-label";
  const caption = document.createElement("span");
  caption.textContent = label;

  const options = (items || []).map((item) => ({
    value: String(item.value ?? ""),
    label: String(item.label ?? ""),
  }));
  let currentValue = String(value || "");
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "node-select";
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-controls", "nodeSelectMenu");
  trigger.setAttribute("aria-expanded", "false");
  const current = options.find((item) => item.value === String(value || ""));
  trigger.textContent = current?.label || options[0]?.label || "";

  // 下拉控件独立处理指针事件，不触发节点选择。
  trigger.addEventListener("pointerdown", (event) => event.stopPropagation());
  // 鼠标打开时不抢焦点，避免按钮的默认按下/焦点反馈造成瞬时跳变；键盘
  // Tab 进入时仍然保留 focus-visible 样式和完整键盘操作。
  trigger.addEventListener("mousedown", (event) => {
    if (event.button === 0) event.preventDefault();
  });
  trigger.addEventListener("click", (event) => {
    event.stopPropagation();
    if (selectMenu.trigger === trigger) {
      closeSelectMenu();
      return;
    }
    openSelectMenu(trigger, options, currentValue, (nextValue) => {
      currentValue = String(nextValue);
      onChange(nextValue);
    });
  });
  trigger.addEventListener("keydown", (event) => {
    const isOpen = selectMenu.trigger === trigger;
    if (event.key === "Escape" && isOpen) {
      event.preventDefault();
      closeSelectMenu();
      return;
    }
    if (event.key === "Tab" && isOpen) {
      closeSelectMenu();
      return;
    }
    if (isOpen) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const delta = event.key === "ArrowDown" ? 1 : -1;
        highlightSelectMenu(selectMenu.activeIndex + delta);
        return;
      }
      if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        highlightSelectMenu(event.key === "Home" ? 0 : options.length - 1);
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        const item = selectMenu.items[selectMenu.activeIndex];
        const pick = selectMenu.onPick;
        if (item) {
          trigger.textContent = item.label;
          currentValue = item.value;
          closeSelectMenu();
          pick?.(item.value);
        }
      }
      return;
    }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    openSelectMenu(trigger, options, currentValue, (nextValue) => {
      currentValue = String(nextValue);
      onChange(nextValue);
    });
    if (event.key === "ArrowUp") highlightSelectMenu(selectMenu.activeIndex - 1);
  });

  field.append(caption, trigger);
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
  } else if (node.meta?.raw) {
    // 与画师角标互斥：raw 不追加画师预设，服务端也就不会回 artist。
    // 沿用同一套样式——两者同属"这张图用了什么"的标注，不该长得不一样；
    // image-raw-badge 只作语义标记，不覆盖任何视觉属性。
    // 不挂 title——这类角标是 pointer-events: none，原生提示根本触发不了。
    const rawBadge = document.createElement("span");
    rawBadge.className = "image-artist-badge image-raw-badge";
    rawBadge.textContent = "原始提示词";
    frame.appendChild(rawBadge);
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
const EDITABLE_FIELD_CLASSES = ["prompt-text", "note-text", "retag-character-text", "negative-prompt-text", "generation-seed-text"];

function captureEditingFocus() {
  const active = document.activeElement;
  const host = active?.closest?.("[data-node-id]");
  if (!host) return null;
  const field = EDITABLE_FIELD_CLASSES.find((name) => active.classList?.contains(name));
  if (!field) return null;
  return {
    nodeId: host.dataset.nodeId,
    field,
    characterIndex: active.dataset.characterIndex,
    characterField: active.dataset.characterField,
    start: active.selectionStart,
    end: active.selectionEnd,
    scrollTop: active.scrollTop,
  };
}

function restoreEditingFocus(snapshot) {
  if (!snapshot?.nodeId) return;
  const host = els.nodeLayer.querySelector(`[data-node-id="${CSS.escape(snapshot.nodeId)}"]`);
  const selector = snapshot.field === "retag-character-text"
    ? `.retag-character-text[data-character-index="${CSS.escape(snapshot.characterIndex)}"][data-character-field="${CSS.escape(snapshot.characterField)}"]`
    : `.${snapshot.field}`;
  const field = host?.querySelector(selector);
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
  // 下拉浮层挂在 body 上，触发器却属于即将被 replaceChildren 移除的节点；
  // 先收起，避免浮层残留并继续回调一枚游离的旧节点。
  closeSelectMenu();
  const editing = captureEditingFocus();
  const panelScroll = capturePanelScrollPositions();
  els.nodeLayer.replaceChildren();
  state.nodes.forEach((node, index) => {
    let element;
    if (node.type === "prompt") element = renderPromptNode(node);
    else if (node.type === "image") element = renderImageNode(node);
    else element = renderNoteNode(node);
    element.style.setProperty("--node-z", String(index + 2));
    els.nodeLayer.appendChild(element);
  });
  els.empty.classList.toggle("hidden", state.nodes.length > 0);
  refreshIcons(els.nodeLayer);
  updateAttachedPanelLayout();
  restorePanelScrollPositions(panelScroll);
  restoreEditingFocus(editing);
  observeAttachedPanels();
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
    node.width = clamp(Number(node.width) || PROMPT_MIN_WIDTH, PROMPT_MIN_WIDTH, PROMPT_MAX_WIDTH);
    node.height = clamp(Number(node.height) || PROMPT_MIN_HEIGHT, PROMPT_MIN_HEIGHT, PROMPT_MAX_HEIGHT);
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

function limitPromptResizeWidth(element, requestedWidth, minWidth = PROMPT_MIN_WIDTH) {
  if (!element) return requestedWidth;
  const roleCard = element.querySelector(".node-role-stack .retag-character-card");
  if (!roleCard || !roleCard.classList.contains("open")) return requestedWidth;
  const boardRect = els.viewport.getBoundingClientRect();
  const safeTop = boardRect.top + 8;
  const nodeRect = element.getBoundingClientRect();
  const maxByViewport = Math.floor(
    Math.max(minWidth, (nodeRect.top - safeTop) / state.viewport.scale - 24),
  );
  return Math.min(requestedWidth, maxByViewport);
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
  // 平移/缩放会改变触发器的 fixed 坐标；让用户重新点击打开，避免菜单漂在
  // 旧位置，也避免它盖住正在进行的画布手势。
  closeSelectMenu();
  resetNativeCanvasScroll();
  const { x, y, scale } = state.viewport;
  els.world.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  updateAttachedPanelLayout();
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
    updateAttachedPanelLayout();
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

// 指针手势进行中推迟整体重渲染：renderNodes 会重建节点元素，
// 拖动/缩放持有的旧引用会变成游离节点，手势看起来就"中断"了。
let gestureLockCount = 0;

function beginGestureLock() {
  gestureLockCount += 1;
}

function endGestureLock() {
  gestureLockCount = Math.max(0, gestureLockCount - 1);
  if (gestureLockCount === 0 && state.renderPending && !state.composing) {
    renderAll();
  }
}

function gesturesLocked() {
  return gestureLockCount > 0;
}

function renderAll() {
  // 中文/日文输入法组字期间重建 DOM 会直接把未上屏的内容打断，
  // 光标恢复也救不回来；指针手势同理。两者都把渲染推迟到结束。
  if (state.composing || gesturesLocked()) {
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
    beginGestureLock();

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
      endGestureLock();
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
      width: node.width || element.offsetWidth || (node.type === "prompt" ? 380 : 260),
      height: node.height || element.offsetHeight || (node.type === "prompt" ? 360 : 232),
    };
    const minimumHeight = Math.max(
      node.type === "prompt" ? PROMPT_MIN_HEIGHT : 180,
      parseFloat(getComputedStyle(element).minHeight) || 0,
    );
    let moved = false;
    beginGestureLock();
    const move = (moveEvent) => {
      const dx = (moveEvent.clientX - start.x) / state.viewport.scale;
      const dy = (moveEvent.clientY - start.y) / state.viewport.scale;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 2) return;
      if (!moved) {
        moved = true;
        pushHistory();
      }
      let nextWidth = clamp(
        Math.round(start.width + dx),
        node.type === "prompt" ? PROMPT_MIN_WIDTH : 220,
        node.type === "prompt" ? PROMPT_MAX_WIDTH : 640,
      );
      if (node.type === "prompt") nextWidth = limitPromptResizeWidth(element, nextWidth);
      node.width = nextWidth;
      node.height = clamp(
        Math.round(start.height + dy),
        minimumHeight,
        node.type === "prompt" ? PROMPT_MAX_HEIGHT : 800,
      );
      element.style.width = `${node.width}px`;
      element.style.height = `${node.height}px`;
      scheduleCanvasProjection();
    };
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      endGestureLock();
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
    beginGestureLock();
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
      endGestureLock();
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
  // \u4e0e\u540e\u7aef `not raw_mode or raw_translate` \u4e00\u81f4\u3002\u5355\u72ec\u52fe\u4e86\u7ffb\u8bd1\u65f6\u72b6\u6001\u6587\u6848\u4e5f\u8981
  // \u8ddf\u7740\u8d70\u7ffb\u8bd1\u5206\u652f\uff0c\u5426\u5219\u754c\u9762\u663e\u793a"\u6b63\u5728\u751f\u6210\u56fe\u7247"\u800c\u540e\u53f0\u5176\u5b9e\u5728\u7b49\u7ffb\u8bd1\u63a5\u53e3\u3002
  const rawTranslateOn = !!node.raw && !!node.meta?.rawTranslate;
  const translationSource = (node.raw && !rawTranslateOn)
    ? ""
    : (retagged ? basePrompt : workingPrompt);
  const willTranslate = (!node.raw || rawTranslateOn)
    && /[\u4e00-\u9fff]/.test(translationSource);
  const canReuseTranslation = willTranslate
    && node.meta?.translationSource === translationSource
    && !!node.meta?.translationResult;
  node.status = "generating";
  node.error = "";
  node.statusText = willTranslate
    ? (canReuseTranslation
      ? "正在复用英文 tags 并生成图片…"
      : "正在翻译并生成图片…")
    : "正在生成图片…";
  recordOperation(retagged ? "反推并生成" : "生成图片", node.title || "提示词节点");
  renderAll();
  try {
    const retagLayerCategories = retagged
      ? retagLayerCategoryLists(node)
      : { preserve: [], drop: [] };
    const totalCount = clamp(Math.round(Number(node.meta?.count)) || 1, 1, 4);
    const buildPayload = (callSeed) => {
      const characterLayout = automaticRetagCharLayout(node);
      return {
        prompt: workingPrompt,
        model: node.model || state.config.defaultModel || "",
        // 优先级：节点高级参数卡 > 反推命中的原图参数 > 插件默认
        ...generationParameterPayload(node.meta),
        varietyPlus: !!node.meta?.varietyBoost,
        retagPrompt: (node.raw && node.meta?.retagRawPrompt)
          ? String(node.meta.retagRawPrompt).trim()
          : requestRetagPrompt,
        retagCharacter: retagged ? String(node.meta?.retagCharacter || "").trim() : "",
        retagSeries: retagged ? String(node.meta?.retagSeries || "").trim() : "",
        ratio: node.ratio,
        artist: node.artist,
        retagPreserveCategories: retagLayerCategories.preserve,
        retagDropCategories: retagLayerCategories.drop,
        retagDropTags: retagDroppedTags(node),
        raw: !!node.raw,
        // 只有 raw 打开时这个开关才有意义，关掉 raw 就不该把它带出去
        rawTranslate: rawTranslateOn,
        translationSource,
        cachedTranslationSource: node.meta?.translationSource || "",
        cachedTranslation: node.meta?.translationResult || "",
        cachedTranslationCharacter: node.meta?.translationCharacter || "",
        cachedTranslationSeries: node.meta?.translationSeries || "",
        debug: debugModeEnabled(),
        retagCharPrompts: characterLayout.entries,
        retagUseCoords: characterLayout.useCoords,
        retagUseOrder: characterLayout.useOrder,
        // 原图自带种子时沿用它，配合原图 prompt 才能真正还原这张图
        // A seed collected from an image belongs to the retag flow.  If the
        // source connection was removed, a plain prompt generation must not
        // silently inherit that old seed.
        seed: callSeed,
      };
    };
    const baseStatus = willTranslate
      ? (canReuseTranslation
        ? "正在复用英文 tags 并生成图片"
        : "正在翻译并生成图片")
      : "正在生成图片";
    const createdIds = [];
    let gridBase = null;
    let lastDebug = null;
    let lastMeta = null;
    let failures = 0;
    let historyPushed = false;

    for (let index = 0; index < totalCount; index += 1) {
      // 多张时首张沿用反推种子保证可复现，其余随机避免重复
      const callSeed = index === 0
        ? normalizeNaiSeed(node.meta?.generationSeed) || (retagged ? reusableRetagSeed(node) : undefined)
        : undefined;
      if (totalCount > 1) {
        node.statusText = `${baseStatus}… (${index + 1}/${totalCount})`;
        renderAll();
      }

      let result;
      try {
        result = await bridge.apiPost("canvas/generate", buildPayload(callSeed));
      } catch (error) {
        failures += 1;
        if (!createdIds.length) throw error;
        recordOperation("部分生成失败", error.message || "生成失败", "warning");
        break;
      }
      const assets = Array.isArray(result?.assets) ? result.assets : [];
      if (!assets.length) {
        failures += 1;
        if (!createdIds.length) throw new Error("服务未返回图片");
        break;
      }
      lastDebug = result.meta?.debug;
      lastMeta = result.meta;
      assets.forEach((asset) => {
        const sourceWidth = asset.width || result.meta?.width;
        const sourceHeight = asset.height || result.meta?.height;
        const imageNodeWidth = fittedImageNodeWidth(sourceWidth, sourceHeight);
        const imageNodeHeight = estimatedImageNodeHeight(
          imageNodeWidth,
          sourceWidth,
          sourceHeight,
        );
        let position;
        if (totalCount > 1) {
          // 两列网格排布：4 张正好凑成 2×2 四方格
          if (!gridBase) {
            gridBase = findNextGeneratedPosition(node, imageNodeWidth, imageNodeHeight);
          }
          const slot = createdIds.length;
          position = {
            x: gridBase.x + (slot % 2) * (imageNodeWidth + 48),
            y: gridBase.y + Math.floor(slot / 2) * (imageNodeHeight + 48),
          };
        } else {
          position = findNextGeneratedPosition(node, imageNodeWidth, imageNodeHeight);
        }
        if (!historyPushed) {
          pushHistory();
          historyPushed = true;
        }
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
            // 出图后要能一眼看出这张是不是原始提示词生成的。raw 不追加画师，
            // 服务端也就不会回 artist，右上角正好空着可以放这个角标。
            raw: !!node.raw,
            width: sourceWidth,
            height: sourceHeight,
            finalPrompt: result.meta?.finalPrompt || "",
            seed: normalizeNaiSeed(result.meta?.seed),
            steps: result.meta?.steps || 0,
            scale: result.meta?.scale || 0,
            ...imageGenerationMeta(result.meta),
          },
        };
        state.nodes.push(imageNode);
        state.connections.push({ source: node.id, target: imageNode.id });
        createdIds.push(imageNode.id);
      });
    }

    if (!createdIds.length) throw new Error("服务未返回图片");
    node.meta = {
      ...(node.meta || {}),
      translatedPrompt: lastMeta?.translatedPrompt || requestRetagPrompt || "",
      translationSource: lastMeta?.translationSource || "",
      translationResult: lastMeta?.translationResult || "",
      translationCharacter: lastMeta?.translationCharacter || "",
      translationSeries: lastMeta?.translationSeries || "",
    };
    recordRunDebug(node, "generate", lastDebug);
    setSelection(createdIds, createdIds[createdIds.length - 1]);
    node.statusText = retagged
      ? `反推完成 · 已合并提示词并生成 ${createdIds.length} 张图片`
      : `已生成 ${createdIds.length} 张图片`;
    toast(failures ? `已生成 ${createdIds.length} 张，${failures} 张失败` : "生成完成");
    recordOperation("生成完成", `已生成 ${createdIds.length} 张图片`, "success");
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
    retagCharacterExpanded: _retagCharacterExpanded,
    advParamsExpanded: _advParamsExpanded,
    retagSteps: _retagSteps,
    retagScale: _retagScale,
    retagCfgRescale: _retagCfgRescale,
    retagNoiseSchedule: _retagNoiseSchedule,
    retagSampler: _retagSampler,
    // 划掉的标签是针对某一张原图的；换图后再套用只会误伤新图的标签。
    // 落盘之后它不会随刷新自动消失，所以断开时必须显式清掉。
    retagDropTags: _retagDropTags,
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

// 超范围时截取到边界，而不是当成"没这个值"：反推带回原图 50 步应该落到上限
// 28，不该退化成未设置再回落默认值；引导同理（原图 15 该截到 10，而不是变回
// 默认 7）。缺失/非数字/非正数返回 0——下游一律用 falsy 判定"未设置"，
// Rescale 的合法 0 值走这条路的结果也是 0。
function clampMetaNumber(value, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return 0;
  return Math.min(Math.max(number, min), max);
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
  // Older workspaces only persisted the control-stripped prompt. In raw mode
  // that cache is incomplete, so refresh once to recover the full metadata
  // prompt before generating.
  if (node.raw && meta.retagFromMetadata && !String(meta.retagRawPrompt || "").trim()) {
    return null;
  }
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
    rawPrompt: String(meta.retagRawPrompt || "").trim(),
    ratio: String(meta.retagRatio || "").trim(),
    character: String(meta.retagCharacter || "").trim(),
    series: String(meta.retagSeries || "").trim(),
    seed: cachedSeed,
    fromMetadata: !!meta.retagFromMetadata,
    fromCanvasCache: !!meta.retagFromCanvasCache,
    tagGroups,
    tagTranslations: normalizeRetagTagTranslations(meta.retagTagTranslations),
    charPrompts: normalizeCharPromptEntries(meta.retagCharPrompts),
    steps: clampMetaNumber(meta.retagSteps, ADV_RANGES.steps.min, ADV_RANGES.steps.max),
    scale: clampMetaNumber(meta.retagScale, ADV_RANGES.scale.min, ADV_RANGES.scale.max),
    cfgRescale: clampMetaNumber(
      meta.retagCfgRescale,
      ADV_RANGES.cfgRescale.min,
      ADV_RANGES.cfgRescale.max,
    ),
    noiseSchedule: String(meta.retagNoiseSchedule || "").trim(),
    sampler: String(meta.retagSampler || "").trim(),
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
    const incomingCharPrompts = normalizeCharPromptEntries(result?.charPrompts);
    const existingCharPrompts = normalizeCharPromptEntries(
      node.meta?.retagCharPrompts,
      { keepEmpty: true },
    );
    const nextCharPrompts = incomingCharPrompts.length
      ? incomingCharPrompts
      : existingCharPrompts;
    const originalCharPrompts = Array.isArray(node.meta?.retagCharPromptsOriginal)
      ? normalizeCharPromptEntries(node.meta.retagCharPromptsOriginal)
      : incomingCharPrompts;

    pushHistory();
    node.meta = {
      ...(node.meta || {}),
      retagBasePrompt: basePrompt,
      retagPrompt,
      // 元数据里的完整 prompt 供 raw 模式复用，普通模式仍使用清理版。
      retagRawPrompt: String(result?.rawPrompt || "").trim(),
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
      retagCharPrompts: nextCharPrompts,
      retagCharPromptsOriginal: originalCharPrompts,
      retagCharDisabled: normalizeRetagCharIndexes(node.meta?.retagCharDisabled),
      // 采样参数直接来自对原图文件的元数据解析，和 prompt 从哪来无关。
      // fromMetadata 只说明"prompt 是内嵌的"，命中画布缓存时它是 false，
      // 可图片里的 steps/sampler 依然有效——拿它当门禁等于整批丢掉。
      // 走视觉模型的分支后端根本不返回这几个字段，取到 undefined 自然归零。
      retagSteps: clampMetaNumber(result?.steps, ADV_RANGES.steps.min, ADV_RANGES.steps.max),
      retagScale: clampMetaNumber(result?.scale, ADV_RANGES.scale.min, ADV_RANGES.scale.max),
      retagCfgRescale: clampMetaNumber(
        result?.cfgRescale,
        ADV_RANGES.cfgRescale.min,
        ADV_RANGES.cfgRescale.max,
      ),
      retagNoiseSchedule: String(result?.noiseSchedule || "").trim(),
      retagSampler: String(result?.sampler || "").trim(),
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
    // 反推刚往 node.meta 里写完原图采样参数，不重绘的话高级参数卡不会重建，
    // 滑条就一直停在旧值上——数据到了、界面没动。开头和 catch 分支都有重绘，
    // 唯独这里漏了；自动反推是 fire-and-forget，也没有调用方兜底。
    renderAll();
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
    const result = await bridge.apiGet("canvas/asset", { id: node.assetId, preview: 1 });
    node.dataUrl = result.dataUrl;
    node.meta = {
      ...(node.meta || {}),
      width: node.meta?.width || result.width,
      height: node.meta?.height || result.height,
      sourceFormat: result.format || node.meta?.sourceFormat,
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
      // 手势进行中不替换元素：被拖动/缩放的正持有这个节点，
      // 推迟到松手后的 renderPending 统一刷新
      if (gesturesLocked()) {
        state.renderPending = true;
      } else {
        const replacement = renderImageNode(node);
        current.replaceWith(replacement);
        requestAnimationFrame(() => {
          renderConnections();
        });
      }
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
    const extension = node.meta?.sourceFormat || (mime === "jpeg" ? "jpg" : mime);
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

function isSupportedImageFile(file) {
  const type = String(file?.type || "").toLowerCase();
  if (type.startsWith("image/")) return true;
  // Desktop drag-and-drop providers occasionally omit MIME metadata.  The
  // backend still verifies the actual bytes, so an extension fallback keeps
  // those legitimate image drops usable without weakening server validation.
  return /\.(?:png|jpe?g|jfif|webp|gif|bmp|tiff?|ico|avif)$/i.test(String(file?.name || ""));
}

async function uploadFiles(files, point = worldCenter()) {
  const images = [...files].filter(isSupportedImageFile);
  if (!images.length) {
    toast("请选择 PNG、JPEG、WebP、GIF、BMP、TIFF、ICO 或 AVIF 图片", "error");
    return;
  }
  for (let index = 0; index < images.length; index += 1) {
    try {
      const asset = await bridge.upload("canvas/upload", images[index]);
      const importedAt = new Date();
      const importedTitle = `导入图片 ${importedAt.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      }).replace(/\//g, "-")}`;
      const nodeWidth = fittedImageNodeWidth(asset.width, asset.height);
      const nodeHeight = estimatedImageNodeHeight(nodeWidth, asset.width, asset.height);
      const node = {
        id: uid("image"),
        type: "image",
        x: point.x + index * 34 - nodeWidth / 2,
        y: point.y + index * 34 - nodeHeight / 2,
        width: nodeWidth,
        title: importedTitle,
        assetId: asset.id,
        dataUrl: asset.dataUrl,
        createdAt: new Date().toISOString(),
        meta: {
          prompt: images[index].name,
          sourceFilename: images[index].name,
          sourceFormat: asset.format,
          width: asset.width,
          height: asset.height,
        },
      };
      addNode(node);
      recordOperation("上传图片", images[index].name, "success");
    } catch (error) {
      recordOperation("上传图片失败", `${images[index].name}：${error.message}`, "error");
      toast(`${images[index].name}：${error.message}`, "error");
    }
  }
}

async function reuseImageParameters(imageNode) {
  if (!imageNode || els.imageViewerReuseBtn.disabled) return;
  els.imageViewerReuseBtn.disabled = true;
  try {
    await hydrateImageGenerationMeta(imageNode, state.viewerLibraryAsset);
    const meta = imageNode.meta || {};
    const prompt = String(meta.finalPrompt || meta.tags || "").trim();
    if (!prompt) throw new Error("图片没有可复用的提示词记录");
    const node = createPromptNode(worldCenter());
    node.y = clientToWorld(0, document.querySelector(".topbar").getBoundingClientRect().bottom + 64).y;
    node.title = `复用 · ${imageNode.title || "图片"}`;
    node.prompt = prompt;
    node.raw = true;
    node.artist = "";
    const model = String(meta.model || "").toLowerCase();
    if (model.includes("diffusion-5") || /\bv5\b/.test(model)) node.model = "nai-diffusion-5-full";
    else if (model.includes("4-5") || /4[.]5/.test(model)) node.model = "nai-diffusion-4-5-full";
    if (meta.width > 0 && meta.height > 0) node.ratio = `${Math.round(meta.width)}x${Math.round(meta.height)}`;
    const characters = normalizeCharPromptEntries((meta.characterPrompts || []).map((item) => typeof item === "string" ? { prompt: item } : item));
    node.meta = {
      ...imageGenerationMeta(meta),
      generationSeed: normalizeNaiSeed(meta.seed) || 0,
      retagCharPrompts: characters,
      retagCharPromptsOriginal: structuredClone(characters),
      retagCharDisabled: [],
      retagCharacterExpanded: false,
      advParamsExpanded: true,
      rawTranslate: false,
      ratioManual: true,
    };
    const adjusted = [];
    for (const key of ["steps", "scale", "cfgRescale"]) {
      const value = effectiveParameter(meta, key, "");
      if (value === undefined) delete node.meta[key];
      else {
        node.meta[key] = value;
        if (Number(meta[key]) !== value) adjusted.push(key);
      }
    }
    closeImageViewer();
    setAssetPanel(false);
    addNode(node);
    recordOperation("复用图片参数", imageNode.title || "图片", "success");
    toast(adjusted.length ? "已复用参数，步数/引导按当前生成范围校正" : "已新建提示词节点并带入原图参数");
  } catch (error) {
    toast(error.message || "参数复用失败", "error");
  } finally {
    els.imageViewerReuseBtn.disabled = false;
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
  setLibraryData(library);
  await switchCanvas(canvasMeta, { saveCurrent: false });
  startHealthMonitor();
}

const pageApi = {
  apiGet: (...args) => bridge.apiGet(...args),
  apiPost: (...args) => bridge.apiPost(...args),
  download: (...args) => bridge.download(...args),
};

const {
  positionCharacterEditor,
  makeCharacterCard
} = createCharacterEditor({
  state,
  attachedPanelViewportBounds,
  MAX_CHAR_PROMPTS,
  automaticRetagCharLayout,
  bringNodeToFront,
  clamp,
  clearDebugTrace,
  cloneCharPromptEntry,
  editableCharCenter,
  icon,
  isNodeSelected,
  normalizeCharPromptEntries,
  pushHistory,
  randomCharacterCenter,
  renderAll,
  renderNodes,
  retagCharDisabledIndexes,
  retagCharEnabled,
  scheduleSave,
  scheduleAttachedPanelLayout,
  scrollContainerConsumesWheel,
  selectNode
});

const {
  applyImageViewerLayout,
  scheduleImageViewerFrameSync,
  imageGenerationMeta,
  hydrateImageGenerationMeta,
  openImageViewer,
  stepImageViewer,
  closeImageViewer,
  updateImageViewerSaveButton,
  bindImageViewerEvents
} = createImageViewer({
  reuseImageParameters,
  alignToastRegion,
  bridge: pageApi,
  copyPlainText,
  copyViewerText,
  downloadImage,
  els,
  findNode,
  normalizeCharPromptEntries,
  normalizeNaiSeed,
  normalizeRetagTagTranslations,
  openLibraryImageViewer: (...args) => openLibraryImageViewer(...args),
  placeImageAssetOnCanvas: (...args) => placeImageAssetOnCanvas(...args),
  recordOperation,
  retagTagLookupKey,
  saveImageToLibrary: (...args) => saveImageToLibrary(...args),
  scheduleSave,
  setAssetPanel: (...args) => setAssetPanel(...args),
  state,
  toast,
  worldCenter
});

const {
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
} = createAssetLibrary({
  ASSET_LIBRARY_PREFS_KEY,
  ASSET_RECENT_LIMIT,
  ASSET_RENDER_BATCH,
  addNode,
  alignDebugBar,
  alignedPanelEdges,
  bridge: pageApi,
  clamp,
  createZipBlob,
  decodeDataUrl,
  downloadBlob,
  els,
  encodeZipText,
  estimatedImageNodeHeight,
  findNode,
  fittedImageNodeWidth,
  hydrateImageGenerationMeta: (...args) => hydrateImageGenerationMeta(...args),
  icon,
  imageExtension,
  imageGenerationMeta: (...args) => imageGenerationMeta(...args),
  normalizeNaiSeed,
  normalizeRetagTagTranslations,
  openImageViewer: (...args) => openImageViewer(...args),
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
  updateImageViewerSaveButton: (...args) => updateImageViewerSaveButton(...args),
  worldCenter
});

bindImageViewerEvents();

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
    setDebugBarOpen(false);
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
        setDebugBarOpen(false);
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
  const editor = targetElement.closest("textarea, input, select, [contenteditable='true']");
  return !!editor && document.activeElement === editor;
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
  // 滚轮落在 body 之外（如标题栏/操作记录边框）时兜底滚动调试内容，
  // 避免出现"滚不动"的死区
  const body = els.debugBarBody;
  if (!body || body.hidden || body.contains(event.target)) return;
  event.preventDefault();
  body.scrollTop += event.deltaY;
}, { passive: false });

// The diagnostics HUD is an interactive surface of its own. Keep pointer
// gestures (including text drag-selection) from reaching the canvas' CAD
// selection/pan handlers.
els.debugBar?.addEventListener("pointerdown", (event) => event.stopPropagation());
els.debugBar?.addEventListener("dblclick", (event) => event.stopPropagation());

// 点击素材库面板之外的地方收起素材库
document.addEventListener("pointerdown", (event) => {
  if (!els.assetPanel?.classList.contains("open")) return;
  const target = event.target;
  // 判断不了归属就别关，免得误收
  if (!(target instanceof Element)) return;
  // 大图预览是从素材库里点开的，盖在库上面：点它的空白处只该退出预览，
  // 不该把底下的素材库一起收掉。
  if (target.closest(".asset-panel, .image-viewer")) return;
  if (target.closest("#assetLibraryBtn, #mobileAssetLibraryBtn")) return;
  setAssetPanel(false);
}, true);

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

const SELECTABLE_TEXT_SELECTOR = "textarea, input, [contenteditable='true'], .image-viewer-copy-text, .clipboard-copy-buffer, .debug-body, .operation-log-list";

function isSelectableTextTarget(target) {
  const targetElement = target instanceof Element ? target : target?.parentElement;
  const selection = window.getSelection?.();
  const selectionNodes = selection
    ? [selection.anchorNode, selection.focusNode]
    : [];
  const selectionInTextSurface = selectionNodes.some((node) => {
    const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
    return element?.closest?.(SELECTABLE_TEXT_SELECTOR);
  });
  return !!(
    targetElement?.closest(SELECTABLE_TEXT_SELECTOR)
    || document.activeElement?.closest?.(SELECTABLE_TEXT_SELECTOR)
    || selectionInTextSurface
  );
}

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
window.addEventListener("blur", closeSelectMenu);

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
  if (selectMenuOpen()) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target?.closest(".node-select, .node-select-menu")) closeSelectMenu();
  }
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
  if (!els.imageViewer.hidden && !event.shiftKey && !event.ctrlKey && !event.metaKey
      && (event.key === "ArrowLeft" || event.key === "ArrowRight")) {
    event.preventDefault();
    void stepImageViewer(event.key === "ArrowLeft" ? -1 : 1);
    return;
  }
  if (event.key === "Escape") {
    if (selectMenuOpen()) {
      closeSelectMenu();
      return;
    }
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
  // 灯箱内保留文字复制，不能让 Delete / Ctrl+A 操作背后的画布节点。
  if (!els.imageViewer.hidden) return;
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
  if (selectMenuOpen()) placeSelectMenu(selectMenu.trigger);
  setCanvasContextMenu(false);
  setNodeContextMenu(false);
  setSelectionContextMenu(false);
  alignToastRegion();
  scheduleOverlayAlignment();
  scheduleAttachedPanelLayout();
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




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
  minimap: document.getElementById("minimap"),
  minimapContent: document.getElementById("minimapContent"),
  minimapViewport: document.getElementById("minimapViewport"),
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
  imageViewerImage: document.getElementById("imageViewerImage"),
  imageViewerPromptSection: document.getElementById("imageViewerPromptSection"),
  imageViewerPrompt: document.getElementById("imageViewerPrompt"),
  imageViewerTags: document.getElementById("imageViewerTags"),
  imageViewerPlaceBtn: document.getElementById("imageViewerPlaceBtn"),
  assetPanel: document.getElementById("assetPanel"),
  debugModeBtn: document.getElementById("debugModeBtn"),
  debugBar: document.getElementById("debugBar"),
  debugBarToggle: document.getElementById("debugBarToggle"),
  debugBarSummary: document.getElementById("debugBarSummary"),
  debugBarBody: document.getElementById("debugBarBody"),
  assetGrid: document.getElementById("assetGrid"),
  assetEmpty: document.getElementById("assetEmpty"),
  assetLibraryCount: document.getElementById("assetLibraryCount"),
  assetExpandBtn: document.getElementById("assetExpandBtn"),
  assetSelectModeBtn: document.getElementById("assetSelectModeBtn"),
  assetDeleteActions: document.getElementById("assetDeleteActions"),
  assetDeleteCount: document.getElementById("assetDeleteCount"),
  assetDeleteCancel: document.getElementById("assetDeleteCancel"),
  assetDeleteConfirm: document.getElementById("assetDeleteConfirm"),
  projectMenuBtn: document.getElementById("projectMenuBtn"),
  projectMenu: document.getElementById("projectMenu"),
  projectList: document.getElementById("projectList"),
  newProjectRow: document.getElementById("newProjectRow"),
  newProjectInput: document.getElementById("newProjectInput"),
  canvasContextMenu: document.getElementById("canvasContextMenu"),
};

const state = {
  config: {
    configured: false,
    ratios: [],
    artists: [],
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
  minimapTransform: null,
  pendingUploadPoint: null,
  library: { images: [], prompts: [] },
  libraryAssetPromises: new Map(),
  libraryPreloadPromise: null,
  libraryRenderObserver: null,
  libraryRenderCleanup: null,
  assetPanelExpanded: false,
  assetDeleteMode: false,
  selectedAssetIds: new Set(),
  deletingAssets: false,
  canvases: [],
  pendingDeleteCanvasId: "",
  currentCanvasTitle: "未命名项目",
  assetCache: new Map(),
  promptDefaults: { ratio: "", artist: "" },
  debugEnabled: (() => {
    try { return localStorage.getItem("bestnaiCanvasDebug") === "1"; } catch (_) { return false; }
  })(),
  debugBarOpen: false,
  preferencesSaveChain: Promise.resolve(),
  contextMenuPoint: null,
  viewerLibraryAsset: null,
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
  if (next) setCanvasContextMenu(false);
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

function alignedPanelEdges() {
  const topbarRect = document.querySelector(".topbar").getBoundingClientRect();
  const buttonRect = document.getElementById("assetLibraryBtn").getBoundingClientRect();
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
  if (saveCurrent && canvasId) await flushWorkspace();

  const workspace = await bridge.apiGet("canvas/workspace", { id: canvas.id });
  canvasId = canvas.id;
  projectId = canvas.projectId || "default";
  state.currentCanvasTitle = canvas.title || "未命名项目";
  state.nodes = Array.isArray(workspace?.nodes)
    ? workspace.nodes.map(normalizeLoadedNodeDimensions)
    : [];
  state.connections = Array.isArray(workspace?.connections) ? workspace.connections : [];
  state.viewport = workspace?.viewport || { x: 160, y: 120, scale: 1 };
  state.selectedId = "";
  state.selectedIds = [];
  state.history = [];
  state.future = [];
  state.connectionDrag = null;
  state.minimapTransform = null;
  rememberCurrentCanvas();
  updateCanvasUrl();
  document.title = `${state.currentCanvasTitle} · ${state.config.plugin?.name || "BestNAI"}`;
  setProjectMenu(false);
  renderAll();
  renderProjectMenu();
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
  } catch (error) {
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
  } catch (error) {
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
}

function redo() {
  if (!state.future.length) return;
  state.history.push(snapshot());
  restoreSnapshot(state.future.pop());
  updateHistoryButtons();
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
  state.selectedIds = [...new Set(ids)].filter((id) => !!findNode(id));
  state.selectedId = state.selectedIds.includes(primaryId)
    ? primaryId
    : state.selectedIds[state.selectedIds.length - 1] || "";
  updateSelectionControls();
}

function clearSelection() {
  setSelection([]);
}

function updateSelectionControls() {
  els.arrangeSelectionBtn.classList.toggle("visible", selectedNodeIds().length >= 2);
}

function deleteNodes(ids) {
  const deleteIds = new Set(ids.filter((id) => !!findNode(id)));
  if (!deleteIds.size) return;
  pushHistory();
  state.nodes = state.nodes.filter((node) => !deleteIds.has(node.id));
  state.connections = state.connections.filter(
    (edge) => !deleteIds.has(edge.source) && !deleteIds.has(edge.target),
  );
  clearSelection();
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
    target.statusText = "";
  }
  renderAll();
  scheduleSave();
  toast("已删除连线");
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
  renderAll();
  scheduleSave();
}

function selectNode(id, additive = false) {
  if (!findNode(id)) return;
  if (additive) {
    const next = new Set(selectedNodeIds());
    if (next.has(id)) next.delete(id); else next.add(id);
    setSelection([...next], next.has(id) ? id : "");
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
    if (event.ctrlKey || event.metaKey || event.shiftKey) selectNode(node.id, true);
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
  prompt.addEventListener("input", () => {
    node.prompt = prompt.value;
    node.error = "";
    if (node.meta?.translatedPrompt || node.meta?.retagPrompt || node.meta?.retagSeed) {
      clearRetagCache(node);
    }
    scheduleSave();
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
    rememberPromptDefaults({ ratio: value });
    scheduleSave();
  });
  const artistOptions = canvasArtistOptions();
  const artistField = makeSelectField("画师", artistOptions, node.artist, (value) => {
    node.artist = value;
    rememberPromptDefaults({ artist: value });
    scheduleSave();
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
    scheduleSave();
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
  const resizeHandle = document.createElement("span");
  resizeHandle.className = "node-resize-handle";
  resizeHandle.setAttribute("aria-hidden", "true");
  attachNodeResize(resizeHandle, element, node);
  element.appendChild(resizeHandle);
  return element;
}

const DEBUG_SECTIONS = [
  { key: "retag", label: "反推" },
  { key: "generate", label: "生图" },
];

function formatDebugMs(ms) {
  const value = Number(ms) || 0;
  return value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`;
}

function formatDebugValue(value) {
  if (value === null || value === undefined) return "(无)";
  if (typeof value === "object") {
    return Object.entries(value)
      .map(([key, item]) => `${key}=${formatDebugValue(item)}`)
      .join("  ");
  }
  return String(value);
}

function debugPlainText(runs) {
  const lines = [];
  runs.forEach(({ label, run }) => {
    lines.push(`${label} 总耗时 ${run.totalMs}ms`);
    (run.stages || []).forEach((stage) => {
      lines.push(`  · ${stage.name} ${stage.ms}ms${stage.error ? ` · 失败：${stage.error}` : ""}`);
    });
    Object.entries(run.notes || {}).forEach(([key, value]) => {
      lines.push(`  ${key}: ${formatDebugValue(value)}`);
    });
    lines.push("");
  });
  return lines.join("\n").trim();
}

function debugRunsForNode(node) {
  if (!node) return [];
  return DEBUG_SECTIONS
    .map((section) => ({ label: section.label, run: node.meta?.debug?.[section.key] }))
    .filter((item) => item.run && typeof item.run === "object");
}

/** 调试模式专用：状态栏自己负责折叠，这里只渲染实际流水内容。 */
function makeDebugPanel(node) {
  const runs = debugRunsForNode(node);

  if (!debugModeEnabled() || !runs.length) return null;

  const body = document.createElement("div");
  body.className = "debug-body";

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

    Object.entries(run.notes || {}).forEach(([key, value]) => {
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
    copyPlainText(debugPlainText(runs), "复制调试信息");
  });
  body.appendChild(copy);

  return body;
}

function setDebugBarOpen(open) {
  state.debugBarOpen = !!open;
  els.debugBarToggle?.setAttribute("aria-expanded", String(state.debugBarOpen));
  els.debugBar?.classList.toggle("open", state.debugBarOpen);
  els.debugBarBody?.toggleAttribute("hidden", !state.debugBarOpen);
  const chevron = els.debugBarToggle?.querySelector(".debug-bar-chevron");
  chevron?.classList.toggle("rotated", state.debugBarOpen);
  if (els.assetPanel.classList.contains("open")) {
    window.requestAnimationFrame(() => {
      alignAssetPanel();
      updateAssetGridMetrics();
    });
  }
}

function renderDebugBar() {
  if (!els.debugBar) return;
  if (!debugModeEnabled()) {
    els.debugBar.hidden = true;
    els.debugBarBody.replaceChildren();
    if (els.assetPanel.classList.contains("open")) {
      window.requestAnimationFrame(() => {
        alignAssetPanel();
        updateAssetGridMetrics();
      });
    }
    return;
  }
  const candidates = [
    findNode(state.selectedId),
    ...[...state.nodes].reverse(),
  ].filter((node, index, list) => node && list.indexOf(node) === index);
  const node = candidates.find((item) => item?.meta?.debug);
  const runs = debugRunsForNode(node);
  const total = runs.reduce((sum, item) => sum + (Number(item.run.totalMs) || 0), 0);
  els.debugBar.hidden = false;
  els.debugBarSummary.textContent = node && runs.length
    ? `调试信息 · ${formatDebugMs(total)} · ${node.title || "提示词节点"}`
    : "调试信息 · 等待下一次画布请求";
  els.debugBarBody.replaceChildren();
  const panel = makeDebugPanel(node);
  if (panel) {
    els.debugBarBody.appendChild(panel);
  } else {
    const empty = document.createElement("div");
    empty.className = "debug-empty";
    empty.textContent = "运行生成或反推后，这里会显示详细调试信息";
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
  frame.setAttribute("aria-label", "放大图片并查看提示词");
  frame.title = "点击放大图片并查看提示词";
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
  const seed = Number(node.meta?.seed) || 0;
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
  note.addEventListener("input", () => {
    node.note = note.value;
    scheduleSave();
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
          if (findNode(destination)?.type === "prompt") {
            state.connections = state.connections.filter(
              (edge) => edge.target !== destination || findNode(edge.source)?.type !== "image",
            );
          }
          state.connections.push({ source, target: destination });
          scheduleSave();
          renderAll();
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

function renderViewport() {
  const { x, y, scale } = state.viewport;
  els.world.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  els.viewport.style.backgroundPosition = `${x}px ${y}px`;
  els.viewport.style.backgroundSize = `${24 * scale}px ${24 * scale}px`;
}

let viewportProjectionFrame = 0;
let canvasProjectionFrame = 0;
let connectionRenderFrame = 0;

function scheduleViewportProjection() {
  if (viewportProjectionFrame) return;
  viewportProjectionFrame = window.requestAnimationFrame(() => {
    viewportProjectionFrame = 0;
    renderViewport();
    drawMinimap();
  });
}

function scheduleCanvasProjection() {
  if (canvasProjectionFrame) return;
  canvasProjectionFrame = window.requestAnimationFrame(() => {
    canvasProjectionFrame = 0;
    renderConnections();
    drawMinimap();
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
    drawMinimap();
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

    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      selectNode(node.id, true);
      if (!isNodeSelected(node.id)) return;
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
      if (moved) scheduleSave();
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
      if (moved) scheduleSave();
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
      if (moved) scheduleSave();
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
  const candidate = {
    x: sourceNode.x + (sourceNode.width || 320) + 100,
    y: sourceNode.y,
    width,
    height,
  };
  const occupied = state.nodes.map(nodeRect);
  for (let attempt = 0; attempt < occupied.length + 1; attempt += 1) {
    const collisions = occupied.filter((rect) => rectanglesOverlap(candidate, rect));
    if (!collisions.length) return { x: candidate.x, y: candidate.y };
    candidate.y = Math.max(...collisions.map((rect) => rect.y + rect.height + 36));
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
  drawMinimap();
  scheduleSave(800);
}

function fitView() {
  if (!state.nodes.length) {
    pushHistory();
    state.viewport = { x: 160, y: 120, scale: 1 };
    renderAll();
    scheduleSave();
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
  renderAll();
  try {
    const result = await bridge.apiPost("canvas/generate", {
      prompt: workingPrompt,
      retagPrompt: requestRetagPrompt,
      retagCharacter: retagged ? String(node.meta?.retagCharacter || "").trim() : "",
      retagSeries: retagged ? String(node.meta?.retagSeries || "").trim() : "",
      ratio: node.ratio,
      artist: node.artist,
      raw: !!node.raw,
      translationSource,
      cachedTranslationSource: node.meta?.translationSource || "",
      cachedTranslation: node.meta?.translationResult || "",
      cachedTranslationCharacter: node.meta?.translationCharacter || "",
      cachedTranslationSeries: node.meta?.translationSeries || "",
      debug: debugModeEnabled(),
      // 原图自带种子时沿用它，配合原图 prompt 才能真正还原这张图
       seed: reusableRetagSeed(node),
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
          artist: result.meta?.artist || "",
          ratio: result.meta?.ratio || node.ratio,
          retagged,
          width: sourceWidth,
          height: sourceHeight,
          finalPrompt: result.meta?.finalPrompt || "",
          seed: result.meta?.seed || 0,
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
    renderAll();
    scheduleSave();
  } catch (error) {
    node.error = error.message || "生成失败";
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

function clearRetagCache(node) {
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
    translatedPrompt: _translatedPrompt,
    translationSource: _translationSource,
    translationResult: _translationResult,
    translationCharacter: _translationCharacter,
    translationSeries: _translationSeries,
    ...meta
  } = node.meta || {};
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

function reusableRetagSeed(node) {
  const meta = node?.meta || {};
  const seed = Number(meta.retagSeed) || 0;
  if (!seed) return undefined;

  // Workspaces created before the fingerprint fields existed can still use
  // their saved seed. A changed prompt invalidates the retag cache (and its
  // seed) at input time; ratio/artist/raw changes intentionally keep the seed
  // so NovelAI can preserve composition direction across style variants.
  const hasFingerprint = [
    "retagSeedPrompt",
    "retagSeedRatio",
    "retagSeedArtist",
    "retagSeedRaw",
  ].some((key) => Object.prototype.hasOwnProperty.call(meta, key));
  if (!hasFingerprint) return seed;

  if (String(meta.retagSeedPrompt || "") !== String(node.prompt || "").trim()) {
    return undefined;
  }
  return seed;
}

function cachedRetagResult(node, sourceImage, basePrompt) {
  if (!node || !sourceImage?.assetId) return null;
  const meta = node.meta || {};
  if (
    !meta.retagPrompt
    || meta.retagAssetId !== sourceImage.assetId
    || String(meta.retagBasePrompt || "") !== String(basePrompt || "")
  ) return null;
  return {
    prompt: String(meta.retagPrompt).trim(),
    ratio: String(meta.retagRatio || "").trim(),
    character: String(meta.retagCharacter || "").trim(),
    series: String(meta.retagSeries || "").trim(),
    seed: Number(meta.retagSeed) || 0,
    fromMetadata: !!meta.retagFromMetadata,
  };
}

function runPromptNode(id) {
  // 每次手动运行都从空白开始记，否则上一轮的反推流水会跟这一轮的生图混在一起
  const node = findNode(id);
  if (node && debugModeEnabled() && node.meta?.debug) {
    const { debug: _debug, ...meta } = node.meta;
    node.meta = meta;
  }
  return sourceImageForPrompt(id)
    ? retagFromNode(id, true)
    : generateFromNode(id);
}

function recordRunDebug(node, stage, payload) {
  if (!debugModeEnabled()) return;
  node.meta = {
    ...(node.meta || {}),
    debug: { ...(node.meta?.debug || {}), [stage]: payload || null },
  };
}

async function retagFromNode(id, generateAfter = false) {
  const node = findNode(id);
  if (!node || node.status) return false;

  const sourceImage = sourceImageForPrompt(id);
  if (!sourceImage?.assetId) {
    node.error = "请先把原图连接到提示词节点左侧";
    renderAll();
    return false;
  }

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
  renderAll();

  let succeeded = false;
  try {
    const result = cachedRetag || await bridge.apiPost("canvas/retag", {
      assetId: sourceImage.assetId,
      debug: debugModeEnabled(),
    });
    const retagPrompt = String(result?.prompt || "").trim();
    if (!retagPrompt) throw new Error("反推服务未返回提示词");

    pushHistory();
    node.meta = {
      ...(node.meta || {}),
      retagBasePrompt: basePrompt,
      retagPrompt,
      retagCharacter: String(result?.character || "").trim(),
      retagSeries: String(result?.series || "").trim(),
      retagAssetId: sourceImage.assetId,
      retagRatio: result.ratio || "",
      retagSeed: Number(result.seed) || 0,
      retagSeedPrompt: basePrompt,
      retagSeedRatio: node.ratio || "",
      retagSeedArtist: node.artist || "",
      retagSeedRaw: !!node.raw,
      retagFromMetadata: !!result.fromMetadata,
      translatedPrompt: retagPrompt,
    };
    recordRunDebug(node, "retag", result.debug);
    node.statusText = result.fromMetadata
      ? `已读取原图内嵌参数 · 种子 ${result.seed}`
      : "已提取原图 tags，准备生成";
    toast(
      result.fromMetadata
        ? "已读取原图内嵌的 NovelAI 参数"
        : (cachedRetag ? "已复用反推结果" : "原图 tags 已提取"),
    );
    scheduleSave();
    succeeded = true;
  } catch (error) {
    node.error = error.message || "图片反推失败";
    toast(node.error, "error");
  } finally {
    node.status = "";
    renderAll();
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
        drawMinimap();
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
  } catch (error) {
    toast(error.message || "图片下载失败", "error");
  }
}

function openImageViewer(node, { libraryAsset = null } = {}) {
  if (!node?.dataUrl) {
    toast("图片仍在读取，请稍后重试", "error");
    return;
  }
  const meta = node.meta || {};
  els.imageViewerImage.src = node.dataUrl;
  els.imageViewerImage.alt = node.title || "画布图片";
  const prompt = String(meta.prompt || "").trim();
  const tags = String(meta.tags || meta.finalPrompt || "").trim();
  els.imageViewerPromptSection.hidden = !!tags && isPureEnglishPrompt(prompt);
  els.imageViewerPrompt.textContent = prompt || "暂无提示词记录";
  els.imageViewerTags.textContent = tags || "暂无英文 tags 记录";
  state.viewerLibraryAsset = libraryAsset;
  els.imageViewerPlaceBtn.hidden = !libraryAsset;
  els.imageViewer.hidden = false;
  els.imageViewer.focus({ preventScroll: true });
}

function isPureEnglishPrompt(value) {
  const text = String(value || "").trim();
  return !!text && /^[\x00-\x7F]+$/.test(text) && /[A-Za-z]/.test(text);
}

function closeImageViewer() {
  els.imageViewer.hidden = true;
  els.imageViewerImage.removeAttribute("src");
  els.imageViewerPromptSection.hidden = false;
  els.imageViewerPrompt.textContent = "暂无提示词记录";
  els.imageViewerTags.textContent = "暂无英文 tags 记录";
  state.viewerLibraryAsset = null;
  els.imageViewerPlaceBtn.hidden = true;
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
    preloadLibraryImages();
    if (render) renderAssetLibrary();
  } catch (error) {
    toast(error.message || "素材库读取失败", "error");
  }
}

function updateAssetExpandControl() {
  if (!els.assetExpandBtn) return;
  const expanded = state.assetPanelExpanded;
  const canExpand = window.innerWidth > 620;
  els.assetExpandBtn.hidden = !canExpand;
  els.assetExpandBtn.disabled = !canExpand;
  els.assetExpandBtn.setAttribute("aria-pressed", String(expanded));
  els.assetExpandBtn.setAttribute("aria-label", expanded ? "收起素材库" : "展开素材库");
  els.assetExpandBtn.title = expanded ? "收起素材库" : "展开素材库";
  const label = document.createElement("span");
  label.textContent = expanded ? "收起" : "展开";
  els.assetExpandBtn.replaceChildren(icon(expanded ? "minimize-2" : "maximize-2"), label);
  refreshIcons(els.assetExpandBtn);
}

function setAssetPanelExpanded(expanded, { realign = true } = {}) {
  const next = !!expanded
    && window.innerWidth > 620
    && els.assetPanel.classList.contains("open");
  state.assetPanelExpanded = next;
  els.assetPanel.classList.toggle("expanded", next);
  document.body.classList.toggle("asset-library-expanded", next);
  updateAssetExpandControl();
  els.assetGrid.querySelectorAll(".asset-image-card").forEach((card) => {
    card.title = next ? "点击预览，确认后放入画布" : "点击预览，拖到画布使用";
  });
  if (realign && els.assetPanel.classList.contains("open")) {
    alignAssetPanel();
    updateAssetGridMetrics();
    window.requestAnimationFrame(updateAssetGridMetrics);
  }
}

function setAssetPanel(open) {
  if (open) setCanvasContextMenu(false);
  if (open && !els.projectMenu.hidden) setProjectMenu(false);
  if (!open) setAssetPanelExpanded(false, { realign: false });
  els.assetPanel.classList.toggle("open", open);
  document.querySelectorAll("#assetLibraryBtn, #mobileAssetLibraryBtn").forEach((button) => {
    button.classList.toggle("active", open);
    button.setAttribute("aria-expanded", String(open));
  });
  if (!open) {
    setAssetDeleteMode(false);
    return;
  }
  updateAssetExpandControl();
  alignAssetPanel();
  renderAssetLibrary();
}

function setAssetDeleteMode(enabled) {
  state.assetDeleteMode = !!enabled;
  if (!state.assetDeleteMode) {
    state.selectedAssetIds.clear();
    els.assetGrid.querySelectorAll(".asset-image-card.selected").forEach((card) => {
      card.classList.remove("selected");
      card.setAttribute("aria-selected", "false");
    });
  }
  els.assetPanel.classList.toggle("delete-mode", state.assetDeleteMode);
  els.assetSelectModeBtn.classList.toggle("active", state.assetDeleteMode);
  els.assetSelectModeBtn.setAttribute("aria-pressed", String(state.assetDeleteMode));
  updateAssetDeleteControls();
}

function updateAssetDeleteControls() {
  const count = state.selectedAssetIds.size;
  els.assetDeleteActions.hidden = !state.assetDeleteMode;
  els.assetDeleteCount.textContent = `已选 ${count} 项`;
  els.assetDeleteConfirm.disabled = count === 0 || state.deletingAssets;
  els.assetDeleteConfirm.querySelector("span").textContent = state.deletingAssets ? "删除中…" : "删除";
  els.assetDeleteCancel.disabled = state.deletingAssets;
  els.assetSelectModeBtn.disabled = state.deletingAssets;
}

function toggleAssetSelection(card, assetId) {
  if (state.selectedAssetIds.has(assetId)) state.selectedAssetIds.delete(assetId);
  else state.selectedAssetIds.add(assetId);
  card.classList.toggle("selected", state.selectedAssetIds.has(assetId));
  card.setAttribute("aria-selected", String(state.selectedAssetIds.has(assetId)));
  updateAssetDeleteControls();
}

async function deleteSelectedLibraryAssets() {
  const ids = [...state.selectedAssetIds];
  if (!ids.length || state.deletingAssets) return;
  state.deletingAssets = true;
  updateAssetDeleteControls();
  try {
    await Promise.all(ids.map((id) => bridge.apiPost("canvas/library/image/delete", { id })));
    state.library.images = state.library.images.filter((item) => !ids.includes(item.id));
    setAssetDeleteMode(false);
    renderAssetLibrary();
    toast(`已删除 ${ids.length} 项素材`);
  } catch (error) {
    toast(error.message || "批量删除素材失败", "error");
  } finally {
    state.deletingAssets = false;
    updateAssetDeleteControls();
  }
}

function renderAssetLibrary() {
  state.libraryRenderCleanup?.();
  state.libraryRenderCleanup = null;
  state.libraryRenderObserver?.disconnect();
  state.libraryRenderObserver = null;
  const items = state.library.images;
  els.assetLibraryCount.textContent = `已收录 ${items.length} 张`;
  els.assetGrid.replaceChildren();
  els.assetGrid.scrollTop = 0;
  els.assetGrid.className = "asset-grid compact-layout";
  els.assetGrid.classList.toggle("empty", items.length === 0);
  els.assetEmpty.classList.toggle("visible", items.length === 0);
  els.assetEmpty.querySelector("span").textContent = "暂无图片素材";

  if (items.length) renderAssetBatch(items, 0);
  updateAssetGridMetrics();
  window.requestAnimationFrame(updateAssetGridMetrics);
  refreshIcons(els.assetPanel);
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
  const { topbarRect, left, right } = alignedPanelEdges();
  const viewportRect = els.viewport.getBoundingClientRect();
  const minimapRect = els.minimap.getBoundingClientRect();
  const debugRect = !els.debugBar.hidden
    ? els.debugBar.getBoundingClientRect()
    : { height: 0 };
  const gap = 14;
  if (state.assetPanelExpanded) {
    const margin = 12;
    els.assetPanel.style.left = `${margin}px`;
    els.assetPanel.style.width = `${Math.max(240, viewportRect.width - margin * 2)}px`;
  } else {
    els.assetPanel.style.left = `${left - viewportRect.left}px`;
    els.assetPanel.style.width = `${right - left}px`;
  }
  els.assetPanel.style.top = `${topbarRect.bottom - viewportRect.top + gap}px`;
  const bottomOffsets = [12];
  if (!state.assetPanelExpanded && minimapRect.height > 0) {
    bottomOffsets.push(viewportRect.bottom - minimapRect.top + gap);
  }
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
  const columns = state.assetPanelExpanded
    ? clamp(Math.floor((availableWidth + columnGap) / (156 + columnGap)), 3, 10)
    : 3;
  els.assetGrid.style.gridTemplateColumns = state.assetPanelExpanded
    ? `repeat(${columns}, minmax(0, 1fr))`
    : "";
  const tileSize = Math.max(
    64,
    Math.floor((availableWidth - columnGap * (columns - 1)) / columns),
  );
  els.assetGrid.style.setProperty("--asset-card-height", `${tileSize}px`);
}

function renderImageAssetCard(item, container = els.assetGrid) {
  const card = document.createElement("article");
  card.className = "asset-card asset-image-card";
  card.title = state.assetPanelExpanded
    ? "点击预览，确认后放入画布"
    : "点击预览，拖到画布使用";
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
  if (item.artist) {
    const artist = document.createElement("span");
    artist.className = "asset-thumb-artist";
    artist.textContent = item.artist;
    artist.title = `画师预设：${item.artist}`;
    thumb.appendChild(artist);
  }
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
  attachLibraryImageDrag(card, item);
  container.appendChild(card);
}

function isCanvasDropPoint(clientX, clientY) {
  const rect = els.viewport.getBoundingClientRect();
  if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
    return false;
  }
  const target = document.elementFromPoint(clientX, clientY);
  return !target?.closest(".asset-panel, .topbar, .image-viewer");
}

function attachLibraryImageDrag(card, item) {
  let suppressClick = false;
  card.addEventListener("click", () => {
    if (state.assetDeleteMode) {
      toggleAssetSelection(card, item.id);
      return;
    }
    if (suppressClick) {
      suppressClick = false;
      return;
    }
    openLibraryImageViewer(item);
  });
  card.addEventListener("pointerdown", (event) => {
    if (
      state.assetDeleteMode
      || state.assetPanelExpanded
      || event.pointerType === "touch"
      || event.button !== 0
      || event.target.closest("button")
    ) return;
    const cardRect = card.getBoundingClientRect();
    const start = {
      x: event.clientX,
      y: event.clientY,
      grabOffsetX: event.clientX - cardRect.left,
      grabOffsetY: event.clientY - cardRect.top,
      cardWidth: cardRect.width,
    };
    let dragging = false;
    let ghost = null;
    let canDrop = false;
    const moveGhost = (moveEvent) => {
      ghost.style.left = `${moveEvent.clientX - start.grabOffsetX}px`;
      ghost.style.top = `${moveEvent.clientY - start.grabOffsetY}px`;
    };
    const move = (moveEvent) => {
      if (!dragging && Math.hypot(moveEvent.clientX - start.x, moveEvent.clientY - start.y) < 6) return;
      moveEvent.preventDefault();
      if (!dragging) {
        dragging = true;
        card.classList.add("dragging");
        ghost = card.cloneNode(true);
        ghost.className = "asset-drag-ghost";
        ghost.style.width = `${start.cardWidth}px`;
        ghost.querySelectorAll("button").forEach((button) => button.remove());
        document.body.appendChild(ghost);
      }
      moveGhost(moveEvent);
      canDrop = isCanvasDropPoint(moveEvent.clientX, moveEvent.clientY);
      els.viewport.classList.toggle("drag-over", canDrop);
      ghost.classList.toggle("can-drop", canDrop);
    };
    const end = (endEvent) => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
      card.classList.remove("dragging");
      ghost?.remove();
      clearDropOverlay();
      if (!dragging) return;
      endEvent.preventDefault();
      suppressClick = true;
      window.setTimeout(() => { suppressClick = false; }, 120);
      if (canDrop && isCanvasDropPoint(endEvent.clientX, endEvent.clientY)) {
        placeImageAssetOnCanvas(item, clientToWorld(endEvent.clientX, endEvent.clientY));
      }
    };
    window.addEventListener("pointermove", move, { passive: false });
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
  });
}

async function openLibraryImageViewer(item) {
  try {
    await ensureLibraryImageData(item);
    openImageViewer({
      dataUrl: item.dataUrl,
      title: item.name || "图片素材",
      meta: {
        prompt: item.prompt || "",
        tags: item.tags || "",
        artist: item.artist || "",
        width: item.width,
        height: item.height,
        ratio: item.ratio || "",
        seed: Number(item.seed) || 0,
      },
    }, { libraryAsset: item });
  } catch (error) {
    toast(error.message || "图片素材读取失败", "error");
  }
}

async function placeImageAssetOnCanvas(item, point = worldCenter()) {
  try {
    await ensureLibraryImageData(item);
    const nodeWidth = fittedImageNodeWidth(item.width, item.height);
    const nodeHeight = estimatedImageNodeHeight(nodeWidth, item.width, item.height);
    addNode({
      id: uid("image"),
      type: "image",
      x: point.x - nodeWidth / 2,
      y: point.y - nodeHeight / 2,
      width: nodeWidth,
      title: item.name || "素材图片",
      assetId: item.id,
      dataUrl: item.dataUrl,
      createdAt: new Date().toISOString(),
      meta: {
        prompt: item.prompt || item.name || "素材图片",
        tags: item.tags || "",
        artist: item.artist || "",
        width: item.width,
        height: item.height,
        ratio: item.ratio || "",
        seed: Number(item.seed) || 0,
        retagged: item.source === "retagged",
        source: item.source || "",
      },
    });
    return true;
  } catch (error) {
    toast(error.message || "添加图片素材失败", "error");
    return false;
  }
}

async function saveImageToLibrary(node) {
  if (!node?.assetId) return;
  try {
    const result = await bridge.apiPost("canvas/library/image/add", {
      assetId: node.assetId,
      name: node.title || node.meta?.prompt || "画布图片",
      source: node.meta?.retagged ? "retagged" : "generated",
      prompt: node.meta?.prompt || "",
      tags: node.meta?.tags || node.meta?.finalPrompt || "",
      artist: node.meta?.artist || "",
      ratio: node.meta?.ratio || "",
      // A source image may only reveal its seed during the retag pass; keep
      // that value when the image itself is later collected into the library.
      seed: Number(node.meta?.seed || node.meta?.retagSeed) || 0,
    });
    const image = { ...result.image, dataUrl: node.dataUrl };
    state.library.images = [image, ...state.library.images.filter((item) => item.id !== image.id)];
    if (els.assetPanel.classList.contains("open")) renderAssetLibrary();
    toast("图片已保存到素材库");
  } catch (error) {
    toast(error.message || "图片保存失败", "error");
  }
}

async function uploadFiles(files, point = worldCenter()) {
  const images = [...files].filter((file) => file.type.startsWith("image/"));
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
    } catch (error) {
      toast(`${images[index].name}：${error.message}`, "error");
    }
  }
}

// DOM projection and drag navigation follow hero8152/Infinite-Canvas.
function drawMinimap() {
  if (window.matchMedia("(max-width: 620px)").matches) {
    state.minimapTransform = null;
    return;
  }
  const viewportWidth = els.viewport.clientWidth / state.viewport.scale;
  const viewportHeight = els.viewport.clientHeight / state.viewport.scale;
  const viewportX = -state.viewport.x / state.viewport.scale;
  const viewportY = -state.viewport.y / state.viewport.scale;
  const viewportBounds = {
    x: viewportX,
    y: viewportY,
    width: viewportWidth,
    height: viewportHeight,
  };
  const nodeBounds = state.nodes.map((node) => {
    const element = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
    return {
      x: node.x,
      y: node.y,
      width: node.width || 320,
      height: element?.offsetHeight || 280,
    };
  });
  const bounds = [...nodeBounds, viewportBounds];
  const minX = Math.min(...bounds.map((item) => item.x), -200);
  const minY = Math.min(...bounds.map((item) => item.y), -200);
  const maxX = Math.max(...bounds.map((item) => item.x + item.width), viewportX + viewportWidth + 200);
  const maxY = Math.max(...bounds.map((item) => item.y + item.height), viewportY + viewportHeight + 200);
  const mapWidth = els.minimapContent.clientWidth || 172;
  const mapHeight = els.minimapContent.clientHeight || 110;
  const scale = Math.min(mapWidth / Math.max(1, maxX - minX), mapHeight / Math.max(1, maxY - minY));
  const ox = (mapWidth - (maxX - minX) * scale) / 2;
  const oy = (mapHeight - (maxY - minY) * scale) / 2;
  const mapX = (x) => ox + (x - minX) * scale;
  const mapY = (y) => oy + (y - minY) * scale;
  state.minimapTransform = { minX, minY, scale, ox, oy, mapWidth, mapHeight };

  const selected = new Set(selectedNodeIds());
  const fragments = nodeBounds.map((node, index) => {
    const item = document.createElement("div");
    item.className = `minimap-node${selected.has(state.nodes[index].id) ? " selected" : ""}`;
    item.style.left = `${mapX(node.x)}px`;
    item.style.top = `${mapY(node.y)}px`;
    item.style.width = `${Math.max(4, node.width * scale)}px`;
    item.style.height = `${Math.max(4, node.height * scale)}px`;
    return item;
  });
  els.minimapViewport.style.left = `${mapX(viewportX)}px`;
  els.minimapViewport.style.top = `${mapY(viewportY)}px`;
  els.minimapViewport.style.width = `${Math.max(4, viewportWidth * scale)}px`;
  els.minimapViewport.style.height = `${Math.max(4, viewportHeight * scale)}px`;
  els.minimapContent.replaceChildren(...fragments, els.minimapViewport);
}

function minimapEventToWorld(event) {
  if (!state.minimapTransform) drawMinimap();
  const transform = state.minimapTransform;
  if (!transform) return worldCenter();
  const rect = els.minimapContent.getBoundingClientRect();
  const canvasX = clamp(event.clientX - rect.left, 0, rect.width);
  const canvasY = clamp(event.clientY - rect.top, 0, rect.height);
  return {
    x: transform.minX + (canvasX - transform.ox) / Math.max(0.0001, transform.scale),
    y: transform.minY + (canvasY - transform.oy) / Math.max(0.0001, transform.scale),
  };
}

function centerViewportOnWorldPoint(point) {
  state.viewport.x = els.viewport.clientWidth / 2 - point.x * state.viewport.scale;
  state.viewport.y = els.viewport.clientHeight / 2 - point.y * state.viewport.scale;
  renderViewport();
  drawMinimap();
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
}

els.viewport.addEventListener("pointerdown", (event) => {
  const middlePan = event.pointerType === "mouse" && event.button === 1;
  if (
    (event.button !== 0 && !middlePan)
    || (!middlePan && event.target.closest(".node, button, .link-hit, .link-delete, .minimap, .asset-panel"))
  ) return;

  if (middlePan) event.preventDefault();
  setCanvasContextMenu(false);
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
  const editor = targetElement.closest(".prompt-text, .note-text");
  return !!editor?.closest(".node.selected");
}

els.viewport.addEventListener("wheel", (event) => {
  if (nodeEditorOwnsWheel(event.target)) return;
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

els.viewport.addEventListener("dblclick", (event) => {
  if (event.target.closest(".node, button, .link-hit, .link-delete, .minimap, .asset-panel")) return;
  event.preventDefault();
  addNode(createPromptNode(clientToWorld(event.clientX, event.clientY)));
});

els.viewport.addEventListener("contextmenu", (event) => {
  if (event.target.closest("textarea, input, select, [contenteditable='true']")) return;
  event.preventDefault();
  event.stopPropagation();
  setProjectMenu(false);
  if (els.assetPanel.classList.contains("open")) setAssetPanel(false);
  state.contextMenuPoint = clientToWorld(event.clientX, event.clientY);
  setCanvasContextMenu(true, event.clientX, event.clientY);
});

function dataTransferHasFiles(dataTransfer) {
  return Array.from(dataTransfer?.types || []).includes("Files");
}

function clearDropOverlay() {
  els.viewport.classList.remove("drag-over");
}

function isSelectableTextTarget(target) {
  const targetElement = target instanceof Element ? target : target?.parentElement;
  return !!(
    targetElement?.closest(".prompt-text, .image-viewer-copy-text, .clipboard-copy-buffer")
    || document.activeElement?.closest?.(".prompt-text, .image-viewer-copy-text, .clipboard-copy-buffer")
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

els.minimap.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  els.minimap.classList.add("dragging");
  els.minimap.setPointerCapture(event.pointerId);
  centerViewportOnWorldPoint(minimapEventToWorld(event));

  const move = (moveEvent) => {
    moveEvent.preventDefault();
    centerViewportOnWorldPoint(minimapEventToWorld(moveEvent));
  };
  const end = (endEvent) => {
    els.minimap.classList.remove("dragging");
    if (els.minimap.hasPointerCapture(endEvent.pointerId)) {
      els.minimap.releasePointerCapture(endEvent.pointerId);
    }
    els.minimap.removeEventListener("pointermove", move);
    els.minimap.removeEventListener("pointerup", end);
    els.minimap.removeEventListener("pointercancel", end);
    scheduleSave(800);
  };

  els.minimap.addEventListener("pointermove", move);
  els.minimap.addEventListener("pointerup", end);
  els.minimap.addEventListener("pointercancel", end);
});

els.minimap.addEventListener("keydown", (event) => {
  const directions = {
    ArrowLeft: [-80, 0],
    ArrowRight: [80, 0],
    ArrowUp: [0, -80],
    ArrowDown: [0, 80],
  };
  const direction = directions[event.key];
  if (!direction) return;
  event.preventDefault();
  const multiplier = event.shiftKey ? 2.5 : 1;
  const center = worldCenter();
  centerViewportOnWorldPoint({
    x: center.x + direction[0] * multiplier / state.viewport.scale,
    y: center.y + direction[1] * multiplier / state.viewport.scale,
  });
  scheduleSave(800);
});

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
document.getElementById("fitBtn").addEventListener("click", fitView);
els.debugModeBtn?.addEventListener("click", () => {
  state.debugEnabled = !state.debugEnabled;
  try { localStorage.setItem("bestnaiCanvasDebug", state.debugEnabled ? "1" : "0"); } catch (_) { /* ignore */ }
  els.debugModeBtn.setAttribute("aria-pressed", String(debugModeEnabled()));
  els.debugModeBtn.classList.toggle("active", debugModeEnabled());
  renderDebugBar();
  renderAll();
});
els.debugBarToggle?.addEventListener("click", () => setDebugBarOpen(!state.debugBarOpen));
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
});
document.querySelectorAll("#assetLibraryBtn, #mobileAssetLibraryBtn").forEach((button) => {
  button.addEventListener("click", () => {
    setAssetPanel(!els.assetPanel.classList.contains("open"));
  });
});
els.assetExpandBtn?.addEventListener("click", () => {
  setAssetPanelExpanded(!state.assetPanelExpanded);
});
els.assetSelectModeBtn.addEventListener("click", () => setAssetDeleteMode(true));
els.assetDeleteCancel.addEventListener("click", () => setAssetDeleteMode(false));
els.assetDeleteConfirm.addEventListener("click", deleteSelectedLibraryAssets);

els.imageInput.addEventListener("change", () => {
  uploadFiles(els.imageInput.files, state.pendingUploadPoint || worldCenter());
  state.pendingUploadPoint = null;
  els.imageInput.value = "";
});

document.getElementById("exportBtn").addEventListener("click", async () => {
  await saveWorkspace();
  try {
    await bridge.download("canvas/workspace/export", { id: canvasId }, `${state.currentCanvasTitle || "bestnai-canvas"}.json`);
  } catch (error) {
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
    state.viewport = workspace.viewport || state.viewport;
    clearSelection();
    renderAll();
    scheduleSave(0);
    toast("工作区导入完成");
  } catch (error) {
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
  deleteNodes(state.nodes.map((node) => node.id));
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
els.imageViewer.addEventListener("pointerdown", (event) => {
  if (!event.target.closest("#imageViewerImage, .image-viewer-details")) closeImageViewer();
});
document.querySelectorAll("[data-copy-target]").forEach((button) => {
  button.addEventListener("click", () => copyViewerText(button.dataset.copyTarget, button.title));
});

async function copyViewerText(targetId, label) {
  const text = document.getElementById(targetId)?.textContent?.trim() || "";
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
    if (!els.imageViewer.hidden) {
      closeImageViewer();
      return;
    }
    if (!els.canvasContextMenu.hidden) {
      setCanvasContextMenu(false);
      return;
    }
    if (!els.projectMenu.hidden) {
      setProjectMenu(false);
      return;
    }
    if (els.assetPanel.classList.contains("open")) {
      if (state.assetPanelExpanded) {
        setAssetPanelExpanded(false);
        return;
      }
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
  }
});

window.addEventListener("resize", () => {
  setCanvasContextMenu(false);
  drawMinimap();
  alignToastRegion();
  // The embedded page can receive its first resize after initialization
  // (for example when a desktop iframe settles).  Keep the desktop-only
  // expand control in sync with the actual responsive viewport.
  updateAssetExpandControl();
  if (!els.projectMenu.hidden) alignProjectMenu();
  if (els.assetPanel.classList.contains("open")) {
    if (state.assetPanelExpanded && window.innerWidth <= 620) {
      setAssetPanelExpanded(false);
      return;
    }
    alignAssetPanel();
    updateAssetGridMetrics();
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

refreshIcons();
setupLogoEasterEgg();
setupCompositionGuard();
loadInitialState().catch((error) => {
  setConnectionState("offline");
  toast(error.message, "error");
  renderAll();
});

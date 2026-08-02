const bridge = window.AstrBotPluginPage;

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
  providerDot: document.getElementById("providerDot"),
  providerStatus: document.getElementById("providerStatus"),
  saveState: document.getElementById("saveState"),
  zoomValue: document.getElementById("zoomBadge"),
  undoBtn: document.getElementById("undoBtn"),
  redoBtn: document.getElementById("redoBtn"),
  imageInput: document.getElementById("imageInput"),
  workspaceInput: document.getElementById("workspaceInput"),
  toastRegion: document.getElementById("toastRegion"),
  selectionBox: document.getElementById("selectionBox"),
  createMenu: document.getElementById("createMenu"),
  arrangeSelectionBtn: document.getElementById("canvasArrangeBtn"),
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
  history: [],
  future: [],
  restoring: false,
  connectionDrag: null,
  minimapTransform: null,
  createPoint: null,
  pendingUploadPoint: null,
};

const MAX_HISTORY = 40;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const uid = (prefix) => `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
const nowLabel = () => new Date().toLocaleString([], { hour: "2-digit", minute: "2-digit" });

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
  const item = document.createElement("div");
  item.className = `toast${type === "error" ? " error" : ""}`;
  item.textContent = String(message || "操作失败");
  els.toastRegion.appendChild(item);
  window.setTimeout(() => item.remove(), 3600);
}

function setSaveState(text) {
  els.saveState.textContent = text;
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
  state.nodes = Array.isArray(data.nodes) ? data.nodes : [];
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
  setSaveState("有未保存更改");
  state.saveTimer = window.setTimeout(saveWorkspace, delay);
}

async function saveWorkspace() {
  if (state.saving) {
    scheduleSave(700);
    return;
  }
  state.saving = true;
  setSaveState("保存中");
  try {
    await bridge.apiPost("canvas/workspace", serializableWorkspace());
    setSaveState(`已保存 ${nowLabel()}`);
  } catch (error) {
    setSaveState("保存失败");
    toast(error.message, "error");
  } finally {
    state.saving = false;
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
    title: "提示词节点",
    prompt: "",
    ratio: state.config.defaultRatio || "2:3",
    artist: "",
    raw: false,
    createdAt: new Date().toISOString(),
  };
}

function createNoteNode(point = null) {
  const center = point || suggestedNodeCenter(260);
  return {
    id: uid("note"),
    type: "note",
    x: center.x - 130,
    y: center.y - 100,
    width: 260,
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
    if (event.ctrlKey || event.metaKey) selectNode(node.id, true);
    else if (!isNodeSelected(node.id)) selectNode(node.id);
  });
  attachNodeDrag(handle, element, node);
  return element;
}

function renderPromptNode(node) {
  const element = makeNodeShell(node, node.title || "提示词节点");
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
    scheduleSave();
  });
  prompt.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      generateFromNode(node.id);
    }
  });

  const options = document.createElement("div");
  options.className = "prompt-options";
  const ratioField = makeSelectField("画幅", state.config.ratios, node.ratio, (value) => {
    node.ratio = value;
    scheduleSave();
  });
  const artistOptions = [
    { value: "", label: `默认 · ${state.config.defaultArtist || "配置预设"}` },
    { value: "__none__", label: "不使用画师预设" },
    ...(state.config.artists || []),
  ];
  const artistField = makeSelectField("画师", artistOptions, node.artist, (value) => {
    node.artist = value;
    scheduleSave();
  });
  options.append(ratioField, artistField);

  const footer = document.createElement("div");
  footer.className = "node-footer";
  const rawLabel = document.createElement("label");
  rawLabel.className = "raw-toggle";
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
  const sourceImage = sourceImageForPrompt(node.id);

  const retag = document.createElement("button");
  retag.type = "button";
  retag.className = "retag-btn";
  retag.disabled = !!node.status || !sourceImage || !state.config.retagConfigured;
  retag.append(icon("scan-search"), document.createTextNode(node.status === "retagging" ? "反推中…" : "反推原图"));
  if (!state.config.retagEnabled) {
    retag.title = "请先在插件配置中启用图片反推";
  } else if (!state.config.retagConfigured) {
    retag.title = "请选择支持视觉输入的反推提供商";
  } else if (!sourceImage) {
    retag.title = "先把图片节点右侧端口连接到此节点左侧";
  } else {
    retag.title = "从左侧连接的原图反推提示词";
  }
  retag.addEventListener("pointerdown", (event) => event.stopPropagation());
  retag.addEventListener("click", (event) => {
    event.stopPropagation();
    retagFromNode(node.id);
  });

  const generate = document.createElement("button");
  generate.type = "button";
  generate.className = "generate-btn";
  generate.disabled = !!node.status || !state.config.configured;
  generate.append(icon("wand-sparkles"), document.createTextNode(node.status === "generating" ? "生成中…" : "生成"));
  generate.title = state.config.configured ? "生成图片 (Ctrl+Enter)" : "请先配置生图提供商";
  generate.addEventListener("pointerdown", (event) => event.stopPropagation());
  generate.addEventListener("click", (event) => {
    event.stopPropagation();
    generateFromNode(node.id);
  });
  commands.append(retag, generate);
  footer.append(rawLabel, commands);

  const status = document.createElement("div");
  status.className = `node-status${node.error ? " error" : ""}`;
  status.textContent = node.error
    || node.statusText
    || (sourceImage ? "已连接原图，可反推提示词" : "Ctrl + Enter 快速生成");

  const inputPort = document.createElement("span");
  inputPort.className = "port in";
  attachConnectionPort(inputPort, node.id, "in");
  const outputPort = document.createElement("span");
  outputPort.className = "port out";
  attachConnectionPort(outputPort, node.id, "out");
  element.append(body, inputPort, outputPort);
  body.append(prompt, options, footer, status);
  return element;
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
  const element = makeNodeShell(node, node.title || "生成结果");
  const actions = element.querySelector(".node-actions");
  actions.insertBefore(
    makeAction("download", "下载图片", () => downloadImage(node)),
    actions.firstChild,
  );

  const frame = document.createElement("div");
  frame.className = "image-preview-wrap";
  if (node.dataUrl) {
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
  title.textContent = node.meta?.prompt || node.title || "图片资源";
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
  element.append(body, inputPort, outputPort);
  return element;
}

function renderNoteNode(node) {
  const element = makeNodeShell(node, node.title || "备注");
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
  element.appendChild(body);
  return element;
}

function renderNodes() {
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
}

function connectionPath(x1, y1, x2, y2) {
  const curve = Math.max(70, Math.abs(x2 - x1) * 0.45);
  return `M ${x1} ${y1} C ${x1 + curve} ${y1}, ${x2 - curve} ${y2}, ${x2} ${y2}`;
}

function nodePortPoint(node, role) {
  const element = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
  const height = element?.offsetHeight || 260;
  return {
    x: role === "out" ? node.x + (node.width || 320) : node.x,
    y: node.y + height / 2,
  };
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
      renderConnections();
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
  els.zoomValue.textContent = `${Math.round(scale * 100)}%`;
}

function renderAll() {
  renderViewport();
  renderNodes();
  requestAnimationFrame(() => {
    renderConnections();
    drawMinimap();
  });
  updateHistoryButtons();
  updateSelectionControls();
}

function attachNodeDrag(handle, element, node) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button")) return;
    event.preventDefault();
    event.stopPropagation();

    if (event.ctrlKey || event.metaKey) {
      selectNode(node.id, true);
      if (!isNodeSelected(node.id)) return;
    } else if (!isNodeSelected(node.id)) {
      selectNode(node.id);
    }

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
      renderConnections();
      drawMinimap();
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
    height: element?.offsetHeight || 280,
  };
}

function closeCreateMenu() {
  els.createMenu.classList.remove("open");
  state.createPoint = null;
}

function openCreateMenu(event) {
  const viewportRect = els.viewport.getBoundingClientRect();
  state.createPoint = clientToWorld(event.clientX, event.clientY);
  els.createMenu.classList.add("open");
  const menuWidth = els.createMenu.offsetWidth || 330;
  const menuHeight = els.createMenu.offsetHeight || 90;
  els.createMenu.style.left = `${clamp(event.clientX - viewportRect.left, 8, viewportRect.width - menuWidth - 8)}px`;
  els.createMenu.style.top = `${clamp(event.clientY - viewportRect.top, 8, viewportRect.height - menuHeight - 8)}px`;
}

function finishBoxSelection(startWorld, endEvent) {
  const endWorld = clientToWorld(endEvent.clientX, endEvent.clientY);
  const minX = Math.min(startWorld.x, endWorld.x);
  const minY = Math.min(startWorld.y, endWorld.y);
  const maxX = Math.max(startWorld.x, endWorld.x);
  const maxY = Math.max(startWorld.y, endWorld.y);
  const ids = state.nodes.filter((node) => {
    const rect = nodeRect(node);
    return rect.x < maxX
      && rect.x + rect.width > minX
      && rect.y < maxY
      && rect.y + rect.height > minY;
  }).map((node) => node.id);
  setSelection(ids, ids[ids.length - 1] || "");
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

async function generateFromNode(id) {
  const node = findNode(id);
  if (!node || node.status) return;
  if (!node.prompt?.trim()) {
    node.error = "请输入提示词";
    renderAll();
    return;
  }
  node.status = "generating";
  node.error = "";
  node.statusText = "正在翻译并生成图片…";
  renderAll();
  try {
    const result = await bridge.apiPost("canvas/generate", {
      prompt: node.prompt,
      ratio: node.ratio,
      artist: node.artist,
      raw: !!node.raw,
    });
    const assets = Array.isArray(result?.assets) ? result.assets : [];
    if (!assets.length) throw new Error("服务未返回图片");
    pushHistory();
    const createdIds = [];
    assets.forEach((asset, index) => {
      const imageNode = {
        id: uid("image"),
        type: "image",
        x: node.x + (node.width || 320) + 100,
        y: node.y + index * 340,
        width: 300,
        title: `生成结果 ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`,
        assetId: asset.id,
        dataUrl: asset.dataUrl,
        createdAt: new Date().toISOString(),
        meta: {
          prompt: result.meta?.cleanPrompt || node.prompt,
          ratio: result.meta?.ratio || node.ratio,
          width: asset.width || result.meta?.width,
          height: asset.height || result.meta?.height,
          finalPrompt: result.meta?.finalPrompt || "",
        },
      };
      state.nodes.push(imageNode);
      state.connections.push({ source: node.id, target: imageNode.id });
      createdIds.push(imageNode.id);
    });
    setSelection(createdIds, createdIds[createdIds.length - 1]);
    node.statusText = `已生成 ${assets.length} 张图片`;
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

async function retagFromNode(id) {
  const node = findNode(id);
  if (!node || node.status) return;

  const sourceImage = sourceImageForPrompt(id);
  if (!sourceImage?.assetId) {
    node.error = "请先把原图连接到提示词节点左侧";
    renderAll();
    return;
  }

  if (!state.config.retagConfigured) {
    node.error = "请先配置图片反推提供商";
    renderAll();
    return;
  }

  node.status = "retagging";
  node.error = "";
  node.statusText = "正在反推原图提示词…";
  renderAll();

  try {
    const result = await bridge.apiPost("canvas/retag", {
      assetId: sourceImage.assetId,
      userHint: node.prompt?.trim() || "",
    });
    const prompt = String(result?.prompt || "").trim();
    if (!prompt) throw new Error("反推服务未返回提示词");

    pushHistory();
    node.prompt = prompt;
    if (result.ratio && state.config.ratios.some((item) => item.value === result.ratio)) {
      node.ratio = result.ratio;
    }
    node.statusText = result.ratio
      ? `反推完成 · 已采用原图比例 ${result.ratio}`
      : "反推完成";
    toast("原图反推完成");
    scheduleSave();
  } catch (error) {
    node.error = error.message || "图片反推失败";
    toast(node.error, "error");
  } finally {
    node.status = "";
    renderAll();
  }
}

async function ensureAssetLoaded(node) {
  if (!node.assetId || node.dataUrl || node.assetLoading || node.assetError) return;
  node.assetLoading = true;
  try {
    const result = await bridge.apiGet("canvas/asset", { id: node.assetId });
    node.dataUrl = result.dataUrl;
  } catch (error) {
    node.assetError = error.message || "图片读取失败";
  } finally {
    node.assetLoading = false;
    const current = document.querySelector(`[data-node-id="${CSS.escape(node.id)}"]`);
    if (current) {
      const replacement = renderImageNode(node);
      current.replaceWith(replacement);
      requestAnimationFrame(renderConnections);
    }
  }
}

function downloadImage(node) {
  if (!node.dataUrl) {
    toast("图片仍在读取，请稍后重试", "error");
    return;
  }
  const anchor = document.createElement("a");
  anchor.href = node.dataUrl;
  const mime = /^data:image\/([^;,]+)/i.exec(node.dataUrl)?.[1]?.toLowerCase() || "png";
  const extension = mime === "jpeg" ? "jpg" : mime;
  anchor.download = `bestnai-${node.assetId || Date.now()}.${extension}`;
  anchor.click();
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
      const node = {
        id: uid("image"),
        type: "image",
        x: point.x + index * 34 - 150,
        y: point.y + index * 34 - 150,
        width: 300,
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
  if (!bridge) throw new Error("请从 AstrBot WebUI 插件详情页打开 Canvas");
  await bridge.ready();
  const [config, workspace] = await Promise.all([
    bridge.apiGet("canvas/config"),
    bridge.apiGet("canvas/workspace"),
  ]);
  state.config = { ...state.config, ...(config || {}) };
  state.nodes = Array.isArray(workspace?.nodes) ? workspace.nodes : [];
  state.connections = Array.isArray(workspace?.connections) ? workspace.connections : [];
  state.viewport = workspace?.viewport || state.viewport;
  els.providerDot.classList.toggle("ready", !!state.config.configured);
  els.providerDot.classList.toggle("error", !state.config.configured);
  els.providerStatus.textContent = state.config.configured
    ? `${state.config.model} · 已就绪`
    : "未配置生图提供商";
  setSaveState(workspace?.updatedAt ? "工作区已同步" : "新工作区");
  renderAll();
}

els.viewport.addEventListener("pointerdown", (event) => {
  if (
    event.button !== 0
    || event.target.closest(".node, button, .create-menu, .link-hit, .link-delete")
  ) return;
  closeCreateMenu();

  if (event.ctrlKey || event.metaKey) {
    event.preventDefault();
    event.stopPropagation();
    const viewportRect = els.viewport.getBoundingClientRect();
    const startWorld = clientToWorld(event.clientX, event.clientY);
    const startX = event.clientX - viewportRect.left;
    const startY = event.clientY - viewportRect.top;
    els.selectionBox.classList.add("visible");
    els.selectionBox.style.left = `${startX}px`;
    els.selectionBox.style.top = `${startY}px`;
    els.selectionBox.style.width = "0";
    els.selectionBox.style.height = "0";
    els.viewport.setPointerCapture(event.pointerId);

    const moveSelection = (moveEvent) => {
      const currentX = moveEvent.clientX - viewportRect.left;
      const currentY = moveEvent.clientY - viewportRect.top;
      els.selectionBox.style.left = `${Math.min(startX, currentX)}px`;
      els.selectionBox.style.top = `${Math.min(startY, currentY)}px`;
      els.selectionBox.style.width = `${Math.abs(currentX - startX)}px`;
      els.selectionBox.style.height = `${Math.abs(currentY - startY)}px`;
    };
    const endSelection = (endEvent) => {
      if (els.viewport.hasPointerCapture(endEvent.pointerId)) {
        els.viewport.releasePointerCapture(endEvent.pointerId);
      }
      els.selectionBox.classList.remove("visible");
      els.viewport.removeEventListener("pointermove", moveSelection);
      els.viewport.removeEventListener("pointerup", endSelection);
      els.viewport.removeEventListener("pointercancel", endSelection);
      finishBoxSelection(startWorld, endEvent);
    };
    els.viewport.addEventListener("pointermove", moveSelection);
    els.viewport.addEventListener("pointerup", endSelection);
    els.viewport.addEventListener("pointercancel", endSelection);
    return;
  }

  clearSelection();
  renderNodes();
  requestAnimationFrame(renderConnections);
  const start = { x: event.clientX, y: event.clientY, vx: state.viewport.x, vy: state.viewport.y };
  els.viewport.classList.add("panning");
  els.viewport.setPointerCapture(event.pointerId);
  const move = (moveEvent) => {
    state.viewport.x = start.vx + moveEvent.clientX - start.x;
    state.viewport.y = start.vy + moveEvent.clientY - start.y;
    renderViewport();
    drawMinimap();
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

els.viewport.addEventListener("wheel", (event) => {
  event.preventDefault();
  const factor = Math.exp(-event.deltaY * 0.0015);
  setZoom(state.viewport.scale * factor, event.clientX, event.clientY);
}, { passive: false });

els.viewport.addEventListener("dblclick", (event) => {
  if (event.target.closest(".node, button, .create-menu, .link-hit, .link-delete")) return;
  event.preventDefault();
  openCreateMenu(event);
});

els.viewport.addEventListener("contextmenu", (event) => {
  if (event.target.closest(".node, button, .create-menu, .link-hit, .link-delete")) return;
  event.preventDefault();
  event.stopPropagation();
  openCreateMenu(event);
});

els.viewport.addEventListener("dragover", (event) => {
  event.preventDefault();
  els.viewport.classList.add("drag-over");
});
els.viewport.addEventListener("dragleave", (event) => {
  if (!els.viewport.contains(event.relatedTarget)) els.viewport.classList.remove("drag-over");
});
els.viewport.addEventListener("drop", (event) => {
  event.preventDefault();
  els.viewport.classList.remove("drag-over");
  uploadFiles(event.dataTransfer.files, clientToWorld(event.clientX, event.clientY));
});

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
document.getElementById("fitBtn").addEventListener("click", fitView);
els.undoBtn.addEventListener("click", undo);
els.redoBtn.addEventListener("click", redo);
els.arrangeSelectionBtn.addEventListener("click", arrangeSelectedNodes);

els.createMenu.addEventListener("pointerdown", (event) => event.stopPropagation());
els.createMenu.addEventListener("click", (event) => {
  const button = event.target.closest("[data-create-type]");
  if (!button) return;
  event.stopPropagation();
  const point = state.createPoint || worldCenter();
  const type = button.dataset.createType;
  if (type === "prompt") addNode(createPromptNode(point));
  else if (type === "note") addNode(createNoteNode(point));
  else if (type === "image") {
    state.pendingUploadPoint = point;
    els.imageInput.click();
  }
  closeCreateMenu();
});

els.imageInput.addEventListener("change", () => {
  uploadFiles(els.imageInput.files, state.pendingUploadPoint || worldCenter());
  state.pendingUploadPoint = null;
  els.imageInput.value = "";
});

document.getElementById("exportBtn").addEventListener("click", async () => {
  await saveWorkspace();
  try {
    await bridge.download("canvas/workspace/export", {}, "bestnai-canvas.json");
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
    const workspace = await bridge.upload("canvas/workspace/import", file);
    pushHistory();
    state.nodes = workspace.nodes || [];
    state.connections = workspace.connections || [];
    state.viewport = workspace.viewport || state.viewport;
    clearSelection();
    renderAll();
    setSaveState("已导入");
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
  pushHistory();
  state.nodes = [];
  state.connections = [];
  clearSelection();
  renderAll();
  scheduleSave();
});
clearModal.addEventListener("pointerdown", (event) => {
  if (event.target === clearModal) clearModal.hidden = true;
});

document.addEventListener("keydown", (event) => {
  const editing = event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement;
  if (event.key === "Escape") {
    closeCreateMenu();
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

window.addEventListener("resize", drawMinimap);
window.addEventListener("beforeunload", () => {
  if (state.saveTimer) saveWorkspace();
});

refreshIcons();
loadInitialState().catch((error) => {
  els.providerDot.classList.add("error");
  els.providerStatus.textContent = "连接失败";
  toast(error.message, "error");
  renderAll();
});

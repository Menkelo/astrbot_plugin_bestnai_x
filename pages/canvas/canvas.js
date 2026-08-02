const bridge = window.AstrBotPluginPage;

const els = {
  viewport: document.getElementById("canvasViewport"),
  world: document.getElementById("canvasWorld"),
  nodeLayer: document.getElementById("nodeLayer"),
  paths: document.getElementById("connectionPaths"),
  empty: document.getElementById("emptyState"),
  minimap: document.getElementById("minimap"),
  providerDot: document.getElementById("providerDot"),
  providerStatus: document.getElementById("providerStatus"),
  saveState: document.getElementById("saveState"),
  zoomValue: document.getElementById("zoomValue"),
  undoBtn: document.getElementById("undoBtn"),
  redoBtn: document.getElementById("redoBtn"),
  imageInput: document.getElementById("imageInput"),
  workspaceInput: document.getElementById("workspaceInput"),
  toastRegion: document.getElementById("toastRegion"),
};

const state = {
  config: {
    configured: false,
    ratios: [],
    artists: [],
    defaultRatio: "2:3",
    defaultArtist: "",
  },
  nodes: [],
  connections: [],
  viewport: { x: 160, y: 120, scale: 1 },
  selectedId: "",
  saveTimer: null,
  saving: false,
  history: [],
  future: [],
  restoring: false,
};

const MAX_HISTORY = 40;
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const uid = (prefix) => `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 9)}`;
const nowLabel = () => new Date().toLocaleString([], { hour: "2-digit", minute: "2-digit" });

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
  state.selectedId = node.id;
  renderAll();
  scheduleSave();
}

function findNode(id) {
  return state.nodes.find((node) => node.id === id);
}

function deleteNode(id) {
  if (!findNode(id)) return;
  pushHistory();
  state.nodes = state.nodes.filter((node) => node.id !== id);
  state.connections = state.connections.filter((edge) => edge.source !== id && edge.target !== id);
  if (state.selectedId === id) state.selectedId = "";
  renderAll();
  scheduleSave();
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
  state.selectedId = copy.id;
  renderAll();
  scheduleSave();
}

function selectNode(id) {
  if (state.selectedId === id) return;
  state.selectedId = id;
  document.querySelectorAll(".node.selected").forEach((node) => node.classList.remove("selected"));
  document.querySelector(`[data-node-id="${CSS.escape(id)}"]`)?.classList.add("selected");
  renderConnections();
}

function makeAction(label, title, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "node-action";
  button.textContent = label;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.addEventListener("pointerdown", (event) => event.stopPropagation());
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    action();
  });
  return button;
}

function makeNodeShell(node, label) {
  const element = document.createElement("article");
  element.className = `node ${node.type}-node${state.selectedId === node.id ? " selected" : ""}${node.status === "generating" ? " generating" : ""}`;
  element.dataset.nodeId = node.id;
  element.style.left = `${node.x}px`;
  element.style.top = `${node.y}px`;
  element.style.width = `${node.width || 320}px`;

  const handle = document.createElement("header");
  handle.className = "node-handle";
  const nodeLabel = document.createElement("span");
  nodeLabel.className = "node-label";
  const kind = document.createElement("span");
  kind.className = "node-kind";
  const text = document.createElement("span");
  text.textContent = label;
  nodeLabel.append(kind, text);

  const actions = document.createElement("span");
  actions.className = "node-actions";
  actions.append(
    makeAction("⧉", "复制节点", () => duplicateNode(node.id)),
    makeAction("×", "删除节点", () => deleteNode(node.id)),
  );
  handle.append(nodeLabel, actions);
  element.appendChild(handle);
  element.addEventListener("pointerdown", () => selectNode(node.id));
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

  const generate = document.createElement("button");
  generate.type = "button";
  generate.className = "generate-btn";
  generate.disabled = node.status === "generating" || !state.config.configured;
  generate.textContent = node.status === "generating" ? "生成中…" : "生成";
  generate.title = state.config.configured ? "生成图片 (Ctrl+Enter)" : "请先配置生图提供商";
  generate.addEventListener("pointerdown", (event) => event.stopPropagation());
  generate.addEventListener("click", (event) => {
    event.stopPropagation();
    generateFromNode(node.id);
  });
  footer.append(rawLabel, generate);

  const status = document.createElement("div");
  status.className = `node-status${node.error ? " error" : ""}`;
  status.textContent = node.error || node.statusText || "Ctrl + Enter 快速生成";

  const port = document.createElement("span");
  port.className = "node-port out";
  element.append(body, port);
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
    makeAction("↓", "下载图片", () => downloadImage(node)),
    actions.firstChild,
  );

  const frame = document.createElement("div");
  frame.className = "image-frame";
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

  const port = document.createElement("span");
  port.className = "node-port in";
  element.append(frame, meta, port);
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
}

function renderConnections() {
  els.paths.replaceChildren();
  const selected = state.selectedId;
  state.connections.forEach((edge) => {
    const source = findNode(edge.source);
    const target = findNode(edge.target);
    if (!source || !target) return;
    const sourceEl = document.querySelector(`[data-node-id="${CSS.escape(source.id)}"]`);
    const targetEl = document.querySelector(`[data-node-id="${CSS.escape(target.id)}"]`);
    const sourceHeight = sourceEl?.offsetHeight || 260;
    const targetHeight = targetEl?.offsetHeight || 260;
    const x1 = source.x + (source.width || 320);
    const y1 = source.y + sourceHeight / 2;
    const x2 = target.x;
    const y2 = target.y + targetHeight / 2;
    const curve = Math.max(70, Math.abs(x2 - x1) * 0.45);
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", `M ${x1 + 10000} ${y1 + 10000} C ${x1 + curve + 10000} ${y1 + 10000}, ${x2 - curve + 10000} ${y2 + 10000}, ${x2 + 10000} ${y2 + 10000}`);
    path.setAttribute("class", `connection-path${selected === source.id || selected === target.id ? " active" : ""}`);
    els.paths.appendChild(path);
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
}

function attachNodeDrag(handle, element, node) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0 || event.target.closest("button")) return;
    event.preventDefault();
    event.stopPropagation();
    selectNode(node.id);
    pushHistory();
    const start = { x: event.clientX, y: event.clientY, nodeX: node.x, nodeY: node.y };
    handle.setPointerCapture(event.pointerId);

    const move = (moveEvent) => {
      node.x = start.nodeX + (moveEvent.clientX - start.x) / state.viewport.scale;
      node.y = start.nodeY + (moveEvent.clientY - start.y) / state.viewport.scale;
      element.style.left = `${node.x}px`;
      element.style.top = `${node.y}px`;
      renderConnections();
      drawMinimap();
    };
    const end = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", end);
      handle.removeEventListener("pointercancel", end);
      scheduleSave();
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", end);
    handle.addEventListener("pointercancel", end);
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
  if (!node || node.status === "generating") return;
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
      state.selectedId = imageNode.id;
    });
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

function drawMinimap() {
  const canvas = els.minimap;
  const ctx = canvas.getContext("2d");
  const style = getComputedStyle(document.documentElement);
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = style.getPropertyValue("--panel-soft").trim();
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  if (!state.nodes.length) return;

  const minX = Math.min(...state.nodes.map((node) => node.x)) - 120;
  const minY = Math.min(...state.nodes.map((node) => node.y)) - 120;
  const maxX = Math.max(...state.nodes.map((node) => node.x + (node.width || 320))) + 120;
  const maxY = Math.max(...state.nodes.map((node) => node.y + 300)) + 120;
  const scale = Math.min(canvas.width / Math.max(1, maxX - minX), canvas.height / Math.max(1, maxY - minY));
  const ox = (canvas.width - (maxX - minX) * scale) / 2;
  const oy = (canvas.height - (maxY - minY) * scale) / 2;
  const mapX = (x) => ox + (x - minX) * scale;
  const mapY = (y) => oy + (y - minY) * scale;

  state.nodes.forEach((node) => {
    ctx.fillStyle = node.type === "prompt"
      ? style.getPropertyValue("--accent").trim()
      : node.type === "image"
        ? style.getPropertyValue("--warm").trim()
        : style.getPropertyValue("--muted").trim();
    ctx.fillRect(mapX(node.x), mapY(node.y), Math.max(3, (node.width || 320) * scale), Math.max(3, 220 * scale));
  });

  const rect = els.viewport.getBoundingClientRect();
  const worldLeft = -state.viewport.x / state.viewport.scale;
  const worldTop = -state.viewport.y / state.viewport.scale;
  ctx.strokeStyle = style.getPropertyValue("--ink").trim();
  ctx.lineWidth = 1;
  ctx.strokeRect(
    mapX(worldLeft),
    mapY(worldTop),
    (rect.width / state.viewport.scale) * scale,
    (rect.height / state.viewport.scale) * scale,
  );
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
  if (event.button !== 0 || event.target.closest(".node") || event.target.closest("button")) return;
  state.selectedId = "";
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
  if (event.target.closest(".node") || event.target.closest("button")) return;
  addNode(createPromptNode(clientToWorld(event.clientX, event.clientY)));
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

document.getElementById("addPromptBtn").addEventListener("click", () => addNode(createPromptNode()));
document.getElementById("addNoteBtn").addEventListener("click", () => addNode(createNoteNode()));
document.getElementById("uploadBtn").addEventListener("click", () => els.imageInput.click());
document.getElementById("zoomInBtn").addEventListener("click", () => setZoom(state.viewport.scale * 1.2));
document.getElementById("zoomOutBtn").addEventListener("click", () => setZoom(state.viewport.scale / 1.2));
document.getElementById("fitBtn").addEventListener("click", fitView);
els.zoomValue.addEventListener("click", () => setZoom(1));
els.undoBtn.addEventListener("click", undo);
els.redoBtn.addEventListener("click", redo);

els.imageInput.addEventListener("change", () => {
  uploadFiles(els.imageInput.files);
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
    state.selectedId = "";
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
  state.selectedId = "";
  renderAll();
  scheduleSave();
});
clearModal.addEventListener("pointerdown", (event) => {
  if (event.target === clearModal) clearModal.hidden = true;
});

document.addEventListener("keydown", (event) => {
  const editing = event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement;
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
  if (!editing && (event.key === "Delete" || event.key === "Backspace") && state.selectedId) {
    event.preventDefault();
    deleteNode(state.selectedId);
  }
});

window.addEventListener("resize", drawMinimap);
window.addEventListener("beforeunload", () => {
  if (state.saveTimer) saveWorkspace();
});

loadInitialState().catch((error) => {
  els.providerDot.classList.add("error");
  els.providerStatus.textContent = "连接失败";
  toast(error.message, "error");
  renderAll();
});

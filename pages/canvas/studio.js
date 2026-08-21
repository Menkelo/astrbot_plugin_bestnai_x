// BestNAI Studio —— 仿 NovelAI 的表单式工作区。
// 与无限画布（editor.html/canvas.js）共用后端路由（canvas/*），
// 通过顶栏按钮在两个工作区之间互跳。

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

const PREFS_KEY = "bestnaiStudioPrefs";
const HANDOFF_KEY = "bestnaiStudioHandoff";

const SAMPLERS = [
  { value: "k_euler_ancestral", label: "Euler Ancestral" },
  { value: "k_euler", label: "Euler" },
  { value: "k_dpmpp_2s", label: "DPM++ 2S" },
  { value: "k_dpmpp_2m", label: "DPM++ 2M" },
  { value: "k_dpmpp_sde", label: "DPM++ SDE" },
];

const NOISE_SCHEDULES = [
  { value: "karras", label: "Karras" },
  { value: "native", label: "Native" },
  { value: "exponential", label: "Exponential" },
  { value: "polyexponential", label: "Polyexponential" },
];

const state = {
  config: { ratios: [], artists: [], configured: false },
  history: [],
  activeEntry: null,
  lastTranslation: null,
  healthTimer: null,
  healthChecking: false,
  generating: false,
};

const els = {
  indicator: document.getElementById("connectionIndicator"),
  model: document.getElementById("studioModel"),
  prompt: document.getElementById("promptInput"),
  negative: document.getElementById("negativeInput"),
  ratio: document.getElementById("ratioSelect"),
  artist: document.getElementById("artistSelect"),
  steps: document.getElementById("stepsRange"),
  stepsValue: document.getElementById("stepsValue"),
  scale: document.getElementById("scaleRange"),
  scaleValue: document.getElementById("scaleValue"),
  cfgRescale: document.getElementById("cfgRescaleRange"),
  cfgRescaleValue: document.getElementById("cfgRescaleValue"),
  sampler: document.getElementById("samplerSelect"),
  noise: document.getElementById("noiseSelect"),
  seed: document.getElementById("seedInput"),
  randomSeed: document.getElementById("randomSeedBtn"),
  raw: document.getElementById("rawToggle"),
  generate: document.getElementById("generateBtn"),
  generateText: document.getElementById("generateBtnText"),
  generateHint: document.getElementById("generateHint"),
  previewEmpty: document.getElementById("previewEmpty"),
  previewFrame: document.getElementById("previewFrame"),
  previewImage: document.getElementById("previewImage"),
  previewLoading: document.getElementById("previewLoading"),
  previewLoadingText: document.getElementById("previewLoadingText"),
  metaBar: document.getElementById("metaBar"),
  metaSeed: document.getElementById("metaSeed"),
  metaSize: document.getElementById("metaSize"),
  metaSteps: document.getElementById("metaSteps"),
  metaScale: document.getElementById("metaScale"),
  metaSampler: document.getElementById("metaSampler"),
  metaDownload: document.getElementById("metaDownloadBtn"),
  metaSendCanvas: document.getElementById("metaSendCanvasBtn"),
  historyStrip: document.getElementById("historyStrip"),
  historyTrack: document.getElementById("historyTrack"),
  libraryBtn: document.getElementById("libraryBtn"),
  libraryPanel: document.getElementById("libraryPanel"),
  libraryGrid: document.getElementById("libraryGrid"),
  libraryClose: document.getElementById("libraryCloseBtn"),
  canvasSwitch: document.getElementById("canvasSwitchBtn"),
  panelToggle: document.getElementById("panelToggleBtn"),
  controlPanel: document.getElementById("controlPanel"),
  viewerModal: document.getElementById("viewerModal"),
  viewerImage: document.getElementById("viewerImage"),
  viewerTags: document.getElementById("viewerTags"),
  viewerClose: document.getElementById("viewerCloseBtn"),
  viewerCopy: document.getElementById("viewerCopyBtn"),
  toastRegion: document.getElementById("toastRegion"),
};

function refreshIcons() {
  if (window.lucide?.createIcons) window.lucide.createIcons();
}

function toast(message, kind = "info") {
  const node = document.createElement("div");
  node.className = `toast${kind === "error" ? " error" : ""}`;
  node.textContent = message;
  els.toastRegion.appendChild(node);
  setTimeout(() => node.remove(), 3200);
}

function optionValue(option) {
  return String(option?.value ?? "").trim();
}

function fillSelect(select, options, selectedValue) {
  select.innerHTML = "";
  options.forEach((option) => {
    const el = document.createElement("option");
    el.value = optionValue(option);
    el.textContent = option.label ?? optionValue(option);
    select.appendChild(el);
  });
  if (selectedValue) select.value = selectedValue;
}

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {};
  } catch {
    return {};
  }
}

function savePrefs() {
  const prefs = {
    prompt: els.prompt.value,
    negative: els.negative.value,
    ratio: els.ratio.value,
    artist: els.artist.value,
    steps: Number(els.steps.value),
    scale: Number(els.scale.value),
    cfgRescale: Number(els.cfgRescale.value),
    sampler: els.sampler.value,
    noise: els.noise.value,
    raw: els.raw.checked,
  };
  try {
    localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
  } catch { /* 存储失败不影响使用 */ }
}

function bindRange(range, output, format) {
  const update = () => { output.textContent = format(range.value); };
  range.addEventListener("input", () => { update(); savePrefs(); });
  update();
}

function setGenerating(busy, text) {
  state.generating = busy;
  els.generate.disabled = busy || !state.config.configured;
  els.previewLoading.hidden = !busy;
  els.previewLoadingText.textContent = text || "正在生成图片…";
  els.generateText.textContent = busy ? "生成中…" : "生成 Generate";
}

// ---------- 连接状态 ----------

async function checkConnection() {
  if (state.healthChecking) return;
  state.healthChecking = true;
  try {
    await bridge.apiGet("canvas/health");
    setIndicator("ok");
  } catch {
    setIndicator("bad");
  } finally {
    state.healthChecking = false;
  }
}

function setIndicator(kind) {
  els.indicator.classList.remove("ok", "bad", "checking");
  els.indicator.classList.add(kind);
  const title = kind === "ok" ? "服务连接正常" : kind === "bad" ? "服务连接异常" : "正在检测服务连接";
  els.indicator.title = title;
  els.indicator.setAttribute("aria-label", title);
}

function startHealthMonitor() {
  window.clearInterval(state.healthTimer);
  checkConnection();
  state.healthTimer = window.setInterval(checkConnection, 15_000);
}

// ---------- 初始化 ----------

async function initPanel() {
  const [config] = await Promise.all([bridge.apiGet("canvas/config")]);
  state.config = config || state.config;
  els.model.textContent = state.config.model || "nai-diffusion-4-5-full";

  const prefs = loadPrefs();
  const ratios = Array.isArray(state.config.ratios) ? state.config.ratios : [];
  const artists = [...(state.config.artists || [])];
  if (!artists.some((item) => optionValue(item) === "__none__")) {
    artists.unshift({ value: "__none__", label: "不使用画师" });
  }

  fillSelect(els.ratio, ratios.length ? ratios : [{ value: "", label: "加载失败" }],
    prefs.ratio || state.config.defaultRatio || optionValue(ratios[0]));
  fillSelect(els.artist, artists.length ? artists : [{ value: "", label: "配置画师预设" }],
    prefs.artist ?? state.config.defaultArtist ?? "__none__");
  const samplers = Array.isArray(state.config.samplers) && state.config.samplers.length
    ? state.config.samplers
    : SAMPLERS;
  const noiseSchedules = Array.isArray(state.config.noiseSchedules) && state.config.noiseSchedules.length
    ? state.config.noiseSchedules
    : NOISE_SCHEDULES;
  fillSelect(els.sampler, samplers, prefs.sampler || state.config.defaultSampler || "k_euler_ancestral");
  fillSelect(els.noise, noiseSchedules, prefs.noise || "karras");

  const defaultNegative = String(state.config.defaultNegativePrompt || "").trim();
  if (!els.negative.value && defaultNegative) {
    els.negative.placeholder = defaultNegative;
  }

  if (prefs.prompt !== undefined) els.prompt.value = prefs.prompt;
  if (prefs.negative !== undefined) els.negative.value = prefs.negative;
  if (prefs.steps !== undefined) els.steps.value = prefs.steps;
  if (prefs.scale !== undefined) els.scale.value = prefs.scale;
  if (prefs.cfgRescale !== undefined) els.cfgRescale.value = prefs.cfgRescale;
  els.raw.checked = !!prefs.raw;

  els.steps.value = Number(els.steps.value) || 28;
  els.scale.value = Number(els.scale.value) || 7;
  els.cfgRescale.value = String(Number(prefs.cfgRescale) || 0);

  els.generate.disabled = !state.config.configured;
  els.generateHint.textContent = state.config.configured
    ? "提示词支持中文，会自动翻译为英文 tags"
    : "插件未配置生图提供商，请先在 AstrBot 中完成配置";

  [els.prompt, els.negative].forEach((el) => el.addEventListener("input", savePrefs));
  [els.ratio, els.artist, els.sampler, els.noise].forEach((el) => el.addEventListener("change", savePrefs));
  els.raw.addEventListener("change", savePrefs);
  refreshIcons();
}

// ---------- 生成 ----------

async function generate() {
  if (state.generating) return;
  const prompt = els.prompt.value.trim();
  if (!prompt) {
    toast("请输入提示词", "error");
    els.prompt.focus();
    return;
  }
  const seedText = els.seed.value.trim();
  const payload = {
    prompt,
    ratio: els.ratio.value,
    artist: els.artist.value,
    raw: els.raw.checked,
    steps: Number(els.steps.value),
    scale: Number(els.scale.value),
    cfgRescale: Number(els.cfgRescale.value),
    sampler: els.sampler.value,
    noiseSchedule: els.noise.value,
    // 与画布一致的翻译缓存字段：提示词没变时跳过翻译请求
    translationSource: state.lastTranslation?.source || "",
    cachedTranslationSource: state.lastTranslation?.source || "",
    cachedTranslation: state.lastTranslation?.result || "",
  };
  const negative = els.negative.value.trim();
  if (negative) payload.negativePrompt = negative;
  if (seedText && /^\d+$/.test(seedText)) payload.seed = Number(seedText);

  setGenerating(true, /[\u4e00-\u9fff]/.test(prompt) && !state.lastTranslation
    ? "正在翻译并生成图片…"
    : "正在生成图片…");
  try {
    const result = await bridge.apiPost("canvas/generate", payload);
    const assets = Array.isArray(result?.assets) ? result.assets : [];
    if (!assets.length) throw new Error("服务未返回图片");

    if (result.meta?.translationSource) {
      state.lastTranslation = {
        source: result.meta.translationSource,
        result: result.meta.translationResult || "",
      };
    }

    const entry = { asset: assets[0], meta: result.meta || {} };
    state.history.unshift(entry);
    if (state.history.length > 60) state.history.pop();
    showEntry(entry);
    renderHistory();
    toast("生成完成");
  } catch (error) {
    toast(String(error?.message || error || "生成失败"), "error");
  } finally {
    setGenerating(false);
  }
}

function showEntry(entry) {
  state.activeEntry = entry;
  els.previewEmpty.hidden = true;
  els.previewFrame.hidden = false;
  els.previewImage.src = entry.asset?.dataUrl || "";
  const meta = entry.meta || {};
  els.metaBar.hidden = false;
  els.metaSeed.textContent = `Seed ${meta.seed ?? "—"}`;
  els.metaSeed.dataset.seed = meta.seed ?? "";
  els.metaSize.textContent = meta.width && meta.height ? `${meta.width}×${meta.height}` : "";
  els.metaSteps.textContent = meta.steps ? `Steps ${meta.steps}` : "";
  els.metaScale.textContent = meta.scale ? `Scale ${meta.scale}` : "";
  els.metaSampler.textContent = meta.sampler ? `${meta.sampler} · ${meta.noiseSchedule || ""}` : "";
  renderHistory();
}

function renderHistory() {
  els.historyTrack.innerHTML = "";
  state.history.forEach((entry, index) => {
    const btn = document.createElement("button");
    btn.className = "history-item";
    btn.type = "button";
    btn.title = entry.meta?.finalPrompt || "生成结果";
    if (state.activeEntry === entry) btn.classList.add("active");
    const img = document.createElement("img");
    img.src = entry.asset?.dataUrl || "";
    img.alt = `历史 ${index + 1}`;
    btn.appendChild(img);
    btn.addEventListener("click", () => showEntry(entry));
    els.historyTrack.appendChild(btn);
  });
  els.historyStrip.classList.toggle("has-items", state.history.length > 0);
}

// ---------- 下载 / 发送到无限画布 ----------

function downloadActive() {
  const entry = state.activeEntry;
  if (!entry?.asset?.dataUrl) return;
  const link = document.createElement("a");
  link.href = entry.asset.dataUrl;
  link.download = `bestnai-studio-${entry.meta?.seed || Date.now()}.png`;
  link.click();
}

// 跳回无限画布时必须原样转发 query/hash：AstrBot 页面认证参数就在 query 里，
// 新建 URL 会丢掉它，切过去就是「未授权」。
function canvasWorkspaceUrl() {
  const target = new URL("./editor.html", window.location.href);
  target.search = window.location.search;
  target.hash = window.location.hash;
  return target;
}

function sendToCanvas() {
  const entry = state.activeEntry;
  if (!entry) return;
  const handoff = {
    assetId: entry.asset?.id || "",
    dataUrl: entry.asset?.dataUrl || "",
    prompt: entry.meta?.finalPrompt || els.prompt.value.trim(),
    createdAt: Date.now(),
  };
  try {
    localStorage.setItem(HANDOFF_KEY, JSON.stringify(handoff));
  } catch {
    toast("本地存储不可用，无法发送到画布", "error");
    return;
  }
  window.location.assign(canvasWorkspaceUrl().href);
}

// ---------- 资产库 ----------

async function openLibrary() {
  els.libraryPanel.hidden = false;
  els.libraryBtn.setAttribute("aria-expanded", "true");
  els.libraryGrid.innerHTML = "";
  els.libraryPanel.classList.add("is-empty");
  try {
    const library = await bridge.apiGet("canvas/library");
    const images = Array.isArray(library?.images) ? library.images : [];
    els.libraryPanel.classList.toggle("is-empty", images.length === 0);
    images.slice().reverse().forEach((item) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.title = item.createdAt || "素材";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.alt = "素材";
      btn.appendChild(img);
      btn.addEventListener("click", () => {
        loadAssetIntoViewer(item.id, img);
      });
      els.libraryGrid.appendChild(btn);
      bridge.apiGet("canvas/asset", { id: item.id }).then((payload) => {
        if (payload?.dataUrl) img.src = payload.dataUrl;
      }).catch(() => { /* 单个素材加载失败忽略 */ });
    });
  } catch {
    toast("资产库加载失败", "error");
  }
}

function closeLibrary() {
  els.libraryPanel.hidden = true;
  els.libraryBtn.setAttribute("aria-expanded", "false");
}

async function loadAssetIntoViewer(assetId, imgEl) {
  try {
    const payload = await bridge.apiGet("canvas/asset", { id: assetId });
    openViewer(payload?.dataUrl || imgEl?.src || "", "");
  } catch {
    toast("素材加载失败", "error");
  }
}

// ---------- 查看器 ----------

function openViewer(dataUrl, finalPrompt) {
  els.viewerImage.src = dataUrl || "";
  els.viewerTags.innerHTML = "";
  String(finalPrompt || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean)
    .forEach((tag) => {
      const chip = document.createElement("span");
      chip.className = "viewer-tag";
      chip.textContent = tag;
      els.viewerTags.appendChild(chip);
    });
  els.viewerModal.dataset.prompt = finalPrompt || "";
  els.viewerModal.hidden = false;
}

function closeViewer() {
  els.viewerModal.hidden = true;
}

// ---------- 事件绑定 ----------

function bindEvents() {
  els.generate.addEventListener("click", generate);
  els.randomSeed.addEventListener("click", () => { els.seed.value = ""; });
  els.metaDownload.addEventListener("click", downloadActive);
  els.metaSendCanvas.addEventListener("click", sendToCanvas);
  els.metaSeed.addEventListener("click", () => {
    const seed = els.metaSeed.dataset.seed || "";
    if (seed) {
      navigator.clipboard?.writeText(seed);
      els.seed.value = seed;
      toast(`已复制并填入种子 ${seed}`);
    }
  });
  els.previewImage.addEventListener("click", () => {
    const entry = state.activeEntry;
    if (entry) openViewer(entry.asset?.dataUrl, entry.meta?.finalPrompt);
  });
  els.viewerClose.addEventListener("click", closeViewer);
  els.viewerModal.addEventListener("click", (event) => {
    if (event.target === els.viewerModal) closeViewer();
  });
  els.viewerCopy.addEventListener("click", () => {
    const text = els.viewerModal.dataset.prompt || "";
    if (text) {
      navigator.clipboard?.writeText(text);
      toast("已复制最终提示词");
    }
  });
  els.libraryBtn.addEventListener("click", () => {
    if (els.libraryPanel.hidden) openLibrary();
    else closeLibrary();
  });
  els.libraryClose.addEventListener("click", closeLibrary);
  els.canvasSwitch.addEventListener("click", () => {
    window.location.assign(canvasWorkspaceUrl().href);
  });
  els.panelToggle?.addEventListener("click", () => {
    const open = els.controlPanel.classList.toggle("open");
    els.panelToggle.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!els.viewerModal.hidden) closeViewer();
      else if (!els.libraryPanel.hidden) closeLibrary();
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      event.preventDefault();
      generate();
    }
  });
  bindRange(els.steps, els.stepsValue, (v) => String(v));
  bindRange(els.scale, els.scaleValue, (v) => Number(v).toFixed(1));
  bindRange(els.cfgRescale, els.cfgRescaleValue, (v) => Number(v).toFixed(2));
}

// ---------- 启动 ----------

async function boot() {
  try {
    bridge = await getBridge();
  } catch (error) {
    setIndicator("bad");
    els.generateHint.textContent = String(error?.message || error);
    return;
  }
  bindEvents();
  try {
    await initPanel();
  } catch {
    setIndicator("bad");
    els.generateHint.textContent = "配置加载失败，请刷新重试";
  }
  startHealthMonitor();
  refreshIcons();
}

boot();

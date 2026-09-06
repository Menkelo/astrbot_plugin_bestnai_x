// Canvas component with explicit dependencies; no build step required.
export function createImageViewer({
  alignToastRegion,
  bridge,
  copyPlainText,
  copyViewerText,
  downloadImage,
  els,
  findNode,
  normalizeCharPromptEntries,
  normalizeNaiSeed,
  normalizeRetagTagTranslations,
  openLibraryImageViewer,
  placeImageAssetOnCanvas,
  recordOperation,
  retagTagLookupKey,
  saveImageToLibrary,
  scheduleSave,
  setAssetPanel,
  state,
  toast,
  worldCenter,
  reuseImageParameters
}) {
  function preferredImageViewerLayout(width, height) {
    const imageWidth = Number(width) || 0;
    const imageHeight = Number(height) || 0;
    // NovelAI-Tag keeps the desktop lightbox as a stable two-column layout;
    // choosing bottom for landscape images leaves the absolute details card
    // constrained to a short strip in our canvas viewer.  Only narrow/mobile
    // viewports use the bottom sheet layout.
    if (window.matchMedia("(max-width: 760px)").matches) return "bottom";
    // Legacy breakpoint expression retained for compatibility: return window.innerWidth >= 1100 ? "side" : "bottom"
    return imageWidth && imageHeight ? "side" : "bottom";
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
    return true;
  }

  function lockImageViewerBottomLayout() {
    if (els.imageViewer.hidden || !els.imageViewer.classList.contains("layout-bottom")) return;
    const frame = els.imageViewerImageFrame;
    if (!frame) return;
    const frameRect = frame.getBoundingClientRect();
    if (!frameRect.width || !frameRect.height) return;
    state.viewerBottomLayoutLock = {
      frameWidth: frameRect.width,
      frameHeight: frameRect.height,
    };
    applyImageViewerBottomLayoutLock();
  }

  function syncImageViewerFrameSize() {
    const frame = els.imageViewerImageFrame;
    if (!frame) return;
    if (els.imageViewer.hidden || !els.imageViewer.classList.contains("layout-bottom")) {
      clearImageViewerBottomLayoutLock(true);
      return;
    }
    if (applyImageViewerBottomLayoutLock()) return;
    frame.style.removeProperty("width");
    frame.style.removeProperty("height");

    const imageWidth = Number(els.imageViewerImage.naturalWidth)
      || Number(state.viewerImageDimensions.width)
      || 0;
    const imageHeight = Number(els.imageViewerImage.naturalHeight)
      || Number(state.viewerImageDimensions.height)
      || 0;
    if (!imageWidth || !imageHeight) return;

    const stage = frame.closest(".image-viewer-stage");
    if (!stage) return;
    const stageRect = stage.getBoundingClientRect();
    const maxWidth = Math.max(0, stageRect.width);
    // 信息卡是悬浮在舞台右侧之外的独立图层，不占舞台空间，图片可以用满整个舞台
    const maxHeight = Math.max(0, stageRect.height);
    if (!maxWidth || !maxHeight) return;

    const scale = Math.min(maxWidth / imageWidth, maxHeight / imageHeight);
    frame.style.width = `${imageWidth * scale}px`;
    frame.style.height = `${imageHeight * scale}px`;
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
    els.imageViewer.classList.toggle("details-collapsed", next);
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
    let weightedStart = -1;
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
          weightedStart = index;
          continue;
        }
      }

      if (weighted) {
        if (text.startsWith("::", index)) {
          buffer += "::";
          index += 2;
          weighted = false;
          weightedStart = -1;
          continue;
        }
        if (index > weightedStart && (index === 0 || ",; \n\t".includes(text[index - 1]))) {
          const nested = /^-?\d+(?:\.\d+)?::/.exec(text.slice(index));
          if (nested) {
            const value = buffer.trim().replace(/^[,;\s]+|[,;\s]+$/g, "");
            if (value) tokens.push(value.endsWith("::") ? value : `${value} ::`);
            buffer = "";
            weighted = false;
            weightedStart = -1;
            continue;
          }
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
      if (buffer && (index === 0 || " \t\n".includes(text[index - 1]))) {
        const nextWeight = /^-?\d+(?:\.\d+)?::/.exec(text.slice(index));
        if (nextWeight) {
          flush();
          continue;
        }
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
      .replace(/_/g, " ")
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
      /^(?:\[+|\{+)?artist\s*:/.test(lowered)
      || configuredKeys.has(plain)
      || IMAGE_VIEWER_CONTROL_TAGS.has(plain)
      || /^(?:rating|score)\s*[:_]/.test(plain)
    );
  }

  function stripImageViewerControlTags(tags, extraControlPrompts = []) {
    const configuredKeys = imageViewerConfiguredControlKeys(extraControlPrompts);
    const kept = [];
    splitImageViewerPromptTokens(tags).forEach((segment) => {
      const { weight, atoms, weighted } = imageViewerWeightedTokenParts(segment);
      const filtered = [];
      atoms.forEach((rawToken) => {
        const token = String(rawToken || "").trim().replace(/^[,;\s]+|[,;\s]+$/g, "");
        const key = imageViewerControlTagKey(token);
        if (!token || !key || imageViewerTagIsControl(token, configuredKeys)) return;
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
    // 翻译结果可能只覆盖部分标签，不能用它替换原始标签列表。
    const source = imageViewerAtomicTags(tags);
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

  function renderImageViewerTags(tags, pairs = [], translations = {}, target = els.imageViewerTags) {
    const rawTags = String(tags || "").trim();
    const filtered = state.viewerShowFilteredTags;
    target.dataset.copyText = rawTags;
    target.classList.toggle("image-viewer-tag-grid", filtered);
    target.classList.toggle("image-viewer-tag-text", !filtered);
    target.classList.toggle("image-viewer-copy-text", !filtered);
    target.replaceChildren();
    scheduleImageViewerFrameSync();
    if (rawTags && !filtered) {
      // 原始视图直接显示原文，保留权重、括号、换行与全部标签。
      target.textContent = rawTags;
      return;
    }
    const entries = imageViewerTagEntries(pairs, translations, rawTags);
    if (!entries.length) {
      const empty = document.createElement("span");
      empty.className = "image-viewer-tag-empty";
      empty.textContent = "暂无英文 Tags 记录 / No English Tags yet";
      target.appendChild(empty);
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
      target.appendChild(chip);
    });
  }

  function imageViewerCharacterEntries(meta = {}) {
    const entries = Array.isArray(meta.characterPrompts) ? meta.characterPrompts : [];
    return normalizeCharPromptEntries(entries.map((item) => (
      typeof item === "string" ? { prompt: item } : item
    )));
  }

  function imageGenerationMeta(meta = {}) {
    const keys = [
      "steps", "scale", "sampler", "cfgRescale", "noiseSchedule", "varietyBoost",
      "ucPreset", "model", "quality", "imageFormat", "negativePrompt",
      "characterUseCoords", "characterUseOrder", "finalPrompt",
    ];
    const result = Object.fromEntries(keys
      .filter((key) => meta?.[key] != null)
      .map((key) => [key, meta[key]]));
    if (Array.isArray(meta?.characterPrompts)) {
      result.characterPrompts = imageViewerCharacterEntries(meta);
    }
    return result;
  }

  async function hydrateImageGenerationMeta(node, libraryAsset = null) {
    const assetId = node?.assetId || libraryAsset?.id;
    if (!assetId) return;
    try {
      let pending = state.imageParamsCache.get(assetId);
      if (!pending) {
        pending = bridge.apiGet("canvas/asset/params", { id: assetId });
        if (state.imageParamsCache.size >= 160) {
          state.imageParamsCache.delete(state.imageParamsCache.keys().next().value);
        }
        state.imageParamsCache.set(assetId, pending);
      }
      const params = { ...await pending };
      if (params.tags && !node.meta?.finalPrompt) params.finalPrompt = params.tags;
      // 已保存的提示词与种子优先；其他已知内嵌参数补回旧版未记录的信息。
      if (node.meta?.tags || node.meta?.finalPrompt) delete params.tags;
      if (normalizeNaiSeed(node.meta?.seed)) delete params.seed;
      if (!Object.keys(params).length) return;
      const previous = JSON.stringify(node.meta);
      node.meta = { ...(node.meta || {}), ...params };
      if (libraryAsset) {
        libraryAsset.generationMeta = imageGenerationMeta(node.meta);
        libraryAsset.tags = libraryAsset.tags || node.meta.tags || "";
        libraryAsset.seed = normalizeNaiSeed(libraryAsset.seed) || normalizeNaiSeed(node.meta.seed);
      }
      if (findNode(node.id) === node && JSON.stringify(node.meta) !== previous) scheduleSave();
    } catch (_) {
      state.imageParamsCache.delete(assetId);
      // 参数丢失或读取失败时保留已有记录，预览不能退回付费反推。
    }
  }

  function imageViewerNoteText(meta) {
    const numberLine = (label, value, allowZero = false) => (
      value != null && value !== "" && Number.isFinite(Number(value))
        && (allowZero || Number(value) > 0) ? `${label}: ${value}` : ""
    );
    const boolLine = (label, value) => typeof value === "boolean"
      ? `${label}: ${value ? "开启" : "关闭"}` : "";
    return [
      meta.model ? `Model: ${meta.model}` : "",
      meta.width && meta.height ? `Size: ${meta.width} × ${meta.height}` : "",
      numberLine("Seed", normalizeNaiSeed(meta.seed)),
      numberLine("Steps", meta.steps),
      numberLine("CFG scale", meta.scale),
      meta.sampler ? `Sampler: ${meta.sampler}` : "",
      meta.noiseSchedule ? `Noise schedule: ${meta.noiseSchedule}` : "",
      numberLine("CFG rescale", meta.cfgRescale, true),
      boolLine("Variety+", meta.varietyBoost),
      boolLine("Quality", meta.quality),
      meta.ucPreset != null && meta.ucPreset !== "" ? `UC preset: ${meta.ucPreset}` : "",
      meta.imageFormat ? `Format: ${meta.imageFormat}` : "",
      imageViewerCharacterEntries(meta).length && typeof meta.characterUseCoords === "boolean"
        ? `角色布局: ${meta.characterUseCoords ? "坐标分区" : "出场顺序"}` : "",
    ].filter(Boolean).join("\n");
  }

  function renderImageViewerInfo(node) {
    const meta = node.meta || {};
    els.imageViewerMeta.textContent = [
      meta.width && meta.height ? `${meta.width}×${meta.height}` : "",
      meta.ratio || "",
      meta.seed ? `Seed ${meta.seed}` : "",
    ].filter(Boolean).join(" / ") || "暂无生成参数记录";
    state.viewerTagsFull = String(meta.finalPrompt || meta.tags || "").trim();
    state.viewerTagsFiltered = stripImageViewerControlTags(state.viewerTagsFull, meta.artist || "");
    const negative = String(meta.negativePrompt || meta.negative_prompt || "").trim();
    els.imageViewerNegative.textContent = negative;
    els.imageViewerNegative.dataset.copyText = negative;
    els.imageViewerNegativeSection.hidden = !negative;
    const note = imageViewerNoteText(meta);
    els.imageViewerNote.textContent = note;
    els.imageViewerNote.dataset.copyText = note;
    els.imageViewerNoteSection.hidden = !note;
    applyImageViewerTagsView();
  }

  function renderImageViewerCharacters(node, sequence) {
    const characters = imageViewerCharacterEntries(node?.meta);
    els.imageViewerCharactersSection.hidden = !characters.length;
    els.imageViewerCharacters.replaceChildren();
    const copyParts = [];
    characters.forEach((entry, index) => {
      const section = document.createElement("section");
      section.className = "image-viewer-character";
      const title = `角色 ${index + 1}`;
      const position = entry.center
        ? `中心: ${entry.center.x}, ${entry.center.y}`
        : entry.position ? `位置: ${entry.position}` : "";
      const prompt = state.viewerShowFilteredTags
        ? stripImageViewerControlTags(entry.prompt, node?.meta?.artist || "") : entry.prompt;
      const addPrompt = (label, text, suffix, negative = false) => {
        const head = document.createElement("div");
        head.className = "image-viewer-copy-head";
        const caption = document.createElement("span");
        caption.className = "image-viewer-copy-text";
        caption.textContent = label;
        const target = document.createElement("div");
        target.id = `imageViewerCharacter${index}${suffix}`;
        head.appendChild(caption);
        if (negative) {
          const copy = document.createElement("button");
          copy.type = "button";
          copy.className = "image-viewer-copy-btn copy-negative";
          copy.dataset.copyTarget = target.id;
          copy.title = `复制${title}负面提示词`;
          copy.textContent = "复制负面";
          head.appendChild(copy);
        }
        section.appendChild(head);
        if (!negative && position) {
          const coordinates = document.createElement("p");
          coordinates.className = "image-viewer-character-position image-viewer-copy-text";
          coordinates.textContent = position;
          section.appendChild(coordinates);
        }
        section.appendChild(target);
        if (negative) {
          target.className = "image-viewer-note image-viewer-copy-text";
          target.textContent = text;
          target.dataset.copyText = text;
        } else if (state.viewerShowFilteredTags && text) {
          void hydrateImageViewerChineseTags(node, text, sequence, target);
        } else {
          renderImageViewerTags(text, [], {}, target);
        }
      };
      els.imageViewerCharacters.appendChild(section);
      addPrompt(title, prompt, "Tags");
      if (entry.negative_prompt) addPrompt("Negative", entry.negative_prompt, "Negative", true);
      copyParts.push([
        `${title}${position ? ` · ${position}` : ""}:`, prompt,
        entry.negative_prompt ? `Negative prompt: ${entry.negative_prompt}` : "",
      ].filter(Boolean).join("\n"));
    });
    els.imageViewerCharacters.dataset.copyText = copyParts.join("\n\n");
  }

  function applyImageViewerTagsView() {
    const sequence = ++state.viewerTagLookupSequence;
    const node = state.viewerNodeRef;
    const tags = state.viewerShowFilteredTags ? state.viewerTagsFiltered : state.viewerTagsFull;
    if (state.viewerShowFilteredTags && tags && node) {
      void hydrateImageViewerChineseTags(node, tags, sequence);
    } else {
      renderImageViewerTags(tags, [], {});
    }
    renderImageViewerCharacters(node, sequence);
  }

  async function hydrateImageViewerChineseTags(node, tags, lookupSequence, target = els.imageViewerTags) {
    const initialTranslations = normalizeRetagTagTranslations(
      node?.meta?.tagTranslations || node?.meta?.retagTagTranslations,
    );
    renderImageViewerTags(tags, [], initialTranslations, target);
    const tagKeys = imageViewerTagKeys(tags);
    if (tagKeys.length && tagKeys.every((key) => initialTranslations[key])) return;

    try {
      let pending = state.viewerTagTranslationCache.get(tags);
      if (!pending) {
        pending = bridge.apiPost("canvas/tags/translate", { tags }).catch((error) => {
          if (state.viewerTagTranslationCache.get(tags) === pending) state.viewerTagTranslationCache.delete(tags);
          throw error;
        });
        if (state.viewerTagTranslationCache.size >= 80) {
          state.viewerTagTranslationCache.delete(state.viewerTagTranslationCache.keys().next().value);
        }
        state.viewerTagTranslationCache.set(tags, pending);
      }
      const result = await pending;
      if (lookupSequence !== state.viewerTagLookupSequence || els.imageViewer.hidden || !target.isConnected) return;
      const translations = {
        ...initialTranslations,
        ...normalizeRetagTagTranslations(result?.translations),
      };
      // Freeze the already-visible English layout before longer bilingual chips
      // are inserted. New content then scrolls inside the Tags surface instead
      // of feeding back into image sizing and moving both columns/rows.
      lockImageViewerBottomLayout();
      renderImageViewerTags(tags, result?.pairs, translations, target);
      if (Object.keys(translations).length) {
        node.meta = {
          ...(node.meta || {}),
          tagTranslations: { ...normalizeRetagTagTranslations(node.meta?.tagTranslations), ...translations },
        };
        if (findNode(node.id) === node) scheduleSave();
        if (state.viewerLibraryAsset) {
          state.viewerLibraryAsset.tagTranslations = node.meta.tagTranslations;
        }
      }
    } catch (_) {
      // The English chips are already visible; a tags-site outage should not
      // replace them with an error state or interrupt image preview.
    }
  }

  function openImageViewer(node, { libraryAsset = null, operationLabel = "打开图片预览", preserveState = false } = {}) {
    if (!node?.dataUrl) {
      toast("图片仍在读取，请稍后重试", "error");
      return;
    }
    const meta = node.meta || {};
    const keepState = preserveState && !els.imageViewer.hidden;
    const folded = keepState && els.imageViewer.classList.contains("folded");
    const collapsed = keepState && els.imageViewerDetails.classList.contains("collapsed");
    const scrollTop = keepState ? els.imageViewerDetails.scrollTop : 0;
    if (!libraryAsset) state.viewerOpenSequence = (state.viewerOpenSequence || 0) + 1;
    state.viewerPendingLibraryAsset = null;
    state.viewerImageDimensions = {
      width: Number(meta.width) || 0,
      height: Number(meta.height) || 0,
    };
    applyImageViewerLayout(state.viewerImageDimensions.width, state.viewerImageDimensions.height);
    setImageViewerDetailsCollapsed(collapsed);
    els.imageViewer.classList.toggle("folded", folded);
    if (els.imageViewerFoldBtn) {
      els.imageViewerFoldBtn.setAttribute("aria-expanded", String(!folded));
      els.imageViewerFoldBtn.setAttribute("aria-label", folded ? "展开信息栏" : "收起信息栏");
      els.imageViewerFoldBtn.title = folded ? "展开信息栏" : "收起信息栏";
    }
    els.imageViewerImage.src = node.dataUrl;
    els.imageViewerImage.draggable = false;
    els.imageViewerImage.alt = node.title || "画布图片";
    els.imageViewerTitle.textContent = node.title || "图片预览";
    state.viewerNodeRef = node;
    els.imageViewerCopyAllBtn.onclick = () => copyPlainText(
      [
        els.imageViewerTags.dataset.copyText,
        els.imageViewerNegative.dataset.copyText
          ? `Negative prompt: ${els.imageViewerNegative.dataset.copyText}` : "",
        els.imageViewerCharacters.dataset.copyText,
        els.imageViewerNote.dataset.copyText ? `Note:\n${els.imageViewerNote.dataset.copyText}` : "",
      ].filter(Boolean).join("\n\n"),
      "复制全部信息",
      () => els.imageViewer.focus({ preventScroll: true }),
    );
    els.imageViewerDownloadBtn.onclick = () => downloadImage(node);
    state.viewerLibraryAsset = libraryAsset;
    state.viewerNodeId = node.id || "";
    updateImageViewerSaveButton();
    const navItems = libraryAsset
      ? state.library.images
      : state.nodes.filter((item) => item.type === "image" && item.dataUrl);
    state.viewerNavItems = navItems;
    const navEnabled = navItems.length > 1;
    [els.imageViewerPrevBtn, els.imageViewerNextBtn].forEach((button) => {
      if (!button) return;
      button.hidden = !navEnabled;
      button.disabled = !navEnabled;
    });
    if (els.imageViewerFilterToggle) {
      els.imageViewerFilterToggle.checked = state.viewerShowFilteredTags;
    }
    els.imageViewerPlaceBtn.hidden = !libraryAsset;
    els.imageViewer.hidden = false;
    alignToastRegion();
    els.imageViewer.focus({ preventScroll: true });
    scheduleImageViewerFrameSync();
    renderImageViewerInfo(node);
    els.imageViewerDetails.scrollTop = scrollTop;
    const infoSequence = ++state.viewerInfoSequence;
    void hydrateImageGenerationMeta(node, libraryAsset).then(() => {
      if (infoSequence !== state.viewerInfoSequence || els.imageViewer.hidden) return;
      renderImageViewerInfo(node);
    });
    recordOperation(operationLabel, node.title || "图片");
  }

  async function stepImageViewer(delta) {
    const current = state.viewerPendingLibraryAsset || state.viewerLibraryAsset;
    if (current) {
      const items = state.library.images;
      const index = items.findIndex((item) => item.id === current.id);
      if (index < 0 || items.length < 2) return;
      const target = items[(index + delta + items.length) % items.length];
      await openLibraryImageViewer(target, { preserveState: true });
      return;
    }
    const items = Array.isArray(state.viewerNavItems)
      ? state.viewerNavItems
      : state.nodes.filter((item) => item.type === "image" && item.dataUrl);
    const index = items.findIndex((item) => item.id === state.viewerNodeId);
    if (index < 0 || items.length < 2) return;
    openImageViewer(items[(index + delta + items.length) % items.length], { preserveState: true });
  }

  function closeImageViewer() {
    state.viewerOpenSequence = (state.viewerOpenSequence || 0) + 1;
    state.viewerPendingLibraryAsset = null;
    const wasOpen = !els.imageViewer.hidden;
    state.viewerTagLookupSequence += 1;
    state.viewerInfoSequence += 1;
    els.imageViewer.hidden = true;
    alignToastRegion();
    els.imageViewerImage.removeAttribute("src");
    renderImageViewerTags("");
    els.imageViewerTitle.textContent = "图片预览";
    els.imageViewerMeta.textContent = "--";
    els.imageViewerNegative.textContent = "";
    els.imageViewerNegative.dataset.copyText = "";
    els.imageViewerNegativeSection.hidden = true;
    els.imageViewerNote.textContent = "";
    els.imageViewerNote.dataset.copyText = "";
    els.imageViewerNoteSection.hidden = true;
    els.imageViewerCharacters.replaceChildren();
    els.imageViewerCharacters.dataset.copyText = "";
    els.imageViewerCharactersSection.hidden = true;
    setImageViewerDetailsCollapsed(false);
    els.imageViewer.classList.remove("folded");
    state.viewerImageDimensions = { width: 0, height: 0 };
    state.viewerTagsFull = "";
    state.viewerTagsFiltered = "";
    state.viewerNodeRef = null;
    applyImageViewerLayout(0, 0);
    state.viewerLibraryAsset = null;
    state.viewerNodeId = "";
    state.viewerNavItems = [];
    els.imageViewerPlaceBtn.hidden = true;
    if (wasOpen) recordOperation("关闭图片预览");
  }

  function updateImageViewerSaveButton() {
    const assetId = state.viewerNodeRef?.assetId;
    const saved = !!state.viewerLibraryAsset || state.library.images.some((item) => item.id === assetId);
    const saving = state.savingLibraryAssetIds.has(assetId);
    els.imageViewerSaveBtn.disabled = !assetId || saved || saving;
    els.imageViewerSaveBtn.setAttribute("aria-pressed", String(saved));
    els.imageViewerSaveBtn.querySelector("span").textContent = saving ? "正在收藏…" : saved ? "已收藏" : "收藏到素材库";
    els.imageViewerSaveBtn.title = saved ? "已收藏到素材库" : "收藏到素材库";
  }


  function bindImageViewerEvents() {
    els.imageViewerStage.addEventListener("transitionend", (event) => {
      if (event.target === els.imageViewerStage) alignToastRegion();
    });
    els.imageViewerReuseBtn.addEventListener("click", () => reuseImageParameters(state.viewerNodeRef));
    els.imageViewerSaveBtn.addEventListener("click", () => saveImageToLibrary(state.viewerNodeRef));
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
    els.imageViewerFilterToggle?.addEventListener("change", () => {
      state.viewerShowFilteredTags = els.imageViewerFilterToggle.checked;
      recordOperation(
        "切换正向 Tags 过滤",
        state.viewerShowFilteredTags ? "只看内容标签" : "展示全部 tags",
      );
      applyImageViewerTagsView();
    });
    els.imageViewerFoldBtn?.addEventListener("click", (event) => {
      event.stopPropagation();
      clearImageViewerBottomLayoutLock(true);
      const folded = els.imageViewer.classList.toggle("folded");
      alignToastRegion();
      els.imageViewerFoldBtn.setAttribute("aria-expanded", String(!folded));
      els.imageViewerFoldBtn.setAttribute("aria-label", folded ? "展开信息栏" : "收起信息栏");
      els.imageViewerFoldBtn.title = folded ? "展开信息栏" : "收起信息栏";
      scheduleImageViewerFrameSync();
    });
    els.imageViewerPrevBtn?.addEventListener("click", (event) => { event.stopPropagation(); void stepImageViewer(-1); });
    els.imageViewerNextBtn?.addEventListener("click", (event) => { event.stopPropagation(); void stepImageViewer(1); });
    els.imageViewer.addEventListener("pointerdown", (event) => {
      // Keep the original selector contract: event.target.closest(".image-viewer-details, .image-viewer-place-btn")
      if (
        event.button !== 0
        || event.target.closest(
          ".image-viewer-details, .image-viewer-place-btn, .image-viewer-nav, .image-viewer-fold, .image-viewer-thumbs",
        )
      ) return;
      if (imageViewerPointHitsRenderedImage(event.clientX, event.clientY)) return;
      closeImageViewer();
    });
    els.imageViewerDetails.addEventListener("click", (event) => {
      const button = event.target.closest("[data-copy-target]");
      if (button) void copyViewerText(button.dataset.copyTarget, button.title);
    });
  }

  return {
    applyImageViewerLayout,
    scheduleImageViewerFrameSync,
    imageGenerationMeta,
    hydrateImageGenerationMeta,
    openImageViewer,
    stepImageViewer,
    closeImageViewer,
    updateImageViewerSaveButton,
    bindImageViewerEvents
  };
}

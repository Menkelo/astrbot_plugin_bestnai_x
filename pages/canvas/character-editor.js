// Canvas component with explicit dependencies; no build step required.
export function createCharacterEditor({
  MAX_CHAR_PROMPTS,
  attachedPanelViewportBounds,
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
  selectNode,
  state
}) {
  function positionCharacterEditor(card, editor) {
    if (!card?.isConnected || !editor || editor.hidden || !card.classList.contains("open")) return;
    const cardRect = card.getBoundingClientRect();
    const scale = Number(state.viewport.scale) || 1;
    const bounds = attachedPanelViewportBounds();
    const availableHeight = Math.max(1, bounds.bottom - bounds.top);
    editor.style.maxWidth = `${Math.max(1, window.innerWidth - 24) / scale}px`;
    editor.style.maxHeight = `${Math.min(520, availableHeight / scale)}px`;
    editor.style.minHeight = `${Math.min(190, availableHeight / scale)}px`;
    const editorRect = editor.getBoundingClientRect();
    const editorWidth = editorRect.width || 280 * scale;
    const gap = 10;
    const margin = 12;
    const fitsRight = cardRect.right + gap + editorWidth <= window.innerWidth - margin;
    const fitsLeft = cardRect.left >= editorWidth + gap + margin;
    const preferredLeft = fitsRight ? cardRect.right + gap : fitsLeft ? cardRect.left - gap - editorWidth : cardRect.left;
    const left = clamp(preferredLeft, margin, Math.max(margin, window.innerWidth - editorWidth - margin));
    editor.classList.toggle("place-left", !fitsRight && fitsLeft);
    editor.classList.toggle("place-overlay", !fitsRight && !fitsLeft);
    const height = editor.getBoundingClientRect().height;
    const top = clamp(cardRect.bottom - height, bounds.top, Math.max(bounds.top, bounds.bottom - height));
    editor.style.left = `${(left - cardRect.left) / scale}px`;
    editor.style.right = "auto";
    editor.style.top = `${(top - cardRect.top) / scale}px`;
    editor.style.bottom = "auto";
  }


  function makeCharacterCard(node, sourceImage, nodeElement) {
    const charPrompts = normalizeCharPromptEntries(
      node?.meta?.retagCharPrompts,
      { keepEmpty: true },
    );
    let characterCard = null;
    let characterSummary = null;
    const refreshSummary = () => {
      if (characterSummary) {
        const { entries, useCoords } = automaticRetagCharLayout(node);
        characterSummary.textContent = `${entries.length}/${charPrompts.length} 有效${
          useCoords ? " · 按坐标" : " · 按顺序"
        }`;
      }
    };
    const originalCharPrompts = Array.isArray(node.meta?.retagCharPromptsOriginal)
      ? normalizeCharPromptEntries(node.meta.retagCharPromptsOriginal, { keepEmpty: true })
      : (sourceImage ? charPrompts.map(cloneCharPromptEntry) : []);

    const characterPanel = document.createElement("section");
    characterPanel.className = "retag-character-panel";
    const characterEditorPopover = document.createElement("div");
    characterEditorPopover.className = "retag-character-editor-popover";
    characterEditorPopover.hidden = !charPrompts.length;
    characterEditorPopover.addEventListener("wheel", (event) => {
      if (scrollContainerConsumesWheel(characterEditorPopover, event)) event.stopPropagation();
    }, { passive: true });
    const editorTools = document.createElement("div");
    editorTools.className = "retag-character-editor-tools";
    const dismissEditor = document.createElement("button");
    dismissEditor.type = "button";
    dismissEditor.title = "关闭角色编辑";
    dismissEditor.setAttribute("aria-label", "关闭角色编辑");
    dismissEditor.appendChild(icon("x"));
    dismissEditor.addEventListener("click", (event) => {
      event.stopPropagation();
      characterEditorPopover.hidden = true;
    });
    editorTools.appendChild(dismissEditor);
    characterEditorPopover.appendChild(editorTools);

    const characterOptions = document.createElement("div");
    characterOptions.className = "retag-character-options";

    const restoreCharacters = document.createElement("button");
    restoreCharacters.type = "button";
    restoreCharacters.className = "retag-character-restore";
    restoreCharacters.textContent = sourceImage ? "恢复原图参数" : "清空角色";
    restoreCharacters.title = sourceImage
      ? "恢复原图角色提示词、坐标、启用状态和布局开关"
      : "清空当前角色列表和布局参数";
    restoreCharacters.addEventListener("click", (event) => {
      event.stopPropagation();
      pushHistory();
      node.meta = {
        ...(node.meta || {}),
        retagCharPrompts: originalCharPrompts.map((item) => ({
          ...item,
          ...(item.center ? { center: { ...item.center } } : {}),
        })),
        retagCharDisabled: [],
        retagCharacterExpanded: true,
      };
      clearDebugTrace(node);
      scheduleSave();
      renderNodes();
    });
    characterOptions.appendChild(restoreCharacters);

    const updateCharacterEntry = (index, patch) => {
      const current = charPrompts[index];
      if (!current) return;
      charPrompts[index] = { ...current, ...patch };
      node.meta = {
        ...(node.meta || {}),
        retagCharPrompts: charPrompts.map((item) => ({
          ...item,
          ...(item.center ? { center: { ...item.center } } : {}),
        })),
      };
      clearDebugTrace(node);
      scheduleSave();
    };

    const editText = (index, key, input) => {
      let historyCaptured = false;
      input.addEventListener("input", () => {
        if (!historyCaptured) {
          pushHistory();
          historyCaptured = true;
        }
        updateCharacterEntry(index, { [key]: input.value });
        refreshSummary();
      });
      input.addEventListener("blur", () => {
        historyCaptured = false;
      });
    };

    const characterRows = new Map();
    const characterEditors = new Map();
    const markerByIndex = new Map();
    let selectedCharacterIndex = -1;
    const serializeCharacterEntries = () => charPrompts.map((item) => ({
      ...item,
      ...(item.center ? { center: { ...item.center } } : {}),
    }));
    const selectCharacter = (index, focusEditor = false) => {
      selectedCharacterIndex = index;
      node._characterModuleSelectedIndex = index;
      characterRows.forEach((row, rowIndex) => row.classList.toggle("is-active", rowIndex === index));
      markerByIndex.forEach((marker, markerIndex) => marker.classList.toggle("is-active", markerIndex === index));
      characterEditorPopover.hidden = index < 0 || !charPrompts.length;
      const editor = characterEditors.get(index);
      if (focusEditor && editor?.prompt) {
        editor.prompt.focus({ preventScroll: true });
        editor.prompt.setSelectionRange(editor.prompt.value.length, editor.prompt.value.length);
      }
      if (index >= 0) {
        requestAnimationFrame(() => positionCharacterEditor(characterCard, characterEditorPopover));
      }
    };
    const addCharacterAt = (center = null) => {
      if (charPrompts.length >= MAX_CHAR_PROMPTS) return;
      pushHistory();
      if (!Array.isArray(node.meta?.retagCharPromptsOriginal)) {
        node.meta = {
          ...(node.meta || {}),
          retagCharPromptsOriginal: serializeCharacterEntries(),
        };
      }
      charPrompts.push({
        prompt: "",
        negative_prompt: "",
        position: "",
        center: center || randomCharacterCenter(charPrompts.map((item) => editableCharCenter(item))),
      });
      node.meta = {
        ...(node.meta || {}),
        retagCharPrompts: serializeCharacterEntries(),
        retagCharacterExpanded: true,
      };
      node._characterModuleSelectedIndex = charPrompts.length - 1;
      clearDebugTrace(node);
      scheduleSave();
      renderAll();
    };
    const addCharacter = () => addCharacterAt(null);
    const addCharacterButton = document.createElement("button");
    addCharacterButton.type = "button";
    addCharacterButton.className = "retag-character-add";
    addCharacterButton.append(icon("plus"), document.createTextNode("添加角色"));
    addCharacterButton.disabled = charPrompts.length >= MAX_CHAR_PROMPTS;
    addCharacterButton.title = `添加角色，最多 ${MAX_CHAR_PROMPTS} 个`;
    addCharacterButton.addEventListener("click", (event) => {
      event.stopPropagation();
      addCharacter();
    });
    characterOptions.prepend(addCharacterButton);
    const removeCharacter = (index) => {
      if (!charPrompts[index]) return;
      pushHistory();
      charPrompts.splice(index, 1);
      const disabled = retagCharDisabledIndexes(node)
        .filter((item) => item !== index)
        .map((item) => (item > index ? item - 1 : item));
      node.meta = {
        ...(node.meta || {}),
        retagCharPrompts: serializeCharacterEntries(),
        retagCharDisabled: disabled,
        retagCharacterExpanded: true,
      };
      node._characterModuleSelectedIndex = Math.min(index, charPrompts.length - 1);
      clearDebugTrace(node);
      scheduleSave();
      renderAll();
    };

    charPrompts.forEach((character, index) => {
      const characterRow = document.createElement("article");
      characterRow.className = "retag-character-row";
      const rowHead = document.createElement("div");
      rowHead.className = "retag-character-row-head";
      const enabledLabel = document.createElement("label");
      enabledLabel.className = "retag-character-enabled";
      const enabled = document.createElement("input");
      enabled.type = "checkbox";
      enabled.checked = retagCharEnabled(node, index);
      enabled.title = "是否把这个角色发送给 NovelAI";
      const roleName = document.createElement("strong");
      roleName.textContent = `角色 ${index + 1}`;
      enabledLabel.append(enabled, roleName);
      const centerSummary = document.createElement("span");
      const initialCenter = editableCharCenter(character);
      centerSummary.textContent = `(${initialCenter.x.toFixed(3)}, ${initialCenter.y.toFixed(3)})`;
      centerSummary.className = "retag-character-center-summary";
      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "retag-character-delete";
      deleteButton.title = `删除角色 ${index + 1}`;
      deleteButton.setAttribute("aria-label", `删除角色 ${index + 1}`);
      deleteButton.appendChild(icon("trash-2"));
      const deleteConfirm = document.createElement("button");
      deleteConfirm.type = "button";
      deleteConfirm.className = "retag-character-delete-confirm";
      deleteConfirm.title = `确认删除角色 ${index + 1}`;
      deleteConfirm.setAttribute("aria-label", `确认删除角色 ${index + 1}`);
      deleteConfirm.appendChild(icon("check"));
      deleteConfirm.hidden = true;
      let deletePending = false;
      const resetDeleteConfirmation = () => {
        deletePending = false;
        deleteConfirm.hidden = true;
        deleteButton.replaceChildren(icon("trash-2"));
        deleteButton.title = `删除角色 ${index + 1}`;
        deleteButton.setAttribute("aria-label", `删除角色 ${index + 1}`);
      };
      deleteConfirm.addEventListener("click", (event) => {
        event.stopPropagation();
        removeCharacter(index);
      });
      deleteButton.addEventListener("click", (event) => {
        event.stopPropagation();
        if (deletePending) {
          resetDeleteConfirmation();
          return;
        }
        deletePending = true;
        deleteConfirm.hidden = false;
        deleteButton.replaceChildren(icon("x"));
        deleteButton.title = "取消删除";
        deleteButton.setAttribute("aria-label", "取消删除");
      });
      const deleteActions = document.createElement("span");
      deleteActions.className = "retag-character-delete-actions";
      deleteActions.append(deleteConfirm, deleteButton);
      rowHead.append(enabledLabel, centerSummary, deleteActions);
      characterRow.appendChild(rowHead);
      characterRows.set(index, characterRow);

      enabled.addEventListener("change", (event) => {
        event.stopPropagation();
        pushHistory();
        const disabled = new Set(retagCharDisabledIndexes(node));
        if (enabled.checked) disabled.delete(index);
        else disabled.add(index);
        node.meta = {
          ...(node.meta || {}),
          retagCharDisabled: [...disabled].sort((left, right) => left - right),
        };
        characterRow.classList.toggle("is-disabled", !enabled.checked);
        syncCharacterPreview();
        clearDebugTrace(node);
        refreshSummary();
        scheduleSave();
      });
      characterRow.classList.toggle("is-disabled", !enabled.checked);

      const makeTextField = (labelText, placeholderText, key, value) => {
        const field = document.createElement("label");
        field.className = "retag-character-field";
        const caption = document.createElement("span");
        caption.textContent = labelText;
        const input = document.createElement("textarea");
        input.className = "retag-character-text";
        input.dataset.characterIndex = String(index);
        input.dataset.characterField = key;
        input.setAttribute("aria-label", `角色 ${index + 1}${labelText}提示词`);
        input.rows = 4;
        input.maxLength = 2000;
        input.value = String(value || "");
        input.placeholder = placeholderText;
        input.addEventListener("pointerdown", (event) => event.stopPropagation());
        editText(index, key, input);
        field.append(caption, input);
        return field;
      };

      const promptField = makeTextField("正面",
        "例如：外观、服饰、表情与动作",
        "prompt",
        character.prompt,
      );
      const negativeField = makeTextField("负面",
        "填写不希望出现在该角色上的特征",
        "negative_prompt",
        character.negative_prompt,
      );
      characterEditors.set(index, {
        prompt: promptField.querySelector("textarea"),
        negative: negativeField.querySelector("textarea"),
      });
      characterRow.append(promptField, negativeField);

      characterEditorPopover.appendChild(characterRow);
    });
    const layoutTools = document.createElement("div");
    layoutTools.className = "retag-character-layouts";
    const layoutLabel = document.createElement("span");
    layoutLabel.textContent = "快捷布局";
    layoutLabel.className = "retag-character-layout-label";
    layoutTools.appendChild(layoutLabel);

    const applyCharacterCenters = (centers) => {
      if (!Array.isArray(centers) || centers.length !== charPrompts.length) return;
      pushHistory();
      charPrompts.forEach((item, index) => {
        item.center = {
          x: centers[index].x,
          y: centers[index].y,
        };
        item.position = "";
      });
      node.meta = {
        ...(node.meta || {}),
        retagCharPrompts: charPrompts.map((item) => ({
          ...item,
          ...(item.center ? { center: { ...item.center } } : {}),
        })),
      };
      clearDebugTrace(node);
      syncCharacterPreview();
      refreshSummary();
      scheduleSave();
    };

    const randomizeCharacterCenters = () => {
      const centers = charPrompts.map((item) => editableCharCenter(item));
      const disabled = new Set(retagCharDisabledIndexes(node));
      const placed = centers.filter((_, index) => disabled.has(index));
      charPrompts.forEach((item, index) => {
        if (disabled.has(index)) return;
        const center = randomCharacterCenter(placed);
        centers[index] = center;
        placed.push(center);
      });
      applyCharacterCenters(centers);
    };

    const uniformCenters = (count) => Array.from(
      { length: count },
      (_, index) => ({ x: (index + 1) / (count + 1), y: 0.5 }),
    );
    const threeCharacterCenters = () => [
      { x: 0.5, y: 0.28 },
      { x: 0.28, y: 0.66 },
      { x: 0.72, y: 0.66 },
    ];
    const fourCharacterCenters = () => [
      { x: 0.28, y: 0.30 },
      { x: 0.72, y: 0.30 },
      { x: 0.28, y: 0.70 },
      { x: 0.72, y: 0.70 },
    ];
    [
      ["均匀横向", () => uniformCenters(charPrompts.length), 0],
      ["三人构图", threeCharacterCenters, 3],
      ["四人构图", fourCharacterCenters, 4],
      ["随机位置", randomizeCharacterCenters, 0],
    ].forEach(([labelText, buildCenters, requiredCount]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "retag-character-layout";
      button.textContent = labelText;
      button.disabled = !charPrompts.length
        || (requiredCount > 0 && charPrompts.length !== requiredCount);
      button.title = button.disabled
        ? (!charPrompts.length ? "请先添加角色" : `${labelText}仅适用于 ${requiredCount} 个角色`)
        : `将 ${charPrompts.length} 个角色${labelText === "均匀横向" ? "均匀横向排列" : "排列为" + labelText}`;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        applyCharacterCenters(buildCenters());
      });
      layoutTools.appendChild(button);
    });
    const preview = document.createElement("div");
    preview.className = "retag-character-preview";
    const previewHelp = document.createElement("p");
    previewHelp.className = "retag-character-preview-help";
    previewHelp.textContent = "点击编号编辑，拖动圆点调整位置；也可双击画布添加角色。";
    const previewSurface = document.createElement("div");
    previewSurface.className = "retag-character-preview-surface";
    const ratioText = String(
      node.ratio
        || (sourceImage?.meta?.width && sourceImage?.meta?.height
          ? `${sourceImage.meta.width}:${sourceImage.meta.height}`
          : "2:3"),
    );
    const ratioMatch = ratioText.match(/(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)/);
    const ratioWidth = ratioMatch ? Number(ratioMatch[1]) : 1;
    const ratioHeight = ratioMatch ? Number(ratioMatch[2]) : 1;
    const targetRatio = ratioWidth > 0 && ratioHeight > 0 ? ratioWidth / ratioHeight : 1;
    previewSurface.style.aspectRatio = "1 / 1";
    const cropFrame = document.createElement("div");
    cropFrame.className = "retag-character-crop-frame";
    cropFrame.dataset.ratio = ratioMatch ? `${ratioMatch[1]}:${ratioMatch[2]}` : "1:1";
    if (targetRatio >= 1) {
      cropFrame.style.width = "100%";
      cropFrame.style.height = `${100 / targetRatio}%`;
    } else {
      cropFrame.style.width = `${targetRatio * 100}%`;
      cropFrame.style.height = "100%";
    }
    const markerLayer = document.createElement("div");
    markerLayer.className = "retag-character-marker-layer";
    cropFrame.appendChild(markerLayer);
    previewSurface.appendChild(cropFrame);
    preview.append(previewSurface);

    const syncCharacterPreview = () => {
      charPrompts.forEach((character, index) => {
        const center = editableCharCenter(character);
        const marker = markerByIndex.get(index);
        if (marker) {
          marker.style.left = `${center.x * 100}%`;
          marker.style.top = `${center.y * 100}%`;
          marker.classList.toggle("is-disabled", !retagCharEnabled(node, index));
          marker.classList.toggle("is-active", selectedCharacterIndex === index);
          marker.title = `角色 ${index + 1}：(${center.x.toFixed(3)}, ${center.y.toFixed(3)})\n拖动调整位置`;
        }
        const row = characterRows.get(index);
        const summary = row?.querySelector(".retag-character-center-summary");
        if (summary) summary.textContent = `(${center.x.toFixed(3)}, ${center.y.toFixed(3)})`;
      });
    };

    // 空白画布双击直接在点击位置创建角色，竖图也不需要先找标题栏按钮。
    cropFrame.addEventListener("dblclick", (event) => {
      if (event.target.closest(".retag-character-marker")) return;
      if (charPrompts.length >= MAX_CHAR_PROMPTS) return;
      const rect = cropFrame.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      event.preventDefault();
      event.stopPropagation();
      addCharacterAt({
        x: clamp((event.clientX - rect.left) / rect.width, 0, 1),
        y: clamp((event.clientY - rect.top) / rect.height, 0, 1),
      });
    });

    charPrompts.forEach((_, index) => {
      const marker = document.createElement("button");
      marker.type = "button";
      marker.className = "retag-character-marker";
      marker.textContent = String(index + 1);
      marker.setAttribute("aria-label", `拖动角色 ${index + 1} 的中心点`);
      marker.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        selectCharacter(index, true);
      });
      marker.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        const pointerId = event.pointerId;
        const startX = event.clientX;
        const startY = event.clientY;
        let moved = false;
        try { cropFrame.setPointerCapture(pointerId); } catch (_) { /* ignore */ }
        const updateFromPointer = (moveEvent) => {
          if (!moved && Math.hypot(moveEvent.clientX - startX, moveEvent.clientY - startY) < 4) return;
          if (!moved) {
            moved = true;
            pushHistory();
          }
          const rect = cropFrame.getBoundingClientRect();
          if (!rect.width || !rect.height) return;
          const center = {
            x: clamp((moveEvent.clientX - rect.left) / rect.width, 0, 1),
            y: clamp((moveEvent.clientY - rect.top) / rect.height, 0, 1),
          };
          updateCharacterEntry(index, { center, position: "" });
          syncCharacterPreview();
          refreshSummary();
        };
        const stopDrag = () => {
          cropFrame.removeEventListener("pointermove", updateFromPointer);
          cropFrame.removeEventListener("pointercancel", stopDrag);
          try { cropFrame.releasePointerCapture(pointerId); } catch (_) { /* ignore */ }
          if (moved) scheduleSave();
        };
        const finish = () => {
          if (!moved) selectCharacter(index, true);
          stopDrag();
        };
        cropFrame.addEventListener("pointermove", updateFromPointer);
        cropFrame.addEventListener("pointerup", finish, { once: true });
        cropFrame.addEventListener("pointercancel", stopDrag);
      });
      markerLayer.appendChild(marker);
      markerByIndex.set(index, marker);
    });
    // 常用操作置顶，布局按钮在预览下方按两列排列，角色编辑保留在侧栏。
    characterPanel.append(characterOptions, preview, layoutTools, previewHelp);
    syncCharacterPreview();
    if (charPrompts.length) {
      const selectedIndex = clamp(
        Number(node._characterModuleSelectedIndex) || 0,
        0,
        charPrompts.length - 1,
      );
      selectCharacter(selectedIndex, false);
    }

    characterCard = document.createElement("aside");
    characterCard.className = "retag-layer-card retag-character-card";
    characterCard.dataset.nodeId = node.id;
    characterCard.addEventListener("pointerdown", (event) => {
      // 中键拖动要继续冒泡到画布，让附加卡片区域也能平移画布。
      if (event.button === 1) return;
      event.stopPropagation();
      bringNodeToFront(node.id, nodeElement);
      if (!isNodeSelected(node.id)) selectNode(node.id);
    });
    const characterToggle = document.createElement("button");
    characterToggle.type = "button";
    characterToggle.className = "retag-layer-toggle";
    characterToggle.setAttribute("aria-expanded", "false");
    // 标题按钮只切换展开状态。
    characterToggle.addEventListener("pointerdown", (event) => {
      if (event.button !== 1) event.stopPropagation();
    });
    const characterToggleTitle = document.createElement("span");
    characterToggleTitle.className = "retag-layer-title";
    characterToggleTitle.append(icon("users-round"), document.createTextNode("角色模块"));
    characterSummary = document.createElement("span");
    characterSummary.className = "retag-layer-summary";
    const characterChevron = icon("chevron-up", "retag-layer-chevron");
    characterToggle.append(characterToggleTitle, characterSummary, characterChevron);
    const characterCardHead = document.createElement("div");
    characterCardHead.className = "retag-character-card-head";
    characterCardHead.append(characterToggle);
    const characterBody = document.createElement("div");
    characterBody.className = "retag-layer-body retag-character-body";
    characterBody.hidden = true;
    characterBody.addEventListener("wheel", (event) => {
      if (scrollContainerConsumesWheel(characterBody, event)) event.stopPropagation();
    }, { passive: true });
    characterBody.appendChild(characterPanel);
    const setCharacterOpen = (open) => {
      characterCard.classList.toggle("open", open);
      characterBody.hidden = !open;
      characterEditorPopover.hidden = !open || !charPrompts.length || selectedCharacterIndex < 0;
      characterToggle.setAttribute("aria-expanded", String(open));
      scheduleAttachedPanelLayout();
    };
    characterToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const open = !characterCard.classList.contains("open");
      node.meta = { ...(node.meta || {}), retagCharacterExpanded: open };
      setCharacterOpen(open);
      scheduleSave();
    });
    setCharacterOpen(node.meta?.retagCharacterExpanded === true);
    // 标题栏放在正文之后，整张卡以底边锚定时正文只会向上展开，
    // 标题栏本身在展开/收起前后保持同一个位置。
    characterCard.append(characterBody, characterCardHead, characterEditorPopover);
    refreshSummary();
    return characterCard;
  }

  return {
    positionCharacterEditor,
    makeCharacterCard
  };
}

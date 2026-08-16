(function () {
  const $ = (id) => document.getElementById(id);
  const DRAFT_KEY = "aitag.studio.draft.v1";
  const HISTORY_KEY = "aitag.studio.history.v1";

  const state = {
    workId: 0,
    pageIndex: 0,
    comment: null,
    params: {},
    beforeTexts: null,
    generating: false,
    undoStack: [],
    defaultOptimizeMode: "smart",
    sizePresets: [],
    samplers: [],
    history: [],
    draftId: "",
    sourceProvider: "",
    sourceLabel: "",
    /** AITag remote identity for generate grouping / labels */
    onlineWorkIdStr: "",
    onlineSourceTitle: "",
    onlineSourceThumb: "",
    /** @type {Array<{image_index:number, draft:object, slot_indexes?:number[]}>} */
    aitagPages: [],
    action: "generate",
    sourceImage: "",
    painting: false,
  };

  async function api(path, opts) {
    if (!window.ApiClient) throw new Error("ApiClient is not loaded");
    return window.ApiClient.request(path, opts || {});
  }

  function toast(msg, kind) {
    try {
      if (window.UiToast) {
        if (kind === "ok") return window.UiToast.ok(msg);
        if (kind === "err") return window.UiToast.err(msg);
        return window.UiToast.show(msg);
      }
    } catch (_) { /* ignore */ }
  }

  function setStatus(text, ok, warn) {
    const el = $("studioStatus");
    if (!el) return;
    el.textContent = text || "";
    el.className = "studio-status"
      + (text ? (warn ? " warn" : (ok ? " ok" : " err")) : "");
  }

  function setChip(key, cls, label) {
    const el = document.querySelector(`#studioReady [data-chip="${key}"]`);
    if (!el) return;
    el.className = "studio-chip " + (cls || "warn");
    if (label) el.textContent = label;
  }

  function refreshReady() {
    const hasPrompt = !!(textsFromForm().prompt || textsFromForm().base_caption);
    if (state.sourceProvider === "aitag-online") {
      setChip("source", "ok", state.sourceLabel || "AITag 在线");
    } else {
      setChip("source", state.workId ? "ok" : "warn", state.workId ? `来源 #${state.workId}` : "无来源");
    }
    setChip("prompt", hasPrompt ? "ok" : "warn", hasPrompt ? "咒语就绪" : "待填咒语");
  }

  function isUsableDraft(draft) {
    if (!draft || typeof draft !== "object") return false;
    const texts = draft.texts || {};
    return !!(texts.prompt || texts.base_caption || (texts.char_captions || []).length || draft.comment);
  }

  function renderAitagPageTabs() {
    const host = $("studioAitagPages");
    if (!host) return;
    const pages = Array.isArray(state.aitagPages) ? state.aitagPages : [];
    if (state.sourceProvider !== "aitag-online" || pages.length <= 1) {
      host.classList.add("hidden");
      host.innerHTML = "";
      return;
    }
    host.classList.remove("hidden");
    host.innerHTML = pages.map((page) => {
      const idx = Number(page.image_index || 0);
      const active = idx === Number(state.pageIndex || 0);
      return `<button type="button" class="studio-btn${active ? "" : " ghost"} studio-aitag-page-tab" data-aitag-page="${idx}" aria-pressed="${active ? "true" : "false"}">p${idx}</button>`;
    }).join("");
    host.querySelectorAll("[data-aitag-page]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const idx = Number(btn.getAttribute("data-aitag-page") || 0);
        switchAitagPage(idx);
      });
    });
  }

  function flushCurrentAitagPage() {
    if (state.sourceProvider !== "aitag-online") return;
    if (!Array.isArray(state.aitagPages) || !state.aitagPages.length) return;
    const idx = Number(state.pageIndex) || 0;
    const texts = textsFromForm();
    let comment = null;
    try { comment = commentFromForm(); } catch (_) { comment = state.comment; }
    const params = {
      width: $("studioWidth")?.value,
      height: $("studioHeight")?.value,
      steps: $("studioSteps")?.value,
      scale: $("studioScale")?.value,
      seed: $("studioSeed")?.value,
      sampler: $("studioSampler")?.value,
      batch: $("studioBatchCount")?.value,
    };
    const refs = {
      vibe: $("studioVibeUrl")?.value || "",
      char: $("studioCharRefUrl")?.value || "",
      strength: $("studioVibeStrength")?.value || "0.6",
    };
    state.aitagPages = state.aitagPages.map((p) => {
      if (Number(p.image_index) !== idx) return p;
      const prev = (p.draft && typeof p.draft === "object") ? p.draft : {};
      return {
        ...p,
        draft: {
          ...prev,
          texts,
          comment: comment || prev.comment || null,
          params: { ...(prev.params || {}), ...params },
          refs: { ...(prev.refs || {}), ...refs },
          pageIndex: idx,
          source: prev.source || {
            provider: "aitag-online",
            imageIndex: idx,
            workIdStr: state.onlineWorkIdStr || "",
          },
        },
      };
    });
  }

  function switchAitagPage(pageIndex) {
    flushCurrentAitagPage();
    const pages = Array.isArray(state.aitagPages) ? state.aitagPages : [];
    const hit = pages.find((p) => Number(p.image_index) === Number(pageIndex));
    if (!hit || !hit.draft || typeof hit.draft !== "object") {
      setStatus(`没有 p${pageIndex} 的在线草稿`, false);
      return false;
    }
    const pack = {
      ...hit.draft,
      draftId: state.draftId,
      sourceKind: "aitag-online",
      source: hit.draft.source || { provider: "aitag-online", imageIndex: pageIndex },
      pageIndex: Number(pageIndex) || 0,
      pages: state.aitagPages,
      texts: hit.draft.texts,
      params: hit.draft.params,
      refs: hit.draft.refs,
      comment: hit.draft.comment,
    };
    return applyDraftObject(pack, `已切换到在线草稿 p${pageIndex}（未生成）`);
  }

  function applyDraftObject(draft, statusText) {
    if (!isUsableDraft(draft)) return false;
    state.draftId = String(draft.draftId || draft.draft_id || "").trim();
    const source = draft.source && typeof draft.source === "object" ? draft.source : {};
    state.sourceProvider = String(source.provider || draft.sourceKind || "").trim();
    if (Array.isArray(draft.pages) && draft.pages.length) {
      state.aitagPages = draft.pages
        .map((p) => ({
          image_index: Number(p.image_index ?? p.draft?.pageIndex ?? 0) || 0,
          slot_indexes: p.slot_indexes || [],
          draft: p.draft || p,
        }))
        .filter((p) => p.draft && typeof p.draft === "object");
    } else if (state.sourceProvider !== "aitag-online") {
      state.aitagPages = [];
    }
    if (state.sourceProvider === "aitag-online") {
      const workLabel = source.workId || source.workIdStr || draft.onlineReference?.workId || "";
      const pageN = state.aitagPages.length;
      state.sourceLabel = workLabel
        ? `AITag #${workLabel}${pageN > 1 ? ` · ${pageN} 页` : ""}`
        : "AITag 在线";
      state.workId = 0;
      state.pageIndex = Number(draft.pageIndex || source.imageIndex || 0) || 0;
      state.onlineWorkIdStr = String(
        source.workIdStr
        || source.workId
        || draft.onlineWorkIdStr
        || draft.onlineReference?.workId
        || state.onlineWorkIdStr
        || ""
      ).trim();
      state.onlineSourceTitle = String(
        source.title
        || draft.title
        || draft.sourceTitle
        || state.onlineSourceTitle
        || ""
      ).trim();
      state.onlineSourceThumb = String(
        source.thumb
        || draft.thumb
        || draft.sourceThumb
        || state.onlineSourceThumb
        || ""
      ).trim();
    } else if (draft.workId) {
      state.workId = draft.workId;
      state.pageIndex = Number(draft.pageIndex || 0) || 0;
      state.aitagPages = [];
      state.onlineWorkIdStr = "";
      state.onlineSourceTitle = "";
      state.onlineSourceThumb = "";
    }
    if (draft.comment && typeof draft.comment === "object") {
      state.comment = draft.comment;
    }
    if (draft.texts) applyTextsToForm(draft.texts);
    if (draft.params) fillParams(draft.params);
    if (draft.refs) {
      if ($("studioVibeUrl")) $("studioVibeUrl").value = draft.refs.vibe || "";
      if ($("studioCharRefUrl")) $("studioCharRefUrl").value = draft.refs.char || "";
      if ($("studioVibeStrength") && draft.refs.strength) {
        $("studioVibeStrength").value = draft.refs.strength;
        if ($("studioStrengthVal")) $("studioStrengthVal").textContent = Number(draft.refs.strength).toFixed(2);
      }
    }
    let draftSaved = true;
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({
        ...draft,
        draftId: state.draftId,
        pages: state.aitagPages,
        pageIndex: state.pageIndex,
        ts: Date.now(),
      }));
    } catch (_) {
      draftSaved = false;
    }
    renderAitagPageTabs();
    refreshReady();
    if (!draftSaved) {
      // 静默吞掉会让用户以为草稿已持久化，刷新后才发现丢失
      setStatus("本地草稿保存失败（缓存可能已满），刷新前请勿关闭页面", false, true);
    } else if (statusText) {
      setStatus(statusText, true, true);
    }
    return true;
  }

  function pickAitagDraftFromServerResult(result, preferredPageIndex) {
    const pages = Array.isArray(result?.pages) ? result.pages : [];
    let chosen = result?.draft && typeof result.draft === "object" ? result.draft : null;
    let pageIndex = Number(
      preferredPageIndex != null && preferredPageIndex !== ""
        ? preferredPageIndex
        : (result?.image_index ?? result?.draft?.pageIndex ?? 0)
    ) || 0;
    if (pages.length) {
      const hit = pages.find((p) => Number(p?.image_index) === pageIndex)
        || pages.find((p) => Number(p?.draft?.pageIndex) === pageIndex)
        || pages[0];
      if (hit && hit.draft && typeof hit.draft === "object") {
        chosen = hit.draft;
        pageIndex = Number(hit.image_index ?? hit.draft.pageIndex ?? pageIndex) || 0;
      }
    }
    if (!chosen) return null;
    return {
      ...chosen,
      draftId: result.draft_id || result.draftId || "",
      recipe: result.recipe || null,
      sourceKind: "aitag-online",
      texts: chosen.texts,
      params: chosen.params,
      refs: chosen.refs,
      comment: chosen.comment,
      source: chosen.source || { provider: "aitag-online" },
      pageIndex,
      // Keep full multi-page package for later page switches / local restore.
      pages: pages.map((p) => ({
        image_index: p.image_index,
        slot_indexes: p.slot_indexes || [],
        draft: p.draft,
      })).filter((p) => p.draft),
      partial: !!result.partial,
      failed_pages: result.failed_pages || [],
    };
  }

  async function restoreDraftFromServer(draftId, preferredPageIndex) {
    const id = String(draftId || "").trim();
    if (!/^[0-9a-f]{16}$/i.test(id)) return false;
    const result = await api(`/api/nai/aitag/drafts/${encodeURIComponent(id)}`);
    if (!result || result.ok === false || Number(result.generation_calls) !== 0) {
      throw new Error(result?.message || "服务端草稿不可用或未证明零生成调用");
    }
    const draft = pickAitagDraftFromServerResult(result, preferredPageIndex);
    if (!draft) return false;
    const pageN = Array.isArray(draft.pages) ? draft.pages.length : 1;
    const note = pageN > 1
      ? `已从服务端恢复 AITag 草稿（p${draft.pageIndex}，共 ${pageN} 页未生成）`
      : "已从服务端恢复 AITag 草稿（未生成，可继续编辑）";
    return applyDraftObject(draft, note);
  }

  async function restoreLatestServerDraft(preferredPageIndex) {
    const result = await api("/api/nai/aitag/drafts/latest/restore", { method: "POST", body: {} });
    if (!result || result.ok === false || Number(result.generation_calls) !== 0) return false;
    const draft = pickAitagDraftFromServerResult(result, preferredPageIndex);
    if (!draft) return false;
    const pageN = Array.isArray(draft.pages) ? draft.pages.length : 1;
    const note = pageN > 1
      ? `已恢复最近 AITag 服务端草稿（p${draft.pageIndex}，共 ${pageN} 页）`
      : "已恢复最近一次 AITag 服务端草稿（未生成）";
    return applyDraftObject(draft, note);
  }

  function textsFromForm() {
    const charsRaw = ($("studioCharCaptions") || {}).value || "";
    const charLines = charsRaw.split("\n").map((s) => s.trim()).filter(Boolean);
    return {
      prompt: (($("studioPrompt") || {}).value || "").trim(),
      base_caption: (($("studioBase") || {}).value || "").trim(),
      uc: (($("studioUc") || {}).value || "").trim(),
      char_captions: charLines,
    };
  }

  function applyTextsToForm(texts) {
    if (!texts) return;
    if ($("studioPrompt")) $("studioPrompt").value = texts.prompt || texts.base_caption || "";
    if ($("studioBase")) $("studioBase").value = texts.base_caption || "";
    if ($("studioUc")) $("studioUc").value = texts.uc || "";
    if ($("studioCharCaptions")) {
      // 兼容 V4 对象格式 {char_caption, centers} / 在线草稿 {caption, center} 与纯字符串行，避免 [object Object]
      $("studioCharCaptions").value = (texts.char_captions || [])
        .map((c) => (typeof c === "string" ? c : String((c && (c.char_caption || c.caption)) || "")))
        .filter(Boolean)
        .join("\n");
    }
    refreshReady();
    saveDraftLocal();
  }

  function pushUndoSnapshot() {
    state.undoStack.push(JSON.stringify(textsFromForm()));
    if (state.undoStack.length > 12) state.undoStack.shift();
  }

  function commentFromForm() {
    const base = copyComment(state.comment || {});
    const texts = textsFromForm();
    base.prompt = texts.prompt || texts.base_caption;
    base.uc = texts.uc;
    const v4 = base.v4_prompt || {};
    const cap = v4.caption || {};
    cap.base_caption = texts.base_caption || texts.prompt;
    if (texts.char_captions && texts.char_captions.length) {
      const old = cap.char_captions || [];
      cap.char_captions = texts.char_captions.map((line, i) => {
        const prev = old[i] && typeof old[i] === "object" ? old[i] : {};
        const centers = prev.centers || (prev.center ? [prev.center] : [{ x: 0.5, y: 0.5 }]);
        return { char_caption: line, centers };
      });
    }
    v4.caption = cap;
    base.v4_prompt = v4;
    base.width = parseInt($("studioWidth")?.value || state.params.width || 832, 10);
    base.height = parseInt($("studioHeight")?.value || state.params.height || 1216, 10);
    base.steps = parseInt($("studioSteps")?.value || state.params.steps || 28, 10);
    base.scale = parseFloat($("studioScale")?.value || state.params.scale || 5);
    const seedVal = ($("studioSeed") || {}).value;
    base.seed = seedVal === "" ? null : parseInt(seedVal, 10);
    base.sampler = ($("studioSampler") || {}).value || state.params.sampler || "k_euler_ancestral";
    const vibeUrl = (($("studioVibeUrl") || {}).value || "").trim();
    if (vibeUrl) {
      base.xianyun_vibe = {
        reference_images: [vibeUrl],
        reference_strength_multiple: [parseFloat($("studioVibeStrength")?.value || "0.6")],
        reference_information_extracted_multiple: [1.0],
      };
    } else {
      delete base.xianyun_vibe;
    }
    const charRef = (($("studioCharRefUrl") || {}).value || "").trim();
    if (charRef) {
      base.reference_image_multiple = [charRef];
      base.reference_strength_multiple = [parseFloat($("studioVibeStrength")?.value || "0.6")];
    } else if (!base.reference_image_multiple) {
      delete base.reference_strength_multiple;
    }
    const action = (($("studioAction") || {}).value || state.action || "generate").trim();
    state.action = action;
    if (action === "img2img" || action === "inpaint") {
      base.action = action;
      base.requested_action = action;
      base.strength = parseFloat($("studioImg2ImgStrength")?.value || "0.55");
      const canvasImage = exportCanvasBase64($("studioImgCanvas"));
      if (canvasImage) base.image = canvasImage;
      else if (state.sourceImage) base.image = state.sourceImage;
      if (action === "inpaint") {
        const mask = exportMaskBase64();
        if (mask) base.mask = mask;
      }
    } else {
      delete base.action;
      delete base.requested_action;
      delete base.image;
      delete base.mask;
      delete base.strength;
    }
    return base;
  }

  function exportCanvasBase64(canvas) {
    if (!canvas || !canvas.width) return "";
    const raw = canvas.toDataURL("image/png");
    const comma = raw.indexOf(",");
    return comma >= 0 ? raw.slice(comma + 1) : raw;
  }

  function exportMaskBase64() {
    return exportCanvasBase64($("studioMaskCanvas"));
  }

  function drawStudioSource(dataUrl) {
    const imageCanvas = $("studioImgCanvas");
    const maskCanvas = $("studioMaskCanvas");
    if (!imageCanvas || !maskCanvas) return;
    const image = new Image();
    image.onload = () => {
      const width = Math.max(1, image.naturalWidth || image.width);
      const height = Math.max(1, image.naturalHeight || image.height);
      const scale = Math.min(1, 640 / Math.max(width, height));
      imageCanvas.width = Math.max(1, Math.round(width * scale));
      imageCanvas.height = Math.max(1, Math.round(height * scale));
      maskCanvas.width = imageCanvas.width;
      maskCanvas.height = imageCanvas.height;
      const ctx = imageCanvas.getContext("2d");
      ctx && ctx.drawImage(image, 0, 0, imageCanvas.width, imageCanvas.height);
      const maskCtx = maskCanvas.getContext("2d");
      if (maskCtx) {
        maskCtx.fillStyle = "#000000";
        maskCtx.fillRect(0, 0, maskCanvas.width, maskCanvas.height);
      }
    };
    image.src = dataUrl;
  }

  function syncStudioActionUi() {
    const action = (($("studioAction") || {}).value || "generate").trim();
    state.action = action;
    const panel = $("studioCanvasPanel");
    const strengthField = $("studioStrengthField");
    const mask = $("studioMaskCanvas");
    if (panel) panel.classList.toggle("hidden", action === "generate");
    if (strengthField) strengthField.classList.toggle("hidden", action === "generate");
    if (mask) mask.classList.toggle("active", action === "inpaint");
  }

  async function loadStudioSourceImage() {
    if (!state.workId) {
      setStatus("先导入作品，才能加载 img2img / inpaint 原图", false, true);
      return;
    }
    const data = await api(`/api/studio/source-image?work_id=${encodeURIComponent(state.workId)}&page_index=${state.pageIndex || 0}`);
    const encoded = String(data.image || "");
    if (!encoded) throw new Error("作品没有本地原图");
    state.sourceImage = encoded;
    drawStudioSource("data:image/png;base64," + encoded);
    setStatus("已加载本地原图，可切换 img2img / inpaint", true);
  }

  function copyComment(c) {
    return JSON.parse(JSON.stringify(c || {}));
  }

  function renderCompare(before, after) {
    const b = $("studioBefore");
    const a = $("studioAfter");
    if (b) b.textContent = formatTexts(before);
    if (a) a.textContent = formatTexts(after);
  }

  function formatTexts(t) {
    if (!t) return "";
    const parts = [];
    if (t.base_caption) parts.push("[base]\n" + t.base_caption);
    if (t.char_captions && t.char_captions.length) {
      t.char_captions.forEach((c, i) => parts.push(`[char${i + 1}]\n${c}`));
    } else if (t.prompt) parts.push(t.prompt);
    if (t.uc) parts.push("[uc]\n" + t.uc);
    return parts.join("\n\n");
  }

  function fillParams(params) {
    const p = params || {};
    if ($("studioWidth")) $("studioWidth").value = p.width || 832;
    if ($("studioHeight")) $("studioHeight").value = p.height || 1216;
    if ($("studioSteps")) $("studioSteps").value = p.steps || 28;
    if ($("studioScale")) $("studioScale").value = p.scale != null ? p.scale : 5;
    if ($("studioSeed")) $("studioSeed").value = p.seed != null && p.seed !== "" ? String(p.seed) : "";
    if ($("studioSampler")) {
      const s = p.sampler || "k_euler_ancestral";
      if (![...$("studioSampler").options].some((o) => o.value === s)) {
        const opt = document.createElement("option");
        opt.value = s;
        opt.textContent = s;
        $("studioSampler").appendChild(opt);
      }
      $("studioSampler").value = s;
    }
    highlightSizePreset();
  }

  function syncRefWorkId() {
    if ($("studioRefWorkId") && state.workId) {
      $("studioRefWorkId").value = String(state.workId);
    }
  }

  function setPreviewImage(url) {
    const img = $("studioPreviewImg");
    const box = img && img.closest(".studio-preview-out");
    if (!img) return;
    if (url) {
      img.src = url;
      img.style.display = "block";
      if (box) box.classList.add("has-image");
    } else {
      img.removeAttribute("src");
      img.style.display = "none";
      if (box) box.classList.remove("has-image");
    }
  }

  function showGenProgress(on, label) {
    const el = $("studioGenProgress");
    const lab = $("studioGenProgressLabel");
    if (!el) return;
    el.classList.toggle("hidden", !on);
    if (lab && label) lab.textContent = label;
  }

  async function loadImport(workId, pageIndex) {
    const sourceWorkId = window.WorkBridge?.normalizeWorkId?.(workId) || String(workId || "");
    setStatus("正在导入作品咒语…", true);
    const data = await api(`/api/studio/import?work_id=${encodeURIComponent(sourceWorkId)}&page_index=${pageIndex || 0}`);
    state.workId = data.work_id;
    state.pageIndex = data.page_index;
    state.comment = data.comment;
    state.params = data.params || {};
    state.beforeTexts = data.texts;
    state.undoStack = [];
    applyTextsToForm(data.texts);
    fillParams(state.params);
    renderCompare(data.texts, data.texts);
    syncRefWorkId();
    const src = $("studioSource");
    if (src) {
      const detailUrl = window.WorkBridge?.withGalleryContext?.(`/i/${encodeURIComponent(String(data.work_id))}`) || `/i/${encodeURIComponent(String(data.work_id))}`;
      src.innerHTML = `来源资产 <a href="${detailUrl}" target="_blank" rel="noopener">#${data.work_id}</a> · ${escapeHtml(data.title || "")}`;
    }
    const back = $("studioBackDetail");
    if (back) {
      back.href = window.WorkBridge?.withGalleryContext?.(`/i/${encodeURIComponent(String(data.work_id))}`) || `/i/${encodeURIComponent(String(data.work_id))}`;
      back.classList.remove("hidden");
    }
    const restore = $("studioRestoreOriginal");
    if (restore) restore.classList.remove("hidden");
    const sourceThumb = $("studioSourceThumb");
    if (sourceThumb && data.thumb) {
      const detailUrl = window.WorkBridge?.withGalleryContext?.(`/i/${encodeURIComponent(String(data.work_id))}`) || `/i/${encodeURIComponent(String(data.work_id))}`;
      sourceThumb.innerHTML = `<a href="${detailUrl}" title="回图库详情"><img src="${escapeHtml(data.thumb)}" alt="source" /></a>`;
    }
    const thumb = $("studioThumb");
    if (thumb && data.thumb) {
      thumb.innerHTML = `<img src="${escapeHtml(data.thumb)}" alt="ref" />`;
    }
    document.querySelectorAll(".studio-queue-item").forEach((el) => {
      el.classList.toggle("active", String(el.dataset.workId) === sourceWorkId);
    });
    setStatus("已导入图库资产，可编辑或智能优化后生成", true);
    toast(`已导入 #${workId}`, "ok");
    refreshReady();
    saveDraftLocal();
  }

  function clearSource() {
    state.workId = 0;
    state.pageIndex = 0;
    state.comment = null;
    state.params = {};
    state.beforeTexts = null;
    state.undoStack = [];
    applyTextsToForm({ prompt: "", base_caption: "", uc: "", char_captions: [] });
    fillParams({ width: 832, height: 1216, steps: 28, scale: 5, sampler: "k_euler_ancestral" });
    renderCompare(null, null);
    if ($("studioSource")) $("studioSource").textContent = "空白新建 · 手写咒语出图";
    if ($("studioSourceThumb")) $("studioSourceThumb").innerHTML = "";
    if ($("studioThumb")) $("studioThumb").innerHTML = "";
    if ($("studioBackDetail")) $("studioBackDetail").classList.add("hidden");
    if ($("studioRestoreOriginal")) $("studioRestoreOriginal").classList.add("hidden");
    setStatus("已切换为空白新建", true, true);
    refreshReady();
    saveDraftLocal();
  }

  const escapeHtml = window.escapeHtml;

  async function refreshTokenStatus(tokenInfo) {
    try {
      const s = tokenInfo || await api("/api/nai/status");
      const el = $("studioToken");
      if (!el) return;
      if (!s.has_token) {
        el.innerHTML = '未配置 NAI/闲云 Token，请前往 <a href="/settings">设置中心</a>';
        setChip("token", "err", "无 Token");
        return;
      }
      const providers = s.providers
        ? Object.entries(s.providers).map(([k, v]) => `${k}×${v}`).join(" · ")
        : "";
      el.textContent = `Token 就绪${providers ? ` · ${providers}` : ""}`;
      setChip("token", "ok", "Token 就绪");
    } catch (e) {
      if ($("studioToken")) $("studioToken").textContent = String(e.message || e);
      setChip("token", "err", "Token 异常");
    }
  }

  function renderSizePresets(presets) {
    const host = $("studioSizePresets");
    if (!host) return;
    state.sizePresets = presets || [];
    host.innerHTML = "";
    state.sizePresets.forEach((p) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = p.label || `${p.width}×${p.height}`;
      btn.dataset.w = String(p.width);
      btn.dataset.h = String(p.height);
      btn.addEventListener("click", () => {
        if ($("studioWidth")) $("studioWidth").value = p.width;
        if ($("studioHeight")) $("studioHeight").value = p.height;
        highlightSizePreset();
        saveDraftLocal();
      });
      host.appendChild(btn);
    });
    highlightSizePreset();
  }

  function highlightSizePreset() {
    const w = Number($("studioWidth")?.value || 0);
    const h = Number($("studioHeight")?.value || 0);
    document.querySelectorAll("#studioSizePresets button").forEach((btn) => {
      btn.classList.toggle("active", Number(btn.dataset.w) === w && Number(btn.dataset.h) === h);
    });
  }

  function fillSamplers(list) {
    const sel = $("studioSampler");
    if (!sel) return;
    const items = list && list.length ? list : ["k_euler_ancestral"];
    state.samplers = items;
    const cur = sel.value;
    sel.innerHTML = items.map((s) => `<option value="${escapeHtml(s)}">${escapeHtml(s)}</option>`).join("");
    if (cur && items.includes(cur)) sel.value = cur;
  }

  async function loadStudioConfig() {
    try {
      const cfg = await api("/api/studio/config");
      const prefs = cfg.prefs || {};
      state.defaultOptimizeMode = prefs.default_optimize_mode || "smart";
      if ($("studioOptimizeMode")) $("studioOptimizeMode").value = state.defaultOptimizeMode;
      renderSizePresets(cfg.size_presets || []);
      fillSamplers(cfg.samplers || []);
      if (cfg.defaults) fillParams({ ...cfg.defaults, ...state.params });
      await refreshTokenStatus(cfg.token);
      if (!cfg.ai?.has_api_key) {
        setStatus("未配置智能优化 Key，可在设置中使用「智能优化」以外的模式", true, true);
      }
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  async function loadQueue() {
    const host = $("studioQueueList");
    if (!host) return;
    try {
      const data = await api("/api/studio/queue?limit=40");
      const items = data.items || [];
      if (!items.length) {
        host.innerHTML = `<div class="studio-muted">队列为空 · 在图库详情「加入待生成」</div>`;
        return;
      }
      host.innerHTML = "";
      items.forEach((it) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "studio-queue-item" + (String(it.work_id) === String(state.workId) ? " active" : "");
        btn.dataset.workId = String(it.work_id);
        const thumb = it.thumb
          ? `<img src="${escapeHtml(it.thumb)}" alt="" />`
          : `<img alt="" style="opacity:.3" />`;
        btn.innerHTML = `${thumb}<div class="meta"><div class="title">${escapeHtml(it.title || ("作品 " + it.work_id))}</div><div class="sub">#${it.work_id} · 点击导入</div></div>`;
        btn.addEventListener("click", () => {
          loadImport(it.work_id, 0).catch((e) => setStatus(String(e.message || e), false));
        });
        host.appendChild(btn);
      });
    } catch (e) {
      host.innerHTML = `<div class="studio-muted">队列加载失败：${escapeHtml(e.message || e)}</div>`;
    }
  }

  function currentOptimizeMode() {
    return ($("studioOptimizeMode") || {}).value || state.defaultOptimizeMode || "smart";
  }

  async function onOptimize(mode) {
    const modeKey = mode || currentOptimizeMode();
    try {
      pushUndoSnapshot();
      setStatus(modeKey === "sanitize" ? "本地净化中…" : "优化中…", true);
      const comment = commentFromForm();
      const res = await api("/api/studio/optimize", {
        method: "POST",
        body: { comment, mode: modeKey },
      });
      state.comment = res.comment;
      applyTextsToForm(res.texts);
      renderCompare(state.beforeTexts || res.before || res.texts, res.texts);
      const note = res.notes ? ` · ${res.notes}` : "";
      const msg = (res.message || res.label || "优化完成") + note;
      if (res.fallback) setStatus(msg, false, true);
      else setStatus(msg, true);
      toast(msg, res.fallback ? undefined : "ok");
    } catch (e) {
      state.undoStack.pop();
      const msg = String(e.message || e);
      if (modeKey === "smart" && /API Key|api_key|未配置/i.test(msg)) {
        setStatus(`${msg} — 请打开设置中心配置`, false, true);
      } else {
        setStatus(msg, false);
      }
      toast(msg, "err");
    }
  }

  function onUndo() {
    const prev = state.undoStack.pop();
    if (!prev) return setStatus("没有可撤销的优化步骤", false, true);
    try {
      applyTextsToForm(JSON.parse(prev));
      renderCompare(state.beforeTexts, textsFromForm());
      setStatus("已撤销上一步优化", true);
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  async function applyReference(kind) {
    const workId = parseInt(($("studioRefWorkId") || {}).value || state.workId || "0", 10);
    const strength = parseFloat(($("studioVibeStrength") || {}).value || "0.6");
    const manualUrl = kind === "vibe"
      ? (($("studioVibeUrl") || {}).value || "").trim()
      : (($("studioCharRefUrl") || {}).value || "").trim();
    try {
      setStatus(kind === "vibe" ? "应用 Vibe 参考…" : "应用角色参考…", true);
      const res = await api("/api/studio/reference", {
        method: "POST",
        body: {
          comment: commentFromForm(),
          work_id: workId || null,
          image_url: manualUrl,
          page_index: state.pageIndex || 0,
          kind,
          strength,
        },
      });
      state.comment = res.comment;
      const url = res.image_url || "";
      if (kind === "vibe" && $("studioVibeUrl")) $("studioVibeUrl").value = url;
      if (kind === "char" && $("studioCharRefUrl")) $("studioCharRefUrl").value = url;
      setStatus(kind === "vibe" ? "Vibe 参考已写入" : "角色参考已写入", true);
      toast("参考已应用", "ok");
      saveDraftLocal();
    } catch (e) {
      setStatus(String(e.message || e), false);
      toast(String(e.message || e), "err");
    }
  }

  function loadHistory() {
    try {
      state.history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]") || [];
    } catch (_) {
      state.history = [];
    }
    renderHistory();
  }

  function pushHistory(url, meta) {
    if (!url) return;
    state.history.unshift({
      url,
      workId: state.workId || null,
      ts: Date.now(),
      seed: meta && meta.seed,
    });
    state.history = state.history.slice(0, 18);
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(state.history));
    } catch (_) {
      console.warn("[studio] history persist failed (quota?)");
    }
    renderHistory();
  }

  function renderHistory() {
    const host = $("studioHistory");
    if (!host) return;
    if (!state.history.length) {
      host.innerHTML = `<div class="studio-muted" style="grid-column:1/-1">本会话生成会显示在此</div>`;
      return;
    }
    host.innerHTML = "";
    state.history.forEach((h) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.title = h.workId ? `来源 #${h.workId}` : "独立生成";
      btn.innerHTML = `<img src="${escapeHtml(h.url)}" alt="" />`;
      btn.addEventListener("click", () => setPreviewImage(h.url));
      host.appendChild(btn);
    });
  }

  function saveDraftLocal() {
    try {
      flushCurrentAitagPage();
      const payload = {
        workId: state.workId,
        pageIndex: state.pageIndex,
        draftId: state.draftId || "",
        sourceKind: state.sourceProvider || "",
        sourceProvider: state.sourceProvider || "",
        sourceLabel: state.sourceLabel || "",
        source: {
          provider: state.sourceProvider || "",
          workIdStr: state.onlineWorkIdStr || "",
          workId: state.onlineWorkIdStr || "",
          title: state.onlineSourceTitle || "",
          thumb: state.onlineSourceThumb || "",
          imageIndex: state.pageIndex || 0,
        },
        onlineWorkIdStr: state.onlineWorkIdStr || "",
        sourceTitle: state.onlineSourceTitle || "",
        sourceThumb: state.onlineSourceThumb || "",
        // Keep multi-page AITag packages across form edits / refresh.
        pages: Array.isArray(state.aitagPages) ? state.aitagPages : [],
        texts: textsFromForm(),
        params: {
          width: $("studioWidth")?.value,
          height: $("studioHeight")?.value,
          steps: $("studioSteps")?.value,
          scale: $("studioScale")?.value,
          seed: $("studioSeed")?.value,
          sampler: $("studioSampler")?.value,
          batch: $("studioBatchCount")?.value,
        },
        refs: {
          vibe: $("studioVibeUrl")?.value || "",
          char: $("studioCharRefUrl")?.value || "",
          strength: $("studioVibeStrength")?.value || "0.6",
        },
        comment: state.comment || null,
        ts: Date.now(),
      };
      localStorage.setItem(DRAFT_KEY, JSON.stringify(payload));
    } catch (err) {
      try {
        setStatus("本地草稿保存失败（缓存可能已满）", false, true);
      } catch (_) { /* ignore */ }
    }
  }

  function restoreDraftLocal() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      if (!raw) return null;
      return JSON.parse(raw);
    } catch (_) {
      return null;
    }
  }

  async function onGenerate() {
    if (state.generating) return;
    const texts = textsFromForm();
    if (!texts.prompt && !texts.base_caption && !(texts.char_captions || []).length) {
      setStatus("请先填写 Prompt / Base / 角色槽", false, true);
      return;
    }
    const copies = Math.max(1, Math.min(8, parseInt($("studioBatchCount")?.value || "1", 10) || 1));
    const snapshot = commentFromForm();
    const seedVal = ($("studioSeed") || {}).value;
    const seedPolicy = (seedVal === "" || seedVal === "-1") ? "random" : "increment";
    const isAitag = state.sourceProvider === "aitag-online";
    const remoteId = String(state.onlineWorkIdStr || "").trim();
    let workIdPayload = state.workId || null;
    if (isAitag && remoteId) {
      const asNum = Number(remoteId);
      workIdPayload = (Number.isSafeInteger(asNum) && asNum > 0) ? asNum : remoteId;
    }
    if (isAitag && snapshot && typeof snapshot === "object") {
      snapshot._aitag_source = {
        work_id: remoteId,
        page_index: state.pageIndex || 0,
        title: state.onlineSourceTitle || "",
        thumb: state.onlineSourceThumb || "",
      };
    }
    const sourceGalleryId = isAitag ? "aitag-online" : (state.sourceProvider || "site");
    state.generating = true;
    if ($("studioGenerate")) $("studioGenerate").disabled = true;
    showGenProgress(true, copies > 1 ? `入队中 0/${copies}…` : "入队中…");
    try {
      setStatus(copies > 1 ? `提交 ${copies} 张生成任务…` : "提交生成任务…", true);
      const res = await api("/api/nai/generate", {
        method: "POST",
        body: {
          patched_comment: snapshot,
          work_id: workIdPayload,
          work_id_str: isAitag ? remoteId : "",
          remote_work_id: isAitag ? remoteId : "",
          source_gallery_id: sourceGalleryId,
          source_title: isAitag ? (state.onlineSourceTitle || "") : "",
          source_thumb: isAitag ? (state.onlineSourceThumb || "") : "",
          page_index: state.pageIndex || 0,
          copies,
          seed_policy: seedPolicy,
          force_free: true,
          prompt_profile: "native",
        },
      });
      if (!res.ok) throw new Error(res.message || res.error || "生成失败");
      const taskId = res.task_id || (res.batch && res.batch.task_id) || "";
      if (!taskId) throw new Error("未返回生成任务 ID");
      setStatus("任务已入队，正在出图…", true);
      const job = await window.ApiClient.pollJob(taskId, (status) => {
        const done = Number(status.done || 0);
        const total = Number(status.total || copies);
        const msg = String(status.message || "");
        showGenProgress(true, total > 1 ? `生成中 ${done}/${total}… ${msg}` : (msg || "生成中…"));
        setStatus(msg || (total > 1 ? `生成中 ${done}/${total}` : "生成中…"), true);
        const items = Array.isArray(status.items) ? status.items : [];
        const lastOk = [...items].reverse().find((item) => item && item.ok && item.image_url);
        if (lastOk && lastOk.image_url) {
          setPreviewImage(lastOk.image_url + (lastOk.image_url.includes("?") ? "&" : "?") + "t=" + Date.now());
        }
      });
      if (String(job.status || "") === "unknown") {
        const warn = job.message || "这次可能已扣费，不要自动重试；要重出请再确认。";
        setStatus(warn, false, true);
        toast(warn, "err");
        return;
      }
      const items = Array.isArray(job.items) ? job.items : [];
      const okItems = items.filter((item) => item && item.ok && item.image_url);
      okItems.forEach((item) => {
        pushHistory(item.image_url, { seed: snapshot.seed, task_id: taskId });
      });
      if (okItems.length) {
        const last = okItems[okItems.length - 1];
        setPreviewImage(last.image_url + (last.image_url.includes("?") ? "&" : "?") + "t=" + Date.now());
      }
      if (job.status === "cancelled") {
        throw new Error(job.message || "已取消");
      }
      const failed = Number(job.effective_fail_count || job.fail_count || 0);
      if (!okItems.length) {
        throw new Error(job.message || "生成失败");
      }
      const doneMsg = failed
        ? `完成 ${okItems.length} 张，失败 ${failed}（5xx 未自动重试）`
        : (copies > 1 ? `已生成 ${okItems.length} 张` : "生成完成");
      setStatus(job.message || doneMsg, true);
      toast(doneMsg, failed ? "err" : "ok");
    } catch (e) {
      setStatus(String(e.message || e), false);
      toast(String(e.message || e), "err");
    } finally {
      state.generating = false;
      if ($("studioGenerate")) $("studioGenerate").disabled = false;
      showGenProgress(false);
      saveDraftLocal();
    }
  }

  function bind() {
    $("studioOptimize")?.addEventListener("click", () => onOptimize(currentOptimizeMode()));
    $("studioUndo")?.addEventListener("click", onUndo);
    $("studioGenerate")?.addEventListener("click", onGenerate);
    $("studioApplyVibe")?.addEventListener("click", () => applyReference("vibe"));
    $("studioApplyCharRef")?.addEventListener("click", () => applyReference("char"));
    $("studioUseSourceRef")?.addEventListener("click", () => {
      if (!state.workId) return setStatus("请先导入来源作品", false, true);
      if ($("studioRefWorkId")) $("studioRefWorkId").value = String(state.workId);
      setStatus(`已填入来源作品 #${state.workId}`, true);
    });
    $("studioImportById")?.addEventListener("click", async () => {
      const manual = parseInt(prompt("输入图库作品 ID：") || "0", 10);
      if (manual > 0) {
        try {
          await loadImport(manual, 0);
        } catch (e) {
          setStatus(String(e.message || e), false);
        }
      }
    });
    $("studioClearSource")?.addEventListener("click", clearSource);
    $("studioRefreshQueue")?.addEventListener("click", () => loadQueue());
    $("studioRandomSeed")?.addEventListener("click", () => {
      if ($("studioSeed")) $("studioSeed").value = String(Math.floor(Math.random() * 2 ** 31));
      saveDraftLocal();
    });
    $("studioCopyPrompt")?.addEventListener("click", async () => {
      const t = textsFromForm().prompt || textsFromForm().base_caption || "";
      try {
        await navigator.clipboard.writeText(t);
        toast("已复制 Prompt", "ok");
      } catch (_) {
        setStatus("复制失败", false);
      }
    });
    $("studioPastePrompt")?.addEventListener("click", async () => {
      try {
        const t = await navigator.clipboard.readText();
        if ($("studioPrompt")) $("studioPrompt").value = t;
        refreshReady();
        saveDraftLocal();
        toast("已粘贴", "ok");
      } catch (_) {
        setStatus("无法读取剪贴板", false, true);
      }
    });
    $("studioOpenGenerated")?.addEventListener("click", (e) => {
      e.preventDefault();
      const q = state.workId ? `?g=${state.workId}` : "";
      window.open("/generated" + q, "_blank", "noopener");
    });
    $("studioRestoreOriginal")?.addEventListener("click", async () => {
      if (!state.workId) return setStatus("没有可恢复的来源资产", false, true);
      try {
        await loadImport(state.workId, state.pageIndex || 0);
        setStatus("已恢复为图库原文咒语", true);
      } catch (e) {
        setStatus(String(e.message || e), false);
      }
    });
    $("studioVibeStrength")?.addEventListener("input", () => {
      const v = Number($("studioVibeStrength").value || 0);
      if ($("studioStrengthVal")) $("studioStrengthVal").textContent = v.toFixed(2);
      saveDraftLocal();
    });
    $("studioAction")?.addEventListener("change", () => {
      syncStudioActionUi();
      saveDraftLocal();
    });
    $("studioImg2ImgStrength")?.addEventListener("input", () => {
      const v = Number($("studioImg2ImgStrength").value || 0.55);
      if ($("studioImg2ImgStrengthVal")) $("studioImg2ImgStrengthVal").textContent = v.toFixed(2);
    });
    $("studioLoadSourceImage")?.addEventListener("click", () => {
      loadStudioSourceImage().catch((err) => setStatus(String(err.message || err), false));
    });
    $("studioSourceFile")?.addEventListener("change", (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = String(reader.result || "");
        const comma = dataUrl.indexOf(",");
        state.sourceImage = comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl;
        drawStudioSource(dataUrl);
        setStatus("已从本地文件加载原图", true);
      };
      reader.readAsDataURL(file);
    });
    $("studioBrush")?.addEventListener("input", () => {
      if ($("studioBrushVal")) $("studioBrushVal").textContent = String($("studioBrush").value || "22");
    });
    const mask = $("studioMaskCanvas");
    if (mask) {
      const paint = (event) => {
        if (!state.painting || (($("studioAction") || {}).value || "") !== "inpaint") return;
        const ctx = mask.getContext("2d");
        if (!ctx) return;
        const rect = mask.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / rect.width) * mask.width;
        const y = ((event.clientY - rect.top) / rect.height) * mask.height;
        const brush = Number($("studioBrush")?.value || 22);
        ctx.fillStyle = "#ffffff";
        ctx.beginPath();
        ctx.arc(x, y, brush, 0, Math.PI * 2);
        ctx.fill();
      };
      mask.addEventListener("pointerdown", (event) => {
        state.painting = true;
        paint(event);
      });
      mask.addEventListener("pointermove", paint);
      mask.addEventListener("pointerup", () => { state.painting = false; });
      mask.addEventListener("pointerleave", () => { state.painting = false; });
    }
    ["studioPrompt", "studioBase", "studioCharCaptions", "studioUc", "studioWidth", "studioHeight", "studioSteps", "studioScale", "studioSeed", "studioSampler", "studioBatchCount"].forEach((id) => {
      $(id)?.addEventListener("input", () => {
        refreshReady();
        saveDraftLocal();
        if (id === "studioWidth" || id === "studioHeight") highlightSizePreset();
      });
      $(id)?.addEventListener("change", saveDraftLocal);
    });
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        onGenerate();
      }
    });
  }

  async function boot() {
    bind();
    loadHistory();
    await Promise.all([loadStudioConfig(), loadQueue()]);
    const params = new URLSearchParams(window.location.search);
    const draftId = String(params.get("draft") || "").trim();
    const wantAitag = params.get("aitag") === "1" || params.get("source") === "aitag-online";
    let workId = window.WorkBridge?.normalizeWorkId?.(params.get("from") || params.get("work")) || String(params.get("from") || params.get("work") || "").trim();
    let pageIndex = parseInt(params.get("page") || "0", 10);
    if (!workId && window.WorkBridge) {
      const bridged = window.WorkBridge.load();
      if (bridged && bridged.workId) {
        workId = bridged.workId;
        pageIndex = bridged.pageIndex || 0;
      }
    }
    if (draftId) {
      try {
        const ok = await restoreDraftFromServer(draftId, pageIndex);
        if (!ok) setStatus("服务端草稿为空", false, true);
      } catch (e) {
        setStatus(`服务端草稿恢复失败：${e.message || e}`, false);
      }
    } else if (workId) {
      try {
        await loadImport(workId, pageIndex);
      } catch (e) {
        setStatus(String(e.message || e), false);
      }
    } else {
      const draft = restoreDraftLocal();
      if (isUsableDraft(draft)) {
        const provider = String(
          draft.source?.provider || draft.sourceKind || draft.sourceProvider || ""
        ).trim();
        if (provider === "aitag-online" || !draft.workId) {
          applyDraftObject(draft, "已恢复上次草稿（可继续编辑）");
        } else {
          try {
            await loadImport(draft.workId, draft.pageIndex || 0);
            setStatus("已恢复上次草稿（可继续编辑）", true, true);
          } catch (_) {
            applyDraftObject(draft, "已恢复上次草稿（可继续编辑）");
          }
        }
      } else if (wantAitag) {
        try {
          const ok = await restoreLatestServerDraft();
          if (!ok) setStatus("没有可恢复的 AITag 服务端草稿；请从资产工作台建立", false, true);
        } catch (_) {
          setStatus("没有可恢复的 AITag 服务端草稿；请从资产工作台建立", false, true);
        }
      } else {
        setStatus("从图库点「用此图生成」，或从左侧队列导入；Ctrl+Enter 快速生成", true, true);
      }
    }
    refreshReady();
    if ($("studioVibeStrength") && $("studioStrengthVal")) {
      $("studioStrengthVal").textContent = Number($("studioVibeStrength").value || 0.6).toFixed(2);
    }
    syncStudioActionUi();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

(function () {
  const $ = (id) => document.getElementById(id);
  const DRAFT_KEY = "aitag.studio.draft.v1";
  const HISTORY_KEY = "aitag.studio.history.v1";
  const COPIES_KEY = "aitag.studio.copies.v1";
  const SERIES_KEY = "aitag.studio.seriesAll.v1";
  const JOB_KEY = "aitag.studio.job.v1";
  let COPIES_MAX = 20;

  const state = {
    workId: 0,
    pageIndex: 0,
    comment: null,
    params: {},
    beforeTexts: null,
    generating: false,
    currentTaskId: "",
    lastTaskId: "",
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
  };

  function clampCopies(value) {
    const n = parseInt(value, 10);
    if (!Number.isFinite(n)) return 1;
    return Math.max(1, Math.min(COPIES_MAX, n));
  }

  function currentCopies() {
    return clampCopies($("studioBatchCount")?.value || "1");
  }

  function persistCopies(n) {
    try {
      localStorage.setItem(COPIES_KEY, String(n));
    } catch (_) { /* ignore */ }
  }

  function setCopies(value, persist) {
    const n = clampCopies(value);
    const input = $("studioBatchCount");
    if (input) input.value = String(n);
    document.querySelectorAll("#studioBatchPresets [data-copies]").forEach((btn) => {
      btn.classList.toggle("is-active", clampCopies(btn.getAttribute("data-copies")) === n);
    });
    const gen = $("studioGenerate");
    if (gen && !state.generating) {
      gen.textContent = generateButtonLabel(n);
    }
    if (persist !== false) persistCopies(n);
    return n;
  }

  function seriesPageCount() {
    const pages = Array.isArray(state.aitagPages) ? state.aitagPages : [];
    return pages.length;
  }

  function currentStudioGalleryId() {
    try {
      const params = new URLSearchParams(window.location.search);
      const fromUrl = params.get("gallery") || params.get("gallery_id");
      if (fromUrl) return fromUrl;
      const bridged = window.WorkBridge?.load?.();
      if (bridged && bridged.galleryId) return bridged.galleryId;
    } catch (_) { /* ignore */ }
    if (state.sourceProvider && state.sourceProvider !== "aitag-online") {
      return state.sourceProvider;
    }
    return "site";
  }

  function jobCanRetry(job) {
    if (!job || !job.task_id) return false;
    const status = String(job.status || "");
    if (!["done", "error", "cancelled"].includes(status)) return false;
    if (job.needs_review || Number(job.blocked_retry_count) > 0) return false;
    const failed = Number(job.effective_fail_count || job.fail_count || 0);
    const deferred = Number(job.deferred_unattempted_count || 0);
    const unfinished = Math.max(0, Number(job.total || 0) - Number(job.done || 0));
    return failed > 0 || deferred > 0 || unfinished > 0 || status === "cancelled";
  }

  function syncRetryButton(job) {
    const btn = $("studioRetryFailed");
    if (!btn) return;
    const can = !state.generating && jobCanRetry(job);
    btn.classList.toggle("hidden", !can);
    if (can) {
      const failed = Number((job && (job.effective_fail_count || job.fail_count)) || 0);
      const unfinished = Math.max(0, Number((job && job.total) || 0) - Number((job && job.done) || 0));
      btn.textContent = failed && unfinished
        ? `重试失败/未完成（${failed + unfinished}）`
        : (unfinished && !failed ? "继续未完成页" : "重试失败页");
    }
    syncResumeBanner(job);
  }

  function seriesAllEnabled() {
    return seriesPageCount() > 1 && !!$("studioSeriesAll")?.checked;
  }

  function generateButtonLabel(copies) {
    const n = clampCopies(copies);
    const pages = seriesPageCount();
    if (seriesAllEnabled()) {
      return n > 1 ? `开始生成 本系列 ${pages} 页 × ${n}` : `开始生成 本系列 ${pages} 页`;
    }
    return `开始生成 ${n} 张`;
  }

  function syncSeriesToggle() {
    const wrap = $("studioSeriesToggle");
    const box = $("studioSeriesAll");
    const label = $("studioSeriesAllLabel");
    const pages = seriesPageCount();
    if (wrap) wrap.classList.toggle("hidden", pages <= 1);
    if (label && pages > 1) label.textContent = `生成本系列全部 ${pages} 页`;
    if ($("studioGenerate") && !state.generating) {
      $("studioGenerate").textContent = generateButtonLabel(currentCopies());
    }
  }

  function persistSeriesPref() {
    try {
      localStorage.setItem(SERIES_KEY, $("studioSeriesAll")?.checked ? "1" : "0");
    } catch (_) { /* ignore */ }
  }

  function restoreSeriesPref() {
    const box = $("studioSeriesAll");
    if (!box) return;
    try {
      const saved = localStorage.getItem(SERIES_KEY);
      if (saved === "0") box.checked = false;
      else if (saved === "1") box.checked = true;
    } catch (_) { /* ignore */ }
    syncSeriesToggle();
  }

  function restoreCopies() {
    let saved = "";
    try {
      saved = localStorage.getItem(COPIES_KEY) || "";
    } catch (_) {
      saved = "";
    }
    setCopies(saved || $("studioBatchCount")?.value || "1", false);
  }

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
    if (pages.length <= 1) {
      host.classList.add("hidden");
      host.innerHTML = "";
      syncSeriesToggle();
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
    syncSeriesToggle();
  }

  function flushCurrentAitagPage() {
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
            provider: state.sourceProvider || "site",
            imageIndex: idx,
            workId: state.workId || 0,
            workIdStr: state.onlineWorkIdStr || "",
            title: state.onlineSourceTitle || "",
            thumb: state.onlineSourceThumb || "",
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
      setStatus(`没有 p${pageIndex} 的草稿`, false);
      return false;
    }
    const pack = {
      ...hit.draft,
      draftId: state.draftId,
      workId: state.workId,
      sourceKind: state.sourceProvider || hit.draft.source?.provider || "",
      source: hit.draft.source || {
        provider: state.sourceProvider || "site",
        imageIndex: pageIndex,
        workId: state.workId || 0,
      },
      pageIndex: Number(pageIndex) || 0,
      pages: state.aitagPages,
      texts: hit.draft.texts,
      params: hit.draft.params,
      refs: hit.draft.refs,
      comment: hit.draft.comment,
    };
    return applyDraftObject(pack, `已切换到 p${pageIndex}`);
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
    } else if (!(Array.isArray(state.aitagPages) && state.aitagPages.length)) {
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
    } else {
      const localId = draft.workId || source.workId || state.workId;
      if (localId) state.workId = localId;
      state.pageIndex = Number(draft.pageIndex || source.imageIndex || 0) || 0;
      const pageN = state.aitagPages.length;
      if (state.workId) {
        state.sourceLabel = `来源 #${state.workId}${pageN > 1 ? ` · ${pageN} 页` : ""}`;
      }
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
    syncSeriesToggle();
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

  function charCaptionText(value, depth) {
    if ((depth || 0) > 4) return "";
    if (typeof value === "string") return value;
    if (!value || typeof value !== "object") return "";
    if (value.char_caption != null && value.char_caption !== value) {
      return charCaptionText(value.char_caption, (depth || 0) + 1);
    }
    return String(value.caption || value.text || "").trim();
  }

  function normalizeCharSlots(slots) {
    if (!Array.isArray(slots)) return [];
    return slots.map((item) => {
      const prev = item && typeof item === "object" ? item : {};
      const centers = Array.isArray(prev.centers) && prev.centers.length
        ? prev.centers
        : (prev.center ? [prev.center] : [{ x: 0.5, y: 0.5 }]);
      return { char_caption: charCaptionText(item), centers };
    });
  }

  function sanitizeCommentCaptions(comment) {
    if (!comment || typeof comment !== "object") return comment;
    ["v4_prompt", "v4_negative_prompt"].forEach((key) => {
      const block = comment[key];
      if (!block || typeof block !== "object") return;
      const cap = block.caption;
      if (!cap || typeof cap !== "object") return;
      cap.char_captions = normalizeCharSlots(cap.char_captions);
    });
    return comment;
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
        return { char_caption: charCaptionText(line), centers };
      });
    }
    v4.caption = cap;
    base.v4_prompt = v4;
    sanitizeCommentCaptions(base);
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
    return base;
  }

  function overlayCurrentParams(comment) {
    const next = copyComment(comment || {});
    next.width = parseInt($("studioWidth")?.value || next.width || 832, 10);
    next.height = parseInt($("studioHeight")?.value || next.height || 1216, 10);
    next.steps = parseInt($("studioSteps")?.value || next.steps || 28, 10);
    next.scale = parseFloat($("studioScale")?.value || next.scale || 5);
    next.sampler = ($("studioSampler") || {}).value || next.sampler || "k_euler_ancestral";
    return next;
  }

  function commentHasPrompt(comment) {
    if (!comment || typeof comment !== "object") return false;
    const cap = (comment.v4_prompt && comment.v4_prompt.caption) || {};
    const chars = Array.isArray(cap.char_captions) ? cap.char_captions : [];
    const charText = chars.some((item) => String((item && item.char_caption) || item || "").trim());
    return !!(
      String(comment.prompt || "").trim()
      || String(cap.base_caption || "").trim()
      || charText
    );
  }

  function commentFromPageDraft(page) {
    const draft = (page && page.draft && typeof page.draft === "object") ? page.draft : {};
    let comment;
    if (draft.comment && typeof draft.comment === "object") {
      comment = copyComment(draft.comment);
    } else if (draft.prompt != null || draft.v4_prompt) {
      comment = copyComment(draft);
    } else {
      comment = copyComment(state.comment || {});
    }
    const texts = draft.texts || {};
    if (texts.prompt || texts.base_caption || (texts.char_captions || []).length) {
      comment.prompt = texts.prompt || texts.base_caption || comment.prompt;
      if (texts.uc != null) comment.uc = texts.uc;
      const v4 = comment.v4_prompt || {};
      const cap = v4.caption || {};
      cap.base_caption = texts.base_caption || texts.prompt || cap.base_caption;
      if (texts.char_captions && texts.char_captions.length) {
        const old = cap.char_captions || [];
        cap.char_captions = texts.char_captions.map((line, i) => {
          const prev = old[i] && typeof old[i] === "object" ? old[i] : {};
          const centers = prev.centers || (prev.center ? [prev.center] : [{ x: 0.5, y: 0.5 }]);
          return { char_caption: charCaptionText(line), centers };
        });
      }
      v4.caption = cap;
      comment.v4_prompt = v4;
    }
    return sanitizeCommentCaptions(overlayCurrentParams(comment));
  }

  function buildSeriesPagePayloads() {
    flushCurrentAitagPage();
    const remoteId = String(state.onlineWorkIdStr || "").trim();
    const pages = (Array.isArray(state.aitagPages) ? state.aitagPages : [])
      .slice()
      .sort((a, b) => Number(a.image_index || 0) - Number(b.image_index || 0));
    return pages.map((page) => {
      const comment = commentFromPageDraft(page);
      if (!commentHasPrompt(comment)) return null;
      const draft = page.draft || {};
      const source = draft.source || {};
      return {
        page_index: Number(page.image_index || 0),
        patched_comment: comment,
        source_title: String(source.title || draft.sourceTitle || state.onlineSourceTitle || "").trim(),
        source_thumb: String(source.thumb || draft.thumb || draft.sourceThumb || state.onlineSourceThumb || "").trim(),
        remote_work_id: String(source.workIdStr || draft.workIdStr || remoteId || "").trim(),
      };
    }).filter(Boolean);
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

  async function loadImport(workId, pageIndex, galleryId) {
    const sourceWorkId = window.WorkBridge?.normalizeWorkId?.(workId) || String(workId || "");
    const gid = String(galleryId || currentStudioGalleryId() || "site").trim() || "site";
    setStatus("正在导入作品咒语…", true);
    const data = await api(`/api/studio/import?work_id=${encodeURIComponent(sourceWorkId)}&page_index=${pageIndex || 0}&gallery_id=${encodeURIComponent(gid)}`);
    state.workId = data.work_id;
    state.pageIndex = data.page_index;
    state.comment = data.comment;
    state.params = data.params || {};
    state.sourceProvider = String(data.gallery_id || gid || "site").trim() || "site";
    if (state.sourceProvider === "aitag-online") {
      state.sourceLabel = `AITag #${sourceWorkId}`;
    } else {
      const pageN = Array.isArray(data.pages) ? data.pages.length : 0;
      state.sourceLabel = `来源 #${data.work_id}${pageN > 1 ? ` · ${pageN} 页` : ""}`;
    }
    state.aitagPages = (Array.isArray(data.pages) ? data.pages : [])
      .map((page) => ({
        image_index: Number(page.image_index ?? page.draft?.pageIndex ?? 0) || 0,
        slot_indexes: page.slot_indexes || [],
        draft: page.draft || page,
      }))
      .filter((page) => page.draft && typeof page.draft === "object");
    if (!state.aitagPages.length && data.comment) {
      state.aitagPages = [{
        image_index: Number(data.page_index || 0) || 0,
        draft: {
          texts: data.texts,
          comment: data.comment,
          params: data.params || {},
          pageIndex: Number(data.page_index || 0) || 0,
          source: {
            provider: state.sourceProvider,
            workId: data.work_id,
            imageIndex: Number(data.page_index || 0) || 0,
            title: data.title || "",
            thumb: data.thumb || "",
          },
        },
      }];
    }
    state.beforeTexts = data.texts;
    state.undoStack = [];
    applyTextsToForm(data.texts);
    fillParams(state.params);
    renderCompare(data.texts, data.texts);
    renderAitagPageTabs();
    syncSeriesToggle();
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
    state.sourceProvider = "";
    state.sourceLabel = "";
    state.aitagPages = [];
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
    renderAitagPageTabs();
    syncSeriesToggle();
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
      const cap = parseInt(cfg.copy_max, 10);
      if (Number.isFinite(cap) && cap > 0) {
        COPIES_MAX = Math.max(1, Math.min(64, cap));
        if ($("studioBatchCount")) $("studioBatchCount").max = String(COPIES_MAX);
      }
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
        btn.dataset.galleryId = String(it.gallery_id || "site");
        const thumb = it.thumb
          ? `<img src="${escapeHtml(it.thumb)}" alt="" />`
          : `<img alt="" style="opacity:.3" />`;
        const gid = String(it.gallery_id || "site");
        btn.innerHTML = `${thumb}<div class="meta"><div class="title">${escapeHtml(it.title || ("作品 " + it.work_id))}</div><div class="sub">#${it.work_id}${gid !== "site" ? ` · ${escapeHtml(gid)}` : ""} · 点击导入</div></div>`;
        btn.addEventListener("click", () => {
          loadImport(it.work_id, 0, it.gallery_id || "site").catch((e) => setStatus(String(e.message || e), false));
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

  function persistJobId(id) {
    const value = String(id || "");
    try { sessionStorage.setItem(JOB_KEY, value); } catch (_) { /* ignore */ }
    try { localStorage.setItem(JOB_KEY, value); } catch (_) { /* ignore */ }
  }

  function restoreJobId() {
    try {
      return sessionStorage.getItem(JOB_KEY) || localStorage.getItem(JOB_KEY) || "";
    } catch (_) {
      return "";
    }
  }

  function jobCancelledByRestart(job) {
    return String((job && job.status) || "") === "cancelled"
      && String((job && job.message) || "").includes("进程重启");
  }

  function syncResumeBanner(job) {
    const banner = $("studioResumeBanner");
    const btn = $("studioRetryFailed");
    const show = jobCancelledByRestart(job) && jobCanRetry(job) && !state.generating;
    if (banner) {
      banner.classList.toggle("hidden", !show);
      if (show) {
        banner.textContent = "服务重启后，未发出的排队任务已取消。已成功的不会再扣；点「继续未完成页」只补未发出的页。";
      }
    }
    if (btn) {
      btn.classList.toggle("ghost", !show);
      btn.classList.toggle("primary", show);
    }
  }

  function renderStudioJobPanel(job, queue) {
    const summary = $("studioJobSummary");
    const log = $("studioJobLog");
    if (!summary || !log) return;
    const status = String((job && job.status) || "");
    const done = Number((job && job.done) || 0);
    const total = Number((job && job.total) || 0);
    const pending = Number((queue && queue.pending_count) || 0);
    const failed = Number((job && (job.effective_fail_count || job.fail_count)) || 0);
    const ok = Number((job && job.ok_count) || 0);
    if (!status || status === "idle") {
      summary.textContent = pending ? `空闲 · 排队 ${pending}` : "空闲";
      syncRetryButton(job);
      return;
    }
    if (status === "running" || status === "queued") {
      summary.textContent = `${status === "queued" ? "排队中" : "进行中"} ${done}/${total || "?"}`
        + (pending ? ` · 其后还有 ${pending} 个任务` : "");
    } else {
      summary.textContent = `${job.message || status} · 成功 ${ok} / 失败 ${failed} / 共 ${total || done}`;
    }
    const rows = [];
    if (status === "running") {
      rows.push(`<div class="active">… #${job.current_work_id ?? "studio"} p${job.current_page_index ?? 0} ${job.message || ""}</div>`);
    }
    (Array.isArray(job.items) ? job.items : []).slice().reverse().slice(0, 12).forEach((item) => {
      const cls = item.ok ? "ok" : "fail";
      rows.push(`<div class="${cls}">${item.ok ? "✓" : "✗"} p${item.page_index ?? 0} ${item.message || item.error || ""}</div>`);
    });
    log.innerHTML = rows.join("");
    syncRetryButton(job);
  }

  async function refreshStudioJobPanel() {
    try {
      const id = state.currentTaskId || state.lastTaskId || restoreJobId();
      const q = id ? ("?task_id=" + encodeURIComponent(id)) : "";
      const data = await api("/api/nai/jobs" + q);
      const job = data.job || {};
      if (job.task_id) state.lastTaskId = job.task_id;
      renderStudioJobPanel(job, data.queue || {});
      return data;
    } catch (_) {
      return null;
    }
  }

  async function resumeActiveJob() {
    const stored = restoreJobId();
    if (stored) state.lastTaskId = stored;
    const data = await refreshStudioJobPanel();
    const job = (data && data.job) || {};
    const status = String(job.status || "");
    const taskId = String(job.task_id || stored || "").trim();
    if (taskId) state.lastTaskId = taskId;
    if (jobCancelledByRestart(job) && jobCanRetry(job)) {
      setStatus("服务重启后未发出任务已取消。点「继续未完成页」只补未发出的页，已成功的不会再扣。", false, true);
    }
    if (!taskId || (status !== "running" && status !== "queued")) return;
    if (state.generating) return;
    state.currentTaskId = taskId;
    persistJobId(taskId);
    state.generating = true;
    if ($("studioGenerate")) $("studioGenerate").disabled = true;
    if ($("studioCancelGenerate")) $("studioCancelGenerate").classList.remove("hidden");
    const total = Number(job.total || 0);
    showGenProgress(true, total > 1 ? `继续任务 ${job.done || 0}/${total}…` : "继续任务…");
    setStatus("已恢复进行中的生成队列（离开页面不会中断）", true);
    try {
      const finished = await window.ApiClient.pollJob(taskId, (statusJob) => {
        renderStudioJobPanel(statusJob, (data && data.queue) || {});
        const done = Number(statusJob.done || 0);
        const tot = Number(statusJob.total || total);
        showGenProgress(true, tot > 1 ? `生成中 ${done}/${tot}…` : (statusJob.message || "生成中…"));
        const items = Array.isArray(statusJob.items) ? statusJob.items : [];
        const lastOk = [...items].reverse().find((item) => item && item.ok && item.image_url);
        if (lastOk && lastOk.image_url) {
          setPreviewImage(lastOk.image_url + (lastOk.image_url.includes("?") ? "&" : "?") + "t=" + Date.now());
        }
      });
      const failed = Number(finished.effective_fail_count || finished.fail_count || 0);
      const okItems = (finished.items || []).filter((item) => item && item.ok);
      setStatus(finished.message || `队列结束 · 成功 ${okItems.length} · 失败 ${failed}`, !failed);
    } catch (e) {
      setStatus(String(e.message || e), false);
    } finally {
      state.generating = false;
      state.currentTaskId = "";
      if ($("studioGenerate")) $("studioGenerate").disabled = false;
      if ($("studioCancelGenerate")) $("studioCancelGenerate").classList.add("hidden");
      setCopies(currentCopies(), false);
      showGenProgress(false);
      refreshStudioJobPanel();
    }
  }

  async function onGenerate() {
    if (state.generating) return;
    const texts = textsFromForm();
    if (!texts.prompt && !texts.base_caption && !(texts.char_captions || []).length) {
      setStatus("请先填写 Prompt / Base / 角色槽", false, true);
      return;
    }
    const copies = currentCopies();
    const useSeries = seriesAllEnabled();
    const seriesPages = useSeries ? buildSeriesPagePayloads() : [];
    if (useSeries && !seriesPages.length) {
      setStatus("本系列没有可生成的页（每页需要 Prompt）", false, true);
      return;
    }
    const pageCount = seriesPages.length || 1;
    const expectedTotal = pageCount * copies;
    if (expectedTotal > 250) {
      setStatus(`本系列 ${pageCount} 页 × ${copies} 张共 ${expectedTotal} 张，超过单次上限 250`, false, true);
      return;
    }
    if (expectedTotal > 1) {
      const skipped = useSeries ? (seriesPageCount() - pageCount) : 0;
      const extra = skipped > 0 ? `\n（${skipped} 页没有咒语，已跳过）` : "";
      const label = useSeries
        ? `生成本系列 ${pageCount} 页 × ${copies} 张，共 ${expectedTotal} 张。当前走 Opus 免费档，不按张扣付费 Anlas；超大尺寸/步数会自动压到免费上限（最长边 1216、步数 28）。确认开始？${extra}`
        : `生成本页 ${copies} 张。当前走 Opus 免费档，不按张扣付费 Anlas；超大尺寸/步数会自动压到免费上限（最长边 1216、步数 28）。确认开始？`;
      if (!window.confirm(label)) {
        return;
      }
    }
    state.generating = true;
    const snapshot = seriesPages.length
      ? copyComment(seriesPages[0].patched_comment)
      : commentFromForm();
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
        page_index: seriesPages.length ? seriesPages[0].page_index : (state.pageIndex || 0),
        title: state.onlineSourceTitle || "",
        thumb: state.onlineSourceThumb || "",
      };
    }
    const sourceGalleryId = isAitag ? "aitag-online" : (state.sourceProvider || "site");
    state.currentTaskId = "";
    if ($("studioGenerate")) $("studioGenerate").disabled = true;
    if ($("studioCancelGenerate")) $("studioCancelGenerate").classList.remove("hidden");
    showGenProgress(true, expectedTotal > 1 ? `入队中 0/${expectedTotal}…` : "入队中…");
    try {
      setStatus(
        useSeries
          ? `提交本系列 ${pageCount} 页 × ${copies} 张…`
          : (copies > 1 ? `提交 ${copies} 张生成任务…` : "提交生成任务…"),
        true,
      );
      const body = {
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
      };
      if (seriesPages.length > 1) body.pages = seriesPages;
      const res = await api("/api/nai/generate", {
        method: "POST",
        body,
      });
      if (!res.ok) throw new Error(res.message || res.error || "生成失败");
      const accepted = Math.max(1, Number(res.total) || expectedTotal);
      const taskId = res.task_id || (res.batch && res.batch.task_id) || "";
      if (!taskId) throw new Error("未返回生成任务 ID");
      state.currentTaskId = taskId;
      state.lastTaskId = taskId;
      persistJobId(taskId);
      refreshStudioJobPanel();
      setStatus(accepted > 1 ? `任务已入队，正在出 ${accepted} 张…` : "任务已入队，正在出图…", true);
      const job = await window.ApiClient.pollJob(taskId, (status) => {
        const done = Number(status.done || 0);
        const total = Number(status.total || accepted);
        const pos = Number(status.queue_position || 0);
        const queued = String(status.status || "") === "queued";
        const rawMsg = String(status.message || "");
        const msg = queued && pos
          ? `排队中（第 ${pos} 位）${rawMsg ? " · " + rawMsg : ""}`
          : rawMsg;
        showGenProgress(true, total > 1 ? `生成中 ${done}/${total}… ${msg}` : (msg || "生成中…"));
        setStatus(msg || (total > 1 ? `生成中 ${done}/${total}` : "生成中…"), true);
        renderStudioJobPanel(status, {});
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
        : (accepted > 1 ? `已生成 ${okItems.length} 张` : "生成完成");
      setStatus(job.message || doneMsg, true);
      toast(doneMsg, failed ? "err" : "ok");
    } catch (e) {
      setStatus(String(e.message || e), false);
      toast(String(e.message || e), "err");
    } finally {
      state.generating = false;
      state.currentTaskId = "";
      if ($("studioGenerate")) $("studioGenerate").disabled = false;
      if ($("studioCancelGenerate")) $("studioCancelGenerate").classList.add("hidden");
      setCopies(currentCopies(), false);
      showGenProgress(false);
      saveDraftLocal();
      refreshStudioJobPanel();
    }
  }

  async function onRetryFailed() {
    const taskId = String(state.lastTaskId || restoreJobId() || "").trim();
    if (!taskId || state.generating) return;
    if (!window.confirm("只重试失败或未发出的页，已成功的不会再扣。确认继续？")) return;
    state.generating = true;
    if ($("studioGenerate")) $("studioGenerate").disabled = true;
    if ($("studioRetryFailed")) $("studioRetryFailed").classList.add("hidden");
    if ($("studioCancelGenerate")) $("studioCancelGenerate").classList.remove("hidden");
    showGenProgress(true, "重试入队中…");
    try {
      setStatus("正在重试失败/未完成页…", true);
      const res = await api("/api/nai/jobs/retry?task_id=" + encodeURIComponent(taskId), {
        method: "POST",
        body: {},
      });
      if (!res.ok) throw new Error(res.message || res.error || "重试失败");
      const nextId = res.task_id || (res.batch && res.batch.task_id) || "";
      if (!nextId) throw new Error("未返回重试任务 ID");
      state.currentTaskId = nextId;
      state.lastTaskId = nextId;
      persistJobId(nextId);
      const accepted = Math.max(1, Number(res.total) || 0);
      setStatus(accepted > 1 ? `已重试入队 ${accepted} 张…` : "已重试入队…", true);
      const job = await window.ApiClient.pollJob(nextId, (status) => {
        const done = Number(status.done || 0);
        const total = Number(status.total || accepted);
        showGenProgress(true, total > 1 ? `重试中 ${done}/${total}…` : (status.message || "重试中…"));
        setStatus(status.message || (total > 1 ? `重试中 ${done}/${total}` : "重试中…"), true);
        renderStudioJobPanel(status, {});
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
      if (okItems.length) {
        const last = okItems[okItems.length - 1];
        setPreviewImage(last.image_url + (last.image_url.includes("?") ? "&" : "?") + "t=" + Date.now());
      }
      if (job.status === "cancelled") {
        throw new Error(job.message || "已取消");
      }
      const failed = Number(job.effective_fail_count || job.fail_count || 0);
      if (!okItems.length) {
        throw new Error(job.message || "重试后仍失败");
      }
      const doneMsg = failed
        ? `重试完成 ${okItems.length} 张，仍失败 ${failed}`
        : `重试完成 ${okItems.length} 张`;
      setStatus(job.message || doneMsg, true);
      toast(doneMsg, failed ? "err" : "ok");
    } catch (e) {
      setStatus(String(e.message || e), false);
      toast(String(e.message || e), "err");
    } finally {
      state.generating = false;
      state.currentTaskId = "";
      if ($("studioGenerate")) $("studioGenerate").disabled = false;
      if ($("studioCancelGenerate")) $("studioCancelGenerate").classList.add("hidden");
      showGenProgress(false);
      refreshStudioJobPanel();
    }
  }

  async function onCancelGenerate() {
    const taskId = String(state.currentTaskId || "").trim();
    if (!taskId) return;
    try {
      await api("/api/nai/jobs/cancel?task_id=" + encodeURIComponent(taskId), {
        method: "POST",
        body: {},
      });
      setStatus("已请求取消", true);
    } catch (e) {
      setStatus(String(e.message || e), false);
    }
  }

  function bind() {
    $("studioOptimize")?.addEventListener("click", () => onOptimize(currentOptimizeMode()));
    $("studioUndo")?.addEventListener("click", onUndo);
    $("studioGenerate")?.addEventListener("click", onGenerate);
    $("studioRetryFailed")?.addEventListener("click", onRetryFailed);
    $("studioCancelGenerate")?.addEventListener("click", onCancelGenerate);
    $("studioSeriesAll")?.addEventListener("change", () => {
      persistSeriesPref();
      syncSeriesToggle();
    });
    $("studioBatchPresets")?.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-copies]");
      if (!btn) return;
      setCopies(btn.getAttribute("data-copies"));
      refreshReady();
      saveDraftLocal();
    });
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
    ["studioPrompt", "studioBase", "studioCharCaptions", "studioUc", "studioWidth", "studioHeight", "studioSteps", "studioScale", "studioSeed", "studioSampler", "studioBatchCount"].forEach((id) => {
      $(id)?.addEventListener("input", () => {
        if (id === "studioBatchCount") setCopies($("studioBatchCount").value);
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
    let galleryId = params.get("gallery") || params.get("gallery_id") || "";
    if (window.WorkBridge) {
      const bridged = window.WorkBridge.load();
      if (bridged) {
        if (!workId && bridged.workId) {
          workId = bridged.workId;
          pageIndex = bridged.pageIndex || 0;
        }
        if (!galleryId && bridged.galleryId) galleryId = bridged.galleryId;
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
        await loadImport(workId, pageIndex, galleryId);
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
            await loadImport(draft.workId, draft.pageIndex || 0, draft.source?.provider || draft.galleryId);
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
    restoreCopies();
    restoreSeriesPref();
    refreshReady();
    if ($("studioVibeStrength") && $("studioStrengthVal")) {
      $("studioStrengthVal").textContent = Number($("studioVibeStrength").value || 0.6).toFixed(2);
    }
    resumeActiveJob();
    setInterval(() => {
      if (!state.generating) refreshStudioJobPanel();
    }, 3000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

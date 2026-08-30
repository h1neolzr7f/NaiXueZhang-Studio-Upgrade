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

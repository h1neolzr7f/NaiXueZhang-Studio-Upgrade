// CharSwap Plugin Entry Point (ES Module)

import { 
  state, 
  extractCache, 
  restoreDraftCache, 
  saveCurrentDraftToCache,
  normalizeWorkId,
  normalizeGalleryId,
} from "./state.js?v=f80b97d795";
import { 
  loadPluginConfig, 
  $,
  flashMsg
} from "./api.js?v=a73081883e";
import { 
  buildPanel, 
  initDraft, 
  renderSlotRows, 
  renderStyleRows, 
  mountSettings,
  bindToolbar,
  bindSeedControls
} from "./panel.js?v=9ce9824be0";
import { 
  fillStylePresetSelects,
  applyStylePreset
} from "./presets.js?v=f16dbe971d";
import { 
  isBatchMode, 
  loadBatchQueue, 
  addToBatch,
  addManyToBatch,
  removeWorkFromBatch, 
  batchKey,
  currentBatchGalleryId,
  refreshBatchCardChecks, 
  updateQuickAddHint, 
  mountBatchDrawer, 
  mountQuickFab, 
  unmountGenSidebar, 
  mountGenSidebar 
} from "./batch.js?v=78189662ea";

const PLUGIN_VERSION = "56-mount-gen";
window.__CHAR_SWAP_PLUGIN_VERSION__ = PLUGIN_VERSION;

/** Monotonic token so concurrent mountDetail/mountRemix drop stale work. */
let _mountGeneration = 0;

function currentDetailPayload() {
  const cached = window.__AITAG_CURRENT_DETAIL__;
  if (cached && cached.workId && cached.data) return cached;
  return null;
}

// Make the plugin accessible globally for compatibility with index.html and detail views
window.CharSwapPlugin = {
  unmount() {
    _mountGeneration += 1;
    const panel = document.getElementById("charSwapPanel");
    if (panel) panel.remove();
    if (state.batchPollTimer) {
      clearTimeout(state.batchPollTimer);
      state.batchPollTimer = null;
    }
    if (window.__charSwapHintInterval) {
      clearInterval(window.__charSwapHintInterval);
      window.__charSwapHintInterval = null;
    }
    unmountGenSidebar();
    extractCache.clear();
    state.workId = null;
    state.pageIndex = 0;
    state.galleryId = "site";
    state.original = null;
    state.draft = null;
    state.draftChars = [];
    state.styleSlots = [];
    state.styleBundle = { groups: [], combined: "", combined_all: "" };
    state.seedBeforeRandom = null;
    state.imagePageCount = 1;
    state.workTitle = "";
    try { updateQuickAddHint(); } catch { }
  },

  async _mountPanel(workId, data, attachAfter) {
    const gen = ++_mountGeneration;
    const url = new URL(window.location.href);
    const preservedGalleryId = normalizeGalleryId(
      url.searchParams.get("gallery")
      || url.searchParams.get("gallery_id")
      || state.galleryId
    );
    try {
      // unmount() also bumps generation — restore ours so this mount stays live.
      const panel = document.getElementById("charSwapPanel");
      if (panel) panel.remove();
      if (state.batchPollTimer) {
        clearTimeout(state.batchPollTimer);
        state.batchPollTimer = null;
      }
      if (window.__charSwapHintInterval) {
        clearInterval(window.__charSwapHintInterval);
        window.__charSwapHintInterval = null;
      }
      unmountGenSidebar();
      extractCache.clear();
      state.original = null;
      state.draft = null;
      state.draftChars = [];
      state.styleSlots = [];
      state.styleBundle = { groups: [], combined: "", combined_all: "" };
      state.seedBeforeRandom = null;
      state.imagePageCount = 1;
      state.workTitle = "";
    } catch { }
    if (gen !== _mountGeneration) return;
    state.galleryId = preservedGalleryId;
    restoreDraftCache();
    const cfg = await loadPluginConfig();
    if (gen !== _mountGeneration) return;
    if (document.getElementById("charSwapPanel")) return;
    if (cfg.plugin_enabled === false) return;

    const work = data.work || {};
    const wtype = String(work.AI_type || work.ai_type || work.image_type || "").toLowerCase();
    if (wtype !== "nai" && wtype !== "nai_x") return;

    const panel = buildPanel();
    if (typeof attachAfter === "function") {
      attachAfter(panel);
    } else if (attachAfter && attachAfter.appendChild) {
      attachAfter.appendChild(panel);
    } else {
      const imagesHost = document.getElementById("detailImages");
      if (imagesHost) {
        imagesHost.after(panel);
      } else {
        document.getElementById("detailView")?.appendChild(panel);
      }
    }

    const images = (data.images || []).slice().sort((a, b) => {
      const pa = parseInt(String(a.file_name || "0").match(/_p(\d+)/)?.[1] || "0", 10);
      const pb = parseInt(String(b.file_name || "0").match(/_p(\d+)/)?.[1] || "0", 10);
      return pa - pb;
    });
    state.workId = normalizeWorkId(workId);
    state.imagePageCount = images.length;
    state.workTitle = (data.work || {}).title || "";

    bindToolbar(panel);
    bindSeedControls(panel);
    fillStylePresetSelects().then(() => {
      const sp = document.getElementById("charSwapStylePreset");
      const panelMsgEl = $(".char-swap-msg", panel);
      if (sp && !sp.dataset.bound) {
        sp.dataset.bound = "1";
        sp.addEventListener("change", async () => {
          const opt = sp.selectedOptions[0];
          if (!opt || !opt.value) return;
          const preset = {
            id: opt.value,
            label: opt.textContent || opt.value,
            style: opt.dataset.style || "",
          };
          try {
            flashMsg(panelMsgEl, `正在消除画风并加入：${preset.label}…`, true);
            await applyStylePreset(preset, panel, panelMsgEl, {});
          } catch (e) {
            flashMsg(panelMsgEl, e.message || String(e), false);
          } finally {
            sp.value = "";
          }
        });
      }
    });

    // Header tabs for multi-page works
    if (images.length > 1) {
      const tabs = document.createElement("div");
      tabs.className = "char-swap-page-tabs";
      images.forEach((img, idx) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "char-swap-btn" + (idx === 0 ? " active" : "");
        b.textContent = `图 p${idx}`;
        b.addEventListener("click", async () => {
          tabs.querySelectorAll("button").forEach((x) => x.classList.remove("active"));
          b.classList.add("active");
          await initDraft(workId, idx, panel);
          renderSlotRows(panel);
          renderStyleRows(panel);
        });
        tabs.appendChild(b);
      });
      $(".char-swap-head", panel)?.appendChild(tabs);
    }
    
    await initDraft(workId, 0, panel, { throwOnError: true });
    if (gen !== _mountGeneration) {
      try { panel.remove(); } catch { }
      return;
    }
    updateQuickAddHint();
    const multiPage = images.length > 1;
    panel.querySelectorAll('[data-action="add-batch-all-pages"], [data-action="replace-male-all"], [data-action="replace-female-all"], [data-action="replace-style-all"]').forEach((btn) => {
      btn.style.display = multiPage ? "" : "none";
    });
    mountBatchDrawer();
    mountQuickFab();
  },

  async mountDetail(workId, data) {
    const cached = currentDetailPayload();
    if (!cached || normalizeWorkId(cached.workId) !== normalizeWorkId(workId)) return;
    await this._mountPanel(workId, data, null);
  },

  async mountRemix(workId, data, host, opts) {
    window.__AITAG_CURRENT_DETAIL__ = { workId: normalizeWorkId(workId), data };
    if (opts && opts.gallery_id) {
      state.galleryId = normalizeGalleryId(opts.gallery_id);
    }
    await this._mountPanel(workId, data, (panel) => {
      if (host) {
        host.innerHTML = "";
        host.appendChild(panel);
      }
    });
  },

  mountGenSidebar,
  unmountGenSidebar,

  addToBatch,
  addManyToBatch,
  decorateGalleryCard(card, work) {
    if (!card || card.querySelector(".char-swap-batch-check")) return;
    const chk = document.createElement("button");
    chk.type = "button";
    chk.className = "char-swap-batch-check";
    chk.title = "加入/移出批量队列";
    chk.textContent = "✓";
    chk.style.display = isBatchMode() ? "flex" : "none";
    const wid = normalizeWorkId(work && work.id);
    const galleryId = currentBatchGalleryId(work && work.gallery_id);
    const refresh = () => {
      const targetKey = batchKey(wid, 0, galleryId);
      const inQ = loadBatchQueue().some((x) => batchKey(x.work_id, x.page_index, x.gallery_id) === targetKey);
      chk.classList.toggle("active", inQ);
    };
    chk.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (loadBatchQueue().some((x) => batchKey(x.work_id, x.page_index, x.gallery_id) === batchKey(wid, 0, galleryId))) {
        removeWorkFromBatch(wid, galleryId);
      } else {
        addToBatch(wid, 0, { title: work.title, gallery_id: galleryId });
      }
      refresh();
    });
    refresh();
    card.appendChild(chk);
    refreshBatchCardChecks();
  },

  onGalleryUpdated() {
    refreshBatchCardChecks();
    updateQuickAddHint();
  },

  init() {
    mountSettings();
    mountBatchDrawer();
    mountQuickFab();
  }
};

// Initialize the plugin when document is ready
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => window.CharSwapPlugin.init());
} else {
  window.CharSwapPlugin.init();
}

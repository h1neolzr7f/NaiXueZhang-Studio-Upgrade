(function () {
  if (window.__AITAG_DETAIL_HOOKS__) return;
  window.__AITAG_DETAIL_HOOKS__ = true;
  const PLUGIN_URL = "/assets/plugins/char-swap/plugin.js?v=838915f997";
  const STYLE_URL = "/assets/plugins/char-swap/char-swap.css?v=220e25d883";
  let pluginPromise = null;

  function normalizeWorkId(value) {
    if (window.WorkBridge && typeof window.WorkBridge.normalizeWorkId === "function") {
      return window.WorkBridge.normalizeWorkId(value);
    }
    const id = String(value == null ? "" : value).trim();
    return /^\d+$/.test(id) && id !== "0" ? id : "";
  }

  function loadCharSwapStyles() {
    if (document.querySelector('link[data-char-swap-styles="1"]')) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = STYLE_URL;
    link.dataset.charSwapStyles = "1";
    document.head.appendChild(link);
  }

  function loadCharSwapPlugin() {
    loadCharSwapStyles();
    if (window.CharSwapPlugin) return Promise.resolve(window.CharSwapPlugin);
    if (!pluginPromise) {
      pluginPromise = import(PLUGIN_URL)
        .then(() => window.CharSwapPlugin || null)
        .catch((err) => {
          pluginPromise = null;
          console.warn("CharSwap plugin failed to load", err);
          return null;
        });
    }
    return pluginPromise;
  }

  window.addEventListener("aitag:detail-ready", async (ev) => {
    const detail = ev && ev.detail ? ev.detail : {};
    const workId = normalizeWorkId(detail.workId);
    const data = detail.data;
    const source = String(detail.source || (data && data.source) || "").trim();
    const online = source === "aitag-online"
      || (typeof window.isAitagGallery === "function" && window.isAitagGallery());
    if (online) return;
    if (!workId || !data) return;
    try {
      const plugin = await loadCharSwapPlugin();
      if (!plugin || typeof plugin.mountDetail !== "function") return;
      await plugin.mountDetail(workId, data);
    } catch (err) {
      console.warn("CharSwap mountDetail failed", err);
    }
  });

  window.GalleryDetailHooks = { loadCharSwapPlugin };
})();

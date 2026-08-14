(function () {
  const PLUGIN_URL = "/assets/plugins/char-swap/plugin.js?v=838915f997";
  let loadGeneration = 0;

  function normalizeWorkId(value) {
    if (window.WorkBridge && typeof window.WorkBridge.normalizeWorkId === "function") {
      return window.WorkBridge.normalizeWorkId(value);
    }
    const id = String(value == null ? "" : value).trim();
    return /^\d+$/.test(id) && id !== "0" ? id : "";
  }

  function setStatus(message, isError) {
    const status = document.getElementById("remixStatus");
    if (!status) return;
    status.textContent = String(message || "");
    status.style.color = isError ? "#ff8f9c" : "#8fa3be";
  }

  function setLoading(isLoading) {
    const form = document.getElementById("remixLoader");
    const input = document.getElementById("remixWorkId");
    const button = document.getElementById("remixLoadBtn");
    if (form) form.setAttribute("aria-busy", isLoading ? "true" : "false");
    if (input) input.disabled = Boolean(isLoading);
    if (button) {
      button.disabled = Boolean(isLoading);
      button.textContent = isLoading ? "加载中…" : "加载作品";
    }
  }

  function currentGalleryId() {
    const params = new URLSearchParams(window.location.search);
    return params.get("gallery") || params.get("gallery_id") || "site";
  }

  function isOnlineGallery(galleryId) {
    return String(galleryId || "").trim().toLowerCase() === "aitag-online";
  }

  function redirectOnlineWork(workId) {
    const id = encodeURIComponent(String(workId || "").trim());
    window.location.replace(`/i/${id}?gallery=aitag-online#onlineRemixPanel`);
  }

  function syncLoadedWorkContext(workId, galleryId) {
    const wid = normalizeWorkId(workId);
    const gid = galleryId || "site";
    if (window.WorkBridge && typeof window.WorkBridge.save === "function") {
      window.WorkBridge.save({ workId: wid, pageIndex: 0, galleryId: gid, from: "remix" });
    }
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("from", wid);
      url.searchParams.set("gallery", gid);
      for (const key of ["work_id", "id", "target_work_id", "gallery_id"]) {
        url.searchParams.delete(key);
      }
      window.history.replaceState(null, "", url.pathname + url.search + url.hash);
    } catch (_) {}
  }

  async function fetchWork(workId, galleryId) {
    const gid = galleryId || "site";
    const wid = normalizeWorkId(workId);
    if (window.WorkBridge && typeof window.WorkBridge.loadDetail === "function") {
      const cached = window.WorkBridge.loadDetail(wid, gid);
      if (cached) return cached;
    }
    return await ApiClient.get(`/api/work/${encodeURIComponent(wid)}?gallery_id=${encodeURIComponent(gid)}`);
  }

  async function ensurePlugin() {
    if (window.CharSwapPlugin) return window.CharSwapPlugin;
    await import(PLUGIN_URL);
    return window.CharSwapPlugin || null;
  }

  async function mountWork(workId, galleryId) {
    const host = document.getElementById("remixHost");
    const empty = document.getElementById("remixEmpty");
    if (!host) return;
    const gid = galleryId || "site";
    const wid = normalizeWorkId(workId);
    if (!wid) throw new Error("请输入有效的作品 ID");
    if (isOnlineGallery(gid)) {
      redirectOnlineWork(wid);
      return false;
    }
    const requestGeneration = ++loadGeneration;
    setLoading(true);
    setStatus(`正在载入作品 #${wid}…`, false);
    try {
      const data = await fetchWork(wid, gid);
      if (requestGeneration !== loadGeneration) return false;
      const wtype = String((data.work || {}).AI_type || (data.work || {}).ai_type || "").toLowerCase();
      if (wtype !== "nai" && wtype !== "nai_x") {
        throw new Error("仅支持 NAI / NAI_X 作品");
      }
      window.__AITAG_CURRENT_DETAIL__ = { workId: wid, galleryId: gid, data };
      const plugin = await ensurePlugin();
      if (requestGeneration !== loadGeneration) return false;
      if (!plugin || typeof plugin.mountRemix !== "function") {
        throw new Error("换角洗稿插件未就绪");
      }
      await plugin.mountRemix(wid, data, host, { gallery_id: gid });
      if (requestGeneration !== loadGeneration) return false;
      if (empty) empty.style.display = "none";
      syncLoadedWorkContext(wid, gid);
      setStatus(`已载入作品 #${wid}`, false);
      return true;
    } finally {
      if (requestGeneration === loadGeneration) setLoading(false);
    }
  }

  function bind() {
    const form = document.getElementById("remixLoader");
    const input = document.getElementById("remixWorkId");
    form?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (form.getAttribute("aria-busy") === "true") return;
      const wid = normalizeWorkId((input || {}).value);
      if (!wid) {
        setStatus("请输入有效的作品 ID", true);
        input?.focus();
        input?.select();
        return;
      }
      try {
        await mountWork(wid, currentGalleryId());
      } catch (e) {
        setStatus(String(e.message || e), true);
      }
    });
  }

  async function boot() {
    bind();
    const params = new URLSearchParams(window.location.search);
    let workId = normalizeWorkId(params.get("from") || params.get("work") || params.get("work_id") || params.get("id") || params.get("target_work_id"));
    let galleryId = params.get("gallery") || params.get("gallery_id");
    if (!galleryId) galleryId = "site";
    if (isOnlineGallery(galleryId)) {
      if (workId) {
        redirectOnlineWork(workId);
        return;
      }
      setStatus("在线灵感库请打开作品详情后使用「角色换角」。本地换角页不加载在线作品。", true);
      return;
    }
    if (workId) {
      const input = document.getElementById("remixWorkId");
      if (input) input.value = String(workId);
      try {
        await mountWork(workId, galleryId);
      } catch (e) {
        setStatus(String(e.message || e), true);
        console.warn(e);
      }
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();

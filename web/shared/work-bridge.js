(function () {
  const KEY = "aitag.workBridge";
  const DETAIL_KEY = "aitag.workBridgeDetail";

  function normalizeWorkId(value) {
    const id = String(value == null ? "" : value).trim();
    if (/^\d+$/.test(id) && id !== "0") return id;
    // 法典图鉴词条：book_id:entry_id，例如 suozhang:sz-0001
    if (/^[a-z0-9_]{1,64}:[A-Za-z0-9._-]{1,180}$/.test(id)) return id;
    return "";
  }

  function activeGalleryId() {
    try {
      if (typeof document !== "undefined") {
        const select = document.getElementById("gallerySource");
        if (select && select.value) return select.value;
        const btn = document.querySelector("#gallerySourceSwitch .gallery-source-button[aria-pressed='true']");
        if (btn && btn.dataset && btn.dataset.gallerySource) return btn.dataset.gallerySource;
      }
      const url = new URL(window.location.href);
      return url.searchParams.get("gallery") || url.searchParams.get("gallery_id") || "site";
    } catch (_) {
      return "site";
    }
  }

  function withGalleryContext(urlOrPath) {
    const raw = String(urlOrPath || "");
    try {
      const target = new URL(raw, window.location.origin);
      const current = new URL(window.location.href, window.location.origin);
      if (target.origin !== window.location.origin) return raw;
      for (const key of ["gallery", "group"]) {
        const value = target.searchParams.get(key) || current.searchParams.get(key);
        if (value && !target.searchParams.has(key)) target.searchParams.set(key, value);
      }
      if (!target.searchParams.has("gallery")) {
        const gid = activeGalleryId();
        if (gid) target.searchParams.set("gallery", gid);
      }
      return target.pathname + target.search + target.hash;
    } catch (_) {
      return raw;
    }
  }

  function save(payload) {
    const gid = payload.galleryId || activeGalleryId();
    const data = {
      workId: normalizeWorkId(payload.workId),
      pageIndex: Number(payload.pageIndex) || 0,
      galleryId: gid,
      from: String(payload.from || "gallery"),
      ts: Date.now(),
    };
    try {
      sessionStorage.setItem(KEY, JSON.stringify(data));
    } catch (_) { /* ignore */ }
    return data;
  }

  function saveDetail(workId, galleryId, detailData) {
    const gid = galleryId || activeGalleryId();
    const wid = normalizeWorkId(workId);
    try {
      sessionStorage.setItem(DETAIL_KEY, JSON.stringify({
        workId: wid,
        galleryId: gid,
        data: detailData,
        ts: Date.now(),
      }));
    } catch (_) {}
  }

  function loadDetail(workId, galleryId) {
    try {
      const raw = sessionStorage.getItem(DETAIL_KEY);
      if (!raw) return null;
      const cached = JSON.parse(raw);
      if (!cached || Date.now() - cached.ts > 300000) return null;
      if (normalizeWorkId(cached.workId) === normalizeWorkId(workId)) {
        if (!galleryId || cached.galleryId === galleryId) {
          return cached.data;
        }
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  function load() {
    try {
      const raw = sessionStorage.getItem(KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (!data || !data.workId) return null;
      return data;
    } catch (_) {
      return null;
    }
  }

  function buildUrl(base, workId, pageIndex, galleryId) {
    const u = new URL(base, window.location.origin);
    const id = normalizeWorkId(workId);
    if (id) u.searchParams.set("from", id);
    if (pageIndex) u.searchParams.set("page", String(pageIndex));
    const gid = galleryId || activeGalleryId();
    if (gid) u.searchParams.set("gallery", gid);
    // Propagate group from current URL if not already set
    try {
      const current = new URL(window.location.href);
      const group = current.searchParams.get("group");
      if (group && !u.searchParams.has("group")) u.searchParams.set("group", group);
    } catch (_) {}
    return u.pathname + u.search;
  }

  function go(target, workId, pageIndex, galleryId) {
    const gid = galleryId || activeGalleryId();
    save({ workId, pageIndex, galleryId: gid, from: "gallery" });
    window.location.href = buildUrl(target, workId, pageIndex, gid);
  }

  window.WorkBridge = { save, load, saveDetail, loadDetail, buildUrl, go, normalizeWorkId, withGalleryContext, KEY };
})();

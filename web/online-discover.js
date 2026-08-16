// Classic gallery Online / My Library switch. Does not add a ninth primary nav item.
(function () {
  const api = window.ApiClient;
  if (!api) return;

  function $(id) {
    return document.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function lifecycleLabel(item) {
    if (item.available === false) return "来源暂不可用，仍可看收藏快照";
    if (item.lifecycle === "materialized") return "已在我的图库";
    if (item.lifecycle === "cached") return "已缓存，尚未入库";
    if (item.favorite) return "已收藏引用";
    return "在线引用";
  }

  function isOnline() {
    return document.body.classList.contains("online-discover-active");
  }

  function setOnline(on) {
    document.body.classList.toggle("online-discover-active", on);
    const panel = $("onlineDiscover");
    const grid = $("gallery");
    const btn = $("onlineDiscoverBtn");
    if (panel) {
      panel.hidden = !on;
      panel.classList.toggle("hidden", !on);
    }
    if (grid) grid.classList.toggle("is-online-hidden", on);
    if (btn) btn.setAttribute("aria-pressed", on ? "true" : "false");
    const title = $("gallerySearchTitle");
    const resultsTitle = $("galleryResultsTitle");
    if (title) title.textContent = on ? "检索在线发现" : "检索本地图谱";
    if (resultsTitle) resultsTitle.textContent = on ? "在线发现" : "作品流";
    if (on) void runSearch();
  }

  function render(items) {
    const host = $("onlineDiscoverGrid");
    if (!host) return;
    host.replaceChildren();
    (items || []).forEach((item) => {
      const remoteId = String((item.ref && item.ref.remote_id) || item.qualified_id || "");
      const card = document.createElement("article");
      card.className = "card online-discover-card";
      card.innerHTML = `
        ${item.thumb_url ? `<img src="${escapeHtml(item.thumb_url)}" alt="${escapeHtml(item.title || remoteId)}" />` : "<div class='online-discover-placeholder'></div>"}
        <div class="card-link">
          <strong>${escapeHtml(item.title || remoteId)}</strong>
          <p>${escapeHtml(lifecycleLabel(item))}</p>
          <div class="online-discover-actions">
            <button type="button" data-online-add="${escapeHtml(remoteId)}">加入我的图库</button>
            <button type="button" data-online-fav="${escapeHtml(remoteId)}">${item.favorite ? "已收藏引用" : "收藏（不下载）"}</button>
          </div>
        </div>
      `;
      host.appendChild(card);
    });
  }

  async function runSearch() {
    const status = $("onlineDiscoverStatus");
    const query = String(($("q") && $("q").value) || "").trim();
    if (status) status.textContent = "正在搜索在线引用…";
    try {
      const data = await api.get("/api/online/search?q=" + encodeURIComponent(query));
      if (!data.ok) {
        if (status) status.textContent = data.message || "在线来源暂不可用，本地图库仍可继续用。";
        render([]);
        return;
      }
      render(data.items || []);
      if (status) {
        status.textContent = (data.items || []).length
          ? "收藏只记引用；加入我的图库才会下载入库。"
          : "在线区还没有结果。换个词搜索，或先回我的图库。";
      }
    } catch (error) {
      if (status) status.textContent = error instanceof Error ? error.message : String(error);
    }
  }

  async function favorite(remoteId) {
    await api.post("/api/online/favorite", { remote_id: remoteId });
    await runSearch();
  }

  async function addToLibrary(remoteId) {
    const status = $("onlineDiscoverStatus");
    if (status) status.textContent = "正在加入我的图库…";
    const data = await api.post("/api/online/add-to-library", {
      remote_id: remoteId,
      gallery_id: "codex",
    });
    if (data && data.work_id) {
      window.location.assign("/studio?from=" + encodeURIComponent(String(data.work_id)) + "&gallery=codex");
      return;
    }
    if (status) status.textContent = (data && data.message) || "已加入我的图库";
  }

  document.addEventListener("click", (event) => {
    const add = event.target.closest("[data-online-add]");
    if (add) {
      event.preventDefault();
      void addToLibrary(add.getAttribute("data-online-add") || "");
      return;
    }
    const fav = event.target.closest("[data-online-fav]");
    if (fav) {
      event.preventDefault();
      void favorite(fav.getAttribute("data-online-fav") || "");
    }
  });

  const onlineBtn = $("onlineDiscoverBtn");
  if (onlineBtn) {
    onlineBtn.addEventListener("click", () => setOnline(!isOnline()));
  }
  document.getElementById("gallerySourceSwitch")?.addEventListener("click", (event) => {
    if (event.target.closest("[data-gallery-source]") && isOnline()) setOnline(false);
  });
  $("searchBtn")?.addEventListener(
    "click",
    (event) => {
      if (!isOnline()) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      void runSearch();
    },
    true,
  );
  $("q")?.addEventListener("keydown", (event) => {
    if (!isOnline() || event.key !== "Enter") return;
    event.preventDefault();
    event.stopImmediatePropagation();
    void runSearch();
  });
})();

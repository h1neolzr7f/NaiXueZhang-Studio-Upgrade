(function () {
  // Product IA: gallery assets first, production surfaces second, ops last.
  const NAV_PRIMARY = [
    { href: "/app", id: "gallery", label: "图库" },
    { href: "/app/generated", id: "generated", label: "生成库" },
    { href: "/app/studio", id: "studio", label: "工作台" },
    { href: "/app/butler", id: "butler", label: "小镜" },
    { href: "/app/remix", id: "remix", label: "换角" },
    { href: "/app/progress", id: "progress", label: "爬虫" },
    { href: "/app/tags", id: "nai-tags", label: "分类" },
    { href: "/app/pixiv", id: "pixiv", label: "发布" },
  ];
  const NAV_SECONDARY = [
    { href: "/queue", id: "queue", label: "待生成", group: "创作" },
    { href: "/director", id: "director", label: "导演台", group: "创作" },
    { href: "/favorites", id: "favorites", label: "收藏", group: "创作" },
    { href: "/references", id: "references", label: "参考库", group: "创作" },
    { href: "/codex", id: "codex", label: "自选库", group: "创作" },
    { href: "/", id: "classic", label: "经典图库", group: "创作" },
    { href: "/pipeline", id: "pipeline", label: "后处理", group: "管理" },
    { href: "/tag-assets", id: "tag-assets", label: "本地资产", group: "管理" },
    { href: "/settings", id: "settings", label: "设置", group: "系统" },
    { href: "/maintenance", id: "maintenance", label: "维护", group: "系统" },
    { href: "/ops", id: "ops", label: "运营", group: "系统" },
    { href: "/compliance", id: "compliance", label: "合规与来源", group: "系统" },
  ];

  function currentNavId() {
    const p = (window.location.pathname || "/").replace(/\/+$/, "") || "/";
    if (p.startsWith("/app/studio") || p.startsWith("/studio")) return "studio";
    if (p.startsWith("/app/generated") || p.startsWith("/generated")) return "generated";
    if (p.startsWith("/app/butler") || p.startsWith("/butler")) return "butler";
    if (p.startsWith("/app/settings") || p.startsWith("/settings")) return "settings";
    if (p.startsWith("/app/remix") || p.startsWith("/remix")) return "remix";
    if (p.startsWith("/app/progress") || p.startsWith("/progress")) return "progress";
    if (p.startsWith("/app/pixiv") || p.startsWith("/pixiv")) return "pixiv";
    if (p.startsWith("/app/pipeline") || p.startsWith("/pipeline")) return "pipeline";
    if (p.startsWith("/app/director") || p.startsWith("/director")) return "director";
    if (p.startsWith("/app/tags") || p.startsWith("/nai-tags")) return "nai-tags";
    if (p.startsWith("/app/ops") || p.startsWith("/ops")) return "ops";
    if (p.startsWith("/app/compliance") || p.startsWith("/compliance")) return "compliance";
    if (p === "/") return "classic";
    if (p.startsWith("/i/") || p === "/app" || p.startsWith("/app")) return "gallery";
    if (p.startsWith("/references")) return "references";
    if (p.startsWith("/favorites")) return "favorites";
    if (p.startsWith("/queue")) return "queue";
    if (p.startsWith("/maintenance")) return "maintenance";
    if (p.startsWith("/tag-assets")) return "tag-assets";
    if (p.startsWith("/codex")) return "codex";
    if (p.startsWith("/pipeline")) return "pipeline";
    if (p.startsWith("/ops")) return "ops";
    if (p.startsWith("/pixiv")) return "pixiv";
    if (p.startsWith("/progress")) return "progress";
    if (p.startsWith("/nai-tags")) return "nai-tags";
    if (p.startsWith("/compliance")) return "compliance";
    return "";
  }

  function appendItems(el, items, active) {
    let lastGroup = "";
    items.forEach((item) => {
      if (item.group && item.group !== lastGroup) {
        lastGroup = item.group;
        const heading = document.createElement("div");
        heading.className = "nav-more-group";
        heading.textContent = item.group;
        heading.setAttribute("aria-hidden", "true");
        el.appendChild(heading);
      }
      const a = document.createElement("a");
      a.href = item.href;
      a.textContent = item.label;
      a.dataset.navId = item.id;
      if (item.id === active) {
        a.classList.add("active");
        a.setAttribute("aria-current", "page");
      }
      el.appendChild(a);
    });
  }

  function mountNav(host) {
    const el = host || document.getElementById("siteNav");
    if (!el) return;
    if (typeof el._siteNavCleanup === "function") el._siteNavCleanup();
    const active = currentNavId();
    el.className = "site-nav";
    el.innerHTML = "";
    el.setAttribute("aria-label", "主导航");
    if (String(el.tagName || "").toUpperCase() !== "NAV") el.setAttribute("role", "navigation");
    appendItems(el, NAV_PRIMARY, active);

    const divider = document.createElement("span");
    divider.className = "nav-divider";
    divider.setAttribute("aria-hidden", "true");
    el.appendChild(divider);

    const more = document.createElement("details");
    more.className = "nav-more-dropdown";
    more.open = false;
    const summary = document.createElement("summary");
    summary.className = "nav-more-trigger";
    const activeItem = NAV_SECONDARY.find((item) => item.id === active);
    summary.textContent = "更多";
    if (activeItem) summary.classList.add("active");
    summary.setAttribute("aria-label", activeItem ? `更多，当前：${activeItem.label}` : "更多功能");
    summary.setAttribute("aria-expanded", "false");
    const menu = document.createElement("div");
    menu.className = "nav-more-menu";
    menu.setAttribute("role", "group");
    menu.setAttribute("aria-label", "更多功能");
    appendItems(menu, NAV_SECONDARY, active);
    more.appendChild(summary);
    more.appendChild(menu);
    el.appendChild(more);

    const onToggle = () => summary.setAttribute("aria-expanded", more.open ? "true" : "false");
    const onKeydown = (event) => {
      if (event.key !== "Escape" || !more.open) return;
      more.open = false;
      onToggle();
      if (typeof summary.focus === "function") summary.focus();
    };
    const onDocumentPointerDown = (event) => {
      if (!more.open || typeof more.contains !== "function" || more.contains(event.target)) return;
      more.open = false;
      onToggle();
    };
    if (typeof more.addEventListener === "function") {
      more.addEventListener("toggle", onToggle);
      more.addEventListener("keydown", onKeydown);
    }
    if (typeof document.addEventListener === "function") document.addEventListener("pointerdown", onDocumentPointerDown);
    el._siteNavCleanup = () => {
      if (typeof more.removeEventListener === "function") {
        more.removeEventListener("toggle", onToggle);
        more.removeEventListener("keydown", onKeydown);
      }
      document.removeEventListener("pointerdown", onDocumentPointerDown);
    };

    const spacer = document.createElement("span");
    spacer.className = "nav-spacer";
    el.appendChild(spacer);
    const note = document.createElement("span");
    note.className = "nav-note";
    note.textContent = "本地图库资产 · 再创作流水线";
    el.appendChild(note);
  }

  async function acknowledgeNotice() {
    if (!window.ApiClient || typeof window.ApiClient.post !== "function") {
      throw new Error("ApiClient unavailable");
    }
    return window.ApiClient.post("/api/compliance/notice/accept", {
      app_version: window.__APP_VERSION__ || "",
    });
  }

  function renderResponsibilityNotice() {
    if (document.getElementById("responsibilityNotice")) return;
    const style = document.createElement("style");
    style.textContent = `
      .responsibility-notice{position:fixed;right:18px;bottom:18px;z-index:10000;width:min(440px,calc(100vw - 36px));box-sizing:border-box;padding:16px 18px;border:1px solid rgba(93,228,255,.35);border-radius:14px;background:#101823;color:#d7e6f5;box-shadow:0 18px 48px rgba(0,0,0,.55),0 0 24px rgba(93,228,255,.08);font:13px/1.6 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}
      .responsibility-notice strong{display:block;margin-bottom:5px;font-size:14px;color:#5de4ff}.responsibility-notice p{margin:0 0 10px}.responsibility-notice-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.responsibility-notice button{border:0;border-radius:8px;padding:7px 12px;background:linear-gradient(135deg,#35b6f2,#1d83d4);color:#04121e;font-weight:700;cursor:pointer}.responsibility-notice a{color:#8fd8ff;text-decoration:none}.responsibility-notice small{color:#7c8ea3}
    `;
    document.head.appendChild(style);
    const box = document.createElement("aside");
    box.id = "responsibilityNotice";
    box.className = "responsibility-notice";
    box.setAttribute("role", "status");
    box.innerHTML = `
      <strong>非官方项目与使用责任提示</strong>
      <p>本工具在本机运行。请自行确认访问、下载、处理与发布行为符合适用法律、平台规则及第三方权利要求。</p>
      <div class="responsibility-notice-actions">
        <button type="button" data-acknowledge>我已阅读并理解</button>
        <a href="/compliance">查看完整条款与来源管理</a>
        <small>不上传身份或确认记录</small>
      </div>`;
    box.querySelector("[data-acknowledge]").addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await acknowledgeNotice();
        box.remove();
        style.remove();
      } catch (error) {
        button.disabled = false;
        button.textContent = "保存失败，请重试";
        console.warn("responsibility notice accept failed", error);
      }
    });
    document.body.appendChild(box);
  }

  async function mountResponsibilityNotice() {
    if ((window.location.pathname || "").startsWith("/compliance")) return;
    if (!window.ApiClient || typeof window.ApiClient.raw !== "function") return;
    try {
      const response = await window.ApiClient.raw("/api/compliance/notice/status", { cache: "no-store" });
      if (!response.ok) return;
      const status = await response.json();
      if (status.required) renderResponsibilityNotice();
    } catch (error) {
      console.warn("responsibility notice status failed", error);
    }
  }

  window.SiteNav = {
    mount: mountNav,
    currentNavId,
    PRIMARY: NAV_PRIMARY,
    SECONDARY: NAV_SECONDARY,
  };

  function start() {
    mountNav();
    mountResponsibilityNotice();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

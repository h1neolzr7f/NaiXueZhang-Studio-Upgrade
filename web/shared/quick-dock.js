(function () {
  // Nai学长工作室 · 全局快捷面板（⌘K / Ctrl+K）
  // 目的：减少页面反复跳转——任意页面一键搜索直达 + 常用动作。
  const ACTIONS = [
    { id: "act-search", label: "检索图库", hint: "/", group: "动作", run: () => go("/", "#q") },
    { id: "act-generate", label: "去工作台生成", hint: "/studio", group: "动作", run: () => go("/studio") },
    { id: "act-tomori", label: "问助手凑企鹅", hint: "/butler?agent=tomori", group: "动作", run: () => {
      if (window.CompanionDock && typeof window.CompanionDock.open === "function") {
        window.CompanionDock.open("tomori");
        return;
      }
      go("/butler?agent=tomori");
    } },
    { id: "act-crawl", label: "开始采集", hint: "/progress", group: "动作", run: () => go("/progress") },
    { id: "act-queue", label: "看待生成队列", hint: "/queue", group: "动作", run: () => go("/queue") },
    { id: "act-publish", label: "发布到 Pixiv", hint: "/pixiv", group: "动作", run: () => go("/pixiv") },
  ];

  function go(href, focusSelector) {
    if (focusSelector && (window.location.pathname === href)) {
      const el = document.querySelector(focusSelector);
      if (el) { el.focus(); el.scrollIntoView({ block: "center", behavior: "smooth" }); return; }
    }
    window.location.href = href;
  }

  function pageEntries() {
    const nav = window.SiteNav || {};
    const groups = nav.GROUPS || [];
    const all = nav.ALL || (nav.PRIMARY || []).concat(nav.SECONDARY || []);
    const entries = [];
    groups.forEach((group) => {
      group.ids.forEach((id) => {
        const item = all.find((entry) => entry.id === id);
        if (item) entries.push({ label: item.label, hint: item.href, group: group.title, run: () => go(item.href) });
      });
    });
    if (!entries.length) {
      all.forEach((item) => entries.push({ label: item.label, hint: item.href, group: "页面", run: () => go(item.href) }));
    }
    return entries;
  }

  let overlay = null;
  let input = null;
  let list = null;
  let activeIndex = 0;
  let visible = [];

  function matches(entry, query) {
    if (!query) return true;
    const q = query.toLowerCase();
    return entry.label.toLowerCase().includes(q) || entry.hint.toLowerCase().includes(q) || entry.group.toLowerCase().includes(q);
  }

  function render() {
    const query = (input.value || "").trim();
    const entries = ACTIONS.concat(pageEntries());
    visible = entries.filter((entry) => matches(entry, query));
    if (activeIndex >= visible.length) activeIndex = visible.length - 1;
    if (activeIndex < 0) activeIndex = 0;
    list.innerHTML = "";
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "qd-empty";
      empty.textContent = "没有匹配的页面或动作";
      list.appendChild(empty);
      return;
    }
    let lastGroup = null;
    visible.forEach((entry, index) => {
      if (entry.group !== lastGroup) {
        lastGroup = entry.group;
        const title = document.createElement("div");
        title.className = "qd-group-title";
        title.textContent = entry.group;
        list.appendChild(title);
      }
      const item = document.createElement("button");
      item.type = "button";
      item.className = "qd-item" + (index === activeIndex ? " is-active" : "");
      item.innerHTML = `<span>${entry.label}</span><small>${entry.hint}</small>`;
      item.addEventListener("click", () => { close(); entry.run(); });
      item.addEventListener("mousemove", () => {
        if (activeIndex !== index) { activeIndex = index; paintActive(); }
      });
      list.appendChild(item);
    });
  }

  function paintActive() {
    list.querySelectorAll(".qd-item").forEach((el) => el.classList.remove("is-active"));
    const items = list.querySelectorAll(".qd-item");
    // 注意：分组标题不占索引，需要按可见项顺序对应
    let i = 0;
    items.forEach((el) => {
      if (i === activeIndex) el.classList.add("is-active");
      i += 1;
    });
    const active = list.querySelector(".qd-item.is-active");
    if (active) active.scrollIntoView({ block: "nearest" });
  }

  function open() {
    if (overlay) { close(); return; }
    overlay = document.createElement("div");
    overlay.className = "qd-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-label", "快捷跳转");
    const panel = document.createElement("div");
    panel.className = "qd-panel";
    input = document.createElement("input");
    input.className = "qd-input";
    input.type = "text";
    input.placeholder = "输入页面或动作名称…";
    input.setAttribute("aria-label", "搜索页面或动作");
    list = document.createElement("div");
    list.className = "qd-list";
    const foot = document.createElement("div");
    foot.className = "qd-foot";
    foot.innerHTML = "<span><b>↑↓</b> 选择</span><span><b>Enter</b> 前往</span><span><b>Esc</b> 关闭</span>";
    panel.appendChild(input);
    panel.appendChild(list);
    panel.appendChild(foot);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    activeIndex = 0;
    render();
    input.focus();
    input.addEventListener("input", () => { activeIndex = 0; render(); });
    input.addEventListener("keydown", onKeys);
    overlay.addEventListener("pointerdown", (event) => {
      if (event.target === overlay) close();
    });
  }

  function onKeys(event) {
    if (event.key === "ArrowDown") { event.preventDefault(); activeIndex = Math.min(activeIndex + 1, visible.length - 1); paintActive(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); paintActive(); }
    else if (event.key === "Enter") {
      event.preventDefault();
      const entry = visible[activeIndex];
      if (entry) { close(); entry.run(); }
    } else if (event.key === "Escape") { close(); }
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    input = null;
    list = null;
  }

  function mountLauncher() {
    if (document.querySelector(".qd-launcher")) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "qd-launcher";
    btn.innerHTML = '<span class="nv-kbd-key" aria-hidden="true">⌘K</span><span class="qd-launcher-text">快捷跳转</span>';
    btn.setAttribute("aria-label", "打开快捷跳转面板");
    btn.addEventListener("click", open);
    document.body.appendChild(btn);
    // 详情浮层打开时底部有 save-dock，把入口抬高避免遮挡
    const detail = document.getElementById("detailView");
    if (detail && typeof MutationObserver === "function") {
      const sync = () => {
        const open_ = detail.classList.contains("is-open") && !detail.classList.contains("hidden");
        btn.style.bottom = open_ ? "92px" : "";
      };
      new MutationObserver(sync).observe(detail, { attributes: true, attributeFilter: ["class"] });
      sync();
    }
  }

  document.addEventListener("keydown", (event) => {
    const isK = (event.key || "").toLowerCase() === "k";
    if (isK && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      if (overlay) close(); else open();
    }
  });
  document.addEventListener("quickdock:open", open);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountLauncher);
  } else {
    mountLauncher();
  }

  window.QuickDock = { open, close };
})();

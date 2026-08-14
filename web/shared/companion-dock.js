(function () {
  const CATALOG_URL = "/assets/vendor/live2d-models/companions.json";
  const WIDGET_SRC = "/assets/vendor/l2d-widget/index.min.js?v=87d455d82f";
  const TOUCH_SRC = "/assets/shared/live2d-touch.js?v=dd0a813c9f";
  const FALLBACK_CATALOG = {
    sakiko: {
      scale: 1.05,
      offset: [0, 0.18],
      default_costume: "causal",
      costumes: {
        causal: { label: "便服", path: "/assets/vendor/live2d-models/sakiko/causal/model.json" },
      },
    },
    tomori: {
      scale: 1.05,
      offset: [0, 0.18],
      default_costume: "casual",
      costumes: {
        casual: { label: "便服", path: "/assets/vendor/live2d-models/tomori/casual/model.json" },
      },
    },
  };
  const AGENTS = {
    sakiko: {
      id: "sakiko",
      side: "left",
      name: "客服小祥",
      peek: "客服小祥",
      mark: "祥",
      duty: "处理、维护和使用教学",
      greeting: "有事就说。用法、采集和排障我来。",
      placeholder: "例如：图库怎么用，或帮我检查采集",
      chips: [
        ["怎么用", "我是新手，请按步骤教我怎么开始用这个软件"],
        ["检查图库", "帮我检查图库状态，并告诉我最需要先处理的三件事"],
        ["采集状态", "查看当前采集是否在跑，有没有缺图或耗尽封面"],
      ],
    },
    tomori: {
      id: "tomori",
      side: "right",
      name: "助手凑企鹅",
      peek: "凑企鹅",
      mark: "灯",
      duty: "选材与生成",
      greeting: "那个……想出图的话，我在这里。咕。",
      placeholder: "例如：从待生成里挑任务，先给参数不要立刻出图",
      chips: [
        ["找素材", "找最近一个月收藏最多的 6 个适合继续生成的作品，先给候选不要生图"],
        ["准备出图", "从待生成队列里挑任务，先给参数建议，不要立刻调用 NAI"],
        ["整理投稿", "把最新的生成结果整理成 Pixiv 投稿草稿，不要上传"],
      ],
    },
  };

  const state = {
    catalog: FALLBACK_CATALOG,
    openId: "",
    pinned: "",
    hideTimer: 0,
    starting: { sakiko: false, tomori: false },
    widgets: { sakiko: null, tomori: null },
    canvases: { sakiko: null, tomori: null },
    busy: { sakiko: false, tomori: false },
  };

  function onButlerPage() {
    const path = (window.location.pathname || "").replace(/\/+$/, "") || "/";
    return path === "/butler" || path.startsWith("/app/butler");
  }

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function api() {
    return window.ApiClient;
  }

  function $(sel, root) {
    return (root || document).querySelector(sel);
  }

  function isSummer() {
    const month = new Date().getMonth() + 1;
    return month >= 5 && month <= 9;
  }

  function costumeFor(agentId) {
    const profile = state.catalog[agentId];
    if (!profile) return "";
    let spec = (profile.situations && profile.situations.ready) || profile.default_costume;
    if (Array.isArray(spec) && spec.length) spec = spec[0];
    if (spec === "school" && profile.school) {
      spec = isSummer() ? profile.school.summer : profile.school.winter;
    }
    return spec || profile.default_costume || "";
  }

  function ensureCss() {
    if (document.querySelector("link[data-companion-dock]")) return;
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/assets/shared/companion-dock.css?v=cebc7fec7f";
    link.dataset.companionDock = "1";
    document.head.appendChild(link);
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing && window.L2D_WIDGET) {
        resolve();
        return;
      }
      const script = existing || document.createElement("script");
      script.src = src;
      script.async = true;
      script.addEventListener("load", resolve, { once: true });
      script.addEventListener("error", () => reject(new Error("Live2D 组件加载失败")), { once: true });
      if (!existing) document.head.appendChild(script);
    });
  }

  function setMood(agentId, text) {
    const node = $(`.companion-dock[data-agent="${agentId}"] .companion-mood`);
    if (node) node.textContent = text;
  }

  function setLog(agentId, text) {
    const node = $(`.companion-dock[data-agent="${agentId}"] .companion-log`);
    if (!node) return;
    node.textContent = text || "";
  }

  function tapLine(agentId, kind) {
    if (agentId === "tomori") {
      return kind === "head" ? "那个、头发……" : "我在听。咕。";
    }
    return kind === "head" ? "等一下……" : "有事就说。";
  }

  function bindTouch(agentId) {
    const stage = document.getElementById(`companionStage-${agentId}`);
    if (!window.Live2dTouch || !stage) return;
    window.Live2dTouch.bind(stage, {
      getWidget: () => state.widgets[agentId],
      tone: agentId === "tomori" ? "pink" : "gold",
      onTap(kind) {
        pin(agentId);
        setMood(agentId, tapLine(agentId, kind));
      },
    });
  }

  function costumeLabel(agentId) {
    const profile = state.catalog[agentId] || {};
    const id = costumeFor(agentId);
    const row = profile.costumes && profile.costumes[id];
    return (row && row.label) || "情景服饰";
  }

  function dockHasFocus(agentId) {
    const dock = $(`.companion-dock[data-agent="${agentId}"]`);
    const active = document.activeElement;
    return Boolean(dock && active && dock.contains(active));
  }

  function hideWidgetShell(canvas, stage) {
    const shell = canvas && canvas.parentElement;
    if (!canvas || !stage) return;
    ["position", "left", "top", "right", "bottom", "width", "height", "transform"].forEach((key) => {
      canvas.style.removeProperty(key);
    });
    stage.appendChild(canvas);
    if (shell && shell !== stage && shell !== document.body && !shell.closest(".companion-dock, .butler-live2d-stage")) {
      shell.style.setProperty("display", "none", "important");
    }
  }

  async function destroyLive2d(agentId) {
    const widget = state.widgets[agentId];
    const canvas = state.canvases[agentId];
    state.widgets[agentId] = null;
    state.canvases[agentId] = null;
    const dock = $(`.companion-dock[data-agent="${agentId}"]`);
    if (dock) dock.classList.remove("is-live", "is-loading");
    if (widget && typeof widget.destroy === "function") {
      try { await widget.destroy(); } catch (_) { /* canvas removed below */ }
    }
    if (canvas && canvas.isConnected) canvas.remove();
  }

  async function initLive2d(agentId) {
    if (reducedMotion()) return;
    if (state.widgets[agentId] || state.starting[agentId]) return;
    const profile = state.catalog[agentId];
    const costumeId = costumeFor(agentId);
    const costume = profile && profile.costumes && profile.costumes[costumeId];
    if (!costume || !costume.path) return;
    const stage = document.getElementById(`companionStage-${agentId}`);
    const dock = $(`.companion-dock[data-agent="${agentId}"]`);
    if (!stage) return;
    state.starting[agentId] = true;
    if (dock) dock.classList.add("is-loading");
    try {
      await loadScript(WIDGET_SRC);
      if (!window.L2D_WIDGET || typeof window.L2D_WIDGET.createWidget !== "function") return;
      if (state.widgets[agentId]) return;
      const previous = new Set(document.querySelectorAll("canvas"));
      const bounds = stage.getBoundingClientRect();
      const size = Math.max(400, Math.min(720, Math.round(Math.max(bounds.width || 0, bounds.height || 0, window.innerHeight * 0.52))));
      const widget = window.L2D_WIDGET.createWidget({
        model: {
          path: costume.path,
          scale: Number(profile.scale || 1.05),
          offset: Array.isArray(profile.offset) ? profile.offset : [0, 0.18],
          volume: 0,
          logLevel: "error",
          tips: false,
        },
        position: agentId === "tomori" ? "bottom-right" : "bottom-left",
        size,
        primaryColor: agentId === "tomori" ? "rgba(244, 164, 200, 0.9)" : "rgba(232, 196, 120, 0.9)",
        transitionDuration: 280,
        transitionType: "fade",
        menus: { items: [] },
        statusBar: { style: { display: "none" } },
      });
      const canvas = Array.from(document.querySelectorAll("canvas")).find(
        (item) => !previous.has(item) && !stage.contains(item),
      );
      if (canvas) {
        hideWidgetShell(canvas, stage);
        state.canvases[agentId] = canvas;
      }
      state.widgets[agentId] = widget;
      const markLive = () => {
        if (dock) {
          dock.classList.add("is-live");
          dock.classList.remove("is-loading");
        }
        if (widget.l2d && typeof widget.l2d.playMotion === "function") {
          try { widget.l2d.playMotion("ready"); } catch (_) { /* optional motion pack */ }
        }
      };
      if (widget.l2d && typeof widget.l2d.on === "function") widget.l2d.on("loaded", markLive);
      else markLive();
    } catch (_) {
      await destroyLive2d(agentId);
    } finally {
      state.starting[agentId] = false;
    }
  }

  async function collapse(agentId, options) {
    const dock = $(`.companion-dock[data-agent="${agentId}"]`);
    if (!dock) return;
    dock.classList.remove("is-open");
    const peek = $(".companion-peek", dock);
    if (peek) peek.setAttribute("aria-pressed", "false");
    if (state.openId === agentId) state.openId = "";
    if (state.pinned === agentId) state.pinned = "";
    if (options && options.destroy) await destroyLive2d(agentId);
  }

  async function expand(agentId) {
    if (state.openId && state.openId !== agentId) {
      const previous = state.openId;
      await collapse(previous, { destroy: true });
    }
    const dock = $(`.companion-dock[data-agent="${agentId}"]`);
    if (!dock) return;
    dock.classList.add("is-open");
    state.openId = agentId;
    const label = $(".companion-costume", dock);
    if (label) label.textContent = costumeLabel(agentId);
    if (!state.widgets[agentId]) {
      await new Promise((resolve) => window.requestAnimationFrame(() => window.requestAnimationFrame(resolve)));
      await initLive2d(agentId);
    }
  }

  function pin(agentId) {
    state.pinned = agentId;
    const peek = $(`.companion-dock[data-agent="${agentId}"] .companion-peek`);
    if (peek) peek.setAttribute("aria-pressed", "true");
  }

  function scheduleCollapse(agentId) {
    window.clearTimeout(state.hideTimer);
    state.hideTimer = window.setTimeout(() => {
      if (state.pinned === agentId || state.busy[agentId] || dockHasFocus(agentId)) return;
      collapse(agentId);
    }, 900);
  }

  async function sendTask(agentId, message) {
    const text = String(message || "").trim();
    if (!text || state.busy[agentId] || !api()) return;
    state.busy[agentId] = true;
    pin(agentId);
    setMood(agentId, `${AGENTS[agentId].name}正在接任务…`);
    try {
      const historyPayload = await api().get("/api/butler/history?limit=8", { timeoutMs: 15000 });
      const history = ((historyPayload && historyPayload.messages) || []).slice(-8).map((item) => ({
        role: item.role,
        content: item.content,
      }));
      const data = await api().post(
        "/api/butler/chat",
        { message: text, history, agent: agentId },
        { timeoutMs: 150000 },
      );
      setLog(agentId, data.reply || "已经记下了。完整过程在对话工作台。");
      setMood(agentId, data.workflow_id ? "任务已收下，完整进度在对话工作台" : "说完啦");
      const input = $(`.companion-dock[data-agent="${agentId}"] textarea`);
      if (input) input.value = "";
    } catch (error) {
      setLog(agentId, String(error.message || error));
      setMood(agentId, "这次没接住，完整对话里可以接着查");
    } finally {
      state.busy[agentId] = false;
    }
  }

  function renderDock(spec) {
    const dock = document.createElement("aside");
    dock.className = `companion-dock is-${spec.side}`;
    dock.dataset.agent = spec.id;
    dock.setAttribute("aria-label", `${spec.name}快捷对话`);
    dock.innerHTML = `
      <button type="button" class="companion-peek" aria-pressed="false" aria-label="打开${spec.name}" title="打开${spec.name}">
        <span class="companion-peek-tab" aria-hidden="true"></span>
      </button>
      <div class="companion-panel">
        <div class="companion-frame">
          <div class="companion-stage" id="companionStage-${spec.id}">
            <div class="companion-stage-grid" aria-hidden="true"></div>
            <div class="companion-stage-aura" aria-hidden="true"></div>
            <div class="companion-fallback">${spec.mark}</div>
          </div>
          <div class="companion-kicker">
            <span>${spec.side === "left" ? "左侧 · 客服" : "右侧 · 生成"}</span>
            <button type="button" data-close>收起</button>
          </div>
          <div class="companion-hud">
            <div class="companion-bubble">
              <p class="companion-mood">${spec.greeting}</p>
              <div class="companion-log"></div>
            </div>
            <div class="companion-nameplate">
              <em>${spec.duty}</em>
              <strong>${spec.name}</strong>
              <span class="companion-costume">情景服饰</span>
            </div>
            <div class="companion-chips"></div>
            <form class="companion-form">
              <textarea maxlength="4000" rows="2" placeholder="${spec.placeholder}"></textarea>
              <button type="submit" class="companion-send">交代</button>
            </form>
            <a class="companion-full" href="/butler?agent=${encodeURIComponent(spec.id)}">完整对话 →</a>
          </div>
        </div>
      </div>`;
    const chips = $(".companion-chips", dock);
    spec.chips.forEach(([label, command]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", () => {
        const input = $("textarea", dock);
        if (input) {
          input.value = command;
          input.focus();
        }
        pin(spec.id);
      });
      chips.appendChild(button);
    });
    const peek = $(".companion-peek", dock);
    peek.addEventListener("click", () => {
      if (state.pinned === spec.id) {
        collapse(spec.id, { destroy: true });
        return;
      }
      pin(spec.id);
      expand(spec.id);
    });
    dock.addEventListener("pointerenter", () => {
      window.clearTimeout(state.hideTimer);
      expand(spec.id);
    });
    dock.addEventListener("pointerleave", (event) => {
      if (event.relatedTarget && dock.contains(event.relatedTarget)) return;
      scheduleCollapse(spec.id);
    });
    const input = $("textarea", dock);
    input.addEventListener("focus", () => pin(spec.id));
    $(".companion-form", dock).addEventListener("submit", (event) => {
      event.preventDefault();
      sendTask(spec.id, input.value);
    });
    $("[data-close]", dock).addEventListener("click", () => {
      collapse(spec.id, { destroy: true });
    });
    return dock;
  }

  async function mount() {
    if (onButlerPage() || document.getElementById("companionDocks")) return;
    if (window.matchMedia && (
      window.matchMedia("(max-width: 1100px)").matches ||
      window.matchMedia("(hover: none)").matches
    )) return;
    ensureCss();
    const host = document.createElement("div");
    host.id = "companionDocks";
    host.className = "companion-docks";
    host.appendChild(renderDock(AGENTS.sakiko));
    host.appendChild(renderDock(AGENTS.tomori));
    document.body.appendChild(host);
    if (api() && typeof api().get === "function") {
      try {
        const data = await api().get(CATALOG_URL, { timeoutMs: 15000 });
        const payload = typeof data === "string" ? JSON.parse(data) : data;
        if (payload && typeof payload === "object") {
          state.catalog = Object.assign({}, FALLBACK_CATALOG, payload);
        }
      } catch (_) { /* keep letter fallback */ }
    }
    loadScript(TOUCH_SRC).then(() => {
      bindTouch("sakiko");
      bindTouch("tomori");
    }).catch(() => {});
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && state.openId) collapse(state.openId, { destroy: true });
    });
    window.addEventListener("pagehide", () => {
      ["sakiko", "tomori"].forEach((id) => { destroyLive2d(id); });
    }, { once: true });
  }

  window.CompanionDock = {
    open(agentId) {
      const id = agentId === "tomori" ? "tomori" : "sakiko";
      pin(id);
      return expand(id);
    },
    close() {
      if (state.openId) return collapse(state.openId, { destroy: true });
      return Promise.resolve();
    },
  };

  function start() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", () => { mount(); });
      return;
    }
    mount();
  }
  start();
})();

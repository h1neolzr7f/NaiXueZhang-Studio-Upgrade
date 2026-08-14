(function () {
  const $ = (id) => document.getElementById(id);
  const ASSISTANT_NAME_KEY = "aitag.assistant.name.v1";
  const AGENT_KEY = "aitag.assistant.agent.v1";
  const STUDIO_DRAFT_KEY = "aitag.studio.draft.v1";
  const HISTORY_API = "/api/butler/history";
  const COMPARISON_KEY = window.ComparisonWorkspace?.STORAGE_KEY || "aitag.butler.comparison.v1";
  const FALLBACK_MODEL = "/assets/vendor/live2d-models/hiyori/Hiyori.model3.json";
  const CATALOG_URL = "/assets/vendor/live2d-models/companions.json";
  const TOMORI_HINTS = /生成|出图|换角|换画风|导演|投稿|pixiv|remix|studio|选材|线稿|去背景|上色|草图/i;
  const SAKIKO_HINTS = /采集|爬虫|后处理|设置|排障|日志|体检|缺图|配置|故障|诊断|修复|维护|怎么用|入门|小白/i;
  const MOTION_BY_SITUATION = {
    ready: "ready",
    idle: "idle",
    thinking: "thinking",
    working: "working",
    happy: "happy",
    sorry: "sorry",
    surprised: "surprised",
    generate: "generate",
    publish: "publish",
    remix: "happy",
  };
  const POLL_DELAYS = { realtime: 900, balanced: 2500, eco: 8000 };
  const state = {
    history: [],
    historyBefore: null,
    busy: false,
    status: null,
    tasks: [],
    selectedTaskId: "",
    assistantName: "客服小祥",
    agent: "sakiko",
    catalog: {},
    costumeOrder: [],
    costumeId: "",
    costumeIndex: 0,
    situation: "ready",
    lastPlayedSituation: "",
    companionSync: Promise.resolve(),
    live2dEnabled: true,
    live2dModel: FALLBACK_MODEL,
    pollMode: "balanced",
    pollTimer: null,
    polling: false,
    pollBurstUntil: 0,
    taskStream: null,
    taskStreamConnected: false,
    taskStreamSelectedId: "",
    lastTaskStreamRevision: -1,
    widget: null,
    live2dCanvas: null,
    pendingImage: null,
    comparisonWorkspace: null,
  };
  const ACTIVE_TASK_STATUSES = new Set(["planned", "accepted", "running"]);
  const TASK_STATUS_LABELS = {
    planned: "规划中",
    awaiting_confirmation: "待确认",
    accepted: "已接受",
    running: "运行中",
    paused: "已暂停",
    succeeded: "已完成",
    partially_succeeded: "部分成功",
    failed: "失败",
    cancelled: "已取消",
    unknown: "待核对",
  };

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  function redactSensitiveText(value) {
    let text = String(value || "");
    const patterns = [
      /\bBearer\s+[A-Za-z0-9._~+/=-]{12,}/gi,
      /\bsk-[A-Za-z0-9_-]{12,}\b/g,
      /\bpst-[A-Za-z0-9_-]{20,}\b/gi,
      /\b(?=[A-Za-z0-9_-]{32,}\b)(?=[A-Za-z0-9_-]*[A-Z])(?=[A-Za-z0-9_-]*[a-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]{32,}\b/g,
      /\b(api[_ -]?key|access[_ -]?token|refresh[_ -]?token|token|password|passwd|username|account|cookie|authorization)\b\s*[:：=]\s*[^\s,，;；。]{3,}/gi,
      /(访问令牌|刷新令牌|账号|帐号|用户名|密码|口令|令牌|密钥)\s*(?:[:：=]|是|为)?\s*[A-Za-z0-9@._+\-]{5,}/g,
    ];
    patterns.forEach((pattern) => {
      text = text.replace(pattern, (...args) => {
        const label = typeof args[1] === "string" ? args[1] : "secret";
        return `${label} [REDACTED]`;
      });
    });
    return text;
  }

  function rememberAssistantName() {
    try {
      localStorage.setItem(ASSISTANT_NAME_KEY, state.assistantName);
      localStorage.setItem(AGENT_KEY, state.agent);
    } catch (_) { /* private browsing can disable local storage */ }
  }

  function currentProfile() {
    return state.catalog[state.agent] || null;
  }

  function agentMeta(agentId) {
    const id = agentId === "tomori" ? "tomori" : "sakiko";
    const profile = state.catalog[id] || {};
    if (id === "tomori") {
      return {
        id: "tomori",
        name: profile.name || "助手凑企鹅",
        short: "凑企鹅",
        duty: "选材与生成",
        fallback: "灯",
      };
    }
    return {
      id: "sakiko",
      name: profile.name || "客服小祥",
      short: "小祥",
      duty: "处理和维护",
      fallback: "祥",
    };
  }

  function applyAssistantName() {
    const meta = agentMeta(state.agent);
    state.assistantName = meta.name;
    document.querySelectorAll("[data-assistant-name]").forEach((element) => {
      element.textContent = state.assistantName;
    });
    document.title = `${state.assistantName} · 图库智能管家`;
    const portrait = $("assistantPortrait");
    if (portrait) portrait.setAttribute("aria-label", `${state.assistantName}的 Live2D 伙伴形象`);
    const fallbackMark = document.querySelector("#live2dFallback span");
    if (fallbackMark) fallbackMark.textContent = meta.fallback;
    const fallbackHint = document.querySelector("#live2dFallback small");
    if (fallbackHint) fallbackHint.textContent = meta.duty;
    renderAgentSwitch();
    updateCostumeLabel();
  }

  function renderAgentSwitch() {
    const host = $("agentSwitch");
    if (!host) return;
    host.replaceChildren();
    ["sakiko", "tomori"].forEach((id) => {
      const meta = agentMeta(id);
      const button = node("button", state.agent === id ? "is-active" : "");
      button.type = "button";
      button.dataset.agent = id;
      button.appendChild(node("strong", "", meta.name));
      button.appendChild(node("span", "", meta.duty));
      button.addEventListener("click", () => setAgent(id, { reason: "ready" }));
      host.appendChild(button);
    });
  }

  function updateCostumeLabel() {
    const label = $("costumeLabel");
    if (!label) return;
    const profile = currentProfile();
    const costume = profile && profile.costumes && profile.costumes[state.costumeId];
    label.textContent = costume && costume.label ? costume.label : "情景服饰";
  }

  function isSummerSeason() {
    const month = new Date().getMonth() + 1;
    return month >= 5 && month <= 9;
  }

  function pickCostumeId(situation) {
    const profile = currentProfile();
    if (!profile) return "";
    const key = situation || "ready";
    let spec = (profile.situations && profile.situations[key]) || profile.default_costume;
    if (Array.isArray(spec) && spec.length) {
      const stamp = `${key}:${new Date().toISOString().slice(0, 10)}`;
      let hash = 0;
      for (let i = 0; i < stamp.length; i += 1) hash = (hash * 33 + stamp.charCodeAt(i)) % 2147483647;
      spec = spec[Math.abs(hash) % spec.length];
    }
    if (spec === "school" && profile.school) {
      spec = isSummerSeason() ? profile.school.summer : profile.school.winter;
    }
    if (profile.costumes && profile.costumes[spec]) return spec;
    return profile.default_costume || Object.keys(profile.costumes || {})[0] || "";
  }

  function inferAgent(message, intent) {
    if (intent === "gallery_audit") return "sakiko";
    const text = String(message || "");
    const wantsTomori = TOMORI_HINTS.test(text);
    const wantsSakiko = SAKIKO_HINTS.test(text);
    if (wantsTomori && !wantsSakiko) return "tomori";
    if (wantsSakiko && !wantsTomori) return "sakiko";
    return state.agent;
  }

  function situationFromTask(task) {
    if (!task) return state.situation || "ready";
    if (task.terminal) return task.status === "succeeded" ? "happy" : "sorry";
    const blob = `${task.title || ""} ${task.kind || ""} ${task.message || ""} ${task.phase || ""}`;
    if (/投稿|pixiv|发布/i.test(blob)) return "publish";
    if (/换角|换画风|remix/i.test(blob)) return "remix";
    if (/生成|出图|导演|线稿|去背景/i.test(blob)) return "generate";
    if (/采集|爬虫|后处理|体检|检修|日志/i.test(blob)) return "working";
    if (task.status === "awaiting_confirmation") return "ready";
    return "thinking";
  }

  function setMood(kind, message) {
    const host = $("assistantPortrait");
    const mood = $("assistantMood");
    const situation = kind || "ready";
    state.situation = situation;
    if (host) host.dataset.mood = situation;
    if (mood) mood.textContent = message || `${state.assistantName}在这里陪你`;
    queueCompanionSync(situation);
  }

  function queueCompanionSync(situation) {
    state.companionSync = state.companionSync
      .then(() => syncCompanion(situation))
      .catch(() => {});
  }

  async function syncCompanion(situation) {
    if (!state.widget) return;
    const portrait = $("assistantPortrait");
    if (!portrait || !portrait.classList.contains("live2d-ready")) return;
    const costumeId = pickCostumeId(situation);
    const changed = costumeId !== state.costumeId || situation !== state.lastPlayedSituation;
    if (costumeId && costumeId !== state.costumeId) {
      await switchCostume(costumeId);
    }
    if (changed) {
      state.lastPlayedSituation = situation;
      playCompanionMotion(situation);
    }
  }

  function playCompanionMotion(situation) {
    const l2d = state.widget && state.widget.l2d;
    if (!l2d || typeof l2d.playMotion !== "function") return;
    const group = MOTION_BY_SITUATION[situation] || "idle";
    try { l2d.playMotion(group); } catch (_) { /* motion pack may omit a group */ }
    if (typeof l2d.setExpression === "function") {
      const expr = {
        happy: "smile01",
        thinking: "thinking01",
        sorry: "sad01",
        surprised: "surprised01",
        working: "serious01",
        generate: "kime01",
        publish: "smile02",
      }[situation];
      if (expr) {
        try { l2d.setExpression(expr); } catch (_) { /* expression names vary by pack */ }
      }
    }
  }

  function waitForLive2dLoaded(widget) {
    return new Promise((resolve) => {
      const l2d = widget && widget.l2d;
      let settled = false;
      const done = () => {
        if (settled) return;
        settled = true;
        resolve();
      };
      if (l2d && typeof l2d.on === "function") l2d.on("loaded", done);
      window.setTimeout(done, 2200);
    });
  }

  function costumeQueue(profile, startId) {
    const ids = Object.keys((profile && profile.costumes) || {});
    const first = ids.includes(startId) ? startId : ((profile && profile.default_costume) || ids[0] || "");
    return first ? [first, ...ids.filter((id) => id !== first)] : ids;
  }

  async function switchCostume(costumeId) {
    const index = state.costumeOrder.indexOf(costumeId);
    if (!state.widget || typeof state.widget.switchModel !== "function" || index < 0) return;
    if (index === state.costumeIndex && state.costumeId === costumeId) {
      playCompanionMotion(state.situation);
      return;
    }
    await state.widget.switchModel(index);
    await waitForLive2dLoaded(state.widget);
    state.costumeIndex = index;
    state.costumeId = costumeId;
    state.lastPlayedSituation = "";
    updateCostumeLabel();
  }

  async function setAgent(agentId, options) {
    const next = agentId === "tomori" ? "tomori" : "sakiko";
    const reason = (options && options.reason) || "ready";
    if (next === state.agent && state.widget) {
      setMood(reason, `${agentMeta(next).name}在这里陪你`);
      return;
    }
    state.agent = next;
    rememberAssistantName();
    applyAssistantName();
    if (state.status) renderSkills(state.status.skills || []);
    if (state.live2dEnabled) await initLive2d();
    setMood(reason, `${state.assistantName}接过这一摊啦`);
  }

  function mountLive2dCanvas(previousCanvases) {
    const stage = $("live2dStage");
    if (!stage) throw new Error("Live2D 舞台不存在");
    const canvas = Array.from(document.querySelectorAll("canvas")).find(
      (item) => !previousCanvases.has(item) && !stage.contains(item),
    );
    if (!canvas) throw new Error("Live2D 画布没有创建");
    const shell = canvas.parentElement;
    ["position", "left", "top", "right", "bottom", "width", "height", "transform"].forEach((key) => {
      canvas.style.removeProperty(key);
    });
    stage.appendChild(canvas);
    if (shell && shell !== stage && shell !== document.body && !shell.closest(".butler-live2d-stage")) {
      shell.style.setProperty("display", "none", "important");
    }
    state.live2dCanvas = canvas;
    return canvas;
  }

  async function destroyLive2d() {
    const widget = state.widget;
    const canvas = state.live2dCanvas;
    state.widget = null;
    state.live2dCanvas = null;
    state.costumeOrder = [];
    state.costumeIndex = 0;
    if (widget && typeof widget.destroy === "function") {
      try { await widget.destroy(); } catch (_) { /* canvas is removed separately */ }
    }
    if (canvas && canvas.isConnected) canvas.remove();
    $("assistantPortrait").classList.remove("live2d-ready", "live2d-cubism2");
  }

  async function loadCompanionCatalog() {
    try {
      const data = await window.ApiClient.get(CATALOG_URL, { timeoutMs: 15000 });
      const payload = typeof data === "string" ? JSON.parse(data) : data;
      if (payload && typeof payload === "object") state.catalog = payload;
    } catch (_) {
      state.catalog = {};
    }
  }

  async function loadPreferences() {
    try {
      const data = await window.ApiClient.get("/api/settings/prefs", { timeoutMs: 15000 });
      const prefs = data.prefs || data || {};
      state.live2dEnabled = prefs.assistant_live2d_enabled !== false;
      state.live2dModel = String(prefs.assistant_live2d_model || FALLBACK_MODEL);
      state.pollMode = Object.prototype.hasOwnProperty.call(POLL_DELAYS, prefs.assistant_poll_mode)
        ? prefs.assistant_poll_mode
        : "balanced";
    } catch (_) { /* use defaults */ }
    try {
      const stored = String(localStorage.getItem(AGENT_KEY) || "").trim();
      if (stored === "tomori" || stored === "sakiko") state.agent = stored;
    } catch (_) { /* private browsing */ }
    rememberAssistantName();
    applyAssistantName();
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

  function companionModels(profile, startId) {
    const order = costumeQueue(profile, startId);
    const scale = Number(profile.scale || 1.05);
    const offset = Array.isArray(profile.offset) ? profile.offset : [0, 0.18];
    return order.map((id) => {
      const costume = profile.costumes[id];
      return {
        path: costume.path,
        scale,
        offset,
        volume: 0,
        logLevel: "error",
        tips: false,
      };
    });
  }

  async function initLive2d() {
    if (!state.live2dEnabled || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setMood("ready", `${state.assistantName}已就绪（动态形象已关闭）`);
      return;
    }
    try {
      await loadScript("/assets/vendor/l2d-widget/index.min.js?v=87d455d82f");
      if (!window.L2D_WIDGET || typeof window.L2D_WIDGET.createWidget !== "function") throw new Error("Live2D 接口不可用");
      if (state.widget) await destroyLive2d();
      const previousCanvases = new Set(document.querySelectorAll("canvas"));
      const stageSize = Math.max(360, Math.min(640, Math.round($("live2dStage").clientWidth || 360)));
      const profile = currentProfile();
      if (!state.situation || state.situation === "ready") state.situation = "happy";
      const startId = pickCostumeId(state.situation || "happy");
      const models = profile && profile.costumes
        ? companionModels(profile, startId)
        : [{
          path: state.live2dModel || FALLBACK_MODEL,
          scale: window.innerWidth < 720 ? 1.72 : 2.05,
          offset: [0, -0.55],
          volume: 0,
          logLevel: "error",
          tips: false,
        }];
      state.costumeOrder = profile && profile.costumes ? costumeQueue(profile, startId) : [];
      state.costumeId = state.costumeOrder[0] || startId || "";
      state.costumeIndex = 0;
      $("assistantPortrait").classList.toggle("live2d-cubism2", Boolean(profile && profile.costumes));
      state.widget = window.L2D_WIDGET.createWidget({
        model: models.length === 1 ? models[0] : models,
        position: "bottom-right",
        size: stageSize,
        primaryColor: "rgba(156, 113, 255, 0.92)",
        transitionDuration: 650,
        transitionType: "fade",
        menus: { items: [] },
        statusBar: { style: { display: "none" } },
      });
      mountLive2dCanvas(previousCanvases);
      updateCostumeLabel();
      const markReady = () => {
        $("assistantPortrait").classList.add("live2d-ready");
        playCompanionMotion(state.situation || "ready");
        setMood("happy", `${state.assistantName}已就绪，很高兴见到你`);
      };
      if (state.widget.l2d && typeof state.widget.l2d.on === "function") {
        state.widget.l2d.on("loaded", markReady);
      } else {
        markReady();
      }
      $("toggleLive2d").hidden = false;
      $("toggleLive2d").textContent = "隐藏形象";
    } catch (error) {
      await destroyLive2d();
      setMood("ready", `${state.assistantName}已就绪 · 动态形象暂未加载`);
    }
  }

  function fileToDataUrl(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.addEventListener("load", () => resolve(String(reader.result || "")), { once: true });
      reader.addEventListener("error", () => reject(new Error("图片读取失败")), { once: true });
      reader.readAsDataURL(blob);
    });
  }

  function loadImageBitmap(file) {
    if (typeof window.createImageBitmap === "function") return window.createImageBitmap(file);
    return new Promise((resolve, reject) => {
      const image = new Image();
      const url = URL.createObjectURL(file);
      image.addEventListener("load", () => {
        URL.revokeObjectURL(url);
        resolve(image);
      }, { once: true });
      image.addEventListener("error", () => {
        URL.revokeObjectURL(url);
        reject(new Error("图片无法解码"));
      }, { once: true });
      image.src = url;
    });
  }

  function canvasBlob(canvas, quality) {
    return new Promise((resolve, reject) => {
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error("图片压缩失败"))),
        "image/jpeg",
        quality,
      );
    });
  }

  async function compressImage(file) {
    const supported = new Set(["image/png", "image/jpeg", "image/webp"]);
    if (!file || !supported.has(file.type)) throw new Error("请选择 PNG、JPEG 或 WebP 图片");
    if (file.size > 20 * 1024 * 1024) throw new Error("原图超过 20MB，请先缩小后再试");
    const bitmap = await loadImageBitmap(file);
    const sourceWidth = Number(bitmap.width || bitmap.naturalWidth || 0);
    const sourceHeight = Number(bitmap.height || bitmap.naturalHeight || 0);
    if (!sourceWidth || !sourceHeight) throw new Error("图片尺寸读取失败");
    const maxSide = 1536;
    const ratio = Math.min(1, maxSide / Math.max(sourceWidth, sourceHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(sourceWidth * ratio));
    canvas.height = Math.max(1, Math.round(sourceHeight * ratio));
    const context = canvas.getContext("2d", { alpha: false });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    if (typeof bitmap.close === "function") bitmap.close();
    let blob = await canvasBlob(canvas, 0.84);
    if (blob.size > 6 * 1024 * 1024) blob = await canvasBlob(canvas, 0.68);
    if (blob.size > 6 * 1024 * 1024) throw new Error("压缩后仍超过 6MB，请换一张更小的图片");
    return {
      name: String(file.name || "图片").slice(0, 120),
      mime: "image/jpeg",
      size_bytes: blob.size,
      data_url: await fileToDataUrl(blob),
    };
  }

  function renderPendingImage(image) {
    state.pendingImage = image || null;
    const preview = $("imagePreview");
    preview.hidden = !image;
    if (image) {
      $("imagePreviewThumb").src = image.data_url;
      $("imagePreviewName").textContent = image.name || "已选择图片";
    } else {
      $("imagePreviewThumb").removeAttribute("src");
      $("imagePreviewName").textContent = "已选择图片";
      $("imageInput").value = "";
    }
  }

  function scrollMessages() {
    const host = $("butlerMessages");
    host.scrollTop = host.scrollHeight;
  }

  function messageElement(role, content, options) {
    const article = node("article", `butler-message ${role}`);
    article.appendChild(node("div", "butler-avatar", role === "user" ? "我" : agentMeta(state.agent).fallback));
    const bubble = node("div", "butler-bubble");
    if (options && options.preview) {
      const image = node("img", "butler-message-image");
      image.src = options.preview;
      image.alt = options.imageName || "本次对话附图";
      bubble.appendChild(image);
    }
    bubble.appendChild(node("p", "", redactSensitiveText(content)));
    article.appendChild(bubble);
    return article;
  }

  function appendMessage(role, content, options) {
    const safeContent = redactSensitiveText(content);
    const article = messageElement(role, safeContent, options);
    $("butlerMessages").appendChild(article);
    if (!options || options.record !== false) {
      state.history.push({ role, content: safeContent });
      state.history = state.history.slice(-200);
    }
    scrollMessages();
    return article;
  }

  async function loadHistory(beforeId) {
    const query = beforeId ? `?limit=60&before_id=${encodeURIComponent(beforeId)}` : "?limit=60";
    const data = await window.ApiClient.get(`${HISTORY_API}${query}`, { timeoutMs: 30000 });
    const messages = Array.isArray(data.messages) ? data.messages : [];
    const host = $("butlerMessages");
    if (!beforeId) {
      if (messages.length) host.replaceChildren();
      state.history = messages.map(({ role, content }) => ({ role, content }));
      messages.forEach((item) => host.appendChild(messageElement(item.role, item.content)));
      if (messages.length) scrollMessages();
    } else if (messages.length) {
      const oldHeight = host.scrollHeight;
      [...messages].reverse().forEach((item) => host.insertBefore(messageElement(item.role, item.content), host.firstChild));
      state.history = messages.map(({ role, content }) => ({ role, content })).concat(state.history).slice(-200);
      host.scrollTop += host.scrollHeight - oldHeight;
    }
    state.historyBefore = messages.length ? messages[0].id : state.historyBefore;
    $("loadOlderHistory").hidden = !data.has_more;
    return data;
  }

  function resultShell(title, meta, extraClass, target) {
    const card = node("section", `butler-result${extraClass ? ` ${extraClass}` : ""}`);
    const head = node("div", "butler-result-head");
    head.appendChild(node("strong", "", title));
    if (meta) head.appendChild(node("span", "", meta));
    card.appendChild(head);
    const host = target || $("butlerMessages");
    host.appendChild(card);
    if (!target) scrollMessages();
    return card;
  }

  function workCard(item) {
    const link = node("a", "butler-work-card");
    link.href = item.url || `/i/${item.work_id}`;
    if (item.thumb) {
      const image = node("img");
      image.src = item.thumb;
      image.alt = item.title || `作品 ${item.work_id}`;
      image.loading = "lazy";
      link.appendChild(image);
    }
    link.appendChild(node("strong", "", item.title || `作品 ${item.work_id}`));
    const metrics = [];
    if (item.work_id) metrics.push(`#${item.work_id}`);
    if (item.image_count) metrics.push(`${item.image_count} 张`);
    if (item.bookmarks) metrics.push(`收藏 ${item.bookmarks}`);
    link.appendChild(node("span", "", metrics.join(" · ")));
    return link;
  }

  function comparisonCandidates() {
    return state.comparisonWorkspace ? state.comparisonWorkspace.snapshot() : [];
  }

  function renderComparisonWorkspace() {
    const host = $("butlerCompareGrid");
    if (!host) return;
    const items = comparisonCandidates();
    $("butlerCompareCount").textContent = `${items.length}/4 · ${items.length < 2 ? "至少加入 2 张才能比较" : "候选身份已固定"}`;
    $("runGalleryCompare").disabled = state.busy || items.length < 2;
    host.replaceChildren();
    if (!items.length) {
      host.appendChild(node("div", "butler-compare-empty", "候选会固定保存在本机；加入、移除和查看都不会消耗 Token。"));
      return;
    }
    items.forEach((item, index) => {
      const card = node("article", "butler-compare-candidate");
      if (item.thumb) {
        const image = node("img");
        image.src = item.thumb;
        image.alt = item.title || `候选 ${index + 1}`;
        image.loading = "lazy";
        card.appendChild(image);
      }
      const meta = node("div");
      meta.appendChild(node("strong", "", `${index === 0 ? "左" : index === 1 ? "右" : `候选 ${index + 1}`} · ${item.title || `作品 ${item.work_id}`}`));
      meta.appendChild(node("span", "", `${item.gallery_id} · #${item.work_id} · 第 ${Number(item.page_index || 0) + 1} 张`));
      card.appendChild(meta);
      const remove = node("button", "butler-compare-remove", "移除");
      remove.type = "button";
      remove.addEventListener("click", () => {
        state.comparisonWorkspace.remove(item.candidate_id);
        renderComparisonWorkspace();
      });
      card.appendChild(remove);
      host.appendChild(card);
    });
  }

  function addComparisonCandidate(item) {
    try {
      state.comparisonWorkspace.add({
        gallery_id: item.gallery_id || "site",
        work_id: item.work_id,
        page_index: item.page_index || 0,
        title: item.title,
        thumb: item.thumb,
        url: item.url,
      });
      renderComparisonWorkspace();
      setMood("happy", "候选固定好啦；加入和查看不会消耗 Token，明确比较时才会识图");
    } catch (error) {
      setMood("sorry", String(error.message || error));
    }
  }

  function comparisonPick(item) {
    const wrap = node("div", "butler-work-pick");
    wrap.appendChild(workCard(item));
    const add = node("button", "butler-compare-add", "加入固定对比");
    add.type = "button";
    add.addEventListener("click", () => addComparisonCandidate(item));
    wrap.appendChild(add);
    return wrap;
  }

  function renderGalleryComparison(result, target) {
    const stats = result.stats || {};
    const card = resultShell(
      "固定候选视觉比较",
      `${stats.vision_checked || 0} 张低清图 · ${stats.cache_hit ? "复用近期结果" : `${stats.model_calls || 0} 次模型调用`}`,
      target ? "butler-audit-persisted" : "",
      target,
    );
    card.appendChild(node("p", "butler-audit-summary", result.summary || "比较完成。"));
    if (stats.vision_refused) {
      card.appendChild(node("div", "butler-error", "上游拒绝了这批图片；候选没有被过滤，也没有自动重试。"));
    }
    const ranking = node("div", "butler-comparison-ranking");
    (result.items || []).slice().sort((left, right) => Number(left.rank || 99) - Number(right.rank || 99)).forEach((item) => {
      const row = node("div", "butler-comparison-row");
      row.appendChild(node("strong", "", `${item.rank ? `第 ${item.rank} 名 · ` : ""}${item.title || `作品 ${item.work_id}`}`));
      if (item.strengths) row.appendChild(node("span", "", `优点：${item.strengths}`));
      if (item.weaknesses) row.appendChild(node("span", "", `不足：${item.weaknesses}`));
      if (item.reason) row.appendChild(node("span", "", `理由：${item.reason}`));
      ranking.appendChild(row);
    });
    if (ranking.childNodes.length) card.appendChild(ranking);
    return card;
  }

  function renderGalleryAudit(result, target) {
      const stats = result.stats || {};
      const items = result.items || [];
      const card = resultShell(
        "图库体检结果",
        `${stats.scanned || 0} 个作品`,
        target ? "butler-audit-persisted" : "",
        target,
      );
      card.appendChild(node("p", "butler-audit-summary", result.summary || "检查完成。"));
      const meta = node("div", "butler-audit-meta");
      meta.appendChild(node("span", "", `视觉检查 ${stats.vision_checked || 0} 张`));
      meta.appendChild(node("span", "", `发现 ${stats.issues || 0} 项`));
      if (stats.high) meta.appendChild(node("span", "", `高优先级 ${stats.high} 项`));
      if (stats.cache_hit) meta.appendChild(node("span", "", "已复用近期结果"));
      card.appendChild(meta);
      if (!items.length) {
        card.appendChild(node("div", "", "这批没有发现需要单独标记的问题。"));
        return card;
      }
      items.forEach((item) => {
        const row = node("div", "butler-audit-work");
        row.appendChild(comparisonPick(item));
        const list = node("div", "butler-audit-findings");
        (item.findings || []).forEach((finding) => {
          const severity = String(finding.severity || "medium");
          const label = ({ high: "高", medium: "中", low: "低" })[severity] || "中";
          const box = node("div", `butler-audit-finding ${severity}`);
          box.appendChild(node("strong", "", `${label}优先级 · ${finding.issue || "待复核"}`));
          if (finding.evidence) box.appendChild(node("span", "", `依据：${finding.evidence}`));
          if (finding.suggestion) box.appendChild(node("span", "", `建议：${finding.suggestion}`));
          list.appendChild(box);
        });
        row.appendChild(list);
        card.appendChild(row);
      });
      return card;
  }

  function renderToolResult(result, target) {
    const tool = String(result.tool || "result");
    if (tool === "compare_gallery_candidates") {
      renderGalleryComparison(result, target);
      return;
    }
    if (tool === "audit_gallery") {
      renderGalleryAudit(result, target);
      return;
    }
    if (tool === "search_gallery") {
      const items = result.items || [];
      const card = resultShell("图库搜索结果", `${items.length} 个匹配`, "", target);
      if (!items.length) {
        card.appendChild(node("div", "butler-error", "没有找到符合条件的作品。"));
      } else {
        const grid = node("div", "butler-work-grid");
        items.forEach((item) => grid.appendChild(comparisonPick(item)));
        card.appendChild(grid);
      }
      return;
    }
    if (tool === "search_character_references") {
      const items = result.items || [];
      const card = resultShell("NAI 角色资料", `${Number(result.total || items.length)} 个匹配`, "", target);
      if (!items.length) {
        card.appendChild(node("div", "butler-error", "本地角色资料库没有找到匹配项。"));
      } else {
        const list = node("div", "butler-generated-list");
        items.forEach((item) => {
          const link = node("a", "butler-generated-row");
          link.href = `/references?q=${encodeURIComponent(item.label || item.source_id || "")}`;
          link.appendChild(node("strong", "", item.label || item.source_id || "未命名角色"));
          link.appendChild(node("span", "", [
            item.copyright || "未标注作品",
            item.trigger || "",
            item.gender || "unknown",
          ].filter(Boolean).join(" · ")));
          list.appendChild(link);
        });
        card.appendChild(list);
      }
      const open = node("a", "", "打开角色资料库");
      open.href = result.references_url || "/references";
      card.appendChild(open);
      return;
    }
    if (tool === "search_style_references") {
      const items = result.items || [];
      const card = resultShell("NAI 画风资料", `${Number(result.total || items.length)} 个匹配`, "", target);
      if (!items.length) {
        card.appendChild(node("div", "butler-error", "本地画风资料库没有找到匹配项。"));
      } else {
        const list = node("div", "butler-generated-list");
        items.forEach((item) => {
          const link = node("a", "butler-generated-row");
          link.href = `/references?tab=styles&q=${encodeURIComponent(item.tag || item.label || "")}`;
          link.appendChild(node("strong", "", item.label || item.tag || "未命名画风"));
          link.appendChild(node("span", "", [
            item.kind === "artist" ? "画师" : "画风",
            item.tag || "",
            item.source || "",
          ].filter(Boolean).join(" · ")));
          list.appendChild(link);
        });
        card.appendChild(list);
      }
      const open = node("a", "", "打开 NAI 资料库");
      open.href = result.references_url || "/references?tab=styles";
      card.appendChild(open);
      return;
    }
    if (tool === "inspect_work") {
      const card = resultShell("作品详情", result.work ? `#${result.work.work_id}` : "", "", target);
      if (result.work) {
        const grid = node("div", "butler-work-grid");
        grid.appendChild(workCard(result.work));
        card.appendChild(grid);
      }
      if (result.prompt) {
        const prompt = node("p", "");
        prompt.textContent = result.prompt;
        card.appendChild(prompt);
      }
      return;
    }
    if (tool === "list_queue") {
      const items = result.items || [];
      const card = resultShell("待生成队列", `${items.length} 个作品`, "", target);
      const grid = node("div", "butler-work-grid");
      items.forEach((item) => grid.appendChild(workCard({ ...item, url: `/i/${item.work_id}` })));
      if (items.length) card.appendChild(grid);
      else card.appendChild(node("div", "", "队列目前为空。"));
      return;
    }
    if (tool === "list_favorites") {
      const items = result.items || [];
      const card = resultShell("我的收藏", `${items.length} 个作品`, "", target);
      const grid = node("div", "butler-work-grid");
      items.forEach((item) => grid.appendChild(workCard(item)));
      if (items.length) card.appendChild(grid);
      else card.appendChild(node("div", "", "收藏目前为空。"));
      return;
    }
    if (tool === "list_generated") {
      const groups = result.groups || [];
      const items = result.items || [];
      const card = resultShell("生成成果", result.message || `${groups.length} 个系列`, "", target);
      if (groups.length) {
        const list = node("div", "butler-generated-list");
        groups.forEach((group) => {
          const link = node("a", "butler-generated-row");
          link.href = `/generated?group=${encodeURIComponent(group.group_id || "")}`;
          link.appendChild(node("strong", "", `系列 ${group.group_id || "未命名"}`));
          link.appendChild(node("span", "", `${Number(group.count || 0)} 张 · ${String(group.latest_at || "").replace("T", " ").slice(0, 16)}`));
          list.appendChild(link);
        });
        card.appendChild(list);
      } else if (items.length) {
        const grid = node("div", "butler-work-grid");
        items.filter((item) => item.image_url).forEach((item) => {
          const link = node("a", "butler-work-card");
          link.href = item.image_url;
          const image = node("img");
          image.src = item.image_url;
          image.alt = item.id || "生成成果";
          link.append(image, node("strong", "", item.id || "生成成果"));
          grid.appendChild(link);
        });
        card.appendChild(grid);
      } else {
        card.appendChild(node("div", "", "还没有生成成果。"));
      }
      return;
    }
    if (tool === "inspect_crawler") {
      const progress = result.progress || {};
      const card = resultShell("三图库采集状态", `${Number(progress.overall_percent || 0)}%`, "", target);
      card.appendChild(node("p", "", result.message || progress.status_text || "采集状态已读取"));
      if (Number(progress.preview_exhausted || 0) > 0) {
        card.appendChild(node("p", "butler-error", `${Number(progress.preview_exhausted)} 个封面已耗尽，只有确认后才会重新入队。`));
      }
      const open = node("a", "", "打开采集进度页");
      open.href = result.progress_url || "/progress";
      card.appendChild(open);
      return;
    }
    if (tool === "inspect_capabilities") {
      const card = resultShell("助手可以完成的操作", `${Number(result.supported || 0)} 项`, "", target);
      Object.entries(result.categories || {}).forEach(([category, labels]) => {
        card.appendChild(node("p", "", `${category}：${(labels || []).join("、")}`));
      });
      (result.protected || []).forEach((item) => {
        card.appendChild(node("small", "", `${item.label}：${item.reason}`));
      });
      return;
    }
    if ((tool === "prepare_studio" || tool === "prepare_remix" || tool === "prepare_character_reference") && result.draft) {
      const card = resultShell(
        tool === "prepare_character_reference"
          ? "NAI 角色资料草稿已准备"
          : tool === "prepare_remix"
          ? ({ style: "换画风草稿已准备", combined: "换角与换画风草稿已准备" }[result.remix_kind] || "换角草稿已准备")
          : "工作台草稿已准备",
        result.title || "可应用",
        "",
        target,
      );
      const params = result.draft.params || {};
      card.appendChild(node("p", "", [
        params.width && params.height ? `${params.width}×${params.height}` : "",
        params.steps ? `steps ${params.steps}` : "",
        params.scale !== undefined ? `scale ${params.scale}` : "",
        params.sampler || "",
        params.batch ? `${params.batch} 张` : "",
      ].filter(Boolean).join(" · ")));
      if (result.reference && result.reference.label) {
        card.appendChild(node(
          "small",
          "",
          `角色资料：${result.reference.label} · ${result.reference.source || "本地资料库"}`,
        ));
      }
      const actions = node("div", "butler-result-actions");
      const apply = node("button", "", "应用并打开工作台");
      apply.type = "button";
      apply.addEventListener("click", () => {
        try {
          localStorage.setItem(STUDIO_DRAFT_KEY, JSON.stringify({ ...result.draft, ts: Date.now() }));
          window.location.href = result.studio_url || "/studio?butler=1";
        } catch (_) {
          appendMessage("assistant", "浏览器无法保存工作台草稿，请检查本地存储权限。", { record: false });
        }
      });
      actions.appendChild(apply);
      card.appendChild(actions);
      return;
    }
    const items = result.items || [];
    const card = resultShell("执行结果", tool, "", target);
    card.appendChild(node("p", result.ok === false ? "butler-error" : "", result.message || (result.ok === false ? "执行失败" : "执行完成")));
    if (result.quality && result.quality.replacement_requested) {
      const quality = result.quality;
      const role = quality.preset_label || quality.preset_id || "所选角色";
      card.appendChild(node(
        "p",
        Number(quality.replacement_applied || 0) > 0 ? "" : "butler-error",
        `换角核验：${role} · 已应用 ${Number(quality.replacement_applied || 0)}/${Number(quality.verified_items || 0)} 张`,
      ));
    }
    if (result.quality && result.quality.style_requested) {
      const quality = result.quality;
      const style = quality.style_reference_label || quality.style_preset_label || quality.style_preset_id || "所选画风";
      card.appendChild(node(
        "p",
        Number(quality.style_applied || 0) > 0 ? "" : "butler-error",
        `换画风核验：${style} · 已应用 ${Number(quality.style_applied || 0)}/${Number(quality.verified_items || 0)} 张`,
      ));
    }
    const resultUrl = result.gallery_url || result.generated_url || result.pipeline_url || result.progress_url;
    if (resultUrl) {
      const actions = node("div", "butler-result-actions");
      const open = node("a", "", result.pipeline_url ? "打开后处理" : (result.progress_url ? "打开采集进度" : "打开生成图库"));
      open.href = resultUrl;
      actions.appendChild(open);
      card.appendChild(actions);
    }
    const images = items.filter((item) => item && item.image_url);
    if (images.length) {
      const grid = node("div", "butler-work-grid");
      images.forEach((item, index) => {
        const link = node("a", "butler-work-card");
        link.href = item.image_url;
        const image = node("img");
        image.src = item.image_url;
        image.alt = `生成结果 ${index + 1}`;
        link.appendChild(image);
        link.appendChild(node("strong", "", item.message || `第 ${index + 1} 张`));
        grid.appendChild(link);
      });
      card.appendChild(grid);
    }
  }

  async function handleConfirmation(card, pending, approve) {
    const buttons = card.querySelectorAll("button");
    buttons.forEach((button) => { button.disabled = true; });
    try {
      const data = await window.ApiClient.post("/api/butler/confirm", {
        confirmation_id: pending.confirmation_id,
        approve,
      }, { timeoutMs: 300000 });
      card.replaceChildren();
      card.appendChild(node("p", "", data.message || data.reply || (data.cancelled ? "已取消" : "已确认执行")));
      if (data.result) renderToolResult(data.result);
      (data.pending_actions || []).forEach(renderPending);
      if (data.task) applyTaskSnapshot(data.task, true);
      activatePollBurst();
      startTaskStream(true);
      schedulePoll();
    } catch (error) {
      card.appendChild(node("p", "butler-error", String(error.message || error)));
      buttons.forEach((button) => { button.disabled = false; });
    }
  }

  function renderPending(pending, target) {
    const card = resultShell(pending.label || "等待确认", pending.risk || "confirm", "butler-confirm", target);
    card.appendChild(node("p", "", pending.summary || "这项操作需要确认。"));
    if (pending.preview && ["character_remix", "style_remix"].includes(pending.preview.kind)) {
      const preview = pending.preview;
      const isStyle = preview.kind === "style_remix";
      const subject = isStyle
        ? (preview.style_reference_label || preview.style_preset_label || preview.style_preset_id || "所选画风")
        : (preview.reference_label || preview.preset_label || preview.preset_id || "所选角色");
      card.appendChild(node(
        "strong",
        Number(preview.ready || 0) > 0 ? "" : "butler-error",
        `本地${isStyle ? "换画风" : "换角"}预检：${subject} · 可处理 ${Number(preview.ready || 0)}/${Number(preview.total || 0)} 张`,
      ));
      const skipped = (preview.items || []).filter((item) => !item.ok).slice(0, 4);
      skipped.forEach((item) => {
        card.appendChild(node(
          "small",
          "butler-error",
          `作品 ${item.work_id} 第 ${Number(item.page_index || 0) + 1} 页：${item.message || (isStyle ? "无法换画风" : "无法换角")}`,
        ));
      });
    }
    card.appendChild(node(
      "small",
      "",
      Number(pending.expires_in || 0) > 0
        ? `一次性确认 · ${Math.round(Number(pending.expires_in) / 60)} 分钟内有效`
        : "持久确认点 · 仅当前工作流有效",
    ));
    const actions = node("div", "butler-result-actions");
    const approve = node("button", "approve", "确认执行");
    approve.type = "button";
    approve.addEventListener("click", () => handleConfirmation(card, pending, true));
    const cancel = node("button", "secondary", "取消");
    cancel.type = "button";
    cancel.addEventListener("click", () => handleConfirmation(card, pending, false));
    actions.append(approve, cancel);
    card.appendChild(actions);
  }

  function setBusy(busy) {
    state.busy = busy;
    $("butlerSend").disabled = busy;
    $("butlerInput").disabled = busy;
    $("imageInput").disabled = busy;
    $("stageAttachImage").disabled = busy;
    $("stageAuditGallery").disabled = busy;
    $("removeImage").disabled = busy;
    $("runGalleryCompare").disabled = busy || comparisonCandidates().length < 2;
    $("butlerSend").textContent = busy ? "规划中…" : "发送";
  }

  async function sendMessage(rawMessage, options) {
    const sendOptions = options || {};
    const comparisonCandidates = Array.isArray(sendOptions.comparison) ? sendOptions.comparison : null;
    const attachment = sendOptions.intent === "gallery_audit" ? null : state.pendingImage;
    const message = String(rawMessage || "").trim() || (attachment ? "请看这张图片，说明画面内容并给我具体建议。" : "");
    if (!message || state.busy) return;
    const history = state.history.slice(-12);
    const displayMessage = attachment
      ? `🖼 已附图片：${attachment.name || "图片"}\n${message}`
      : message;
    appendMessage("user", displayMessage, attachment ? {
      preview: attachment.data_url,
      imageName: attachment.name,
    } : undefined);
    $("butlerInput").value = "";
    const inferred = inferAgent(message, sendOptions.intent || "");
    if (inferred !== state.agent) {
      await setAgent(inferred, { reason: "thinking" });
    }
    setBusy(true);
    setMood("thinking", sendOptions.intent === "gallery_audit"
      ? `${state.assistantName}正在分批体检图库…`
      : (attachment ? `${state.assistantName}正在认真看图…` : `${state.assistantName}正在认真想办法…`));
    try {
      const data = await window.ApiClient.post(
        "/api/butler/chat",
        { message, history, image: attachment, intent: sendOptions.intent || "", comparison: comparisonCandidates, agent: state.agent },
        { timeoutMs: 150000 },
      );
      appendMessage("assistant", data.reply || "任务计划已生成。");
      (data.tool_results || []).forEach(renderToolResult);
      (data.pending_actions || []).forEach(renderPending);
      (data.rejected_actions || []).forEach((item) => {
        const card = resultShell("动作已拦截", item.tool || "未知工具");
        card.appendChild(node("p", "butler-error", item.reason || "不在允许的技能范围内"));
      });
      if (data.workflow_id) {
        state.selectedTaskId = data.workflow_id;
        if (data.task) applyTaskSnapshot(data.task, true);
        activatePollBurst();
        startTaskStream(true);
        schedulePoll();
      }
      renderPendingImage(null);
      const submittedTask = data.task || {};
      if (data.answer_only) {
        setMood("happy", "问题回答好啦；只有你明确交代任务时，我才会进入执行流程");
      } else if (submittedTask.terminal) {
        setMood(
          submittedTask.status === "succeeded" ? "happy" : "sorry",
          submittedTask.status === "succeeded"
            ? "完成啦，交付报告也替你整理好了"
            : "这次遇到了阻碍，报告里保留了原因和下一步",
        );
      } else if (submittedTask.status === "awaiting_confirmation") {
        setMood("thinking", "计划已经整理好啦，确认后我就继续替你完成");
      } else {
        setMood("thinking", "任务接住啦，我会盯着每一步，完成后回来向你交付");
      }
    } catch (error) {
      appendMessage("assistant", `这次没有执行：${String(error.message || error)}`);
      setMood("sorry", "刚才没有成功，但我会陪你一起解决");
    } finally {
      setBusy(false);
      $("butlerInput").focus();
    }
  }

  function renderSkills(skills) {
    const host = $("skillList");
    host.replaceChildren();
    const visible = (skills || []).filter((skill) => {
      const desk = skill && skill.desk;
      return !desk || desk === "shared" || desk === state.agent;
    });
    visible.forEach((skill) => {
      const card = node("div", "butler-skill");
      card.appendChild(node("strong", "", skill.label));
      card.appendChild(node("span", "", (skill.capabilities || []).join(" · ")));
      host.appendChild(card);
    });
    $("skillCount").textContent = `${visible.length} 组`;
  }

  function taskForecast(task) {
    const progress = (task && task.progress) || {};
    const steps = Array.isArray(progress.steps) ? progress.steps : [];
    const currentStep = steps.find((item) => ["running", "waiting"].includes(item.status));
    const pendingStep = steps.find((item) => item.status === "pending");
    const status = String((task && task.status) || "");
    const terminal = Boolean(task && task.terminal) || [
      "done", "ready", "error", "cancelled", "succeeded", "partially_succeeded", "failed", "unknown",
    ].includes(status);
    const hasReport = Boolean(task && (task.has_report || (task.result && task.result.report)));
    return {
      current: terminal
        ? (hasReport ? (progress.current_label || "交付报告已生成") : ((task && task.message) || "历史任务已结束"))
        : (progress.current_label || (currentStep && currentStep.label) || (task && task.message) || "等待状态更新"),
      next: terminal ? "无，任务已结束" : (progress.next_label || (pendingStep && pendingStep.label) || "等待计划更新"),
      eta: terminal ? "已结束" : (progress.eta_text || "正在估算"),
      basis: progress.eta_basis || "",
      steps,
      itemCurrent: Number(progress.item_current || 0),
      itemTotal: Number(progress.item_total || 0),
    };
  }

  function durationText(seconds) {
    const value = Math.max(0, Number(seconds || 0));
    if (value < 60) return `${Math.round(value)} 秒`;
    if (value < 3600) return `${Math.max(1, Math.round(value / 60))} 分钟`;
    return `${Math.round(value / 360) / 10} 小时`;
  }

  function renderForecast(task, host, compact) {
    const forecast = taskForecast(task);
    const panel = node("div", compact ? "butler-forecast compact" : "butler-forecast");
    const rows = [
      ["现在", forecast.current],
      ["接下来", forecast.next],
      ["预计", forecast.eta],
    ];
    rows.forEach(([label, value]) => {
      const row = node("div", "butler-forecast-row");
      row.appendChild(node("span", "", label));
      row.appendChild(node("strong", "", value));
      panel.appendChild(row);
    });
    if (forecast.itemTotal > 0) {
      panel.appendChild(node("small", "", `当前步骤内：${forecast.itemCurrent}/${forecast.itemTotal} 项`));
    }
    host.appendChild(panel);
  }

  function renderStepPlan(task, host) {
    const steps = taskForecast(task).steps;
    if (!steps.length) return;
    const section = node("section", "butler-task-detail-card");
    section.appendChild(node("h3", "", `预计进行步骤 · ${steps.length} 步`));
    const list = node("ol", "butler-step-list");
    const statusLabels = {
      completed: "完成", running: "进行中", waiting: "待确认", pending: "稍后", skipped: "已跳过", failed: "未完成", cancelled: "已取消",
    };
    steps.forEach((step) => {
      const item = node("li", `butler-step ${step.status || "pending"}`);
      item.appendChild(node("span", "butler-step-dot", step.status === "completed" ? "✓" : String(step.index || "•")));
      const copy = node("div", "");
      copy.appendChild(node("strong", "", step.label || step.tool || "执行步骤"));
      copy.appendChild(node("small", "", statusLabels[step.status] || step.status || "等待"));
      item.appendChild(copy);
      list.appendChild(item);
    });
    section.appendChild(list);
    host.appendChild(section);
  }

  function renderDeliveryReport(task, host) {
    let report = task && task.result && task.result.report;
    if ((!report || typeof report !== "object") && task && task.terminal) {
      const progress = taskProgress(task);
      const toolResults = Array.isArray((task.result || {}).tool_results) ? task.result.tool_results : [];
      report = {
        title: "历史任务摘要",
        summary: task.message || "这条任务完成于新版交付报告上线前，现有状态和时间线仍可查看。",
        counts: {
          planned: progress.total,
          completed: progress.current,
          skipped: 0,
          rejected: 0,
          item_failed: progress.failed,
        },
        highlights: toolResults.map((item) => item && (item.message || item.summary)).filter(Boolean).slice(0, 8),
        errors: task.error ? [task.error] : [],
        links: [],
      };
    }
    if (!report || typeof report !== "object") return;
    const details = node("details", "butler-task-detail-card butler-delivery-report");
    details.open = true;
    const summary = node("summary", "");
    summary.appendChild(node("strong", "", report.title || "交付报告"));
    summary.appendChild(node("span", "", report.duration_seconds !== undefined ? `用时 ${durationText(report.duration_seconds)}` : "已生成"));
    details.appendChild(summary);
    details.appendChild(node("p", "butler-report-summary", report.summary || report.message || "任务报告已生成。"));
    const counts = report.counts || {};
    const stats = node("div", "butler-report-stats");
    [
      ["计划", counts.planned || 0],
      ["完成", counts.completed || 0],
      ["跳过", counts.skipped || 0],
      ["异常", Number(counts.item_failed || 0) + Number(counts.rejected || 0)],
    ].forEach(([label, value]) => {
      const stat = node("div", "");
      stat.appendChild(node("strong", "", value));
      stat.appendChild(node("span", "", label));
      stats.appendChild(stat);
    });
    details.appendChild(stats);
    const usage = report.usage || {};
    if (Number(usage.calls || 0) || Number(usage.images || 0)) {
      const usageLine = node("p", "butler-report-summary", "");
      const parts = [];
      if (Number(usage.total_tokens || 0)) {
        parts.push(`Token ${Number(usage.total_tokens).toLocaleString()}`);
      }
      if (Number(usage.images || 0)) {
        parts.push(`生图 ${Number(usage.images).toLocaleString()} 张`);
      }
      if (Number(usage.anlas_unknown_images || 0)) {
        parts.push(`Anlas：已知 ${Number(usage.anlas_spent || 0).toLocaleString()}，${Number(usage.anlas_unknown_images)} 张未回报扣费`);
      } else if (Number(usage.images || 0)) {
        parts.push(`Anlas ${Number(usage.anlas_spent || 0).toLocaleString()}`);
      }
      usageLine.textContent = `本任务用量：${parts.join(" · ")}`;
      details.appendChild(usageLine);
    }
    const appendReportList = (title, values, className) => {
      if (!Array.isArray(values) || !values.length) return;
      details.appendChild(node("h4", "", title));
      const list = node("ul", className || "butler-report-list");
      values.forEach((value) => list.appendChild(node("li", "", value)));
      details.appendChild(list);
    };
    appendReportList("交付结果", report.highlights, "butler-report-list");
    appendReportList("需要留意", report.errors, "butler-report-list errors");
    const links = Array.isArray(report.links) ? report.links : [];
    if (links.length) {
      const actions = node("div", "butler-task-actions");
      links.forEach((item) => {
        const link = node("a", "", item.label || "查看结果");
        link.href = item.url || "#";
        actions.appendChild(link);
      });
      details.appendChild(actions);
    }
    host.appendChild(details);
  }

  function renderWorkflow(workflow) {
    const host = $("workflowPanel");
    host.replaceChildren();
    const status = String((workflow && workflow.status) || "idle");
    $("workflowBadge").textContent = ({ running: "运行中", ready: "待上传", done: "已完成", error: "失败", idle: "空闲" })[status] || status;
    host.appendChild(node("strong", "", (workflow && workflow.message) || "暂无管家后台任务"));
    const progress = (workflow && workflow.progress) || {};
    if (progress.total) {
      const current = Number(progress.current !== undefined ? progress.current : progress.done || 0);
      const succeeded = Number(progress.succeeded !== undefined ? progress.succeeded : progress.ok || 0);
      const bar = node("div", "butler-progress");
      const fill = node("span");
      fill.style.width = `${Math.min(100, Math.round((current / Number(progress.total)) * 100))}%`;
      bar.appendChild(fill);
      host.appendChild(bar);
      host.appendChild(node("div", "", `${current}/${progress.total} · 成功 ${succeeded} · 失败 ${progress.failed || 0}`));
    }
    if (workflow && workflow.id) renderForecast(workflow, host, true);
    const result = workflow && workflow.result;
    if ((status === "ready" || (workflow && workflow.phase === "ready_for_upload")) && result) {
      host.appendChild(node("div", "", `共 ${result.total_images || 0} 张，后处理与文案已就绪。`));
      const link = node("a", "", "前往投稿台检查并上传");
      link.href = result.pixiv_url || "/pixiv?prepared=1";
      host.appendChild(link);
    } else if (status === "done" && result && result.gallery_url) {
      const link = node("a", "", "查看生成结果");
      link.href = result.gallery_url;
      host.appendChild(link);
    }
    if (workflow && workflow.id && (workflow.has_report || (result && result.report))) {
      const reportButton = node("button", "butler-report-open", "打开交付报告");
      reportButton.type = "button";
      reportButton.addEventListener("click", () => loadTaskDetail(workflow.id));
      host.appendChild(reportButton);
    }
  }

  function workflowFromTask(task) {
    if (!task) return {};
    const rawResult = task.result || task.result_summary || null;
    const result = rawResult && rawResult.prepared && typeof rawResult.prepared === "object"
      ? { ...rawResult.prepared, report: rawResult.report }
      : rawResult;
    const status = ({
      awaiting_confirmation: "running",
      succeeded: task.phase === "ready_for_upload" ? "ready" : "done",
      partially_succeeded: task.phase === "ready_for_upload" ? "ready" : "done",
      failed: "error",
      cancelled: "cancelled",
      unknown: "error",
    })[task.status] || task.status || "idle";
    return {
      id: task.id,
      status,
      phase: task.phase,
      message: task.message,
      progress: task.progress || {},
      result,
      has_report: Boolean(task.has_report || (task.result && task.result.report)),
      terminal: task.terminal,
    };
  }

  function taskProgress(task) {
    const progress = (task && task.progress) || {};
    const current = Number(progress.current !== undefined ? progress.current : progress.done || 0);
    const total = Number(progress.total || 0);
    const succeeded = Number(progress.succeeded !== undefined ? progress.succeeded : progress.ok || 0);
    const failed = Number(progress.failed || 0);
    const workflowTotal = Number(progress.workflow_total || 0);
    const workflowCompleted = Number(progress.workflow_completed || 0);
    return {
      current: workflowTotal ? workflowCompleted : current,
      total: workflowTotal || total,
      succeeded,
      failed,
    };
  }

  function renderTaskList(tasks) {
    const host = $("taskList");
    host.replaceChildren();
    state.tasks = Array.isArray(tasks) ? tasks : [];
    if (!state.tasks.length) {
      host.appendChild(node("div", "", "暂无持久任务"));
      $("taskDetail").replaceChildren();
      return;
    }
    renderWorkflow(workflowFromTask(state.tasks[0]));
    state.tasks.forEach((task) => {
      const row = node("button", `butler-task-row${state.selectedTaskId === task.id ? " active" : ""}`);
      row.type = "button";
      row.appendChild(node("strong", "", task.title || task.message || `任务 ${task.id}`));
      row.appendChild(node("span", `butler-task-status ${task.status || ""}`, TASK_STATUS_LABELS[task.status] || task.status || "未知"));
      const progress = taskProgress(task);
      const forecast = taskForecast(task);
      row.appendChild(node("span", "", progress.total ? `${progress.current}/${progress.total} · ${forecast.current}` : (task.phase || "等待详情")));
      row.appendChild(node("span", "", String(task.updated_at || "").replace("T", " ").slice(5, 16)));
      const hasReport = Boolean(task.has_report || (task.result && task.result.report));
      row.appendChild(node(
        "span",
        "butler-task-row-flow",
        `${task.terminal ? (hasReport ? "报告" : "摘要") : "下一步"}：${task.terminal ? "可查看" : forecast.next} · ${forecast.eta}`,
      ));
      row.addEventListener("click", () => {
        loadTaskDetail(task.id)
          .then(() => startTaskStream(true))
          .catch(() => {});
      });
      host.appendChild(row);
    });
  }

  function taskPreparedResult(task) {
    const result = (task && task.result) || {};
    if (result.prepared && typeof result.prepared === "object") return result.prepared;
    const toolResults = Array.isArray(result.tool_results) ? result.tool_results : [];
    for (let index = toolResults.length - 1; index >= 0; index -= 1) {
      if (toolResults[index] && toolResults[index].prepared) return toolResults[index].prepared;
    }
    return null;
  }

  async function runTaskAction(task, action) {
    const detail = $("taskDetail");
    detail.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    try {
      const data = await window.ApiClient.post(`/api/butler/tasks/${encodeURIComponent(task.id)}/${action}`, {}, { timeoutMs: 30000 });
      (data.pending_actions || []).forEach(renderPending);
      const selectedId = data.task && data.task.id ? data.task.id : task.id;
      if (data.task) applyTaskSnapshot(data.task, true);
      activatePollBurst();
      if (selectedId) state.selectedTaskId = selectedId;
      startTaskStream(true);
      schedulePoll();
    } catch (error) {
      detail.appendChild(node("div", "butler-task-error", String(error.message || error)));
      detail.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    }
  }

  function renderTaskDetail(task) {
    const host = $("taskDetail");
    host.replaceChildren();
    if (!task) return;
    state.selectedTaskId = task.id || "";
    renderTaskList(state.tasks);
    const card = node("section", "butler-task-detail-card");
    card.appendChild(node("h3", "", task.title || `任务 ${task.id}`));
    card.appendChild(node("div", "", `${TASK_STATUS_LABELS[task.status] || task.status} · ${task.phase || ""}`));
    card.appendChild(node("div", "", task.message || ""));
    renderForecast(task, card, false);
    const progress = taskProgress(task);
    if (progress.total) {
      const bar = node("div", "butler-progress");
      const fill = node("span");
      fill.style.width = `${Math.min(100, Math.round((progress.current / progress.total) * 100))}%`;
      bar.appendChild(fill);
      card.appendChild(bar);
      card.appendChild(node("div", "", `${progress.current}/${progress.total} · 成功 ${progress.succeeded} · 失败 ${progress.failed}`));
    }
    if (task.error) card.appendChild(node("div", "butler-task-error", task.error));
    const actions = node("div", "butler-task-actions");
    const capabilities = task.capabilities || {};
    if (capabilities.cancel) {
      const cancel = node("button", "danger", "取消任务");
      cancel.type = "button";
      cancel.addEventListener("click", () => runTaskAction(task, "cancel"));
      actions.appendChild(cancel);
    }
    if (capabilities.retry) {
      const retry = node("button", "", "重新执行");
      retry.type = "button";
      retry.addEventListener("click", () => runTaskAction(task, "retry"));
      actions.appendChild(retry);
    }
    if (capabilities.resume) {
      const resume = node("button", "", "从检查点继续");
      resume.type = "button";
      resume.addEventListener("click", () => runTaskAction(task, "resume"));
      actions.appendChild(resume);
    }
    const prepared = taskPreparedResult(task);
    if (prepared && prepared.status === "ready_for_upload") {
      const open = node("a", "", `检查 ${Array.isArray(prepared.items) ? prepared.items.length : 1} 个投稿草稿`);
      open.href = prepared.pixiv_url || `/pixiv?prepared=1&package=${encodeURIComponent(prepared.package_id || task.id)}`;
      actions.appendChild(open);
    }
    if (actions.childNodes.length) card.appendChild(actions);
    host.appendChild(card);

    renderStepPlan(task, host);
    renderDeliveryReport(task, host);

    if (task.pending_action) renderPending(task.pending_action, host);

    const storedResults = Array.isArray((task.result || {}).tool_results)
      ? task.result.tool_results
      : [];
    storedResults
      .filter(Boolean)
      .forEach((result) => renderToolResult(result, host));

    const events = Array.isArray(task.events) ? task.events : [];
    if (events.length) {
      const timelineCard = node("section", "butler-task-detail-card");
      timelineCard.appendChild(node("h3", "", "执行时间线"));
      const timeline = node("div", "butler-timeline");
      events.slice().reverse().forEach((event) => {
        const row = node("div", "butler-timeline-row");
        row.appendChild(node("time", "", String(event.time || "").slice(11, 19)));
        row.appendChild(node("span", "", event.message || event.type || "状态更新"));
        timeline.appendChild(row);
      });
      timelineCard.appendChild(timeline);
      host.appendChild(timelineCard);
    }
  }

  async function loadTaskDetail(taskId) {
    if (!taskId) return;
    const data = await window.ApiClient.get(`/api/butler/tasks/${encodeURIComponent(taskId)}`, { timeoutMs: 30000 });
    renderTaskDetail(data.task || null);
  }

  async function loadTasks(selectId, options) {
    const targetId = selectId || ((options && options.loadSelected) ? state.selectedTaskId : "");
    let url = "/api/butler/tasks?limit=20";
    if (targetId) url += `&selected_id=${encodeURIComponent(targetId)}`;
    const data = await window.ApiClient.get(url, { timeoutMs: 30000 });
    const tasks = data.tasks || [];
    renderTaskList(tasks);
    if (targetId && data.selected_task) renderTaskDetail(data.selected_task);
    else if (targetId) await loadTaskDetail(targetId);
    return tasks;
  }

  function applyTaskSnapshot(task, showDetail) {
    if (!task || !task.id) return;
    const index = state.tasks.findIndex((item) => item.id === task.id);
    if (index >= 0) state.tasks[index] = { ...state.tasks[index], ...task };
    else state.tasks.unshift(task);
    state.tasks = state.tasks.slice(0, 20);
    renderTaskList(state.tasks);
    if (showDetail) renderTaskDetail(task);
  }

  function stopPolling() {
    if (state.pollTimer) window.clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }

  function shouldPoll() {
    return !document.hidden
      && !state.taskStreamConnected
      && state.tasks.some((task) => ACTIVE_TASK_STATUSES.has(task.status));
  }

  function stopTaskStream() {
    const stream = state.taskStream;
    state.taskStream = null;
    state.taskStreamConnected = false;
    state.taskStreamSelectedId = "";
    state.lastTaskStreamRevision = -1;
    if (stream) stream.close();
  }

  function updateTaskMood(task) {
    if (!task) return;
    if (task.terminal) {
      setMood(
        task.status === "succeeded" ? "happy" : "sorry",
        task.status === "succeeded"
          ? "顺利完成啦，报告已经整理好，等你来验收"
          : "这一步没能顺利完成，但原因和可继续的线索都留在报告里了",
      );
      return;
    }
    const forecast = taskForecast(task);
    const situation = situationFromTask(task);
    setMood(
      situation === "ready" ? "ready" : situation,
      task.status === "awaiting_confirmation"
        ? `计划走到「${forecast.current}」，等你确认后我就继续`
        : `正在替你做「${forecast.current}」· ${forecast.eta}`,
    );
  }

  async function applyTaskStreamPayload(data) {
    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    renderTaskList(tasks);
    if (data.selected_task) renderTaskDetail(data.selected_task);
    const selected = data.selected_task
      || tasks.find((task) => task.id === state.selectedTaskId)
      || tasks.find((task) => ACTIVE_TASK_STATUSES.has(task.status));
    if (selected && selected.terminal) await loadHistory();
    updateTaskMood(selected);
    schedulePoll();
  }

  function startTaskStream(force) {
    if (document.hidden || typeof window.EventSource !== "function") return false;
    const selectedId = state.selectedTaskId || "";
    if (!force && state.taskStream && state.taskStreamSelectedId === selectedId) return true;
    stopTaskStream();
    const query = selectedId ? `?selected_id=${encodeURIComponent(selectedId)}` : "";
    const stream = new EventSource("/api/butler/tasks/stream" + query);
    state.taskStream = stream;
    state.taskStreamSelectedId = selectedId;
    stream.addEventListener("open", () => {
      if (state.taskStream !== stream) return;
      state.taskStreamConnected = true;
      state.lastTaskStreamRevision = -1;
      stopPolling();
    });
    stream.addEventListener("tasks", (event) => {
      if (state.taskStream !== stream) return;
      state.taskStreamConnected = true;
      try {
        const data = JSON.parse(event.data || "{}");
        const revision = Number(data.revision || 0);
        if (revision < state.lastTaskStreamRevision) return;
        state.lastTaskStreamRevision = revision;
        applyTaskStreamPayload(data).catch(() => {});
      } catch (_) {
        /* Invalid push data falls back to the existing polling path. */
      }
    });
    stream.addEventListener("error", () => {
      if (state.taskStream !== stream) return;
      state.taskStreamConnected = false;
      activatePollBurst(4000);
      schedulePoll();
    });
    return true;
  }

  function activatePollBurst(durationMs) {
    state.pollBurstUntil = Math.max(state.pollBurstUntil, Date.now() + Number(durationMs || 12000));
  }

  function currentPollDelay() {
    const configured = POLL_DELAYS[state.pollMode] || POLL_DELAYS.balanced;
    if (Date.now() < state.pollBurstUntil) return Math.min(configured, 750);
    const active = state.tasks.find((task) => ACTIVE_TASK_STATUSES.has(task.status));
    const eta = Number(active && active.progress && active.progress.eta_seconds || 0);
    return eta > 120 ? Math.max(configured, 5000) : configured;
  }

  function schedulePoll() {
    stopPolling();
    if (!shouldPoll()) return;
    const delay = currentPollDelay();
    state.pollTimer = window.setTimeout(pollTasks, delay);
  }

  async function pollTasks() {
    if (state.polling || !shouldPoll()) return;
    state.polling = true;
    try {
      const selectedId = state.selectedTaskId;
      await loadTasks(selectedId, { loadSelected: Boolean(selectedId) });
      const selected = state.tasks.find((task) => task.id === selectedId);
      if (selected && selected.terminal) {
        await loadHistory();
        updateTaskMood(selected);
      } else if (selected) {
        updateTaskMood(selected);
      }
    } catch (_) {
      /* A transient status failure should not interrupt chat. */
    } finally {
      state.polling = false;
      schedulePoll();
    }
  }

  function renderAudit(rows) {
    const host = $("auditList");
    host.replaceChildren();
    if (!rows || !rows.length) {
      host.textContent = "暂无记录";
      return;
    }
    rows.slice(0, 8).forEach((row) => {
      const line = node("div", "butler-audit-row");
      line.appendChild(node("span", "", String(row.time || "").slice(11, 19)));
      line.appendChild(node("strong", "", row.tool || "action"));
      line.appendChild(node("span", "", row.status || ""));
      host.appendChild(line);
    });
  }

  async function loadStatus(options) {
    const data = await window.ApiClient.get("/api/butler/status", { timeoutMs: 30000 });
    state.status = data;
    const readiness = $("butlerReadiness");
    readiness.replaceChildren();
    if (data.ai && data.ai.configured) {
      readiness.className = `butler-readiness ${data.generation && data.generation.configured ? "ready" : "warn"}`;
      readiness.textContent = data.generation && data.generation.configured
        ? "AI 与生图能力均已就绪"
        : "AI 已就绪；批量生图还需要配置 NAI Token";
      $("butlerModel").textContent = `${data.ai.provider || "OpenAI-compatible"} · ${data.ai.model || "已配置"}`;
    } else {
      readiness.className = "butler-readiness warn";
      readiness.appendChild(node("span", "", "尚未配置大模型 API · "));
      const link = node("a", "", "前往设置");
      link.href = "/settings";
      readiness.appendChild(link);
      $("butlerModel").textContent = "等待 API 配置";
    }
    renderSkills(data.skills || []);
    renderWorkflow(data.workflow || {});
    renderAudit(data.audit || []);
    if (!options || !options.skipTasks) renderTaskList(data.tasks || []);
    schedulePoll();
    return data;
  }

  function fillTemplate(prompt) {
    const input = $("butlerInput");
    input.value = String(prompt || "");
    input.focus();
  }

  function renderTemplates(templates) {
    const host = $("butlerTemplates");
    if (!host) return;
    host.replaceChildren();
    (templates || []).forEach((template) => {
      const fill = node("button", "", template.label || "常用任务");
      fill.type = "button";
      fill.title = "填入输入框，不会立即执行";
      fill.addEventListener("click", () => fillTemplate(template.prompt));
      if (!template.deletable) {
        host.appendChild(fill);
        return;
      }
      const chip = node("span", "butler-template-chip");
      chip.appendChild(fill);
      const remove = node("button", "", "×");
      remove.type = "button";
      remove.title = `删除“${template.label || "常用任务"}”`;
      remove.setAttribute("aria-label", remove.title);
      remove.addEventListener("click", async () => {
        if (!window.confirm(`删除常用任务“${template.label || ""}”？`)) return;
        try {
          await window.ApiClient.request(`/api/butler/templates/${encodeURIComponent(template.id)}`, {
            method: "DELETE",
            timeoutMs: 15000,
          });
          await loadTemplates();
          setMood("happy", "常用任务已经删掉啦，其他内容都没有变化。");
        } catch (error) {
          setMood("sorry", `删除失败：${String(error.message || error)}`);
        }
      });
      chip.appendChild(remove);
      host.appendChild(chip);
    });
  }

  async function loadTemplates() {
    const data = await window.ApiClient.get("/api/butler/templates", { timeoutMs: 15000 });
    renderTemplates(data.templates || []);
  }

  async function saveCurrentTemplate() {
    const prompt = String($("butlerInput").value || "").trim();
    if (!prompt) {
      setMood("sorry", "先在输入框写好任务指令，再保存成常用任务吧。");
      $("butlerInput").focus();
      return;
    }
    const suggested = prompt.length > 14 ? `${prompt.slice(0, 14)}…` : prompt;
    const label = window.prompt("给这个常用任务起个短名字", suggested);
    if (label === null) return;
    const button = $("saveTemplateBtn");
    button.disabled = true;
    try {
      await window.ApiClient.request("/api/butler/templates", {
        method: "POST",
        body: { label, prompt },
        timeoutMs: 15000,
      });
      await loadTemplates();
      setMood("happy", "记住啦！以后点一下就能把这条指令填回来，不会自动执行。");
    } catch (error) {
      setMood("sorry", `保存失败：${String(error.message || error)}`);
    } finally {
      button.disabled = false;
    }
  }

  function tapLine(kind) {
    if (state.agent === "tomori") {
      return kind === "head" ? "那个、头发……" : "我在听。咕。";
    }
    return kind === "head" ? "等一下……" : "有事就说。";
  }

  function bindLive2dTouch() {
    if (!window.Live2dTouch || !$("live2dStage")) return;
    window.Live2dTouch.bind($("live2dStage"), {
      getWidget: () => state.widget,
      tone: () => (state.agent === "tomori" ? "pink" : "gold"),
      onTap(kind) {
        setMood(kind === "head" ? "surprised" : "happy", tapLine(kind));
      },
    });
  }

  function bind() {
    bindLive2dTouch();
    $("butlerForm").addEventListener("submit", (event) => {
      event.preventDefault();
      sendMessage($("butlerInput").value);
    });
    $("butlerInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage($("butlerInput").value);
      }
    });
    $("imageInput").addEventListener("change", async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) return;
      setMood("thinking", `${state.assistantName}正在准备图片…`);
      try {
        renderPendingImage(await compressImage(file));
        setMood("happy", "图片准备好啦，告诉我想看什么就可以发送");
        $("butlerInput").focus();
      } catch (error) {
        renderPendingImage(null);
        setMood("sorry", String(error.message || error));
      }
    });
    $("stageAttachImage").addEventListener("click", () => $("imageInput").click());
    $("stageAuditGallery").addEventListener("click", () => {
      sendMessage("检查最近一个月的图库本地状态，帮我找出缺图、索引错误和采集不足，不要识图。", {
        intent: "gallery_audit",
      });
    });
    $("clearGalleryCompare").addEventListener("click", () => {
      state.comparisonWorkspace.clear();
      renderComparisonWorkspace();
      setMood("ready", "固定候选已经清空；没有调用识图");
    });
    $("runGalleryCompare").addEventListener("click", () => {
      const candidates = comparisonCandidates();
      if (candidates.length < 2) {
        setMood("sorry", "先从图库搜索结果加入至少 2 张图片，我才能认真比较");
        return;
      }
      const question = String($("galleryCompareQuestion").value || "").trim()
        || "这几张哪个更好看？请比较构图、完成度和明显不足。";
      sendMessage(question, {
        intent: "gallery_compare",
        comparison: candidates.map((item) => ({
          gallery_id: item.gallery_id,
          work_id: item.work_id,
          page_index: item.page_index,
        })),
      });
    });
    $("removeImage").addEventListener("click", () => {
      renderPendingImage(null);
      setMood("ready", `${state.assistantName}在这里陪你`);
    });
    document.querySelectorAll("[data-command]").forEach((button) => {
      button.addEventListener("click", () => fillTemplate(button.dataset.command));
    });
    $("saveTemplateBtn").addEventListener("click", saveCurrentTemplate);
    $("loadOlderHistory").addEventListener("click", () => {
      if (!state.historyBefore) return;
      $("loadOlderHistory").disabled = true;
      loadHistory(state.historyBefore)
        .catch((error) => setMood("sorry", `更早记录读取失败：${String(error.message || error)}`))
        .finally(() => { $("loadOlderHistory").disabled = false; });
    });
    $("clearChat").addEventListener("click", async () => {
      if (!window.confirm("确定清空与助手的全部本机聊天记录吗？此操作无法撤销。")) return;
      try {
        await window.ApiClient.request(HISTORY_API, { method: "DELETE", timeoutMs: 30000 });
        state.history = [];
        state.historyBefore = null;
        $("loadOlderHistory").hidden = true;
        $("butlerMessages").replaceChildren();
        appendMessage("assistant", "记录已经清空啦。没关系，我们可以从新的目标重新开始。", { record: false });
        setMood("ready", `${state.assistantName}随时等你`);
      } catch (error) {
        setMood("sorry", `清空失败：${String(error.message || error)}`);
      }
    });
    $("refreshTasks").addEventListener("click", () => {
      loadTasks(state.selectedTaskId, { loadSelected: true }).then(schedulePoll).catch(() => {});
    });
    $("toggleLive2d").addEventListener("click", async () => {
      const button = $("toggleLive2d");
      button.disabled = true;
      try {
        if (state.widget && typeof state.widget.destroy === "function") {
          await destroyLive2d();
          button.textContent = "显示形象";
          setMood("ready", `${state.assistantName}先在旁边安静陪你`);
        } else {
          await initLive2d();
        }
      } finally {
        button.disabled = false;
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stopTaskStream();
        stopPolling();
      } else {
        loadTasks(state.selectedTaskId, { loadSelected: Boolean(state.selectedTaskId) })
          .then(() => {
            startTaskStream(true);
            schedulePoll();
          })
          .catch(schedulePoll);
      }
    });
    window.addEventListener("pagehide", () => {
      stopTaskStream();
      stopPolling();
      if (state.widget && typeof state.widget.destroy === "function") destroyLive2d();
    }, { once: true });
  }

  document.addEventListener("DOMContentLoaded", async () => {
    const linkedTask = new URLSearchParams(window.location.search).get("task") || "";
    if (/^[a-zA-Z0-9_-]{1,80}$/.test(linkedTask)) state.selectedTaskId = linkedTask;
    if (!window.ComparisonWorkspace?.ComparisonWorkspace) {
      throw new Error("固定候选工作区模块没有加载");
    }
    state.comparisonWorkspace = new window.ComparisonWorkspace.ComparisonWorkspace();
    bind();
    renderComparisonWorkspace();
    const statusPromise = loadStatus();
    await loadCompanionCatalog();
    await loadPreferences();
    const linkedAgent = new URLSearchParams(window.location.search).get("agent") || "";
    if (linkedAgent === "tomori" || linkedAgent === "sakiko") {
      state.agent = linkedAgent;
      applyAssistantName();
    }
    initLive2d();
    try {
      await Promise.all([loadHistory(), loadTemplates(), statusPromise]);
    } catch (error) {
      $("butlerReadiness").textContent = `状态读取失败：${String(error.message || error)}`;
    }
    startTaskStream();
    schedulePoll();
  });
})();

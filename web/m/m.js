(function () {
  const TOKEN_KEY = "nai-mobile-pair-token";
  const QUEUE_KEY = "nai-mobile-online-queue";
  const LAST_WORK_KEY = "nai-mobile-last-work";
  const DRAFTS_KEY = "nai-mobile-work-drafts";
  const state = {
    route: { name: "browse" },
    canWrite: false,
    loopback: false,
    lastWorkId: "",
    work: null,
    drafts: {},
    targetId: "",
    targetLabel: "",
    targetRecord: null,
    targetGender: "female",
    targetQuery: "",
    searchSource: "all",
    ocMode: true,
    clothing: "",
    extraTags: "",
    removeTags: "",
    styleId: "",
    styleLabel: "",
    styleRecord: null,
    copies: 1,
    slot: null,
    slotTargets: {},
    pageIndex: 0,
    busy: false,
    favIds: {},
    browseMode: "online",
    searchPage: 1,
    searchSort: "new",
    searchQ: "明日方舟",
    lastSearchMeta: {},
  };
  let browseSearchSeq = 0;
  let charSearchSeq = 0;
  let styleSearchSeq = 0;
  let favIdsAt = 0;

  function debounce(fn, ms) {
    let timer = 0;
    return function () {
      const args = arguments;
      const ctx = this;
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(ctx, args), ms);
    };
  }

  function isStandalone() {
    const search = String(location.search || "");
    return !!(
      window.__NAI_STANDALONE__
      || (document.body && document.body.getAttribute("data-standalone") === "1")
      || /(?:\?|&)standalone=1(?:&|$)/.test(search)
    );
  }

  function api() {
    if (!window.ApiClient) throw new Error("ApiClient 未加载");
    return window.ApiClient;
  }

  function restoreToken() {
    try {
      const raw = localStorage.getItem(TOKEN_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved && saved.token && Number(saved.expires_at || 0) * 1000 > Date.now()) {
        window.__NAI_SESSION_TOKEN__ = saved.token;
      } else {
        localStorage.removeItem(TOKEN_KEY);
      }
    } catch (_) { /* ignore */ }
  }

  function saveToken(token, expiresAt) {
    window.__NAI_SESSION_TOKEN__ = token;
    try {
      localStorage.setItem(TOKEN_KEY, JSON.stringify({ token: token, expires_at: expiresAt }));
    } catch (_) { /* ignore */ }
  }

  function clearToken() {
    window.__NAI_SESSION_TOKEN__ = "";
    try { localStorage.removeItem(TOKEN_KEY); } catch (_) { /* ignore */ }
  }

  function toast(message, kind) {
    const el = document.getElementById("mToast");
    if (!el) return;
    el.textContent = message;
    el.className = "m-toast" + (kind === "err" ? " err" : "");
    window.setTimeout(() => el.classList.add("hidden"), 3200);
  }

  function confirmAction(title, body) {
    return new Promise((resolve) => {
      const modal = document.getElementById("mModal");
      document.getElementById("mModalTitle").textContent = title;
      document.getElementById("mModalBody").textContent = body;
      modal.classList.remove("hidden");
      modal.setAttribute("aria-hidden", "false");
      const done = (ok) => {
        modal.classList.add("hidden");
        modal.setAttribute("aria-hidden", "true");
        resolve(ok);
      };
      document.getElementById("mModalYes").onclick = () => done(true);
      document.getElementById("mModalNo").onclick = () => done(false);
    });
  }

  function friendlyError(error) {
    const raw = String((error && (error.message || error.detail)) || error || "");
    if (/connection closed|connection reset|broken pipe|unexpected end|生成连接被掐断/i.test(raw)) {
      return "生成连接被掐断。没看到成功回执，先看 NovelAI 记录有没有扣费，再手动重试。失败任务可从队列删除。";
    }
    if (/proxy|Connection refused|Failed to connect|ECONNREFUSED|CONNECT|7890|7897/i.test(raw)) {
      return "代理没通。Clash 开 HTTP，填 http://127.0.0.1:7890，不要只开全局 VPN。";
    }
    if (/<!DOCTYPE|Just a moment|cloudflare|HTTP 403|HTTP 502|Bad Gateway|浏览器通道/i.test(raw)) {
      return "在线库暂时打不开。网站拦了访问：到设置填 Clash HTTP，或点「打开在线库过验证」。";
    }
    if (/not found|404/i.test(raw)) {
      return "这一页还没有数据。先去发现选一张图。";
    }
    return raw.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim().slice(0, 140) || "出了点问题，再试一次";
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function loadQueue() {
    try {
      const raw = JSON.parse(localStorage.getItem(QUEUE_KEY) || "[]");
      return Array.isArray(raw) ? raw : [];
    } catch (_) {
      return [];
    }
  }

  function saveQueue(items) {
    localStorage.setItem(QUEUE_KEY, JSON.stringify(items.slice(0, 80)));
  }

  function persistDrafts(workId) {
    const id = String(workId || "");
    if (!id) return;
    try { localStorage.setItem(DRAFTS_KEY + ":" + id, JSON.stringify(state.drafts || {})); } catch (_) { /* ignore */ }
    try { localStorage.setItem(DRAFTS_KEY + "-slots:" + id, JSON.stringify(state.slotTargets || {})); } catch (_) { /* ignore */ }
  }

  function restoreSlotTargets(workId) {
    const id = String(workId || "");
    if (!id) return {};
    try {
      const raw = JSON.parse(localStorage.getItem(DRAFTS_KEY + "-slots:" + id) || "{}");
      return raw && typeof raw === "object" ? raw : {};
    } catch (_) {
      return {};
    }
  }

  function restoreDrafts(workId) {
    const id = String(workId || "");
    if (!id) return {};
    try {
      const raw = JSON.parse(localStorage.getItem(DRAFTS_KEY + ":" + id) || "{}");
      return raw && typeof raw === "object" ? raw : {};
    } catch (_) {
      return {};
    }
  }

  function parseRoute() {
    const hash = String(location.hash || "#/browse").replace(/^#/, "") || "/browse";
    const parts = hash.split("/").filter(Boolean);
    if (parts[0] === "library" && parts[1]) return { name: "work", id: String(parts[1]), local: true };
    if (parts[0] === "library") return { name: "browse", mode: "library" };
    if (parts[0] === "work" && parts[1]) return { name: "work", id: String(parts[1]), local: state.browseMode === "library" };
    if (parts[0] === "work") return { name: "work", id: state.lastWorkId || "", local: state.browseMode === "library" };
    if (parts[0] === "batch") return { name: "batch" };
    if ((parts[0] === "gallery" || parts[0] === "outputs") && parts[1]) return { name: "album", id: String(parts[1]) };
    if (parts[0] === "gallery" || parts[0] === "outputs") return { name: "gallery" };
    if (parts[0] === "pipeline") return { name: isStandalone() ? "gallery" : "pipeline" };
    if (parts[0] === "pair" || parts[0] === "settings") {
      return { name: isStandalone() ? "settings" : "pair" };
    }
    return { name: "browse" };
  }

  function setConn(text, kind) {
    const el = document.getElementById("mConn");
    if (!el) return;
    el.textContent = text;
    el.className = "m-pill" + (kind ? " " + kind : "");
  }

  function markTabs(name) {
    document.querySelectorAll(".m-tabbar a").forEach((link) => {
      const tab = link.dataset.tab;
      const onGallery = (name === "gallery" || name === "album") && (tab === "gallery" || tab === "pipeline");
      link.classList.toggle("active", tab === name || onGallery);
    });
  }

  async function refreshWriteAccess() {
    if (isStandalone()) {
      state.loopback = true;
      state.canWrite = true;
      setConn("手机本地", "ok");
      try {
        return await api().get("/api/mobile/status");
      } catch (_) {
        return { ok: true, standalone: true, loopback: true };
      }
    }
    try {
      const status = await api().get("/api/mobile/status");
      state.loopback = !!status.loopback;
      if (state.loopback) {
        state.canWrite = true;
        setConn("本机", "ok");
        return status;
      }
      if (window.__NAI_SESSION_TOKEN__) {
        state.canWrite = true;
        setConn("已配对", "ok");
        return status;
      }
      state.canWrite = false;
      setConn(status.remote_listen ? "待配对" : "只读", "warn");
      return status;
    } catch (error) {
      state.canWrite = !!window.__NAI_SESSION_TOKEN__ || state.loopback;
      setConn("离线", "warn");
      return null;
    }
  }

  function openSettings() {
    if (isStandalone()) {
      location.hash = "#/settings";
      return;
    }
    location.hash = "#/pair";
  }

  function openNativeSettings() {
    if (window.PhoneApp && typeof window.PhoneApp.openSettings === "function") {
      window.PhoneApp.openSettings();
    }
  }

  function requireWrite() {
    if (isStandalone() || state.canWrite) return true;
    toast("手机写操作需要先配对，或用 USB adb reverse 访问本机", "err");
    location.hash = "#/pair";
    return false;
  }

  function draftComment(entry) {
    const draft = entry && (entry.draft || entry);
    if (draft && draft.comment && typeof draft.comment === "object") return draft.comment;
    return null;
  }

  function workHasPrompts() {
    const images = (state.work && state.work.images) || [];
    return images.some((image) => {
      if (!image) return false;
      if (String(image.prompt_text || "").trim()) return true;
      const comment = (window.StandaloneCore && window.StandaloneCore.imageComment)
        ? window.StandaloneCore.imageComment(image)
        : {};
      const prompt = String((comment && (comment.prompt || (comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.base_caption))) || "").trim();
      const slots = comment && comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.char_captions;
      return !!prompt || (Array.isArray(slots) && slots.some((slot) => slot && String(slot.char_caption || "").trim()));
    });
  }

  function remixReady() {
    if (!isStandalone()) return true;
    const workId = String((state.work && state.work.work && (state.work.work.work_id || state.work.work.id)) || "");
    if (!workId) return false;
    if (DemoWorksSafe(workId) || String(workId).startsWith("g")) return true;
    const saveState = String((state.work && state.work.save_state) || "");
    if (saveState === "ready") return true;
    return workHasPrompts();
  }

  function remixBlockReason() {
    const saveState = String((state.work && state.work.save_state) || "");
    if (workHasPrompts()) return "";
    if (saveState === "pending" || saveState === "saving") return "正在抓咒语，抓到就能换角，不用等原图";
    if (saveState === "partial") return "这套还没有 NovelAI 咒语，换不了角";
    return "先收藏入本地库，才能换角和生成";
  }

  async function render() {
    state.route = parseRoute();
    if (state.route.mode === "library") state.browseMode = "library";
    markTabs(state.route.name);
    const root = document.getElementById("mApp");
    if (state.route.name === "settings") return renderSettings(root);
    if (state.route.name === "pair") return renderPair(root);
    if (state.route.name === "work") return renderWork(root, state.route.id);
    if (state.route.name === "batch") return renderBatch(root);
    if (state.route.name === "album") return renderAlbum(root, state.route.id);
    if (state.route.name === "gallery") return renderGallery(root);
    if (state.route.name === "pipeline") return renderPipeline(root);
    return renderBrowse(root);
  }

  async function renderBrowse(root) {
    const standalone = isStandalone();
    let nai = { has_token: false };
    let ai = { has_api_key: false };
    if (standalone) {
      try { nai = await api().get("/api/nai/status"); } catch (_) { /* ignore */ }
      try { ai = await api().get("/api/ai/status"); } catch (_) { /* ignore */ }
    }
    const hasNai = !!nai.has_token;
    const hasAi = !!(ai.has_api_key || ai.has_deepseek);
    root.innerHTML = `
      <section class="m-hero">
        <p class="m-eyebrow">Nai学长工作室 · ${standalone ? "1.5.2 手机独立版" : "手机预览"}</p>
        <h2>三步就会用</h2>
        <ol class="m-guide">
          <li>点右上角「设置」，填 NovelAI 和 DeepSeek</li>
          <li>${standalone ? "发现里点☆收藏，入本地库" : "下面搜一张图，点进去"}</li>
          <li>${standalone ? "本地库选人、看画风，点「整系列换角并入队」" : "选人 → 写草稿 → 确认出图"}</li>
        </ol>
        <p class="m-hint">${standalone
          ? "不遥控电脑。在线库只负责搜图收藏。收藏后咒语到了就能换角，原图下不下都行。原图画风会先识别出来，再整系列替换。同一任务的图会收进图库一组。多个 Token 可并发出图。"
          : "搜 AITag 在线库，点进作品后换角。默认只要 NAI 图。"}</p>
        <div class="m-quote">凑企鹅：先选人，再看原图画风。整系列一键入队。没填 Token 我不会替你出图。</div>
      </section>
      ${standalone ? `
      <section class="m-card m-keys">
        <h2>先填两把钥匙</h2>
        <p>出图：<strong class="${hasNai ? "m-ok" : "m-err"}">${hasNai ? ("NovelAI 已填" + (nai.token_count > 1 ? (" · " + nai.token_count + " 路并发") : "")) : "还没填 NovelAI"}</strong></p>
        <p>写角色：<strong class="${hasAi ? "m-ok" : "m-err"}">${hasAi ? "DeepSeek 已填" : "还没填 DeepSeek"}</strong></p>
        <div class="m-row" style="margin-top:10px">
          <button type="button" id="mGoSettings" class="m-primary">${hasNai && hasAi ? "查看设置" : "去填钥匙"}</button>
        </div>
      </section>` : ""}
      <section class="m-card">
        <h2>在线发现</h2>
        <p class="m-hint">${standalone
          ? "在线库用来搜图和收藏。点☆入库后，去本地库才能换角和生成。在线挂了也能先用内置样例。"
          : "搜 AITag 在线库，点进作品后换角。默认只要 NAI 图。在线挂了也能先用内置样例把换角跑通。"}</p>
        <div class="m-row">
          <input id="mSearch" placeholder="角色 / 作品 / 标签" enterkeyhint="search" value="${escapeHtml(state.searchQ || "")}" />
          <button type="button" id="mSearchBtn" class="m-primary">搜索</button>
        </div>
        <div class="m-chips" id="mModeChips"></div>
        <div class="m-chips" id="mSortChips"></div>
        <div class="m-chips" id="mQuickChips"></div>
      </section>
      <div id="mBrowseGrid" class="m-grid"></div>
      <div id="mBrowsePager"></div>
      <p id="mBrowseStatus" class="m-status">正在给你找图…</p>`;
    const goSet = document.getElementById("mGoSettings");
    if (goSet) goSet.onclick = openSettings;
    (isStandalone() ? [["online", "在线库"], ["library", "本地库"]] : [["online", "在线库"]]).forEach(([value, label]) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "m-chip" + (state.browseMode === value ? " active" : "");
      chip.textContent = label;
      chip.onclick = () => {
        state.browseMode = value;
        state.searchPage = 1;
        renderBrowse(root);
      };
      document.getElementById("mModeChips").appendChild(chip);
    });
    if (standalone && document.getElementById("mSortChips")) {
      [["new", "最新"], ["popular", "热门"]].forEach(([value, label]) => {
        const chip = document.createElement("button");
        chip.type = "button";
        chip.className = "m-chip" + (state.searchSort === value ? " active" : "");
        chip.textContent = label;
        chip.onclick = () => {
          state.searchSort = value;
          state.searchPage = 1;
          renderBrowse(root);
        };
        document.getElementById("mSortChips").appendChild(chip);
      });
    }
    [["内置样例", "内置样例"], ["明日方舟", "明日方舟"], ["甘雨", "甘雨"], ["初音", "初音"], ["高松灯", "高松灯"], ["丰川祥子", "丰川祥子"], ["能天使", "能天使"]].forEach(([label, q]) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "m-chip";
      chip.textContent = label;
      chip.onclick = () => {
        document.getElementById("mSearch").value = q;
        run();
      };
      document.getElementById("mQuickChips").appendChild(chip);
    });
    const run = async (page) => {
      const q = document.getElementById("mSearch").value.trim();
      state.searchQ = q;
      if (q === "内置样例") {
        location.hash = "#/work/" + encodeURIComponent("demo-ark-amiya");
        return;
      }
      if (page) state.searchPage = page;
      const seq = ++browseSearchSeq;
      const status = document.getElementById("mBrowseStatus");
      status.className = "m-status";
      status.textContent = state.browseMode === "library" ? "读取本地库…" : "正在搜…";
      try {
        await refreshFavIds(false);
        const data = state.browseMode === "library"
          ? await api().get("/api/mobile/library/works?q=" + encodeURIComponent(q))
          : await api().get("/api/nai/aitag/search?q=" + encodeURIComponent(q)
            + "&page=" + state.searchPage + "&page_size=60&nai_only=true&sort=" + encodeURIComponent(state.searchSort || "new"));
        if (seq !== browseSearchSeq) return;
        state.lastSearchMeta = data;
        const items = data.items || data.works || [];
        const grid = document.getElementById("mBrowseGrid");
        grid.innerHTML = items.map((item) => workCardHtml(item)).join("") || "";
        bindFavButtons(grid);
        const offline = !!data.offline_demo;
        status.textContent = items.length
          ? (state.browseMode === "library"
            ? `本地库 ${items.length} 个，点进去选人、看画风，整系列入队`
            : (offline
              ? "在线库暂时打不开，先用内置样例把换角跑通。连上后再搜。"
              : `第 ${state.searchPage} 页 · ${items.length} 个作品，先☆收藏入库`))
          : (state.browseMode === "library" ? "本地库是空的。在线库点☆收藏就会入库。" : "没有结果，换个词再搜");
        if (state.browseMode === "library" && items.some((item) => {
          const save = String(item.save_state || "");
          return save === "pending" || save === "saving";
        })) {
          setTimeout(() => {
            if (state.route && state.route.name === "browse" && state.browseMode === "library") run(state.searchPage);
          }, 2000);
        }
        const pager = document.getElementById("mBrowsePager");
        if (pager) {
          if (state.browseMode !== "library") {
            pager.className = "m-row";
            pager.style.marginTop = "10px";
            pager.innerHTML = `
              <button type="button" class="m-ghost" id="mPrevPage" ${state.searchPage <= 1 ? "disabled" : ""}>上一页</button>
              <button type="button" class="m-ghost" id="mNextPage" ${data.has_more ? "" : "disabled"}>下一页</button>`;
            const prev = document.getElementById("mPrevPage");
            const next = document.getElementById("mNextPage");
            if (prev) prev.onclick = () => run(Math.max(1, state.searchPage - 1));
            if (next) next.onclick = () => run(state.searchPage + 1);
          } else {
            pager.innerHTML = "";
          }
        }
      } catch (error) {
        if (seq !== browseSearchSeq) return;
        status.textContent = friendlyError(error);
        status.className = "m-status m-err";
        const pager = document.getElementById("mBrowsePager");
        if (pager && !document.getElementById("mDemoFallback")) {
          pager.innerHTML = `<a class="m-primary" id="mDemoFallback" href="#/work/${encodeURIComponent("demo-ark-amiya")}">打开内置样例</a>`;
        }
      }
    };
    document.getElementById("mSearchBtn").onclick = () => { state.searchPage = 1; run(1); };
    document.getElementById("mSearch").addEventListener("keydown", (event) => {
      if (event.key === "Enter") { state.searchPage = 1; run(1); }
    });
    document.getElementById("mSearch").addEventListener("input", debounce(() => {
      state.searchPage = 1;
      run(1);
    }, 360));
    if (!document.getElementById("mSearch").value.trim()) {
      document.getElementById("mSearch").value = state.searchQ || "明日方舟";
    }
    run(state.searchPage);
  }

  async function renderWork(root, workId) {
    if (!workId) {
      root.innerHTML = `<section class="m-card">
        <h2>换角</h2>
        <p class="m-hint">${isStandalone() ? "先在「发现」收藏入本地库，再从本地库点进来。" : "先在「发现」里点开一张在线作品。"}</p>
        <div class="m-row" style="margin-top:10px">
          <a class="m-primary" href="#/${isStandalone() ? "library" : "browse"}">${isStandalone() ? "去本地库" : "去发现选图"}</a>
        </div>
      </section>`;
      return;
    }
    state.lastWorkId = workId;
    try { localStorage.setItem(LAST_WORK_KEY, workId); } catch (_) { /* ignore */ }
    root.innerHTML = `<p class="m-status">加载作品…</p>`;
    try {
      await refreshFavIds(false);
      const local = !!(state.route && state.route.local) || workId === "demo-ark-amiya" || !!state.favIds[workId];
      if (isStandalone() && !local) {
        const cached = findSearchItem(workId);
        if (cached) {
          state.work = window.StandaloneCore
            ? window.StandaloneCore.decorateWork({ work: cached, images: cached.images || [], source: "aitag-online" })
            : { work: cached, images: cached.images || [] };
          state.pageIndex = 0;
          paintCollect(root);
          api().get("/api/nai/aitag/work/" + encodeURIComponent(workId)).then((data) => {
            if (!state.route || String(state.route.id || "") !== String(workId)) return;
            state.work = window.StandaloneCore ? window.StandaloneCore.decorateWork(data) : data;
            paintCollect(document.getElementById("mApp"));
          }).catch(() => {});
          return;
        }
        const data = await api().get("/api/nai/aitag/work/" + encodeURIComponent(workId));
        state.work = (window.StandaloneCore) ? window.StandaloneCore.decorateWork(data) : data;
        state.pageIndex = 0;
        return paintCollect(root);
      }
      if (isStandalone() && local && !(state.route && state.route.local) && workId !== "demo-ark-amiya") {
        location.hash = "#/library/" + encodeURIComponent(workId);
        return;
      }
      const data = (isStandalone() && local)
        ? await api().get("/api/mobile/library/work/" + encodeURIComponent(workId))
        : await api().get("/api/nai/aitag/work/" + encodeURIComponent(workId));
      state.work = (isStandalone() && window.StandaloneCore) ? window.StandaloneCore.decorateWork(data) : data;
      state.pageIndex = 0;
      state.slot = (state.work.character_candidates || [])[0] || null;
      state.drafts = restoreDrafts(workId);
      state.slotTargets = restoreSlotTargets(workId);
      paintWork(root);
    } catch (error) {
      root.innerHTML = `<section class="m-card"><h2>换角</h2><p class="m-err">${escapeHtml(friendlyError(error))}</p>
        <div class="m-row"><a class="m-primary" href="#/browse">回发现再选</a></div></section>`;
    }
  }

  function currentImage() {
    const images = (state.work && state.work.images) || [];
    return images[state.pageIndex] || images[0] || {};
  }

  function imageCountOf(item) {
    const work = (item && item.work) || item || {};
    const images = (item && item.images) || work.images || [];
    return Number(work.image_count || item.image_count || images.length || 0);
  }

  function workCardHtml(item) {
    const id = String(item.work_id || item.id || "");
    const cover = (item.images && item.images[0] && (item.images[0].thumbnail_url || item.images[0].url))
      || ("/api/nai/aitag/cover/" + encodeURIComponent(id));
    const count = imageCountOf(item);
    const on = !!state.favIds[id];
    const fav = isStandalone()
      ? `<button type="button" class="m-fav${on ? " on" : ""}" data-fav="${escapeHtml(id)}" aria-label="收藏">${on ? "★" : "☆"}</button>`
      : "";
    const href = (isStandalone() && (state.browseMode === "library" || item.local))
      ? `#/library/${encodeURIComponent(id)}`
      : `#/work/${encodeURIComponent(id)}`;
    const saveState = String(item.save_state || "");
    const saveLabel = saveState === "ready" ? "可换角生成" : saveState === "pending" ? "正在抓咒语" : saveState === "partial" ? "没有咒语" : "";
    return `<div class="m-work-card">
      <a class="m-work" href="${href}">
        <img src="${escapeHtml(cover)}" alt="">
        <em class="m-page-badge">${count}张</em>
        <span>${escapeHtml(item.title || id)}${saveLabel ? " · " + saveLabel : ""}</span>
      </a>
      ${fav}
    </div>`;
  }

  function bindFavButtons(host) {
    if (!host) return;
    host.querySelectorAll("[data-fav]").forEach((button) => {
      button.onclick = (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleFavorite(button.getAttribute("data-fav"), button);
      };
    });
  }

  async function refreshFavIds(force) {
    if (!force && favIdsAt && Date.now() - favIdsAt < 2500) return;
    try {
      const data = await api().get("/api/nai/aitag/favorites");
      const next = {};
      (data.ids || []).forEach((id) => { next[String(id)] = true; });
      state.favIds = next;
      favIdsAt = Date.now();
    } catch (_) { /* ignore */ }
  }

  function findSearchItem(id) {
    const items = (state.lastSearchMeta && (state.lastSearchMeta.items || state.lastSearchMeta.works)) || [];
    return items.find((item) => String(item.work_id || item.id || "") === String(id || "")) || null;
  }

  function captureVisibleJpeg(img) {
    try {
      if (!img || !img.complete || !img.naturalWidth) return "";
      const canvas = document.createElement("canvas");
      const max = 720;
      let width = img.naturalWidth;
      let height = img.naturalHeight;
      if (Math.max(width, height) > max) {
        const scale = max / Math.max(width, height);
        width = Math.max(1, Math.round(width * scale));
        height = Math.max(1, Math.round(height * scale));
      }
      canvas.width = width;
      canvas.height = height;
      canvas.getContext("2d").drawImage(img, 0, 0, width, height);
      return canvas.toDataURL("image/jpeg", 0.78);
    } catch (_) {
      return "";
    }
  }

  function favoriteSnapshot(id, button) {
    const work = (state.work && state.work.work) || {};
    const search = findSearchItem(id) || {};
    const card = button && button.closest ? button.closest(".m-work-card") : null;
    const img = (card && card.querySelector("img")) || document.querySelector("img.m-preview");
    const images = (state.work && state.work.images) || search.images || [];
    const first = images[0] || currentImage() || {};
    return {
      title: work.title || search.title || (card && card.querySelector("span") ? card.querySelector("span").textContent : id),
      creator: work.creator || search.creator || "",
      cover_url: (img && img.getAttribute("src")) || first.thumbnail_url || first.url || "",
      image_count: imageCountOf(state.work || search || work),
      tags: work.tags || search.tags || [],
      images: images,
      work: Object.keys(work).length ? work : search,
      prompt_text: first.prompt_text || "",
      ai_json: first.ai_json || null,
      cover_jpeg: captureVisibleJpeg(img),
    };
  }

  async function toggleFavorite(workId, button) {
    const id = String(workId || "");
    if (!id) return;
    try {
      const snapshot = favoriteSnapshot(id, button);
      const result = await api().post("/api/nai/aitag/favorites/" + encodeURIComponent(id) + "/toggle", snapshot);
      favIdsAt = 0;
      if (result.favorited) state.favIds[id] = true;
      else delete state.favIds[id];
      if (button) {
        button.textContent = result.favorited ? "★" : "☆";
        button.classList.toggle("on", !!result.favorited);
      }
      toast(result.message || (result.favorited ? "已收藏到本机，可去本地库换角" : "已取消收藏"));
      if (isStandalone() && result.favorited && id) {
        const go = document.getElementById("mGoLocal");
        if (go) go.setAttribute("href", "#/library/" + encodeURIComponent(id));
      }
    } catch (error) {
      toast(friendlyError(error), "err");
    }
  }

  function closeCharPicker() {
    const picker = document.getElementById("mPicker");
    if (!picker) return;
    const active = document.activeElement;
    if (active && picker.contains(active) && active.blur) active.blur();
    picker.classList.add("hidden");
    picker.setAttribute("aria-hidden", "true");
    const title = picker.querySelector(".m-sheet-head h3");
    if (title) title.textContent = "换成谁";
  }

  function openCharPicker(options) {
    const opts = options || {};
    const picker = document.getElementById("mPicker");
    const body = document.getElementById("mPickerBody");
    if (!picker || !body) return;
    body.innerHTML = `
      <p class="m-hint">D 站角色库 / 方舟 / OC 都能换。自定义就是 OC：整段咒语，支持 {{权重}}，不会拆开。</p>
      <div class="m-row" id="mSourceRow"></div>
      <div class="m-row" id="mGenderRow"></div>
      <div class="m-row">
        <input id="mTargetQ" placeholder="初音 / 阿米娅 / 原神 / OC 名" value="${escapeHtml(state.targetQuery || "")}" enterkeyhint="search" />
        <button type="button" id="mTargetBtn" class="m-primary">搜角色</button>
      </div>
      <div id="mTargets" class="m-list" style="margin-top:8px"></div>
      <p class="m-hint" id="mTargetHint">${state.targetLabel ? ("已选 " + state.targetLabel) : "先选来源，再搜一个名字"}</p>
      <section class="m-card" id="mCustomBox" style="margin-top:12px">
        <h3>OC / 群友 OC</h3>
        <p class="m-hint">整段咒语原样进槽，只补原槽动作。服饰 / 额外 / 移除也按你写的来，不简化成人设卡片。</p>
        <label class="m-hint" style="display:block;margin-top:10px">
          <input type="checkbox" id="mCustomOcMode" ${state.ocMode === false ? "" : "checked"} /> 整段咒语模式
        </label>
        <div class="m-row" style="margin-top:10px">
          <input id="mCustomName" placeholder="OC 名字，如 香蕉姐" />
        </div>
        <textarea id="mCustomCaption" placeholder="整段角色咒语，例如 1girl, banana_onee_(oc), {{1.2::horns}}, blonde hair" style="margin-top:8px"></textarea>
        <div class="m-row" style="margin-top:8px">
          <input id="mCustomIdentity" placeholder="身份标签（非整段时用），如 banana_onee_(oc)" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mCustomAppear" placeholder="外观（非整段时用），如 blonde_hair, yellow_eyes" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mCustomClothing" placeholder="服饰替换，如 china dress, thighhighs" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mCustomExtra" placeholder="额外添加，如 earrings, necklace" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mCustomRemove" placeholder="移除标签，如 long hair" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mCustomUse" class="m-ghost">用这次不保存</button>
          <button type="button" id="mCustomSave" class="m-primary">保存 OC</button>
        </div>
        <div id="mCustomList" class="m-list" style="margin-top:10px"></div>
      </section>
      <div class="m-quote" style="margin-top:12px">小祥：把一整段 OC 人设或咒语贴下面。已是标签就立刻填好；中文描述才走 DeepSeek 拆栏。这步不扣 Anlas。</div>
      <textarea id="mDescribe" placeholder="整段 OC：1girl, banana_onee_(oc), {{1.2::horns}} … 或中文人设" style="margin-top:8px"></textarea>
      <div class="m-row" style="margin-top:8px">
        <button type="button" id="mDescribeBtn" class="m-ghost">DeepSeek 拆开填好</button>
      </div>`;
    picker.classList.remove("hidden");
    picker.setAttribute("aria-hidden", "false");
    if (opts.custom) state.searchSource = "oc";
    const sourceRow = document.getElementById("mSourceRow");
    [["all", "全部"], ["danbooru", "D站"], ["ark", "方舟"], ["oc", "OC"]].forEach(([value, label]) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "m-chip" + (state.searchSource === value ? " active" : "");
      chip.textContent = label;
      chip.onclick = () => { state.searchSource = value; openCharPicker(); };
      sourceRow.appendChild(chip);
    });
    const genderRow = document.getElementById("mGenderRow");
    [["female", "女角色"], ["male", "男角色"]].forEach(([value, label]) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "m-chip" + (state.targetGender === value ? " active" : "");
      chip.textContent = label;
      chip.onclick = () => { state.targetGender = value; openCharPicker(); };
      genderRow.appendChild(chip);
    });
    document.getElementById("mTargetBtn").onclick = searchTargets;
    const targetBox = document.getElementById("mTargetQ");
    if (targetBox) {
      targetBox.addEventListener("keydown", (event) => {
        if (event.key === "Enter") searchTargets();
      });
      targetBox.addEventListener("input", debounce(searchTargets, 280));
    }
    const ocModeBox = document.getElementById("mCustomOcMode");
    if (ocModeBox) ocModeBox.onchange = () => { state.ocMode = !!ocModeBox.checked; };
    document.getElementById("mCustomUse").onclick = () => useCustomRecord(false);
    document.getElementById("mCustomSave").onclick = () => useCustomRecord(true);
    document.getElementById("mDescribeBtn").onclick = describeWithDeepSeek;
    searchTargets();
    refreshCustomList();
    if (opts.custom) {
      const box = document.getElementById("mCustomBox");
      const name = document.getElementById("mCustomName");
      if (box && box.scrollIntoView) box.scrollIntoView({ block: "start" });
      if (name) name.focus();
    }
  }

  async function refreshCustomList() {
    const host = document.getElementById("mCustomList");
    if (!host) return;
    const items = await listCustom(state.targetGender);
    host.innerHTML = items.length
      ? items.map((item) => `<div class="m-item"><div><strong>${escapeHtml(item.label || item.id)}</strong></div><div class="m-row"><button type="button" class="m-primary" data-use-custom="${escapeHtml(item.id)}">用这个 OC</button><button type="button" class="m-ghost" data-del-custom="${escapeHtml(item.id)}">删除</button></div></div>`).join("")
      : '<p class="m-hint">还没有已保存的 OC</p>';
    host.querySelectorAll("[data-use-custom]").forEach((button) => {
      button.onclick = () => {
        const id = button.getAttribute("data-use-custom");
        const item = items.find((row) => String(row.id) === String(id));
        if (!item) return;
        pickTarget({
          reference_id: "custom:" + (item.gender || state.targetGender) + ":" + item.id,
          label: "OC：" + (item.label || item.id),
          record: Object.assign({ kind: "oc" }, item),
        });
        toast("已选 OC：" + (item.label || item.id));
      };
    });
    host.querySelectorAll("[data-del-custom]").forEach((button) => {
      button.onclick = async () => {
        const id = button.getAttribute("data-del-custom");
        if (!await confirmAction("删除 OC", "只删本机保存的这条，不会出图。")) return;
        try {
          if (isStandalone()) await api().post("/api/plugin/char-swap/custom/delete", { id: id });
          else {
            const next = loadLocalCustom().filter((item) => String(item.id) !== String(id));
            try { localStorage.setItem("nai-mobile-custom-chars", JSON.stringify(next)); } catch (_) { /* ignore */ }
          }
          toast("已删除");
          refreshCustomList();
          searchTargets();
        } catch (error) {
          toast(error.message || String(error), "err");
        }
      };
    });
  }

  function currentDraftEntry() {
    return state.drafts[String(state.pageIndex)] || null;
  }

  function recognizedStylesFor(image, work) {
    if (!(window.StandaloneCore && window.StandaloneCore.recognizeStyles)) {
      return { tokens: [], labels: [], text: "", label_text: "" };
    }
    const extra = work && Array.isArray(work.tags) ? { tags: work.tags } : {};
    if (window.StandaloneCore.imageComment) {
      return window.StandaloneCore.recognizeStyles(Object.assign({}, window.StandaloneCore.imageComment(image || {}), extra));
    }
    return window.StandaloneCore.recognizeStyles(image || extra);
  }

  function recognizedWorkStyles() {
    if (window.StandaloneCore && window.StandaloneCore.recognizeWorkStyles) {
      return window.StandaloneCore.recognizeWorkStyles(state.work || {});
    }
    return { tokens: [], labels: [], text: "", label_text: "", pages: [] };
  }

  function styleSummaryText(rec) {
    if (!rec) return "";
    if (rec.label_text && rec.text && rec.label_text !== rec.text) return rec.label_text + "（" + rec.text + "）";
    return rec.label_text || rec.text || "";
  }

  function draftPreviewHtml(entry) {
    const comment = draftComment(entry);
    if (!comment) return '<p class="m-hint">还没有本页草稿。可先点「本页换角」，或「整系列换角并入队」。</p>';
    const snap = (window.StandaloneCore && window.StandaloneCore.promptSnapshot)
      ? window.StandaloneCore.promptSnapshot(comment)
      : { prompt: comment.prompt || "", uc: comment.uc || comment.negative_prompt || "", char_captions: [] };
    const slots = Array.isArray(snap.char_captions) ? snap.char_captions : [];
    const prompt = String(snap.base_caption || snap.prompt || comment.prompt || "");
    const uc = String(comment.uc || comment.negative_prompt || snap.uc || "");
    const seed = comment.seed == null ? "" : String(comment.seed);
    const steps = comment.steps == null ? "" : String(comment.steps);
    return `<div class="m-draft" id="mDraftPreview">
      <p><strong>草稿预览</strong> · 还没扣 Anlas</p>
      <p class="m-meta">底栏：${escapeHtml(prompt.slice(0, 280))}</p>
      ${slots.map((slot, index) => {
        const text = slot && typeof slot === "object" ? (slot.caption || slot.char_caption || "") : slot;
        return `<p class="m-meta">槽${index + 1}：${escapeHtml(String(text || "").slice(0, 180))}</p>`;
      }).join("")}
      <p class="m-meta">负面：${escapeHtml(uc.slice(0, 160))}</p>
      ${state.styleLabel ? `<p class="m-meta">画风：${escapeHtml(state.styleLabel)}</p>` : ""}
      <details class="m-adv">
        <summary>手改草稿</summary>
        <textarea id="mDraftPrompt" placeholder="底栏咒语">${escapeHtml(prompt)}</textarea>
        <textarea id="mDraftUc" placeholder="负面咒语">${escapeHtml(uc)}</textarea>
        <div class="m-row" style="margin-top:8px">
          <input id="mDraftSeed" inputmode="numeric" placeholder="seed，空=随机" value="${escapeHtml(seed)}" />
          <input id="mDraftSteps" inputmode="numeric" placeholder="步数 1-28" value="${escapeHtml(steps)}" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mSaveDraft" class="m-ghost">保存手改</button>
        </div>
      </details>
    </div>`;
  }

  function paintCollect(root) {
    const work = (state.work && state.work.work) || {};
    const img = currentImage();
    const workId = String(work.work_id || work.id || "");
    const cover = img.thumbnail_url || img.url || ("/api/nai/aitag/cover/" + encodeURIComponent(workId));
    const pageCount = imageCountOf(state.work);
    const tags = Array.isArray(work.tags) ? work.tags.map((tag) => String(tag || "")).filter(Boolean).slice(0, 8) : [];
    root.innerHTML = `
      <section class="m-card">
        <p class="m-eyebrow">发现 · 先收藏</p>
        <h2>${escapeHtml(work.title || workId || "作品")}</h2>
        <img class="m-preview" src="${escapeHtml(cover)}" alt="">
        <p class="m-hint">${pageCount}张${work.creator ? " · " + escapeHtml(work.creator) : ""}</p>
        ${tags.length ? `<p class="m-meta">标签：${escapeHtml(tags.join(" / "))}</p>` : ""}
        <p class="m-hint">代理不稳时，在线页不能直接换角。点☆收藏入本地库后，咒语和图都留在手机，再换角色和生成。</p>
        <div class="m-row" style="margin-top:10px">
          <button type="button" class="m-primary" data-fav="${escapeHtml(workId)}" aria-label="收藏">收藏入本地库</button>
          <a class="m-ghost" id="mGoLocal" href="#/library">去本地库</a>
        </div>
        <p class="m-status">先收藏入本地库，才能换角和生成</p>
      </section>`;
    bindFavButtons(root);
  }

  function paintWork(root) {
    const work = (state.work && state.work.work) || {};
    const images = state.work.images || [];
    const img = currentImage();
    const candidates = (state.work.character_candidates || []).filter((item) => Number(item.image_index || 0) === state.pageIndex);
    const cover = img.thumbnail_url || img.url || ("/api/nai/aitag/cover/" + encodeURIComponent(work.work_id || ""));
    const workId = String(work.work_id || work.id || "");
    const favOn = !!state.favIds[workId];
    const pageCount = imageCountOf(state.work);
    const comment = (window.StandaloneCore && window.StandaloneCore.imageComment)
      ? window.StandaloneCore.imageComment(img)
      : {};
    const promptText = String((comment && (comment.prompt || (comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.base_caption))) || img.prompt_text || "").trim();
    const tags = Array.isArray(work.tags) ? work.tags.map((tag) => String(tag || "")).filter(Boolean).slice(0, 8) : [];
    const saveState = String((state.work && state.work.save_state) || "");
    const canRemix = remixReady();
    const pageStyle = recognizedStylesFor(img, work);
    const seriesStyle = recognizedWorkStyles();
    const pageStyleText = styleSummaryText(pageStyle);
    const seriesStyleText = styleSummaryText(seriesStyle);
    const styleReplaceText = state.styleLabel
      ? ("将替换为 " + state.styleLabel)
      : "不换画风就保持原图识别到的词";
    root.innerHTML = `
      <section class="m-card">
        <p class="m-eyebrow">第 1 步 · 看图</p>
        <div class="m-target-row">
          <h2>${escapeHtml(work.title || work.work_id || "作品")}</h2>
          ${isStandalone() ? `<button type="button" class="m-fav${favOn ? " on" : ""}" data-fav="${escapeHtml(workId)}" aria-label="收藏">${favOn ? "★" : "☆"}</button>` : ""}
        </div>
        <img class="m-preview" src="${escapeHtml(cover)}" alt="">
        <p class="m-hint">${pageCount}张 · ${images.length} 页已加载${work.creator ? " · " + escapeHtml(work.creator) : ""}${work.ai_type ? " · " + escapeHtml(work.ai_type) : ""}${saveState === "pending" || saveState === "saving" ? " · 正在抓咒语" : saveState === "partial" && !canRemix ? " · 没有咒语" : canRemix ? " · 可换角生成" : ""}</p>
        ${tags.length ? `<p class="m-meta">标签：${escapeHtml(tags.join(" / "))}</p>` : ""}
        ${promptText
          ? `<p class="m-meta">原图咒语：${escapeHtml(promptText.slice(0, 220))}</p>`
          : `<p class="m-err">这页没有 NovelAI 咒语，不能换角。换一页或换一张图。</p>`}
        <p class="m-meta" id="mPageStyle">原图画风：${pageStyleText ? escapeHtml(pageStyleText) : "这页没识别到画风词"}</p>
        ${pageCount > 1
          ? `<p class="m-meta" id="mSeriesStyle">整系列画风：${seriesStyleText ? escapeHtml(seriesStyleText) : "各页都没识别到画风词"}</p>`
          : ""}
        <div class="m-row" id="mPages"></div>
      </section>
      <section class="m-card">
        <p class="m-eyebrow">第 2 步 · 选人</p>
        <h3>角色槽</h3>
        <div class="m-row" id="mSlots"></div>
        <p class="m-hint" id="mSlotHint">还没选槽</p>
        <p class="m-hint" id="mTargetHint" style="margin-top:8px">${state.targetLabel ? ("已选 " + state.targetLabel) : "D 站 / 方舟 / OC 都能换。OC 就是群友整段咒语。"}</p>
        <div class="m-row">
          <button type="button" id="mOpenPicker" class="m-primary">点开搜索</button>
          <button type="button" id="mOpenCustom" class="m-ghost">写 OC</button>
        </div>
        <div id="mSlotAssign" style="margin-top:10px"></div>
      </section>
      <section class="m-card">
        <p class="m-eyebrow">第 3 步 · 看/换画风</p>
        <p class="m-meta">原图画风：${pageStyleText ? escapeHtml(pageStyleText) : "这页没识别到画风词"}</p>
        <p class="m-hint" id="mStyleHint">${escapeHtml(styleReplaceText)}</p>
        <div class="m-row">
          <button type="button" id="mOpenStyle" class="m-primary">选画风</button>
          <button type="button" id="mApplyStyleAll" class="m-ghost" ${canRemix ? "" : "disabled"}>整系列换画风</button>
        </div>
        <p class="m-hint">选完会先清掉原图识别到的画风词，再写上新的。只换画风也可以，不必先换人。</p>
      </section>
      <section class="m-card">
        <p class="m-eyebrow">第 4 步 · 换角方式</p>
        <p class="m-hint">${canRemix
          ? ("下面每种换法都直接可用，没有收进折叠。已草稿 "
            + Object.keys(state.drafts || {}).length + "/" + pageCount + " 页。")
          : remixBlockReason()}</p>
        <div class="m-row" style="margin-top:8px">
          <input id="mCopies" inputmode="numeric" value="${escapeHtml(String(state.copies || 1))}" placeholder="每页张数 1-8" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mRemixSeries" class="m-primary m-cta" ${canRemix ? "" : "disabled"}>整系列换角并入队</button>
        </div>
        <p class="m-hint">把这 ${pageCount} 页都换成选好的人/画风并入队。还没扣费前会再确认。</p>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mApplyOne" class="m-ghost" ${canRemix ? "" : "disabled"}>本页换角</button>
          <button type="button" id="mApplyPageGender" class="m-ghost" ${canRemix ? "" : "disabled"}>本页全部女槽</button>
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mApplySlots" class="m-ghost" ${canRemix ? "" : "disabled"}>按槽位换本页</button>
          <button type="button" id="mApplyAll" class="m-ghost" ${canRemix ? "" : "disabled"}>全部页换同性别</button>
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mApplySlotsAll" class="m-ghost" ${canRemix ? "" : "disabled"}>全部页按槽位换</button>
          <button type="button" id="mOptimize" class="m-ghost">DeepSeek 优化草稿</button>
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mGenOne" class="m-ghost">加入队列</button>
          ${isStandalone()
            ? `<button type="button" id="mGenSeries" class="m-ghost">全部页加入队列</button>`
            : `<button type="button" id="mQueueBtn" class="m-ghost">加入批量</button>`}
        </div>
        <p class="m-hint" style="margin-top:12px">附加咒语（这次换角才用，不改原图）</p>
        <div class="m-row" style="margin-top:8px">
          <input id="mClothing" placeholder="服饰替换，如 china dress" value="${escapeHtml(state.clothing || "")}" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mExtra" placeholder="额外添加，如 earrings" value="${escapeHtml(state.extraTags || "")}" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mRemove" placeholder="移除标签，如 long hair" value="${escapeHtml(state.removeTags || "")}" />
        </div>
        ${draftPreviewHtml(currentDraftEntry())}
        <p id="mWorkStatus" class="m-status"></p>
        <img id="mGenImg" class="m-preview hidden" alt="生成结果">
      </section>`;
    const pages = document.getElementById("mPages");
    images.forEach((_, index) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "m-chip" + (index === state.pageIndex ? " active" : "");
      chip.textContent = "P" + (index + 1) + (state.drafts[String(index)] ? "✓" : "");
      chip.onclick = () => { state.pageIndex = index; paintWork(root); };
      pages.appendChild(chip);
    });
    const slots = document.getElementById("mSlots");
    if (!candidates.length) {
      slots.innerHTML = '<span class="m-hint">这页没有识别到角色槽</span>';
    }
    if (state.slot && Number(state.slot.image_index) !== state.pageIndex) state.slot = null;
    if (!state.slot && candidates.length) {
      state.slot = candidates.find((item) => item.replaceable) || candidates[0];
      if (state.slot.role === "male" || state.slot.role === "female") state.targetGender = state.slot.role;
    }
    candidates.forEach((item) => {
      const chip = document.createElement("button");
      chip.type = "button";
      const id = String(item.candidate_id || "");
      chip.className = "m-chip" + (state.slot && String(state.slot.candidate_id) === id ? " active" : "");
      const genderLabel = item.role === "male" ? "男" : item.role === "female" ? "女" : "未判";
      chip.textContent = (item.label || ("槽" + (Number(item.slot_index || 0) + 1))) + " · " + genderLabel + " · 槽" + (Number(item.slot_index || 0) + 1);
      chip.onclick = () => {
        state.slot = item;
        if (item.role === "male" || item.role === "female") state.targetGender = item.role;
        paintWork(root);
      };
      slots.appendChild(chip);
    });
    const hint = document.getElementById("mSlotHint");
    if (state.slot) {
      hint.textContent = (state.slot.label || "角色") + " · 槽 " + (Number(state.slot.slot_index || 0) + 1) + " · " + String(state.slot.caption || "").slice(0, 80);
    }
    const openPicker = document.getElementById("mOpenPicker");
    if (openPicker) openPicker.onclick = openCharPicker;
    const openCustom = document.getElementById("mOpenCustom");
    if (openCustom) openCustom.onclick = () => openCharPicker({ custom: true });
    const openStyle = document.getElementById("mOpenStyle");
    if (openStyle) openStyle.onclick = openStylePicker;
    bindFavButtons(root);
    paintSlotAssign(root, candidates);
    document.getElementById("mOptimize").onclick = optimizeCurrentDraft;
    document.getElementById("mApplyOne").onclick = () => applyDraft({ allPages: false, genderScope: "" });
    const pageGender = document.getElementById("mApplyPageGender");
    if (pageGender) {
      const role = (state.slot && state.slot.role === "male") ? "male" : "female";
      pageGender.textContent = role === "male" ? "本页全部男槽" : "本页全部女槽";
      pageGender.onclick = () => applyDraft({ allPages: false, genderScope: role });
    }
    document.getElementById("mApplyAll").onclick = () => applyDraft({
      allPages: true,
      genderScope: (state.slot && state.slot.role === "male") ? "male" : "female",
    });
    const applySlots = document.getElementById("mApplySlots");
    if (applySlots) applySlots.onclick = () => applyDraft({ allPages: false, useSlotTargets: true });
    const applySlotsAll = document.getElementById("mApplySlotsAll");
    if (applySlotsAll) applySlotsAll.onclick = () => applyDraft({ allPages: true, useSlotTargets: true });
    document.getElementById("mGenOne").onclick = generateCurrent;
    const genSeries = document.getElementById("mGenSeries");
    if (genSeries) genSeries.onclick = () => enqueueSeries({});
    const remixSeries = document.getElementById("mRemixSeries");
    if (remixSeries) remixSeries.onclick = remixSeriesAndEnqueue;
    const applyStyleAll = document.getElementById("mApplyStyleAll");
    if (applyStyleAll) applyStyleAll.onclick = applyStyleSeries;
    ["mClothing", "mExtra", "mRemove"].forEach((id) => {
      const box = document.getElementById(id);
      if (!box) return;
      box.addEventListener("input", readRemixLayers);
    });
    const queueBtn = document.getElementById("mQueueBtn");
    if (queueBtn) queueBtn.onclick = enqueueCurrent;
    const saveDraft = document.getElementById("mSaveDraft");
    if (saveDraft) saveDraft.onclick = saveDraftEdits;
    if (isStandalone() && !canRemix && (saveState === "pending" || saveState === "saving") && workId) {
      setTimeout(() => {
        if (state.route && state.route.name === "work" && String(state.route.id || "") === workId) {
          renderWork(document.getElementById("mApp"), workId);
        }
      }, 1600);
    }
  }

  function saveDraftEdits() {
    const entry = currentDraftEntry();
    const comment = draftComment(entry);
    if (!comment) {
      toast("先做本页换角草稿", "err");
      return;
    }
    const promptEl = document.getElementById("mDraftPrompt");
    const ucEl = document.getElementById("mDraftUc");
    const seedEl = document.getElementById("mDraftSeed");
    const stepsEl = document.getElementById("mDraftSteps");
    const next = (window.StandaloneCore && window.StandaloneCore.applyDraftEdits)
      ? window.StandaloneCore.applyDraftEdits(comment, {
        prompt: promptEl ? promptEl.value : comment.prompt,
        uc: ucEl ? ucEl.value : (comment.uc || comment.negative_prompt || ""),
        seed: seedEl ? seedEl.value : comment.seed,
        steps: stepsEl ? stepsEl.value : comment.steps,
      })
      : comment;
    if (entry.draft) entry.draft.comment = next;
    else entry.comment = next;
    const workId = String((state.work && state.work.work && (state.work.work.work_id || state.work.work.id)) || "");
    persistDrafts(workId);
    toast("手改草稿已保存");
    paintWork(document.getElementById("mApp"));
  }

  function openStylePicker() {
    const picker = document.getElementById("mPicker");
    const body = document.getElementById("mPickerBody");
    if (!picker || !body) return;
    const title = picker.querySelector(".m-sheet-head h3");
    if (title) title.textContent = "画风";
    body.innerHTML = `
      <p class="m-hint">选内置画风，或保存自己的画风串。应用时会先清掉原图识别到的画风词。</p>
      <div class="m-row">
        <input id="mStyleQ" placeholder="水彩 / 官方 / 赛璐璐" enterkeyhint="search" />
        <button type="button" id="mStyleBtn" class="m-primary">搜画风</button>
      </div>
      <div id="mStyles" class="m-list" style="margin-top:8px"></div>
      <details class="m-adv">
        <summary>保存自定义画风</summary>
        <div class="m-row" style="margin-top:10px">
          <input id="mStyleName" placeholder="画风名，如 Granblue" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mStyleTag" placeholder="画风标签，如 watercolor, official art" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mStyleSave" class="m-primary">保存画风</button>
        </div>
      </details>`;
    picker.classList.remove("hidden");
    picker.setAttribute("aria-hidden", "false");
    const search = async () => {
      const host = document.getElementById("mStyles");
      const q = document.getElementById("mStyleQ") ? document.getElementById("mStyleQ").value.trim() : "";
      if (!host) return;
      const seq = ++styleSearchSeq;
      host.textContent = "正在搜…";
      try {
        const data = await api().get("/api/plugin/char-swap/styles?q=" + encodeURIComponent(q) + "&limit=40");
        if (seq !== styleSearchSeq) return;
        const items = data.items || [];
        host.innerHTML = "";
        items.forEach((item) => {
          const row = document.createElement("button");
          row.type = "button";
          row.className = "m-chip" + (state.styleId === item.reference_id ? " active" : "");
          row.textContent = (item.source ? item.source + " · " : "") + (item.label || item.reference_id);
          row.onclick = () => {
            state.styleId = item.reference_id;
            state.styleLabel = item.label;
            state.styleRecord = item.record || item;
            const hint = document.getElementById("mStyleHint");
            if (hint) hint.textContent = "将替换为 " + item.label;
            closeCharPicker();
            const sheetTitle = document.querySelector("#mPicker .m-sheet-head h3");
            if (sheetTitle) sheetTitle.textContent = "换成谁";
          };
          host.appendChild(row);
        });
        if (!items.length) host.innerHTML = '<p class="m-hint">没有匹配画风，可在下方保存自定义</p>';
      } catch (error) {
        if (seq !== styleSearchSeq) return;
        host.innerHTML = '<p class="m-err">' + escapeHtml(error.message || error) + "</p>";
      }
    };
    document.getElementById("mStyleBtn").onclick = search;
    const styleBox = document.getElementById("mStyleQ");
    if (styleBox) {
      styleBox.addEventListener("keydown", (event) => {
        if (event.key === "Enter") search();
      });
      styleBox.addEventListener("input", debounce(search, 280));
    }
    document.getElementById("mStyleSave").onclick = async () => {
      try {
        const label = document.getElementById("mStyleName").value.trim();
        const tag = document.getElementById("mStyleTag").value.trim();
        const saved = await api().post("/api/plugin/char-swap/styles", { label: label, tag: tag });
        state.styleId = "custom-style:" + ((saved.item && saved.item.id) || "");
        state.styleLabel = label;
        state.styleRecord = saved.item || { label: label, tag: tag, kind: "style" };
        toast(saved.message || "已保存自定义画风");
        closeCharPicker();
        const sheetTitle = document.querySelector("#mPicker .m-sheet-head h3");
        if (sheetTitle) sheetTitle.textContent = "换成谁";
      } catch (error) {
        toast(error.message || String(error), "err");
      }
    };
    search();
  }

  function pickTarget(item) {
    state.targetId = item.reference_id;
    state.targetLabel = item.label;
    state.targetRecord = (window.StandaloneCore && item.record)
      ? window.StandaloneCore.targetRecord(item.record, item.reference_id)
      : item.record || null;
    rememberSlotTarget();
    const hint = document.getElementById("mTargetHint");
    if (hint) hint.textContent = "已选 " + item.label;
    closeCharPicker();
    const app = document.getElementById("mApp");
    if (app && state.route && state.route.name === "work") paintWork(app);
  }

  function rememberSlotTarget() {
    if (!state.slot || !state.targetRecord) return;
    const candidates = (state.work && state.work.character_candidates) || [];
    const idx = window.StandaloneCore && window.StandaloneCore.genderSlotIndexOf
      ? window.StandaloneCore.genderSlotIndexOf(candidates, state.slot)
      : -1;
    const role = state.slot.role === "male" ? "male" : (state.slot.role === "female" ? "female" : "");
    if (idx < 0 || !role) return;
    state.slotTargets[role + ":" + idx] = {
      gender: role,
      gender_slot_index: idx,
      slot_index: Number(state.slot.slot_index || 0),
      candidate_id: state.slot.candidate_id,
      targetId: state.targetId,
      targetLabel: state.targetLabel,
      targetRecord: state.targetRecord,
    };
    const workId = String((state.work && state.work.work && (state.work.work.work_id || state.work.work.id)) || "");
    persistDrafts(workId);
  }

  function collectSlotTargets(gender) {
    const role = gender === "male" ? "male" : "female";
    return Object.keys(state.slotTargets || {})
      .filter((key) => key.indexOf(role + ":") === 0)
      .map((key) => state.slotTargets[key])
      .filter((item) => item && item.targetRecord)
      .map((item) => ({
        gender: item.gender || role,
        gender_slot_index: item.gender_slot_index,
        slot_index: item.slot_index,
        target_record: item.targetRecord,
        target_reference_id: item.targetId,
      }));
  }

  function paintSlotAssign(root, candidates) {
    const host = document.getElementById("mSlotAssign");
    if (!host) return;
    const page = (candidates || []).filter((item) => Number(item.image_index) === Number(state.pageIndex));
    const females = page.filter((item) => item.role === "female");
    const males = page.filter((item) => item.role === "male");
    const rows = females.length >= 2 ? females : (males.length >= 2 ? males : []);
    if (!rows.length) {
      host.innerHTML = "";
      return;
    }
    const role = rows[0].role === "male" ? "male" : "female";
    host.innerHTML = `<p class="m-hint">这页有 ${rows.length} 个${role === "male" ? "男" : "女"}槽。每个槽选不同人后，点「整系列换角并入队」。</p>`;
    rows.forEach((item, index) => {
      const assigned = state.slotTargets[role + ":" + index];
      const row = document.createElement("div");
      row.className = "m-row";
      row.style.marginTop = "8px";
      row.innerHTML = `<button type="button" class="m-ghost" data-assign-slot="${index}">${role === "male" ? "男" : "女"}槽${index + 1} · ${escapeHtml(item.label || ("槽" + (Number(item.slot_index) + 1)))} → ${assigned && assigned.targetLabel ? escapeHtml(assigned.targetLabel) : "还没选"}</button>`;
      host.appendChild(row);
      const btn = row.querySelector("[data-assign-slot]");
      if (btn) {
        btn.onclick = () => {
          state.slot = item;
          state.targetGender = role;
          if (assigned) {
            state.targetId = assigned.targetId;
            state.targetLabel = assigned.targetLabel;
            state.targetRecord = assigned.targetRecord;
          }
          openCharPicker();
        };
      }
    });
  }

  function readRemixLayers() {
    const clothing = document.getElementById("mClothing");
    const extra = document.getElementById("mExtra");
    const remove = document.getElementById("mRemove");
    if (clothing) state.clothing = clothing.value.trim();
    if (extra) state.extraTags = extra.value.trim();
    if (remove) state.removeTags = remove.value.trim();
    return {
      clothing: state.clothing || "",
      extra_tags: state.extraTags || "",
      remove_tags: state.removeTags || "",
    };
  }

  function customDraftFromForm() {
    const name = (document.getElementById("mCustomName") && document.getElementById("mCustomName").value.trim())
      || (document.getElementById("mTargetQ") && document.getElementById("mTargetQ").value.trim());
    if (!name) throw new Error("先写 OC 名字");
    const ocMode = !document.getElementById("mCustomOcMode") || document.getElementById("mCustomOcMode").checked;
    state.ocMode = ocMode;
    const identityRaw = document.getElementById("mCustomIdentity") ? document.getElementById("mCustomIdentity").value : "";
    const appearRaw = document.getElementById("mCustomAppear") ? document.getElementById("mCustomAppear").value : "";
    const caption = document.getElementById("mCustomCaption") ? document.getElementById("mCustomCaption").value.trim() : "";
    const clothing = document.getElementById("mCustomClothing") ? document.getElementById("mCustomClothing").value.trim() : "";
    const extra = document.getElementById("mCustomExtra") ? document.getElementById("mCustomExtra").value.trim() : "";
    const remove = document.getElementById("mCustomRemove") ? document.getElementById("mCustomRemove").value.trim() : "";
    if (ocMode && !caption) throw new Error("群友 OC 请填写整段角色咒语");
    const identity = String(identityRaw || "").split(",").map((item) => item.trim()).filter(Boolean);
    if (!identity.length) identity.push(name);
    const appearance = String(appearRaw || "").split(",").map((item) => item.trim()).filter(Boolean);
    return {
      id: "typed",
      label: name,
      gender: state.targetGender === "male" ? "male" : "female",
      kind: "oc",
      oc_mode: ocMode,
      identity: identity,
      appearance: appearance,
      char_caption: caption,
      clothing: clothing,
      extra: extra,
      extra_tags: extra,
      remove: remove,
      remove_tags: remove,
      tag: identity[0] || name,
    };
  }

  async function useCustomRecord(save) {
    try {
      let record = customDraftFromForm();
      let referenceId = "custom:" + record.gender + ":typed";
      if (save) {
        if (isStandalone()) {
          const saved = await api().post("/api/plugin/char-swap/custom", record);
          record = saved.item || record;
          referenceId = "custom:" + record.gender + ":" + record.id;
          toast(saved.message || "已保存 OC");
        } else {
          const all = loadLocalCustom();
          record.id = "c" + Date.now();
          all.unshift(record);
          try { localStorage.setItem("nai-mobile-custom-chars", JSON.stringify(all.slice(0, 80))); } catch (_) { /* ignore */ }
          referenceId = "custom:" + record.gender + ":" + record.id;
          toast("已保存 OC");
        }
      }
      pickTarget({ reference_id: referenceId, label: "OC：" + record.label, record: record });
      searchTargets();
    } catch (error) {
      toast(error.message || String(error), "err");
    }
  }

  function loadLocalCustom() {
    try {
      const raw = JSON.parse(localStorage.getItem("nai-mobile-custom-chars") || "[]");
      return Array.isArray(raw) ? raw : [];
    } catch (_) {
      return [];
    }
  }

  async function listCustom(gender) {
    if (isStandalone()) {
      try {
        const data = await api().get("/api/plugin/char-swap/custom?gender=" + encodeURIComponent(gender));
        return data.items || [];
      } catch (_) { /* fall through */ }
    }
    return loadLocalCustom().filter((item) => !gender || item.gender === gender);
  }

  function fillOcForm(record) {
    if (!record) return;
    if (document.getElementById("mCustomName")) document.getElementById("mCustomName").value = record.label || "";
    if (document.getElementById("mCustomIdentity")) document.getElementById("mCustomIdentity").value = (record.identity || []).join(", ");
    if (document.getElementById("mCustomAppear")) document.getElementById("mCustomAppear").value = (record.appearance || []).join(", ");
    if (document.getElementById("mCustomCaption")) document.getElementById("mCustomCaption").value = record.char_caption || "";
    if (document.getElementById("mCustomClothing")) document.getElementById("mCustomClothing").value = record.clothing || "";
    if (document.getElementById("mCustomExtra")) document.getElementById("mCustomExtra").value = record.extra || record.extra_tags || "";
    if (document.getElementById("mCustomRemove")) document.getElementById("mCustomRemove").value = record.remove || record.remove_tags || "";
    const ocMode = document.getElementById("mCustomOcMode");
    if (ocMode) {
      ocMode.checked = record.oc_mode !== false;
      state.ocMode = ocMode.checked;
    }
  }

  function classifyOcLocal(text, gender) {
    const compact = String(text || "").trim();
    if (!compact) return null;
    const parts = compact.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean);
    const latin = parts.filter((item) => /[A-Za-z_{}:]/.test(item)).length;
    if (parts.length < 3 || latin < 2) return null;
    const namePart = parts.find((item) => /\(oc\)|_\(oc\)/i.test(item)) || parts.find((item) => /_\(/i.test(item)) || parts[0];
    return {
      id: "typed",
      label: String(namePart || "OC").replace(/[_(),]/g, " ").trim().slice(0, 40) || "OC",
      gender: gender,
      kind: "oc",
      oc_mode: true,
      identity: parts.filter((item) => /1girl|1boy|\(oc\)|_\(/i.test(item)).slice(0, 8),
      appearance: parts.filter((item) => /hair|eyes|skin|ears|horns|tail|bangs/i.test(item)).slice(0, 12),
      clothing: parts.filter((item) => /dress|shirt|skirt|jacket|uniform|thigh|coat|shoes|boots/i.test(item)).join(", "),
      extra: "",
      remove: "",
      char_caption: parts.join(", "),
      tag: namePart,
    };
  }

  async function describeWithDeepSeek() {
    const box = document.getElementById("mDescribe");
    const text = box ? box.value.trim() : "";
    if (!text) {
      toast("先把一整段 OC 贴进来", "err");
      return;
    }
    const status = document.getElementById("mWorkStatus");
    const local = classifyOcLocal(text, state.targetGender);
    if (local) {
      fillOcForm(local);
      pickTarget({
        reference_id: "custom:" + (local.gender || state.targetGender) + ":typed",
        label: "OC：" + local.label,
        record: local,
      });
      toast("已按整段咒语填好各栏");
    }
    const hasHan = /[\u4e00-\u9fff]/.test(text);
    if (local && !hasHan) return;
    try {
      const ai = await api().get("/api/ai/status");
      if (!ai.has_api_key && !ai.has_deepseek) {
        if (!local) {
          toast("这串不像现成标签。先在设置里填 DeepSeek，才能自动拆栏。", "err");
          if (isStandalone()) openSettings();
        }
        return;
      }
      if (status) status.textContent = "DeepSeek 正在拆 OC…";
      const result = await api().post("/api/mobile/char-describe", {
        text: text,
        gender: state.targetGender,
      });
      if (!result || Number(result.generation_calls) !== 0) {
        throw new Error("角色草稿未通过零生成安全检查");
      }
      const record = result.item || result.record;
      if (!record) throw new Error(result.detail || "DeepSeek 没有返回角色");
      fillOcForm(record);
      pickTarget({
        reference_id: "custom:" + (record.gender || state.targetGender) + ":typed",
        label: "DeepSeek OC：" + (record.label || "OC"),
        record: record,
      });
      if (status) {
        status.textContent = result.message || "OC 各栏已填好，还没扣 Anlas";
        status.className = "m-status m-ok";
      }
    } catch (error) {
      if (!local) toast(error.message || String(error), "err");
    }
  }

  async function optimizeCurrentDraft() {
    const entry = state.drafts[String(state.pageIndex)];
    const comment = draftComment(entry);
    if (!comment) {
      toast("先做本页换角草稿", "err");
      return;
    }
    const status = document.getElementById("mWorkStatus");
    try {
      const ai = await api().get("/api/ai/status");
      if (!ai.has_api_key && !ai.has_deepseek) {
        toast("先在设置里填 DeepSeek Key", "err");
        if (isStandalone()) openSettings();
        return;
      }
      if (status) status.textContent = "DeepSeek 正在优化咒语…";
      const result = await api().post("/api/studio/optimize", { comment: comment, mode: "smart" });
      if (!result || Number(result.generation_calls) !== 0) {
        throw new Error("优化未通过零生成安全检查");
      }
      const next = result.comment
        || (window.StandaloneCore && window.StandaloneCore.applyOptimizeTexts
          ? window.StandaloneCore.applyOptimizeTexts(comment, result.texts || {})
          : comment);
      if (entry.draft) entry.draft.comment = next;
      else entry.comment = next;
      if (status) {
        status.textContent = result.notes || "草稿已优化，还没扣 Anlas";
        status.className = "m-status m-ok";
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message || String(error);
        status.className = "m-status m-err";
      } else {
        toast(error.message || String(error), "err");
      }
    }
  }

  async function searchTargets() {
    const qEl = document.getElementById("mTargetQ");
    const host = document.getElementById("mTargets");
    if (!host) return;
    const q = qEl ? qEl.value.trim() : "";
    state.targetQuery = q;
    const gender = state.targetGender === "male" ? "male" : "female";
    const source = state.searchSource || "all";
    const seq = ++charSearchSeq;
    host.textContent = "正在搜…";
    try {
      let items = [];
      try {
        const found = await api().get("/api/plugin/char-swap/search?gender=" + gender + "&q=" + encodeURIComponent(q) + "&limit=32&source=" + encodeURIComponent(source));
        (found.items || []).forEach((item) => {
          items.push({
            reference_id: item.reference_id,
            label: (item.source ? item.source + " · " : "") + (item.label || item.reference_id),
            record: item.record || item,
          });
        });
      } catch (_) {
        const wantCustom = source === "all" || source === "oc";
        const wantArk = source === "all" || source === "ark";
        const [ark, customItems] = await Promise.all([
          wantArk ? api().get("/api/plugin/char-swap/ark-library?gender=" + gender + "&q=" + encodeURIComponent(q) + "&limit=20") : Promise.resolve({ items: [] }),
          wantCustom ? listCustom(gender) : Promise.resolve([]),
        ]);
        (customItems || []).forEach((item) => {
          items.push({
            reference_id: "custom:" + (item.gender || gender) + ":" + item.id,
            label: "OC：" + (item.label || item.id),
            record: Object.assign({ kind: "oc" }, item),
          });
        });
        (ark.items || []).forEach((item) => {
          items.push({
            reference_id: "ark:" + gender + ":" + item.id,
            label: item.label || item.id,
            record: item,
          });
        });
      }
      if (seq !== charSearchSeq) return;
      if (q && (source === "all" || source === "oc")) {
        items.unshift({
          reference_id: "custom:" + gender + ":typed",
          label: "写 OC：" + q,
          record: { id: "typed", label: q, gender: gender, kind: "oc", oc_mode: false, identity: [q], appearance: [], tag: q },
        });
      }
      host.innerHTML = "";
      items.slice(0, 40).forEach((item) => {
        const row = document.createElement("button");
        row.type = "button";
        row.className = "m-chip" + (state.targetId === item.reference_id ? " active" : "");
        row.textContent = item.label;
        row.onclick = () => {
          pickTarget(item);
          searchTargets();
        };
        host.appendChild(row);
      });
      if (!items.length) {
        host.innerHTML = source === "danbooru"
          ? '<p class="m-hint">输入角色名搜 D 站</p>'
          : '<p class="m-hint">没有匹配角色，可在下方写 OC</p>';
      }
    } catch (error) {
      if (seq !== charSearchSeq) return;
      host.innerHTML = '<p class="m-err">' + escapeHtml(error.message || error) + "</p>";
    }
  }

  async function applyDraft(options) {
    if (!requireWrite() || state.busy) return false;
    if (isStandalone() && !remixReady()) {
      toast(remixBlockReason(), "err");
      return false;
    }
    const workId = String((state.work && state.work.work && state.work.work.work_id) || "");
    if (!workId) return false;
    const styleOnly = !!options.styleOnly;
    const slotTargets = options.useSlotTargets
      ? collectSlotTargets((state.slot && state.slot.role === "male") ? "male" : "female")
      : [];
    if (options.useSlotTargets && !slotTargets.length) {
      toast("先给每个角色槽选好人", "err");
      return false;
    }
    if (!options.useSlotTargets && !state.targetId && !styleOnly) {
      toast("先选目标角色", "err");
      return false;
    }
    if (styleOnly && !state.styleRecord) {
      toast("先选画风", "err");
      return false;
    }
    const roleLabel = (options.genderScope === "male" || (state.slot && state.slot.role === "male")) ? "男" : "女";
    if (!options.skipConfirm) {
      if (styleOnly && options.allPages) {
        if (!await confirmAction("整系列换画风", "会清掉每页识别到的画风词，换成你选的。只写草稿，不出图。缺页会跳过。")) return false;
      } else if (options.allPages) {
        const title = options.useSlotTargets ? "全部页按槽位换" : ("全部页换" + roleLabel + "角");
        if (!await confirmAction(title, "会给每一页做零费用草稿，不会出图。缺槽的页会跳过该槽。")) return false;
      } else if (options.genderScope) {
        if (!await confirmAction("本页全部" + roleLabel + "槽", "只改这一页的全部" + roleLabel + "槽，换成同一个人。不会出图。")) return false;
      } else if (options.useSlotTargets) {
        if (!await confirmAction("按槽位换本页", "按你给每个槽选的人写草稿，不会出图。")) return false;
      }
    }
    const status = document.getElementById("mWorkStatus");
    if (status) status.textContent = "正在写草稿…";
    state.busy = true;
    const remixLayers = readRemixLayers();
    try {
      if (isStandalone() && window.StandaloneCore) {
        const compileOpts = {
          image_index: state.pageIndex,
          slot_index: Number((state.slot && state.slot.slot_index) || 0),
          candidate_id: (options.allPages || options.genderScope || options.useSlotTargets || styleOnly)
            ? ""
            : String((state.slot && state.slot.candidate_id) || ""),
          gender_scope: (options.useSlotTargets || styleOnly) ? "" : (options.genderScope || ""),
          target_record: (options.useSlotTargets || styleOnly) ? null : state.targetRecord,
          target_reference_id: (options.useSlotTargets || styleOnly) ? "" : state.targetId,
          style_record: state.styleRecord,
          clothing: remixLayers.clothing,
          extra_tags: remixLayers.extra_tags,
          remove_tags: remixLayers.remove_tags,
        };
        if (options.useSlotTargets) compileOpts.slot_targets = slotTargets;
        const result = options.allPages
          ? window.StandaloneCore.compileDrafts(state.work, compileOpts)
          : window.StandaloneCore.compileDraft(state.work, compileOpts);
        if (!result || Number(result.generation_calls) !== 0) {
          throw new Error("在线草稿未通过零生成安全检查");
        }
        if (Array.isArray(result.pages) && result.pages.length) {
          result.pages.forEach((page) => {
            state.drafts[String(page.image_index)] = page;
          });
        } else {
          state.drafts[String(state.pageIndex)] = result;
        }
        persistDrafts(workId);
        paintWork(document.getElementById("mApp"));
        const next = document.getElementById("mWorkStatus");
        if (next) {
          next.textContent = result.message || "草稿已就绪，还没扣 Anlas";
          next.className = "m-status m-ok";
        }
        return true;
      }
      const payload = {
        image_index: state.pageIndex,
        slot_index: Number((state.slot && state.slot.slot_index) || 0),
        all_pages: !!options.allPages,
        clothing: remixLayers.clothing,
        extra_tags: remixLayers.extra_tags,
        remove_tags: remixLayers.remove_tags,
      };
      if (state.slot && state.slot.candidate_id && !options.allPages) payload.candidate_id = state.slot.candidate_id;
      if (options.genderScope) payload.gender_scope = options.genderScope;
      if (state.targetId) payload.target_reference_id = state.targetId;
      const result = await api().request("/api/nai/aitag/work/" + encodeURIComponent(workId) + "/draft", {
        method: "POST",
        body: payload,
        timeoutMs: 120000,
      });
      if (!result || !result.draft || Number(result.generation_calls) !== 0) {
        throw new Error("在线草稿未通过零生成安全检查");
      }
      if (Array.isArray(result.pages) && result.pages.length) {
        result.pages.forEach((page) => {
          state.drafts[String(page.image_index)] = page;
        });
      } else {
        state.drafts[String(state.pageIndex)] = result;
      }
      persistDrafts(workId);
      paintWork(document.getElementById("mApp"));
      const next = document.getElementById("mWorkStatus");
      if (next) {
        next.textContent = result.message || "草稿已就绪，还没扣 Anlas";
        next.className = "m-status m-ok";
      }
      return true;
    } catch (error) {
      if (status) {
        status.textContent = error.message || String(error);
        status.className = "m-status m-err";
      } else {
        toast(error.message || String(error), "err");
      }
      return false;
    } finally {
      state.busy = false;
    }
  }

  function seriesRole() {
    return (state.slot && state.slot.role === "male") ? "male" : "female";
  }

  function seriesWhoLabel(slotTargets, useSlots) {
    if (useSlots) {
      return slotTargets.map((item) => {
        const rec = item.target_record || {};
        return rec.label || rec.name || rec.character || "角色";
      }).filter(Boolean).join(" / ") || "分槽角色";
    }
    return state.targetLabel || "原角色";
  }

  async function applyStyleSeries() {
    if (!state.styleRecord) {
      toast("先选画风", "err");
      return false;
    }
    return applyDraft({ allPages: true, styleOnly: true });
  }

  async function remixSeriesAndEnqueue() {
    if (!requireWrite() || state.busy) return false;
    if (isStandalone() && !remixReady()) {
      toast(remixBlockReason(), "err");
      return false;
    }
    const pageCount = imageCountOf(state.work);
    const role = seriesRole();
    const slotTargets = collectSlotTargets(role);
    const genderCount = (window.StandaloneCore && window.StandaloneCore.countGenderSlots)
      ? window.StandaloneCore.countGenderSlots((state.work && state.work.character_candidates) || [], state.pageIndex, role)
      : slotTargets.length;
    const useSlots = slotTargets.length >= 1 && genderCount >= 2;
    const hasTarget = !!state.targetId;
    const hasStyle = !!state.styleRecord;
    if (!useSlots && !hasTarget && !hasStyle) {
      toast("先选人，或先选画风", "err");
      return false;
    }
    const nai = await api().get("/api/nai/status");
    if (!nai.has_token) {
      toast(isStandalone() ? "先在设置里填 NovelAI Token" : "电脑上还没配置 NovelAI Token", "err");
      if (isStandalone()) openSettings();
      return false;
    }
    const copiesBox = document.getElementById("mCopies");
    const copies = Math.max(1, Math.min(8, Number(copiesBox && copiesBox.value) || state.copies || 1));
    state.copies = copies;
    const who = seriesWhoLabel(slotTargets, useSlots);
    const stylePart = hasStyle ? ("，画风换成" + state.styleLabel) : "";
    if (!await confirmAction(
      "整系列换角并入队",
      "把这 " + pageCount + " 页都换成「" + who + "」" + stylePart + "，每页出 " + copies + " 张，收进图库同一组。默认免费档。点确认后才会调用 NovelAI。"
    )) return false;
    const compiled = await applyDraft({
      allPages: true,
      useSlotTargets: useSlots,
      genderScope: (!useSlots && hasTarget) ? role : "",
      styleOnly: !useSlots && !hasTarget && hasStyle,
      skipConfirm: true,
    });
    if (!compiled) return false;
    return enqueueSeries({ skipConfirm: true });
  }

  async function generateCurrent() {
    if (!requireWrite() || state.busy) return;
    if (isStandalone() && !remixReady()) {
      toast(remixBlockReason(), "err");
      return;
    }
    const entry = state.drafts[String(state.pageIndex)];
    const comment = draftComment(entry);
    if (!comment) {
      toast("先做本页换角草稿", "err");
      return;
    }
    const nai = await api().get("/api/nai/status");
    if (!nai.has_token) {
      toast(isStandalone() ? "先在设置里填 NovelAI Token" : "电脑上还没配置 NovelAI Token", "err");
      if (isStandalone()) openSettings();
      return;
    }
    const copiesBox = document.getElementById("mCopies");
    const copies = Math.max(1, Math.min(8, Number(copiesBox && copiesBox.value) || state.copies || 1));
    state.copies = copies;
    if (!await confirmAction("加入队列", "默认免费档。同一任务会生成 " + copies + " 张，收进图库一组。多个 Token 会并发。点确认后才会调用 NovelAI。")) return;
    if (isStandalone()) {
      const status = document.getElementById("mWorkStatus");
      try {
        const started = await enqueueGenerate(entry, state.pageIndex, copies);
        if (status) {
          status.textContent = (started.message || "已加入生成队列") + " · " + copies + "张";
          status.className = "m-status m-ok";
        }
        toast("已加入队列，去排队页看进度");
        location.hash = "#/batch";
      } catch (error) {
        if (status) {
          status.textContent = error.message || String(error);
          status.className = "m-status m-err";
        } else {
          toast(error.message || String(error), "err");
        }
      }
      return;
    }
    await generateEntry(entry, state.pageIndex, document.getElementById("mWorkStatus"), document.getElementById("mGenImg"));
  }

  async function enqueueGenerate(entry, pageIndex, copies) {
    const comment = draftComment(entry);
    if (!comment) throw new Error("草稿不完整");
    const work = (state.work && state.work.work) || {};
    const workId = String(work.work_id || work.id || "");
    if (isStandalone() && !DemoWorksSafe(workId) && !state.favIds[workId] && !(state.route && state.route.local) && !String(workId).startsWith("g")) {
      throw new Error("先收藏入本地库，才能换角和生成");
    }
    const img = ((state.work && state.work.images) || [])[pageIndex] || {};
    const snapshot = JSON.parse(JSON.stringify(comment));
    snapshot._aitag_source = {
      work_id: workId,
      page_index: pageIndex,
      title: work.title || "",
      thumb: img.thumbnail_url || img.url || "",
    };
    const res = await api().request("/api/nai/generate", {
      method: "POST",
      body: {
        patched_comment: snapshot,
        work_id: work.work_id || null,
        work_id_str: workId,
        remote_work_id: workId,
        source_gallery_id: "phone-local",
        source_title: work.title || "",
        source_thumb: img.thumbnail_url || img.url || "",
        page_index: pageIndex,
        copies: copies || 1,
        force_free: true,
        prompt_profile: "native",
      },
      timeoutMs: 60000,
    });
    if (!res || !res.ok) throw new Error((res && (res.message || res.detail)) || "入队失败");
    return res;
  }

  async function enqueueSeries(options) {
    const opts = options || {};
    if (!requireWrite() || state.busy) return false;
    if (isStandalone() && !remixReady()) {
      toast(remixBlockReason(), "err");
      return false;
    }
    const keys = Object.keys(state.drafts || {}).sort((a, b) => Number(a) - Number(b));
    if (!keys.length) {
      toast("先给各页写草稿。点「整系列换角并入队」，或在高级里换各页。", "err");
      return false;
    }
    const nai = await api().get("/api/nai/status");
    if (!nai.has_token) {
      toast(isStandalone() ? "先在设置里填 NovelAI Token" : "电脑上还没配置 NovelAI Token", "err");
      if (isStandalone()) openSettings();
      return false;
    }
    const copiesBox = document.getElementById("mCopies");
    const copies = Math.max(1, Math.min(8, Number(copiesBox && copiesBox.value) || state.copies || 1));
    state.copies = copies;
    if (!opts.skipConfirm) {
      if (!await confirmAction(
        "全部页加入队列",
        "默认免费档。已草稿的 " + keys.length + " 页各出 " + copies + " 张，收进图库同一组。多个 Token 会并发。点确认后才会调用 NovelAI。"
      )) return false;
    }
    const work = (state.work && state.work.work) || {};
    const workId = String(work.work_id || work.id || "");
    const pages = [];
    keys.forEach((key) => {
      const comment = draftComment(state.drafts[key]);
      if (!comment) return;
      const snapshot = JSON.parse(JSON.stringify(comment));
      snapshot._aitag_source = {
        work_id: workId,
        page_index: Number(key),
        title: work.title || "",
        thumb: currentImage().thumbnail_url || currentImage().url || "",
      };
      pages.push({
        comment: snapshot,
        patched_comment: snapshot,
        page_index: Number(key),
      });
    });
    if (!pages.length) {
      toast("草稿不完整", "err");
      return false;
    }
    const status = document.getElementById("mWorkStatus");
    try {
      const res = await api().request("/api/nai/generate", {
        method: "POST",
        body: {
          patched_comment: pages[0].patched_comment,
          pages: pages,
          work_id: work.work_id || null,
          work_id_str: workId,
          remote_work_id: workId,
          source_gallery_id: "phone-local",
          source_title: work.title || "",
          source_thumb: currentImage().thumbnail_url || currentImage().url || "",
          copies: copies,
          force_free: true,
          prompt_profile: "native",
        },
        timeoutMs: 60000,
      });
      if (!res || !res.ok) throw new Error((res && (res.message || res.detail)) || "入队失败");
      if (status) {
        status.textContent = (res.message || "已加入生成队列") + " · " + pages.length + "页";
        status.className = "m-status m-ok";
      }
      toast(res.message || "整系列已入队，去排队页看进度");
      location.hash = "#/batch";
      return true;
    } catch (error) {
      if (status) {
        status.textContent = error.message || String(error);
        status.className = "m-status m-err";
      } else {
        toast(error.message || String(error), "err");
      }
      return false;
    }
  }

  function DemoWorksSafe(workId) {
    return String(workId || "") === "demo-ark-amiya";
  }

  async function generateEntry(entry, pageIndex, statusEl, imgEl, options) {
    const comment = draftComment(entry);
    if (!comment) throw new Error("草稿不完整");
    const work = (state.work && state.work.work) || {};
    const img = ((state.work && state.work.images) || [])[pageIndex] || {};
    const snapshot = JSON.parse(JSON.stringify(comment));
    snapshot._aitag_source = {
      work_id: String(work.work_id || ""),
      page_index: pageIndex,
      title: work.title || "",
      thumb: img.thumbnail_url || img.url || "",
    };
    if (statusEl) statusEl.textContent = "排队生成中…";
    const manageBusy = !options || options.manageBusy !== false;
    if (manageBusy) state.busy = true;
    try {
      const res = await api().request("/api/nai/generate", {
        method: "POST",
        body: {
          patched_comment: snapshot,
          work_id: work.work_id || null,
          work_id_str: String(work.work_id || ""),
          remote_work_id: String(work.work_id || ""),
          source_gallery_id: isStandalone() ? "phone-local" : "aitag-online",
          source_title: work.title || "",
          source_thumb: img.thumbnail_url || img.url || "",
          page_index: pageIndex,
          copies: isStandalone() ? (state.copies || 1) : 1,
          force_free: true,
          prompt_profile: "native",
        },
        timeoutMs: 60000,
      });
      if (!res || !res.ok) throw new Error((res && (res.message || res.detail)) || "生图失败");
      const taskId = res.task_id || (res.batch && res.batch.task_id) || "";
      if (!taskId) throw new Error("未返回生成任务");
      const job = await api().pollJob(taskId, (progress) => {
        if (statusEl) statusEl.textContent = "生成中 " + (progress.done || 0) + "/" + (progress.total || 1);
      });
      if (String(job.status || "") === "unknown") {
        throw new Error(job.message || "这次可能已扣费，不要自动重试");
      }
      const items = Array.isArray(job.items) ? job.items : [];
      const lastOk = [...items].reverse().find((item) => item && item.ok && (item.image_url || item.gallery_url));
      if (!lastOk) throw new Error(job.message || "生图失败");
      if (statusEl) {
        statusEl.textContent = lastOk.message || "完成。生成后若开了自动流水线会继续后处理。";
        statusEl.className = "m-status m-ok";
      }
      if (imgEl && lastOk.image_url) {
        imgEl.src = lastOk.image_url + (lastOk.image_url.includes("?") ? "&" : "?") + "t=" + Date.now();
        imgEl.classList.remove("hidden");
      }
      if (statusEl && lastOk.library_id) {
        const extra = document.createElement("div");
        extra.className = "m-row";
        extra.style.marginTop = "8px";
        extra.innerHTML = `<a class="m-ghost" href="#/library/${encodeURIComponent(lastOk.library_id)}">去本地库再换</a><a class="m-ghost" href="#/gallery/${encodeURIComponent(lastOk.album_id || "")}">看图库</a>`;
        statusEl.insertAdjacentElement("afterend", extra);
      }
      return lastOk;
    } finally {
      if (manageBusy) state.busy = false;
    }
  }

  function enqueueCurrent() {
    const pages = Object.keys(state.drafts);
    if (!pages.length) {
      toast("还没有可入队的草稿", "err");
      return;
    }
    const work = (state.work && state.work.work) || {};
    const queue = loadQueue();
    queue.push({
      work_id: String(work.work_id || ""),
      title: work.title || work.work_id,
      thumb: currentImage().thumbnail_url || currentImage().url || "",
      drafts: state.drafts,
    });
    saveQueue(queue);
    toast("已加入批量队列");
    location.hash = "#/batch";
  }

  async function renderBatch(root) {
    const online = loadQueue();
    let serverQueue = { items: [] };
    if (isStandalone()) {
      try { serverQueue = await api().get("/api/mobile/queue"); } catch (_) { /* ignore */ }
    }
    const jobs = serverQueue.items || [];
    root.innerHTML = `
      ${isStandalone() ? `
      <section class="m-card">
        <h2>生成队列</h2>
        <p class="m-hint">几个 Token 就几路并发。整系列用「整系列换角并入队」，多页收进图库一组。失败可手动重试或删除，不会自动重试。</p>
        <div class="m-row" style="margin-bottom:8px">
          <button type="button" id="mClearEnded" class="m-ghost">清空已结束</button>
        </div>
        <div class="m-list">${jobs.map((job) => `
          <div class="m-item">
            <div></div>
            <div>
              <strong>${escapeHtml(job.title || job.task_id || "任务")}</strong>
              <div class="m-hint">${escapeHtml(job.status || "")} · ${job.done || 0}/${job.total || 1}张${job.concurrency > 1 ? " · " + job.concurrency + "路并发" : ""}</div>
              ${job.message ? `<div class="m-err">${escapeHtml(String(job.message).slice(0, 160))}</div>` : ""}
            </div>
            <div class="m-row">
              ${job.cancellable ? `<button type="button" class="m-ghost" data-cancel="${escapeHtml(job.task_id || "")}">取消</button>` : ""}
              ${job.retryable ? `<button type="button" class="m-ghost" data-retry="${escapeHtml(job.task_id || "")}">重试</button>` : ""}
              <button type="button" class="m-danger" data-del-job="${escapeHtml(job.task_id || "")}">删除</button>
              <a class="m-ghost" href="#/gallery/${encodeURIComponent(job.album_id || job.task_id || "")}">图库</a>
            </div>
          </div>`).join("") || '<p class="m-hint">队列是空的。在本地库换角后点「整系列换角并入队」。</p>'}
        </div>
      </section>` : ""}
      <section class="m-card" ${isStandalone() ? "hidden" : ""}>
        <h2>在线批量</h2>
        <p class="m-hint">把已换角草稿按页依次生成。默认免费档，开始前会再确认一次。</p>
        <div id="mOnlineQueue" class="m-list"></div>
        <div class="m-row" style="margin-top:10px">
          <button type="button" id="mRunOnline" class="m-primary">开始在线批量</button>
          <button type="button" id="mClearOnline" class="m-ghost">清空</button>
        </div>
        <p id="mOnlineStatus" class="m-status"></p>
      </section>
      <section class="m-card" ${isStandalone() ? "hidden" : ""}>
        <h2>本地待生成</h2>
        <p class="m-hint">读取电脑里的待生成队列，先预检再跑本地批量换角。</p>
        <div class="m-row">
          <select id="mLocalGallery">
            <option value="site">Pixiv NAI</option>
            <option value="codex">自选库</option>
            <option value="qqgroup">Q群</option>
          </select>
          <button type="button" id="mLoadLocal" class="m-ghost">读取队列</button>
        </div>
        <p id="mLocalHint" class="m-hint">尚未读取</p>
        <div class="m-row" style="margin-top:10px">
          <button type="button" id="mPreviewLocal" class="m-ghost">预检</button>
          <button type="button" id="mRunLocal" class="m-primary">开始本地批量</button>
        </div>
        <p id="mLocalStatus" class="m-status"></p>
      </section>`;
    const host = document.getElementById("mOnlineQueue");
    host.innerHTML = online.map((item, index) => `
      <div class="m-item">
        <img src="${escapeHtml(item.thumb || "")}" alt="">
        <div><strong>${escapeHtml(item.title || item.work_id)}</strong><div class="m-hint">${Object.keys(item.drafts || {}).length} 页草稿</div></div>
        <button type="button" data-drop="${index}" class="m-ghost">移除</button>
      </div>`).join("") || '<p class="m-hint">队列是空的</p>';
    host.querySelectorAll("[data-drop]").forEach((button) => {
      button.onclick = () => {
        const next = loadQueue();
        next.splice(Number(button.dataset.drop), 1);
        saveQueue(next);
        renderBatch(root);
      };
    });
    root.querySelectorAll("[data-cancel]").forEach((button) => {
      button.onclick = async () => {
        const taskId = button.getAttribute("data-cancel");
        if (!taskId) return;
        if (!await confirmAction("取消队列", "未发出的张不会再生成。已经发出的请求拦不住。")) return;
        try {
          await api().post("/api/mobile/queue/" + encodeURIComponent(taskId) + "/cancel", {});
          toast("已取消");
          renderBatch(root);
        } catch (error) {
          toast(friendlyError(error), "err");
        }
      };
    });
    root.querySelectorAll("[data-retry]").forEach((button) => {
      button.onclick = async () => {
        const taskId = button.getAttribute("data-retry");
        if (!taskId) return;
        if (!await confirmAction("重试这组", "不会自动重试。结果不明时可能已扣费，先看 NovelAI 记录。")) return;
        try {
          const started = await api().post("/api/mobile/queue/" + encodeURIComponent(taskId) + "/retry", {});
          toast(started.message || "已重新入队");
          renderBatch(root);
        } catch (error) {
          toast(friendlyError(error), "err");
        }
      };
    });
    const deleteJob = async (taskId) => {
      if (!taskId) return;
      if (!await confirmAction("删除队列任务", "只从排队列表拿掉。已经发出的请求拦不住，图库里已生成的还在。")) return;
      try {
        await api().post("/api/mobile/queue/" + encodeURIComponent(taskId) + "/delete", {});
        toast("已从队列删除");
        renderBatch(root);
      } catch (error) {
        toast(friendlyError(error), "err");
      }
    };
    root.querySelectorAll("[data-del-job]").forEach((button) => {
      button.onclick = () => deleteJob(button.getAttribute("data-del-job"));
    });
    const clearEnded = document.getElementById("mClearEnded");
    if (clearEnded) {
      clearEnded.onclick = async () => {
        const ended = jobs.filter((job) => job && (job.terminal || job.status === "error" || job.status === "done" || job.status === "cancelled" || job.status === "unknown"));
        if (!ended.length) {
          toast("没有已结束的任务");
          return;
        }
        if (!await confirmAction("清空已结束", "从排队列表拿掉 " + ended.length + " 个已结束任务。图库里的图还在。")) return;
        for (const job of ended) {
          try {
            await api().post("/api/mobile/queue/" + encodeURIComponent(job.task_id) + "/delete", {});
          } catch (_) { /* ignore */ }
        }
        toast("已清空结束任务");
        renderBatch(root);
      };
    }
    document.getElementById("mClearOnline").onclick = () => { saveQueue([]); renderBatch(root); };
    document.getElementById("mRunOnline").onclick = runOnlineBatch;
    if (isStandalone() && jobs.some((job) => job && !job.terminal && job.status !== "done" && job.status !== "error" && job.status !== "cancelled" && job.status !== "unknown")) {
      setTimeout(() => {
        if (state.route && state.route.name === "batch") renderBatch(root);
      }, 1800);
    }
    let localTargets = [];
    document.getElementById("mLoadLocal").onclick = async () => {
      const gid = document.getElementById("mLocalGallery").value;
      try {
        const data = await api().get("/api/queue/works?gallery_id=" + encodeURIComponent(gid) + "&page_size=60");
        localTargets = (data.items || []).map((item) => ({
          gallery_id: gid,
          work_id: item.id || item.work_id,
          page_index: 0,
        }));
        document.getElementById("mLocalHint").textContent = "队列里有 " + localTargets.length + " 个作品";
      } catch (error) {
        document.getElementById("mLocalHint").textContent = error.message || String(error);
      }
    };
    document.getElementById("mPreviewLocal").onclick = async () => {
      if (!requireWrite()) return;
      if (!localTargets.length) { toast("先读取本地待生成队列", "err"); return; }
      const status = document.getElementById("mLocalStatus");
      try {
        const preview = await api().post("/api/plugin/char-swap/batch/preview", {
          targets: localTargets,
          recipe: localRecipe(),
        });
        status.textContent = preview.message || ("预检 " + (preview.ok ? "通过" : "失败"));
      } catch (error) {
        status.textContent = error.message || String(error);
        status.className = "m-status m-err";
      }
    };
    document.getElementById("mRunLocal").onclick = async () => {
      if (!requireWrite()) return;
      if (!localTargets.length) { toast("先读取本地待生成队列", "err"); return; }
      if (!await confirmAction("开始本地批量", "默认免费档。确认后才会生成。")) return;
      const status = document.getElementById("mLocalStatus");
      try {
        const started = await api().post("/api/plugin/char-swap/batch/run", {
          targets: localTargets,
          recipe: localRecipe(),
          force_free: true,
          generate: true,
          preview_only: false,
        });
        const taskId = started.task_id || (started.batch && started.batch.task_id) || "";
        if (!taskId) throw new Error(started.message || "没有任务 ID");
        const job = await api().pollJob(taskId, (progress) => {
          status.textContent = "批量中 " + (progress.done || 0) + "/" + (progress.total || localTargets.length);
        });
        status.textContent = job.message || ("结束：" + (job.status || "done"));
        status.className = "m-status m-ok";
      } catch (error) {
        status.textContent = error.message || String(error);
        status.className = "m-status m-err";
      }
    };
  }

  function localRecipe() {
    return {
      auto_sanitize: true,
      prompt_profile: "native",
      preserve_action: false,
      preserve_center: true,
      transform: { enabled: false, mode: "replace", gender: "female", preset_id: "", target_char_index: "0" },
      style: { find: "", replace: "" },
      sanitize: { enabled: true, filter_racial: true, filter_gore: true, filter_creature: false },
    };
  }

  async function runOnlineBatch() {
    if (!requireWrite() || state.busy) return;
    const queue = loadQueue();
    if (!queue.length) { toast("在线队列是空的", "err"); return; }
    const nai = await api().get("/api/nai/status");
    if (!nai.has_token) {
      toast(isStandalone() ? "先在设置里填 NovelAI Token" : "电脑上还没配置 NovelAI Token", "err");
      if (isStandalone()) openSettings();
      return;
    }
    if (!await confirmAction("开始在线批量", "会按队列逐页生成，默认免费档。中途失败不会自动重试。")) return;
    const status = document.getElementById("mOnlineStatus");
    const runBtn = document.getElementById("mRunOnline");
    if (runBtn) runBtn.disabled = true;
    state.busy = true;
    let done = 0;
    let total = 0;
    queue.forEach((item) => { total += Object.keys(item.drafts || {}).length; });
    try {
      for (const item of queue) {
        state.work = { work: { work_id: item.work_id, title: item.title }, images: [{ thumbnail_url: item.thumb }] };
        const pages = Object.keys(item.drafts || {}).sort((a, b) => Number(a) - Number(b));
        for (const key of pages) {
          try {
            await generateEntry(item.drafts[key], Number(key), status, null, { manageBusy: false });
            done += 1;
            status.textContent = "在线批量 " + done + "/" + total;
          } catch (error) {
            status.textContent = (error.message || error) + "（已完成 " + done + "/" + total + "）";
            status.className = "m-status m-err";
            return;
          }
        }
      }
      status.textContent = "在线批量完成 " + done + "/" + total;
      status.className = "m-status m-ok";
    } finally {
      state.busy = false;
      if (runBtn) runBtn.disabled = false;
    }
  }

  async function renderPipeline(root) {
    root.innerHTML = `<section class="m-card"><h2>自动流水线</h2><p class="m-status">读取中…</p></section>`;
    try {
      const [cfg, status] = await Promise.all([
        api().get("/api/pipeline/config"),
        api().get("/api/pipeline/status"),
      ]);
      const auto = !!(cfg.config && cfg.config.auto_after_generate);
      const job = status.job || {};
      const backlog = status.backlog || {};
      const phoneHint = isStandalone()
        ? "生成成功后跑本机流水线：2x 超分、清元数据、入本地库、存相册。打码需要电脑 ANR，不打进手机包。"
        : "生成成功后，电脑端会按配置做超分 / 打码 / 清元数据。手机只负责查看和补跑。";
      root.innerHTML = `
        <section class="m-card">
          <h2>自动流水线</h2>
          <p class="m-hint">${phoneHint}</p>
          <p>生成后自动后处理：<strong class="${auto ? "m-ok" : "m-err"}">${auto ? "已开" : "未开"}</strong></p>
          <p class="m-hint">当前任务：${escapeHtml(job.status || "空闲")} · 待处理 ${escapeHtml(String(backlog.count ?? backlog.pending ?? 0))}</p>
          <div class="m-row">
            <button type="button" id="mPipeRun" class="m-primary">补跑缺失项</button>
            <button type="button" id="mPipeAuto" class="m-ghost">${auto ? "关闭自动" : "打开自动"}</button>
          </div>
          <p id="mPipeStatus" class="m-status"></p>
        </section>`;
      document.getElementById("mPipeRun").onclick = async () => {
        if (!requireWrite()) return;
        if (!await confirmAction("补跑流水线", "只处理后处理缺失的已生成图，不会重新出图。")) return;
        const box = document.getElementById("mPipeStatus");
        try {
          const result = await api().post("/api/pipeline/run", { only_missing: true });
          box.textContent = result.message || "已开始";
          box.className = "m-status m-ok";
        } catch (error) {
          box.textContent = error.message || String(error);
          box.className = "m-status m-err";
        }
      };
      document.getElementById("mPipeAuto").onclick = async () => {
        if (!requireWrite()) return;
        if (!await confirmAction(auto ? "关闭自动流水线" : "打开自动流水线", "只改本机后处理开关，不会立刻出图。")) return;
        try {
          await api().post("/api/pipeline/config", { auto_after_generate: !auto });
          renderPipeline(root);
        } catch (error) {
          toast(error.message || String(error), "err");
        }
      };
    } catch (error) {
      root.innerHTML = `<section class="m-card"><h2>自动流水线</h2><p class="m-err">${escapeHtml(error.message || error)}</p></section>`;
    }
  }

  async function renderPair(root) {
    const status = await refreshWriteAccess();
    const urls = (status && status.urls) || [];
    root.innerHTML = `
      <section class="m-card">
        <h2>手机配对</h2>
        <p class="m-hint">默认只监听本机。手机要换角/出图，请在电脑双击「启动手机版.bat」，再用下面的配对码。</p>
        <p class="m-hint">USB 调试也可以：<code>adb reverse tcp:8797 tcp:8797</code> 后打开 http://127.0.0.1:8797/m</p>
        <div id="mPairBox"></div>
      </section>`;
    const box = document.getElementById("mPairBox");
    if (state.loopback) {
      box.innerHTML = `
        <p class="m-ok">这台电脑已可写。</p>
        <p class="m-hint">${urls.length ? urls.map(escapeHtml).join("<br>") : "当前没有探测到局域网地址。启动手机版后重试。"}</p>
        <div class="m-code" id="mPairCode">------</div>
        <div class="m-row">
          <button type="button" id="mMakeCode" class="m-primary">生成配对码</button>
          <button type="button" id="mRevoke" class="m-danger">撤销手机</button>
        </div>
        <p id="mPairStatus" class="m-status"></p>`;
      document.getElementById("mMakeCode").onclick = async () => {
        try {
          const created = await api().post("/api/mobile/pair/start", {});
          document.getElementById("mPairCode").textContent = created.code;
          document.getElementById("mPairStatus").textContent = created.message || "把 6 位码发给手机";
        } catch (error) {
          toast(error.message || String(error), "err");
        }
      };
      document.getElementById("mRevoke").onclick = async () => {
        if (!await confirmAction("撤销手机配对", "已配对的手机将无法再写。")) return;
        await api().post("/api/mobile/pair/revoke", {});
        toast("已撤销");
      };
      return;
    }
    box.innerHTML = `
      <p class="m-hint">在电脑生成 6 位配对码，输入后才能换角和生成。</p>
      <input id="mClaimCode" inputmode="numeric" maxlength="6" placeholder="6 位配对码" />
      <div class="m-row" style="margin-top:10px">
        <button type="button" id="mClaimBtn" class="m-primary">配对</button>
      </div>
      <p id="mPairStatus" class="m-status"></p>`;
    document.getElementById("mClaimBtn").onclick = async () => {
      const code = document.getElementById("mClaimCode").value.trim();
      try {
        const claimed = await api().request("/api/mobile/pair/claim", {
          method: "POST",
          body: { code: code },
          skipSessionToken: true,
        });
        saveToken(claimed.token, claimed.expires_at);
        state.canWrite = true;
        setConn("已配对", "ok");
        document.getElementById("mPairStatus").textContent = claimed.message || "配对成功";
        document.getElementById("mPairStatus").className = "m-status m-ok";
      } catch (error) {
        document.getElementById("mPairStatus").textContent = error.message || String(error);
        document.getElementById("mPairStatus").className = "m-status m-err";
      }
    };
  }

  async function renderGallery(root) {
    root.innerHTML = `<section class="m-card"><h2>成果</h2><p class="m-status">读取中…</p></section>`;
    try {
      const [data, cfg] = await Promise.all([
        api().get("/api/mobile/outputs"),
        api().get("/api/pipeline/config").catch(() => ({ config: {} })),
      ]);
      const albums = data.albums || data.items || [];
      const items = albums;
      const cfgObj = cfg.config || {};
      const auto = !!cfgObj.auto_after_generate;
      const upscale = cfgObj.upscale !== false;
      const metadata = cfgObj.metadata !== false;
      root.innerHTML = `
        <section class="m-hero">
          <p class="m-eyebrow">图库</p>
          <h2>本机图库</h2>
          <p class="m-hint">按生成任务分组，和电脑大型图库一样：同一任务的图片放在一起，点进去才能看。流水线做本机 2x 超分和清元数据。</p>
        </section>
        <section class="m-card">
          <h2>后处理流水线</h2>
          <p>自动后处理：<strong class="${auto ? "m-ok" : "m-err"}">${auto ? "已开" : "未开"}</strong></p>
          <p>本机 2x 拉伸：<strong class="${upscale ? "m-ok" : "m-err"}">${upscale ? "已开" : "未开"}</strong></p>
          <p>清元数据：<strong class="${metadata ? "m-ok" : "m-err"}">${metadata ? "已开" : "未开"}</strong></p>
          <p class="m-hint">这是 Bitmap 拉伸，不是电脑版 ANR。打码未打包（ANR + YOLO 上百 MB）。</p>
          <div class="m-row" style="margin-top:10px">
            <button type="button" id="mPipeRun" class="m-primary">补跑流水线</button>
            <button type="button" id="mPipeAuto" class="m-ghost">${auto ? "关闭自动" : "打开自动"}</button>
          </div>
          <div class="m-row" style="margin-top:8px">
            <button type="button" id="mPipeUp" class="m-ghost">${upscale ? "关闭超分" : "打开超分"}</button>
            <button type="button" id="mPipeMeta" class="m-ghost">${metadata ? "关闭清元数据" : "打开清元数据"}</button>
          </div>
          <p id="mPipeStatus" class="m-status"></p>
        </section>
        <div class="m-grid" id="mOutGrid"></div>
        <p class="m-status">${items.length ? ("共 " + items.length + " 个任务，点进去看这一组图") : "还没有生成任务。先收藏入本地库，再换角排队。"}</p>`;
      const grid = document.getElementById("mOutGrid");
      grid.innerHTML = items.map((item) => {
        const albumId = item.album_id || item.task_id || item.id || "";
        const cover = item.cover_url || item.image_url || item.thumb || "";
        const count = item.image_count || (item.images && item.images.length) || 0;
        return `<a class="m-work" href="#/gallery/${encodeURIComponent(albumId)}">
          <img src="${escapeHtml(cover)}" alt="">
          <em class="m-page-badge">${count}张</em>
          <span>${escapeHtml(item.title || albumId || "生成任务")}</span>
        </a>`;
      }).join("");
      document.getElementById("mPipeRun").onclick = async () => {
        if (!await confirmAction("补跑流水线", "会对还没处理的生成图做本机 2x 拉伸和清元数据，并补存相册。不会重新出图，也不会打码。")) return;
        const box = document.getElementById("mPipeStatus");
        try {
          const result = await api().post("/api/pipeline/run", { only_missing: true });
          box.textContent = result.message || "已开始";
          box.className = "m-status m-ok";
        } catch (error) {
          box.textContent = error.message || String(error);
          box.className = "m-status m-err";
        }
      };
      document.getElementById("mPipeAuto").onclick = async () => {
        if (!await confirmAction(auto ? "关闭自动流水线" : "打开自动流水线", "只改这台手机的开关，不会立刻出图。")) return;
        await api().post("/api/pipeline/config", { auto_after_generate: !auto });
        renderGallery(root);
      };
      document.getElementById("mPipeUp").onclick = async () => {
        await api().post("/api/pipeline/config", { upscale: !upscale });
        renderGallery(root);
      };
      document.getElementById("mPipeMeta").onclick = async () => {
        await api().post("/api/pipeline/config", { metadata: !metadata });
        renderGallery(root);
      };
    } catch (error) {
      root.innerHTML = `<section class="m-card"><h2>图库</h2><p class="m-hint">装到手机后，这里按生成任务分组。电脑预览也可先走一遍收藏→换角→队列。</p></section>`;
    }
  }

  async function renderAlbum(root, albumId) {
    root.innerHTML = `<section class="m-card"><h2>图库任务</h2><p class="m-status">读取中…</p></section>`;
    try {
      const data = await api().get("/api/mobile/gallery/" + encodeURIComponent(albumId));
      const album = data.album || {};
      const images = data.images || album.images || [];
      root.innerHTML = `
        <section class="m-card">
          <p class="m-eyebrow">图库任务</p>
          <h2>${escapeHtml(album.title || albumId)}</h2>
          <p class="m-hint">${images.length}张 · 同一生成任务，点图看大图</p>
          <div class="m-row">
            <a class="m-ghost" href="#/gallery">返回图库</a>
            ${album.source_work_id ? `<a class="m-ghost" href="#/library/${encodeURIComponent("g" + album.album_id)}">用这组再换角</a>` : ""}
            <button type="button" id="mAlbumDel" class="m-danger">删除这组</button>
          </div>
        </section>
        <div class="m-grid" id="mAlbumGrid"></div>`;
      const grid = document.getElementById("mAlbumGrid");
      grid.innerHTML = images.map((item, index) => `
        <a class="m-work" href="${escapeHtml(item.image_url || item.url || "")}" target="_blank" rel="noopener">
          <img src="${escapeHtml(item.thumbnail_url || item.image_url || item.url || "")}" alt="">
          <em class="m-page-badge">P${index + 1}</em>
          <span>第 ${index + 1} 张</span>
        </a>`).join("") || '<p class="m-hint">这个任务还没有图。</p>';
      const del = document.getElementById("mAlbumDel");
      if (del) {
        del.onclick = async () => {
          if (!await confirmAction("删除这组", "只删应用里的这组图，系统相册里已导出的还在。")) return;
          try {
            await api().post("/api/mobile/gallery/" + encodeURIComponent(albumId) + "/delete", {});
            toast("已删除这组图");
            location.hash = "#/gallery";
          } catch (error) {
            toast(friendlyError(error), "err");
          }
        };
      }
    } catch (error) {
      root.innerHTML = `<section class="m-card"><h2>图库任务</h2><p class="m-err">${escapeHtml(friendlyError(error))}</p>
        <div class="m-row"><a class="m-primary" href="#/gallery">返回图库</a></div></section>`;
    }
  }

  async function renderSettings(root) {
    let nai = { has_token: false };
    let ai = { has_api_key: false };
    try { nai = await api().get("/api/nai/status"); } catch (_) { /* ignore */ }
    try { ai = await api().get("/api/ai/status"); } catch (_) { /* ignore */ }
    const hasAi = !!(ai.has_api_key || ai.has_deepseek);
    root.innerHTML = `
      <section class="m-card">
        <h2>手机本地设置</h2>
        <p class="m-hint">独立软件，不遥控电脑。先填下面两把钥匙就能用。NovelAI 负责出图，DeepSeek 负责写角色和优化咒语。密钥只存在这台手机。Token 每行一个，几个就能并发几路。</p>
        <p>NovelAI：<strong class="${nai.has_token ? "m-ok" : "m-err"}">${nai.has_token ? ("已配置 " + (nai.token_count || 1) + " 个 Token，可 " + (nai.concurrency || nai.token_count || 1) + " 路并发") : "还没填 Token"}</strong></p>
        <textarea id="mToken" rows="5" placeholder="每行一个 NovelAI Token。几个就能并发几路。" autocomplete="off"></textarea>
        <div class="m-row" style="margin-top:10px">
          <button type="button" id="mSaveToken" class="m-primary">保存</button>
          <button type="button" id="mClearToken" class="m-danger">清除</button>
        </div>
        <p style="margin-top:16px">DeepSeek：<strong class="${hasAi ? "m-ok" : "m-err"}">${hasAi ? "已配置 Key" : "还没填 Key"}</strong></p>
        <textarea id="mDeepseek" placeholder="粘贴 DeepSeek API Key（sk- 开头）" autocomplete="off"></textarea>
        <div class="m-row" style="margin-top:10px">
          <button type="button" id="mSaveDeepseek" class="m-primary">保存 DeepSeek</button>
          <button type="button" id="mClearDeepseek" class="m-danger">清除 DeepSeek</button>
        </div>
        <p style="margin-top:16px">网络分流</p>
        <p class="m-hint">不要只开全局 VPN/TUN。把 Clash HTTP 填下面，例如 http://127.0.0.1:7890，也可只填 7890。应用会自动探测本机代理。还被网站拦就点「打开在线库过验证」。</p>
        <input id="mProxy" placeholder="代理，例如 http://127.0.0.1:7890" autocomplete="off" />
        <label class="m-hint" style="display:flex;gap:8px;align-items:center;margin-top:10px">
          <input id="mOnlineProxy" type="checkbox" style="width:auto;min-height:22px" /> 搜图 / 写角色走代理
        </label>
        <label class="m-hint" style="display:flex;gap:8px;align-items:center;margin-top:6px">
          <input id="mNaiProxy" type="checkbox" style="width:auto;min-height:22px" /> 出图走代理（默认关）
        </label>
        <div class="m-row" style="margin-top:10px">
          <button type="button" id="mSaveNet" class="m-primary">保存网络设置</button>
          <button type="button" id="mProbeNet" class="m-ghost">测试在线库</button>
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mVerifyNet" class="m-ghost">打开在线库过验证</button>
        </div>
        <p id="mSetStatus" class="m-status"></p>
      </section>`;
    document.getElementById("mSaveToken").onclick = async () => {
      const token = document.getElementById("mToken").value.trim();
      if (!token) { toast("先粘贴 Token", "err"); return; }
      if (!await confirmAction("保存 Token", "每行一个 Token。几个就能并发几路。只写进本机，不会上传到电脑。")) return;
      try {
        const saved = await api().post("/api/nai/token", { token: token });
        document.getElementById("mToken").value = "";
        document.getElementById("mSetStatus").textContent = saved.message || "已保存";
        document.getElementById("mSetStatus").className = "m-status m-ok";
        renderSettings(root);
      } catch (error) {
        document.getElementById("mSetStatus").textContent = error.message || String(error);
        document.getElementById("mSetStatus").className = "m-status m-err";
      }
    };
    document.getElementById("mClearToken").onclick = async () => {
      if (!await confirmAction("清除 Token", "清除后必须重新粘贴才能出图。")) return;
      try {
        await api().post("/api/nai/token", { token: "" });
        toast("已清除");
        renderSettings(root);
      } catch (error) {
        toast(error.message || String(error), "err");
      }
    };
    document.getElementById("mSaveDeepseek").onclick = async () => {
      const key = document.getElementById("mDeepseek").value.trim();
      if (!key) { toast("先粘贴 DeepSeek Key", "err"); return; }
      if (!await confirmAction("保存 DeepSeek", "只写进本机应用存储，不连电脑。")) return;
      try {
        const saved = await api().post("/api/ai/key", { api_key: key });
        document.getElementById("mDeepseek").value = "";
        document.getElementById("mSetStatus").textContent = saved.message || "DeepSeek 已保存";
        document.getElementById("mSetStatus").className = "m-status m-ok";
        renderSettings(root);
      } catch (error) {
        document.getElementById("mSetStatus").textContent = error.message || String(error);
        document.getElementById("mSetStatus").className = "m-status m-err";
      }
    };
    document.getElementById("mClearDeepseek").onclick = async () => {
      if (!await confirmAction("清除 DeepSeek", "清除后不能再用自然语言写角色或智能优化。")) return;
      try {
        await api().post("/api/ai/key", { api_key: "" });
        toast("已清除 DeepSeek");
        renderSettings(root);
      } catch (error) {
        toast(error.message || String(error), "err");
      }
    };
    let net = { proxy: "", online_use_proxy: true, nai_use_proxy: false };
    try { net = await api().get("/api/nai/network"); } catch (_) { /* ignore */ }
    const proxyBox = document.getElementById("mProxy");
    const onlineBox = document.getElementById("mOnlineProxy");
    const naiBox = document.getElementById("mNaiProxy");
    if (proxyBox) proxyBox.value = net.proxy || "";
    if (onlineBox) onlineBox.checked = net.online_use_proxy !== false;
    if (naiBox) naiBox.checked = !!net.nai_use_proxy;
    document.getElementById("mSaveNet").onclick = async () => {
      try {
        const saved = await api().post("/api/nai/network", {
          proxy: proxyBox ? proxyBox.value.trim() : "",
          online_use_proxy: !!(onlineBox && onlineBox.checked),
          nai_use_proxy: !!(naiBox && naiBox.checked),
        });
        document.getElementById("mSetStatus").textContent = saved.message || "网络设置已保存";
        document.getElementById("mSetStatus").className = "m-status m-ok";
      } catch (error) {
        document.getElementById("mSetStatus").textContent = error.message || String(error);
        document.getElementById("mSetStatus").className = "m-status m-err";
      }
    };
    const probeBtn = document.getElementById("mProbeNet");
    if (probeBtn) {
      probeBtn.onclick = async () => {
        document.getElementById("mSetStatus").textContent = "正在测在线库…";
        document.getElementById("mSetStatus").className = "m-status";
        try {
          const result = await api().get("/api/nai/aitag/probe");
          const extra = result.detected_proxy ? "  已发现 " + result.detected_proxy : "";
          document.getElementById("mSetStatus").textContent = (result.message || (result.ok ? "在线库已接通" : "在线库暂时打不开")) + extra;
          document.getElementById("mSetStatus").className = result.ok ? "m-status m-ok" : "m-status m-err";
        } catch (error) {
          document.getElementById("mSetStatus").textContent = friendlyError(error);
          document.getElementById("mSetStatus").className = "m-status m-err";
        }
      };
    }
    const verifyBtn = document.getElementById("mVerifyNet");
    if (verifyBtn) {
      verifyBtn.onclick = () => {
        if (window.PhoneApp && typeof window.PhoneApp.openAitagVerify === "function") {
          window.PhoneApp.openAitagVerify();
        } else {
          document.getElementById("mSetStatus").textContent = "装到手机后才能打开在线库验证页。";
          document.getElementById("mSetStatus").className = "m-status";
        }
      };
    }
    if (window.PhoneApp && typeof window.PhoneApp.openSettings === "function") {
      const nativeBtn = document.createElement("button");
      nativeBtn.type = "button";
      nativeBtn.className = "m-ghost";
      nativeBtn.textContent = "打开系统设置页";
      nativeBtn.onclick = openNativeSettings;
      document.getElementById("mSetStatus").insertAdjacentElement("beforebegin", nativeBtn);
    }
  }

  const pickerClose = document.getElementById("mPickerClose");
  if (pickerClose) pickerClose.onclick = closeCharPicker;
  const pairBtn = document.getElementById("mPairBtn");
  if (pairBtn) {
    pairBtn.textContent = isStandalone() ? "设置" : "配对";
    pairBtn.onclick = () => {
      if (isStandalone()) openSettings();
      else location.hash = "#/pair";
    };
  }
  if (isStandalone()) {
    const last = document.querySelector('.m-tabbar a[data-tab="pipeline"]');
    if (last) {
      last.dataset.tab = "gallery";
      last.setAttribute("href", "#/gallery");
      const label = last.querySelector("span");
      if (label) label.textContent = "图库";
    }
    const batch = document.querySelector('.m-tabbar a[data-tab="batch"]');
    if (batch) {
      const label = batch.querySelector("span");
      if (label) label.textContent = "排队";
    }
  }
  window.__NAI_REFRESH__ = () => refreshWriteAccess().finally(render);
  window.addEventListener("hashchange", () => { render(); });
  if (window.visualViewport) {
    const applyKb = () => {
      const vv = window.visualViewport;
      const inset = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
      document.documentElement.style.setProperty("--kb", inset + "px");
    };
    window.visualViewport.addEventListener("resize", applyKb);
    window.visualViewport.addEventListener("scroll", applyKb);
    applyKb();
  }
  restoreToken();
  try { state.lastWorkId = localStorage.getItem(LAST_WORK_KEY) || ""; } catch (_) { /* ignore */ }
  refreshWriteAccess().finally(render);
})();

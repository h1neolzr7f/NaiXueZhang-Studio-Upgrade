(function () {
  const TOKEN_KEY = "nai-mobile-pair-token";
  const QUEUE_KEY = "nai-mobile-online-queue";
  const LAST_WORK_KEY = "nai-mobile-last-work";
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
    slot: null,
    pageIndex: 0,
    busy: false,
  };

  function isStandalone() {
    return !!(window.__NAI_STANDALONE__ || (document.body && document.body.getAttribute("data-standalone") === "1"));
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

  function parseRoute() {
    const hash = String(location.hash || "#/browse").replace(/^#/, "") || "/browse";
    const parts = hash.split("/").filter(Boolean);
    if (parts[0] === "work" && parts[1]) return { name: "work", id: String(parts[1]) };
    if (parts[0] === "work") return { name: "work", id: state.lastWorkId || "" };
    if (parts[0] === "batch") return { name: "batch" };
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
      const onSettings = name === "pair" || name === "settings";
      const onGallery = name === "gallery" && (tab === "gallery" || tab === "pipeline");
      link.classList.toggle("active", tab === name || onGallery || (onSettings && tab === "browse"));
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
    if (isStandalone() && window.PhoneApp && typeof window.PhoneApp.openSettings === "function") {
      window.PhoneApp.openSettings();
      return;
    }
    location.hash = "#/settings";
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

  async function render() {
    state.route = parseRoute();
    markTabs(state.route.name);
    const root = document.getElementById("mApp");
    if (state.route.name === "settings") return renderSettings(root);
    if (state.route.name === "pair") return renderPair(root);
    if (state.route.name === "work") return renderWork(root, state.route.id);
    if (state.route.name === "batch") return renderBatch(root);
    if (state.route.name === "gallery") return renderGallery(root);
    if (state.route.name === "pipeline") return renderPipeline(root);
    return renderBrowse(root);
  }

  async function renderBrowse(root) {
    const standalone = isStandalone();
    root.innerHTML = `
      <section class="m-hero">
        <p class="m-eyebrow">Nai学长工作室 · ${standalone ? "1.5.2 手机独立版" : "手机预览"}</p>
        <h2>在线发现 · 换角出图</h2>
        <p class="m-hint">${standalone
          ? "不遥控电脑。搜 AITag 在线库，点进作品换角，确认后走 NovelAI。写角色和优化咒语用 DeepSeek。"
          : "搜 AITag 在线库，点进作品后换角。默认只要 NAI 图。"}</p>
        <div class="m-quote">凑企鹅：先选图，再点准角色槽。没填 Token 我不会替你出图。</div>
      </section>
      <section class="m-card">
        <h2>在线发现</h2>
        <p class="m-hint">搜 AITag 在线库，点进作品后换角。默认只要 NAI 图。</p>
        <div class="m-row">
          <input id="mSearch" placeholder="角色 / 作品 / 标签" />
          <button type="button" id="mSearchBtn" class="m-primary">搜索</button>
        </div>
        <div class="m-chips" id="mQuickChips"></div>
      </section>
      <div id="mBrowseGrid" class="m-grid"></div>
      <p id="mBrowseStatus" class="m-status">输入关键词后搜索。</p>`;
    [["明日方舟", "明日方舟"], ["高松灯", "高松灯"], ["丰川祥子", "丰川祥子"], ["能天使", "能天使"]].forEach(([label, q]) => {
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
    const run = async () => {
      const q = document.getElementById("mSearch").value.trim();
      const status = document.getElementById("mBrowseStatus");
      status.textContent = "搜索中…";
      try {
        const data = await api().get("/api/nai/aitag/search?q=" + encodeURIComponent(q) + "&page=1&page_size=24&nai_only=true");
        const items = data.items || data.works || [];
        const grid = document.getElementById("mBrowseGrid");
        grid.innerHTML = items.map((item) => {
          const id = String(item.work_id || item.id || "");
          const cover = (item.images && item.images[0] && (item.images[0].thumbnail_url || item.images[0].url))
            || ("/api/nai/aitag/cover/" + encodeURIComponent(id));
          return `<a class="m-work" href="#/work/${encodeURIComponent(id)}">
            <img src="${escapeHtml(cover)}" alt="">
            <span>${escapeHtml(item.title || id)}</span>
          </a>`;
        }).join("") || "";
        status.textContent = items.length ? `找到 ${items.length} 个作品` : "没有结果";
      } catch (error) {
        status.textContent = error.message || String(error);
        status.className = "m-status m-err";
      }
    };
    document.getElementById("mSearchBtn").onclick = run;
    document.getElementById("mSearch").addEventListener("keydown", (event) => {
      if (event.key === "Enter") run();
    });
  }

  async function renderWork(root, workId) {
    if (!workId) {
      root.innerHTML = `<section class="m-card"><h2>换角</h2><p class="m-hint">先在「发现」里点开一张在线作品。</p></section>`;
      return;
    }
    state.lastWorkId = workId;
    try { localStorage.setItem(LAST_WORK_KEY, workId); } catch (_) { /* ignore */ }
    root.innerHTML = `<p class="m-status">加载作品…</p>`;
    try {
      const data = await api().get("/api/nai/aitag/work/" + encodeURIComponent(workId));
      state.work = (isStandalone() && window.StandaloneCore) ? window.StandaloneCore.decorateWork(data) : data;
      state.pageIndex = 0;
      state.slot = (state.work.character_candidates || [])[0] || null;
      paintWork(root);
    } catch (error) {
      root.innerHTML = `<section class="m-card"><h2>换角</h2><p class="m-err">${escapeHtml(error.message || error)}</p></section>`;
    }
  }

  function currentImage() {
    const images = (state.work && state.work.images) || [];
    return images[state.pageIndex] || images[0] || {};
  }

  function paintWork(root) {
    const work = (state.work && state.work.work) || {};
    const images = state.work.images || [];
    const img = currentImage();
    const candidates = (state.work.character_candidates || []).filter((item) => Number(item.image_index || 0) === state.pageIndex);
    const cover = img.thumbnail_url || img.url || ("/api/nai/aitag/cover/" + encodeURIComponent(work.work_id || ""));
    root.innerHTML = `
      <section class="m-card">
        <h2>${escapeHtml(work.title || work.work_id || "作品")}</h2>
        <img class="m-preview" src="${escapeHtml(cover)}" alt="">
        <p class="m-hint">${images.length} 页 · 先点准角色槽，再从明日方舟库或自定义里选人。</p>
        <div class="m-row" id="mPages"></div>
      </section>
      <section class="m-card">
        <h3>角色槽</h3>
        <div class="m-row" id="mSlots"></div>
        <p class="m-hint" id="mSlotHint">还没选槽</p>
      </section>
      <section class="m-card">
        <h3>换成谁</h3>
        <div class="m-row" id="mGenderRow"></div>
        <div class="m-row">
          <input id="mTargetQ" placeholder="阿米娅 / 能天使 / 自定义名" value="${escapeHtml(state.targetQuery || "")}" />
          <button type="button" id="mTargetBtn" class="m-ghost">搜明日方舟</button>
        </div>
        <div id="mTargets" class="m-list" style="margin-top:8px"></div>
        <p class="m-hint" id="mTargetHint">${state.targetLabel ? ("已选 " + state.targetLabel) : "默认明日方舟库，也可以保存自定义"}</p>
        <div class="m-row" style="margin-top:10px">
          <input id="mCustomName" placeholder="自定义名字" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mCustomIdentity" placeholder="身份标签，如 my_oc_(oc)" />
        </div>
        <div class="m-row" style="margin-top:8px">
          <input id="mCustomAppear" placeholder="外观，如 white_hair, red_eyes" />
        </div>
        <textarea id="mCustomCaption" placeholder="完整槽位咒语（可选，会保留原槽动作）" style="margin-top:8px"></textarea>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mCustomUse" class="m-ghost">用这次不保存</button>
          <button type="button" id="mCustomSave" class="m-primary">保存自定义</button>
        </div>
        <div class="m-quote" style="margin-top:12px">小祥：也可以用中文描述角色，DeepSeek 帮你写成槽位 tag。这步不扣 Anlas。</div>
        <textarea id="mDescribe" placeholder="例如：粉头发红眼睛的阿米娅风 OC，短外套" style="margin-top:8px"></textarea>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mDescribeBtn" class="m-ghost">DeepSeek 写角色</button>
        </div>
      </section>
      <section class="m-card">
        <div class="m-row">
          <button type="button" id="mApplyOne" class="m-primary">本页换角</button>
          <button type="button" id="mApplyAll" class="m-ghost">全部页换同性别</button>
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mOptimize" class="m-ghost">DeepSeek 优化草稿</button>
        </div>
        <div class="m-row" style="margin-top:8px">
          <button type="button" id="mGenOne" class="m-primary">生成本页</button>
          <button type="button" id="mQueueBtn" class="m-ghost">加入批量</button>
        </div>
        <p id="mWorkStatus" class="m-status"></p>
        <img id="mGenImg" class="m-preview hidden" alt="生成结果">
      </section>`;
    const pages = document.getElementById("mPages");
    images.forEach((_, index) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "m-chip" + (index === state.pageIndex ? " active" : "");
      chip.textContent = "P" + (index + 1);
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
    const genderRow = document.getElementById("mGenderRow");
    [["female", "明日方舟·女"], ["male", "明日方舟·男"]].forEach(([value, label]) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "m-chip" + (state.targetGender === value ? " active" : "");
      chip.textContent = label;
      chip.onclick = () => { state.targetGender = value; paintWork(root); };
      genderRow.appendChild(chip);
    });
    document.getElementById("mTargetBtn").onclick = searchTargets;
    document.getElementById("mCustomUse").onclick = () => useCustomRecord(false);
    document.getElementById("mCustomSave").onclick = () => useCustomRecord(true);
    document.getElementById("mDescribeBtn").onclick = describeWithDeepSeek;
    document.getElementById("mOptimize").onclick = optimizeCurrentDraft;
    document.getElementById("mApplyOne").onclick = () => applyDraft({ allPages: false, genderScope: "" });
    document.getElementById("mApplyAll").onclick = () => applyDraft({
      allPages: true,
      genderScope: (state.slot && state.slot.role === "male") ? "male" : "female",
    });
    document.getElementById("mGenOne").onclick = generateCurrent;
    document.getElementById("mQueueBtn").onclick = enqueueCurrent;
    searchTargets();
  }

  function pickTarget(item) {
    state.targetId = item.reference_id;
    state.targetLabel = item.label;
    state.targetRecord = (window.StandaloneCore && item.record)
      ? window.StandaloneCore.targetRecord(item.record, item.reference_id)
      : item.record || null;
    const hint = document.getElementById("mTargetHint");
    if (hint) hint.textContent = "已选 " + item.label;
  }

  function customDraftFromForm() {
    const name = (document.getElementById("mCustomName") && document.getElementById("mCustomName").value.trim())
      || (document.getElementById("mTargetQ") && document.getElementById("mTargetQ").value.trim());
    if (!name) throw new Error("先写自定义名字");
    const identityRaw = document.getElementById("mCustomIdentity") ? document.getElementById("mCustomIdentity").value : "";
    const appearRaw = document.getElementById("mCustomAppear") ? document.getElementById("mCustomAppear").value : "";
    const caption = document.getElementById("mCustomCaption") ? document.getElementById("mCustomCaption").value.trim() : "";
    const identity = String(identityRaw || "").split(",").map((item) => item.trim()).filter(Boolean);
    if (!identity.length) identity.push(name);
    const appearance = String(appearRaw || "").split(",").map((item) => item.trim()).filter(Boolean);
    return {
      id: "typed",
      label: name,
      gender: state.targetGender === "male" ? "male" : "female",
      kind: "oc",
      identity: identity,
      appearance: appearance,
      char_caption: caption,
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
          toast(saved.message || "已保存自定义角色");
        } else {
          const all = loadLocalCustom();
          record.id = "c" + Date.now();
          all.unshift(record);
          try { localStorage.setItem("nai-mobile-custom-chars", JSON.stringify(all.slice(0, 80))); } catch (_) { /* ignore */ }
          referenceId = "custom:" + record.gender + ":" + record.id;
          toast("已保存自定义角色");
        }
      }
      pickTarget({ reference_id: referenceId, label: "自定义：" + record.label, record: record });
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

  async function describeWithDeepSeek() {
    const box = document.getElementById("mDescribe");
    const text = box ? box.value.trim() : "";
    if (!text) {
      toast("先写角色描述", "err");
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
      if (status) status.textContent = "DeepSeek 正在写角色槽…";
      const result = await api().post("/api/mobile/char-describe", {
        text: text,
        gender: state.targetGender,
      });
      if (!result || Number(result.generation_calls) !== 0) {
        throw new Error("角色草稿未通过零生成安全检查");
      }
      const record = result.item || result.record;
      if (!record) throw new Error(result.detail || "DeepSeek 没有返回角色");
      if (document.getElementById("mCustomName")) document.getElementById("mCustomName").value = record.label || "";
      if (document.getElementById("mCustomIdentity")) document.getElementById("mCustomIdentity").value = (record.identity || []).join(", ");
      if (document.getElementById("mCustomAppear")) document.getElementById("mCustomAppear").value = (record.appearance || []).join(", ");
      if (document.getElementById("mCustomCaption")) document.getElementById("mCustomCaption").value = record.char_caption || "";
      pickTarget({
        reference_id: "custom:" + (record.gender || state.targetGender) + ":typed",
        label: "DeepSeek：" + (record.label || "自定义"),
        record: record,
      });
      if (status) {
        status.textContent = result.message || "角色槽已写好，还没扣 Anlas";
        status.className = "m-status m-ok";
      }
    } catch (error) {
      toast(error.message || String(error), "err");
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
    host.textContent = "搜索中…";
    try {
      const [ark, customItems] = await Promise.all([
        api().get("/api/plugin/char-swap/ark-library?gender=" + gender + "&q=" + encodeURIComponent(q) + "&limit=20"),
        listCustom(gender),
      ]);
      const items = [];
      (customItems || []).forEach((item) => {
        items.push({
          reference_id: "custom:" + (item.gender || gender) + ":" + item.id,
          label: "自定义：" + (item.label || item.id),
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
      if (q) {
        items.unshift({
          reference_id: "custom:" + gender + ":typed",
          label: "自定义：" + q,
          record: { id: "typed", label: q, gender: gender, kind: "oc", identity: [q], appearance: [], tag: q },
        });
      }
      host.innerHTML = "";
      items.slice(0, 20).forEach((item) => {
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
      if (!items.length) host.innerHTML = '<p class="m-hint">没有匹配角色，可在下方保存自定义</p>';
    } catch (error) {
      host.innerHTML = '<p class="m-err">' + escapeHtml(error.message || error) + "</p>";
    }
  }

  async function applyDraft(options) {
    if (!requireWrite() || state.busy) return;
    const workId = String((state.work && state.work.work && state.work.work.work_id) || "");
    if (!workId) return;
    if (!options.allPages && !state.targetId) {
      toast("先选目标角色", "err");
      return;
    }
    if (options.allPages && !await confirmAction("全部页换女角", "会给每一页做零费用草稿，不会出图。")) return;
    const status = document.getElementById("mWorkStatus");
    status.textContent = "正在写草稿…";
    state.busy = true;
    try {
      if (isStandalone() && window.StandaloneCore) {
        const compileOpts = {
          image_index: state.pageIndex,
          slot_index: Number((state.slot && state.slot.slot_index) || 0),
          candidate_id: options.allPages ? "" : String((state.slot && state.slot.candidate_id) || ""),
          gender_scope: options.genderScope || "",
          target_record: state.targetRecord,
          target_reference_id: state.targetId,
        };
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
        status.textContent = result.message || "草稿已就绪，还没扣 Anlas";
        status.className = "m-status m-ok";
        return;
      }
      const payload = {
        image_index: state.pageIndex,
        slot_index: Number((state.slot && state.slot.slot_index) || 0),
        all_pages: !!options.allPages,
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
      status.textContent = result.message || "草稿已就绪，还没扣 Anlas";
      status.className = "m-status m-ok";
    } catch (error) {
      status.textContent = error.message || String(error);
      status.className = "m-status m-err";
    } finally {
      state.busy = false;
    }
  }

  async function generateCurrent() {
    if (!requireWrite() || state.busy) return;
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
    if (!await confirmAction("生成本页", "默认免费档。点确认后才会调用 NovelAI。")) return;
    await generateEntry(entry, state.pageIndex, document.getElementById("mWorkStatus"), document.getElementById("mGenImg"));
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
          source_gallery_id: "aitag-online",
          source_title: work.title || "",
          source_thumb: img.thumbnail_url || img.url || "",
          page_index: pageIndex,
          copies: 1,
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
    root.innerHTML = `
      <section class="m-card">
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
    document.getElementById("mClearOnline").onclick = () => { saveQueue([]); renderBatch(root); };
    document.getElementById("mRunOnline").onclick = runOnlineBatch;
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
        ? "生成成功后，手机把图存进系统相册「Nai学长工作室」。手机不做超分/打码。"
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
      const items = data.items || [];
      const auto = !!(cfg.config && cfg.config.auto_after_generate);
      root.innerHTML = `
        <section class="m-hero">
          <p class="m-eyebrow">生成库</p>
          <h2>本机成果</h2>
          <p class="m-hint">只存在这台手机。生成成功后可进系统相册「Nai学长工作室」。手机不做超分 / 打码。</p>
        </section>
        <section class="m-card">
          <h2>流水线</h2>
          <p>生成后自动存相册：<strong class="${auto ? "m-ok" : "m-err"}">${auto ? "已开" : "未开"}</strong></p>
          <div class="m-row">
            <button type="button" id="mPipeRun" class="m-primary">补存到相册</button>
            <button type="button" id="mPipeAuto" class="m-ghost">${auto ? "关闭自动" : "打开自动"}</button>
          </div>
          <p id="mPipeStatus" class="m-status"></p>
        </section>
        <div class="m-grid" id="mOutGrid"></div>
        <p class="m-status">${items.length ? ("共 " + items.length + " 张") : "还没有生成图。先在发现里换角出图。"}</p>`;
      const grid = document.getElementById("mOutGrid");
      grid.innerHTML = items.map((item) => `
        <a class="m-work" href="${escapeHtml(item.image_url || "")}" target="_blank" rel="noopener">
          <img src="${escapeHtml(item.image_url || item.thumb || "")}" alt="">
          <span>${escapeHtml(item.title || item.work_id || item.id || "生成图")}</span>
        </a>`).join("");
      document.getElementById("mPipeRun").onclick = async () => {
        if (!await confirmAction("补存到相册", "只把本机已生成图补进相册，不会重新出图。")) return;
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
        if (!await confirmAction(auto ? "关闭自动存相册" : "打开自动存相册", "只改这台手机的开关，不会立刻出图。")) return;
        await api().post("/api/pipeline/config", { auto_after_generate: !auto });
        renderGallery(root);
      };
    } catch (error) {
      root.innerHTML = `<section class="m-card"><h2>成果</h2><p class="m-err">${escapeHtml(error.message || error)}</p></section>`;
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
        <p class="m-hint">独立软件，不遥控电脑。NovelAI 负责出图，DeepSeek 负责写角色和优化咒语。密钥只存在这台手机。</p>
        <p>NovelAI：<strong class="${nai.has_token ? "m-ok" : "m-err"}">${nai.has_token ? "已配置 Token" : "还没填 Token"}</strong></p>
        <textarea id="mToken" placeholder="粘贴 NovelAI Token（pst- 或 Bearer 后面那段）" autocomplete="off"></textarea>
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
        <p id="mSetStatus" class="m-status"></p>
      </section>`;
    document.getElementById("mSaveToken").onclick = async () => {
      const token = document.getElementById("mToken").value.trim();
      if (!token) { toast("先粘贴 Token", "err"); return; }
      if (!await confirmAction("保存 Token", "只写进本机应用存储，不会上传到电脑。")) return;
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
  }

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
      if (label) label.textContent = "成果";
    }
  }
  window.__NAI_REFRESH__ = () => refreshWriteAccess().finally(render);
  window.addEventListener("hashchange", () => { render(); });
  restoreToken();
  try { state.lastWorkId = localStorage.getItem(LAST_WORK_KEY) || ""; } catch (_) { /* ignore */ }
  refreshWriteAccess().finally(render);
})();

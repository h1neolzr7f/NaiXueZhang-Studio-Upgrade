import { state, saveCurrentDraftToCache, loadDraftFromCache, clearDraftCacheForWork, BATCH_MAX_DEFAULT, normalizeWorkId, normalizeGalleryId } from "./state.js?v=f80b97d795";
import { api, $, deepClone, setMsg, flashMsg, copyText, loadPluginConfig, esc } from "./api.js?v=01f205facd";
import { fillStylePresetSelects } from "./presets.js?v=f16dbe971d";
import { buildRecipeFromForm, syncBatchTargetSlot } from "./batch_recipe.js?v=cde99cf67e";
import { draftCommentForPage, getBatchMax } from "./draft_helpers.js?v=71bb7ead54";

const BATCH_KEY = "charSwapBatchQueue";
const BATCH_MODE_KEY = "charSwapBatchMode";

export function currentBatchGalleryId(value) {
    let galleryId = String(value || "").trim();
    if (!galleryId) {
      try {
        const params = new URL(window.location.href).searchParams;
        galleryId = params.get("gallery") || params.get("gallery_id") || "";
      } catch { }
    }
    return normalizeGalleryId(galleryId || state.galleryId || "site");
  }

function updateBatchCapLabel() {
    const el = document.getElementById("charSwapBatchCap");
    if (el) el.textContent = `上限 ${getBatchMax()}`;
  }

export function loadBatchQueue() {
    try {
      const raw = localStorage.getItem(BATCH_KEY);
      const list = raw ? JSON.parse(raw) : [];
      return Array.isArray(list)
        ? list.map((item) => ({
            ...item,
            gallery_id: currentBatchGalleryId(item && item.gallery_id ? item.gallery_id : "site"),
          }))
        : [];
    } catch {
      return [];
    }
  }

export function saveBatchQueue(list) {
    try {
      localStorage.setItem(BATCH_KEY, JSON.stringify(list));
    } catch { }
    updateBatchBadge();
    updateQuickAddHint();
  }

export function isBatchMode() {
    try {
      return localStorage.getItem(BATCH_MODE_KEY) === "1";
    } catch {
      return false;
    }
  }

export function setBatchMode(on) {
    try {
      localStorage.setItem(BATCH_MODE_KEY, on ? "1" : "0");
    } catch { }
    document.querySelectorAll(".char-swap-batch-check").forEach((el) => {
      el.style.display = on ? "flex" : "none";
    });
    updateBatchBadge();
  }

export function batchKey(workId, pageIndex, galleryId) {
    return `${currentBatchGalleryId(galleryId)}:${normalizeWorkId(workId)}:${Number(pageIndex || 0)}`;
  }

export function refreshBatchCardChecks() {
    const galleryId = currentBatchGalleryId();
    const inQ = new Set(loadBatchQueue().map((x) => batchKey(x.work_id, x.page_index, x.gallery_id)));
    document.querySelectorAll(".char-swap-batch-check").forEach((chk) => {
      const card = chk.closest(".card");
      const wid = card && card.dataset.workId;
      if (!wid) return;
      chk.classList.toggle("active", inQ.has(batchKey(wid, 0, galleryId)));
    });
  }

export function setQuickAddStatus(text, ok) {
    const el = document.getElementById("charSwapQuickStatus");
    if (!el) return;
    el.className = "char-swap-quick-status" + (ok === true ? " ok" : ok === false ? " fail" : "");
    el.textContent = text || "";
  }

export function updateQuickAddHint() {
    const hint = document.getElementById("charSwapQuickHint");
    const fab = document.getElementById("charSwapQuickFab");
    const listBox = document.getElementById("charSwapQuickAddList");
    const detailBox = document.getElementById("charSwapQuickAddDetail");
    const workIdEl = document.getElementById("charSwapQuickWorkId");
    const detailHint = document.getElementById("charSwapQuickDetailHint");
    const gal = window.AitagGallery;
    const room = Math.max(0, getBatchMax() - loadBatchQueue().length);
    if (fab) fab.style.display = "";
    const onList = gal && typeof gal.getListContext === "function" && gal.getListContext().isListView;
    if (listBox) listBox.classList.toggle("hidden", !onList);
    if (detailBox) detailBox.classList.toggle("hidden", onList || !state.workId);
    if (!onList && state.workId) {
      if (workIdEl) workIdEl.textContent = String(state.workId);
      const n = Math.max(1, Number(state.imagePageCount) || 1);
      if (detailHint) {
        detailHint.textContent = n > 1
          ? `本作品共 ${n} 张图（p0～p${n - 1}），将全部加入批量队列`
          : "本作品仅 1 张图，加入批量队列";
      }
      if (hint) {
        hint.textContent = `当前在作品页 · 队列还可加 ${room} 张`;
      }
      return;
    }
    if (!hint) return;
    if (!onList) {
      hint.textContent = "打开作品页 /i/xxx 可批量本作品全部图片";
      return;
    }
    const ctx = gal.getListContext();
    hint.textContent = `图库列表第 ${ctx.page} 页 · ${ctx.currentPageCount} 个作品 · 队列还可加 ${room} 张`;
  }

export function buildBatchEntry(workId, pageIndex, title, galleryId) {
    const entry = {
      gallery_id: currentBatchGalleryId(galleryId),
      work_id: normalizeWorkId(workId),
      page_index: Number(pageIndex || 0),
      title: String(title || "").trim(),
    };
    const draft = draftCommentForPage(workId, pageIndex);
    if (draft && draft.v4_prompt) {
      entry.patched_comment = draft;
      entry.from_draft = true;
    }
    return entry;
  }

export function mapQueueToTargets() {
    return loadBatchQueue().map((x) => {
      const t = {
        gallery_id: x.gallery_id,
        work_id: x.work_id,
        page_index: x.page_index || 0,
      };
      if (x.patched_comment && x.patched_comment.v4_prompt) {
        t.patched_comment = x.patched_comment;
        t.frozen_comment = true;
      }
      return t;
    });
  }

export function addAllWorkPagesToBatch(workId, pageCount, meta) {
    const id = normalizeWorkId(workId);
    const n = Math.max(1, Number(pageCount) || 1);
    if (!id) return { added: 0, skipped: 0, draftCount: 0, total: loadBatchQueue().length };
    saveCurrentDraftToCache();
    const title = (meta && meta.title) || state.workTitle || "";
    const galleryId = currentBatchGalleryId(meta && meta.gallery_id);
    const entries = [];
    for (let i = 0; i < n; i += 1) {
      entries.push(buildBatchEntry(id, i, title ? `${title} p${i}` : `#${id} p${i}`, galleryId));
    }
    const draftInRequest = entries.filter((e) => e.from_draft).length;
    return { ...addManyToBatch(entries), draftInRequest };
  }

export function addToBatch(workId, pageIndex, meta) {
    saveCurrentDraftToCache();
    const title = (meta && meta.title) || "";
    const galleryId = currentBatchGalleryId(meta && meta.gallery_id);
    return addManyToBatch([buildBatchEntry(workId, pageIndex, title, galleryId)]).added > 0;
  }

export function addManyToBatch(entries, opts) {
    const limit = Math.min(
      getBatchMax(),
      opts && opts.max ? Number(opts.max) : getBatchMax()
    );
    const queue = loadBatchQueue();
    const seen = new Set(queue.map((x) => batchKey(x.work_id, x.page_index, x.gallery_id)));
    let added = 0;
    let skipped = 0;
    let updated = 0;
    let capped = false;
    const list = Array.isArray(entries) ? entries : [];
    for (const raw of list) {
      if (queue.length >= limit) {
        capped = true;
        break;
      }
      const id = normalizeWorkId(raw && (raw.work_id != null ? raw.work_id : raw.id));
      if (!id) continue;
      const pi = Number((raw && raw.page_index) || 0);
      const galleryId = currentBatchGalleryId(raw && raw.gallery_id);
      const key = batchKey(id, pi, galleryId);
      if (seen.has(key)) {
        if (raw && raw.patched_comment) {
          const ex = queue.find((x) => batchKey(x.work_id, x.page_index, x.gallery_id) === key);
          if (ex) {
            ex.patched_comment = raw.patched_comment;
            ex.from_draft = !!raw.from_draft;
            if (raw.title) ex.title = String(raw.title).trim();
            ex.added_at = Date.now();
            updated += 1;
          }
        }
        skipped += 1;
        continue;
      }
      const item = {
        gallery_id: galleryId,
        work_id: id,
        page_index: pi,
        title: String((raw && (raw.title || raw.name)) || "").trim(),
        added_at: Date.now(),
      };
      if (raw && raw.patched_comment) {
        item.patched_comment = raw.patched_comment;
        item.from_draft = !!raw.from_draft;
      }
      queue.push(item);
      seen.add(key);
      added += 1;
    }
    saveBatchQueue(queue);
    renderBatchQueueList();
    refreshBatchCardChecks();
    updateQuickAddHint();
    const draftCount = queue.filter((x) => x.from_draft).length;
    return {
      added,
      skipped,
      updated,
      draftCount,
      capped,
      total: queue.length,
      room: Math.max(0, getBatchMax() - queue.length),
    };
  }

export function removeFromBatch(workId, pageIndex, galleryId) {
    const id = normalizeWorkId(workId);
    const pi = Number(pageIndex || 0);
    const gid = currentBatchGalleryId(galleryId);
    const queue = loadBatchQueue().filter(
      (x) => batchKey(x.work_id, x.page_index, x.gallery_id) !== batchKey(id, pi, gid)
    );
    saveBatchQueue(queue);
    renderBatchQueueList();
    refreshBatchCardChecks();
    updateQuickAddHint();
  }

export function removeWorkFromBatch(workId, galleryId) {
    const id = normalizeWorkId(workId);
    const gid = currentBatchGalleryId(galleryId);
    const queue = loadBatchQueue().filter(
      (x) => !(normalizeWorkId(x.work_id) === id && currentBatchGalleryId(x.gallery_id) === gid)
    );
    saveBatchQueue(queue);
    renderBatchQueueList();
    refreshBatchCardChecks();
    updateQuickAddHint();
  }

export function pruneBatchQueueFromResults(items) {
    if (!Array.isArray(items) || !items.length) return { removed: 0, kept: 0 };
    const okKeys = new Set(
      items
        .filter((it) => it && it.ok)
        .map((it) => batchKey(it.work_id, it.page_index || 0, it.gallery_id))
    );
    if (!okKeys.size) return { removed: 0, kept: loadBatchQueue().length };
    const queue = loadBatchQueue();
    const next = queue.filter((x) => !okKeys.has(batchKey(x.work_id, x.page_index || 0, x.gallery_id)));
    const removed = queue.length - next.length;
    if (removed > 0) {
      saveBatchQueue(next);
      renderBatchQueueList();
      refreshBatchCardChecks();
      updateQuickAddHint();
    }
    return { removed, kept: next.length };
  }

export function ensureListViewForQuickAdd() {
    const gal = window.AitagGallery;
    if (!gal || typeof gal.isListView !== "function" || !gal.isListView()) {
      throw new Error("请先返回图库列表（点左上角返回）");
    }
  }

export async function quickAddCurrentPageWorks() {
    ensureListViewForQuickAdd();
    const gal = window.AitagGallery;
    const ctx = gal.getListContext ? gal.getListContext() : { page: 1 };
    const galleryId = currentBatchGalleryId();
    const works = gal.getCurrentPageWorks ? gal.getCurrentPageWorks() : [];
    if (!works.length) {
      throw new Error(`第 ${ctx.page || 1} 页没有可加入的作品`);
    }
    if (getBatchMax() - loadBatchQueue().length <= 0) {
      throw new Error(`队列已满（最多 ${getBatchMax()} 张）`);
    }
    const res = addManyToBatch(
      works.map((w) => ({ gallery_id: galleryId, work_id: w.id, page_index: 0, title: w.title })),
      { max: getBatchMax() }
    );
    setQuickAddStatus(
      `列表第 ${ctx.page || 1} 页：加入 ${res.added} 个作品${res.skipped ? `，跳过重复 ${res.skipped}` : ""}`,
      true
    );
    return res;
  }

export function updateBatchBadge() {
    const el = document.getElementById("charSwapBatchBadge");
    if (!el) return;
    const n = loadBatchQueue().length;
    el.textContent = n ? `批量(${n})` : "批量(0)";
    el.classList.toggle("has-items", n > 0);
  }

export function renderBatchQueueList() {
    const listEl = document.getElementById("charSwapBatchList");
    if (!listEl) return;
    const queue = loadBatchQueue();
    if (!queue.length) {
      listEl.innerHTML = '<div class="char-swap-batch-empty">队列为空。<br>· 在 <b>/i/作品号</b> 页点「全部图片加入批量」<br>· 或在图库列表点「加入列表本页」</div>';
      return;
    }
    listEl.innerHTML = queue.map((item) => `
      <div class="char-swap-batch-item" data-wid="${esc(item.work_id)}" data-pi="${esc(item.page_index || 0)}" data-gallery-id="${esc(item.gallery_id)}">
        <a href="/i/${encodeURIComponent(item.work_id)}?gallery=${encodeURIComponent(item.gallery_id)}" target="_blank" rel="noopener">#${esc(item.work_id)}</a>
        <span class="meta">${esc(item.gallery_id)} · p${esc(item.page_index || 0)}${item.from_draft ? " · 草稿" : ""}</span>
        <button type="button" class="char-swap-btn char-swap-batch-rm">移除</button>
      </div>`).join("");
    listEl.querySelectorAll(".char-swap-batch-rm").forEach((btn) => {
      btn.addEventListener("click", () => {
        const row = btn.closest(".char-swap-batch-item");
        if (!row) return;
        removeFromBatch(row.dataset.wid, row.dataset.pi, row.dataset.galleryId);
        renderBatchQueueList();
      });
    });
  }

export async function pollBatchStatus() {
    try {
      const res = await api("/api/plugin/char-swap/batch/status");
      const b = res.batch || {};
      const prog = document.getElementById("charSwapBatchProgress");
      const log = document.getElementById("charSwapBatchLog");
      if (prog) {
        const pct = b.total ? Math.round((b.done / b.total) * 100) : 0;
        prog.textContent = `${b.message || b.status || "—"} · ${b.done || 0}/${b.total || 0} (${pct}%)`;
      }
      if (log && Array.isArray(b.items)) {
        log.textContent = b.items.slice(-12).map((it) => {
          const mark = it.ok ? "✓" : (it.deferred ? "…" : "✗");
          const round = it.retry_round ? ` r${it.retry_round}` : "";
          return `${mark} ${it.work_id}${round}: ${it.message || it.summary || ""}`;
        }).join("\n");
      }
      const status = b.status || "idle";
      if (status === "running") {
        state.batchPollTimer = setTimeout(pollBatchStatus, 2000);
      } else if (
        state.lastBatchStatus === "running" &&
        (status === "done" || status === "cancelled")
      ) {
        const prune = pruneBatchQueueFromResults(b.items || []);
        if (prog && status === "done" && prune.removed > 0) {
          const failN = Number(b.fail_count) || 0;
          const extra = failN > 0
            ? ` · 失败 ${failN} 项仍保留在队列，可点「批量生成」稍后重试`
            : "";
          prog.textContent = `${b.message || "完成"} · 已从队列移除 ${prune.removed} 项成功${extra}`;
        }
      }
      state.lastBatchStatus = status;
      if (state.workId) refreshGenSidebar(state.workId);
    } catch {
      state.batchPollTimer = setTimeout(pollBatchStatus, 4000);
    }
  }

export async function startBatch(opts) {
      const queue = loadBatchQueue();
      if (!queue.length) { alert("批量队列为空"); return; }
      await loadPluginConfig();
      const recipe = buildRecipeFromForm();
      const res = await api("/api/plugin/char-swap/batch/run", {
        method: "POST",
        body: JSON.stringify({
          targets: mapQueueToTargets(),
          recipe,
          force_free: document.getElementById("batchForceFree").checked,
          generate: opts.generate !== false,
          preview_only: !!opts.preview_only,
        }),
      });
      if (!res.ok) throw new Error(res.message || "启动失败");
      if (state.batchPollTimer) clearTimeout(state.batchPollTimer);
      pollBatchStatus();
      return res;
    }

export function unmountGenSidebar() {
    if (state.genSidebarTimer) {
      clearTimeout(state.genSidebarTimer);
      state.genSidebarTimer = null;
    }
    if (state.batchPollTimer) {
      clearTimeout(state.batchPollTimer);
      state.batchPollTimer = null;
    }
    genSidebarPoll.noGroup = false;
    genSidebarPoll.busy = false;
    const el = document.getElementById("charSwapGenSidebar");
    if (el) el.remove();
    document.getElementById("detailView")?.classList.remove("has-gen-sidebar");
  }

export function openGenLightbox(url) {
    if (!url) return;
    const backdrop = document.createElement("div");
    backdrop.className = "char-swap-gen-lightbox";
    const img = document.createElement("img");
    img.src = url;
    img.alt = "试生成预览";
    backdrop.replaceChildren(img);
    backdrop.addEventListener("click", () => backdrop.remove());
    document.body.appendChild(backdrop);
  }

export async function deleteGenThumb(imageId, workId) {
    if (!confirm(`删除这张生成图？`)) return;
    await api(`/api/generated/item/${encodeURIComponent(imageId)}`, { method: "DELETE" });
    if (workId) await refreshGenSidebar(workId);
  }

export async function refreshGenSidebar(workId) {
    const statusEl = document.getElementById("charSwapGenStatus");
    const listEl = document.getElementById("charSwapGenList");
    const coverEl = document.getElementById("charSwapGenCover");
    const countEl = document.getElementById("charSwapGenCount");
    const linkEl = document.getElementById("charSwapGenOpenAll");
    if (!statusEl || !listEl) return;

    const wid = normalizeWorkId(workId);
    let statusText = "空闲";
    let statusOk = true;
    let items = [];

    try {
      const [queueRes, batchRes] = await Promise.all([
        api("/api/nai/queue").catch(() => ({ queue: {} })),
        api("/api/plugin/char-swap/batch/status").catch(() => ({ batch: {} })),
      ]);

      const queue = queueRes.queue || {};
      const batch = batchRes.batch || {};
      const busyForWork =
        (queue.status === "running" && normalizeWorkId(queue.work_id) === wid) ||
        (batch.status === "running" && normalizeWorkId(batch.current_work_id) === wid) ||
        (state.generating && state.workId === wid);
      genSidebarPoll.busy = busyForWork;
      if (busyForWork) genSidebarPoll.noGroup = false;

      if (queue.status === "running" && normalizeWorkId(queue.work_id) === wid) {
        statusText = queue.message || "正在生图…";
        statusOk = true;
      } else if (batch.status === "running" && normalizeWorkId(batch.current_work_id) === wid) {
        statusText = batch.message || "批量生成中…";
        statusOk = true;
      } else if (state.generating && state.workId === wid) {
        statusText = "单张试生成中…";
        statusOk = true;
      } else if (queue.status === "error" && normalizeWorkId(queue.work_id) === wid) {
        statusText = queue.message || "生图失败";
        statusOk = false;
      }

      let genRes = null;
      if (!genSidebarPoll.noGroup || busyForWork) {
        const galleryId = String(
          (typeof currentBatchGalleryId === "function" ? currentBatchGalleryId() : "")
          || state.galleryId
          || "site"
        ).trim() || "site";
        // Work-scoped group includes batch run:* series after backend aggregate match.
        const groupKey = galleryId === "site"
          ? String(wid)
          : `gallery:${galleryId}:${wid}`;
        genRes = await ApiClient.get(`/api/generated/${encodeURIComponent(groupKey)}`).catch(() => null);
        if (!genRes) {
          genSidebarPoll.noGroup = true;
        } else {
          genSidebarPoll.noGroup = false;
        }
      }

      if (genRes && genRes.group) {
        items = Array.isArray(genRes.group.items) ? genRes.group.items : [];
        if (items.length) genSidebarPoll.noGroup = false;
      }
      const gid = String(wid);
      const liveMap = new Map((items || []).map((it) => [it.id, { ...it }]));
      for (const bi of batch.items || []) {
        if (!bi.ok || !bi.image_url) continue;
        if (String(bi.work_id != null ? bi.work_id : "standalone") !== gid) continue;
        const fn = String(bi.filename || "").replace(/\.png$/i, "");
        const id = fn || String(bi.image_url || "").split("/").pop().replace(/\.png$/i, "").split("?")[0];
        if (!id || liveMap.has(id)) continue;
        liveMap.set(id, {
          id,
          image_url: bi.image_url,
          processed_url: bi.processed_url || "",
          work_id: bi.work_id,
          created_at: batch.finished_at || batch.started_at || "",
          _live: true,
        });
      }
      items = Array.from(liveMap.values()).sort(
        (a, b) => String(b.created_at || b.id).localeCompare(String(a.created_at || a.id))
      );
      if (items.length) genSidebarPoll.noGroup = false;
    } catch (e) {
      statusText = e.message || "加载失败";
      statusOk = false;
    }

    statusEl.className = "char-swap-gen-status" + (statusOk ? "" : " fail");
    statusEl.textContent = statusText;
    if (countEl) countEl.textContent = String(items.length);
    if (linkEl) linkEl.href = `/generated?g=${wid}`;

    if (coverEl) coverEl.innerHTML = "";
    if (!items.length) {
      listEl.innerHTML = '<div class="char-swap-gen-empty">暂无生成图</div>';
      return;
    }

    const cover = items[0];
    const rest = items.slice(1, 25);
    if (coverEl && cover) {
      const wrap = document.createElement("div");
      wrap.className = "char-swap-gen-cover-wrap";
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = (cover.image_url || "") + "?t=" + (cover.created_at || "c");
      img.alt = "封面";
      img.addEventListener("click", () => openGenLightbox(cover.image_url));
      wrap.appendChild(img);
      const del = document.createElement("button");
      del.type = "button";
      del.className = "char-swap-gen-del";
      del.textContent = "删";
      del.title = "删除封面图";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteGenThumb(cover.id, wid).catch((err) => alert(err.message));
      });
      wrap.appendChild(del);
      coverEl.appendChild(wrap);
    }

    listEl.innerHTML = "";
    if (!rest.length) {
      listEl.innerHTML = '<div class="char-swap-gen-empty">仅 1 张（封面）</div>';
      return;
    }
    rest.forEach((item, idx) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "char-swap-gen-thumb";
      btn.title = (item.created_at || "").replace("T", " ").slice(0, 16);
      const img = document.createElement("img");
      img.loading = "lazy";
      img.src = (item.image_url || "") + "?t=" + (item.created_at || idx);
      img.alt = item.id || "generated";
      btn.appendChild(img);
      btn.addEventListener("click", () => openGenLightbox(item.image_url));
      const del = document.createElement("span");
      del.className = "char-swap-gen-del-mini";
      del.textContent = "×";
      del.title = "删除";
      del.addEventListener("click", (e) => {
        e.stopPropagation();
        deleteGenThumb(item.id, wid).catch((err) => alert(err.message));
      });
      btn.appendChild(del);
      listEl.appendChild(btn);
    });
  }

export function genSidebarPollDelay() {
    if (genSidebarPoll.busy) return 1500;
    if (genSidebarPoll.noGroup) return 30000;
    return 5000;
  }

export function scheduleGenSidebarPoll(workId) {
    if (state.genSidebarTimer) clearTimeout(state.genSidebarTimer);
    if (document.hidden) {
      state.genSidebarTimer = setTimeout(() => scheduleGenSidebarPoll(workId), 5000);
      return;
    }
    state.genSidebarTimer = setTimeout(async () => {
      if (!state.workId || normalizeWorkId(state.workId) !== normalizeWorkId(workId)) return;
      await refreshGenSidebar(workId);
      scheduleGenSidebarPoll(workId);
    }, genSidebarPollDelay());
  }

export function mountGenSidebar(workId) {
    unmountGenSidebar();
    const detailView = document.getElementById("detailView");
    if (!detailView) return;

    const aside = document.createElement("aside");
    aside.id = "charSwapGenSidebar";
    aside.className = "char-swap-gen-sidebar";
    aside.innerHTML = `
      <div class="char-swap-gen-head">
        <strong>生成预览</strong>
        <span id="charSwapGenCount" class="char-swap-gen-count">0</span>
      </div>
      <div id="charSwapGenStatus" class="char-swap-gen-status">加载中…</div>
      <div id="charSwapGenCover" class="char-swap-gen-cover"></div>
      <div id="charSwapGenList" class="char-swap-gen-list"></div>
      <a id="charSwapGenOpenAll" class="char-swap-gen-link" href="/generated" target="_blank" rel="noopener">打开生成图库 ↗</a>`;
    detailView.appendChild(aside);
    detailView.classList.add("has-gen-sidebar");
    refreshGenSidebar(workId);
    scheduleGenSidebarPoll(workId);
    if (!window.__charSwapGenVisHook) {
      window.__charSwapGenVisHook = true;
      document.addEventListener("visibilitychange", () => {
        if (!document.hidden && state.workId && document.getElementById("charSwapGenSidebar")) {
          refreshGenSidebar(state.workId);
          scheduleGenSidebarPoll(state.workId);
        }
      });
    }
  }

export function mountBatchDrawer() {
    if (document.getElementById("charSwapBatchDrawer")) return;
    const drawer = document.createElement("div");
    drawer.id = "charSwapBatchDrawer";
    drawer.className = "char-swap-batch-drawer";
    drawer.innerHTML = `
      <div class="char-swap-batch-head">
        <button type="button" class="char-swap-batch-toggle" id="charSwapBatchBadge">批量(0)</button>
        <span class="char-swap-batch-title">批量替换 & 批量生成</span>
        <label class="char-swap-check"><input type="checkbox" id="batchModeToggle" /> 卡片多选</label>
        <button type="button" class="char-swap-btn" id="charSwapBatchClose">收起</button>
      </div>
      <div class="char-swap-batch-body">
        <div class="char-swap-quick-add" id="charSwapQuickAddList">
          <div class="char-swap-section-title">图库列表 · 加入本页作品</div>
          <div id="charSwapQuickHint" class="char-swap-quick-hint">每个作品对应 /i/xxx 作品页；只加列表当前分页，不含其它页</div>
          <button type="button" class="char-swap-btn primary char-swap-quick-main" id="charSwapQuickPage">加入列表本页</button>
          <div id="charSwapQuickStatus" class="char-swap-quick-status"></div>
        </div>
        <div class="char-swap-quick-add char-swap-quick-add-detail hidden" id="charSwapQuickAddDetail">
          <div class="char-swap-section-title">当前作品页 · /i/<span id="charSwapQuickWorkId">—</span></div>
          <div class="char-swap-quick-hint" id="charSwapQuickDetailHint">把本作品全部图片（p0、p1…）加入批量队列</div>
          <button type="button" class="char-swap-btn primary char-swap-quick-main" id="charSwapQuickWorkAll">全部图片加入批量</button>
        </div>
        <div class="char-swap-batch-cols">
          <div class="char-swap-batch-col">
            <div class="char-swap-section-title">队列 <span class="char-swap-queue-cap" id="charSwapBatchCap">上限 ${BATCH_MAX_DEFAULT}</span></div>
            <div id="charSwapBatchList" class="char-swap-batch-list"></div>
            <button type="button" class="char-swap-btn" id="charSwapBatchClear">清空队列</button>
          </div>
          <div class="char-swap-batch-col">
            <div class="char-swap-section-title">批量配方</div>
            <label class="char-swap-check"><input type="checkbox" id="batchCharEnabled" checked /> 角色替换</label>
            <div class="char-swap-batch-row">
              <select id="batchMode">
                <option value="replace_male">换男角</option>
                <option value="replace_female">换女角</option>
                <option value="replace">普通替换</option>
              </select>
              <select id="batchPreset"></select>
            </div>
            <div class="char-swap-batch-row">
              <label>目标槽</label>
              <select id="batchSlot">
                <option value="auto_creature">自动贵物槽</option>
                <option value="auto_male">自动男槽</option>
                <option value="auto_female">自动女槽（仅第一个）</option>
                <option value="all_female">全部女槽（同一角色）</option>
                <option value="all_male">全部男槽（同一角色）</option>
                <option value="0">槽 #1</option>
                <option value="1">槽 #2</option>
                <option value="2">槽 #3</option>
              </select>
            </div>
            <label class="char-swap-check"><input type="checkbox" id="batchStyleEnabled" /> 画风替换</label>
            <div class="char-swap-batch-row">
              <input id="batchStyleFind" type="text" placeholder="查找画风" />
              <input id="batchStyleReplace" type="text" placeholder="替换为" />
              <select id="batchStylePreset"></select>
            </div>
            <label class="char-swap-check"><input type="checkbox" id="batchSanitize" checked /> 自动净化（不含贵物）</label>
            <label class="char-swap-check"><input type="checkbox" id="batchReplaceCreature" /> 贵物/异种换成搭档（保留人类角色，默认博士）</label>
            <label class="char-swap-check"><input type="checkbox" id="batchForceFree" checked /> Opus 免费路径</label>
          </div>
        </div>
        <div class="char-swap-batch-actions">
          <button type="button" class="char-swap-btn" id="charSwapBatchPreview">预览可处理数</button>
          <button type="button" class="char-swap-btn" id="charSwapBatchReplaceOnly">仅替换（不生图）</button>
          <button type="button" class="char-swap-btn primary" id="charSwapBatchRun">批量生成 ▶</button>
          <button type="button" class="char-swap-btn" id="charSwapBatchCancel">取消任务</button>
          <a href="/generated" target="_blank" rel="noopener" class="char-swap-batch-link">生成图库</a>
        </div>
        <div id="charSwapBatchProgress" class="char-swap-batch-progress">空闲</div>
        <pre id="charSwapBatchLog" class="char-swap-batch-log"></pre>
      </div>`;
    document.body.appendChild(drawer);

    const badge = document.getElementById("charSwapBatchBadge");
    const toggle = () => drawer.classList.toggle("open");
    badge.addEventListener("click", toggle);
    document.getElementById("charSwapBatchClose").addEventListener("click", () => {
      drawer.classList.remove("open");
    });
    // Esc 关闭抽屉，与 fc 面板 / createModal 行为一致
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && drawer.classList.contains("open")) {
        drawer.classList.remove("open");
      }
    });

    const modeToggle = document.getElementById("batchModeToggle");
    modeToggle.checked = isBatchMode();
    modeToggle.addEventListener("change", () => setBatchMode(modeToggle.checked));

    document.getElementById("charSwapBatchClear").addEventListener("click", () => {
      // 清空不可撤销，先确认
      if (!window.confirm("确定清空整个批量队列？此操作不可撤销。")) return;
      saveBatchQueue([]);
      renderBatchQueueList();
      refreshBatchCardChecks();
      setQuickAddStatus("队列已清空", true);
    });

    const runQuick = async (fn) => {
      try {
        const drawer = document.getElementById("charSwapBatchDrawer");
        if (drawer) drawer.classList.add("open");
        await fn();
      } catch (e) {
        setQuickAddStatus(e.message || String(e), false);
      }
    };

    document.getElementById("charSwapQuickPage").addEventListener("click", () => {
      runQuick(quickAddCurrentPageWorks);
    });

    document.getElementById("charSwapQuickWorkAll").addEventListener("click", () => {
      if (!state.workId) {
        setQuickAddStatus("请先打开一个作品页 /i/xxx", false);
        return;
      }
      runQuick(async () => {
        const n = Math.max(1, Number(state.imagePageCount) || 1);
        const res = addAllWorkPagesToBatch(state.workId, n, { title: state.workTitle });
        setQuickAddStatus(
          `作品 #${state.workId}：加入 ${res.added} 项（${n} 张图）`,
          res.added > 0
        );
      });
    });

    const presetSel = document.getElementById("batchPreset");
    const loadPresets = () => {
      api("/api/plugin/char-swap/presets?gender=male").then((res) => {
        presetSel.innerHTML = "";
        (res.presets || []).forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = p.label;
          presetSel.appendChild(opt);
        });
        const doc = (res.presets || []).find((p) => p.id === "doctor_m");
        if (doc) presetSel.value = "doctor_m";
      });
    };
    loadPresets();
    document.getElementById("batchMode").addEventListener("change", (e) => {
      syncBatchTargetSlot();
      const g = e.target.value === "replace_female" ? "female" : "male";
      api(`/api/plugin/char-swap/presets?gender=${g}`).then((res) => {
        presetSel.innerHTML = "";
        (res.presets || []).forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = p.label;
          presetSel.appendChild(opt);
        });
      });
    });
    const replaceCreatureToggle = document.getElementById("batchReplaceCreature");
    if (replaceCreatureToggle) {
      replaceCreatureToggle.addEventListener("change", syncBatchTargetSlot);
    }
    syncBatchTargetSlot();

    const bindStylePresetSelect = (sel, findId, replId) => {
      if (!sel) return;
      sel.addEventListener("change", () => {
        const opt = sel.selectedOptions[0];
        if (!opt || !opt.value) return;
        const f = document.getElementById(findId);
        const r = document.getElementById(replId);
        if (r) r.value = opt.dataset.style || "";
        const styleOn = document.getElementById("batchStyleEnabled");
        if (styleOn) styleOn.checked = true;
      });
    };
    bindStylePresetSelect(document.getElementById("batchStylePreset"), "batchStyleFind", "batchStyleReplace");

    document.getElementById("charSwapBatchPreview").addEventListener("click", async () => {
      const queue = loadBatchQueue();
      if (!queue.length) { alert("队列为空"); return; }
      try {
        const res = await api("/api/plugin/char-swap/batch/preview", {
          method: "POST",
          body: JSON.stringify({
            targets: mapQueueToTargets(),
            recipe: buildRecipeFromForm(),
          }),
        });
        const draftN = queue.filter((x) => x.from_draft).length;
        document.getElementById("charSwapBatchProgress").textContent =
          (res.message || `可处理 ${res.ready}/${res.total}`) + (draftN ? ` · ${draftN} 项用工作台草稿` : "");
        const log = document.getElementById("charSwapBatchLog");
        if (log) {
          log.textContent = (res.items || []).map((it) =>
            `${it.ok ? "✓" : "✗"} ${it.work_id}: ${it.message || it.summary || ""}`
          ).join("\n");
        }
      } catch (e) {
        document.getElementById("charSwapBatchProgress").textContent = e.message;
      }
    });

    document.getElementById("charSwapBatchReplaceOnly").addEventListener("click", async () => {
      if (!confirm("仅批量替换草稿并校验，不请求 NAI 生图？")) return;
      try {
        await startBatch({ generate: false, preview_only: true });
      } catch (e) {
        alert(e.message);
      }
    });

    document.getElementById("charSwapBatchRun").addEventListener("click", async () => {
      const n = loadBatchQueue().length;
      if (!n) { alert("批量队列为空"); return; }
      let slotN = 1;
      try {
        const st = await api("/api/nai/status");
        if (!st.has_token) {
          alert("请先在设置 → 角色插件 中填写 NAI Token");
          return;
        }
        slotN = Math.max(1, Number(st.concurrency || st.enabled_count || 1) || 1);
      } catch (e) {
        alert(`NAI 状态: ${e.message}`);
        return;
      }
      const waves = Math.max(1, Math.ceil(n / slotN));
      if (!confirm(`批量生成 ${n} 张图？\nNAI 并发槽位：${slotN}\n预计耗时 ${waves * 25}-${waves * 45} 秒`)) return;
      try {
        await startBatch({ generate: true });
      } catch (e) {
        alert(e.message);
      }
    });

    document.getElementById("charSwapBatchCancel").addEventListener("click", async () => {
      try {
        await api("/api/plugin/char-swap/batch/cancel", { method: "POST", body: "{}" });
      } catch { }
    });

    fillStylePresetSelects();
    renderBatchQueueList();
    updateBatchBadge();
    updateQuickAddHint();
    if (window.__charSwapHintInterval) {
      clearInterval(window.__charSwapHintInterval);
    }
    window.__charSwapHintInterval = setInterval(updateQuickAddHint, 4000);
  }

export function mountQuickFab() {
    if (document.getElementById("charSwapQuickFab")) return;
    const fab = document.createElement("button");
    fab.type = "button";
    fab.id = "charSwapQuickFab";
    fab.className = "char-swap-quick-fab";
    fab.title = "打开批量工作台";
    fab.textContent = "⚡ 批量";
    fab.addEventListener("click", () => {
      const drawer = document.getElementById("charSwapBatchDrawer");
      if (drawer) drawer.classList.add("open");
      updateQuickAddHint();
    });
    document.body.appendChild(fab);
  }

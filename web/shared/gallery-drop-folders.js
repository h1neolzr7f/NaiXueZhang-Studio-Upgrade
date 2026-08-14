(function () {
  const DROP_GALLERIES = new Set(["codex", "qqgroup"]);
  const ACCEPT = "image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp";
  const IMAGE_RE = /\.(png|jpe?g|webp)$/i;
  const MAX_FILES = 250;
  const MAX_ENTRY_DEPTH = 8;
  let uploading = false;

  function galleryId() {
    if (typeof window.currentGalleryId === "function") return window.currentGalleryId();
    try {
      return new URL(window.location.href).searchParams.get("gallery") || "site";
    } catch (_) {
      return "site";
    }
  }

  function dropGalleryId(gid) {
    return DROP_GALLERIES.has(String(gid || galleryId()));
  }

  function isDropGallery(gid) {
    try {
      if (typeof state !== "undefined" && state && (state.favoritesMode || state.queueMode)) {
        return false;
      }
    } catch (_) { /* ignore */ }
    return dropGalleryId(gid);
  }

  function dock() {
    return document.getElementById("galleryDropDock");
  }

  function setStatus(message, kind) {
    const el = document.getElementById("galleryDropStatus");
    if (!el) return;
    el.textContent = String(message || "");
    el.classList.toggle("is-ok", kind === "ok");
    el.classList.toggle("is-fail", kind === "fail");
  }

  function folderKeyOf(item) {
    const key = String((item && (item.group_key || item.key || item.label)) || "").trim();
    return key.startsWith("group:") ? key.slice(6) : key;
  }

  function searchValueOf(item) {
    const key = String((item && item.key) || "").trim();
    if (key) return key;
    const plain = folderKeyOf(item);
    return plain ? `group:${plain}` : "";
  }

  async function loadFolders() {
    const gid = galleryId();
    if (!isDropGallery(gid) || !window.ApiClient) return [];
    const data = await window.ApiClient.request(`/api/galleries/${encodeURIComponent(gid)}/groups`);
    const items = Array.isArray(data.items) ? data.items : [];
    return items.filter((item) => {
      const kind = String(item.kind || "");
      if (kind && kind !== "folder") return false;
      return !!folderKeyOf(item);
    });
  }

  function selectFolder(item) {
    const select = document.getElementById("galleryGroup");
    const value = searchValueOf(item);
    if (select && value) {
      if (![...select.options].some((opt) => opt.value === value)) {
        const opt = document.createElement("option");
        opt.value = value;
        opt.textContent = item.label || folderKeyOf(item);
        select.appendChild(opt);
      }
      select.value = value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function readyCharSwap(plugin) {
    if (!plugin) return plugin;
    if (typeof plugin.init === "function" && !document.getElementById("charSwapBatchDrawer")) {
      try { plugin.init(); } catch (_) { /* ignore */ }
    }
    return plugin;
  }

  async function ensureCharSwap() {
    if (window.CharSwapPlugin && typeof window.CharSwapPlugin.addManyToBatch === "function") {
      return readyCharSwap(window.CharSwapPlugin);
    }
    const hooks = window.GalleryDetailHooks;
    if (hooks && typeof hooks.loadCharSwapPlugin === "function") {
      await hooks.loadCharSwapPlugin();
    }
    return readyCharSwap(window.CharSwapPlugin);
  }

  async function addFolderToBatch(item) {
    const gid = galleryId();
    const key = folderKeyOf(item);
    const plugin = await ensureCharSwap();
    if (!plugin || typeof plugin.addManyToBatch !== "function") {
      setStatus("换角批量队列未就绪，请稍后再试。", "fail");
      return;
    }
    setStatus(`正在把「${key}」加入批量换角…`);
    const entries = [];
    for (let page = 1; page <= 20; page += 1) {
      const params = new URLSearchParams({
        gallery_id: gid,
        group: `group:${key}`,
        page: String(page),
        page_size: "120",
        sort: "new",
      });
      const payload = await window.ApiClient.request(`/api/ai_works_search?${params}`);
      const items = Array.isArray(payload.items) ? payload.items : [];
      items.forEach((work) => {
        entries.push({
          work_id: work.id,
          page_index: 0,
          title: work.title || key,
          gallery_id: gid,
        });
      });
      if (items.length < 120 || entries.length >= MAX_FILES) break;
    }
    if (!entries.length) {
      setStatus(`文件夹「${key}」里还没有可换角的作品。`, "fail");
      return;
    }
    const result = plugin.addManyToBatch(entries);
    const added = Number(result && result.added) || 0;
    const skipped = Number(result && result.skipped) || 0;
    const capped = result && result.capped;
    document.getElementById("charSwapBatchDrawer")?.classList.add("open");
    if (typeof plugin.onGalleryUpdated === "function") plugin.onGalleryUpdated();
    if (!added && skipped) {
      setStatus(`「${key}」里的作品都已在批量队列中。`, "ok");
      return;
    }
    setStatus(
      capped
        ? `已加入 ${added} 张，批量队列已满。`
        : `已把「${key}」的 ${added} 张加入批量换角。`,
      added ? "ok" : "fail",
    );
  }

  async function mergeFolder(sourceItem, targetKey, opts) {
    const gid = galleryId();
    const source = folderKeyOf(sourceItem);
    let target = String(targetKey || "").trim();
    if (opts && opts.createNew) {
      target = String(window.prompt("合并后的文件夹名", source) || "").trim();
    }
    if (!target || target === source) return;
    if (!window.confirm(`把「${source}」合并进「${target}」？原文件夹会消失。`)) return;
    setStatus(`正在把「${source}」合并进「${target}」…`);
    const payload = await window.ApiClient.request(`/api/gallery/${encodeURIComponent(gid)}/folders/merge`, {
      method: "POST",
      body: { source_keys: [source], target_key: target },
    });
    setStatus(`已合并 ${Number(payload.moved) || 0} 张到「${payload.folder || target}」。`, "ok");
    await reloadAfterChange(payload.folder || target, gid);
  }

  function renderFolders(items) {
    const rail = document.getElementById("galleryFolderRail");
    if (!rail) return;
    rail.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("p");
      empty.className = "gallery-folder-empty";
      empty.textContent = "还没有文件夹。拖入一批图或整个文件夹，会自动收成一叠。";
      rail.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const key = folderKeyOf(item);
      const details = document.createElement("details");
      details.className = "gallery-folder-card";
      details.dataset.folderKey = key;
      const summary = document.createElement("summary");
      summary.innerHTML = `<strong>${escapeText(item.label || key)}</strong><span>${Number(item.count) || 0} 张</span>`;
      const body = document.createElement("div");
      body.className = "gallery-folder-actions";
      const viewBtn = document.createElement("button");
      viewBtn.type = "button";
      viewBtn.className = "gallery-folder-btn";
      viewBtn.textContent = "查看";
      viewBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        selectFolder(item);
      });
      const batchBtn = document.createElement("button");
      batchBtn.type = "button";
      batchBtn.className = "gallery-folder-btn primary";
      batchBtn.textContent = "加入批量换角";
      batchBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        Promise.resolve(addFolderToBatch(item)).catch((err) => setStatus(String(err.message || err), "fail"));
      });
      const mergeSelect = document.createElement("select");
      mergeSelect.className = "gallery-folder-merge";
      mergeSelect.setAttribute("aria-label", `把 ${key} 合并到`);
      mergeSelect.innerHTML = `<option value="">合并到…</option>`
        + items
          .filter((other) => folderKeyOf(other) !== key)
          .map((other) => `<option value="${escapeAttr(folderKeyOf(other))}">${escapeText(other.label || folderKeyOf(other))}</option>`)
          .join("");
      mergeSelect.addEventListener("click", (event) => event.stopPropagation());
      mergeSelect.addEventListener("change", () => {
        const value = mergeSelect.value;
        mergeSelect.value = "";
        if (!value) return;
        Promise.resolve(mergeFolder(item, value)).catch((err) => setStatus(String(err.message || err), "fail"));
      });
      const newBtn = document.createElement("button");
      newBtn.type = "button";
      newBtn.className = "gallery-folder-btn";
      newBtn.textContent = "新建并合并…";
      newBtn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        Promise.resolve(mergeFolder(item, "", { createNew: true })).catch((err) => setStatus(String(err.message || err), "fail"));
      });
      body.append(viewBtn, batchBtn, mergeSelect, newBtn);
      details.append(summary, body);
      rail.appendChild(details);
    });
  }

  function escapeText(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function escapeAttr(value) {
    return escapeText(value).replace(/"/g, "&quot;");
  }

  async function refresh(opts) {
    if (!isDropGallery()) {
      renderFolders([]);
      return [];
    }
    try {
      const items = await loadFolders();
      renderFolders(items);
      if (opts && opts.selectFolder) {
        const hit = items.find((item) => folderKeyOf(item) === opts.selectFolder);
        if (hit) selectFolder(hit);
      }
      return items;
    } catch (error) {
      setStatus(`文件夹列表读取失败：${error.message || error}`, "fail");
      return [];
    }
  }

  function switchedAwayMessage(expectedGallery) {
    const label = expectedGallery === "qqgroup" ? "Q群" : "自选库";
    setStatus(`已在${label}完成。切回该库可看到更新。`, "ok");
  }

  async function reloadAfterChange(folder, expectedGallery) {
    const stillHere = () => !expectedGallery || galleryId() === expectedGallery;
    if (!stillHere()) {
      switchedAwayMessage(expectedGallery);
      return [];
    }
    if (typeof window.loadGalleryHierarchy === "function") {
      await window.loadGalleryHierarchy();
    }
    if (!stillHere()) {
      switchedAwayMessage(expectedGallery);
      return [];
    }
    const items = await refresh();
    if (!stillHere()) {
      switchedAwayMessage(expectedGallery);
      return [];
    }
    if (folder) {
      const hit = items.find((item) => folderKeyOf(item) === folder) || {
        key: `group:${folder}`,
        group_key: folder,
        label: folder,
      };
      selectFolder(hit);
      return items;
    }
    if (typeof window.fetchWorks === "function") window.fetchWorks();
    else if (typeof window.triggerSearch === "function") window.triggerSearch();
    return items;
  }

  async function uploadFiles(files) {
    const gid = galleryId();
    if (!isDropGallery(gid)) return;
    if (uploading) {
      setStatus("正在导入上一批，请稍候。", "fail");
      return;
    }
    const list = (Array.isArray(files) ? files : []).filter(isImageFile);
    if (!list.length) {
      setStatus("没有可导入的图片。请拖入 PNG/JPG/WebP，或直接拖整个文件夹。", "fail");
      return;
    }
    let note = "";
    if (list.length > MAX_FILES) {
      note = `一次最多 ${MAX_FILES} 张，已截取前 ${MAX_FILES} 张。`;
      list.length = MAX_FILES;
    }
    uploading = true;
    setStatus(note ? `${note} 正在解析 ${list.length} 张图片…` : `正在解析 ${list.length} 张图片，将收成一个文件夹…`);
    const form = new FormData();
    form.append("category", "");
    list.forEach((file) => form.append("files", file));
    try {
      const payload = await window.ApiClient.request(`/api/gallery/${encodeURIComponent(gid)}/import-drop`, {
        method: "POST",
        body: form,
        timeoutMs: 300000,
      });
      const accepted = Array.isArray(payload.accepted) ? payload.accepted : [];
      const rejected = Array.isArray(payload.rejected) ? payload.rejected : [];
      const folder = payload.folder || payload.category || "";
      const existing = accepted.filter((item) => item && item.existing).length;
      const lines = [];
      if (note) lines.push(note);
      lines.push(`文件夹「${folder}」：入库 ${accepted.length}，拒绝 ${rejected.length}`);
      if (existing) lines.push(`其中 ${existing} 张已在库中，仍留在原文件夹`);
      rejected.slice(0, 4).forEach((item) => lines.push(`✗ ${item.file} · ${item.reason}`));
      setStatus(lines.join(" · "), accepted.length ? "ok" : "fail");
      await reloadAfterChange(accepted.length ? folder : "", gid);
    } catch (error) {
      const aborted = error && (error.name === "AbortError" || /aborted|timeout/i.test(String(error.message || "")));
      setStatus(
        aborted ? "导入超时，请减少一次拖入的张数后重试。" : `导入失败：${error.message || error}`,
        "fail",
      );
    } finally {
      uploading = false;
    }
  }

  function hasFiles(event) {
    const types = event.dataTransfer && event.dataTransfer.types;
    if (!types) return false;
    return Array.from(types).includes("Files");
  }

  function isIgnoredDropTarget(event) {
    const el = event.target;
    if (!el || !el.closest) return false;
    return !!el.closest(
      ".detail-view, .char-swap-panel, .char-swap-batch-drawer, .companion-dock, .companion-docks, .inspiration-sidebar, .fc-panel",
    );
  }

  function isImageFile(file) {
    if (!file || !file.size) return false;
    const type = String(file.type || "").toLowerCase();
    if (type.startsWith("image/")) return /png|jpe?g|webp/.test(type);
    return IMAGE_RE.test(file.name || "");
  }

  function fileFromEntry(entry) {
    return new Promise((resolve, reject) => entry.file(resolve, reject));
  }

  function readAllEntries(reader) {
    return new Promise((resolve, reject) => {
      const out = [];
      const tick = () => {
        reader.readEntries((batch) => {
          if (!batch.length) {
            resolve(out);
            return;
          }
          out.push(...batch);
          tick();
        }, reject);
      };
      tick();
    });
  }

  async function filesFromEntry(entry, acc, depth) {
    if (!entry || acc.length > MAX_FILES) return acc;
    if (entry.isFile) {
      try {
        const file = await fileFromEntry(entry);
        if (isImageFile(file)) acc.push(file);
      } catch (_) { /* ignore unreadable entries */ }
      return acc;
    }
    if (entry.isDirectory && depth < MAX_ENTRY_DEPTH) {
      try {
        const kids = await readAllEntries(entry.createReader());
        for (const kid of kids) {
          if (acc.length > MAX_FILES) break;
          await filesFromEntry(kid, acc, depth + 1);
        }
      } catch (_) { /* ignore unreadable folders */ }
    }
    return acc;
  }

  async function collectDroppedFiles(event) {
    const dt = event.dataTransfer;
    const files = Array.from((dt && dt.files) || []).filter(isImageFile);
    const items = dt && dt.items;
    if (!items || !items.length) return files;
    const entries = [];
    for (const item of items) {
      if (item.kind !== "file") continue;
      const entry = typeof item.webkitGetAsEntry === "function" ? item.webkitGetAsEntry() : null;
      if (entry) entries.push(entry);
    }
    const hasDir = entries.some((entry) => entry && entry.isDirectory);
    if (!hasDir && files.length) return files;
    const acc = [];
    for (const entry of entries) {
      await filesFromEntry(entry, acc, 0);
    }
    return acc.length ? acc : files;
  }

  function setDragState(on) {
    document.getElementById("galleryDropzone")?.classList.toggle("is-drag", on);
    document.getElementById("noResult")?.classList.toggle("is-drop-target", on);
    document.querySelector(".gallery-main")?.classList.toggle("is-drop-target", on);
  }

  function bindFileInput(input, extra) {
    if (extra && extra.directory) {
      input.setAttribute("webkitdirectory", "");
      input.setAttribute("directory", "");
    } else {
      input.accept = ACCEPT;
    }
    input.type = "file";
    input.multiple = true;
    input.hidden = true;
    input.addEventListener("change", () => {
      if (input.files && input.files.length) {
        Promise.resolve(uploadFiles(Array.from(input.files))).catch((err) => setStatus(String(err.message || err), "fail"));
      }
      input.value = "";
    });
    return input;
  }

  function bindDropzone() {
    const zone = document.getElementById("galleryDropzone");
    if (!zone) return;
    const input = bindFileInput(document.createElement("input"));
    const folderInput = bindFileInput(document.createElement("input"), { directory: true });
    zone.append(input, folderInput);
    const bindPick = (id, target) => {
      document.getElementById(id)?.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        target.click();
      });
    };
    bindPick("galleryDropPick", input);
    bindPick("galleryDropPickFolder", folderInput);
    const onDrag = (event) => {
      if (!dropGalleryId() || !hasFiles(event)) return;
      event.preventDefault();
      const ignored = isIgnoredDropTarget(event);
      if (event.dataTransfer) event.dataTransfer.dropEffect = ignored ? "none" : "copy";
      if (isDropGallery() && !ignored) setDragState(true);
    };
    const onLeave = (event) => {
      if (!dropGalleryId()) return;
      if (event.relatedTarget) return;
      setDragState(false);
    };
    const onDrop = (event) => {
      if (!dropGalleryId() || !hasFiles(event)) return;
      event.preventDefault();
      setDragState(false);
      if (!isDropGallery() || isIgnoredDropTarget(event)) return;
      Promise.resolve(collectDroppedFiles(event))
        .then((files) => uploadFiles(files))
        .catch((err) => setStatus(String(err.message || err), "fail"));
    };
    document.addEventListener("dragenter", onDrag);
    document.addEventListener("dragover", onDrag);
    document.addEventListener("dragleave", onLeave);
    document.addEventListener("drop", onDrop);
  }

  function sync() {
    const host = dock();
    if (!host) return;
    const on = isDropGallery();
    host.hidden = !on;
    host.classList.toggle("hidden", !on);
    document.body.classList.toggle("gallery-drop-active", on);
    const help = document.getElementById("galleryResultsHelp");
    if (help && on) {
      help.dataset.dropHelp = "1";
    }
    if (on) refresh();
    else setDragState(false);
  }

  function start() {
    bindDropzone();
    sync();
    document.getElementById("gallerySource")?.addEventListener("change", () => sync());
    document.getElementById("gallerySourceSwitch")?.addEventListener("click", () => {
      window.setTimeout(sync, 0);
    });
  }

  window.GalleryDropFolders = {
    sync,
    refresh,
    isDropGallery,
    uploadFiles,
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();

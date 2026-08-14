/* Compliance and provenance UI for Pixiv NAI Gallery */
(function () {
  const $ = (id) => document.getElementById(id);

  async function api(path, options) {
    const opts = Object.assign({ headers: { "Content-Type": "application/json" } }, options || {});
    const res = await window.ApiClient.raw(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  function esc(text) {
    return String(text == null ? "" : text).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  function fmtTime(t) {
    if (!t) return "—";
    return String(t).replace("T", " ").slice(0, 16);
  }

  async function initNotice() {
    try {
      const status = await api("/api/compliance/notice/status");
      if (status.required) $("noticeBanner").style.display = "block";
      $("acceptNotice").addEventListener("click", async () => {
        await api("/api/compliance/notice/accept", {
          method: "POST",
          body: JSON.stringify({ app_version: (window.__APP_VERSION__ || "") }),
        });
        $("noticeBanner").style.display = "none";
      });
      $("viewTerms").addEventListener("click", () => {
        $("termsBox").scrollIntoView({ behavior: "smooth" });
      });
    } catch (e) {
      console.warn("notice init failed", e);
    }
  }

  async function cleanupAuthor(item) {
    const count = Number(item.local_works || 0);
    const accepted = window.confirm(
      `将把作者 ${item.author_name}（${item.author_id}）的 ${count} 个本地作品移动到 data/_trash 后删除索引。继续吗？`,
    );
    if (!accepted) return;
    const result = await api(`/api/compliance/authors/${item.author_id}`, { method: "DELETE" });
    const details = [
      `已删除索引作品：${result.deleted_works}`,
      `已移入回收区文件：${result.files_moved}`,
      `未找到文件：${result.files_missing}`,
      `文件错误：${(result.file_failures || []).length}`,
    ];
    alert(details.join("\n"));
    await loadBlacklist();
  }

  async function loadBlacklist() {
    const data = await api("/api/compliance/blacklist");
    const body = $("blacklistBody");
    body.innerHTML = "";
    for (const item of data.items || []) {
      const tr = document.createElement("tr");
      const scopeLabel = item.scope === "crawl"
        ? "仅禁采集"
        : item.scope === "delete"
          ? "标记清理"
          : "禁采集+标记清理";
      const cleanupButton = item.cleanup_required
        ? `<button class="danger" data-clean="${esc(item.author_id)}">清理 ${esc(item.local_works)} 项</button>`
        : "";
      tr.innerHTML = `
        <td>${esc(item.author_id)}</td>
        <td>${esc(item.author_name)}</td>
        <td><span class="badge ${item.scope === "crawl" ? "gray" : "red"}">${esc(scopeLabel)}</span></td>
        <td>${esc(item.reason)}</td>
        <td>${fmtTime(item.created_at)}</td>
        <td>${cleanupButton} <button class="ghost" data-del="${esc(item.author_id)}">移除规则</button></td>`;
      const cleanup = tr.querySelector("[data-clean]");
      if (cleanup) cleanup.addEventListener("click", () => cleanupAuthor(item));
      tr.querySelector("[data-del]").addEventListener("click", async () => {
        await api(`/api/compliance/blacklist/${item.author_id}`, { method: "DELETE" });
        await loadBlacklist();
      });
      body.appendChild(tr);
    }
  }

  $("addBlacklist").addEventListener("click", async () => {
    const author_id = Number($("blAuthorId").value.trim());
    const author_name = $("blAuthorName").value.trim();
    if (!author_id || !author_name) { alert("作者 ID 与作者名必填"); return; }
    const result = await api("/api/compliance/blacklist", {
      method: "POST",
      body: JSON.stringify({ author_id, author_name, scope: $("blScope").value, reason: $("blReason").value.trim() }),
    });
    $("blAuthorId").value = ""; $("blAuthorName").value = ""; $("blReason").value = "";
    await loadBlacklist();
    if (result.cleanup_required) alert("该作者已有本地素材，可在列表中点击“清理”移入回收区。");
  });

  async function loadBlocked() {
    const data = await api("/api/compliance/blocked");
    const body = $("blockedBody");
    body.innerHTML = "";
    for (const item of data.items || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${esc(item.work_id)}</td>
        <td><a href="${esc(typeof safeHttpUrl === "function" ? safeHttpUrl(item.source_url, "#") : "#")}" target="_blank" rel="noopener">${esc(item.source_url)}</a></td>
        <td>${fmtTime(item.created_at)}</td>
        <td><button class="danger" data-del="${esc(item.work_id)}">移除</button></td>`;
      tr.querySelector("[data-del]").addEventListener("click", async () => {
        await api(`/api/compliance/blocked/${item.work_id}`, { method: "DELETE" });
        await loadBlocked();
      });
      body.appendChild(tr);
    }
  }

  $("addBlocked").addEventListener("click", async () => {
    const work_id = Number($("blkWorkId").value.trim());
    if (!work_id) { alert("作品 ID 必填"); return; }
    await api("/api/compliance/blocked", {
      method: "POST",
      body: JSON.stringify({ work_id, source_url: $("blkSourceUrl").value.trim() }),
    });
    $("blkWorkId").value = ""; $("blkSourceUrl").value = "";
    await loadBlocked();
  });

  $("syncRemoved").addEventListener("click", async () => {
    const ids = $("syncWorkIds").value.split(",").map((s) => Number(s.trim())).filter((n) => n > 0);
    if (!ids.length) { alert("作品 ID 必填"); return; }
    const status = $("syncStatus").value;
    const data = await api("/api/compliance/sync/removed", {
      method: "POST",
      body: JSON.stringify({ items: ids.map((work_id) => ({ work_id, status })) }),
    });
    alert(`已标记 ${data.updated} 个作品为「${status}」`);
    $("syncWorkIds").value = "";
  });

  $("syncCheck").addEventListener("click", async () => {
    const ids = $("syncWorkIds").value.split(",").map((s) => Number(s.trim())).filter((n) => n > 0);
    if (!ids.length) { alert("作品 ID 必填"); return; }
    const data = await api("/api/compliance/sync/check", {
      method: "POST",
      body: JSON.stringify({ work_ids: ids }),
    });
    const removed = data.removed || [];
    alert(removed.length
      ? `以下作品源状态已变化：\n${removed.map((r) => `#${r.work_id} (${r.author || "?"}) - ${r.removed_status}`).join("\n")}`
      : "这些作品未被标记为已删除");
  });

  $("genManifest").addEventListener("click", async () => {
    const ids = $("manifestWorkIds").value.split(",").map((s) => Number(s.trim())).filter((n) => n > 0);
    if (!ids.length) { alert("作品 ID 必填"); return; }
    const data = await api(`/api/compliance/export-manifest?work_ids=${ids.join(",")}`);
    $("manifestOutput").style.display = "block";
    const tsvLines = ["work_id\t作者ID\t作者名\t作品链接\t作者主页\t源状态\t作者声明\t本地文件"];
    for (const it of data.items || []) {
      tsvLines.push([
        it.work_id, it.author_id || "", it.author_name || "",
        it.work_url || "", it.author_url || "",
        it.removed_status || "正常", it.no_ai_notice || "无",
        (it.local_files || []).join(";"),
      ].join("\t"));
    }
    const blob = new Blob([tsvLines.join("\n")], { type: "text/tab-separated-values;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `pixiv-nai-source-manifest-${Date.now()}.tsv`;
    a.click();
    URL.revokeObjectURL(a.href);
    const lines = (data.items || []).map((it) => [
      `作品ID: ${it.work_id}`,
      `标题: ${it.title || ""}`,
      `作者: ${it.author_name || ""} (ID ${it.author_id || ""})`,
      `作者主页: ${it.author_url || ""}`,
      `作品链接: ${it.work_url || ""}`,
      `源状态: ${it.removed_status || "正常"}`,
      `作者声明: ${it.no_ai_notice || "无"}`,
      `本地文件: ${(it.local_files || []).join(", ") || "无"}`,
    ].join("\n")).join("\n\n");
    $("manifestOutput").textContent = lines || "（无结果）";
  });

  async function loadAbout() {
    try {
      const info = await api("/api/settings/status").catch(() => null);
      const version = info && (info.version || info.app_version) ? (info.version || info.app_version) : "—";
      $("aboutInfo").innerHTML = `
        Nai学长工作室 · 升级版 · 版本 <strong>${esc(version)}</strong><br />
        官方仓库：<a href="https://github.com/h1neolzr7f/NaiXueZhang-Studio-Upgrade" target="_blank" rel="noopener">h1neolzr7f/NaiXueZhang-Studio-Upgrade</a><br />
        License：MIT · 本软件按现状提供，使用者自行确认其行为符合适用法律与平台规则。
      `;
    } catch (e) {
      $("aboutInfo").textContent = "版本信息加载失败";
    }
  }

  initNotice();
  loadBlacklist().catch((e) => console.warn(e));
  loadBlocked().catch((e) => console.warn(e));
  loadAbout();
})();

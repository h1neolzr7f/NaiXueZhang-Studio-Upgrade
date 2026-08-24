(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const lines = (value) => String(value || "")
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);

  async function request(path, options = {}) {
    if (!window.ApiClient) throw new Error("共享 API 客户端尚未加载");
    return window.ApiClient.request(path, options);
  }

  function setMessage(text, ok = null) {
    const target = byId("pixivActionMsg");
    if (!target) return;
    target.textContent = text;
    const baseClass = target.classList.contains("action-message") ? "action-message" : "action-msg";
    target.className = `${baseClass}${ok === true ? " ok" : ok === false ? " fail" : ""}`;
  }

  function renderTask(task) {
    byId("pixivEnabled").checked = Boolean(task.enabled);
    byId("pixivAccountId").value = task.account_id || "";
    if (byId("pixivSourceMode")) byId("pixivSourceMode").value = task.source_mode || "auto";
    byId("pixivMaxPages").value = task.max_pages_per_run || 3;
    byId("pixivMaxWorks").value = task.max_works_per_run || 60;
    byId("pixivDelay").value = task.request_delay_sec ?? 1.2;
    if (byId("pixivProxy")) byId("pixivProxy").value = task.proxy_url || "";
    if (byId("pixivBrowserMode")) byId("pixivBrowserMode").checked = Boolean(task.browser_mode);
    if (byId("pixivThumbOnly")) byId("pixivThumbOnly").checked = task.thumbnail_only_pages !== false;
    byId("pixivStorageQuotaGiB").value = Number(task.storage_quota_bytes || 0) / 1073741824;
    byId("pixivAiPrefilter").checked = task.require_pixiv_ai_generated !== false;
    const scopes = Array.isArray(task.scopes) ? task.scopes : [];
    if (byId("pixivSortMode")) {
      const firstSearch = scopes.find((scope) => scope.type === "search");
      byId("pixivSortMode").value = (firstSearch && firstSearch.sort) || "date_desc";
    }
    byId("pixivSearchQueries").value = scopes
      .filter((scope) => scope.type === "search")
      .map((scope) => scope.query || "")
      .filter(Boolean)
      .join("\n");
    byId("pixivUserIds").value = scopes
      .filter((scope) => scope.type === "user")
      .map((scope) => scope.user_id || "")
      .filter(Boolean)
      .join("\n");
    byId("pixivRanking").checked = scopes.some((scope) => scope.type === "ranking");
  }

  function taskFromForm() {
    const scopes = [];
    const searchSort = byId("pixivSortMode")?.value || "date_desc";
    lines(byId("pixivSearchQueries").value).forEach((query, index) => {
      scopes.push({
        id: `search-${index + 1}`,
        type: "search",
        query,
        sort: searchSort,
        search_target: "partial_match_for_tags",
        enabled: true,
      });
    });
    lines(byId("pixivUserIds").value).forEach((userId) => {
      if (!/^\d+$/.test(userId)) throw new Error(`画师 UID 无效：${userId}`);
      scopes.push({ id: `user-${userId}`, type: "user", user_id: Number(userId), enabled: true });
    });
    if (byId("pixivRanking").checked) {
      scopes.push({ id: "ranking-day", type: "ranking", mode: "day", enabled: true });
    }
    if (!scopes.length) throw new Error("至少填写一个搜索标签、画师 UID，或启用日榜");
    return {
      enabled: byId("pixivEnabled").checked,
      source_mode: byId("pixivSourceMode")?.value || "auto",
      account_id: byId("pixivAccountId").value.trim(),
      scopes,
      require_pixiv_ai_generated: byId("pixivAiPrefilter").checked,
      max_pages_per_run: Number(byId("pixivMaxPages").value || 3),
      max_works_per_run: Number(byId("pixivMaxWorks").value || 60),
      request_delay_sec: Number(byId("pixivDelay").value || 0),
      proxy_url: byId("pixivProxy")?.value.trim() || "",
      browser_mode: Boolean(byId("pixivBrowserMode")?.checked),
      thumbnail_only_pages: Boolean(byId("pixivThumbOnly")?.checked !== false),
      retry_max: 4,
      backoff_base_sec: 2,
      max_download_bytes: 134217728,
      storage_quota_bytes: Math.round(Number(byId("pixivStorageQuotaGiB").value || 0) * 1073741824),
      watch_interval_sec: 300,
    };
  }

  function renderPresets(presets) {
    const box = byId("pixivTaskPresets");
    if (!box) return;
    box.replaceChildren();
    (presets || []).forEach((preset) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-preset";
      btn.textContent = preset.label || preset.id || "预设";
      btn.addEventListener("click", () => {
        if (preset.task) renderTask(preset.task);
        setMessage(`已填入预设：${preset.label || preset.id}`, true);
      });
      box.appendChild(btn);
    });
  }

  async function save() {
    const body = taskFromForm();
    body.reset_search = Boolean(byId("pixivResetSearch")?.checked);
    const payload = await request("/api/crawler/pixiv/task", {
      method: "POST",
      body: JSON.stringify(body),
    });
    renderTask(payload.task);
    setMessage(payload.reset_search ? "已保存并重置采集断点" : "Pixiv 采集设置已保存", true);
    return payload.task;
  }

  async function preflight() {
    const button = byId("pixivPreflight");
    const target = byId("pixivPreflightReport");
    if (button) button.disabled = true;
    if (target) {
      target.hidden = false;
      target.textContent = "正在执行只读预检…";
    }
    setMessage("正在从 Pixiv 抽样，不会写入图库…");
    try {
      const task = taskFromForm();
      const maxWorks = Math.min(25, Math.max(1, task.max_works_per_run || 25));
      const payload = await request(
        `/api/crawler/pixiv/preflight?max_pages=1&max_works=${maxWorks}`,
        { method: "POST", body: JSON.stringify(task) },
      );
      const report = payload.report || {};
      const reasons = Object.entries(report.rejection_reasons || {})
        .map(([reason, count]) => `${reason}: ${count}`)
        .join(" · ") || "无";
      if (target) {
        target.textContent = [
          `状态：${report.status || "-"} · 搜索结果 ${report.works_found || 0} · 抽样作品 ${report.works_sampled || 0}`,
          `抽样页 ${report.pages_sampled || 0} · 下载成功 ${report.downloads_succeeded || 0} · 下载失败 ${report.downloads_failed || 0}`,
          `NAI 识别 ${report.nai_accepted || 0} · 非 NAI ${report.nai_rejected || 0}`,
          `下载成功率 ${Math.round((report.download_success_rate || 0) * 100)}% · NAI 识别率 ${Math.round((report.nai_recognition_rate || 0) * 100)}%`,
          `原因：${reasons}`,
          "只读预检未写入数据库、图片、采集游标或运行历史。",
        ].join("\n");
      }
      setMessage(payload.message || "只读预检完成", payload.ok !== false);
    } catch (error) {
      if (target) target.textContent = `只读预检失败：${error.message || error}`;
      setMessage(error.message || String(error), false);
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function control(action, watch) {
    try {
      if (action === "start") {
        const task = await save();
        if (!task.enabled) throw new Error("请先勾选“启用 Pixiv 直连采集”");
      }
      setMessage(action === "start" ? "正在启动…" : "正在停止…");
      const payload = await request(`/api/crawler/${action}`, {
        method: "POST",
        body: JSON.stringify({ target: "pixiv", watch }),
      });
      setMessage(payload.message || "操作完成", true);
      await loadReport();
    } catch (error) {
      setMessage(error.message || String(error), false);
    }
  }

  async function loadReport() {
    const target = byId("pixivNaiReport");
    if (!target) return;
    try {
      const payload = await request("/api/crawler/pixiv/report");
      const report = payload.report || {};
      const process = payload.process || {};
      const reasons = Object.entries(report.rejection_reasons || {})
        .map(([reason, count]) => `${reason}: ${count}`)
        .join(" · ") || "无";
      const failureKinds = Object.entries(report.failure_kinds || {})
        .map(([kind, count]) => `${kind}: ${count}`)
        .join(" · ") || "无";
      const history = (Array.isArray(report.history) ? report.history : [])
        .slice(-3)
        .map((item) => {
          const stamp = String(item.finished_at || item.updated_at || "-").replace("T", " ").slice(0, 19);
          return `${stamp} ${item.status || "-"} · 接受 ${item.works_accepted || 0} · 失败 ${item.works_failed || 0} · 隔离 ${item.works_quarantined || 0}`;
        });
      target.textContent = [
        `进程：${process.running ? "运行中" : "未运行"} · 本轮：${report.status || "-"} · 通道：${report.source_mode || "-"}`,
        `候选作品 ${report.works_seen || 0} · 接受作品 ${report.works_accepted || 0} · 部分接受 ${report.works_partial || 0} · 新隔离 ${report.works_quarantined || 0}`,
        `接受页 ${report.accepted_pages || 0} · 拒绝页 ${report.rejected_pages || 0} · 失败页 ${report.failed_pages || 0}`,
        `拒绝原因：${reasons}`,
        `失败性质：${failureKinds}${report.last_error ? ` · 最近错误类型 ${report.last_error}` : ""}`,
        `更新时间：${report.updated_at || "-"}`,
        ...(history.length ? ["最近运行：", ...history] : []),
      ].join("\n");
    } catch (error) {
      target.textContent = `读取 Pixiv 入库报告失败：${error.message || error}`;
    }
  }

  async function loadQuarantine() {
    const btn = byId("pixivRetryQuarantine");
    const info = byId("pixivQuarantineInfo");
    if (!btn) return;
    try {
      const payload = await request("/api/crawler/pixiv/quarantine");
      const count = (payload.items || []).length;
      if (info) info.textContent = count ? `当前隔离 ${count} 项` : "无隔离项";
      btn.disabled = !count;
    } catch (_error) { /* keep defaults */ }
  }

  const retryBtn = byId("pixivRetryQuarantine");
  if (retryBtn) {
    retryBtn.addEventListener("click", async () => {
      try {
        const payload = await request("/api/crawler/pixiv/quarantine/retry", { method: "POST" });
        setMessage(payload.message || `已清空 ${payload.cleared || 0} 项隔离`, true);
        await loadQuarantine();
        await loadReport();
      } catch (error) {
        setMessage(`重试隔离失败：${error.message || error}`, false);
      }
    });
  }

  async function load() {
    if (!byId("pixivNaiPanel")) return;
    try {
      const payload = await request("/api/crawler/pixiv/task");
      renderTask(payload.task || {});
      renderPresets(payload.presets || []);
      await loadReport();
      await loadQuarantine();
    } catch (error) {
      setMessage(`读取设置失败：${error.message || error}`, false);
    }
  }

  byId("pixivSave")?.addEventListener("click", () => save().catch((error) => setMessage(error.message, false)));
  byId("pixivPreflight")?.addEventListener("click", preflight);
  byId("pixivRunOnce")?.addEventListener("click", () => control("start", false));
  byId("pixivStartWatch")?.addEventListener("click", () => control("start", true));
  byId("pixivStop")?.addEventListener("click", () => control("stop", false));
  load();
  setInterval(loadReport, 5000);
})();

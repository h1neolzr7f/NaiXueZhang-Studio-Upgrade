const PRESETS = {};
let config = null;
// 轮询代数：pollJob / runLaunch / runAnalytics 共用，声明必须早于任何使用
let jobPollGen = 0;
let selectedId = "";
let selectedGroupId = "";
let selectedGroupIds = new Set();
let selectedImageIds = [];
let launchGroups = [];
let pickMode = "series";
let lastPixivAuth = null;
let personaCache = null;
let accounts = [];
let activeAccountId = "";
let statsData = null;
let candidatesItems = [];
let genSidebarTimer = null;
let lastCandidateCount = 0;
let genFocusIndex = 0;
let genWheelMounted = false;
let lastPreviewSig = "";
let lastBatchSig = "";
let lastCandidateSig = "";
let genPollBusy = false;
let genPollPaused = false;
let preparedPackage = null;
let preparedUploadPayload = null;

function qs(name) {
  return new URLSearchParams(location.search).get(name) || "";
}

function leavePreparedDraftMode() {
  preparedUploadPayload = null;
  const launch = document.getElementById("launchBtn");
  const upload = document.getElementById("uploadOnly");
  if (launch) {
    launch.disabled = false;
    launch.title = "";
  }
  if (upload) upload.textContent = "仅上传（用当前文案）";
}

async function readJsonResponse(res) {
  const text = await res.text();
  if (!text) return {};
  try {
    return JSON.parse(text);
  } catch (e) {
    return {
      ok: false,
      detail: text.slice(0, 500) || `HTTP ${res.status}`,
    };
  }
}

function setStatus(el, text, kind) {
  if (!el) return;
  el.textContent = text || "";
  el.classList.remove("ok", "err");
  if (kind) el.classList.add(kind);
}

function toast(msg, kind) {
  try {
    if (window.UiToast) {
      if (kind === "ok") window.UiToast.ok(msg);
      else if (kind === "err") window.UiToast.err(msg);
      else window.UiToast.show(msg);
      return;
    }
  } catch (_) { /* ignore */ }
}

function setReadyChip(key, state, label) {
  const el = document.querySelector(`#pxReadyStrip [data-ready="${key}"]`);
  if (!el) return;
  el.className = "px-ready-chip " + (state || "warn");
  if (label) el.textContent = label;
}

function refreshReadyStrip() {
  const acc = activeAccountInfo();
  const accOk = isAccountReadyForUpload(acc) && !!(lastPixivAuth && lastPixivAuth.ok);
  if (!accounts.length) setReadyChip("account", "err", "无账号槽");
  else if (!acc || !acc.has_token) setReadyChip("account", "warn", "账号待登录");
  else if (acc.identity_mismatch) setReadyChip("account", "err", "身份不一致");
  else if (accOk) setReadyChip("account", "ok", "账号已登录");
  else setReadyChip("account", "warn", "待检测登录");

  const aiSt = document.getElementById("aiAuthStatus");
  const aiText = (aiSt && aiSt.textContent) || "";
  if (/有效|就绪|成功|可用/.test(aiText) && !/未|失败|无效/.test(aiText)) {
    setReadyChip("ai", "ok", "AI 就绪");
  } else if (/失败|无效|未配置|错误/.test(aiText)) {
    setReadyChip("ai", "err", "AI 未就绪");
  } else {
    setReadyChip("ai", "warn", "AI 待检测");
  }

  const pipeSt = document.getElementById("pipeMosaicStatus");
  const pipeText = (pipeSt && pipeSt.textContent) || "";
  if (/可用|就绪|OK|ok/i.test(pipeText) && !/未|失败|无法/.test(pipeText)) {
    setReadyChip("pipeline", "ok", "后处理可用");
  } else if (/失败|无法|未配置|缺失/.test(pipeText)) {
    setReadyChip("pipeline", "err", "后处理异常");
  } else {
    setReadyChip("pipeline", "warn", "后处理待检");
  }

  const picked = !!(selectedId || selectedGroupId || selectedGroupIds.size);
  if (picked) setReadyChip("pick", "ok", "已选图");
  else setReadyChip("pick", "warn", "未选图");
}

function updateJobProgress(job, fallbackLabel = "") {
  const box = document.getElementById("jobProgress");
  const labelEl = document.getElementById("jobProgressLabel");
  const pctEl = document.getElementById("jobProgressPct");
  const barEl = document.getElementById("jobProgressBar");
  const p = (job && job.progress) || {};
  const total = Number(p.total) || 0;
  const pct = Math.max(0, Math.min(100, Number(p.percent) || 0));
  const label = p.label || fallbackLabel || "运行中";
  if (!job || (job.status !== "running" && job.status !== "done" && job.status !== "error")) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  labelEl.textContent = total
    ? `${label} · ${Number(p.current) || 0}/${total}`
    : label;
  pctEl.textContent = `${Math.round(pct)}%`;
  barEl.style.width = `${pct}%`;
}

async function revealGeneratedImage(imageId) {
  const id = String(imageId || "").trim();
  if (!id) {
    alert("缺少图片 ID，无法定位文件");
    return;
  }
  try {
    const data = await window.ApiClient.request(
      `/api/generated/reveal/${encodeURIComponent(id)}`,
      { method: "POST" }
    );
    if (!data || data.opened === false) {
      alert((data && data.message) || "当前系统无法自动打开文件夹");
    }
  } catch (err) {
    alert((err && err.message) || "无法打开文件夹");
  }
}

async function reviewPipelineImage(imageId, action) {
  const id = String(imageId || "").trim();
  const label = action === "approve" ? "通过" : "剔除";
  if (!id) {
    alert(`缺少图片 ID，无法${label}`);
    return;
  }
  if (!confirm(`确认${label}这张图？\n${id}`)) return;
  const res = await window.ApiClient.raw(`/api/pipeline/review/${encodeURIComponent(id)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) {
    alert(data.detail || data.message || `${label}失败`);
    return;
  }
  const current = collectPipelineFailures(window.__lastPixivJob || {});
  const next = current.filter((x) => x.id !== id);
  const job = { pipeline_failures: next };
  if (window.__lastPixivJob) {
    window.__lastPixivJob.pipeline_failures = next;
    if (window.__lastPixivJob.result) window.__lastPixivJob.result.pipeline_failures = next;
  }
  renderPipelineReview(job);
  setStatus(document.getElementById("jobStatus"), data.message || `已${label}`, "ok");
  if (data.resume && data.resume.resumed) {
    const pollToken = ++jobPollGen;
    updateJobProgress({ status: "running", progress: { label: "继续上传", percent: 0 } });
    setStatus(document.getElementById("jobStatus"), data.resume.message || "人工审查已处理，继续上传…", "ok");
    await pollJob(pollToken);
    return;
  }
  if (data.resume && data.resume.pending) {
    setStatus(document.getElementById("jobStatus"), data.resume.message || `还有 ${data.resume.pending} 张待人工审查`, "ok");
    return;
  }
  await resumeLastLaunchAfterReview();
}

async function resumeLastLaunchAfterReview() {
  const req = window.__lastLaunchRequest;
  const job = window.__lastPixivJob || {};
  if (!req || job.status !== "error") return;
  if (collectPipelineFailures(job).length) return;
  const st = document.getElementById("jobStatus");
  updateJobProgress({ status: "running", progress: { label: req.uploadOnly ? "上传" : "一键起号", percent: 0 } });
  setStatus(st, "人工审查已处理，继续上传…", "ok");
  const res = await window.ApiClient.raw(req.url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req.payload),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) {
    updateJobProgress({ status: "error", progress: { label: "继续失败", percent: 0 } });
    setStatus(st, data.detail || data.message || "继续失败，请手动重新上传", "err");
    return;
  }
  const pollToken = ++jobPollGen;
  await pollJob(pollToken);
}

function collectPipelineFailures(job) {
  const seen = new Set();
  const out = [];
  const push = (raw) => {
    if (!raw) return;
    const id = String(raw.id || raw.image_id || "").trim();
    if (!id || seen.has(id)) return;
    seen.add(id);
    out.push({
      id,
      message: String(raw.message || raw.error || "后处理失败，待人工审查"),
    });
  };
  (job && job.pipeline_failures || []).forEach(push);
  const result = (job && job.result) || {};
  (result.pipeline_failures || []).forEach(push);
  return out;
}

function renderPipelineReview(job) {
  const box = document.getElementById("pipelineReview");
  const list = document.getElementById("pipelineReviewList");
  const title = document.getElementById("pipelineReviewTitle");
  if (!box || !list || !title) return;
  const failures = collectPipelineFailures(job);
  if (!failures.length) {
    box.classList.add("hidden");
    list.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  title.textContent = `待人工审查 · ${failures.length} 张`;
  list.innerHTML = failures.map((it) => {
    const id = it.id.replace(/[<>&"]/g, "");
    const msg = it.message.replace(/[<>&]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));
    return `<div class="px-review-item">
      <img src="/data/generated/${encodeURIComponent(id)}.png?t=${Date.now()}" alt="${id}" onerror="this.style.opacity=.35;this.title='图片无法预览，可能已截断或损坏'" />
      <div>
        <div class="px-review-id">${id}</div>
        <div class="px-review-msg">${msg}</div>
        <div class="px-review-actions">
          <button type="button" data-review-action="approve" data-review-id="${id}">通过</button>
          <button type="button" data-review-action="exclude" data-review-id="${id}">剔除</button>
          <a href="/data/generated/${encodeURIComponent(id)}.png" target="_blank" rel="noopener">预览原图</a>
          <a href="/generated?g=${encodeURIComponent(id)}" target="_blank" rel="noopener">生成图库</a>
          <button type="button" data-reveal-id="${id}">定位文件</button>
        </div>
      </div>
    </div>`;
  }).join("");
  list.querySelectorAll("[data-reveal-id]").forEach((btn) => {
    btn.addEventListener("click", () => revealGeneratedImage(btn.dataset.revealId || ""));
  });
  list.querySelectorAll("[data-review-action]").forEach((btn) => {
    btn.addEventListener("click", () => reviewPipelineImage(
      btn.dataset.reviewId || "",
      btn.dataset.reviewAction || "",
    ));
  });
}

function formatPixivAuthError(err, fallback) {
  const e = err || {};
  const msg = e.message || fallback || "登录失败";
  const parts = [`<div><strong>${escapeHtml(msg)}</strong></div>`];
  if (e.status_code) {
    parts.push(`<div>HTTP ${escapeHtml(e.status_code)}${e.code != null ? ` · Pixiv code ${escapeHtml(e.code)}` : ""}</div>`);
  }
  if (e.hint) parts.push(`<div class="hint">${escapeHtml(e.hint)}</div>`);
  return parts.join("");
}

function renderPixivAuth(px, opts) {
  const silent = opts && opts.silent;
  lastPixivAuth = px || null;
  const badge = document.getElementById("pixivAuthBadge");
  const box = document.getElementById("pixivAuthBox");
  const st = document.getElementById("pixivAuthStatus");
  if (!badge || !box || !st) return;

  if (!px || !px.has_refresh_token) {
    badge.className = "px-auth-badge pending";
    badge.textContent = "未配置";
    box.className = "px-auth-box hidden";
    box.innerHTML = "";
    setStatus(st, "请先添加 refresh_token", "");
    updateAccountSetupDisclosure();
    return;
  }

  if (px.ok) {
    const who = (px.user && (px.user.name || px.user.account)) || "Pixiv 用户";
    badge.className = "px-auth-badge ok";
    badge.textContent = "已登录";
    box.className = "px-auth-box ok";
    box.innerHTML = `<div><strong>${escapeHtml(who)}</strong>${px.user && px.user.id ? ` · uid ${escapeHtml(px.user.id)}` : ""}</div><div class="hint">可以上传作品与刷新数据看板</div>`;
    box.classList.remove("hidden");
    setStatus(st, `登录有效，可以上传`, "ok");
    renderUploadAccountBanner();
    renderAccounts();
    refreshReadyStrip();
    updateAccountSetupDisclosure();
    return;
  }

  badge.className = "px-auth-badge err";
  badge.textContent = "登录失败";
  const err = px.error || {};
  box.className = "px-auth-box err";
  box.innerHTML = formatPixivAuthError(err, px.message);
  box.classList.remove("hidden");
  setStatus(st, err.hint || px.message || "登录失败，请按上方说明重新获取 token", "err");
  refreshReadyStrip();
  updateAccountSetupDisclosure();
}

function updateAccountSetupDisclosure() {
  const setup = document.getElementById("pixivAccountSetup");
  if (!setup) return;
  const ready = accounts.some((account) => isAccountReadyForUpload(account))
    && !!(lastPixivAuth && lastPixivAuth.ok);
  setup.open = !ready;
}

function parsePngTextLines(raw) {
  const out = {};
  String(raw || "").split("\n").forEach((line) => {
    const t = line.trim();
    if (!t || t.startsWith("#")) return;
    const i = t.indexOf("=");
    if (i <= 0) return;
    out[t.slice(0, i).trim()] = t.slice(i + 1).trim();
  });
  return out;
}

function formatPngTextLines(obj) {
  if (!obj || typeof obj !== "object") return "";
  return Object.entries(obj).map(([k, v]) => `${k}=${v}`).join("\n");
}

function mosaicPartsFromForm() {
  const parts = [];
  if (document.getElementById("pipeMosaicPartPenis").checked) parts.push("欧金金");
  if (document.getElementById("pipeMosaicPartPussy").checked) parts.push("欧芒果");
  if (document.getElementById("pipeMosaicPartNipple").checked) parts.push("欧派派");
  return parts.length ? parts : ["欧金金", "欧芒果", "欧派派"];
}

function applyMosaicParts(parts) {
  const set = new Set(parts || []);
  document.getElementById("pipeMosaicPartPenis").checked = set.has("欧金金");
  document.getElementById("pipeMosaicPartPussy").checked = set.has("欧芒果");
  document.getElementById("pipeMosaicPartNipple").checked = set.has("欧派派");
}

function toggleMosaicDetail() {
  document.getElementById("pipeMosaicDetail").style.display = "block";
}

async function refreshMosaicRuntimeStatus() {
  const st = document.getElementById("pipeMosaicStatus");
  if (!st) return;
  try {
    const res = await window.ApiClient.raw("/api/pipeline/config");
    const data = await readJsonResponse(res);
    const rt = data.mosaic_runtime || {};
    const root = (rt && rt.anr_root) || (data.config && data.config.anr_root) || "";
    st.textContent = [rt.message || (data.anr_available ? "ANR 打码可用" : "ANR 未配置"), root].filter(Boolean).join(" · ");
    st.className = "px-status" + (rt.ok ? " ok" : " err");
  } catch (e) {
    st.textContent = "无法检测打码环境：" + e.message;
    st.className = "px-status err";
  }
  refreshReadyStrip();
}

function pipelinePayloadFromForm() {
  return {
    anr_root: document.getElementById("pipeAnrRoot").value.trim(),
    only_missing: document.getElementById("pipeOnlyMissing").checked,
    upscale: {
      enabled: document.getElementById("pipeUpscaleEnabled").checked,
      scale: Number(document.getElementById("pipeUpscaleScale").value) || 2,
    },
    mosaic: {
      enabled: true,
      method: document.getElementById("pipeMosaicMethod").value || "像素",
      intensity: Number(document.getElementById("pipeMosaicIntensity").value) || 24,
      parts: mosaicPartsFromForm(),
    },
    metadata: {
      enabled: document.getElementById("pipeMetaEnabled").checked,
      custom_note: document.getElementById("pipeMetaNote").value.trim(),
      custom_note_key: document.getElementById("pipeMetaNoteKey").value.trim() || "pixiv-nai-gallery",
      png_text: parsePngTextLines(document.getElementById("pipeMetaText").value),
    },
  };
}

function fmtDelta(n, opts) {
  const unreliable = opts && opts.unreliable;
  if (n === null || n === undefined) {
    return `<span class="px-delta px-delta-zero" title="${unreliable ? "样本不足或数据波动" : "暂无对比"}">—</span>`;
  }
  const v = Number(n);
  if (!Number.isFinite(v)) return `<span class="px-delta px-delta-zero">—</span>`;
  if (v > 0) return `<span class="px-delta px-delta-up" title="较上次快照增加">▲ +${v.toLocaleString("zh-CN")}</span>`;
  if (v < 0) {
    const title = unreliable ? "数据波动（已忽略异常回落）" : "较上次快照减少";
    return `<span class="px-delta px-delta-down" title="${title}">▼ ${v.toLocaleString("zh-CN")}</span>`;
  }
  return `<span class="px-delta px-delta-zero">0</span>`;
}

function getUploadAccountId() {
  return activeAccountId || "";
}

function activeAccountInfo() {
  const id = getUploadAccountId();
  return accounts.find((a) => a.id === id) || null;
}

function isAccountReadyForUpload(acc) {
  if (!acc) return false;
  if (acc.identity_mismatch) return false;
  if (acc.upload_ready === true) return true;
  if (acc.id === activeAccountId && lastPixivAuth && lastPixivAuth.ok) return true;
  return false;
}

function accountOptionLabel(acc) {
  const label = acc.label || "未命名";
  const who = acc.user_name || acc.user_account || (acc.has_token ? "待检测登录" : "需重新登录");
  const uid = acc.pixiv_user_id ? `uid ${acc.pixiv_user_id}` : "";
  const flags = [];
  if (acc.identity_mismatch) flags.push("身份不一致");
  if (!acc.has_token) flags.push("未登录");
  const suffix = flags.length ? ` [${flags.join(" · ")}]` : "";
  return [label, who, uid].filter(Boolean).join(" · ") + suffix;
}

function renderUploadAccountBanner() {
  const currentEl = document.getElementById("uploadAccountCurrent");
  const hintEl = document.getElementById("uploadAccountHint");
  if (!accounts.length) {
    currentEl.textContent = "未登录 Pixiv 账号";
    hintEl.textContent = "请先在 ① 区登录 Pixiv 账号；上传只会使用当前登录账号。";
    return;
  }
  const nextId = accounts.some((a) => a.id === activeAccountId)
    ? activeAccountId
    : (accounts[0] && accounts[0].id) || "";
  const acc = accounts.find((a) => a.id === nextId) || null;
  if (!acc) return;
  currentEl.textContent = accountOptionLabel(acc);
  if (acc.identity_mismatch) {
    hintEl.textContent = `⚠ 「${acc.label}」与 Pixiv 登录名不一致，请重新通行密钥登录后再上传，不要和另一个号混用 token。`;
    return;
  }
  if (!isAccountReadyForUpload(acc)) {
    hintEl.textContent = `账号「${acc.label}」尚未配置 token。请先在 ① 区选中该账号，单独通行密钥登录。`;
    return;
  }
  const liveOk = acc.id === activeAccountId && lastPixivAuth && lastPixivAuth.ok;
  hintEl.textContent = liveOk
    ? `当前上传号：${accountOptionLabel(acc)}（① 已检测登录，可以上传）`
    : `当前上传号：${accountOptionLabel(acc)}。建议点 ①「检测登录」确认后再上传。`;
}

function fmtStatValue(v) {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return Number.isFinite(n) ? n.toLocaleString("zh-CN") : String(v);
}

function renderAccounts() {
  const box = document.getElementById("accountList");
  if (!accounts.length) {
    box.innerHTML = `<div class="px-status">暂无账号，请添加 refresh_token</div>`;
    return;
  }
  const authOk = !!(lastPixivAuth && lastPixivAuth.ok);
  const statMap = {};
  ((statsData && statsData.items) || []).forEach((it) => {
    statMap[it.account_id] = it.latest || {};
  });
  box.innerHTML = accounts.map((acc) => {
    const active = acc.id === activeAccountId;
    const who = acc.user_name || acc.user_account || (acc.has_token ? "待检测登录" : "无 Token");
    const latest = statMap[acc.id] || {};
    const fans = fmtStatValue(latest.followers);
    const dotCls = active
      ? (authOk ? "ok" : (lastPixivAuth && lastPixivAuth.has_refresh_token ? "err" : ""))
      : "";
    const mismatch = !!acc.identity_mismatch;
    const ready = isAccountReadyForUpload(acc);
    const warnTag = mismatch
      ? '<span class="tag warn">身份不一致</span>'
      : (!ready ? '<span class="tag warn">需登录</span>' : "");
    return `<div class="px-acc-item${active ? " active" : ""}${mismatch ? " mismatch" : ""}" data-id="${escapeHtml(acc.id)}" title="${active ? "当前上传号（仅此一个）" : "点击切换为当前上传号"}">
      <div class="name"><span class="px-acc-dot ${dotCls}"></span>${escapeHtml(acc.label || "未命名")}${active ? '<span class="tag">当前上传号</span>' : ""}${warnTag}</div>
      <div class="sub">${escapeHtml(who)}${acc.pixiv_user_id ? " · uid " + escapeHtml(acc.pixiv_user_id) : ""}${fans !== "—" ? " · 粉丝 " + escapeHtml(fans) : ""}</div>
    </div>`;
  }).join("");
  box.querySelectorAll(".px-acc-item").forEach((el) => {
    el.addEventListener("click", () => switchAccount(el.dataset.id));
  });
}

function renderStats() {
  const grid = document.getElementById("statsGrid");
  const meta = document.getElementById("statsMeta");
  const interval = document.getElementById("statsInterval");
  const items = (statsData && statsData.items) || [];
  const hours = (statsData && statsData.refresh_interval_hours) || 6;
  interval.textContent = `每 ${hours}h 刷新`;
  const last = (statsData && statsData.last_refresh_at) || "";
  meta.textContent = last
    ? `上次刷新：${last.replace("T", " ").slice(0, 19)} · 各账号独立统计，对比本账号上一快照`
    : "尚未采集数据，点「立即刷新」或等待自动刷新（每个账号单独记录）";
  if (!items.length) {
    grid.innerHTML = `<div class="px-status">暂无统计数据</div>`;
    return;
  }
  grid.innerHTML = items.map((it) => {
    const latest = it.latest || {};
    const delta = it.delta || {};
    const active = it.account_id === activeAccountId;
    const cap = latest.captured_at ? latest.captured_at.replace("T", " ").slice(0, 16) : "—";
    const who = it.user_name || latest.user_name || it.user_account || latest.user_account || "";
    const uid = it.pixiv_user_id || latest.pixiv_user_id || "";
    const deltaOpts = { unreliable: it.delta_reliable === false };
    const whoLine = [who, uid ? `uid ${uid}` : ""].filter(Boolean).join(" · ");
    return `<div class="px-stat-card${active ? " active" : ""}">
      <div class="title">${escapeHtml(it.label || it.account_id)}${active ? "（当前上传号）" : ""}</div>
      ${whoLine ? `<div class="sub" style="margin-bottom:4px;font-size:0.72rem;color:#9aa7bd">${escapeHtml(whoLine)}</div>` : ""}
      <div class="px-stat-row">
        <span>粉丝 <strong>${fmtStatValue(latest.followers)}</strong> ${fmtDelta(delta.followers, deltaOpts)}</span>
        <span>浏览 <strong>${fmtStatValue(latest.views)}</strong> ${fmtDelta(delta.views, deltaOpts)}</span>
        <span>作品 <strong>${fmtStatValue(latest.illusts)}</strong> ${fmtDelta(delta.illusts, deltaOpts)}</span>
      </div>
      <div class="sub" style="margin-top:4px;font-size:0.72rem;color:#7a8499">快照 ${cap} · 共 ${it.history_points || 0} 点${it.history_points < 2 ? " · 需至少 2 次刷新才显示变化" : ""}</div>
    </div>`;
  }).join("");
}

function renderAnalytics(analysis, generatedAt) {
  const box = document.getElementById("analyticsBox");
  const a = analysis || {};
  if (!a.summary && !(a.trends || []).length) {
    box.textContent = "暂无分析结果";
    return;
  }
  const sections = [];
  if (generatedAt) sections.push(`<div style="color:#7a8499;font-size:0.72rem;margin-bottom:8px">生成于 ${escapeHtml(String(generatedAt).replace("T", " ").slice(0, 19))}</div>`);
  if (a.summary) sections.push(`<div>${escapeHtml(a.summary)}</div>`);
  if ((a.trends || []).length) {
    sections.push(`<h3>趋势观察</h3><ul>${a.trends.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`);
  }
  if ((a.account_highlights || []).length) {
    sections.push(`<h3>账号亮点</h3><ul>${a.account_highlights.map((h) =>
      `<li><strong>${escapeHtml(h.account_label || h.label || "")}</strong>：${escapeHtml(h.note || h.key_metric || h.status || "")}</li>`
    ).join("")}</ul>`);
  }
  if ((a.recommendations || []).length) {
    sections.push(`<h3>运营建议</h3><ul>${a.recommendations.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`);
  }
  if ((a.risks || []).length) {
    sections.push(`<h3>风险提醒</h3><ul>${a.risks.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`);
  }
  if ((a.next_actions || []).length) {
    sections.push(`<h3>下一步行动</h3><ul>${a.next_actions.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>`);
  }
  box.innerHTML = sections.join("");
}

async function switchAccount(accountId) {
  if (!accountId || accountId === activeAccountId) return;
  const res = await window.ApiClient.raw("/api/pixiv/accounts/switch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: accountId }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) return alert(data.detail || "切换失败");
  activeAccountId = accountId;
  await loadConfig();
  if (data.message) {
    setStatus(document.getElementById("pixivAuthStatus"), data.message, "ok");
  }
}

function applyActiveAccountToForm(activeAcc, accountCfg) {
  const acc = activeAcc || {};
  const cfgAcc = accountCfg || {};
  const direction = acc.direction || cfgAcc.direction || "AI 生成图爱好者，分享 NovelAI 同人插画";
  document.getElementById("direction").value = direction;
  const persona = (acc.persona && Object.keys(acc.persona).length) ? acc.persona : cfgAcc.persona;
  if (persona && Object.keys(persona).length) {
    personaCache = persona;
    document.getElementById("personaBox").value = JSON.stringify(persona, null, 2);
  }
}

async function loadConfig() {
  const res = await window.ApiClient.raw("/api/pixiv/config");
  const data = await res.json();
  config = data.config || {};
  const presets = data.presets || {};
  Object.assign(PRESETS, presets);

  const ai = config.ai || {};
  const account = config.account || {};
  const upload = config.upload || {};
  const pipeline = config.pipeline || {};
  const up = pipeline.upscale || {};
  const mo = pipeline.mosaic || {};
  const md = pipeline.metadata || {};

  const provSel = document.getElementById("aiProvider");
  provSel.innerHTML = "";
  Object.keys(presets).forEach((name) => {
    const opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    provSel.appendChild(opt);
  });
  provSel.value = ai.provider || Object.keys(presets)[0] || "";
  document.getElementById("aiBase").value = ai.api_base || "";
  document.getElementById("aiModel").value = ai.model || "";
  accounts = (data.accounts || []).map((acc) => {
    const row = { ...acc };
    const aid = row.id;
    const px = data.pixiv || {};
    if (aid && aid === ((data.stats && data.stats.active_id) || (data.active_account && data.active_account.id) || "")) {
      if (px.ok) {
        row.upload_ready = true;
        row.has_token = row.has_token !== false;
      }
    }
    return row;
  });
  activeAccountId = (data.stats && data.stats.active_id) || (data.active_account && data.active_account.id) || "";
  statsData = data.stats || null;
  renderAccounts();
  renderStats();

  const activeAcc = data.active_account || accounts.find((a) => a.id === activeAccountId) || null;
  applyActiveAccountToForm(activeAcc, account);
  document.getElementById("nicknameHint").value = account.nickname_hint || "";
  document.getElementById("autoPipeline").checked = upload.auto_pipeline !== false;
  document.getElementById("autoGenCopy").checked = upload.auto_generate_copy !== false;
  document.getElementById("pipeOnlyMissing").checked = pipeline.only_missing !== false;
  document.getElementById("pipeAnrRoot").value = pipeline.anr_root || "";
  document.getElementById("pipeUpscaleEnabled").checked = up.enabled !== false;
  document.getElementById("pipeUpscaleScale").value = up.scale || 2;
  document.getElementById("pipeMosaicEnabled").checked = true;
  document.getElementById("pipeMosaicMethod").value = mo.method || "像素";
  document.getElementById("pipeMosaicIntensity").value = mo.intensity || 24;
  applyMosaicParts(mo.parts || ["欧金金", "欧芒果", "欧派派"]);
  toggleMosaicDetail();
  document.getElementById("pipeMetaEnabled").checked = md.enabled !== false;
  document.getElementById("pipeMetaNote").value = md.custom_note || "";
  document.getElementById("pipeMetaNoteKey").value = md.custom_note_key || "pixiv-nai-gallery";
  document.getElementById("pipeMetaText").value = formatPngTextLines(md.png_text || {});

  renderPixivAuth(data.pixiv || {}, { silent: true });
  renderAccounts();
  renderUploadAccountBanner();

  const aiSt = data.ai || {};
  setStatus(
    document.getElementById("aiAuthStatus"),
    aiSt.has_api_key
      ? `AI 已配置：${aiSt.provider || ""} / ${aiSt.model || ""}`
      : "未配置 AI Key（将使用本地文案模板）",
    aiSt.has_api_key ? "ok" : "",
  );
  refreshReadyStrip();
}

async function loadCandidates(opts) {
  const silent = opts && opts.silent;
  const skipSidebar = opts && opts.skipSidebar;
  const items = (opts && opts.items) || null;
  let list = items;
  if (!list) {
    const res = await window.ApiClient.raw("/api/pixiv/candidates");
    const data = await res.json();
    list = data.items || [];
  }
  if (!skipSidebar) {
    candidatesItems = list;
    lastCandidateCount = list.length;
    lastPreviewSig = previewSignature(list);
    renderGenSidebarItems(list);
  }
  const box = document.getElementById("candidates");
  box.innerHTML = "";
  if (!list.length) {
    setStatus(document.getElementById("pickStatus"), "生成图库为空，请先去作品页生成");
    return;
  }
  list.forEach((item) => {
    const card = document.createElement("div");
    card.className = "px-cand" + (item.id === selectedId ? " selected" : "");
    card.title = item.id;
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = item.processed_url || item.image_url;
    img.alt = item.id;
    card.appendChild(img);
    const sm = document.createElement("small");
    sm.textContent = (item.created_at || "").replace("T", " ").slice(0, 16) || item.id;
    card.appendChild(sm);
    card.addEventListener("click", () => selectImage(item));
    box.appendChild(card);
  });
  const boot = qs("image");
  if (boot && !selectedId && !qs("group")) {
    const hit = list.find((x) => x.id === boot);
    if (hit) selectImage(hit);
  }
  if (!silent && !selectedId && list.length) {
    setStatus(document.getElementById("pickStatus"), `共 ${list.length} 张，右侧栏滚轮切换预览`);
  }
}

function clearGroupSelection() {
  selectedGroupId = "";
  selectedGroupIds = new Set();
  selectedImageIds = [];
  refreshGroupSelectionUI();
  const seriesBtn = document.getElementById("pxGenWheelPickSeries");
  if (seriesBtn) seriesBtn.hidden = true;
}

async function applyGroupFocus(group, opts) {
  const silent = opts && opts.silent;
  if (!group || !group.image_ids || !group.image_ids.length) return;
  selectedGroupId = String(group.group_id || "");
  selectedImageIds = group.image_ids.slice();
  selectedId = selectedImageIds[0];
  setPickMode("series");
  document.querySelectorAll(".px-cand").forEach((el) => el.classList.remove("selected"));

  const primary = (group.items || []).find((x) => x.id === selectedId) || (group.items || [])[0] || {};
  const url = primary.processed_url || primary.image_url || group.cover_url;
  document.getElementById("previewImg").src = url;
  renderPipelineStatus(primary);
  const title = group.source_title || (group.work_id ? `作品 ${group.work_id}` : "独立生成");
  const groups = getSelectedGroups();
  const merged = getMergedSelectionStats();
  const previewLines = groups.length > 1
    ? [
        `<div><strong>已选 ${merged.count} 个系列</strong> · 合并共 ${merged.total} 张为一篇投稿</div>`,
        `<div>当前预览：${escapeHtml(title)}（${selectedImageIds.length} 张）</div>`,
        `<div>上传顺序：按所选系列依次拼接各页</div>`,
      ]
    : [
        `<div><strong>系列 ${escapeHtml(selectedGroupId)}</strong> · ${selectedImageIds.length} 张</div>`,
        `<div>${escapeHtml(title)}</div>`,
        group.work_id ? `<div>源作品 #${group.work_id}</div>` : `<div>独立试生成</div>`,
        `<div>将按 Pixiv 多页漫画投稿</div>`,
        group.pipeline_pending
          ? `<div>待补后处理：${group.pipeline_pending} 张</div>`
          : `<div>后处理已齐全（或已关闭）</div>`,
      ];
  document.getElementById("previewMeta").innerHTML = previewLines.filter(Boolean).join("");
  updatePickStatusFromGroups(group);

  if (Array.isArray(group.items) && group.items.length) {
    candidatesItems = group.items.slice();
    lastPreviewSig = previewSignature(candidatesItems);
    renderGenSidebarItems(candidatesItems);
  }
  const seriesBtn = document.getElementById("pxGenWheelPickSeries");
  if (seriesBtn) seriesBtn.hidden = false;
  if (groups.length <= 1) {
    history.replaceState({}, "", `/pixiv?group=${encodeURIComponent(selectedGroupId)}`);
  } else {
    history.replaceState({}, "", "/pixiv");
  }
  if (document.getElementById("autoGenCopy").checked && !silent) {
    await generateCopy(true);
  }
}

async function selectGroup(group, opts) {
  if (!group || !group.image_ids || !group.image_ids.length) return;
  leavePreparedDraftMode();
  selectedGroupIds = new Set([String(group.group_id || "")]);
  refreshGroupSelectionUI();
  await applyGroupFocus(group, opts);
  refreshReadyStrip();
}

async function toggleGroupSelect(group, e) {
  if (!group || !group.image_ids || !group.image_ids.length) return;
  const gid = String(group.group_id || "");
  const multi = e && (e.ctrlKey || e.metaKey);
  if (multi) {
    if (selectedGroupIds.has(gid)) {
      selectedGroupIds.delete(gid);
      if (!selectedGroupIds.size) {
        clearGroupSelection();
        setStatus(document.getElementById("pickStatus"), "已取消全部系列选择");
        document.getElementById("previewMeta").innerHTML = "";
        document.getElementById("previewImg").removeAttribute("src");
        renderPipelineStatus(null);
        return;
      }
      if (selectedGroupId === gid) {
        const remain = Array.from(selectedGroupIds);
        const next = launchGroups.find((g) => String(g.group_id) === remain[remain.length - 1]);
        if (next) await applyGroupFocus(next, { silent: true });
        else refreshGroupSelectionUI();
        return;
      }
      refreshGroupSelectionUI();
      updatePickStatusFromGroups(launchGroups.find((g) => String(g.group_id) === selectedGroupId));
      renderPipelineStatus(null);
      return;
    }
    selectedGroupIds.add(gid);
    refreshGroupSelectionUI();
    await applyGroupFocus(group, { silent: true });
    return;
  }
  await selectGroup(group, { silent: false });
}

async function selectImage(item) {
  leavePreparedDraftMode();
  clearGroupSelection();
  selectedId = item.id;
  setPickMode("single");
  document.querySelectorAll(".px-cand").forEach((el) => {
    el.classList.toggle("selected", el.title === item.id);
  });
  const url = item.processed_url || item.image_url;
  document.getElementById("previewImg").src = url;
  renderPipelineStatus(item);
  const miss = (item.pipeline && item.pipeline.missing || []).join("、");
  document.getElementById("previewMeta").innerHTML = [
    `<div><strong>${escapeHtml(item.id)}</strong></div>`,
    item.work_id ? `<div>源作品 #${escapeHtml(item.work_id)}</div>` : `<div>独立试生成</div>`,
    item.model ? `<div>模型：${escapeHtml(item.model)}</div>` : "",
    item.processed_url
      ? `<div>上传文件：${escapeHtml(item.id)}_final.png</div>`
      : `<div>上传前将自动补后处理，产出 ${escapeHtml(item.id)}_final.png</div>`,
    miss ? `<div>待补后处理：${escapeHtml(miss)}</div>` : `<div>后处理已齐全（或已关闭）</div>`,
  ].filter(Boolean).join("");
  setStatus(document.getElementById("pickStatus"), `已选单张：${item.id}`, "ok");
  refreshReadyStrip();
  if (candidatesItems.length) {
    syncGenFocusIndex(candidatesItems);
    updateGenWheelFocus({ scroll: true });
  } else {
    renderGenSidebarItems([item]);
  }
  history.replaceState({}, "", `/pixiv?image=${encodeURIComponent(item.id)}`);
  if (document.getElementById("autoGenCopy").checked) {
    await generateCopy(true);
  } else {
    await restorePostDraftIfEmpty(item.id);
  }
}

// 刷新/换图后恢复磁盘草稿：仅当表单为空时填充，不覆盖用户已编辑内容
async function restorePostDraftIfEmpty(imageId) {
  const formEmpty = !document.getElementById("postTitle").value.trim()
    && !document.getElementById("postCaption").value.trim()
    && !document.getElementById("postTags").value.trim();
  if (!formEmpty) return;
  try {
    const res = await window.ApiClient.raw(`/api/pixiv/draft?image_id=${encodeURIComponent(imageId)}`);
    const data = await res.json().catch(() => ({}));
    const draft = data.draft || {};
    if (data.ok && (draft.title || draft.title_ja || draft.title_zh)) {
      fillPostForm(draft);
      setStatus(document.getElementById("copyStatus"), "已从磁盘草稿恢复文案（上次生成）", "ok");
    }
  } catch (_) { /* 草稿不可读时静默跳过 */ }
}

function fillPostForm(post) {
  const p = post || {};
  document.getElementById("postTitleJa").value = p.title_ja || "";
  document.getElementById("postTitleZh").value = p.title_zh || "";
  document.getElementById("postCaptionJa").value = p.caption_ja || "";
  document.getElementById("postCaptionZh").value = p.caption_zh || "";
  document.getElementById("postTitle").value = p.title || p.title_ja || p.title_zh || "";
  document.getElementById("postCaption").value = p.caption || "";
  document.getElementById("postTags").value = (p.tags || []).slice(0, 10).join(" ");
  // 程序化填充不算用户修改
  resetPostFormDirty();
}

function selectPreparedDraft(item, index) {
  if (!item || !Array.isArray(item.image_ids) || !item.image_ids.length) return;
  const imageIds = item.image_ids.map((value) => String(value || "").trim()).filter(Boolean);
  if (!imageIds.length) return;

  selectedId = String(item.image_id || imageIds[0]);
  selectedImageIds = imageIds;
  selectedGroupId = "";
  selectedGroupIds = new Set();
  preparedUploadPayload = {
    image_id: selectedId,
    image_ids: imageIds.slice(),
    restrict: Number(item.restrict) || 0,
    x_restrict: String(item.x_restrict || ""),
    illust_type: Number(item.illust_type) || 0,
    prepared_package_id: String((preparedPackage && preparedPackage.package_id) || ""),
    prepared_item_index: Number(index) || 0,
  };

  fillPostForm(item.post || {});
  setPickMode("series");
  refreshGroupSelectionUI();
  document.querySelectorAll(".px-cand").forEach((el) => el.classList.remove("selected"));
  const preview = candidatesItems.find((candidate) => candidate.id === selectedId) || {};
  const previewUrl = preview.processed_url || preview.image_url || "";
  if (previewUrl) document.getElementById("previewImg").src = previewUrl;
  document.getElementById("previewMeta").innerHTML = [
    `<div><strong>已准备草稿 ${Number(index) + 1}</strong> · ${imageIds.length} 张</div>`,
    `<div>首图：${escapeHtml(selectedId)}</div>`,
    "<div>后处理与投稿文案已由管家准备；页面不会自动上传</div>",
  ].join("");
  setStatus(
    document.getElementById("pickStatus"),
    `已载入准备草稿 ${Number(index) + 1}（${imageIds.length} 张），只会上传当前草稿`,
    "ok"
  );
  setStatus(
    document.getElementById("preparedDraftStatus"),
    `当前为第 ${Number(index) + 1} 份草稿，共 ${imageIds.length} 张。检查账号、标题、简介与标签后，再手动确认上传。`,
    "ok"
  );
  document.querySelectorAll("[data-prepared-index]").forEach((button) => {
    button.classList.toggle("primary", Number(button.dataset.preparedIndex) === Number(index));
  });
  const launch = document.getElementById("launchBtn");
  const upload = document.getElementById("uploadOnly");
  if (launch) {
    launch.disabled = true;
    launch.title = "准备包已有文案和后处理结果，请使用右侧按钮上传当前草稿";
  }
  if (upload) upload.textContent = "检查后上传当前草稿";
  refreshReadyStrip();
}

async function applyPreparedPackage() {
  const wantsPrepared = qs("prepared") === "1" || !!qs("package");
  if (!wantsPrepared) return;
  const packageId = qs("package");
  const suffix = packageId
    ? `?package_id=${encodeURIComponent(packageId)}`
    : "";
  const res = await window.ApiClient.raw(`/api/pixiv/prepared${suffix}`);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
  const prepared = data.prepared;
  const box = document.getElementById("preparedDraftBox");
  const status = document.getElementById("preparedDraftStatus");
  if (!prepared || !Array.isArray(prepared.items) || !prepared.items.length) {
    if (box) box.classList.remove("hidden");
    setStatus(status, "未找到可用的管家准备包；不会执行上传。", "err");
    return;
  }

  preparedPackage = prepared;
  if (box) box.classList.remove("hidden");
  const list = document.getElementById("preparedDraftList");
  list.innerHTML = "";
  prepared.items.forEach((item, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "px-btn";
    button.dataset.preparedIndex = String(index);
    button.textContent = `草稿 ${index + 1} · ${(item.image_ids || []).length} 张`;
    button.addEventListener("click", () => selectPreparedDraft(item, index));
    list.appendChild(button);
  });
  selectPreparedDraft(prepared.items[0], 0);
}

async function saveUploadFlags() {
  await window.ApiClient.raw("/api/pixiv/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      upload: {
        use_processed: true,
        auto_pipeline: document.getElementById("autoPipeline").checked,
        auto_generate_copy: document.getElementById("autoGenCopy").checked,
      },
      pipeline: pipelinePayloadFromForm(),
    }),
  });
}

document.getElementById("pipeMosaicEnabled").addEventListener("change", toggleMosaicDetail);
document.getElementById("savePipelineCfg").addEventListener("click", async () => {
  await saveUploadFlags();
  alert("后处理配置已保存");
  await refreshMosaicRuntimeStatus();
  await loadCandidates();
});

async function pollJob(pollToken) {
  const st = document.getElementById("jobStatus");
  const maxMs = 2 * 60 * 60 * 1000;
  const started = Date.now();
  while (Date.now() - started < maxMs) {
    if (pollToken !== jobPollGen) return;
    await new Promise((r) => setTimeout(r, 2000));
    if (pollToken !== jobPollGen) return;
    const res = await window.ApiClient.raw("/api/pixiv/status");
    const data = await res.json();
    const job = data.job || {};
    window.__lastPixivJob = job;
    renderPipelineReview(job);
    const elapsed = Math.floor((Date.now() - started) / 1000);
    const mins = Math.floor(elapsed / 60);
    const secs = elapsed % 60;
    const tick = mins > 0 ? `${mins}分${secs}秒` : `${secs}秒`;
    if (job.status === "done") {
      const r = job.result || {};
      updateJobProgress(job, "完成");
      renderPipelineReview(job);
      setStatus(
        st,
        `完成！${r.pixiv_url ? "作品页：" + r.pixiv_url : "illust_id=" + (r.illust_id || "?")}\n步骤：${(r.steps || []).join(" → ")}`,
        "ok"
      );
      await loadHistory();
      return;
    }
    if (job.status === "error") {
      updateJobProgress(job, "失败");
      renderPipelineReview(job);
      // 多系列部分成功：明确告知已有作品上线并刷新上传记录，避免用户误以为全失败而重复投稿
      const uploads = (job.result && Array.isArray(job.result.uploads)) ? job.result.uploads : [];
      if (uploads.length) {
        const links = uploads
          .map((u) => (u && u.pixiv_url) || (u && u.illust_id ? `https://www.pixiv.net/artworks/${u.illust_id}` : ""))
          .filter(Boolean);
        setStatus(
          st,
          `部分系列失败：${job.message || "未知错误"}\n已成功上线 ${uploads.length} 篇${links.length ? "：" + links.join("、") : ""}，请勿整批重试`,
          "err"
        );
        await loadHistory();
      } else {
        setStatus(st, job.message || "失败", "err");
      }
      return;
    }
    if (job.status === "running") {
      const hint = job.message || "运行中…";
      updateJobProgress(job, hint);
      const p = job.progress || {};
      const pct = Number(p.percent) ? ` · ${Math.round(Number(p.percent))}%` : "";
      setStatus(st, `${hint}${pct}（已等待 ${tick}，多图上传较慢属正常）`);
      continue;
    }
    updateJobProgress(job, "等待中");
    setStatus(st, `任务状态：${job.status || "未知"}（已等待 ${tick}）`);
  }
  setStatus(
    st,
    "页面轮询已满 2 小时；后台可能仍在投稿，请稍后再看本页状态或上传记录",
    "err"
  );
}

const publishSubmissionGuard = window.PixivPublishUI.createSubmissionGuard();

async function runLaunch(uploadOnly) {
  if (!selectedId && !selectedGroupIds.size) return alert("请先选一张图或一个系列");
  await saveUploadFlags();
  const usingPreparedDraft = !!preparedUploadPayload;
  const payload = {
    ...(usingPreparedDraft ? preparedUploadPayload : {}),
    account_id: getUploadAccountId(),
    image_id: selectedId,
    direction: document.getElementById("direction").value.trim(),
    nickname_hint: document.getElementById("nicknameHint").value.trim(),
    extra: document.getElementById("postExtra").value.trim(),
    regen_persona: document.getElementById("regenPersona").checked,
    title: document.getElementById("postTitle").value.trim(),
    caption: document.getElementById("postCaption").value.trim(),
    tags: document.getElementById("postTags").value.trim().split(/\s+/).filter(Boolean).slice(0, 10),
  };
  if (!usingPreparedDraft && selectedGroupIds.size > 1) {
    payload.group_ids = Array.from(selectedGroupIds);
    payload.merge_groups = true;
  } else if (!usingPreparedDraft && selectedGroupId) {
    payload.group_id = selectedGroupId;
    payload.image_ids = selectedImageIds.slice();
  }
  const effectiveUploadOnly = uploadOnly || usingPreparedDraft;
  const url = effectiveUploadOnly ? "/api/pixiv/upload" : "/api/pixiv/launch";
  const st = document.getElementById("jobStatus");
  const acc = activeAccountInfo();
  if (!acc) {
    alert("请先在左侧 ① 区登录并高亮一个 Pixiv 账号；上传只会使用当前账号。");
    return;
  }
  if (acc.identity_mismatch) {
    alert(`账号「${acc.label}」身份不一致，请为该号单独通行密钥登录后再上传`);
    return;
  }
  if (!isAccountReadyForUpload(acc)) {
    alert(`账号「${acc.label}」尚未配置 token，请先在 ① 区选中该号并通行密钥登录`);
    return;
  }
  // 空标题/空标签不允许直接确认：后端会静默改用 AI/默认值投稿，
  // 用户必须显式选择「先生成」或「确认留空」。
  if (!payload.title) {
    alert("标题为空。请先点「生成标题 & 简介」或手动填写后再投稿——留空会被自动替换为 AI 文案。");
    return;
  }
  if (!payload.tags.length) {
    if (!confirm("Tags 为空，投稿时会使用账号默认标签。确定继续吗？")) return;
  }
  const merged = selectedGroupIds.size > 1 ? getMergedSelectionStats() : null;
  const imageCount = merged
    ? merged.total
    : Math.max(1, selectedImageIds.length || (selectedId ? 1 : 0));
  const ratingKey = String(((config || {}).upload || {}).x_restrict || "r18").toLowerCase();
  const rating = ratingKey === "general"
    ? "全年龄"
    : (ratingKey === "r18g" ? "R-18G" : "R-18");
  const pipeline = document.getElementById("autoPipeline").checked
    ? "自动补齐：超分 / 强制打码 / 清元数据"
    : "不自动补跑；使用现有后处理结果";
  const action = merged
    ? `${effectiveUploadOnly ? "仅上传" : "一键起号上传"}（合并 ${merged.count} 个系列）`
    : (usingPreparedDraft ? "上传管家准备草稿" : (effectiveUploadOnly ? "仅上传" : "一键起号上传"));
  const confirmation = window.PixivPublishUI.buildConfirmation({
    action,
    account: [acc.label || "未命名", acc.user_name || acc.user_account || ""]
      .filter(Boolean)
      .join(" · "),
    imageCount,
    title: payload.title,
    tags: payload.tags,
    rating,
    pipeline,
  });
  if (!confirm(confirmation)) return;

  const publishButtons = [
    document.getElementById("launchBtn"),
    document.getElementById("uploadOnly"),
  ];
  window.PixivPublishUI.setBusy(publishButtons, true);
  try {
    updateJobProgress({ status: "running", progress: { label: effectiveUploadOnly ? "上传" : "一键起号", percent: 0 } });
    renderPipelineReview({ pipeline_failures: [] });
    window.__lastLaunchRequest = { url, payload: JSON.parse(JSON.stringify(payload)), uploadOnly: effectiveUploadOnly };
    setStatus(st, effectiveUploadOnly ? "上传中…" : "一键起号运行中…");
    const res = await window.ApiClient.raw(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      updateJobProgress({ status: "error", progress: { label: "启动失败", percent: 0 } });
      setStatus(st, data.detail || data.message || "请求失败", "err");
      return;
    }
    if (!data.ok) {
      updateJobProgress({ status: "error", progress: { label: "启动失败", percent: 0 } });
      setStatus(st, data.message || data.detail || "启动失败", "err");
      return;
    }
    setStatus(st, data.message || (effectiveUploadOnly ? "浏览器投稿运行中…" : "一键起号运行中…"));
    const pollToken = ++jobPollGen;
    await pollJob(pollToken);
  } catch (error) {
    updateJobProgress({ status: "error", progress: { label: "请求失败", percent: 0 } });
    setStatus(st, error && error.message ? error.message : "请求失败", "err");
  } finally {
    window.PixivPublishUI.setBusy(publishButtons, false);
  }
}

async function doLaunch(uploadOnly) {
  const publishButtons = [
    document.getElementById("launchBtn"),
    document.getElementById("uploadOnly"),
  ];
  if (!publishSubmissionGuard.tryAcquire()) {
    setStatus(document.getElementById("jobStatus"), "投稿请求已提交，请等待当前任务返回，勿重复点击");
    return;
  }
  window.PixivPublishUI.setBusy(publishButtons, true);
  try {
    await runLaunch(uploadOnly);
  } finally {
    publishSubmissionGuard.release();
    window.PixivPublishUI.setBusy(publishButtons, false);
  }
}

document.getElementById("launchBtn").addEventListener("click", () => doLaunch(false));
document.getElementById("uploadOnly").addEventListener("click", () => doLaunch(true));
document.getElementById("pipelineReviewOpenFolder").addEventListener("click", async () => {
  try {
    const data = await window.ApiClient.request("/api/storage/open?target=generated", { method: "POST" });
    if (!data || data.opened === false) {
      alert((data && data.message) || "当前系统无法自动打开文件夹");
    }
  } catch (err) {
    alert((err && err.message) || "无法打开生成目录");
  }
});

async function loadHistory() {
  const res = await window.ApiClient.raw("/api/pixiv/history?limit=8");
  const data = await res.json();
  const box = document.getElementById("historyBox");
  const items = data.items || [];
  if (!items.length) {
    box.textContent = "暂无上传记录";
    return;
  }
  box.innerHTML = items.map((it) => {
    const when = (it.uploaded_at || "").replace("T", " ").slice(0, 16);
    const safeUrl = safeHttpUrl(it.pixiv_url, "");
    const link = safeUrl
      ? `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener">${escapeHtml(safeUrl)}</a>`
      : escapeHtml(it.illust_id || "");
    const accTag = it.account_label || it.user_name || "";
    const accHtml = accTag
      ? `<span class="px-history-acc" title="上传账号">${escapeHtml(accTag)}</span>`
      : "";
    return `<div class="px-history-item">${accHtml}${escapeHtml(when)} · ${escapeHtml(it.title || "")} · ${link}</div>`;
  }).join("");
}

["autoPipeline", "autoGenCopy"].forEach((id) => {
  document.getElementById(id).addEventListener("change", saveUploadFlags);
});

async function loadCachedAnalytics() {
  try {
    const res = await window.ApiClient.raw("/api/pixiv/analytics?account_id=all");
    const data = await res.json();
    if (data.analysis && Object.keys(data.analysis).length) {
      renderAnalytics(data.analysis, data.generated_at);
    }
  } catch (_) {}
}

document.getElementById("pickTabSeries").addEventListener("click", () => setPickMode("series"));
document.getElementById("pickTabSingle").addEventListener("click", () => setPickMode("single"));

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    refreshGenSidebar();
    scheduleGenSidebarPoll();
  }
});

// 刷新/重开页面后重接后台任务：running 则恢复进度条与轮询，done/error 展示终态
async function resumePixivJobOnBoot() {
  try {
    const res = await window.ApiClient.raw("/api/pixiv/status");
    const data = await res.json().catch(() => ({}));
    const job = data.job || {};
    if (job.status === "running") {
      const st = document.getElementById("jobStatus");
      updateJobProgress(job, job.message || "运行中");
      renderPipelineReview(job);
      setStatus(st, `检测到后台投稿任务仍在运行，已重新接管进度显示（${job.message || "运行中…"}）`);
      const pollToken = ++jobPollGen;
      pollJob(pollToken).catch(() => {});
    } else if (job.status === "done" || job.status === "error") {
      updateJobProgress(job, job.status === "done" ? "完成" : "失败");
      renderPipelineReview(job);
    }
  } catch (_) { /* 状态接口不可达时不影响页面其余初始化 */ }
}

(async () => {
  await loadConfig();
  await Promise.all([loadGroups(), loadCandidates()]);
  await applyPreparedPackage();
  await loadHistory();
  await loadCachedAnalytics();
  await refreshMosaicRuntimeStatus();
  await refreshGenSidebar();
  scheduleGenSidebarPoll();
  refreshReadyStrip();
  await resumePixivJobOnBoot();
  // Soft auto-test auth when token exists so readiness chips update
  if (activeAccountId && accounts.some((a) => a.id === activeAccountId && a.has_token)) {
    try {
      const res = await window.ApiClient.raw("/api/pixiv/auth/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ account_id: activeAccountId }),
      });
      const data = await res.json().catch(() => ({}));
      renderPixivAuth({
        ok: data.ok,
        has_refresh_token: true,
        user: data.user,
        message: data.message,
        error: data.error,
      });
    } catch (_) { /* ignore network flakiness on boot */ }
    refreshReadyStrip();
  }
})();

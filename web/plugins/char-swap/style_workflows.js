// Production owner for style preset CRUD and draft style replacement workflows.

import { state, saveCurrentDraftToCache, buildStyleBundleFallback, draftPageCache, draftCacheKey, persistDraftCache, loadDraftFromCache } from "./state.js?v=f80b97d795";
import { api, $, deepClone, setMsg, flashMsg, copyText, loadPluginConfig, invalidatePluginConfig } from "./api.js?v=0411b73ad6";
import {
  presetStyle as readPresetStyle,
  stylePresetDetail as describeStyleReference,
  styleBundleFindText as findStyleBundleText,
  styleBundleFromSelection,
  styleFindCandidates,
  styleTags,
  normalizeStyleReference,
  loadStyleReferences,
} from "./style_references.js?v=c0563853cb";
import {
  loadExtract,
  renderStyleRows,
  resetDraftFromOriginal,
  runTransform,
  runTransformAllPages,
  syncSeedUi,
  syncStyleFromResponse,
  updateDraftPreview,
} from "./workbench_bridge.js?v=e72141834f";

let editingStylePresetId = "";
export function presetStyle(preset) {
    return readPresetStyle(preset);
  }

export function stylePresetDetail(preset) {
    return describeStyleReference(preset);
  }

export function styleBundleFindText(bundle) {
    return findStyleBundleText(bundle);
  }

export function recognizedStyleFind(opts = {}) {
    if (opts.combined) return String(opts.combined).trim();
    return styleBundleFindText(state.styleBundle);
  }

export function collectStyleFindCandidates(opts = {}) {
    return styleFindCandidates(opts);
  }

export function styleBundleFromOpts(opts = {}) {
    return styleBundleFromSelection(opts);
  }

export function collectAllStyleTags(opts = {}) {
    return styleTags(opts);
  }

export async function mutateStyleOnComment(comment, find, replace) {
    const findText = String(find || "").trim();
    const replaceText = replace != null ? String(replace) : "";
    const body = { patched_comment: deepClone(comment) };
    if (!findText && replaceText) {
      body.mode = "append";
      body.replace = replaceText;
    } else if (!findText) {
      throw new Error("请填写要替换的画风片段，或选择画风预设");
    } else {
      body.find = findText;
      body.replace = replaceText;
    }
    return await api("/api/plugin/char-swap/style", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

export function applyStyleResponseToState(res) {
    state.draft = res.patched_comment;
    syncStyleFromResponse(res);
    updateDraftPreview();
    saveCurrentDraftToCache();
  }

export async function runClearThenApplyOnComment(comment, opts, replace) {
    const repl = replace != null ? String(replace) : "";
    let working = deepClone(comment);
    if (!working) throw new Error("草稿未加载");

    const fullOpts = {
      ...opts,
      bundle: styleBundleFromOpts(opts),
      slots: opts.slots || [],
    };
    let cleared = 0;
    let lastRes = null;

    const candidates = collectStyleFindCandidates(fullOpts).sort((a, b) => b.length - a.length);
    for (const find of candidates) {
      const res = await mutateStyleOnComment(working, find, "");
      working = res.patched_comment;
      cleared += Number(res.replacements) || 0;
      if (Number(res.replacements) > 0) lastRes = res;
    }
    for (const tag of [...collectAllStyleTags(fullOpts)].reverse()) {
      const res = await mutateStyleOnComment(working, tag, "");
      working = res.patched_comment;
      cleared += Number(res.replacements) || 0;
      if (Number(res.replacements) > 0) lastRes = res;
    }

    let added = 0;
    if (repl.trim()) {
      const res = await mutateStyleOnComment(working, "", repl);
      working = res.patched_comment;
      added = Number(res.replacements) || 0;
      lastRes = res;
    }

    const ok = cleared > 0 || added > 0;
    let message;
    if (repl.trim()) {
      if (cleared && added) message = `已消除画风 ${cleared} 处并加入新画风`;
      else if (added) message = "未识别到可消除的画风，已追加新画风";
      else if (cleared) message = `已消除画风 ${cleared} 处`;
      else message = "未匹配到可消除的画风";
    } else if (cleared) {
      message = `已消除画风 ${cleared} 处`;
    } else {
      message = "未匹配到可消除的画风";
    }

    const res = {
      ...(lastRes || {}),
      ok: true,
      patched_comment: working,
      replacements: ok ? Math.max(cleared + added, added || cleared) : 0,
      message,
    };
    return { res, cleared, added };
  }

export async function runClearThenApplyStyle(opts, replace, initialComment) {
    const fullOpts = {
      ...opts,
      slots: opts.slots || state.styleSlots || [],
    };
    const { res, cleared, added } = await runClearThenApplyOnComment(
      initialComment || state.draft,
      fullOpts,
      replace,
    );
    if (!initialComment) {
      applyStyleResponseToState(res);
    }
    return { res, findUsed: "", cleared, added };
  }

export async function runStyleReplaceWithFallback(opts, replace) {
    return runClearThenApplyStyle(opts, replace);
  }

export async function refreshStylePresetUi() {
    invalidatePluginConfig();
    await loadPluginConfig(true);
    await fillStylePresetSelects();
    if (typeof window.renderStylePresetSettingsList === "function") {
      window.renderStylePresetSettingsList();
    }
  }

export function isStylePresetApiMissing(err) {
    const msg = String((err && err.message) || err || "").toLowerCase();
    return msg.includes("not found") || msg.includes("404");
  }

export function normalizeStylePresetEntry(body, fallbackId) {
    const label = String(body.label || "").trim();
    if (!label) throw new Error("请填写预设名");
    return normalizeStyleReference({ ...body, label }, fallbackId || `style_${Date.now()}`);
  }

export async function saveStylePresetsViaConfig(presets) {
    await api("/api/plugin/char-swap/config", {
      method: "POST",
      body: JSON.stringify({ style_presets: presets }),
    });
  }

export async function upsertStylePreset(body, method) {
    const mode = method === "PUT" ? "PUT" : "POST";
    try {
      return await api("/api/plugin/char-swap/style-presets", {
        method: mode,
        body: JSON.stringify(body),
      });
    } catch (e) {
      if (!isStylePresetApiMissing(e)) throw e;
      const cfg = await loadPluginConfig(true);
      const presets = [...(cfg.style_presets || [])];
      const entry = normalizeStylePresetEntry(
        body,
        mode === "PUT" ? body.id : `style_${Date.now()}`,
      );
      if (mode === "PUT") {
        const idx = presets.findIndex((p) => String(p.id || "") === String(entry.id));
        if (idx < 0) throw new Error("画风预设不存在");
        presets[idx] = entry;
      } else {
        if (presets.some((p) => String(p.id || "") === entry.id)) {
          throw new Error("预设 id 已存在");
        }
        presets.push(entry);
      }
      await saveStylePresetsViaConfig(presets);
      return { ok: true, preset: entry, presets, message: "画风预设已保存（兼容模式）" };
    }
  }

export async function deleteStylePreset(presetId) {
    const pid = String(presetId || "").trim();
    if (!pid) throw new Error("预设 id 为空");
    try {
      return await api(`/api/plugin/char-swap/style-presets?id=${encodeURIComponent(pid)}`, {
        method: "DELETE",
      });
    } catch (e) {
      if (!isStylePresetApiMissing(e)) throw e;
      const cfg = await loadPluginConfig(true);
      const presets = (cfg.style_presets || []).filter((p) => String(p.id || "") !== pid);
      if (presets.length === (cfg.style_presets || []).length) {
        throw new Error("画风预设不存在");
      }
      await saveStylePresetsViaConfig(presets);
      return { ok: true, presets, message: "画风预设已删除（兼容模式）" };
    }
  }

export function showSaveStylePresetModal(style, msgEl, defaultLabel) {
    dismissCharSwapModals();
    const backdrop = document.createElement("div");
    backdrop.className = "char-swap-modal-backdrop";
    const modal = document.createElement("div");
    modal.className = "char-swap-modal char-swap-modal-save-style";
    modal.innerHTML = `
      <h3>加入画风预设</h3>
      <p class="char-swap-modal-hint">将当前识别到的画风串存入预设，之后可在「画风替换」中一键选用。</p>
      <label class="char-swap-modal-field-label" for="charSwapSaveStyleLabel">预设名称</label>
      <input id="charSwapSaveStyleLabel" class="char-swap-modal-field-input" type="text" autocomplete="off" />
      <div class="char-swap-modal-field-label">画风内容</div>
      <div id="charSwapSaveStylePreview" class="char-swap-save-style-preview"></div>
      <div class="char-swap-modal-foot">
        <button type="button" class="char-swap-btn" id="charSwapSaveStyleCancel">取消</button>
        <button type="button" class="char-swap-btn primary" id="charSwapSaveStyleOk">保存</button>
      </div>`;
    const labelInput = $("#charSwapSaveStyleLabel", modal);
    const previewEl = $("#charSwapSaveStylePreview", modal);
    const okBtn = $("#charSwapSaveStyleOk", modal);
    const cancelBtn = $("#charSwapSaveStyleCancel", modal);
    if (labelInput) {
      labelInput.value = String(defaultLabel || style.slice(0, 36) || "").trim();
      labelInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          okBtn?.click();
        }
      });
    }
    if (previewEl) previewEl.textContent = style;
    const previouslyFocused = document.activeElement;
    const close = () => {
      backdrop.remove();
      document.removeEventListener("keydown", onKeydown, true);
      // 焦点还给触发源，键盘用户不丢上下文
      if (previouslyFocused && typeof previouslyFocused.focus === "function") {
        try { previouslyFocused.focus(); } catch { }
      }
    };
    const onKeydown = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        close();
        setMsg(msgEl, "已取消加入画风预设", false);
      }
    };
    document.addEventListener("keydown", onKeydown, true);
    cancelBtn?.addEventListener("click", () => {
      close();
      setMsg(msgEl, "已取消加入画风预设", false);
    });
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) {
        close();
        setMsg(msgEl, "已取消加入画风预设", false);
      }
    });
    okBtn?.addEventListener("click", async () => {
      const name = String((labelInput && labelInput.value) || "").trim();
      if (!name) {
        setMsg(msgEl, "请填写预设名称", false);
        labelInput?.focus();
        return;
      }
      okBtn.disabled = true;
      cancelBtn.disabled = true;
      setMsg(msgEl, "正在保存画风预设…", true);
      try {
        const res = await upsertStylePreset({ label: name, style }, "POST");
        await refreshStylePresetUi();
        close();
        setMsg(msgEl, res.message || `已加入画风预设：${name}`, true);
      } catch (e) {
        const text = e.message || "保存画风预设失败";
        setMsg(msgEl, text, false);
        window.alert(`加入画风预设失败：${text}`);
        okBtn.disabled = false;
        cancelBtn.disabled = false;
      }
    });
    backdrop.appendChild(modal);
    document.body.appendChild(backdrop);
    setTimeout(() => {
      labelInput?.focus();
      labelInput?.select();
    }, 0);
  }

export async function saveCurrentStyleAsPreset(combined, msgEl, defaultLabel) {
    const style = String(combined || "").trim();
    if (!style) {
      setMsg(msgEl, "当前没有可存入的画风串", false);
      return;
    }
    showSaveStylePresetModal(style, msgEl, defaultLabel);
  }

export async function fillStylePresetSelects() {
    const presets = await loadStyleReferences();
    const fill = (sel, withEmpty) => {
      if (!sel) return;
      sel.innerHTML = withEmpty ? '<option value="">画风预设…</option>' : "";
      presets.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.id || p.label;
        opt.textContent = p.label || presetStyle(p) || "画风预设";
        opt.dataset.style = presetStyle(p);
        sel.appendChild(opt);
      });
    };
    fill(document.getElementById("charSwapStylePreset"), true);
    fill(document.getElementById("batchStylePreset"), true);
  }

export async function renderStylePresetSettingsList() {
      const listEl = document.getElementById("charSwapStylePresetList");
      if (!listEl) return;
      listEl.textContent = "加载中…";
      try {
        const cfg = await loadPluginConfig(true);
        const presets = cfg.style_presets || [];
        if (!presets.length) {
          listEl.innerHTML = '<div class="meta">暂无画风预设，可在下方表单添加。</div>';
          return;
        }
        listEl.innerHTML = "";
        presets.forEach((preset) => {
          const row = document.createElement("div");
          row.className = "char-swap-style-preset-item";
          const main = document.createElement("div");
          main.className = "char-swap-style-preset-main";
          const title = document.createElement("div");
          title.className = "char-swap-style-preset-title";
          title.textContent = preset.label || preset.id || "预设";
          const detail = document.createElement("div");
          detail.className = "meta";
          detail.textContent = stylePresetDetail(preset);
          main.appendChild(title);
          main.appendChild(detail);
          const actions = document.createElement("div");
          actions.className = "char-swap-style-preset-actions";
          const editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.className = "char-swap-btn";
          editBtn.textContent = "编辑";
          editBtn.addEventListener("click", () => {
            editingStylePresetId = String(preset.id || "");
            const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
            set("stylePresetLabel", preset.label || "");
            set("stylePresetStyle", presetStyle(preset));
            const addBtn = document.getElementById("charSwapAddStylePreset");
            const cancelBtn = document.getElementById("charSwapCancelStylePreset");
            if (addBtn) addBtn.textContent = "保存画风预设";
            if (cancelBtn) cancelBtn.style.display = "";
            document.getElementById("stylePresetLabel")?.focus();
          });
          const delBtn = document.createElement("button");
          delBtn.type = "button";
          delBtn.className = "char-swap-btn";
          delBtn.textContent = "删除";
          delBtn.addEventListener("click", async () => {
            const pid = String(preset.id || "");
            if (!pid) return;
            if (!window.confirm(`删除画风预设「${preset.label || pid}」？`)) return;
            try {
              await deleteStylePreset(pid);
              if (editingStylePresetId === pid) resetStylePresetForm();
              await refreshStylePresetUi();
              statusEl.textContent = `已删除画风预设：${preset.label || pid}`;
            } catch (e) {
              statusEl.textContent = e.message;
            }
          });
          actions.appendChild(editBtn);
          actions.appendChild(delBtn);
          row.appendChild(main);
          row.appendChild(actions);
          listEl.appendChild(row);
        });
      } catch (e) {
        listEl.textContent = `加载失败: ${e.message}`;
      }
    }

export function resetStylePresetForm() {
      editingStylePresetId = "";
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
      set("stylePresetLabel", "");
      set("stylePresetStyle", "");
      const addBtn = document.getElementById("charSwapAddStylePreset");
      const cancelBtn = document.getElementById("charSwapCancelStylePreset");
      if (addBtn) addBtn.textContent = "添加画风预设";
      if (cancelBtn) cancelBtn.style.display = "none";
    }

export async function applyStylePreset(preset, panel, msgEl, opts = {}) {
    const replace = presetStyle(preset);

    if (opts.scope === "all") {
      return runStyleReplaceAllPages(replace, panel, msgEl, preset.label || preset.id || "画风", {
        combined: opts.combined || "",
      });
    }

    const { res } = await runClearThenApplyStyle(
      { combined: opts.combined || "" },
      replace,
    );
    renderStyleRows(panel);
    renderSlotRows(panel);
    const findEl = $("#charSwapStyleFind", panel);
    const replaceEl = $("#charSwapStyleReplace", panel);
    if (findEl) findEl.value = styleBundleFindText(state.styleBundle) || "";
    if (replaceEl) replaceEl.value = replace;
    flashMsg(
      msgEl,
      `${res.message || "画风已更新"} → ${preset.label || preset.id}（仅草稿）`,
      Number(res.replacements) > 0,
    );
    return res;
  }

export function openStyleReplaceModal(panel, msgEl, opts = {}) {
    flashMsg(msgEl, "正在打开画风预设（先消除再加入）…", true);
    showStylePresetModal(async (preset, scope) => {
      try {
        if (scope === "all" && msgEl) {
          flashMsg(msgEl, "正在替换全部图片画风…", true);
        }
        await applyStylePreset(preset, panel, msgEl, {
          combined: opts.combined || "",
          scope,
        });
      } catch (e) {
        flashMsg(msgEl, e.message || String(e), false);
      }
    }, {
      showAllPagesChoice: !!opts.showAllPagesChoice,
      pageCount: opts.pageCount,
      allPagesOnly: !!opts.allPagesOnly,
      panel,
      msgEl,
    });
  }

export async function runStyleReplaceOnDraft(find, replace, opts = {}) {
    if (!state.draft) throw new Error("草稿未加载");
    const findText = String(find || "").trim();
    const replaceText = replace != null ? String(replace) : "";
    const body = { patched_comment: state.draft };
    if (!findText && replaceText) {
      body.mode = "append";
      body.replace = replaceText;
    } else if (!findText) {
      throw new Error("请填写要替换的画风片段，或选择画风预设");
    } else {
      body.find = findText;
      body.replace = replaceText;
    }
    const res = await api("/api/plugin/char-swap/style", {
      method: "POST",
      body: JSON.stringify(body),
    });
    state.draft = res.patched_comment;
    syncStyleFromResponse(res);
    updateDraftPreview();
    saveCurrentDraftToCache();
    return res;
  }

export async function runStyleReplaceAllPages(replace, panel, msgEl, presetLabel, opts = {}) {
    const workId = state.workId;
    if (!workId) throw new Error("无作品 ID");
    const pageCount = Math.max(1, Number(state.imagePageCount) || 1);
    saveCurrentDraftToCache();
    if (msgEl) setMsg(msgEl, `正在消除并加入画风（全部 ${pageCount} 张）…`, true);

    let ok = 0;
    const errors = [];
    const noop = [];
    for (let pi = 0; pi < pageCount; pi++) {
      try {
        if (msgEl) setMsg(msgEl, `正在处理画风… p${pi}（${pi + 1}/${pageCount}）`, true);
        const cacheKey = draftCacheKey(workId, pi);
        const cached = draftPageCache.get(cacheKey);
        let draft = cached && cached.draft ? deepClone(cached.draft) : null;
        let draftChars = cached && cached.draftChars ? deepClone(cached.draftChars) : null;
        let styleSlots = cached && cached.styleSlots ? deepClone(cached.styleSlots) : null;
        let styleBundle = cached && cached.styleBundle ? deepClone(cached.styleBundle) : null;
        if (!draft || !styleBundle) {
          const { data } = await loadExtract(workId, pi);
          if (!draft) {
            draft = deepClone(data.comment);
            draftChars = deepClone(data.chars || []);
          }
          styleSlots = deepClone(data.style_slots || []);
          styleBundle = deepClone(data.style_bundle || buildStyleBundleFallback(data.style_slots || []));
        }
        const { res } = await runClearThenApplyOnComment(
          draft,
          { bundle: styleBundle, slots: styleSlots || [], combined: opts.combined || "" },
          replace,
        );
        if (!res.replacements) {
          noop.push(`p${pi}: ${res.message || "未匹配到画风"}`);
          continue;
        }
        draftPageCache.set(cacheKey, {
          cacheVersion: 8,
          draft: deepClone(res.patched_comment),
          draftChars: deepClone(res.chars || []),
          styleSlots: deepClone(res.style_slots || []),
          styleBundle: deepClone(res.style_bundle || buildStyleBundleFallback(res.style_slots || [])),
          lastRemoved: [],
        });
        persistDraftCache();
        ok++;
      } catch (e) {
        errors.push(`p${pi}: ${e.message}`);
      }
    }

    if (!loadDraftFromCache(workId, state.pageIndex)) {
      resetDraftFromOriginal();
    }
    renderStyleRows(panel);
    renderSlotRows(panel);
    syncSeedUi(panel);
    const findEl = panel && $("#charSwapStyleFind", panel);
    const replaceEl = panel && $("#charSwapStyleReplace", panel);
    const curFind = recognizedStyleFind();
    if (findEl && curFind) findEl.value = curFind;
    if (replaceEl) replaceEl.value = replace != null ? String(replace) : "";

    if (!errors.length && !noop.length) {
      setMsg(msgEl, `已全部 ${pageCount} 张图画风替换完成（${presetLabel}）`, true);
    } else if (ok > 0) {
      const extra = [...noop, ...errors].filter(Boolean);
      setMsg(msgEl, `画风替换完成 ${ok}/${pageCount} 张${extra.length ? `；${extra.join("；")}` : ""}`, extra.length ? false : true);
    } else {
      const extra = [...errors, ...noop].filter(Boolean);
      setMsg(msgEl, extra.length ? extra.join("；") : "全部图片画风替换失败", false);
    }
    return { ok, errors, noop };
  }

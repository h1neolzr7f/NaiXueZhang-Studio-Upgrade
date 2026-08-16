// Production owner for the CharSwap panel shell and settings page.
// Workflow orchestration remains in panel.js; this Module owns DOM construction
// and settings-side effects.

import { state } from "./state.js?v=f80b97d795";
import { api, loadPluginConfig } from "./api.js?v=980573fcbd";
import {
  deleteStylePreset,
  presetStyle,
  refreshStylePresetUi,
  stylePresetDetail,
  upsertStylePreset,
} from "./presets.js?v=f16dbe971d";
export function buildPanel() {
    const panel = document.createElement("div");
    panel.className = "char-swap-panel";
    panel.id = "charSwapPanel";
    panel.innerHTML = `
      <div class="char-swap-head">
        <div>
          <strong>角色与画风草稿</strong>
          <div class="char-swap-hint">单张试生成 / 批量生成均在此配置草稿，<b>不会修改</b>图库原文</div>
        </div>
        <span class="char-swap-badge">草稿编辑区</span>
      </div>
      <div class="char-swap-body">
        <div class="char-swap-source-bar empty" id="charSwapSourceBar"></div>
        <div class="char-swap-original" id="charSwapOriginalHint"></div>
        <div class="char-swap-section-title" id="charSwapSlotsTitle">编辑中草稿（角色槽）— 每行右侧有「设为源」</div>
        <div class="char-swap-slots-draft"></div>
        <div class="char-swap-quick-presets" id="charSwapQuickPresets">
          <span>⚡ 常用角色一键替换：</span>
          <button type="button" class="char-swap-btn primary" data-quick-preset="wisadel">♀ 维什戴尔</button>
          <button type="button" class="char-swap-btn primary" data-quick-preset="surtr">♀ 史尔特尔</button>
          <button type="button" class="char-swap-btn primary" data-quick-preset="doctor_m">♂ 博士</button>
          <button type="button" class="char-swap-btn primary" data-quick-preset="silverash_m">♂ 银灰</button>
          <button type="button" class="char-swap-btn" data-quick-preset="more_female">更多女角 (120+) ▾</button>
          <button type="button" class="char-swap-btn" data-quick-preset="more_male">更多男角 (40+) ▾</button>
        </div>
        <div class="char-swap-section-title">画风识别（画师+画风合并为一串）— 每行右侧有「画风替换」</div>
        <div class="char-swap-style-slots"></div>
        <div class="char-swap-section-title">草稿指令预览</div>
        <pre class="char-swap-draft-pre" id="charSwapDraftPreview"></pre>
        <div class="char-swap-style-row">
          <span class="char-swap-style-label">画风替换</span>
          <input id="charSwapStyleFind" type="text" placeholder="当前画风（应用时先消除）" autocomplete="off" />
          <span class="char-swap-style-arrow">→</span>
          <input id="charSwapStyleReplace" type="text" placeholder="要加入的画风（可留空=只消除）" autocomplete="off" />
          <select id="charSwapStylePreset" title="画风预设"></select>
          <button type="button" class="char-swap-btn" data-action="style-apply">应用画风</button>
        </div>
        <div class="char-swap-seed-row">
          <label for="charSwapSeed">Seed</label>
          <input id="charSwapSeed" type="text" inputmode="numeric" placeholder="原图 seed" autocomplete="off" />
          <button type="button" class="char-swap-btn" data-action="seed-random">随机 -1</button>
          <span class="char-swap-seed-hint" id="charSwapSeedHint"></span>
        </div>
        <div class="char-swap-toolbar">
          <button type="button" class="char-swap-btn" data-action="clone">+ 追加</button>
          <button type="button" class="char-swap-btn" data-action="reset">恢复当前原文</button>
          <button type="button" class="char-swap-btn char-swap-btn-all-pages" data-action="reset-all">恢复全部原文</button>
          <button type="button" class="char-swap-btn" data-action="sanitize">净化预览</button>
          <button type="button" class="char-swap-btn char-swap-btn-creature" data-action="replace-creature">贵物→搭档（默认博士）</button>
          <button type="button" class="char-swap-btn" data-action="copy">复制草稿指令</button>
          <button type="button" class="char-swap-btn" data-action="add-batch">加入批量（当前图）</button>
          <button type="button" class="char-swap-btn char-swap-btn-all-pages" data-action="add-batch-all-pages">全部图片加入批量</button>
          <button type="button" class="char-swap-btn char-swap-btn-multi-role" data-action="replace-female-multi" style="display:none">多女角换角</button>
          <button type="button" class="char-swap-btn char-swap-btn-multi-role" data-action="replace-male-multi" style="display:none">多男角换角</button>
          <button type="button" class="char-swap-btn char-swap-btn-all-pages" data-action="replace-male-all">换男角·全部图片</button>
          <button type="button" class="char-swap-btn char-swap-btn-all-pages" data-action="replace-female-all">换女角·全部图片</button>
          <button type="button" class="char-swap-btn char-swap-btn-all-pages char-swap-btn-style" data-action="replace-style-all">画风替换·全部图片</button>
          <button type="button" class="char-swap-btn primary" data-action="generate">单张试生成 ▶</button>
          <button type="button" class="char-swap-btn" data-action="toggle">收起</button>
        </div>
        <div class="char-swap-diff" style="display:none"></div>
        <div class="char-swap-preview" style="display:none"><img alt="试生成结果" /></div>
        <div class="char-swap-msg"></div>
      </div>`;
    return panel;
  }

export function mountSettings() {
    const host = document.getElementById("fcExtraSettings");
    if (!host || document.getElementById("charSwapSettings")) return;

    const box = document.createElement("div");
    box.id = "charSwapSettings";
    box.className = "char-swap-settings";
    box.innerHTML = `
      <div class="fc-divider"></div>
      <div style="display:flex; align-items:center; gap:8px; margin-bottom:12px;">
        <strong style="font-size:1.05rem; color:#9ec5ff;">角色生图插件</strong>
        <span style="font-size:0.75rem; opacity:0.6;">Char-Swap · Batch · Tasteful Prompts</span>
      </div>

      <!-- 通用设置 -->
      <div class="char-swap-section" style="margin-bottom:14px;">
        <div style="font-size:0.85rem; font-weight:600; margin-bottom:6px; opacity:0.85;">通用设置</div>
        <div style="display:grid; grid-template-columns:1fr 1fr; gap:4px 12px; font-size:0.9rem;">
          <label class="char-swap-check"><input type="checkbox" id="cfgPluginEnabled" checked /> 启用生图工作台</label>
          <label class="char-swap-check"><input type="checkbox" id="cfgAutoSanitize" checked /> 试生成前自动去尼</label>
          <label class="char-swap-check"><input type="checkbox" id="cfgSanitizeRacial" checked /> 去尼：种族/强壮肌肉男</label>
          <label class="char-swap-check"><input type="checkbox" id="cfgSanitizeGore" checked /> 净化：猎奇 gross</label>
          <label class="char-swap-check"><input type="checkbox" id="cfgReplaceCreature" checked /> 贵物/异种 → 搭档预设</label>
          <label class="char-swap-check"><input type="checkbox" id="cfgForceFree" checked /> Opus 免费路径（≤28步）</label>
          <label class="char-swap-check"><input type="checkbox" id="cfgPreserveAction" /> 保留原图姿势/动作</label>
        </div>
        <div style="margin-top:6px; display:flex; align-items:center; gap:8px; font-size:0.9rem;">
          <span>NAI 提示词类型</span>
          <select id="cfgPromptProfile" style="background:#1a1f2b; color:#dbe7f5; border:1px solid #445; padding:2px 6px; border-radius:4px;"></select>
        </div>
      </div>

      <!-- NAI Tokens - 突出显示 -->
      <div class="char-swap-section" style="margin-bottom:16px; padding:10px; background:rgba(30,38,55,0.6); border:1px solid rgba(110,182,255,0.25); border-radius:8px;">
        <div style="font-size:0.85rem; font-weight:600; margin-bottom:4px; color:#9ec5ff;">NAI / Xianyun Token Pool</div>
        <textarea id="charSwapToken" class="char-swap-token-pool" placeholder="每行一个：pst-xxx (NovelAI) 或 xianyun:API_KEY (Xianyun)。混合槽位并发。" autocomplete="off" rows="3" style="width:100%; font-family:Consolas, monospace; font-size:0.82rem; background:#0f131c; border:1px solid #445; color:#dbe7f5; padding:6px; border-radius:4px; resize:vertical;"></textarea>
        <div style="display:flex; flex-wrap:wrap; gap:6px; margin-top:6px;">
          <button type="button" class="btn outline" id="charSwapSaveAll" style="padding:4px 10px; font-size:0.85rem;">保存配置</button>
          <button type="button" class="btn outline" id="charSwapReplaceTokens" style="padding:4px 10px; font-size:0.85rem;">覆盖保存 Token 池</button>
          <button type="button" class="btn outline" id="charSwapAddToken" style="padding:4px 10px; font-size:0.85rem;">加入 Token 槽位</button>
          <button type="button" class="btn outline" id="charSwapCheckTokens" style="padding:4px 10px; font-size:0.85rem;">检查并清理坏 Token</button>
        </div>
        <div id="charSwapTokenSlots" class="char-swap-token-slots" style="margin-top:8px;"></div>
        <div style="font-size:0.72rem; opacity:0.6; margin-top:2px;">一行一个 token；仅“覆盖保存 Token 池”会替换整个池子，“加入 Token 槽位”只追加。</div>
      </div>

      <!-- 角色库 -->
      <div class="char-swap-ark-library" id="charSwapArkLibrary" style="margin-bottom:14px;">
        <div style="font-size:0.85rem; font-weight:600; margin-bottom:6px;">备选角色库（明日方舟 · Danbooru）</div>
        <div class="meta" id="charSwapArkStats" style="margin-bottom:4px;">加载中…</div>
        <div class="char-swap-ark-tabs" style="margin-bottom:4px;">
          <button type="button" class="char-swap-btn active" data-ark-gender="female">女干员</button>
          <button type="button" class="char-swap-btn" data-ark-gender="male">男干员</button>
        </div>
        <input id="charSwapArkSearch" class="char-swap-ark-search" type="search" placeholder="搜索角色名 / tag，如 斯卡蒂 / skadi" style="width:100%; margin-bottom:6px;" />
        <div id="charSwapArkList" class="char-swap-ark-list" style="max-height:160px; overflow:auto;"></div>
      </div>

      <!-- 自定义预设表单 -->
      <div class="char-swap-section" style="margin-bottom:14px;">
        <div style="font-size:0.85rem; font-weight:600; margin-bottom:6px;">高级添加角色预设（支持服饰替换、添加、移除）</div>
        <div class="char-swap-preset-form" style="display:flex; flex-direction:column; gap:4px;">
          <div style="display:flex; gap:6px;">
            <input id="presetLabel" type="text" placeholder="预设名，如 斯卡蒂 / 银灰" style="flex:1;" />
            <select id="presetGender" style="width:70px;"><option value="male">男</option><option value="female">女</option></select>
          </div>
          <label class="char-swap-inline-check" style="font-size:0.82rem;"><input id="presetOcMode" type="checkbox" /> 群友 OC（整段咒语模式）</label>
          <textarea id="presetCharCaption" class="char-swap-oc-caption" rows="2" placeholder="OC 整段咒语（仅 OC 模式）：支持 {{权重}} 等" style="font-size:0.82rem;"></textarea>
          <input id="presetIdentity" type="text" placeholder="身份 tag（逗号分隔）" />
          <input id="presetBody" type="text" placeholder="体型 tag" />
          <input id="presetAppearance" type="text" placeholder="外貌 tag" />
          <input id="presetClothing" type="text" placeholder="服饰替换（优先覆盖服装，如 arabian clothes, black skirt）" />
          <input id="presetExtra" type="text" placeholder="额外添加（附加元素，如 holding flower, elegant lighting）" />
          <input id="presetRemove" type="text" placeholder="移除标签（逗号分隔，如 shoes, background）" />
          <button type="button" class="btn outline" id="charSwapAddPreset" style="align-self:flex-start; margin-top:2px;">添加角色预设</button>
        </div>
      </div>

      <!-- 临时替换层 - 突出实用 -->
      <div class="char-swap-adhoc" style="margin-bottom:14px; padding:8px 10px; background:rgba(40,48,65,0.5); border:1px solid rgba(110,182,255,0.2); border-radius:6px;">
        <div style="font-size:0.82rem; font-weight:600; margin-bottom:4px; color:#9ec5ff;">本次角色替换临时层（优先级高，自动应用）</div>
        <input id="adhocClothing" type="text" placeholder="服饰替换（本次覆盖目标服装）" style="width:100%; margin:2px 0; font-size:0.82rem;" />
        <input id="adhocExtra" type="text" placeholder="额外添加（本次附加）" style="width:100%; margin:2px 0; font-size:0.82rem;" />
        <input id="adhocRemove" type="text" placeholder="移除标签（本次，逗号分隔）" style="width:100%; margin:2px 0; font-size:0.82rem;" />
        <div class="meta" style="font-size:0.7rem; margin-top:2px;">支持任何角色（库内或预设）。填好后直接在工作台/批量中使用替换。</div>
      </div>

      <!-- 画风预设 -->
      <div class="char-swap-style-preset-section" id="charSwapStylePresetSection">
        <div style="font-size:0.85rem; font-weight:600; margin-bottom:4px;">画风预设</div>
        <div class="meta" style="margin-bottom:4px; font-size:0.72rem;">点「画风替换」时会先清当前画风，再应用这里的内容。</div>
        <div id="charSwapStylePresetList" class="char-swap-style-preset-list"></div>
        <div class="char-swap-preset-form char-swap-style-preset-form" style="margin-top:6px; display:flex; flex-direction:column; gap:4px;">
          <input id="stylePresetLabel" type="text" placeholder="预设名，如 Granblue 画风" autocomplete="off" />
          <input id="stylePresetStyle" type="text" placeholder="画风串（留空=去掉画风）" autocomplete="off" />
          <div class="char-swap-style-preset-form-actions" style="display:flex; gap:6px;">
            <button type="button" class="btn outline" id="charSwapAddStylePreset">添加画风预设</button>
            <button type="button" class="btn outline" id="charSwapCancelStylePreset" style="display:none">取消编辑</button>
          </div>
        </div>
      </div>

      <div style="margin-top:10px; display:flex; gap:12px; font-size:0.75rem; opacity:0.75;">
        <span id="charSwapNaiStatus"></span>
        <span id="charSwapTagIndexStatus"></span>
      </div>`;
    host.appendChild(box);

    const statusEl = document.getElementById("charSwapNaiStatus");
    let editingStylePresetId = "";

    function resetStylePresetForm() {
      editingStylePresetId = "";
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };
      set("stylePresetLabel", "");
      set("stylePresetStyle", "");
      const addBtn = document.getElementById("charSwapAddStylePreset");
      const cancelBtn = document.getElementById("charSwapCancelStylePreset");
      if (addBtn) addBtn.textContent = "添加画风预设";
      if (cancelBtn) cancelBtn.style.display = "none";
    }

    async function renderStylePresetSettingsList() {
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
    window.renderStylePresetSettingsList = renderStylePresetSettingsList;

    async function loadCfgToForm() {
      const cfg = await loadPluginConfig();
      const set = (id, val) => { const el = document.getElementById(id); if (el) el.checked = !!val; };
      set("cfgPluginEnabled", cfg.plugin_enabled !== false);
      set("cfgSanitizeRacial", cfg.sanitize_racial !== false);
      set("cfgSanitizeGore", cfg.sanitize_gore !== false);
      set("cfgReplaceCreature", cfg.replace_creature_slots !== false);
      set("cfgForceFree", cfg.force_free !== false);
      set("cfgPreserveAction", cfg.preserve_action === true);
      set("cfgAutoSanitize", cfg.auto_sanitize_on_generate !== false);
      const profileEl = document.getElementById("cfgPromptProfile");
      if (profileEl) {
        const choices = cfg.prompt_profile_choices || [
          { id: "native", label: "Original NAI" },
          { id: "anima_faithful", label: "Anima V1 Faithful" },
          { id: "anima_epic", label: "Anima V2 Epic" },
        ];
        profileEl.innerHTML = "";
        choices.forEach((choice) => {
          const opt = document.createElement("option");
          opt.value = choice.id || "native";
          opt.textContent = choice.label || choice.id || "Original NAI";
          if (choice.description) opt.title = choice.description;
          profileEl.appendChild(opt);
        });
        profileEl.value = cfg.prompt_profile || "native";
      }
    }

    function providerLabel(provider) {
      const key = String(provider || "").toLowerCase();
      if (key === "xianyun") return "闲云";
      if (key === "novelai") return "NAI";
      return provider || "unknown";
    }

    function renderTokenSlots(data) {
      const listEl = document.getElementById("charSwapTokenSlots");
      if (!listEl) return;
      const tokens = Array.isArray(data && data.tokens) ? data.tokens : [];
      if (!tokens.length) {
        listEl.innerHTML = '<div class="meta">暂无 Token 槽位</div>';
        return;
      }
      listEl.innerHTML = "";
      tokens.forEach((slot, idx) => {
        const row = document.createElement("div");
        row.className = "char-swap-token-slot";
        row.style.cssText = "display:flex; align-items:center; justify-content:space-between; gap:8px; padding:6px 0; border-top:1px solid rgba(110,182,255,0.16);";
        const main = document.createElement("div");
        main.style.cssText = "min-width:0; flex:1;";
        const title = document.createElement("div");
        title.style.cssText = "font-size:0.82rem; color:#dbe7f5; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;";
        const enabled = slot.enabled !== false;
        title.textContent = `#${idx + 1} ${slot.label || providerLabel(slot.provider)} · ${providerLabel(slot.provider)} · ${slot.masked || ""}`;
        const meta = document.createElement("div");
        meta.className = "meta";
        meta.style.fontSize = "0.7rem";
        const disabledText = enabled ? "启用" : `停用${slot.disabled_reason ? `：${slot.disabled_reason}` : ""}`;
        meta.textContent = `${disabledText}${slot.updated_at ? ` · 更新 ${slot.updated_at}` : ""}`;
        main.appendChild(title);
        main.appendChild(meta);
        const actions = document.createElement("div");
        actions.style.cssText = "display:flex; gap:6px; flex-shrink:0;";
        const checkBtn = document.createElement("button");
        checkBtn.type = "button";
        checkBtn.className = "char-swap-btn";
        checkBtn.textContent = "检查";
        checkBtn.addEventListener("click", async () => {
          try {
            const res = await api("/api/nai/token/check", {
              method: "POST",
              body: JSON.stringify({ token_id: slot.id, remove_bad: true }),
            });
            const item = (res.results || [])[0] || {};
            statusEl.textContent = item.message || (item.ok ? "Token 可用" : "Token 不可用");
            await refreshNaiStatus();
          } catch (e) {
            statusEl.textContent = e.message;
          }
        });
        const delBtn = document.createElement("button");
        delBtn.type = "button";
        delBtn.className = "char-swap-btn";
        delBtn.textContent = "删除";
        delBtn.addEventListener("click", async () => {
          if (!window.confirm(`删除 Token 槽位「${slot.label || slot.masked || slot.id}」？`)) return;
          try {
            await api(`/api/nai/token/${encodeURIComponent(slot.id)}`, { method: "DELETE" });
            statusEl.textContent = "Token 槽位已删除";
            await refreshNaiStatus();
          } catch (e) {
            statusEl.textContent = e.message;
          }
        });
        actions.appendChild(checkBtn);
        actions.appendChild(delBtn);
        row.appendChild(main);
        row.appendChild(actions);
        listEl.appendChild(row);
      });
    }

    async function refreshNaiStatus() {
      try {
        const s = await api("/api/nai/status");
        renderTokenSlots(s);
        if (!s.has_token) { statusEl.textContent = "No NAI token configured"; return; }
        const slotN = Number(s.concurrency || s.enabled_count || 0) || 0;
        const activeN = Number((s.queue && s.queue.active_count) || 0) || 0;
        const providerText = s.providers
          ? Object.entries(s.providers).map(([k, v]) => `${k}:${v}`).join(" / ")
          : "";
        const tokenText = slotN ? `Token ${slotN} slot(s)${providerText ? ` · ${providerText}` : ""}` : "Token 0 slots";
        const activeText = activeN ? ` · active ${activeN}` : "";
        statusEl.textContent = s.ok
          ? `Opus ${s.is_opus ? "yes" : "no"} · ${tokenText}${activeText} · Anlas ${s.anlas_total ?? "?"} · ${(s.queue && s.queue.status) || "idle"}`
          : (s.message || "");
      } catch (e) {
        statusEl.textContent = e.message;
      }
    }

    async function savePluginSettings() {
      const body = {
        plugin_enabled: document.getElementById("cfgPluginEnabled").checked,
        sanitize_racial: document.getElementById("cfgSanitizeRacial").checked,
        sanitize_gore: document.getElementById("cfgSanitizeGore").checked,
        replace_creature_slots: document.getElementById("cfgReplaceCreature").checked,
        force_free: document.getElementById("cfgForceFree").checked,
        preserve_action: document.getElementById("cfgPreserveAction").checked,
        auto_sanitize_on_generate: document.getElementById("cfgAutoSanitize").checked,
        prompt_profile: (document.getElementById("cfgPromptProfile") || {}).value || "native",
      };
      await api("/api/plugin/char-swap/config", { method: "POST", body: JSON.stringify(body) });
      state.pluginConfig = null;
      await loadPluginConfig();
    }

    document.getElementById("charSwapSaveAll").addEventListener("click", async () => {
      try {
        await savePluginSettings();
        statusEl.textContent = "配置已保存";
        await refreshNaiStatus();
      } catch (e) {
        statusEl.textContent = e.message;
      }
    });

    document.getElementById("charSwapReplaceTokens").addEventListener("click", async () => {
      const token = (document.getElementById("charSwapToken") || {}).value || "";
      if (!token.trim()) { statusEl.textContent = "请先填写 token"; return; }
      if (!window.confirm("覆盖保存会替换整个 Token 池，继续？")) return;
      try {
        await savePluginSettings();
        await api("/api/nai/token", { method: "POST", body: JSON.stringify({ token: token.trim() }) });
        statusEl.textContent = "Token 池已覆盖保存";
        await refreshNaiStatus();
      } catch (e) {
        statusEl.textContent = e.message;
      }
    });

    document.getElementById("charSwapAddToken").addEventListener("click", async () => {
      const tokenText = (document.getElementById("charSwapToken") || {}).value || "";
      const lines = tokenText.split(/\r?\n/).map((x) => x.trim()).filter(Boolean);
      if (!lines.length) { statusEl.textContent = "请先填写 token"; return; }
      try {
        await savePluginSettings();
        let added = 0;
        for (const token of lines) {
          await api("/api/nai/token/add", {
            method: "POST",
            body: JSON.stringify({ token }),
          });
          added += 1;
        }
        document.getElementById("charSwapToken").value = "";
        statusEl.textContent = `已加入 ${added} 个 Token 槽位`;
        await refreshNaiStatus();
      } catch (e) {
        statusEl.textContent = e.message;
        await refreshNaiStatus();
      }
    });

    document.getElementById("charSwapCheckTokens").addEventListener("click", async () => {
      try {
        const res = await api("/api/nai/token/check", {
          method: "POST",
          body: JSON.stringify({ remove_bad: true }),
        });
        const removed = (res.results || []).filter((x) => x.removed).length;
        const ok = (res.results || []).filter((x) => x.ok).length;
        statusEl.textContent = `检查完成：可用 ${ok}，已清理 ${removed}`;
        await refreshNaiStatus();
      } catch (e) {
        statusEl.textContent = e.message;
      }
    });

    let arkGender = "female";
    let arkSearchTimer = 0;

    async function renderArkLibrary() {
      const listEl = document.getElementById("charSwapArkList");
      const statsEl = document.getElementById("charSwapArkStats");
      const q = (document.getElementById("charSwapArkSearch") || {}).value || "";
      if (!listEl) return;
      listEl.textContent = "加载中…";
      try {
        const res = await api(`/api/plugin/char-swap/ark-library?gender=${encodeURIComponent(arkGender)}&q=${encodeURIComponent(q)}&limit=60`);
        const items = res.items || [];
        if (statsEl) {
          statsEl.textContent = `女 ${res.female_count || 0} · 男 ${res.male_count || 0} · 当前 ${items.length} 条`;
        }
        if (!items.length) {
          listEl.textContent = "无匹配角色";
          return;
        }
        listEl.innerHTML = "";
        items.forEach((item) => {
          const row = document.createElement("div");
          row.className = "char-swap-ark-item";
          const left = document.createElement("div");
          const title = document.createElement("div");
          title.textContent = item.label || item.tag || "";
          const detail = document.createElement("div");
          detail.className = "meta";
          detail.textContent = (item.identity || []).slice(0, 2).join(", ");
          left.appendChild(title);
          left.appendChild(detail);
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "char-swap-btn";
          btn.textContent = "加入预设";
          btn.addEventListener("click", async () => {
            try {
              await api("/api/plugin/char-swap/presets", {
                method: "POST",
                body: JSON.stringify({
                  label: item.label || item.tag,
                  gender: item.gender || arkGender,
                  identity: item.identity || [],
                  body: item.body || [],
                  appearance: item.appearance || [],
                }),
              });
              statusEl.textContent = `已加入预设：${item.label || item.tag}`;
            } catch (e) {
              statusEl.textContent = e.message;
            }
          });
          row.appendChild(left);
          row.appendChild(btn);
          listEl.appendChild(row);
        });
      } catch (e) {
        listEl.textContent = `加载失败: ${e.message}`;
      }
    }

    document.querySelectorAll("[data-ark-gender]").forEach((btn) => {
      btn.addEventListener("click", () => {
        arkGender = btn.getAttribute("data-ark-gender") || "female";
        document.querySelectorAll("[data-ark-gender]").forEach((el) => {
          el.classList.toggle("active", el.getAttribute("data-ark-gender") === arkGender);
        });
        renderArkLibrary();
      });
    });
    const arkSearchInput = document.getElementById("charSwapArkSearch");
    if (arkSearchInput) {
      arkSearchInput.addEventListener("input", () => {
        clearTimeout(arkSearchTimer);
        arkSearchTimer = setTimeout(renderArkLibrary, 220);
      });
    }
    renderArkLibrary();

    const presetOcModeEl = document.getElementById("presetOcMode");
    const presetCharCaptionEl = document.getElementById("presetCharCaption");
    const togglePresetOcFields = () => {
      const oc = !!(presetOcModeEl && presetOcModeEl.checked);
      if (presetCharCaptionEl) presetCharCaptionEl.style.display = oc ? "block" : "none";
    };
    if (presetOcModeEl) {
      presetOcModeEl.addEventListener("change", togglePresetOcFields);
      togglePresetOcFields();
    }

    document.getElementById("charSwapAddPreset").addEventListener("click", async () => {
      const split = (s) => String(s || "").split(/[,，]/).map((x) => x.trim()).filter(Boolean);
      const label = document.getElementById("presetLabel").value.trim();
      if (!label) { alert("请填写预设名"); return; }
      const ocMode = !!(presetOcModeEl && presetOcModeEl.checked);
      const charCaption = presetCharCaptionEl ? String(presetCharCaptionEl.value || "").trim() : "";
      if (ocMode && !charCaption) { alert("群友 OC 请填写整段角色咒语"); return; }
      try {
        const body = {
          label,
          gender: document.getElementById("presetGender").value,
          identity: split(document.getElementById("presetIdentity").value),
          body: split(document.getElementById("presetBody").value),
          appearance: split(document.getElementById("presetAppearance").value),
          clothing: (document.getElementById("presetClothing") || {}).value || "",
          extra: (document.getElementById("presetExtra") || {}).value || "",
          remove: split((document.getElementById("presetRemove") || {}).value),
        };
        if (ocMode || charCaption) {
          body.kind = "oc";
          body.char_caption = charCaption;
        }
        await api("/api/plugin/char-swap/presets", {
          method: "POST",
          body: JSON.stringify(body),
        });
        statusEl.textContent = `预设「${label}」已添加`;
      } catch (e) {
        statusEl.textContent = e.message;
      }
    });

    const addStylePresetBtn = document.getElementById("charSwapAddStylePreset");
    if (addStylePresetBtn) {
      addStylePresetBtn.addEventListener("click", async () => {
        const label = (document.getElementById("stylePresetLabel") || {}).value || "";
        const style = (document.getElementById("stylePresetStyle") || {}).value || "";
        if (!String(label).trim()) { window.alert("请填写预设名"); return; }
        const body = {
          label: String(label).trim(),
          style: String(style),
        };
        try {
          const res = await upsertStylePreset(
            editingStylePresetId ? { ...body, id: editingStylePresetId } : body,
            editingStylePresetId ? "PUT" : "POST",
          );
          if (statusEl) {
            statusEl.textContent = res.message || (
              editingStylePresetId
                ? `画风预设「${body.label}」已更新`
                : `画风预设「${body.label}」已添加`
            );
          }
          resetStylePresetForm();
          await refreshStylePresetUi();
        } catch (e) {
          const text = e.message || "保存失败";
          if (statusEl) statusEl.textContent = text;
          window.alert(`画风预设保存失败：${text}`);
        }
      });
    }

    const cancelStylePresetBtn = document.getElementById("charSwapCancelStylePreset");
    if (cancelStylePresetBtn) {
      cancelStylePresetBtn.addEventListener("click", () => {
        resetStylePresetForm();
      });
    }

    async function refreshTagIndexStatus() {
      const el = document.getElementById("charSwapTagIndexStatus");
      if (!el) return;
      try {
        const res = await api("/api/plugin/char-swap/tag-index");
        const s = res.stats || {};
        const st = res.style_stats || {};
        const styleText = st.exists
          ? ` · 画风 ${st.artists ?? 0} 画师/${st.styles ?? 0} 标签`
          : " · 画风库未下载";
        el.textContent = s.exists
          ? `本地角色库：${s.characters ?? 0} 角色 · ${s.appearance ?? 0} 特征${styleText}（离线）`
          : "本地角色库未构建，请运行 scripts/build_char_tag_db.py";
      } catch (e) {
        el.textContent = "";
      }
    }

    loadCfgToForm();
    refreshNaiStatus();
    refreshTagIndexStatus();
    renderStylePresetSettingsList();
  }

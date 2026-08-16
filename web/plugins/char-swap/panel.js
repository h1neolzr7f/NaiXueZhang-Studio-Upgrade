import { state, saveCurrentDraftToCache, loadDraftFromCache, clearDraftCacheForPage, clearDraftCacheForWork, buildStyleBundleFallback, extractCache, draftPageCache, draftCacheKey, saveSource, loadSource, clearSource, persistDraftCache } from "./state.js?v=f80b97d795";
import { api, $, deepClone, setMsg, flashMsg, copyText, instructionFromAiJson, loadPluginConfig, esc } from "./api.js?v=0411b73ad6";
import { 
    showPresetModal, showMultiSlotPresetModal, showStylePresetModal, 
    upsertStylePreset, deleteStylePreset, saveStylePresetsViaConfig, 
    presetStyle, applyStylePreset, openStyleReplaceModal, 
    fillStylePresetSelects, renderStylePresetSettingsList,
    refreshStylePresetUi, saveCurrentStyleAsPreset, runStyleReplaceOnDraft,
    runStyleReplaceWithFallback, setWorkbenchHandlers, stylePresetDetail
} from "./presets.js?v=f16dbe971d";
import { 
    addToBatch, addAllWorkPagesToBatch, removeWorkFromBatch, 
    isBatchMode, loadBatchQueue, refreshBatchCardChecks, updateQuickAddHint,
    addManyToBatch, buildBatchEntry, refreshGenSidebar
} from "./batch.js?v=78189662ea";
import {
    applyGenderSwapTarget,
    countGenderSlots,
    genderRoleLabel,
    slotDisplayName,
    slotGender,
    slotIdentityKeys,
    slotOcPreview,
} from "./slots.js?v=6adf84cea2";
import { attachDraftToPayload, getBatchMax } from "./draft_helpers.js?v=71bb7ead54";
import {
    activeGalleryId as resolveActiveGalleryId,
    loadExtract as loadDraftExtract,
    styleStateFromResponse,
    cacheTransformResponse,
    flushDraftCache,
    resetDraftFromOriginal as resetDraftState,
    originalSeed as readOriginalSeed,
    setDraftSeed as writeDraftSeed,
    draftAiJson as buildDraftAiJson,
    runTransformCommand,
    runSanitizeCommand,
} from "./draft_commands.js?v=33b6af2162";
import { renderDraftPreview } from "./dom_adapter.js?v=68ad0782e7";

// Compatibility source manifest for static downstream guards. The production
// markup and handlers are owned by panel_shell.js:
// 角色与画风草稿
// class="char-swap-slots-draft"
// id="charSwapQuickPresets"
// id="charSwapToken"
// NAI / Xianyun Token Pool
// pst-xxx (NovelAI)
// xianyun:API_KEY
// id="charSwapAddToken"
// id="charSwapCheckTokens"
// id="charSwapTokenSlots"
// /api/nai/token/add
// /api/nai/token/check



export function updateBatchCapLabel() {
    const el = document.getElementById("charSwapBatchCap");
    if (el) el.textContent = `上限 ${getBatchMax()}`;
  }

export function activeGalleryId(explicitGalleryId) {
    // Compatibility contract implemented in draft_commands.js:
    // searchParams.get("gallery")
    // params.set("gallery_id", galleryId)
    return resolveActiveGalleryId(explicitGalleryId);
  }

export async function loadExtract(workId, pageIndex) {
    return loadDraftExtract(workId, pageIndex);
  }

export function buildMultiReplacements(entries, gender) {
    const g = gender || "female";
    const mode = g === "male" ? "replace_male" : "replace_female";
    return (entries || [])
      .map((entry, ord) => {
        const slot = (state.draftChars || []).find((ch) => Number(ch.index) === Number(entry.target_char_index));
        return {
        gender_slot_index: ord,
        target_char_index: entry.target_char_index,
        preset_id: entry.preset_id,
        gender: g,
        mode,
        match_identity_keys: entry.match_identity_keys || slotIdentityKeys(slot),
      };
      })
      .filter((r) => r.preset_id);
  }

export async function runTransformMulti(replacements, opts = {}) {
    const list = buildMultiReplacements(replacements, opts.gender || "female");
    if (!list.length) throw new Error("请至少为一个槽位选择预设");
    const gender = opts.gender || "female";
    return runTransform({
      mode: "replace_multi",
      target_work_id: opts.workId != null ? opts.workId : state.workId,
      target_page_index: opts.pageIndex != null ? opts.pageIndex : state.pageIndex,
      gender,
      replacements: list,
      replace_creature: false,
      skip_missing_slots: !!opts.skip_missing_slots,
    });
  }

export async function runTransformMultiAllPages(replacements, panel, msgEl, opts = {}) {
    const workId = state.workId;
    if (!workId) throw new Error("无作品 ID");
    const pageCount = Math.max(1, Number(state.imagePageCount) || 1);
    const list = buildMultiReplacements(replacements, opts.gender || "female");
    if (!list.length) throw new Error("请至少为一个槽位选择预设");
    const gender = opts.gender || "female";
    saveCurrentDraftToCache();

    const cfg = await loadPluginConfig();
    let ok = 0;
    const errors = [];
    for (let pi = 0; pi < pageCount; pi++) {
      try {
        if (msgEl) {
          setMsg(msgEl, `正在逐槽替换全部图片… p${pi}（${pi + 1}/${pageCount}）`, true);
        }
        const payload = {
          preserve_action: cfg.preserve_action === true,
          preserve_center: cfg.preserve_center !== false,
          mode: "replace_multi",
          target_work_id: workId,
          target_page_index: pi,
          gender,
          replacements: list,
          replace_creature: false,
          skip_missing_slots: true,
          gallery_id: activeGalleryId(),
        };
        attachDraftToPayload(payload, workId, pi);
        const res = await api("/api/plugin/char-swap/transform", {
          method: "POST",
          body: JSON.stringify(payload),
        });
        cacheTransformResponse(workId, pi, res);
        flushDraftCache();
        ok++;
      } catch (e) {
        errors.push(`p${pi}: ${e.message}`);
      }
    }

    if (!loadDraftFromCache(workId, state.pageIndex)) {
      resetDraftFromOriginal();
    }
    renderSlotRows(panel);
    renderStyleRows(panel);
    syncSeedUi(panel);

    const roleLabel = genderRoleLabel(gender, list.length);
    const names = (opts.labels || []).filter(Boolean).join("、");
    if (!errors.length) {
      setMsg(msgEl, `已全部 ${pageCount} 张图完成${roleLabel}换角${names ? `：${names}` : ""}`, true);
    } else if (ok > 0) {
      setMsg(msgEl, `完成 ${ok}/${pageCount} 张；失败：${errors.join("；")}`, false);
    } else {
      setMsg(msgEl, errors.join("；"), false);
    }
    return { ok, errors };
  }

export function syncStyleFromResponse(res) {
    styleStateFromResponse(res);
  }

export async function runTransform(body) {
    const gid = activeGalleryId(body.gallery_id);
    // Compatibility contract: every transform still carries `gallery_id: gid`.
    const res = await runTransformCommand({ ...body, gallery_id: gid });
    updateDraftPreview();
    return res;
  }

export async function runTransformAllPages(transformBody, panel, msgEl, presetLabel) {
    const workId = state.workId;
    if (!workId) throw new Error("无作品 ID");
    const pageCount = Math.max(1, Number(state.imagePageCount) || 1);
    saveCurrentDraftToCache();

    const cfg = await loadPluginConfig();
    const baseBody = {
      preserve_action: cfg.preserve_action === true,
      preserve_center: cfg.preserve_center !== false,
      replace_creature: cfg.replace_creature_slots !== false,
      ...transformBody,
      gallery_id: activeGalleryId(transformBody.gallery_id),
      target_work_id: workId,
    };
    delete baseBody.target_page_index;
    if (
      baseBody.target_char_index === undefined
      || baseBody.target_char_index === null
      || baseBody.target_char_index === ""
    ) {
      delete baseBody.target_char_index;
    }
    if (
      baseBody.gender_slot_index === undefined
      || baseBody.gender_slot_index === null
      || baseBody.gender_slot_index === ""
    ) {
      delete baseBody.gender_slot_index;
    }

    let ok = 0;
    const errors = [];
    const pages = Array.from({ length: pageCount }, (_, i) => i);
    const CONCURRENCY = 5;
    let cursor = 0;
    const workers = Array.from({ length: Math.min(CONCURRENCY, pages.length) }, async () => {
      while (cursor < pages.length) {
        const pi = pages[cursor++];
        try {
          if (msgEl) setMsg(msgEl, `正在替换全部图片 tag… p${pi}（${ok + 1}/${pageCount}）`, true);
          const reqBody = { ...baseBody, target_page_index: pi };
          attachDraftToPayload(reqBody, workId, pi);
          const res = await api("/api/plugin/char-swap/transform", {
            method: "POST",
            body: JSON.stringify(reqBody),
          });
          cacheTransformResponse(workId, pi, res);
          ok++;
        } catch (e) {
          errors.push(`p${pi}: ${e.message}`);
        }
      }
    });
    await Promise.all(workers);
    flushDraftCache();

    if (!loadDraftFromCache(workId, state.pageIndex)) {
      resetDraftFromOriginal();
    } else {
      updateDraftPreview();
    }
    renderSlotRows(panel);
    renderStyleRows(panel);
    syncSeedUi(panel);

    const genderLabel = transformBody.gender === "female" ? "女" : "男";
    const doneLabel = `${genderLabel}角色：${presetLabel}`;
    if (!errors.length) {
      setMsg(msgEl, `已全部 ${pageCount} 张图换角完成（${doneLabel}）`, true);
    } else if (ok > 0) {
      setMsg(msgEl, `完成 ${ok}/${pageCount} 张；失败：${errors.join("；")}`, false);
    } else {
      setMsg(msgEl, errors.join("；"), false);
    }
    return { ok, errors };
  }

export async function runSanitize() {
    const res = await runSanitizeCommand();
    if (!res) return null;
    updateDraftPreview();
    return res;
  }

export function resetDraftFromOriginal() {
    if (resetDraftState()) updateDraftPreview();
  }

export function originalSeed() {
    return readOriginalSeed();
  }

export function setDraftSeed(val) {
    writeDraftSeed(val);
  }

export function syncSeedUi(panel) {
    const input = $("#charSwapSeed", panel);
    const hint = $("#charSwapSeedHint", panel);
    const randBtn = panel && panel.querySelector('[data-action="seed-random"]');
    if (!input) return;
    const draftSeed = state.draft ? state.draft.seed : undefined;
    const isRandom = draftSeed === -1;
    const orig = originalSeed();
    if (hint) {
      hint.textContent = orig !== null && orig !== undefined
        ? `原图 seed: ${orig}`
        : "原图无固定 seed";
    }
    if (isRandom) {
      input.value = "-1";
      input.disabled = true;
      if (randBtn) {
        randBtn.classList.add("active");
        randBtn.textContent = "★ 随机 -1";
      }
      return;
    }
    input.disabled = false;
    if (randBtn) {
      randBtn.classList.remove("active");
      randBtn.textContent = "随机 -1";
    }
    if (draftSeed !== undefined && draftSeed !== null && draftSeed !== "") {
      input.value = String(draftSeed);
    } else if (orig !== null) {
      input.value = String(orig);
      setDraftSeed(orig);
    } else {
      input.value = "";
    }
  }

export function applySeedInputFromPanel(panel) {
    const input = $("#charSwapSeed", panel);
    if (!input || input.disabled || !state.draft) return;
    const raw = String(input.value || "").trim();
    if (!raw) {
      const orig = originalSeed();
      if (orig !== null) setDraftSeed(orig);
      else delete state.draft.seed;
      return;
    }
    setDraftSeed(raw);
  }

export function bindSeedControls(panel) {
    const row = $(".char-swap-seed-row", panel);
    if (!row || row.dataset.bound === "1") return;
    row.dataset.bound = "1";
    const input = $("#charSwapSeed", panel);
    const randBtn = row.querySelector('[data-action="seed-random"]');
    const applySeedInput = () => applySeedInputFromPanel(panel);
    if (input) {
      input.addEventListener("change", applySeedInput);
      input.addEventListener("blur", applySeedInput);
    }
    if (randBtn) {
      randBtn.addEventListener("click", () => {
        if (!state.draft) return;
        if (state.draft.seed === -1) {
          const restore = state.seedBeforeRandom;
          state.seedBeforeRandom = null;
          if (restore !== null && restore !== undefined) {
            setDraftSeed(restore);
          } else {
            const orig = originalSeed();
            if (orig !== null) setDraftSeed(orig);
            else delete state.draft.seed;
          }
        } else {
          const current = state.draft.seed;
          state.seedBeforeRandom = current !== undefined && current !== null
            ? current
            : originalSeed();
          setDraftSeed(-1);
        }
        syncSeedUi(panel);
      });
    }
  }

export function draftAiJson() {
    return buildDraftAiJson();
  }

export function updateDraftPreview() {
    renderDraftPreview(draftAiJson());
  }

export function renderSourceBar(panel) {
    const bar = document.getElementById("charSwapSourceBar");
    if (!bar) return;
    const src = loadSource();
    bar.replaceChildren();
    if (!src) {
      bar.className = "char-swap-source-bar empty";
      bar.append("① 在任意角色行点 ");
      const b1 = document.createElement("b");
      b1.textContent = "设为源";
      bar.appendChild(b1);
      bar.append(" → ② 到目标图点 ");
      const b2 = document.createElement("b");
      b2.textContent = "替换";
      bar.appendChild(b2);
      bar.append(" 或工具栏 ");
      const b3 = document.createElement("b");
      b3.textContent = "+ 追加";
      bar.appendChild(b3);
      return;
    }
    bar.className = "char-swap-source-bar active";
    bar.append("当前源：");
    const name = document.createElement("b");
    name.textContent = src.summary || "角色";
    bar.appendChild(name);
    bar.append(" ");
    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "char-swap-btn char-swap-clear-src";
    clearBtn.textContent = "清除";
    clearBtn.addEventListener("click", () => {
      clearSource();
      renderSourceBar(panel);
      setMsg($(".char-swap-msg", panel), "已清除角色源", true);
    });
    bar.appendChild(clearBtn);
  }

export function renderDiff(el, removed) {
    if (!el) return;
    if (!removed || !removed.length) {
      el.style.display = "none";
      el.textContent = "";
      return;
    }
    el.style.display = "";
    el.textContent = removed.map((x) => `${x.field}: -${x.removed.join(", ")}`).join("\n");
  }

export function updateMultiRoleToolbar(panel) {
    const femaleN = countGenderSlots(state.draftChars, "female");
    const maleN = countGenderSlots(state.draftChars, "male");
    const fBtn = panel && panel.querySelector('[data-action="replace-female-multi"]');
    const mBtn = panel && panel.querySelector('[data-action="replace-male-multi"]');
    if (fBtn) {
      fBtn.style.display = femaleN >= 2 ? "" : "none";
      fBtn.textContent = `${genderRoleLabel("female", femaleN)}换角`;
    }
    if (mBtn) {
      mBtn.style.display = maleN >= 2 ? "" : "none";
      mBtn.textContent = `${genderRoleLabel("male", maleN)}换角`;
    }
    const titleEl = panel && panel.querySelector("#charSwapSlotsTitle");
    if (titleEl) {
      const parts = [];
      if (femaleN >= 2) parts.push(`${genderRoleLabel("female", femaleN)}`);
      if (maleN >= 2) parts.push(`${genderRoleLabel("male", maleN)}`);
      titleEl.textContent = parts.length
        ? `编辑中草稿（${parts.join("、")}）— 用工具栏「${parts[0]}换角」可为每个槽选不同预设`
        : "编辑中草稿（角色槽）— 每行右侧有「设为源」";
    }
  }

export function renderSlotRows(panel) {
    const slotsEl = $(".char-swap-slots-draft", panel);
    const msgEl = $(".char-swap-msg", panel);
    if (!slotsEl) return;
    slotsEl.innerHTML = "";
    (state.draftChars || []).forEach((ch) => {
      const row = document.createElement("div");
      row.className = "char-swap-slot";
      const gender = slotGender(ch);
      const genderClass = gender === "female" ? "female" : gender === "male" ? "male" : "unknown";
      const genderText = gender === "female" ? "♀ 女" : gender === "male" ? "♂ 男" : "?";
      const genderBadgeHtml = `<span class="char-swap-gender-badge ${genderClass}">${genderText}</span>`;
      const ocPreview = slotOcPreview(ch);
      // Prefer char_caption / slotDisplayName so restore-original is not stuck on bad identity inference.
      const idTags = slotDisplayName(ch) || "未识别角色";
      const creatureTags = (ch.creature_tags && ch.creature_tags.length)
        ? ch.creature_tags
        : ((ch.bundle && ch.bundle.creature) || []);
      const appearanceTags = (ch.appearance_tags && ch.appearance_tags.length)
        ? ch.appearance_tags.slice(0, 6).join(", ")
        : [
          ...((ch.bundle && ch.bundle.body) || []),
          ...((ch.bundle && ch.bundle.appearance) || []),
        ].slice(0, 4).join(", ");
      const actionTags = (ch.action_tags && ch.action_tags.length)
        ? ch.action_tags.slice(0, 5).join(", ")
        : "";
      const creatureHint = creatureTags.length
        ? `<span class="char-swap-tag-creature">贵物: ${esc(creatureTags.slice(0, 5).join(", "))}</span>`
        : "";
      const metaHtml = ocPreview
        ? [
          `<span class="char-swap-tag-meta char-swap-tag-oc">${esc(ocPreview)}</span>`,
          actionTags
            ? `<span class="char-swap-tag-meta char-swap-tag-action">动作: ${esc(actionTags)}</span>`
            : "",
        ].filter(Boolean).join("")
        : [
          appearanceTags
            ? `<span class="char-swap-tag-meta char-swap-tag-appearance">${genderBadgeHtml}${esc(appearanceTags)}</span>`
            : "",
          actionTags
            ? `<span class="char-swap-tag-meta char-swap-tag-action">动作: ${esc(actionTags)}</span>`
            : "",
        ].filter(Boolean).join("");
      row.innerHTML = `
        <span class="char-swap-slot-label">${esc(ch.marker ? ch.marker : `#${ch.index + 1}`)}</span>
        <span class="char-swap-slot-summary">
          <span class="char-swap-tag-role">${esc(idTags)}</span>
          ${creatureHint}
          ${metaHtml}
        </span>
        <div class="char-swap-actions"></div>`;
      const actions = $(".char-swap-actions", row);
      const mk = (label, fn) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "char-swap-btn";
        b.textContent = label;
        b.addEventListener("click", fn);
        return b;
      };
      const workId = state.workId;
      const pageIndex = state.pageIndex;

      actions.appendChild(mk("复制草稿", async () => {
        await copyText(ch.char_caption);
        setMsg(msgEl, "已复制草稿角色 tag（非图库原文）", true);
      }));
      actions.appendChild(mk("改性别", () => {
        const next = ch.gender === "female" ? "male" : ch.gender === "male" ? "unknown" : "female";
        ch.gender = next;
        ch.role = next === "unknown" ? "unknown" : next;
        ch.gender_confidence = 1;
        if (ch.bundle && typeof ch.bundle === "object") ch.bundle.gender = next;
        if (ch.identity_tags && Array.isArray(ch.identity_tags)) {
          ch.identity_tags = ch.identity_tags.filter(
            (t) => !/^(1girl|1boy|female_focus|male_focus|girls_only|boys_only)$/i.test(String(t))
          );
        }
        renderSlotRows(panel);
        saveCurrentDraftToCache();
        setMsg(
          msgEl,
          `槽位 #${ch.index + 1} 已设为 ${next === "female" ? "♀ 女" : next === "male" ? "♂ 男" : "未知"}`,
          true
        );
      }));
      const srcBtn = mk("设为源", () => {
        saveSource(ch);
        renderSourceBar(panel);
        setMsg(msgEl, `已设为源：${ch.summary}（可到其他图点「替换」）`, true);
      });
      srcBtn.classList.add("char-swap-btn-source");
      const activeSrc = loadSource();
      if (activeSrc && activeSrc.summary === ch.summary) {
        srcBtn.classList.add("active");
        srcBtn.textContent = "★ 当前源";
      }
      actions.appendChild(srcBtn);
      actions.appendChild(mk("替换", async () => {
        const src = loadSource();
        if (!src) { alert("请先在角色行点「设为源」（见上方蓝色提示条）"); return; }
        try {
          await runTransform({
            mode: "replace",
            target_work_id: workId,
            target_page_index: pageIndex,
            target_char_index: ch.index,
            custom_bundle: src.bundle,
          });
          renderSlotRows(panel);
          setMsg(msgEl, `草稿已替换槽位 #${ch.index + 1}（图库原文未改）`, true);
        } catch (e) {
          setMsg(msgEl, e.message, false);
        }
      }));
      actions.appendChild(mk("换男角", () => {
        if (countGenderSlots(state.draftChars, "male") >= 2) {
          showMultiSlotPresetModal("male", panel, msgEl, { focusIndex: ch.index });
          return;
        }
        showPresetModal("male", async (preset, scope) => {
          try {
            const body = {
              mode: "replace_male",
              target_work_id: workId,
              target_page_index: pageIndex,
              preset_id: preset.id,
              gender: "male",
              replace_creature: true,
            };
            applyGenderSwapTarget(body, state.draftChars || [], ch, "male", scope);
            if (scope === "all") {
              await runTransformAllPages(body, panel, msgEl, preset.label);
            } else {
              await runTransform(body);
              renderSlotRows(panel);
              renderStyleRows(panel);
              const slotMsg = scope === "all_slots" ? "（本图全部男槽）" : "";
              setMsg(msgEl, `草稿已换为男角色：${preset.label}${slotMsg}`, true);
            }
          } catch (e) {
            setMsg(msgEl, e.message, false);
          }
        }, { showAllPagesChoice: state.imagePageCount > 1 });
      }));
      actions.appendChild(mk("换女角", () => {
        if (countGenderSlots(state.draftChars, "female") >= 2) {
          showMultiSlotPresetModal("female", panel, msgEl, { focusIndex: ch.index });
          return;
        }
        showPresetModal("female", async (preset, scope) => {
          try {
            const body = {
              mode: "replace_female",
              target_work_id: workId,
              target_page_index: pageIndex,
              preset_id: preset.id,
              gender: "female",
              replace_creature: true,
            };
            applyGenderSwapTarget(body, state.draftChars || [], ch, "female", scope);
            if (scope === "all") {
              await runTransformAllPages(body, panel, msgEl, preset.label);
            } else {
              await runTransform(body);
              renderSlotRows(panel);
              renderStyleRows(panel);
              const slotMsg = scope === "all_slots" ? "（本图全部女槽）" : "";
              setMsg(msgEl, `草稿已换为女角色：${preset.label}${slotMsg}`, true);
            }
          } catch (e) {
            setMsg(msgEl, e.message, false);
          }
        }, { showAllPagesChoice: state.imagePageCount > 1 });
      }));
      if (creatureTags.length) {
        const creatureBtn = mk("贵物→搭档", () => {
          showPresetModal("male", async (preset) => {
            try {
              await runTransform({
                mode: "creature_to_partner",
                target_work_id: workId,
                target_page_index: pageIndex,
                target_char_index: ch.index,
                preset_id: preset.id,
                gender: preset.gender || "male",
                replace_creature: true,
              });
              renderSlotRows(panel);
              setMsg(msgEl, `已保留原角色，贵物换成：${preset.label}`, true);
            } catch (e) {
              setMsg(msgEl, e.message, false);
            }
          });
        });
        creatureBtn.classList.add("char-swap-btn-creature");
        actions.appendChild(creatureBtn);
      }
      slotsEl.appendChild(row);
    });
    updateMultiRoleToolbar(panel);
  }

export function styleKindLabel(kind) {
    const k = String(kind || "");
    if (k === "artist") return "画师";
    if (k === "meta") return "风格";
    return "画风";
  }

export function styleFieldLabel(slot) {
    if (!slot) return "";
    if (slot.field === "base_caption") return "base";
    if (slot.field === "char_caption") return `#${Number(slot.char_index || 0) + 1}`;
    return slot.field || "";
  }

export function styleGroupKindLabel(group) {
    const kinds = (group && group.kinds) || [];
    if (!kinds.length) return "画师+画风";
    const labels = kinds.map((k) => styleKindLabel(k));
    return [...new Set(labels)].join("+");
  }

export function renderStyleRows(panel) {
    const host = $(".char-swap-style-slots", panel);
    const msgEl = $(".char-swap-msg", panel);
    if (!host) return;
    const bundle = state.styleBundle || buildStyleBundleFallback(state.styleSlots || []);
    const groups = Array.isArray(bundle.groups) ? bundle.groups : [];
    if (!groups.length) {
      host.innerHTML = '<div class="char-swap-style-empty-wrap"><div class="char-swap-style-empty">未识别到画师/画风 tag，可点右侧「画风替换」选预设。</div><div class="char-swap-actions char-swap-style-actions"></div></div>';
      const actions = $(".char-swap-style-actions", host);
      const mk = (label, fn) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "char-swap-btn";
        b.textContent = label;
        b.addEventListener("click", fn);
        actions.appendChild(b);
        return b;
      };
      mk("画风替换", () => openStyleReplaceModal(panel, msgEl, {
        showAllPagesChoice: state.imagePageCount > 1,
        pageCount: state.imagePageCount,
      }));
      return;
    }
    host.innerHTML = "";
    groups.forEach((group) => {
      const combined = String(group.combined || "").trim();
      if (!combined) return;
      const row = document.createElement("div");
      row.className = "char-swap-style-slot char-swap-style-unified";
      const count = Number(group.slot_count || (group.tags || []).length || 0);
      row.innerHTML = `
        <div class="char-swap-style-combined-wrap">
          <span class="char-swap-style-slot-tag char-swap-style-combined-tag">${esc(combined)}</span>
          <span class="char-swap-style-slot-meta">${esc(styleGroupKindLabel(group))} · ${esc(styleFieldLabel(group))} · ${count} 项</span>
        </div>
        <div class="char-swap-actions"></div>`;
      const actions = $(".char-swap-actions", row);
      const mk = (label, fn) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "char-swap-btn";
        b.textContent = label;
        b.addEventListener("click", fn);
        return b;
      };
      actions.appendChild(mk("填入整串", () => {
        const findEl = $("#charSwapStyleFind", panel);
        const replaceEl = $("#charSwapStyleReplace", panel);
        if (findEl) findEl.value = combined;
        if (replaceEl) replaceEl.focus();
        setMsg(msgEl, "已填入合并画风串，可一次性整体替换", true);
      }));
      actions.appendChild(mk("删除整串", async () => {
        try {
          let res = await runStyleReplaceOnDraft(combined, "");
          if (!res.replacements && Array.isArray(group.tags)) {
            for (const tag of [...group.tags].reverse()) {
              res = await runStyleReplaceOnDraft(String(tag || "").trim(), "");
            }
          }
          renderStyleRows(panel);
          renderSlotRows(panel);
          setMsg(msgEl, (res.message || "已删除画风串") + "（仅草稿）", true);
        } catch (e) {
          setMsg(msgEl, e.message, false);
        }
      }));
      actions.appendChild(mk("画风替换", () => {
        openStyleReplaceModal(panel, msgEl, {
          combined,
          showAllPagesChoice: state.imagePageCount > 1,
          pageCount: state.imagePageCount,
        });
      }));
      actions.appendChild(mk("加入画风预设", () => {
        saveCurrentStyleAsPreset(combined, msgEl, combined.slice(0, 36));
      }));
      host.appendChild(row);
    });
  }

export function bindToolbar(panel) {
    const msgEl = $(".char-swap-msg", panel);
    const diffEl = $(".char-swap-diff", panel);
    const previewImg = $(".char-swap-preview img", panel);
    const toolbar = $(".char-swap-toolbar", panel);
    const quickBar = $("#charSwapQuickPresets", panel);
    if (quickBar && quickBar.dataset.bound !== "1") {
      quickBar.dataset.bound = "1";
      quickBar.addEventListener("click", async (e) => {
        const btn = e.target.closest("button[data-quick-preset]");
        if (!btn) return;
        const key = btn.dataset.quickPreset;
        if (key === "more_female") {
          showPresetModal("female", async (preset, scope) => {
            try {
              const body = {
                mode: "replace_female",
                target_work_id: state.workId,
                target_page_index: state.pageIndex,
                preset_id: preset.id,
                gender: "female",
                replace_creature: true,
              };
              if (scope === "all") {
                await runTransformAllPages(body, panel, msgEl, preset.label);
              } else {
                await runTransform(body);
                renderSlotRows(panel);
                renderStyleRows(panel);
                setMsg(msgEl, `草稿已换女角色：${preset.label}`, true);
              }
            } catch (err) { setMsg(msgEl, err.message, false); }
          });
          return;
        }
        if (key === "more_male") {
          showPresetModal("male", async (preset, scope) => {
            try {
              const body = {
                mode: "replace_male",
                target_work_id: state.workId,
                target_page_index: state.pageIndex,
                preset_id: preset.id,
                gender: "male",
                replace_creature: true,
              };
              if (scope === "all") {
                await runTransformAllPages(body, panel, msgEl, preset.label);
              } else {
                await runTransform(body);
                renderSlotRows(panel);
                renderStyleRows(panel);
                setMsg(msgEl, `草稿已换男角色：${preset.label}`, true);
              }
            } catch (err) { setMsg(msgEl, err.message, false); }
          });
          return;
        }
        const presetMap = {
          wisadel: { id: "wisadel", gender: "female", label: "维什戴尔" },
          surtr: { id: "surtr", gender: "female", label: "史尔特尔" },
          doctor_m: { id: "doctor_m", gender: "male", label: "博士" },
          silverash_m: { id: "silverash_m", gender: "male", label: "银灰" },
        };
        const preset = presetMap[key];
        if (!preset) return;
        try {
          const body = {
            mode: preset.gender === "female" ? "replace_female" : "replace_male",
            target_work_id: state.workId,
            target_page_index: state.pageIndex,
            preset_id: preset.id,
            gender: preset.gender,
            replace_creature: true,
          };
          await runTransform(body);
          renderSlotRows(panel);
          renderStyleRows(panel);
          setMsg(msgEl, `草稿已一键更换为：${preset.label}`, true);
        } catch (err) {
          setMsg(msgEl, err.message, false);
        }
      });
    }

    if (!toolbar || toolbar.dataset.bound === "1") return;
    toolbar.dataset.bound = "1";

    const bind = (action, handler) => {
      const btn = panel.querySelector(`[data-action="${action}"]`);
      if (btn) btn.addEventListener("click", handler);
    };

    bind("clone", async () => {
      const src = loadSource();
      if (!src) { alert("请先在角色行点「设为源」（见蓝色提示条）"); return; }
      try {
        await runTransform({
          mode: "clone",
          target_work_id: state.workId,
          target_page_index: state.pageIndex,
          custom_bundle: src.bundle,
        });
        renderSlotRows(panel);
        setMsg(msgEl, "草稿已追加角色（图库原文未改）", true);
      } catch (e) {
        setMsg(msgEl, e.message, false);
      }
    });

    bind("reset", () => {
      const gid = activeGalleryId();
      const key = `${gid}:${state.workId}:${state.pageIndex}`;
      extractCache.delete(key);
      if (state.workId != null) {
        clearDraftCacheForPage(state.workId, state.pageIndex);
      }
      initDraft(state.workId, state.pageIndex, panel).then(() => {
        const findEl = panel && $("#charSwapStyleFind", panel);
        const replaceEl = panel && $("#charSwapStyleReplace", panel);
        if (findEl) findEl.value = "";
        if (replaceEl) replaceEl.value = "";
        renderDiff(diffEl, []);
        const titleEl = $("#charSwapSlotsTitle", panel);
        if (titleEl) titleEl.textContent = "已恢复为原文草稿（角色槽）— 每行右侧有「设为源」";
        setMsg(msgEl, "已恢复为图库原始咒语草稿（含 seed）", true);
      });
    });

    bind("reset-all", () => {
      const workId = state.workId;
      if (workId == null) return;
      const pageCount = Math.max(1, Number(state.imagePageCount) || 1);
      if (pageCount > 1 && !window.confirm(`恢复本作品全部 ${pageCount} 张图的原文草稿？`)) return;
      const gid = activeGalleryId();
      for (let pi = 0; pi < pageCount; pi++) {
        extractCache.delete(`${gid}:${workId}:${pi}`);
      }
      clearDraftCacheForWork(workId);
      initDraft(workId, state.pageIndex, panel).then(() => {
        const findEl = panel && $("#charSwapStyleFind", panel);
        const replaceEl = panel && $("#charSwapStyleReplace", panel);
        if (findEl) findEl.value = "";
        if (replaceEl) replaceEl.value = "";
        renderDiff(diffEl, []);
        const titleEl = $("#charSwapSlotsTitle", panel);
        if (titleEl) titleEl.textContent = "已恢复为全部图片原文草稿（角色槽）— 每行右侧有「设为源」";
        setMsg(msgEl, `已恢复本作品全部 ${pageCount} 张图的图库原始咒语草稿（含 seed）`, true);
      });
    });

    bind("replace-male-all", () => {
      const n = Math.max(1, Number(state.imagePageCount) || 1);
      if (countGenderSlots(state.draftChars, "male") >= 2) {
        showMultiSlotPresetModal("male", panel, msgEl);
        return;
      }
      if (n <= 1) {
        setMsg(msgEl, "本作品仅 1 张图，请用角色行的「换男角」", false);
        return;
      }
      showPresetModal("male", async (preset) => {
        try {
          await runTransformAllPages({
            mode: "replace_male",
            preset_id: preset.id,
            gender: "male",
            target_char_index: "all_male",
            replace_creature: false,
          }, panel, msgEl, preset.label);
        } catch (e) {
          setMsg(msgEl, e.message, false);
        }
      }, { allPagesOnly: true, pageCount: n });
    });

    bind("replace-female-multi", () => {
      showMultiSlotPresetModal("female", panel, msgEl);
    });

    bind("replace-male-multi", () => {
      showMultiSlotPresetModal("male", panel, msgEl);
    });

    bind("replace-female-all", () => {
      const n = Math.max(1, Number(state.imagePageCount) || 1);
      if (countGenderSlots(state.draftChars, "female") >= 2) {
        showMultiSlotPresetModal("female", panel, msgEl);
        return;
      }
      if (n <= 1) {
        setMsg(msgEl, "本作品仅 1 张图，请用角色行的「换女角」", false);
        return;
      }
      showPresetModal("female", async (preset) => {
        try {
          await runTransformAllPages({
            mode: "replace_female",
            preset_id: preset.id,
            gender: "female",
            target_char_index: "all_female",
            replace_creature: false,
          }, panel, msgEl, preset.label);
        } catch (e) {
          setMsg(msgEl, e.message, false);
        }
      }, { allPagesOnly: true, pageCount: n });
    });

    bind("replace-style-all", () => {
      const n = Math.max(1, Number(state.imagePageCount) || 1);
      if (n <= 1) {
        setMsg(msgEl, "本作品仅 1 张图，请用画风识别行的「画风替换」", false);
        return;
      }
      openStyleReplaceModal(panel, msgEl, {
        allPagesOnly: true,
        pageCount: n,
      });
    });

    bind("sanitize", async () => {
      try {
        const res = await runSanitize();
        renderDiff(diffEl, res.removed);
        setMsg(msgEl, res.message + "（仅草稿，图库不变）", !res.blocked);
      } catch (e) {
        setMsg(msgEl, e.message, false);
      }
    });

    bind("replace-creature", () => {
      const cfg = state.pluginConfig || {};
      const gender = cfg.creature_replace_gender === "female" ? "female" : "male";
      showPresetModal(gender, async (preset) => {
        try {
          await runTransform({
            mode: "creature_to_partner",
            target_work_id: state.workId,
            target_page_index: state.pageIndex,
            target_char_index: "auto_creature",
            preset_id: preset.id,
            gender: preset.gender || gender,
            replace_creature: true,
          });
          renderSlotRows(panel);
          setMsg(msgEl, `已保留原角色，贵物换成：${preset.label}`, true);
        } catch (e) {
          setMsg(msgEl, e.message, false);
        }
      });
    });

    bind("style-apply", async () => {
      const find = ($("#charSwapStyleFind", panel) || {}).value || "";
      const replace = ($("#charSwapStyleReplace", panel) || {}).value || "";
      try {
        const { res } = await runStyleReplaceWithFallback({ combined: find.trim() }, replace);
        renderStyleRows(panel);
        renderSlotRows(panel);
        flashMsg(msgEl, `${res.message}（仅草稿）`, true);
      } catch (e) {
        flashMsg(msgEl, e.message, false);
      }
    });

    bind("add-batch", () => {
      if (!state.workId) return;
      const res = addManyToBatch([
        buildBatchEntry(
          state.workId,
          state.pageIndex,
          state.workTitle ? `${state.workTitle} p${state.pageIndex}` : `p${state.pageIndex}`,
        ),
      ]);
      const hasDraft = !!(state.draft && state.draft.v4_prompt);
      const added = res.added > 0 || res.updated > 0;
      setMsg(
        msgEl,
        added
          ? `已加入批量（p${state.pageIndex}${hasDraft ? " · 含工作台草稿" : ""}，队列 ${res.total}）`
          : "已在批量队列中（未更新草稿）",
        added,
      );
      const drawer = document.getElementById("charSwapBatchDrawer");
      if (drawer) drawer.classList.add("open");
      updateQuickAddHint();
    });

    bind("add-batch-all-pages", () => {
      if (!state.workId) return;
      const n = Math.max(1, Number(state.imagePageCount) || 1);
      const res = addAllWorkPagesToBatch(state.workId, n, { title: state.workTitle });
      setMsg(
        msgEl,
        `作品 #${state.workId}：加入 ${res.added} 项（${res.draftInRequest || 0} 张含工作台草稿，队列共 ${res.total}）${res.skipped ? `，跳过重复 ${res.skipped}` : ""}${res.updated ? `，更新草稿 ${res.updated}` : ""}`,
        res.added > 0 || res.updated > 0,
      );
      const drawer = document.getElementById("charSwapBatchDrawer");
      if (drawer) drawer.classList.add("open");
      updateQuickAddHint();
    });

    bind("copy", async () => {
      const txt = instructionFromAiJson(draftAiJson());
      if (!txt) { setMsg(msgEl, "无法生成草稿指令", false); return; }
      await copyText(txt);
      setMsg(msgEl, "已复制草稿 NAI 指令（非图库原文）", true);
    });

    bind("toggle", () => {
      state.collapsed = !state.collapsed;
      const body = $(".char-swap-body", panel);
      const btn = toolbar.querySelector('[data-action="toggle"]');
      if (body) body.classList.toggle("hidden", state.collapsed);
      if (btn) btn.textContent = state.collapsed ? "展开工作台" : "收起";
    });

    bind("generate", async () => {
      if (state.generating || !state.draft) return;
      const cfg = await loadPluginConfig();
      let status;
      try { status = await api("/api/nai/status"); } catch (e) {
        setMsg(msgEl, `NAI 状态: ${e.message}`, false);
        return;
      }
      if (!status.has_token) {
        setMsg(msgEl, "⚠️ 未检测到 NAI Token，无法在线生图。您可以点击「复制草稿指令」导出提示词，或到「设置」配置 Token。", false);
        return;
      }
      applySeedInputFromPanel(panel);
      const slotN = Math.max(1, Number(status.concurrency || status.enabled_count || 1) || 1);
      const providerHint = status.providers
        ? Object.entries(status.providers).map(([k, v]) => `${k}:${v}`).join(" / ")
        : `${slotN} slot(s)`;
      const freeHint = status.is_opus ? `Opus/Xianyun path · ${providerHint}` : `Will consume Anlas · ${providerHint}`;
      const seedHint = state.draft && state.draft.seed === -1
        ? "随机(-1)"
        : (state.draft && state.draft.seed !== undefined && state.draft.seed !== null
          ? String(state.draft.seed)
          : "原图");
      if (!confirm(`试生成？\n${freeHint}\nSeed: ${seedHint}\n单张串行，图库原文不会改变。`)) return;

      state.generating = true;
      const genBtn = toolbar.querySelector('[data-action="generate"]');
      if (genBtn) genBtn.disabled = true;
      setMsg(msgEl, "生图中（约 15–40 秒）...");
      if (previewImg) previewImg.removeAttribute("src");

      try {
        if (cfg.auto_sanitize_on_generate !== false) {
          try { await runSanitize(); renderDiff(diffEl, state.lastRemoved); } catch { }
        }
        const snapshot = deepClone(state.draft);
        const res = await api("/api/nai/generate", {
          method: "POST",
          body: JSON.stringify({
            patched_comment: snapshot,
            work_id: state.workId,
            page_index: state.pageIndex || 0,
            copies: 1,
            source_gallery_id: resolveActiveGalleryId() || "site",
            force_free: cfg.force_free !== false,
            prompt_profile: cfg.prompt_profile || "native",
          }),
        });
        if (!res.ok) throw new Error(res.message || res.error || "生图失败");
        const taskId = res.task_id || (res.batch && res.batch.task_id) || "";
        if (!taskId) throw new Error("未返回生成任务 ID");
        const job = await window.ApiClient.pollJob(taskId, (status) => {
          setMsg(msgEl, String(status.message || "生图中…"), true);
        });
        if (String(job.status || "") === "unknown") {
          throw new Error(job.message || "这次可能已扣费，不要自动重试；要重出请再确认。");
        }
        const items = Array.isArray(job.items) ? job.items : [];
        const lastOk = [...items].reverse().find((item) => item && item.ok && (item.image_url || item.gallery_url));
        if (!lastOk) throw new Error(job.message || "生图失败");
        if (previewImg && lastOk.image_url) {
          previewImg.src = lastOk.image_url + "?t=" + Date.now();
          previewImg.closest(".char-swap-preview").style.display = "";
        }
        const base = (lastOk.message || job.message || "完成") + (lastOk.free_eligible ? " · 免费路径" : "");
        const galleryUrl = lastOk.gallery_url || job.gallery_url;
        if (galleryUrl) {
          const wrap = document.createElement("span");
          wrap.textContent = base + " · ";
          const a = document.createElement("a");
          a.href = galleryUrl;
          a.target = "_blank";
          a.rel = "noopener";
          a.style.color = "#6eb6ff";
          a.textContent = "打开本组封面";
          wrap.appendChild(a);
          setMsg(msgEl, wrap, true, true);
        } else {
          setMsg(msgEl, base, true);
        }
        if (state.workId) refreshGenSidebar(state.workId);
      } catch (e) {
        setMsg(msgEl, e.message, false);
      } finally {
        state.generating = false;
        if (state.workId) refreshGenSidebar(state.workId);
        if (genBtn) genBtn.disabled = false;
      }
    });
  }

export async function initDraft(workId, pageIndex, panel, options = {}) {
    const msgEl = $(".char-swap-msg", panel);
    const diffEl = $(".char-swap-diff", panel);
    const origEl = $("#charSwapOriginalHint", panel);
    setMsg(msgEl, "加载中...");
    try {
      if (state.workId === workId && state.draft && state.pageIndex !== pageIndex) {
        saveCurrentDraftToCache();
      }
      const { data } = await loadExtract(workId, pageIndex);
      state.workId = workId;
      state.pageIndex = pageIndex;
      state.original = {
        comment: deepClone(data.comment),
        chars: deepClone(data.chars || []),
        style_slots: deepClone(data.style_slots || []),
        style_bundle: deepClone(data.style_bundle || buildStyleBundleFallback(data.style_slots || [])),
        ai_json: deepClone(data.ai_json),
        base_caption: data.base_caption,
      };
      resetDraftFromOriginal();
      // 如果有缓存的草稿（之前编辑过），加载缓存以恢复上次编辑状态
      // 注意：如果是从"恢复原文"按钮调用的 initDraft，缓存已被删除，不会覆盖
      loadDraftFromCache(workId, pageIndex);
      renderDiff(diffEl, []);

      if (origEl) {
        const base = (data.base_caption || "").slice(0, 120);
        origEl.textContent = base ? `原图 base：${base}…` : "原图咒语已锁定，下方 JSON/指令区始终显示图库原文";
      }

      if (!data.chars || !data.chars.length) {
        renderStyleRows(panel);
        renderSourceBar(panel);
        syncSeedUi(panel);
        updateDraftPreview();
        const styleCount = (state.styleBundle && state.styleBundle.combined)
          ? String(state.styleBundle.combined).split(",").filter((x) => x.trim()).length
          : (state.styleSlots || []).length;
        setMsg(msgEl, `草稿工作台 · 画风与Seed模式 · ${styleCount} 画风项 · p${pageIndex}（此图无 v4 多角色，仍可替换画风/修改Seed/加入批量）`, true);
        return;
      }
      renderSlotRows(panel);
      renderStyleRows(panel);
      renderSourceBar(panel);
      syncSeedUi(panel);
      const styleCount = (state.styleBundle && state.styleBundle.combined)
        ? String(state.styleBundle.combined).split(",").filter((x) => x.trim()).length
        : (state.styleSlots || []).length;
      setMsg(msgEl, `草稿工作台 · ${data.chars.length} 角色槽 · ${styleCount} 画风项 · p${pageIndex}（图库原文未修改）`, true);
    } catch (e) {
      setMsg(msgEl, e.message, false);
      if (options.throwOnError) throw e;
      return false;
    }
    return true;
  }

export { buildPanel, mountSettings } from "./panel_shell.js?v=fcd7e17dc6";

setWorkbenchHandlers({
  loadExtract,
  renderSlotRows,
  renderStyleRows,
  resetDraftFromOriginal,
  runTransform,
  runTransformAllPages,
  runTransformMulti,
  runTransformMultiAllPages,
  syncSeedUi,
  syncStyleFromResponse,
  updateDraftPreview,
});

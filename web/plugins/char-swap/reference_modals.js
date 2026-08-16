// Production owner for character/reference picker modals and selection scope.

import { state } from "./state.js?v=f80b97d795";
import { api, $, setMsg, loadPluginConfig } from "./api.js?v=a73081883e";
import {
  applyGenderSwapTarget,
  countGenderSlots,
  genderRoleLabel,
  genderSlots,
  slotDisplayName,
} from "./slots.js?v=6adf84cea2";
import {
  characterReferenceLabel,
  filterCharacterReferences,
  loadCharacterReferences,
  saveCustomCharacterReference,
} from "./character_references.js?v=0b07780c8b";
import { createModal, dismissModals } from "./dom_adapter.js?v=68ad0782e7";
import { stylePresetDetail } from "./style_workflows.js?v=c55efe211e";
import {
  renderSlotRows,
  renderStyleRows,
  runTransform,
  runTransformAllPages,
  runTransformMulti,
  runTransformMultiAllPages,
} from "./workbench_bridge.js?v=e72141834f";
export function presetModalLabel(p) {
    return characterReferenceLabel(p);
  }

export function createCustomOcComposer(gender, onSaved, opts = {}) {
    const root = document.createElement("section");
    root.className = "char-swap-custom-oc";
    const genderText = gender === "male" ? "男角色" : "女角色";
    root.innerHTML = `
      <button type="button" class="char-swap-btn char-swap-add-custom-oc" aria-expanded="false">＋ 自定义 OC</button>
      <form class="char-swap-custom-oc-form" hidden>
        <div class="char-swap-custom-oc-heading">添加我的 ${genderText}</div>
        <label class="char-swap-modal-field-label">OC 名称
          <input name="label" class="char-swap-modal-field-input" type="text" maxlength="80" autocomplete="off" placeholder="例如：星野澪" required />
        </label>
        <label class="char-swap-modal-field-label">OC 完整特征 / tag
          <textarea name="char_caption" class="char-swap-modal-field-input char-swap-custom-oc-caption" maxlength="8000" rows="4" placeholder="例如：1girl, female_focus, silver hair, starry eyes, blue dress" required></textarea>
        </label>
        <p class="char-swap-modal-hint">性别沿用当前选择（${genderText}）。请写完整且稳定的角色特征，保存后会立即用于${opts.targetLabel || "当前角色槽"}。</p>
        <div class="char-swap-custom-oc-status" role="status" aria-live="polite"></div>
        <div class="char-swap-modal-foot">
          <button type="button" class="char-swap-btn char-swap-custom-oc-cancel">取消</button>
          <button type="submit" class="char-swap-btn primary">保存并使用</button>
        </div>
      </form>`;
    const toggle = $(".char-swap-add-custom-oc", root);
    const form = $(".char-swap-custom-oc-form", root);
    const labelInput = $('[name="label"]', form);
    const captionInput = $('[name="char_caption"]', form);
    const cancel = $(".char-swap-custom-oc-cancel", form);
    const submit = $('button[type="submit"]', form);
    const status = $(".char-swap-custom-oc-status", form);
    const setOpen = (open) => {
      form.hidden = !open;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.textContent = open ? "收起自定义 OC" : "＋ 自定义 OC";
      if (open && !window.matchMedia("(max-width: 640px)").matches) {
        setTimeout(() => labelInput.focus(), 0);
      }
    };
    toggle.addEventListener("click", () => setOpen(form.hidden));
    cancel.addEventListener("click", () => {
      status.textContent = "";
      setOpen(false);
      toggle.focus();
    });
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const label = String(labelInput.value || "").trim();
      const charCaption = String(captionInput.value || "").trim();
      if (!label || !charCaption) {
        status.textContent = "请填写 OC 名称和完整特征。";
        (!label ? labelInput : captionInput).focus();
        return;
      }
      submit.disabled = true;
      cancel.disabled = true;
      status.textContent = "正在保存…";
      try {
        const preset = await saveCustomCharacterReference({ label, gender, charCaption });
        status.textContent = "已保存，正在应用…";
        await onSaved(preset);
        form.reset();
        status.textContent = "";
        setOpen(false);
      } catch (error) {
        status.textContent = error.message || "保存自定义 OC 失败";
      } finally {
        submit.disabled = false;
        cancel.disabled = false;
      }
    });
    return root;
  }

export function showPresetModal(gender, onPick, opts = {}) {
    dismissCharSwapModals();
    const pageCount = Math.max(1, Number(opts.pageCount) || state.imagePageCount || 1);
    const allPagesOnly = !!opts.allPagesOnly && pageCount > 1;
    const showScope = !allPagesOnly && !!opts.showAllPagesChoice && pageCount > 1;
    const multiSlotGender = gender === "female" || gender === "male" ? gender : "";
    const multiSlotCount = multiSlotGender
      ? countGenderSlots(state.draftChars || [], multiSlotGender)
      : 0;
    const showAllSlots = !allPagesOnly && multiSlotCount >= 2;
    const { backdrop, modal, close: closeModal, mount } = createModal();
    const title = allPagesOnly
      ? `选择${gender === "male" ? "男" : "女"}角色 · 应用到全部 ${pageCount} 张图`
      : `选择${gender === "male" ? "男" : "女"}角色预设`;
    modal.innerHTML = `
      <h3>${title}</h3>
      <input id="presetSearchInput" type="text" class="char-swap-search-input" placeholder="🔍 搜索角色 (支持中文名/英文/tag，如 维什戴尔 / 史尔特尔 / 博士 / surtr)..." style="width:100%;padding:8px 12px;margin:8px 0 10px;background:#131720;color:#e6edf3;border:1px solid rgba(255,255,255,0.2);border-radius:6px;font-size:0.88rem;box-sizing:border-box;" />
      <div class="char-swap-preset-tools">
        <button type="button" class="char-swap-btn char-swap-my-oc-filter" aria-pressed="false">我的 OC</button>
      </div>
      <div class="preset-list" style="max-height:360px;overflow-y:auto;"></div>`;
    if (showScope || showAllSlots) {
      const hint = document.createElement("p");
      hint.className = "char-swap-modal-hint";
      if (showScope && showAllSlots) {
        hint.textContent = gender === "male"
          ? `本图有 ${multiSlotCount} 个男槽 · 各槽不同角色请用工具栏「${genderRoleLabel("male", multiSlotCount)}换角」`
          : `本图有 ${multiSlotCount} 个女槽 · 各槽不同角色请用工具栏「${genderRoleLabel("female", multiSlotCount)}换角」`;
      } else if (showAllSlots) {
        hint.textContent = `本图有 ${multiSlotCount} 个${gender === "male" ? "男" : "女"}槽 · 「全部同角色」= 同一预设换所有槽`;
      } else {
        hint.textContent = `本作品共 ${pageCount} 张图 · 点「全部图片」将同时更新每张图的 tag 草稿`;
      }
      modal.insertBefore(hint, $(".preset-list", modal));
    }
    const list = $(".preset-list", modal);
    const searchInput = $("#presetSearchInput", modal);
    const myOcFilter = $(".char-swap-my-oc-filter", modal);
    let combined = [];
    let onlyCustom = false;
    let renderFilteredList = () => {};
    const composer = createCustomOcComposer(gender, async (preset) => {
      combined = [preset, ...combined.filter((item) => String(item.id || "") !== String(preset.id || ""))];
      onlyCustom = false;
      myOcFilter.setAttribute("aria-pressed", "false");
      renderFilteredList(searchInput ? searchInput.value : "");
      await onPick(preset, allPagesOnly ? "all" : "current");
      closeModal();
    });
    modal.insertBefore(composer, searchInput);
    myOcFilter.addEventListener("click", () => {
      onlyCustom = !onlyCustom;
      myOcFilter.setAttribute("aria-pressed", onlyCustom ? "true" : "false");
      myOcFilter.classList.toggle("active", onlyCustom);
      renderFilteredList(searchInput ? searchInput.value : "");
    });

    loadCharacterReferences(gender).then((references) => {
      combined = references;
      renderFilteredList = function renderPresetList(query) {
        list.innerHTML = "";
        const filtered = filterCharacterReferences(combined, query, { onlyCustom });

        if (!filtered.length) {
          const empty = document.createElement("div");
          empty.className = "char-swap-preset-empty";
          empty.textContent = onlyCustom ? "还没有匹配的自定义 OC，可在上方直接添加。" : `未找到匹配角色“${query}”`;
          list.appendChild(empty);
          return;
        }

        filtered.forEach((p) => {
          if (showScope || showAllSlots) {
            const row = document.createElement("div");
            row.className = "char-swap-preset-row";
            const label = document.createElement("span");
            label.className = "char-swap-preset-label";
            label.textContent = presetModalLabel(p);
            const btnWrap = document.createElement("div");
            btnWrap.className = "char-swap-preset-actions";
            if (showScope) {
              const curBtn = document.createElement("button");
              curBtn.type = "button";
              curBtn.className = "char-swap-btn char-swap-btn-all-scope char-swap-btn-scope-current";
              curBtn.textContent = "当前图";
              curBtn.addEventListener("click", () => { onPick(p, "current"); closeModal(); });
              const allBtn = document.createElement("button");
              allBtn.type = "button";
              allBtn.className = "char-swap-btn char-swap-btn-all-scope char-swap-btn-scope-all primary";
              allBtn.textContent = "全部图片";
              allBtn.addEventListener("click", () => { onPick(p, "all"); closeModal(); });
              btnWrap.appendChild(curBtn);
              btnWrap.appendChild(allBtn);
            } else {
              const curBtn = document.createElement("button");
              curBtn.type = "button";
              curBtn.className = "char-swap-btn char-swap-btn-all-scope char-swap-btn-scope-current";
              curBtn.textContent = "当前槽";
              curBtn.addEventListener("click", () => { onPick(p, "current"); closeModal(); });
              btnWrap.appendChild(curBtn);
            }
            if (showAllSlots) {
              const slotsBtn = document.createElement("button");
              slotsBtn.type = "button";
              slotsBtn.className = "char-swap-btn char-swap-btn-all-scope char-swap-btn-scope-slots primary";
              slotsBtn.textContent = "全部同角色";
              slotsBtn.addEventListener("click", () => { onPick(p, "all_slots"); closeModal(); });
              btnWrap.appendChild(slotsBtn);
            }
            row.appendChild(label);
            row.appendChild(btnWrap);
            list.appendChild(row);
            return;
          }
          const btn = document.createElement("button");
          btn.type = "button";
          btn.className = "char-swap-btn char-swap-preset";
          btn.textContent = presetModalLabel(p);
          btn.addEventListener("click", () => {
            onPick(p, allPagesOnly ? "all" : "current");
            closeModal();
          });
          list.appendChild(btn);
        });
      }

      renderFilteredList("");
      if (searchInput) {
        searchInput.addEventListener("input", (e) => renderFilteredList(e.target.value));
        if (!window.matchMedia("(max-width: 640px)").matches) setTimeout(() => searchInput.focus(), 100);
      }
    }).catch((e) => { list.textContent = `加载失败: ${e.message}`; });
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeModal(); });
    mount();
  }

export function showMultiSlotPresetModal(gender, panel, msgEl, opts = {}) {
    const slots = genderSlots(state.draftChars || [], gender);
    if (slots.length < 2) {
      showPresetModal(gender, async (preset, scope) => {
        try {
          const body = {
            mode: gender === "male" ? "replace_male" : "replace_female",
            target_work_id: state.workId,
            target_page_index: state.pageIndex,
            preset_id: preset.id,
            gender,
            replace_creature: true,
          };
          const focusCh = opts.focusIndex != null
            ? (state.draftChars || []).find((c) => c.index === opts.focusIndex)
            : null;
          applyGenderSwapTarget(body, state.draftChars || [], focusCh, gender, scope);
          if (scope === "all") {
            await runTransformAllPages(body, panel, msgEl, preset.label);
          } else {
            await runTransform(body);
            renderSlotRows(panel);
            renderStyleRows(panel);
            setMsg(msgEl, `草稿已换为${gender === "male" ? "男" : "女"}角色：${preset.label}`, true);
          }
        } catch (e) {
          setMsg(msgEl, e.message, false);
        }
      }, { showAllPagesChoice: state.imagePageCount > 1 });
      return;
    }

    const { backdrop, modal, close: closeModal, mount } = createModal({ className: "char-swap-modal-multi" });
    const pageCount = Math.max(1, Number(state.imagePageCount) || 1);
    const roleLabel = genderRoleLabel(gender, slots.length);
    const pageHint = pageCount > 1
      ? `本作品共 ${pageCount} 张图；「全部图片」会按<strong>第1/第2…个${gender === "male" ? "男" : "女"}槽</strong>套用到每张图。`
      : "";
    modal.innerHTML = `
      <h3>${roleLabel}换角 · 逐槽选择</h3>
      <p class="char-swap-modal-hint">本图有 ${slots.length} 个${gender === "male" ? "男" : "女"}槽，请为<strong>每个槽</strong>分别选择要换成的角色。选「保持原角色」则不改该槽。${pageHint}</p>
      <div class="char-swap-multi-slot-list"></div>
      <div class="char-swap-multi-slot-foot"></div>`;
    const listEl = $(".char-swap-multi-slot-list", modal);
    const footEl = $(".char-swap-multi-slot-foot", modal);
    const selects = [];
    const composer = createCustomOcComposer(gender, async (preset) => {
      if (!selects.length) throw new Error("角色槽仍在加载，请稍后再试");
      selects.forEach((select) => {
        if (![...select.options].some((option) => String(option.value) === String(preset.id))) {
          const option = document.createElement("option");
          option.value = preset.id;
          option.textContent = presetModalLabel(preset);
          select.appendChild(option);
        }
      });
      const target = selects.find((select) => Number(select.dataset.index) === Number(opts.focusIndex)) || selects[0];
      target.value = preset.id;
      target.focus();
      target.closest(".char-swap-multi-slot-row")?.classList.add("focused");
      setMsg(msgEl, `已添加自定义 OC「${preset.label}」，并选入当前槽`, true);
    }, { targetLabel: "当前槽（可继续选择其他槽）" });
    modal.insertBefore(composer, listEl);

    loadCharacterReferences(gender, { includeLibrary: false }).then((presets) => {
      slots.forEach((ch) => {
        const row = document.createElement("div");
        row.className = "char-swap-multi-slot-row";
        if (opts.focusIndex === ch.index) row.classList.add("focused");
        const label = document.createElement("div");
        label.className = "char-swap-multi-slot-label";
        label.innerHTML = `<span class="char-swap-slot-num">#${ch.index + 1}</span><span class="char-swap-slot-name"></span>`;
        const nameEl = label.querySelector(".char-swap-slot-name");
        if (nameEl) nameEl.textContent = slotDisplayName(ch) || "";
        const sel = document.createElement("select");
        sel.className = "char-swap-multi-slot-select";
        sel.dataset.index = String(ch.index);
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = "— 保持原角色 —";
        sel.appendChild(empty);
        presets.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = p.id;
          opt.textContent = presetModalLabel(p);
          sel.appendChild(opt);
        });
        row.appendChild(label);
        row.appendChild(sel);
        listEl.appendChild(row);
        selects.push(sel);
      });

      const presetLabelsFromSelects = (replacements) => replacements.map((r) => {
        const sel = selects.find((s) => Number(s.dataset.index) === r.target_char_index);
        const opt = sel && sel.selectedOptions[0];
        return opt ? String(opt.textContent).split(/[·—]/)[0].trim() : "";
      }).filter(Boolean);

      const collectReplacements = () => selects
        .map((sel) => ({
          target_char_index: Number(sel.dataset.index),
          preset_id: sel.value,
        }))
        .filter((r) => r.preset_id);

      const applyCurrentBtn = document.createElement("button");
      applyCurrentBtn.type = "button";
      applyCurrentBtn.className = "char-swap-btn primary";
      applyCurrentBtn.textContent = pageCount > 1 ? "应用·当前图" : "应用";
      applyCurrentBtn.addEventListener("click", async () => {
        const replacements = collectReplacements();
        if (!replacements.length) {
          setMsg(msgEl, "请至少为一个槽位选择预设", false);
          return;
        }
        try {
          await runTransformMulti(replacements, { gender });
          renderSlotRows(panel);
          renderStyleRows(panel);
          const names = presetLabelsFromSelects(replacements);
          setMsg(msgEl, `${roleLabel}已更新：${names.join("、")}（仅草稿）`, true);
          closeModal();
        } catch (e) {
          setMsg(msgEl, e.message, false);
        }
      });

      const applyAllBtn = pageCount > 1 ? document.createElement("button") : null;
      if (applyAllBtn) {
        applyAllBtn.type = "button";
        applyAllBtn.className = "char-swap-btn char-swap-btn-all-scope primary";
        applyAllBtn.textContent = "全部图片替换";
        applyAllBtn.addEventListener("click", async () => {
          const replacements = collectReplacements();
          if (!replacements.length) {
            setMsg(msgEl, "请至少为一个槽位选择预设", false);
            return;
          }
          try {
            const names = presetLabelsFromSelects(replacements);
            await runTransformMultiAllPages(replacements, panel, msgEl, {
              gender,
              labels: names,
            });
            closeModal();
          } catch (e) {
            setMsg(msgEl, e.message, false);
          }
        });
      }

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "char-swap-btn";
      cancelBtn.textContent = "取消";
      cancelBtn.addEventListener("click", closeModal);

      const sameBtn = document.createElement("button");
      sameBtn.type = "button";
      sameBtn.className = "char-swap-btn char-swap-btn-linkish";
      sameBtn.textContent = "全部换成同一角色…";
      sameBtn.addEventListener("click", () => {
        closeModal();
        showPresetModal(gender, async (preset, scope) => {
          try {
            const body = {
              mode: gender === "male" ? "replace_male" : "replace_female",
              target_work_id: state.workId,
              target_page_index: state.pageIndex,
              preset_id: preset.id,
              gender,
              replace_creature: false,
            };
            if (scope === "all_slots" || scope === "current") {
              body.target_char_index = gender === "male" ? "all_male" : "all_female";
            }
            if (scope === "all") {
              await runTransformAllPages(body, panel, msgEl, preset.label);
            } else {
              await runTransform(body);
              renderSlotRows(panel);
              renderStyleRows(panel);
              setMsg(msgEl, `全部槽已换成：${preset.label}（同一角色）`, true);
            }
          } catch (e) {
            setMsg(msgEl, e.message, false);
          }
        }, { showAllPagesChoice: state.imagePageCount > 1 });
      });

      footEl.appendChild(applyCurrentBtn);
      if (applyAllBtn) footEl.appendChild(applyAllBtn);
      footEl.appendChild(cancelBtn);
      footEl.appendChild(sameBtn);
    }).catch((e) => {
      listEl.textContent = `加载预设失败: ${e.message}`;
    });

    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeModal(); });
    mount();
  }

export function dismissCharSwapModals() {
    dismissModals();
  }

export function showStylePresetModal(onPick, opts = {}) {
    dismissCharSwapModals();
    const pageCount = Math.max(1, Number(opts.pageCount) || state.imagePageCount || 1);
    const allPagesOnly = !!opts.allPagesOnly && pageCount > 1;
    const showScope = !allPagesOnly && !!opts.showAllPagesChoice && pageCount > 1;
    const msgEl = opts.msgEl || (opts.panel ? $(".char-swap-msg", opts.panel) : null);

    const runPick = async (preset, scope) => {
      try {
        if (scope === "all" && msgEl) setMsg(msgEl, `正在消除并加入画风（全部 ${pageCount} 张）…`, true);
        await onPick(preset, scope);
      } catch (e) {
        if (msgEl) setMsg(msgEl, e.message || String(e), false);
        else window.alert(e.message || String(e));
      }
    };
    const { backdrop, modal, close: closeModal, mount } = createModal();
    const title = allPagesOnly
      ? `选择画风预设 · 应用到全部 ${pageCount} 张图`
      : "选择画风预设";
    modal.innerHTML = `<h3>${title}</h3><div class="preset-list"></div>`;
    if (showScope) {
      const hint = document.createElement("p");
      hint.className = "char-swap-modal-hint";
      hint.textContent = `本作品共 ${pageCount} 张图 · 点「全部图片」会先消除每张图识别画风，再写入所选预设`;
      modal.insertBefore(hint, $(".preset-list", modal));
    }
    const list = $(".preset-list", modal);
    list.textContent = "加载画风预设…";
    loadPluginConfig().then((cfg) => {
      const presets = cfg.style_presets || [];
      if (!presets.length) {
        list.innerHTML = "";
        const empty = document.createElement("div");
        empty.className = "char-swap-style-preset-empty";
        empty.textContent = "暂无画风预设。";
        const link = document.createElement("button");
        link.type = "button";
        link.className = "char-swap-btn char-swap-btn-style";
        link.textContent = "去设置添加";
        link.addEventListener("click", () => {
          closeModal();
          if (typeof openFcPanel === "function") {
            openFcPanel();
          } else {
            document.getElementById("fcChip")?.click();
          }
          setTimeout(() => {
            document.getElementById("stylePresetLabel")?.focus();
            document.getElementById("charSwapStylePresetSection")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }, 120);
        });
        empty.appendChild(document.createElement("br"));
        empty.appendChild(link);
        list.appendChild(empty);
        return;
      }
      presets.forEach((p) => {
        const detail = stylePresetDetail(p);
        if (showScope) {
          const row = document.createElement("div");
          row.className = "char-swap-preset-row";
          const label = document.createElement("span");
          label.className = "char-swap-preset-label";
          label.textContent = `${p.label || p.id || "预设"} · ${detail}`;
          const curBtn = document.createElement("button");
          curBtn.type = "button";
          curBtn.className = "char-swap-btn char-swap-btn-all-scope char-swap-btn-scope-current";
          curBtn.textContent = "当前图";
          curBtn.addEventListener("click", () => { backdrop.remove(); runPick(p, "current"); });
          const allBtn = document.createElement("button");
          allBtn.type = "button";
          allBtn.className = "char-swap-btn char-swap-btn-all-scope char-swap-btn-scope-all primary";
          allBtn.textContent = "全部图片";
          allBtn.addEventListener("click", () => { backdrop.remove(); runPick(p, "all"); });
          row.appendChild(label);
          row.appendChild(curBtn);
          row.appendChild(allBtn);
          list.appendChild(row);
          return;
        }
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "char-swap-btn char-swap-preset char-swap-btn-style";
        btn.textContent = `${p.label || p.id || "预设"} · ${detail}`;
        btn.addEventListener("click", () => {
          closeModal();
          runPick(p, allPagesOnly ? "all" : "current");
        });
        list.appendChild(btn);
      });
    }).catch((e) => { list.textContent = `加载失败: ${e.message}`; });
    backdrop.addEventListener("click", (e) => { if (e.target === backdrop) closeModal(); });
    mount();
  }


// aitag-online 图库的换角/草稿面板（从 app.js 拆出）。
// 经典脚本：依赖 app-core.js 的全局 state/工具，须在 app.js 之前加载。

const ONLINE_DRAFT_KEY = 'aitag.studio.draft.v1';
const CHAR_SWAP_STYLE_URL = '/assets/plugins/char-swap/char-swap.css?v=220e25d883';
const onlineRemixState = {
  workId: '',
  data: null,
  candidateId: '',
  imageIndex: 0,
  slotIndex: 0,
  targetReferenceId: '',
  targetLabel: '',
  onlyCustomTargets: false,
  genderFilter: '',
  targetCache: [],
  /** @type {Record<string, {draft: object, imageIndex: number, label: string, studioUrl: string}>} */
  pageDrafts: {},
  /**
   * Visual overrides after char replace: key = `${imageIndex}:${slotIndex}`
   * @type {Record<string, {label: string, captionPreview: string, targetReferenceId: string}>}
   */
  slotOverrides: {},
  lastDraftKey: '',
  generating: false,
  drafting: false,
};

function onlineSlotOverrideKey(imageIndex, slotIndex) {
  return `${Number(imageIndex) || 0}:${Number(slotIndex) || 0}`;
}

function onlineSlotOverride(imageIndex, slotIndex) {
  return onlineRemixState.slotOverrides[onlineSlotOverrideKey(imageIndex, slotIndex)] || null;
}

/** Persist which slots were replaced so the list shows the new character. */
function recordOnlineSlotOverridesFromResult(result, label, { replaceCharacter = false, replaceAllSlotsOnPage = false } = {}) {
  if (!replaceCharacter) return 0;
  const displayLabel = String(label || onlineRemixState.targetLabel || '已替换').trim() || '已替换';
  const pages = Array.isArray(result?.pages) && result.pages.length
    ? result.pages
    : (result?.draft ? [result] : []);
  const touchedPages = pages.map((page) => Number(page.image_index ?? page.draft?.pageIndex ?? 0));
  // When this call rewrote whole-page gender slots, drop stale overrides for those pages
  // only for the slots being rewritten (merge for single-slot stack).
  let count = 0;
  pages.forEach((page) => {
    const imageIndex = Number(page.image_index ?? page.draft?.pageIndex ?? 0);
    const draft = page.draft || page;
    const lines = onlineDraftCharLines(draft);
    let slots = Array.isArray(page.slot_indexes) ? page.slot_indexes.map(Number) : [];
    if (!slots.length && page.slot_index != null && page.slot_index !== undefined) {
      slots = [Number(page.slot_index)];
    }
    if (!slots.length && imageIndex === Number(onlineRemixState.imageIndex || 0)) {
      slots = [Number(onlineRemixState.slotIndex || 0)];
    }
    if (replaceAllSlotsOnPage && lines.length) {
      // Clear previous overrides on this page before writing new gender-scope results.
      onlineClearSlotOverridesForPages([imageIndex]);
    }
    slots.forEach((slotIndex) => {
      const si = Number(slotIndex);
      if (!Number.isFinite(si) || si < 0) return;
      const captionPreview = String(lines[si] || lines[0] || '').trim().slice(0, 96);
      onlineRemixState.slotOverrides[onlineSlotOverrideKey(imageIndex, si)] = {
        label: displayLabel,
        captionPreview,
        targetReferenceId: String(onlineRemixState.targetReferenceId || ''),
      };
      count += 1;
    });
  });
  return count;
}

function ensureCharSwapStylesLoaded() {
  if (document.querySelector('link[data-char-swap-styles="1"]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CHAR_SWAP_STYLE_URL;
  link.dataset.charSwapStyles = '1';
  document.head.appendChild(link);
}

function onlineImageArrayIndexes(images) {
  return (Array.isArray(images) ? images : []).map((_, index) => index);
}

function uniqueTagList(values = []) {
  const seen = new Set();
  const out = [];
  for (const value of values) {
    const tag = String(value || '').trim();
    if (!tag || seen.has(tag.toLowerCase())) continue;
    seen.add(tag.toLowerCase());
    out.push(tag);
  }
  return out;
}

function onlineCandidateUsable(candidate = {}) {
  const identity = uniqueTagList([
    ...(Array.isArray(candidate.identity_tags) ? candidate.identity_tags : []),
    ...(Array.isArray(candidate.asset?.identity_tags) ? candidate.asset.identity_tags : []),
  ]);
  const caption = String(candidate.caption || candidate.asset?.label || '').trim();
  const namedIdentity = identity.some((tag) => !/^(1girl|1boy|female_focus|male_focus|original_character)$/i.test(tag));
  const hasCaption = caption.length >= 8;
  return namedIdentity || hasCaption;
}

function onlineCharacterCandidates(data = {}) {
  return (Array.isArray(data.character_candidates) ? data.character_candidates : [])
    .filter((candidate) => candidate && String(candidate.candidate_id || '').trim())
    .map((candidate) => {
      const identityTags = uniqueTagList([
        ...(Array.isArray(candidate.identity_tags) ? candidate.identity_tags : []),
        ...(Array.isArray(candidate.asset?.identity_tags) ? candidate.asset.identity_tags : []),
      ]);
      const appearanceTags = uniqueTagList([
        ...(Array.isArray(candidate.appearance_tags) ? candidate.appearance_tags : []),
        ...(Array.isArray(candidate.asset?.appearance_tags) ? candidate.asset.appearance_tags : []),
      ]);
      const label = String(candidate.label || candidate.asset?.label || `角色槽 ${Number(candidate.slot_index || 0) + 1}`);
      const caption = String(candidate.caption || '');
      const usable = onlineCandidateUsable(candidate);
      return {
        candidateId: String(candidate.candidate_id || ''),
        imageIndex: Number(candidate.image_index || 0),
        slotIndex: Number(candidate.slot_index || 0),
        label,
        caption,
        role: String(candidate.role || ''),
        identityTags,
        appearanceTags,
        usable,
      };
    });
}

function onlineUsableBadge(usable) {
  return usable
    ? '<span class="char-swap-badge online-usable-badge is-usable">可用</span>'
    : '<span class="char-swap-badge online-usable-badge is-weak">弱识别</span>';
}

function renderOnlineCharacterCandidates(data, workId) {
  ensureCharSwapStylesLoaded();
  const candidates = onlineCharacterCandidates(data);
  const usableCount = candidates.filter((item) => item.usable).length;
  const images = Array.isArray(data.images) ? data.images : [];
  const imageIndexes = onlineImageArrayIndexes(images);
  const firstUsable = candidates.find((item) => item.usable);
  const firstIndex = firstUsable?.imageIndex ?? candidates[0]?.imageIndex ?? imageIndexes[0] ?? 0;
  const pageTabs = imageIndexes.map((index) => {
    const pageCandidates = candidates.filter((candidate) => candidate.imageIndex === index);
    const pageUsable = pageCandidates.filter((candidate) => candidate.usable).length;
    return `<button type="button" class="char-swap-btn online-page-tab${index === firstIndex ? ' active' : ''}" data-online-page="${index}">p${index}<small>${pageUsable}/${pageCandidates.length}</small></button>`;
  }).join('');
  const options = imageIndexes.map((index) => {
    const pageCandidates = candidates.filter((candidate) => candidate.imageIndex === index);
    const pageUsable = pageCandidates.filter((candidate) => candidate.usable).length;
    return `<option value="${index}"${index === firstIndex ? ' selected' : ''}>p${index} · ${pageUsable}/${pageCandidates.length}</option>`;
  }).join('');
  // Compact shell aligned with local char-swap panel (same sections, less chrome).
  return `<section id="onlineRemixPanel" class="char-swap-panel online-remix-panel is-compact" data-work-id="${escapeHtml(workId)}">
    <div class="char-swap-head">
      <div>
        <strong>角色与画风草稿</strong>
        <div class="char-swap-hint">在线库 · 换角后直接试生成，<b>不改</b>原作品</div>
      </div>
      <span id="onlineCandidateCount" class="char-swap-badge">可用 ${usableCount}/${candidates.length}</span>
    </div>
    <div class="char-swap-body">
      <div class="char-swap-source-bar empty" id="onlineSourceBar">点选角色槽 → 常用角色 / 搜索替换</div>
      <div class="online-page-row">
        <div class="char-swap-page-tabs online-page-tabs" id="onlinePageTabs">${pageTabs}</div>
        <select id="onlineSourceImage" class="char-swap-search-input online-source-image-select" aria-label="原图页">${options}</select>
      </div>
      <div class="char-swap-section-title">编辑中草稿（角色槽）</div>
      <div class="char-swap-slots-draft online-source-candidates" id="onlineSourceCandidates"></div>
      <div class="char-swap-quick-presets online-quick-row" id="onlineQuickSwapRow">
        <span>⚡ 常用角色：</span>
      </div>
      <div class="char-swap-preset-tools online-target-tools">
        <input id="onlineTargetQuery" type="search" class="char-swap-search-input" placeholder="搜索角色 / tag / 维什戴尔…" autocomplete="off" />
        <button id="onlineTargetSearchBtn" type="button" class="char-swap-btn">搜索</button>
        <button id="onlineTargetMyOcFilter" type="button" class="char-swap-btn char-swap-my-oc-filter" aria-pressed="false">我的 OC</button>
      </div>
      <div id="onlineTargetResults" class="preset-list online-target-results"></div>
      <div id="onlineTargetStatus" class="char-swap-msg online-target-status" role="status">点角色卡会立刻换到当前槽；弱识别角色仍可点，会说明原因。画风可单独替换。</div>
      <div class="char-swap-style-row online-style-row">
        <span class="char-swap-style-label">画风</span>
        <input id="onlineStyleFind" type="text" placeholder="当前画风（可留空=只追加）" autocomplete="off" />
        <span class="char-swap-style-arrow">→</span>
        <input id="onlineStyleReplace" type="text" placeholder="新画风 / 预设" autocomplete="off" />
        <select id="onlineStylePreset" title="画风预设"></select>
        <button type="button" class="char-swap-btn" id="onlineStyleApplyBtn">应用画风</button>
        <button type="button" class="char-swap-btn char-swap-btn-style" id="onlineStyleAllBtn">画风·全部图片</button>
      </div>
      <div class="char-swap-toolbar online-remix-actions">
        <button id="onlineOriginalDraftBtn" type="button" class="char-swap-btn">原图草稿</button>
        <button id="onlineCharacterDraftBtn" type="button" class="char-swap-btn" disabled>应用换角</button>
        <button id="onlineReplaceMaleAllBtn" type="button" class="char-swap-btn char-swap-btn-all-pages" disabled>换男角·全部</button>
        <button id="onlineReplaceFemaleAllBtn" type="button" class="char-swap-btn char-swap-btn-all-pages" disabled>换女角·全部</button>
        <button id="onlineGenerateBtn" type="button" class="char-swap-btn primary" disabled>单张试生成 ▶</button>
        <button id="onlineGenerateAllBtn" type="button" class="char-swap-btn char-swap-btn-all-pages" disabled>生成已换页</button>
        <a id="onlineGenGalleryLink" class="char-swap-btn" href="/generated" target="_blank" rel="noopener">生成库 ↗</a>
      </div>
      <div id="onlineRemixResult" class="online-remix-result hidden"></div>
      <div class="char-swap-preview online-gen-preview hidden" id="onlineGenPreview"><img alt="试生成结果" id="onlineGenPreviewImg" /></div>
      <div id="onlineRemixStatus" class="char-swap-msg online-remix-status" role="status"></div>
    </div>
  </section>`;
}

function selectOnlineSourceCandidate(candidate) {
  if (!candidate) return;
  onlineRemixState.candidateId = candidate.candidateId;
  onlineRemixState.imageIndex = candidate.imageIndex;
  onlineRemixState.slotIndex = candidate.slotIndex;
  document.querySelectorAll('[data-online-source-candidate]').forEach((button) => {
    button.classList.toggle('active', button.dataset.onlineSourceCandidate === candidate.candidateId);
  });
  const bar = document.getElementById('onlineSourceBar');
  if (bar) {
    const status = candidate.usable ? '可用' : '弱识别（仍可尝试换角）';
    bar.textContent = `源槽 p${candidate.imageIndex} · 槽位 ${candidate.slotIndex + 1} · ${candidate.label} · ${status}`;
    bar.className = `char-swap-source-bar active${candidate.usable ? '' : ' is-weak'}`;
  }
  syncOnlineAllSwapButtons();
}

function onlineSlotGender(candidate) {
  const tags = (candidate.identityTags || []).map((tag) => String(tag).toLowerCase());
  if (tags.some((tag) => tag === '1girl' || tag === 'female_focus' || tag === 'girls_only')) return 'female';
  if (tags.some((tag) => tag === '1boy' || tag === 'male_focus' || tag === 'boys_only')) return 'male';
  if (candidate.role === 'female' || candidate.role === 'male') return candidate.role;
  return 'unknown';
}

// 在线源槽渲染为与本地换角一致的槽位行（#编号 + 身份/外观 + 行内动作按钮）
function renderOnlineSourceCandidateButtons() {
  const host = document.getElementById('onlineSourceCandidates');
  if (!host || !onlineRemixState.data) return;
  const imageIndex = Number(document.getElementById('onlineSourceImage')?.value || 0);
  const candidates = onlineCharacterCandidates(onlineRemixState.data)
    .filter((candidate) => candidate.imageIndex === imageIndex);
  const countEl = document.getElementById('onlineCandidateCount');
  const all = onlineCharacterCandidates(onlineRemixState.data);
  if (countEl) {
    const usableAll = all.filter((item) => item.usable).length;
    const draftN = Object.keys(onlineRemixState.pageDrafts || {}).length;
    countEl.textContent = draftN
      ? `可用 ${usableAll}/${all.length} · 已换 ${draftN} 页`
      : `可用 ${usableAll}/${all.length}`;
  }
  document.querySelectorAll('#onlinePageTabs .online-page-tab').forEach((tab) => {
    tab.classList.toggle('active', Number(tab.dataset.onlinePage) === imageIndex);
  });
  if (!candidates.length) {
    host.innerHTML = '<div class="char-swap-preset-empty online-candidate-empty">这张图没有独立 V4 角色槽；请切换其他图片。</div>';
    onlineRemixState.candidateId = '';
    onlineRemixState.imageIndex = imageIndex;
    onlineRemixState.slotIndex = 0;
    const bar = document.getElementById('onlineSourceBar');
    if (bar) {
      bar.className = 'char-swap-source-bar empty';
      bar.textContent = '当前图无可换角色槽';
    }
    return;
  }
  const preferred = candidates.find((item) => item.usable) || candidates[0];
  host.innerHTML = '';

  const copyCandidateTags = async (candidate) => {
    const text = [candidate.identityTags.join(', '), candidate.caption].filter(Boolean).join('\n');
    try {
      await navigator.clipboard.writeText(text || candidate.label);
      const status = document.getElementById('onlineTargetStatus');
      if (status) status.textContent = `已复制槽位 #${candidate.slotIndex + 1} 的角色 tag。`;
    } catch (error) {
      const status = document.getElementById('onlineTargetStatus');
      if (status) status.textContent = '复制失败：浏览器拦截了剪贴板，请手动全选复制。';
      console.warn('copy online candidate tags failed', error);
    }
  };

  // 一键换角：当前槽 + 已选同性别目标（否则在该性别前 6 个可用目标里随机）
  const quickGenderSwap = async (candidate, gender) => {
    selectOnlineSourceCandidate(candidate);
    onlineRemixState.genderFilter = gender;
    const queryInput = document.getElementById('onlineTargetQuery');
    if (queryInput) queryInput.value = '';
    const status = document.getElementById('onlineTargetStatus');
    if (!onlineRemixState.targetCache.length) {
      if (status) status.textContent = '正在读取角色库…';
      await searchOnlineRemixTargets();
    }
    renderOnlineTargetResults(onlineRemixState.targetCache);
    const matching = (onlineRemixState.targetCache || []).filter(
      (item) => item.usable && onlineItemGender(item) === gender
    );
    if (!matching.length) {
      if (status) status.textContent = `角色库里没有可用的${gender === 'male' ? '男' : '女'}角色目标，请手动搜索。`;
      document.getElementById('onlineTargetResults')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }
    const selected = matching.find(
      (item) => String(item.reference_id || '') === String(onlineRemixState.targetReferenceId || '')
    );
    const pool = matching.slice(0, 6);
    const item = selected || pool[Math.floor(Math.random() * pool.length)];
    await applyOnlineTargetItem(item);
  };

  const applyOnlineSelectedTargetToSlot = async (candidate) => {
    selectOnlineSourceCandidate(candidate);
    const status = document.getElementById('onlineTargetStatus');
    if (!onlineRemixState.targetReferenceId) {
      if (status) status.textContent = '先在下方点一个角色，再点这一行的「替换」。';
      document.getElementById('onlineTargetResults')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      document.getElementById('onlineTargetQuery')?.focus({ preventScroll: true });
      return;
    }
    await createOnlineStudioDraft({ replaceCharacter: true });
  };

  candidates.forEach((candidate) => {
    const gender = onlineSlotGender(candidate);
    const genderClass = gender === 'female' ? 'female' : gender === 'male' ? 'male' : 'unknown';
    const genderText = gender === 'female' ? '♀ 女' : gender === 'male' ? '♂ 男' : '?';
    const genderBadgeHtml = `<span class="char-swap-gender-badge ${genderClass}">${genderText}</span>`;
    const override = onlineSlotOverride(imageIndex, candidate.slotIndex);
    const originalHint = candidate.identityTags
        .filter((tag) => !/^(1girl|1boy|female_focus|male_focus|girls_only|boys_only|solo)$/i.test(String(tag)))
        .slice(0, 5).join(', ')
      || candidate.label
      || candidate.caption.slice(0, 72)
      || '无身份 tag';
    // After replace: show target name + "已换" so the user sees the swap immediately.
    const identityHint = override
      ? override.label
      : originalHint;
    const appearanceHint = override
      ? (override.captionPreview || `原：${originalHint}`.slice(0, 72))
      : candidate.appearanceTags.slice(0, 6).join(', ');
    const row = document.createElement('div');
    row.className = `char-swap-slot online-source-slot${candidate.usable ? '' : ' is-weak'}${override ? ' is-swapped' : ''}`;
    row.dataset.onlineSourceCandidate = candidate.candidateId;
    row.dataset.slotIndex = String(candidate.slotIndex);
    row.dataset.imageIndex = String(imageIndex);
    row.innerHTML = `
      <span class="char-swap-slot-label">#${candidate.slotIndex + 1}</span>
      <span class="char-swap-slot-summary">
        <span class="char-swap-tag-role">${escapeHtml(identityHint)}${override ? ' <span class="online-slot-swapped">已换</span>' : ''}</span>
        ${appearanceHint ? `<span class="char-swap-tag-meta char-swap-tag-appearance">${genderBadgeHtml}${escapeHtml(appearanceHint)}</span>` : genderBadgeHtml}
      </span>
      <span class="online-slot-usable">${override ? '<span class="char-swap-badge online-usable-badge is-usable">已替换</span>' : onlineUsableBadge(candidate.usable)}</span>
      <div class="char-swap-actions"></div>`;
    const actions = row.querySelector('.char-swap-actions');
    const mk = (label, fn, primary = false) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `char-swap-btn${primary ? ' primary' : ''}`;
      button.textContent = label;
      button.addEventListener('click', (event) => {
        event.stopPropagation();
        fn();
      });
      actions.appendChild(button);
      return button;
    };
    // Compact actions — same density as local char-swap slot rows.
    mk('♂', () => quickGenderSwap(candidate, 'male')).title = '换男角';
    mk('♀', () => quickGenderSwap(candidate, 'female')).title = '换女角';
    mk('替换', () => applyOnlineSelectedTargetToSlot(candidate), true);
    mk('复制', () => copyCandidateTags(candidate));
    row.addEventListener('click', () => selectOnlineSourceCandidate(candidate));
    host.appendChild(row);
  });
  const keep = candidates.find((item) => item.candidateId === onlineRemixState.candidateId)
    || candidates.find((item) => onlineSlotOverride(imageIndex, item.slotIndex))
    || preferred;
  selectOnlineSourceCandidate(keep);
}

function onlineTargetCaption(item = {}) {
  const raw = item.raw && typeof item.raw === 'object' ? item.raw : {};
  return String(
    item.char_caption
    || item.character_caption
    || raw.char_caption
    || raw.character_caption
    || ''
  ).trim();
}

function onlineItemGender(item = {}) {
  const raw = item.raw && typeof item.raw === 'object' ? item.raw : {};
  const identity = [
    ...(Array.isArray(item.identity) ? item.identity : []),
    ...(Array.isArray(raw.identity) ? raw.identity : []),
    ...(Array.isArray(item.core_tags) ? item.core_tags : []),
  ].map((tag) => String(tag).toLowerCase());
  const itemGender = String(item.gender || raw.gender || '').toLowerCase();
  if (itemGender === 'male' || identity.includes('1boy') || identity.includes('male_focus')) return 'male';
  if (itemGender === 'female' || identity.includes('1girl') || identity.includes('female_focus')) return 'female';
  return '';
}

function onlineReferenceLabel(item = {}) {
  const raw = item.raw && typeof item.raw === 'object' ? item.raw : {};
  const mine = item.is_custom || item.source === 'custom' || String(item.source || '').includes('我的')
    ? '我的 OC · '
    : '';
  const label = String(item.label || item.name || raw.name || raw.character || raw.trigger || item.reference_id || '未命名角色');
  const caption = onlineTargetCaption(item);
  const identity = uniqueTagList([
    ...(Array.isArray(item.identity) ? item.identity : []),
    ...(Array.isArray(raw.identity) ? raw.identity : []),
    ...(Array.isArray(item.core_tags) ? item.core_tags : []),
  ]);
  const isOc = String(item.kind || '').toLowerCase() === 'oc'
    || item.is_custom
    || item.source === 'custom'
    || String(item.source || '').includes('我的');
  if (isOc) {
    const hint = caption
      ? `${caption.slice(0, 48)}${caption.length > 48 ? '…' : ''}`
      : identity.join(', ');
    return `${mine}${label} · OC · ${hint || '自定义特征'}`;
  }
  if (identity.length) return `${mine}${label} — ${identity.join(', ')}`;
  return `${mine}${label}`;
}

function onlineTargetUsable(item = {}) {
  const raw = item.raw && typeof item.raw === 'object' ? item.raw : {};
  const identity = uniqueTagList([
    ...(Array.isArray(item.identity) ? item.identity : []),
    ...(Array.isArray(raw.identity) ? raw.identity : []),
    ...(Array.isArray(item.core_tags) ? item.core_tags : []),
  ]);
  const caption = onlineTargetCaption(item);
  const trigger = String(item.trigger || raw.trigger || '').trim();
  const namedIdentity = identity.some((tag) => !/^(1girl|1boy|female_focus|male_focus|original_character)$/i.test(tag));
  return namedIdentity || caption.length >= 8 || !!trigger;
}

function selectOnlineTarget(item) {
  if (!item) return;
  onlineRemixState.targetReferenceId = String(item.reference_id || '');
  onlineRemixState.targetLabel = onlineReferenceLabel(item);
  document.querySelectorAll('#onlineTargetResults [data-online-target-reference]').forEach((element) => {
    element.classList.toggle('active', element.dataset.onlineTargetReference === onlineRemixState.targetReferenceId);
  });
  syncOnlineAllSwapButtons();
}

async function applyOnlineTargetItem(item) {
  const status = document.getElementById('onlineTargetStatus');
  if (!item || !onlineTargetUsable(item)) {
    if (status) status.textContent = '该角色缺少可用身份 tag / OC 特征，请换一个可用角色。';
    return;
  }
  selectOnlineTarget(item);
  if (status) status.textContent = `正在换上：${onlineRemixState.targetLabel}…`;
  await createOnlineStudioDraft({ replaceCharacter: true });
}

function renderOnlineTargetResults(items) {
  const results = document.getElementById('onlineTargetResults');
  const status = document.getElementById('onlineTargetStatus');
  if (!results || !status) return;
  const onlyCustom = !!onlineRemixState.onlyCustomTargets;
  const genderFilter = String(onlineRemixState.genderFilter || '');
  const query = String(document.getElementById('onlineTargetQuery')?.value || '').trim().toLowerCase();
  const filtered = (items || []).filter((item) => {
    if (onlyCustom && !(item.is_custom || item.source === 'custom' || String(item.source || '').includes('我的'))) {
      return false;
    }
    if (genderFilter) {
      const itemGender = onlineItemGender(item);
      if (genderFilter === 'male' && itemGender !== 'male') return false;
      if (genderFilter === 'female' && itemGender !== 'female') return false;
    }
    if (!query) return true;
    return [
      item.label,
      item.name,
      item.id,
      item.reference_id,
      item.char_caption,
      ...(item.identity || []),
      item.source,
    ].some((value) => String(value || '').toLowerCase().includes(query));
  });
  // Prefer usable targets first so available characters are easy to spot.
  filtered.sort((a, b) => Number(!!b.usable) - Number(!!a.usable));
  if (!filtered.length) {
    results.innerHTML = `<div class="char-swap-preset-empty">${onlyCustom ? '还没有匹配的自定义 OC。' : `未找到匹配角色“${escapeHtml(query || '')}”`}</div>`;
    status.textContent = onlyCustom ? '我的 OC 中没有匹配项。' : '初始库与本地角色库都没有匹配项。';
    return;
  }
  const usableCount = filtered.filter((item) => item.usable).length;
  results.innerHTML = filtered.map((item) => {
    const id = String(item.reference_id || '');
    const source = String(item.source || item.raw?.source || '本地角色');
    const weakClass = item.usable ? '' : ' is-weak';
    const hint = item.usable ? '' : ' · 缺少身份 tag，点此查看原因';
    return `<button type="button" class="char-swap-btn char-swap-preset online-target-item${weakClass}" data-online-target-reference="${escapeHtml(id)}" data-usable="${item.usable ? '1' : '0'}" aria-disabled="${item.usable ? 'false' : 'true'}" title="${item.usable ? '点此换到当前槽' : '缺少身份 tag / OC 特征'}">
      <span class="online-target-item-top">
        <b>${escapeHtml(onlineReferenceLabel(item))}</b>
        ${onlineUsableBadge(item.usable)}
      </span>
      <span class="online-target-item-meta">${escapeHtml(source)}${hint}</span>
    </button>`;
  }).join('');
  results.querySelectorAll('[data-online-target-reference]').forEach((button) => button.addEventListener('click', () => {
    const item = filtered.find((candidate) => String(candidate.reference_id || '') === button.dataset.onlineTargetReference);
    if (!item) return;
    if (!item.usable) {
      status.textContent = '该角色缺少可用身份 tag / OC 特征，请换一个可用角色。';
      return;
    }
    Promise.resolve(applyOnlineTargetItem(item)).catch((err) => reportAsyncError('换角失败', err));
  }));
  status.textContent = `找到 ${filtered.length} 个角色（可用 ${usableCount}）。点角色卡即换到当前槽。`;
}

// 常用角色一键替换芯片（与本地换角 quick-presets 同一行样式）
function renderOnlineQuickChips() {
  const row = document.getElementById('onlineQuickSwapRow');
  if (!row) return;
  const cache = Array.isArray(onlineRemixState.targetCache) ? onlineRemixState.targetCache : [];
  const presets = cache.filter((item) => item.usable && String(item.source || '').includes('内置常用角色'));
  const genderOf = (item) => {
    const tags = (Array.isArray(item.identity) ? item.identity : []).map((tag) => String(tag).toLowerCase());
    if (String(item.gender || '').toLowerCase() === 'male' || tags.includes('1boy')) return 'male';
    return 'female';
  };
  const females = presets.filter((item) => genderOf(item) === 'female').slice(0, 3);
  const males = presets.filter((item) => genderOf(item) === 'male').slice(0, 2);
  const picks = [...females, ...males];
  row.innerHTML = '<span>⚡ 常用角色：</span>';
  if (!picks.length) {
    const empty = document.createElement('span');
    empty.className = 'online-quick-empty';
    empty.textContent = '加载中…';
    row.appendChild(empty);
    return;
  }
  picks.forEach((item) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'char-swap-btn primary online-quick-chip';
    const icon = genderOf(item) === 'male' ? '♂' : '♀';
    chip.textContent = `${icon} ${String(item.label || item.name || item.id || '角色')}`;
    chip.title = '一键替换为 ' + onlineReferenceLabel(item);
    chip.addEventListener('click', async () => {
      selectOnlineTarget(item);
      const status = document.getElementById('onlineTargetStatus');
      if (status) status.textContent = `一键：${onlineRemixState.targetLabel}`;
      await createOnlineStudioDraft({ replaceCharacter: true });
    });
    row.appendChild(chip);
  });
}

/** Return work_id for generate API: string digits keep full precision for Python int(). */
function onlineWorkIdForGenerate() {
  const raw = String(onlineRemixState.workId || '').trim();
  if (/^\d+$/.test(raw) && raw !== '0') return raw;
  return null;
}

function onlineNumericWorkId() {
  const raw = onlineWorkIdForGenerate();
  if (!raw) return null;
  try {
    if (raw.length <= 15) {
      const n = Number(raw);
      if (Number.isSafeInteger(n) && n > 0) return n;
    }
  } catch { /* fall through */ }
  return null;
}

function onlineDraftComment(entry) {
  if (!entry) return null;
  const draft = entry.draft || entry;
  if (draft && typeof draft === 'object' && draft.comment && typeof draft.comment === 'object') {
    return draft.comment;
  }
  // Studio form may already be a NAI comment (prompt / v4_prompt).
  if (draft && typeof draft === 'object' && (draft.prompt != null || draft.v4_prompt)) {
    return draft;
  }
  return null;
}

function onlineCurrentImageIndex() {
  const fromSelect = Number(document.getElementById('onlineSourceImage')?.value);
  if (Number.isFinite(fromSelect)) return fromSelect;
  return Number(onlineRemixState.imageIndex || 0);
}

function onlinePageDraftKey(imageIndex) {
  return `p${Number(imageIndex) || 0}`;
}

function onlineGetPageDraft(imageIndex) {
  return onlineRemixState.pageDrafts[onlinePageDraftKey(imageIndex)] || null;
}

/** Collect stacked base comments for draft API. */
function onlineCollectBaseComments(imageIndexes) {
  const out = {};
  const indexes = Array.isArray(imageIndexes) && imageIndexes.length
    ? imageIndexes
    : Object.keys(onlineRemixState.pageDrafts || {}).map((k) => Number(String(k).replace(/^p/, '')));
  indexes.forEach((idx) => {
    const entry = onlineGetPageDraft(idx);
    const comment = onlineDraftComment(entry);
    if (comment) out[String(idx)] = comment;
  });
  return out;
}

function onlineClearSlotOverridesForPages(imageIndexes) {
  const set = new Set((imageIndexes || []).map((i) => Number(i)));
  Object.keys(onlineRemixState.slotOverrides || {}).forEach((key) => {
    const pi = Number(String(key).split(':')[0]);
    if (set.has(pi)) delete onlineRemixState.slotOverrides[key];
  });
}

function syncOnlineGenerateButtons() {
  const genBtn = document.getElementById('onlineGenerateBtn');
  const allBtn = document.getElementById('onlineGenerateAllBtn');
  const keys = Object.keys(onlineRemixState.pageDrafts || {});
  const currentKey = onlinePageDraftKey(onlineCurrentImageIndex());
  // Enable only when the currently viewed page has a draft (match generate path).
  const hasCurrent = !!onlineRemixState.pageDrafts[currentKey];
  if (genBtn) {
    genBtn.disabled = !hasCurrent || onlineRemixState.generating;
    genBtn.textContent = onlineRemixState.generating ? '生图中…' : '单张试生成 ▶';
  }
  if (allBtn) {
    allBtn.disabled = keys.length === 0 || onlineRemixState.generating;
    allBtn.textContent = keys.length > 1
      ? `生成已换页 (${keys.length})`
      : (keys.length === 1 ? '生成已换页' : '生成已换页');
  }
  const countEl = document.getElementById('onlineCandidateCount');
  if (countEl && onlineRemixState.data) {
    const all = onlineCharacterCandidates(onlineRemixState.data);
    const usableAll = all.filter((item) => item.usable).length;
    const swapN = Object.keys(onlineRemixState.slotOverrides || {}).length;
    countEl.textContent = keys.length
      ? `可用 ${usableAll}/${all.length} · 草稿 ${keys.length} 页${swapN ? ` · 已换 ${swapN} 槽` : ''}`
      : `可用 ${usableAll}/${all.length}`;
  }
}

function rememberOnlineDraft(result, replaceCharacter, studioUrl, extra = {}) {
  const imageIndex = Number(
    result?.image_index ?? onlineRemixState.imageIndex ?? 0
  );
  const key = onlinePageDraftKey(imageIndex);
  const label = extra.label
    || (replaceCharacter
      ? (onlineRemixState.targetLabel || `槽#${onlineRemixState.slotIndex + 1}`)
      : (extra.styleOnly ? '画风' : '原图'));
  onlineRemixState.pageDrafts[key] = {
    draft: result.draft,
    imageIndex,
    label,
    studioUrl: String(studioUrl || '/studio?aitag=1&remix=1'),
    replaceCharacter: !!replaceCharacter,
    styleOnly: !!extra.styleOnly,
  };
  onlineRemixState.lastDraftKey = key;
  syncOnlineGenerateButtons();
}

async function generateOnlineDraftEntry(entry, { quiet = false } = {}) {
  const comment = onlineDraftComment(entry);
  if (!comment) throw new Error('草稿不完整，请先应用换角');
  if (!window.ApiClient) throw new Error('ApiClient 未加载');
  if (onlineRemixState.drafting) throw new Error('草稿仍在写入，请稍候再生成');
  const workIdStr = onlineWorkIdForGenerate();
  const workIdNum = onlineNumericWorkId();
  const workMeta = (onlineRemixState.data && onlineRemixState.data.work) || {};
  const images = Array.isArray(onlineRemixState.data?.images) ? onlineRemixState.data.images : [];
  const pageIdx = Number(entry.imageIndex || 0);
  const pageImg = images[pageIdx] || images[0] || {};
  const sourceTitle = String(workMeta.title || workMeta.Title || '').trim();
  const sourceThumb = String(
    pageImg.thumbnail_url || pageImg.thumb_url || pageImg.url || workMeta.thumbnail_url || ''
  ).trim();
  const snapshot = (typeof structuredClone === 'function')
    ? structuredClone(comment)
    : JSON.parse(JSON.stringify(comment));
  if (snapshot && typeof snapshot === 'object') {
    snapshot._aitag_source = {
      work_id: workIdStr || '',
      page_index: pageIdx,
      title: sourceTitle,
      thumb: sourceThumb,
    };
  }
  const res = await window.ApiClient.request('/api/nai/generate', {
    method: 'POST',
    body: {
      patched_comment: snapshot,
      work_id: workIdNum != null ? workIdNum : (workIdStr || null),
      work_id_str: workIdStr || '',
      remote_work_id: workIdStr || '',
      source_gallery_id: 'aitag-online',
      source_title: sourceTitle,
      source_thumb: sourceThumb,
      page_index: pageIdx,
      copies: 1,
      force_free: true,
      prompt_profile: 'native',
    },
    timeoutMs: 60000,
  });
  if (!res?.ok) {
    throw new Error(res?.message || res?.detail || res?.error || '生图失败');
  }
  const taskId = res.task_id || (res.batch && res.batch.task_id) || '';
  if (!taskId) throw new Error('未返回生成任务 ID');
  const job = await window.ApiClient.pollJob(taskId);
  if (String(job.status || '') === 'unknown') {
    throw new Error(job.message || '这次可能已扣费，不要自动重试；要重出请再确认。');
  }
  const items = Array.isArray(job.items) ? job.items : [];
  const lastOk = [...items].reverse().find((item) => item && item.ok && (item.image_url || item.gallery_url));
  if (!lastOk) throw new Error(job.message || '生图失败');
  const shaped = {
    ok: true,
    image_url: lastOk.image_url || '',
    gallery_url: lastOk.gallery_url || job.gallery_url || '',
    message: lastOk.message || job.message || '完成',
    task_id: taskId,
    free_eligible: lastOk.free_eligible,
  };
  if (!quiet) {
    const preview = document.getElementById('onlineGenPreview');
    const img = document.getElementById('onlineGenPreviewImg');
    if (preview && img && shaped.image_url) {
      img.src = `${shaped.image_url}${shaped.image_url.includes('?') ? '&' : '?'}t=${Date.now()}`;
      preview.classList.remove('hidden');
    }
  }
  return shaped;
}

async function generateOnlineCurrentDraft() {
  const status = document.getElementById('onlineRemixStatus');
  if (onlineRemixState.drafting) {
    if (status) status.textContent = '草稿仍在写入，请稍候再生成。';
    return;
  }
  // Only generate the page the user is currently viewing (no lastDraftKey fallback).
  const currentKey = onlinePageDraftKey(onlineCurrentImageIndex());
  const entry = onlineRemixState.pageDrafts[currentKey] || null;
  if (!entry) {
    if (status) status.textContent = '当前页没有草稿，请先对本页应用换角或建立原图草稿。';
    return;
  }
  onlineRemixState.lastDraftKey = onlinePageDraftKey(entry.imageIndex);
  if (onlineRemixState.generating) return;
  try {
    const naiStatus = await window.ApiClient.request('/api/nai/status');
    if (!naiStatus?.has_token) {
      if (status) status.textContent = '未配置 NAI Token，请到设置页添加后再生成。';
      return;
    }
  } catch (error) {
    if (status) status.textContent = `NAI 状态读取失败：${error.message || error}`;
    return;
  }
  if (!window.confirm(`试生成当前草稿（p${entry.imageIndex} · ${entry.label}）？\n与本地图库换角相同：调用 NAI，原作品不变。`)) {
    return;
  }
  onlineRemixState.generating = true;
  syncOnlineGenerateButtons();
  if (status) status.textContent = `生图中 p${entry.imageIndex}…（约 15–40 秒）`;
  try {
    const res = await generateOnlineDraftEntry(entry);
    const link = res.gallery_url
      ? ` · <a href="${escapeHtml(res.gallery_url)}" target="_blank" rel="noopener">打开生成结果</a>`
      : ' · <a href="/generated" target="_blank" rel="noopener">生成库</a>';
    if (status) {
      status.innerHTML = `${escapeHtml(res.message || '完成')}${link}`;
      status.classList.add('ok');
    }
  } catch (error) {
    if (status) {
      status.textContent = `生图失败：${error.message || error}`;
      status.classList.remove('ok');
    }
  } finally {
    onlineRemixState.generating = false;
    syncOnlineGenerateButtons();
  }
}

async function generateOnlineAllDrafts() {
  const status = document.getElementById('onlineRemixStatus');
  if (onlineRemixState.drafting) {
    if (status) status.textContent = '草稿仍在写入，请稍候再生成。';
    return;
  }
  const entries = Object.values(onlineRemixState.pageDrafts || {})
    .sort((a, b) => Number(a.imageIndex) - Number(b.imageIndex));
  if (!entries.length) {
    if (status) status.textContent = '还没有已换角草稿。先对每页应用换角。';
    return;
  }
  if (onlineRemixState.generating) return;
  try {
    const naiStatus = await window.ApiClient.request('/api/nai/status');
    if (!naiStatus?.has_token) {
      if (status) status.textContent = '未配置 NAI Token，请到设置页添加后再生成。';
      return;
    }
  } catch (error) {
    if (status) status.textContent = `NAI 状态读取失败：${error.message || error}`;
    return;
  }
  if (!window.confirm(`批量生成 ${entries.length} 张已换角草稿？\n顺序与本地批量一致，原作品不变。`)) {
    return;
  }
  onlineRemixState.generating = true;
  syncOnlineGenerateButtons();
  let ok = 0;
  let lastUrl = '';
  try {
    for (let i = 0; i < entries.length; i += 1) {
      const entry = entries[i];
      if (status) status.textContent = `批量生图 ${i + 1}/${entries.length} · p${entry.imageIndex}…`;
      const res = await generateOnlineDraftEntry(entry, { quiet: i < entries.length - 1 });
      ok += 1;
      if (res.image_url) lastUrl = res.image_url;
    }
    if (lastUrl) {
      const preview = document.getElementById('onlineGenPreview');
      const img = document.getElementById('onlineGenPreviewImg');
      if (preview && img) {
        img.src = `${lastUrl}${lastUrl.includes('?') ? '&' : '?'}t=${Date.now()}`;
        preview.classList.remove('hidden');
      }
    }
    if (status) {
      status.innerHTML = `已生成 ${ok}/${entries.length} 张 · <a href="/generated" target="_blank" rel="noopener">打开生成库</a>`;
      status.classList.add('ok');
    }
  } catch (error) {
    if (status) {
      status.textContent = `批量生图中断（已完成 ${ok}/${entries.length}）：${error.message || error}`;
      status.classList.remove('ok');
    }
  } finally {
    onlineRemixState.generating = false;
    syncOnlineGenerateButtons();
  }
}

let onlineTargetSearchGen = 0;

async function searchOnlineRemixTargets() {
  const results = document.getElementById('onlineTargetResults');
  const status = document.getElementById('onlineTargetStatus');
  const query = String(document.getElementById('onlineTargetQuery')?.value || '').trim();
  if (!results || !status || !window.ApiClient) return;
  const searchGen = ++onlineTargetSearchGen;
  status.textContent = '正在读取内置初始库与本地角色库（与本地换角相同数据源）…';
  try {
    const params = new URLSearchParams({ limit: '24', offset: '0' });
    if (query) params.set('q', query);
    const libraryParams = new URLSearchParams({ limit: '40' });
    if (query) libraryParams.set('q', query);
    const [payload, femalePresets, malePresets, femaleLibrary, maleLibrary] = await Promise.all([
      window.ApiClient.request(`/api/nai/references?${params}`),
      window.ApiClient.request('/api/plugin/char-swap/presets?gender=female'),
      window.ApiClient.request('/api/plugin/char-swap/presets?gender=male'),
      window.ApiClient.request(`/api/plugin/char-swap/ark-library?gender=female&${libraryParams}`),
      window.ApiClient.request(`/api/plugin/char-swap/ark-library?gender=male&${libraryParams}`),
    ]);
    const needle = query.toLowerCase();
    const presetItems = [
      ...(Array.isArray(femalePresets.presets) ? femalePresets.presets : []),
      ...(Array.isArray(malePresets.presets) ? malePresets.presets : []),
    ].filter((item) => !needle || [item.id, item.label, ...(item.identity || []), item.char_caption]
      .some((value) => String(value || '').toLowerCase().includes(needle)))
      .map((item) => ({
        ...item,
        reference_id: `preset:${item.gender === 'male' ? 'male' : 'female'}:${item.id}`,
        source: item.is_custom || item.source === 'custom' ? '我的 OC' : '内置常用角色',
        is_custom: !!(item.is_custom || item.source === 'custom'),
      }));
    const libraryItems = [
      ...(Array.isArray(femaleLibrary.items) ? femaleLibrary.items : []),
      ...(Array.isArray(maleLibrary.items) ? maleLibrary.items : []),
    ].map((item) => ({
      ...item,
      reference_id: `ark:${item.gender === 'male' ? 'male' : 'female'}:${item.id}`,
      source: '内置角色库',
      identity: item.identity || [item.tag || `${item.id}_(arknights)`].filter(Boolean),
    }));
    const localItems = (Array.isArray(payload.items) ? payload.items : []).map((item) => ({
      ...item,
      source: item.source || item.raw?.source || '本地角色',
      is_custom: !!(item.is_custom || item.source === 'custom'),
      char_caption: String(item.char_caption || item.character_caption || item.raw?.char_caption || '').trim(),
      kind: item.kind || ((item.is_custom || item.source === 'custom') && (item.char_caption || item.character_caption) ? 'oc' : item.kind),
    }));
    const seen = new Set();
    const items = [...presetItems, ...localItems, ...libraryItems].filter((item) => {
      const id = String(item.reference_id || '');
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    }).map((item) => ({
      ...item,
      usable: onlineTargetUsable(item),
    })).slice(0, 80);
    if (searchGen !== onlineTargetSearchGen) return;
    onlineRemixState.targetCache = items;
    renderOnlineTargetResults(items);
    renderOnlineQuickChips();
  } catch (error) {
    if (searchGen !== onlineTargetSearchGen) return;
    status.textContent = `目标角色读取失败：${error.message || error}`;
  }
}

function onlineDraftCharLines(draft) {
  const caps = draft?.texts?.char_captions;
  if (!Array.isArray(caps)) return [];
  return caps
    .map((c) => (typeof c === 'string' ? c : String((c && (c.char_caption || c.caption)) || '')))
    .filter(Boolean);
}

function rememberOnlineDraftPages(result, label, studioUrl, { replaceCharacter = false, styleOnly = false } = {}) {
  const pages = Array.isArray(result?.pages) && result.pages.length
    ? result.pages
    : (result?.draft ? [result] : []);
  const touched = [];
  pages.forEach((page) => {
    const imageIndex = Number(page.image_index ?? page.draft?.pageIndex ?? 0);
    touched.push(imageIndex);
    const key = onlinePageDraftKey(imageIndex);
    const prev = onlineRemixState.pageDrafts[key];
    onlineRemixState.pageDrafts[key] = {
      draft: page.draft || page,
      imageIndex,
      label: label || (replaceCharacter ? onlineRemixState.targetLabel : (styleOnly ? '画风' : '原图')),
      studioUrl: String(studioUrl || '/studio?aitag=1&remix=1'),
      replaceCharacter: !!replaceCharacter || !!(prev && prev.replaceCharacter),
      styleOnly: !!styleOnly,
    };
  });
  // Keep lastDraftKey on the currently viewed page when possible.
  const currentKey = onlinePageDraftKey(onlineCurrentImageIndex());
  if (onlineRemixState.pageDrafts[currentKey]) {
    onlineRemixState.lastDraftKey = currentKey;
  } else if (touched.length) {
    onlineRemixState.lastDraftKey = onlinePageDraftKey(touched[0]);
  }
  syncOnlineGenerateButtons();
  return pages.length;
}

// 现场展示替换结果：可直接试生成（与本地换角同一路径）
function showOnlineRemixResult(result, replaceCharacter, studioUrl, extra = {}) {
  const host = document.getElementById('onlineRemixResult');
  if (!host) return;
  const styleOnly = !!extra.styleOnly;
  const label = extra.label
    || (replaceCharacter ? onlineRemixState.targetLabel : (styleOnly ? '画风替换' : '原图'));
  const stored = rememberOnlineDraftPages(result, label, studioUrl, { replaceCharacter, styleOnly });
  // Keep legacy single-page remember for current image highlight.
  if (result?.draft && !Array.isArray(result.pages)) {
    rememberOnlineDraft(result, replaceCharacter, studioUrl);
  }
  // Record slot overrides BEFORE re-render so rows show the new character.
  const overrideCount = recordOnlineSlotOverridesFromResult(result, label, {
    replaceCharacter,
    replaceAllSlotsOnPage: !!(extra.genderScope || extra.allPages),
  });
  try {
    renderOnlineSourceCandidateButtons();
  } catch (error) {
    console.warn('refresh online slots after replace failed', error);
  }
  // Mark page tabs that already have swapped slots.
  document.querySelectorAll('#onlinePageTabs .online-page-tab').forEach((tab) => {
    const pi = Number(tab.dataset.onlinePage);
    const hasSwap = Object.keys(onlineRemixState.slotOverrides || {}).some((key) => key.startsWith(`${pi}:`));
    tab.classList.toggle('has-swap', hasSwap);
  });
  const charLines = onlineDraftCharLines(result.draft);
  const pageN = Object.keys(onlineRemixState.pageDrafts).length;
  const slots = Array.isArray(result.slot_indexes) ? result.slot_indexes : [];
  const styleHits = Number(result.style_replacements || 0);
  let head;
  if (stored > 1) {
    head = replaceCharacter
      ? `已全部换角 ${stored} 页 → ${label}`
      : (styleOnly ? `画风已应用到 ${stored} 页` : `已建立 ${stored} 页草稿`);
  } else if (replaceCharacter) {
    head = `已换角 p${result.image_index ?? onlineRemixState.imageIndex} · 槽${slots.length ? slots.map((s) => `#${Number(s) + 1}`).join(',') : `#${onlineRemixState.slotIndex + 1}`} → ${label}`;
  } else if (styleOnly) {
    head = `画风已写回 p${result.image_index ?? onlineRemixState.imageIndex}${styleHits ? ` · ${styleHits} 处` : ''}`;
  } else {
    head = `原图草稿 p${result.image_index ?? onlineRemixState.imageIndex}`;
  }
  if (replaceCharacter && overrideCount) {
    head += ` · 槽位已更新 ${overrideCount}`;
  }
  const partial = !!extra.partial || !!(Array.isArray(result.failed_pages) && result.failed_pages.length);
  const badgeText = partial
    ? `部分成功 · 已存 ${pageN} 页`
    : `可生图 · 已存 ${pageN} 页`;
  host.innerHTML = `
    <div class="online-result-head">
      <strong>${escapeHtml(head)}</strong>
      <span class="online-result-badge${partial ? ' is-partial' : ''}">${escapeHtml(badgeText)}</span>
    </div>
    ${charLines.length ? `<pre class="online-result-prompt">${escapeHtml(charLines.slice(0, 4).join('\n'))}</pre>` : ''}
    <div class="online-result-actions">
      <button type="button" class="char-swap-btn primary" data-online-result-generate>单张试生成 ▶</button>
      <button type="button" class="char-swap-btn" data-online-result-generate-all ${pageN < 1 ? 'disabled' : ''}>生成已换页${pageN > 1 ? ` (${pageN})` : ''}</button>
      <button type="button" class="char-swap-btn" data-online-result-studio>Studio 微调</button>
      <button type="button" class="char-swap-btn" data-online-result-close>继续编辑</button>
    </div>`;
  host.classList.remove('hidden');
  host.querySelector('[data-online-result-generate]')?.addEventListener('click', () =>
    Promise.resolve(generateOnlineCurrentDraft()).catch((err) => reportAsyncError('试生成失败', err)));
  host.querySelector('[data-online-result-generate-all]')?.addEventListener('click', () =>
    Promise.resolve(generateOnlineAllDrafts()).catch((err) => reportAsyncError('批量生成失败', err)));
  host.querySelector('[data-online-result-studio]')?.addEventListener('click', () => {
    window.location.assign(studioUrl);
  });
  host.querySelector('[data-online-result-close]')?.addEventListener('click', () => {
    host.classList.add('hidden');
  });
}

function onlineStylePayloadFromForm() {
  const find = String(document.getElementById('onlineStyleFind')?.value || '').trim();
  const replace = String(document.getElementById('onlineStyleReplace')?.value || '');
  const mode = find ? 'replace' : 'append';
  if (!find && !String(replace).trim()) {
    throw new Error('请填写要替换/追加的画风，或选择画风预设');
  }
  return {
    style_find: find,
    style_replace: replace,
    style_mode: mode,
  };
}

async function loadOnlineStylePresets() {
  const select = document.getElementById('onlineStylePreset');
  if (!select || !window.ApiClient) return;
  try {
    const data = await window.ApiClient.request('/api/plugin/char-swap/style-presets');
    const presets = Array.isArray(data.presets) ? data.presets : [];
    select.innerHTML = '<option value="">画风预设…</option>' + presets.map((item) => {
      const id = String(item.id || item.label || '');
      const label = String(item.label || item.id || '未命名');
      const tag = String(item.tag || item.style || item.replace || item.combined || '').trim();
      return `<option value="${escapeHtml(id)}" data-style-tag="${escapeHtml(tag)}">${escapeHtml(label)}</option>`;
    }).join('');
    select.onchange = () => {
      const opt = select.selectedOptions && select.selectedOptions[0];
      if (!opt || !opt.value) return;
      const tag = opt.dataset.styleTag || '';
      const replaceInput = document.getElementById('onlineStyleReplace');
      if (replaceInput && tag) replaceInput.value = tag;
    };
  } catch (error) {
    select.innerHTML = '<option value="">画风预设加载失败</option>';
  }
}

async function createOnlineStudioDraft(options = {}) {
  const {
    replaceCharacter = false,
    allPages = false,
    genderScope = '',
    styleOnly = false,
    resetOriginal = false,
  } = options;
  const status = document.getElementById('onlineRemixStatus');
  if (!onlineRemixState.data || !onlineRemixState.workId || !window.ApiClient) return;
  if (onlineRemixState.drafting || onlineRemixState.generating) {
    if (status) status.textContent = '上一步还在处理，请稍候…';
    return;
  }
  if (replaceCharacter && !onlineRemixState.targetReferenceId) {
    if (status) status.textContent = '请先选择目标角色。';
    return;
  }
  const imageIndex = onlineCurrentImageIndex();
  onlineRemixState.imageIndex = imageIndex;
  const payload = {
    image_index: imageIndex,
    slot_index: Number(onlineRemixState.slotIndex || 0),
  };
  // all_pages / gender-scope must not pin to a single candidate slot.
  if (onlineRemixState.candidateId && !allPages && !genderScope) {
    payload.candidate_id = onlineRemixState.candidateId;
  }
  if (replaceCharacter) payload.target_reference_id = onlineRemixState.targetReferenceId;
  if (genderScope) payload.gender_scope = genderScope;
  if (allPages) payload.all_pages = true;
  if (styleOnly || options.withStyle) {
    try {
      Object.assign(payload, onlineStylePayloadFromForm());
    } catch (error) {
      if (status) status.textContent = error.message || String(error);
      return;
    }
  }

  // Stack on existing drafts so char → style / slotA → slotB accumulate.
  if (!resetOriginal) {
    if (allPages) {
      const images = Array.isArray(onlineRemixState.data?.images) ? onlineRemixState.data.images : [];
      const indexes = onlineImageArrayIndexes(images);
      const bases = onlineCollectBaseComments(indexes);
      if (Object.keys(bases).length) payload.base_comments = bases;
    } else {
      const existing = onlineDraftComment(onlineGetPageDraft(imageIndex));
      if (existing) payload.base_comment = existing;
    }
  } else {
    // 原图草稿：clear stacked state for target page(s).
    if (allPages) {
      onlineRemixState.pageDrafts = {};
      onlineRemixState.slotOverrides = {};
    } else {
      delete onlineRemixState.pageDrafts[onlinePageDraftKey(imageIndex)];
      onlineClearSlotOverridesForPages([imageIndex]);
    }
  }

  const actionLabel = styleOnly
    ? (allPages ? '全部图片画风' : '画风')
    : (allPages
      ? `全部图片${genderScope === 'male' ? '男' : genderScope === 'female' ? '女' : ''}角`
      : (replaceCharacter ? '换角' : (resetOriginal ? '原图' : '草稿')));
  if (status) status.textContent = `正在建立${actionLabel}草稿…`;
  onlineRemixState.drafting = true;
  syncOnlineAllSwapButtons();
  try {
    const result = await window.ApiClient.request(`/api/nai/aitag/work/${encodeURIComponent(onlineRemixState.workId)}/draft`, {
      method: 'POST', body: payload, timeoutMs: 120000,
    });
    if (!result?.draft || Number(result.generation_calls) !== 0) throw new Error('在线草稿未通过零生成安全检查');
    // Persist multi-page package in localStorage for Studio / tab recovery.
    // Never fail the whole flow if quota is exceeded — server draft already exists.
    const pagePack = Array.isArray(result.pages)
      ? result.pages.map((p) => ({
        image_index: p.image_index,
        slot_indexes: p.slot_indexes || [],
        draft: p.draft,
      })).filter((p) => p.draft)
      : [];
    try {
      localStorage.setItem(ONLINE_DRAFT_KEY, JSON.stringify({
        ...result.draft,
        draftId: String(result.draft_id || ''),
        recipe: result.recipe,
        sourceKind: 'aitag-online',
        generationCalls: 0,
        pages: pagePack,
        partial: !!result.partial,
        failed_pages: result.failed_pages || result.errors || [],
        onlineReference: {
          workId: onlineRemixState.workId,
          imageIndex: payload.image_index,
          sourceCandidateId: (!allPages && !genderScope) ? onlineRemixState.candidateId : '',
          targetReferenceId: replaceCharacter ? onlineRemixState.targetReferenceId : '',
          genderScope: genderScope || '',
          allPages: !!allPages,
          styleOnly: !!styleOnly,
        },
      }));
    } catch (storageError) {
      console.warn('online draft localStorage save failed', storageError);
      if (status) {
        status.textContent = `${status.textContent || '草稿已就绪'} · 本地缓存已满，服务端草稿仍可用`;
        status.classList.add('warn');
      }
    }
    if (status) {
      const partial = !!result.partial
        || (Array.isArray(result.failed_pages) && result.failed_pages.length)
        || (Array.isArray(result.errors) && result.errors.length);
      const failList = result.failed_pages || result.errors || [];
      const errPages = partial && failList.length
        ? ` · 失败：${failList.slice(0, 3).join('；')}`
        : '';
      let styleHits = Number(result.style_replacements || 0);
      if (allPages && Array.isArray(result.pages)) {
        styleHits = result.pages.reduce((sum, p) => sum + Number(p.style_replacements || 0), 0);
      }
      const styleZero = (styleOnly || options.withStyle) && styleHits === 0;
      status.textContent = `${result.message || `${actionLabel}草稿已就绪`} · 可直接试生成${errPages}${styleZero ? ' · 画风 0 处匹配' : ''}`;
      status.classList.toggle('ok', !partial);
      status.classList.toggle('warn', partial);
      if (partial) status.classList.remove('ok');
    }
    let studioUrl = String(result.studio_url || '/studio?aitag=1&remix=1');
    try {
      const u = new URL(studioUrl, window.location.origin);
      u.searchParams.set('page', String(imageIndex));
      studioUrl = `${u.pathname}${u.search}`;
    } catch { /* keep raw */ }
    showOnlineRemixResult(result, replaceCharacter, studioUrl, {
      styleOnly,
      allPages,
      genderScope,
      partial: !!result.partial,
      label: replaceCharacter ? onlineRemixState.targetLabel : (styleOnly ? '画风' : '原图'),
    });
  } catch (error) {
    if (status) {
      const detail = error?.message || error?.detail || error;
      status.textContent = `建立草稿失败：${typeof detail === 'string' ? detail : (detail?.message || String(detail))}`;
      status.classList.remove('ok');
      status.classList.remove('warn');
    }
  } finally {
    onlineRemixState.drafting = false;
    syncOnlineAllSwapButtons();
  }
}

function syncOnlineAllSwapButtons() {
  const hasTarget = !!onlineRemixState.targetReferenceId;
  const busy = !!onlineRemixState.generating || !!onlineRemixState.drafting;
  [
    'onlineCharacterDraftBtn',
    'onlineReplaceMaleAllBtn',
    'onlineReplaceFemaleAllBtn',
    'onlineOriginalDraftBtn',
    'onlineStyleApplyBtn',
    'onlineStyleAllBtn',
  ].forEach((id) => {
    const btn = document.getElementById(id);
    if (!btn) return;
    if (id === 'onlineOriginalDraftBtn' || id === 'onlineStyleApplyBtn' || id === 'onlineStyleAllBtn') {
      btn.disabled = busy;
    } else {
      btn.disabled = !hasTarget || busy;
    }
  });
  syncOnlineGenerateButtons();
}

function wireOnlineRemixPanel(data, workId) {
  if (!isAitagGallery()) return;
  ensureCharSwapStylesLoaded();
  const panel = document.getElementById('onlineRemixPanel');
  const sameWork = String(onlineRemixState.workId || '') === String(workId || '');
  onlineRemixState.workId = String(workId);
  onlineRemixState.data = data;
  // Reset stacked drafts only when opening a different work (or first mount).
  if (!sameWork) {
    onlineRemixState.targetReferenceId = '';
    onlineRemixState.targetLabel = '';
    onlineRemixState.onlyCustomTargets = false;
    onlineRemixState.genderFilter = '';
    onlineRemixState.targetCache = [];
    onlineRemixState.pageDrafts = {};
    onlineRemixState.slotOverrides = {};
    onlineRemixState.lastDraftKey = '';
    onlineRemixState.generating = false;
    onlineRemixState.drafting = false;
  }

  // Bind listeners once per panel DOM node to avoid duplicate handlers.
  if (panel && panel.dataset.onlineWired === '1') {
    syncOnlineAllSwapButtons();
    renderOnlineSourceCandidateButtons();
    if (!onlineRemixState.targetCache.length) searchOnlineRemixTargets();
    return;
  }
  if (panel) panel.dataset.onlineWired = '1';

  const selectImage = document.getElementById('onlineSourceImage');
  selectImage?.addEventListener('change', () => {
    onlineRemixState.imageIndex = Number(selectImage.value || 0);
    renderOnlineSourceCandidateButtons();
    syncOnlineGenerateButtons();
  });
  document.getElementById('onlinePageTabs')?.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-online-page]');
    if (!tab || !selectImage) return;
    selectImage.value = String(tab.dataset.onlinePage);
    selectImage.dispatchEvent(new Event('change', { bubbles: true }));
  });
  document.getElementById('onlineTargetSearchBtn')?.addEventListener('click', () => {
    onlineRemixState.genderFilter = '';
    searchOnlineRemixTargets();
  });
  document.getElementById('onlineTargetQuery')?.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      onlineRemixState.genderFilter = '';
      searchOnlineRemixTargets();
    }
  });
  document.getElementById('onlineTargetQuery')?.addEventListener('input', () => {
    if (onlineRemixState.genderFilter) onlineRemixState.genderFilter = '';
    if (onlineRemixState.targetCache.length) renderOnlineTargetResults(onlineRemixState.targetCache);
  });
  const myOcFilter = document.getElementById('onlineTargetMyOcFilter');
  if (myOcFilter) {
    myOcFilter.addEventListener('click', () => {
      onlineRemixState.onlyCustomTargets = !onlineRemixState.onlyCustomTargets;
      myOcFilter.setAttribute('aria-pressed', onlineRemixState.onlyCustomTargets ? 'true' : 'false');
      myOcFilter.classList.toggle('active', onlineRemixState.onlyCustomTargets);
      if (onlineRemixState.targetCache.length) renderOnlineTargetResults(onlineRemixState.targetCache);
      else searchOnlineRemixTargets();
    });
  }
  document.getElementById('onlineOriginalDraftBtn')?.addEventListener('click', () => createOnlineStudioDraft({
    replaceCharacter: false,
    resetOriginal: true,
  }));
  document.getElementById('onlineCharacterDraftBtn')?.addEventListener('click', () => createOnlineStudioDraft({ replaceCharacter: true }));
  document.getElementById('onlineReplaceMaleAllBtn')?.addEventListener('click', async () => {
    if (!onlineRemixState.targetReferenceId) {
      const status = document.getElementById('onlineRemixStatus');
      if (status) status.textContent = '请先点一个角色，再换全部男槽。';
      return;
    }
    const n = (onlineRemixState.data?.images || []).length || 1;
    if (n > 1 && !window.confirm(`把「${onlineRemixState.targetLabel}」应用到全部 ${n} 张图的男槽？\n与本地「换男角·全部图片」相同，仅改草稿。`)) return;
    await createOnlineStudioDraft({
      replaceCharacter: true,
      allPages: true,
      genderScope: 'male',
    });
  });
  document.getElementById('onlineReplaceFemaleAllBtn')?.addEventListener('click', async () => {
    if (!onlineRemixState.targetReferenceId) {
      const status = document.getElementById('onlineRemixStatus');
      if (status) status.textContent = '请先点一个角色，再换全部女槽。';
      return;
    }
    const n = (onlineRemixState.data?.images || []).length || 1;
    if (n > 1 && !window.confirm(`把「${onlineRemixState.targetLabel}」应用到全部 ${n} 张图的女槽？\n与本地「换女角·全部图片」相同，仅改草稿。`)) return;
    await createOnlineStudioDraft({
      replaceCharacter: true,
      allPages: true,
      genderScope: 'female',
    });
  });
  document.getElementById('onlineStyleApplyBtn')?.addEventListener('click', () => createOnlineStudioDraft({
    replaceCharacter: false,
    styleOnly: true,
    withStyle: true,
  }));
  document.getElementById('onlineStyleAllBtn')?.addEventListener('click', async () => {
    const n = (onlineRemixState.data?.images || []).length || 1;
    if (n > 1 && !window.confirm(`把画风改写应用到全部 ${n} 张图？\n会叠在已有换角草稿上，不会冲掉角色。`)) return;
    await createOnlineStudioDraft({
      replaceCharacter: false,
      allPages: true,
      styleOnly: true,
      withStyle: true,
    });
  });
  document.getElementById('onlineGenerateBtn')?.addEventListener('click', () =>
    Promise.resolve(generateOnlineCurrentDraft()).catch((err) => reportAsyncError('试生成失败', err)));
  document.getElementById('onlineGenerateAllBtn')?.addEventListener('click', () =>
    Promise.resolve(generateOnlineAllDrafts()).catch((err) => reportAsyncError('批量生成失败', err)));
  syncOnlineAllSwapButtons();
  loadOnlineStylePresets();
  renderOnlineSourceCandidateButtons();
  searchOnlineRemixTargets();
}

async function openOnlineRemixPanel(workId, action = 'remix') {
  const current = window.__AITAG_CURRENT_DETAIL__;
  if (!current || String(current.workId) !== String(workId) || !isAitagGallery()) {
    await openDetail(workId);
  }
  if (action === 'draft') {
    await createOnlineStudioDraft({ replaceCharacter: false });
    return;
  }
  document.getElementById('onlineRemixPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  document.getElementById('onlineTargetQuery')?.focus({ preventScroll: true });
}

function isBlockedWork(w) {
  if (!state.blacklist.length) return false;
  const hay = [w.title, w.caption, w.tags, w.AI_type].map((v) => String(v || '').toLowerCase()).join('\n');
  return state.blacklist.some((kw) => kw && hay.includes(kw));
}

const gallerySourceSel = document.getElementById('gallerySource');
const galleryGroupSel = document.getElementById('galleryGroup');
const gallerySourceSwitchEl = document.getElementById('gallerySourceSwitch');
const gallerySourceButtons = Array.from(document.querySelectorAll('[data-gallery-source]'));
const advancedFilterSummaryEl = document.getElementById('advancedFilterSummary');
const clearFiltersBtn = document.getElementById('clearFiltersBtn');
const GALLERY_ASSET_BASE_URLS = Object.freeze({
  site: '/data/images/',
  codex: '/data/gallery/codex/',
  qqgroup: '/data/gallery/qqgroup/',
});
let galleryRequestGeneration = 0;
const AITAG_GALLERY_ID = 'aitag-online';

function currentGalleryId() {
  return (gallerySourceSel && gallerySourceSel.value) || 'site';
}

function isAitagGallery(galleryId = currentGalleryId()) {
  return String(galleryId || '') === AITAG_GALLERY_ID;
}

function currentGalleryGroup() {
  return (galleryGroupSel && galleryGroupSel.value) || '';
}

function aitagImageUrl(image = {}) {
  return String(image.thumbnail_url || image.thumb_url || image.url || image.image_url || '').trim();
}

function adaptAitagWork(item = {}) {
  const metadata = item.metadata && typeof item.metadata === 'object' ? item.metadata : {};
  const images = Array.isArray(item.images) ? item.images : [];
  const cover = aitagImageUrl(images[0] || {});
  const rawType = String(item.AI_type || item.ai_type || metadata.AI_type || 'NAI');
  const aiType = rawType.toLowerCase().includes('novelai') ? 'NAI' : rawType;
  return {
    ...item,
    id: String(item.id || item.work_id || ''),
    AI_type: aiType,
    userId: String(item.userId || item.user_id || metadata.userId || ''),
    creator: String(item.creator || metadata.userName || ''),
    caption: String(item.caption || metadata.caption || ''),
    tags: item.tags || metadata.tags || [],
    create_date: String(item.create_date || metadata.create_date || ''),
    image_count: Number(item.image_count || images.length || 0),
    original_urls: item.original_urls || metadata.original_urls || [],
    thumbnail_url: cover,
    cover_url: cover,
    source_gallery_id: AITAG_GALLERY_ID,
    external_url: String(item.external_url || ''),
  };
}

function adaptAitagDetail(payload = {}) {
  const work = adaptAitagWork(payload.work || payload);
  const images = (Array.isArray(payload.images) ? payload.images : []).map((image, index) => ({
    ...image,
    id: image.id || image.image_id || `${work.id}_p${index}`,
    page_index: Number.isInteger(Number(image.page_index)) ? Number(image.page_index) : index,
    url: String(image.url || image.image_url || ''),
    thumbnail_url: String(image.thumbnail_url || image.thumb_url || image.url || ''),
    ai_json: image.ai_json || image.metadata?.ai_json || {},
  }));
  return {
    ...payload,
    source: AITAG_GALLERY_ID,
    generation_calls: 0,
    work: { ...work, images, image_count: images.length || work.image_count },
    images,
  };
}


function selectedOptionLabel(select, fallback = '') {
  if (!select) return fallback;
  const selected = select.options && select.options[select.selectedIndex];
  return String((selected && selected.textContent) || fallback).trim();
}

function syncGallerySourceSwitch() {
  const selected = currentGalleryId();
  gallerySourceButtons.forEach((button) => {
    const active = button.dataset.gallerySource === selected;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
  if (gallerySourceSwitchEl) {
    gallerySourceSwitchEl.dataset.currentGallery = selected;
  }
}

function updateGallerySourceUi() {
  const online = isAitagGallery();
  document.body.classList.toggle('aitag-gallery-active', online);
  const setText = (selector, value) => {
    const element = document.querySelector(selector);
    if (element) element.textContent = value;
  };
  const title = document.getElementById('gallerySearchTitle');
  if (title) title.textContent = online ? '检索 AITag 在线库' : '检索本地图谱';
  if (qInput) qInput.placeholder = online
    ? '搜索 AITag 在线作品：角色 / 标签 / ID / 作者 / Prompt'
    : '在本地已入库库内搜索：角色 / 标签 / ID / 作者 / 咒语';
  const groupField = galleryGroupSel?.closest('.af-field');
  groupField?.toggleAttribute('hidden', online);
  groupField?.classList.toggle('hidden', online);
  document.querySelectorAll('.aitag-only-filter').forEach((element) => {
    element.classList.toggle('hidden', !online);
    element.toggleAttribute('hidden', !online);
  });
  document.getElementById('localBanner')?.classList.toggle('hidden', online);
  document.getElementById('setupBanner')?.classList.toggle('hidden', online);
  const storage = document.getElementById('storagePathFooter');
  if (storage) storage.classList.toggle('hidden', online);
  document.getElementById('galleryFooter')?.classList.toggle('hidden', online);

  setText('#galleryHeroEyebrow', online ? 'AITag online · NAI works' : 'NAI verified · PIXIV intake');
  setText('#galleryHeroAccent', online ? '下一次创作' : '可检索的图谱');
  setText('#galleryHeroLead', online
    ? '搜索 AITag 在线作品、角色与 Prompt；先浏览完整作品，再建立零生成草稿或进入在线换角。'
    : '搜索作品、画师、Pixiv 标签和原图里的 NAI Prompt；从浏览直接进入小镜、生成、换角与队列。');
  setText('#galleryNoteIndex', online ? 'ONLINE / AITAG' : 'LOCAL / 01');
  setText('#galleryAboutTitle', online ? '关于在线库' : '关于图库');
  setText('#galleryAboutSummary', online ? '在线来源、NAI 准入与再创作' : '来源、准入与本地存储');
  setText('#galleryResultsLabel', online ? 'Online stream / AITag index' : 'Archive stream / local index');
  setText('#galleryResultsTitle', online ? '在线作品流' : '作品流');

  // 收藏 / 待生成模式：检索台与结果区语义对齐
  if (state.favoritesMode || state.queueMode) {
    const isFav = !!state.favoritesMode;
    setText('#galleryHeroEyebrow', isFav ? 'My collection · local' : 'Generation queue · local');
    setText('#galleryHeroAccent', isFav ? '都值得再看一遍' : '排队等生成');
    setText('#gallerySearchTitle', isFav ? '检索我的收藏' : '检索待生成队列');
    setText('#galleryResultsTitle', isFav ? '收藏作品' : '待生成作品');
  }
  setText('#galleryResultsHelp', online
    ? '单击打开详情与全部图片；可在同一详情页建立草稿、识别角色槽并换角。'
    : (window.GalleryDropFolders && window.GalleryDropFolders.isDropGallery()
      ? '把图片拖进下方区域解析入库；每次拖入收成一个文件夹，可折叠、合并，并一键加入批量换角。'
      : '单击打开详情与全部图片；右侧灵感栏可直接送去生成、换角或队列。排序选「随机刷新」后点「换一批」，每次都能看到不同的图。'));
  setText('#searchStatus span', online ? '正在读取 AITag 在线库…' : '正在读取本地图谱…');
  setText('#inspirationEmpty', online
    ? '单击在线作品查看详情与全部图片；在同一页面完成角色槽识别与换角'
    : '单击查看详情与全部图片；侧边栏可预览咒语并送去生成或洗稿');
  setText('#inspirationToStudio', online ? '建立原图草稿 →' : '用此图生成 →');
  setText('#inspirationToRemix', '角色换角 →');
  document.getElementById('inspirationToQueue')?.classList.toggle('hidden', online);

  const signals = document.querySelectorAll('#galleryHeroSignals span');
  const signalText = online
    ? ['01 在线作品即搜即看', '02 NAI 元数据准入', '03 零生成草稿换角']
    : ['01 Pixiv 直连发现', '02 NAI 元数据准入', '03 原图本地保存'];
  signals.forEach((element, index) => {
    const parts = signalText[index]?.split(' ');
    if (!parts) return;
    element.innerHTML = `<b>${parts.shift()}</b> ${parts.join(' ')}`;
  });

  const titleZh = document.querySelector('#hero-intro .hero-title .lang-zh');
  const titleEn = document.querySelector('#hero-intro .hero-title .lang-en');
  const descZh = document.querySelector('#hero-intro .hero-desc .lang-zh');
  const descEn = document.querySelector('#hero-intro .hero-desc .lang-en');
  if (state.favoritesMode || state.queueMode) {
    const isFav = !!state.favoritesMode;
    if (titleZh) titleZh.textContent = isFav ? '我的收藏' : '待生成队列';
    if (titleEn) titleEn.textContent = isFav ? 'My collection' : 'Generation queue';
    if (descZh) descZh.textContent = isFav
      ? '你收藏的作品都在这里；可直接送去生成、换角或加入队列。'
      : '排队等待生成的作品；确认后可送去生成或继续编辑。';
    if (descEn) descEn.textContent = isFav ? 'Your bookmarked works.' : 'Works queued for generation.';
  } else if (online) {
    if (titleZh) titleZh.textContent = '从在线作品里找到';
    if (titleEn) titleEn.textContent = 'Browse the AITag collection';
    if (descZh) descZh.textContent = '在线搜索与浏览 AITag 作品，查看每张原图和可用角色；选择后才建立 Studio 草稿，全程不会自动调用生图。';
    if (descEn) descEn.textContent = 'Search AITag works, inspect every image and character slot, then create a zero-generation Studio draft.';
  } else {
    if (titleZh) titleZh.textContent = CONFIG.gallery_title_zh || '把灵感整理成';
    if (titleEn) titleEn.textContent = CONFIG.gallery_title_en || 'A map for every idea';
    if (descZh) descZh.textContent = CONFIG.gallery_desc_zh || '从 Pixiv 搜索、画师与榜单发现候选图片；只有包含可验证 NovelAI 元数据的页面才会进入本地图库。Pixiv 标签用于分类，NAI 提示词标签另行解析并入库。';
    if (descEn) descEn.textContent = CONFIG.gallery_desc_en || 'Candidates come from Pixiv search, users, and rankings. Only pages with verified NovelAI metadata enter the local gallery; Pixiv tags and parsed NAI prompt tags remain separate.';
  }
  try { window.GalleryDropFolders && window.GalleryDropFolders.sync(); } catch { }
}

function updateAdvancedFilterSummary() {
  if (!advancedFilterSummaryEl) return;
  const source = selectedOptionLabel(gallerySourceSel, '网站图库');
  const group = currentGalleryGroup() ? selectedOptionLabel(galleryGroupSel) : '';
  const sort = selectedOptionLabel(sortModeSel, '最新');
  const time = selectedOptionLabel(timeRangeSel, '全部时间');
  const online = isAitagGallery();
  const extras = online ? [
    aitagCreatorInput?.value ? `作者:${aitagCreatorInput.value.trim()}` : '',
    aitagTagsInput?.value ? `标签:${aitagTagsInput.value.trim()}` : '',
    aitagModelSelect?.value ? selectedOptionLabel(aitagModelSelect) : '',
    aitagMinImagesInput?.value ? `≥${aitagMinImagesInput.value}张` : '',
    aitagMaxImagesInput?.value ? `≤${aitagMaxImagesInput.value}张` : '',
  ] : [];
  advancedFilterSummaryEl.textContent = [source, group, sort, time, ...extras].filter(Boolean).join(' · ');
}

function onlineAdvancedFilters() {
  return {
    creator: String(aitagCreatorInput?.value || '').trim(),
    tags: String(aitagTagsInput?.value || '').trim(),
    model: String(aitagModelSelect?.value || '').trim(),
    minImages: Math.max(0, Number.parseInt(aitagMinImagesInput?.value || '0', 10) || 0),
    maxImages: Math.max(0, Number.parseInt(aitagMaxImagesInput?.value || '0', 10) || 0),
  };
}

function resetOnlineAdvancedFilters() {
  if (aitagCreatorInput) aitagCreatorInput.value = '';
  if (aitagTagsInput) aitagTagsInput.value = '';
  if (aitagModelSelect) aitagModelSelect.value = '';
  if (aitagMinImagesInput) aitagMinImagesInput.value = '';
  if (aitagMaxImagesInput) aitagMaxImagesInput.value = '';
}

function applyGalleryAssetBase() {
  CONFIG.asset_base_url = GALLERY_ASSET_BASE_URLS[currentGalleryId()] || GALLERY_ASSET_BASE_URLS.site;
}

function applyGalleryParams(url) {
  url.searchParams.set('gallery_id', currentGalleryId());
  const group = currentGalleryGroup();
  if (group) url.searchParams.set('group', group);
  return url;
}

function renderGalleryGroups(items) {
  if (!galleryGroupSel) return;
  const rows = Array.isArray(items) ? items : [];
  const folders = rows.filter((it) => it.kind === 'folder');
  const groups = rows.filter((it) => it.kind === 'group');
  const accounts = rows.filter((it) => it.kind === 'account');
  const allLabel = folders.length && groups.length
    ? '全部文件夹、群组和账号'
    : (folders.length ? '全部文件夹' : '全部群组和账号');
  const html = [`<option value="">${allLabel}</option>`];
  if (folders.length && !groups.length) {
    folders.forEach((folder) => {
      const key = String(folder.group_key || folder.label || '');
      html.push(`<option value="${escapeHtml(folder.key || `group:${key}`)}">文件夹 · ${escapeHtml(folder.label || key)} (${Number(folder.count) || 0})</option>`);
    });
  } else if (groups.length) {
    folders.forEach((folder) => {
      const key = String(folder.group_key || folder.label || '');
      html.push(`<option value="${escapeHtml(folder.key || `group:${key}`)}">文件夹 · ${escapeHtml(folder.label || key)} (${Number(folder.count) || 0})</option>`);
    });
    groups.forEach((group) => {
      const groupKey = String(group.group_key || '');
      const label = String(group.label || groupKey);
      html.push(`<option value="${escapeHtml(group.key || `group:${groupKey}`)}">群组 · ${escapeHtml(label)} (${Number(group.count) || 0})</option>`);
      const children = accounts.filter((it) => String(it.group_key || '') === String(group.group_key || ''));
      if (children.length) {
        html.push(`<optgroup label="${escapeHtml(label)}">`);
        children.forEach((account) => {
          html.push(`<option value="${escapeHtml(account.key || '')}">账号 · ${escapeHtml(account.label || account.account_key || '')} (${Number(account.count) || 0})</option>`);
        });
        html.push('</optgroup>');
      }
    });
  } else {
    rows.forEach((item) => {
      html.push(`<option value="${escapeHtml(item.key || '')}">${escapeHtml(item.label || item.key || '')} (${Number(item.count) || 0})</option>`);
    });
  }
  galleryGroupSel.innerHTML = html.join('');
  const requested = new URL(window.location.href).searchParams.get('group') || '';
  if (requested && Array.from(galleryGroupSel.options).some((option) => option.value === requested)) {
    galleryGroupSel.value = requested;
  }
  updateAdvancedFilterSummary();
}

const GALLERY_SORT_OPTIONS = {
  site: [
    { value: 'new', label: '最新发布 (Newest)' },
    { value: 'random', label: '随机刷新 (Shuffle)' },
    { value: 'count', label: '图片数量 (By Count)' },
    { value: 'old', label: '最早发布 (Oldest)' },
  ],
  codex: [
    { value: 'new', label: '最新入库 (Newest)' },
    { value: 'random', label: '随机刷新 (Shuffle)' },
    { value: 'title', label: '图集标题 (By Title)' },
    { value: 'count', label: '包含图片数 (By Count)' },
  ],
  qqgroup: [
    { value: 'new', label: '最新发送 (Newest)' },
    { value: 'random', label: '随机刷新 (Shuffle)' },
    { value: 'group', label: '按Q群/账号 (By Group)' },
    { value: 'author', label: '按发送者 (By Author)' },
  ],
  'aitag-online': [
    { value: 'popular', label: '热门榜单 (Popular)' },
    { value: 'recent', label: '最新收录 (Recent)' },
    { value: 'relevance', label: '相关优先 (Relevance)' },
  ],
};

// Hero 折叠：首次访问展示完整介绍；之后默认收起（localStorage 记忆），
// 手动收起/展开的显式选择优先于默认行为。
(function initHeroCollapse() {
  const hero = document.getElementById('hero-intro');
  const btn = document.getElementById('heroCollapseBtn');
  if (!hero || !btn) return;
  let collapsed = false;
  try {
    const explicit = localStorage.getItem('galleryHeroCollapsed');
    if (explicit !== null) {
      collapsed = explicit === '1';
    } else {
      collapsed = localStorage.getItem('galleryHeroSeen') === '1';
    }
    localStorage.setItem('galleryHeroSeen', '1');
  } catch { }
  const apply = (value) => {
    collapsed = value;
    hero.classList.toggle('hero-collapsed', collapsed);
    btn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  };
  apply(collapsed);
  btn.addEventListener('click', () => {
    apply(!collapsed);
    try { localStorage.setItem('galleryHeroCollapsed', collapsed ? '1' : '0'); } catch { }
  });
})();

// 随机刷新：seed 决定后端哈希乱序的顺序。同一 seed 翻页稳定不重复，
// 换 seed 即换一批；从其它排序切入 random 时自动换一个新 seed。
let shuffleSeed = 0;
let lastListSortMode = '';

function newShuffleSeed() {
  return Math.floor(Math.random() * 4294967296);
}

function updateShuffleButton(mode) {
  const btn = document.getElementById('shuffleBtn');
  if (!btn) return;
  const show = mode === 'random'
    && !isAitagGallery()
    && !state.favoritesMode
    && !state.queueMode;
  btn.classList.toggle('hidden', !show);
}

function updateGallerySortOptions(galleryId) {
  const sortSel = document.getElementById('sortMode');
  if (!sortSel) return;
  const gid = galleryId || currentGalleryId() || 'site';
  const options = GALLERY_SORT_OPTIONS[gid] || GALLERY_SORT_OPTIONS.site;
  const currentVal = sortSel.value;
  sortSel.innerHTML = options.map((opt) => `<option value="${opt.value}">${opt.label}</option>`).join('');
  if (options.some((o) => o.value === currentVal)) {
    sortSel.value = currentVal;
  } else {
    sortSel.value = options[0].value;
  }
}

async function loadGalleryHierarchy(
  expectedGallery = currentGalleryId(),
  requestGeneration = galleryRequestGeneration,
) {
  if (!gallerySourceSel || !galleryGroupSel) return;
  const selected = expectedGallery;
  updateGallerySortOptions(selected);
  if (isAitagGallery(selected)) {
    renderGalleryGroups([]);
    return true;
  }
  const response = await window.ApiClient.raw(`/api/galleries/${encodeURIComponent(selected)}/groups`);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  if (requestGeneration !== galleryRequestGeneration || selected !== currentGalleryId()) return false;
  renderGalleryGroups(data.items || []);
  try {
    if (window.GalleryDropFolders && typeof window.GalleryDropFolders.refresh === "function") {
      await window.GalleryDropFolders.refresh();
    }
  } catch { }
  return true;
}

function updateGalleryLocation() {
  const url = new URL(window.location.href);
  url.searchParams.set('gallery', currentGalleryId());
  const group = currentGalleryGroup();
  if (group) url.searchParams.set('group', group);
  else url.searchParams.delete('group');
  url.searchParams.delete('page');
  history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`);
}

if (gallerySourceSel) {
  const requestedGallery = new URL(window.location.href).searchParams.get('gallery') || 'site';
  if (Array.from(gallerySourceSel.options).some((option) => option.value === requestedGallery)) {
    gallerySourceSel.value = requestedGallery;
  }
  syncGallerySourceSwitch();
  updateGallerySourceUi();
  updateGallerySortOptions(requestedGallery);
  applyGalleryAssetBase();
  gallerySourceSel.addEventListener('change', async () => {
    const requestGeneration = ++galleryRequestGeneration;
    const requestedGallery = currentGalleryId();
    syncGallerySourceSwitch();
    updateGallerySourceUi();
    if (galleryGroupSel) galleryGroupSel.value = '';
    applyGalleryAssetBase();
    updateGalleryLocation();
    setFavoriteIds([]);
    loadFavorites().catch(() => loadCachedFavorites());
    try {
      await loadGalleryHierarchy(requestedGallery, requestGeneration);
    } catch {
      if (requestGeneration === galleryRequestGeneration && requestedGallery === currentGalleryId()) {
        renderGalleryGroups([]);
      }
    }
    if (requestGeneration !== galleryRequestGeneration || requestedGallery !== currentGalleryId()) return;
    updateAdvancedFilterSummary();
    state.page = 1;
    state.items = [];
    fetchWorks(requestGeneration, requestedGallery);
  });
}
gallerySourceButtons.forEach((button) => {
  button.addEventListener('click', () => {
    if (!gallerySourceSel) return;
    const requested = String(button.dataset.gallerySource || '');
    if (!requested || requested === currentGalleryId()) return;
    gallerySourceSel.value = requested;
    syncGallerySourceSwitch();
    gallerySourceSel.dispatchEvent(new Event('change'));
  });
});
galleryGroupSel?.addEventListener('change', () => {
  const requestGeneration = ++galleryRequestGeneration;
  const requestedGallery = currentGalleryId();
  updateGalleryLocation();
  updateAdvancedFilterSummary();
  state.page = 1;
  state.items = [];
  fetchWorks(requestGeneration, requestedGallery);
});
[sortModeSel, timeRangeSel].filter(Boolean).forEach((select) => {
  select.addEventListener('change', updateAdvancedFilterSummary);
});
updateAdvancedFilterSummary();

function syntaxHighlight(jsonStr) {
  // naive highlighter for JSON
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
  let html = esc(jsonStr)
    .replace(/(".*?")(?=\s*:)/g, '<span class="k">$1</span>')
    .replace(/:\s*"(.*?)"/g, ':<span class="s">"$1"</span>')
    .replace(/:\s*(\d+(?:\.\d+)?)/g, ':<span class="n">$1</span>')
    .replace(/:\s*(true|false|null)/g, ':<span class="b">$1</span>');

  // Highlight common SD parameter prefixes within string content
  const sdPattern = /\b(Negative prompt|Steps|Sampler|Schedule type|CFG scale|Seed|Size|Model hash|Model|Denoising strength|Clip skip|Eta|Noise|Upscaler|Hires steps|Hires upscaler|Hires scale|Hires denoising strength|Mask blur|Inpaint area|Masked area padding|Lora hashes|Version|Style Selector Enabled|Style Selector Randomize|Style Selector Style|ADetailer confidence|ADetailer dilate erode|ADetailer mask blur|ADetailer inpaint only masked|ADetailer inpaint padding|ADetailer denoising strength|ADetailer model|ADetailer prompt)\s*:/gi;
  html = html.replace(sdPattern, (m) => `<span class="sd">${m}</span>`);

  // Highlight <lora:...> fragments and ensure the entire token is orange/bold
  // Previous JSON number highlighting may have inserted <span class="n"> inside the token;
  // we strip inner span tags within the matched lora segment so it becomes one colored block.
  html = html.replace(/(&lt;lora:)[\s\S]*?&gt;/gi, (m) => {
    const cleaned = m.replace(/<\/?span[^>]*>/g, '');
    return `<span class="sd-lora">${cleaned}</span>`;
  });

  return html;
}

// 详情页 JSON 框全局展开/折叠状态与注册表
let detailJsonBoxes = [];
let detailJsonExpanded = false;

// 无限滚动加载状态与终止标记
let loadingPage = false;
let endReached = false;
let lastPageCount = 0;

async function fetchWorks(
  requestGeneration = null,
  requestedGallery = currentGalleryId(),
) {
  // 未显式传代数的调用视为新查询：递增代数使所有在途旧响应失效，
  // 防止慢的旧搜索/翻页结果覆盖新列表。
  if (requestGeneration === null) requestGeneration = ++galleryRequestGeneration;
  let keepSearchNotice = false;
  try {
    if (searchStatusEl) {
      searchStatusEl.classList.remove('notice');
      const textEl = searchStatusEl.querySelector('span');
      if (textEl) textEl.textContent = t('status_searching');
      searchStatusEl.classList.add('visible');
    }
  } catch { }
  loadingPage = true;
  loadingEl.textContent = t('loading');
  loadingEl.style.display = 'block';
  const mode = (sortModeSel && sortModeSel.value) || 'new';
  const onlineGallery = isAitagGallery(requestedGallery);
  const isRank = !onlineGallery && !state.favoritesMode && !state.queueMode && mode === 'monthly';
  updateShuffleButton(mode);
  let url;
  if (onlineGallery && state.favoritesMode) {
    url = new URL('/api/nai/aitag/favorites/works', API_BASE);
  } else if (onlineGallery) {
    url = new URL('/api/nai/aitag/search', API_BASE);
  } else if (state.queueMode) {
    url = new URL('/api/queue/works', API_BASE);
  } else if (state.favoritesMode) {
    url = new URL('/api/favorites/works', API_BASE);
  } else if (isRank) {
    const trVal = (timeRangeSel && timeRangeSel.value) || 'current';
    if (trVal === 'current') {
      url = new URL('/api/rank/monthly/real', API_BASE);
    } else if (trVal === 'older' || (trVal.startsWith('m'))) {
      url = new URL('/api/rank/monthly/fixed', API_BASE);
    } else {
      url = new URL('/api/rank/monthly', API_BASE);
    }
  } else {
    url = new URL('/api/ai_works_search', API_BASE);
  }
  url.searchParams.set('page', state.page);
  url.searchParams.set('page_size', state.pageSize);
  if (!onlineGallery) applyGalleryParams(url);
  if (
    !state.favoritesMode
    && !state.queueMode
    && !onlineGallery
    && (state.page > 1 || state.q || state.prompt || state.listMode === 'infinite')
  ) {
    url.searchParams.set('skip_total', '1');
  }
  if ((state.favoritesMode || state.queueMode) && state.q) url.searchParams.set('q', state.q);
  if (!state.favoritesMode && !state.queueMode && state.q) url.searchParams.set('q', state.q);
  if (!state.favoritesMode && !state.queueMode && state.prompt) url.searchParams.set('prompt', state.prompt);
  const tr = (timeRangeSel && timeRangeSel.value) || (isRank ? 'current' : 'all');
  if (onlineGallery) {
    url.searchParams.set('sort', ['popular', 'recent', 'relevance'].includes(mode) ? mode : 'popular');
    url.searchParams.set('time_range', tr || 'all');
    url.searchParams.set('nai_only', 'true');
    url.searchParams.set('safe_only', 'false');
    if (!state.favoritesMode) {
      const filters = onlineAdvancedFilters();
      if (filters.creator) url.searchParams.set('creator', filters.creator);
      if (filters.tags) url.searchParams.set('tags', filters.tags);
      if (filters.model) url.searchParams.set('model', filters.model);
      if (filters.minImages) url.searchParams.set('min_images', String(filters.minImages));
      if (filters.maxImages) url.searchParams.set('max_images', String(filters.maxImages));
    }
  } else if (!state.favoritesMode && !state.queueMode && isRank) {
    // period 参数：current 或 YYYY-MM 或 older
    const path = url.pathname || '';
    if (path.includes('/real')) {
      // 当前月份不需要 period
    } else if (path.includes('/fixed')) {
      let month = '';
      if (tr === 'older') month = 'older';
      else if (tr && tr.startsWith('m')) month = tr.slice(1);
      url.searchParams.set('month', month);
    } else {
      let period = 'current';
      if (tr && tr.startsWith('m')) period = tr.slice(1);
      else if (tr === 'older') period = 'older';
      url.searchParams.set('period', period);
    }
    // 月榜也支持关键词与 prompt 过滤
    if (state.q) url.searchParams.set('q', state.q);
    if (state.prompt) url.searchParams.set('prompt', state.prompt);
  } else if (!state.favoritesMode && !state.queueMode) {
    // 列表接口：sort 与 time_range
    url.searchParams.set('sort', mode || 'new');
    url.searchParams.set('time_range', tr || 'all');
    if (mode === 'random') {
      if (!shuffleSeed || lastListSortMode !== 'random') shuffleSeed = newShuffleSeed();
      url.searchParams.set('seed', String(shuffleSeed));
    }
  }
  lastListSortMode = mode;
  try {
    let data = readSearchCache(url);
    let res = null;
    if (!data) {
      res = await window.ApiClient.raw(url);
      try {
        data = await res.json();
      } catch { data = { page: state.page, page_size: state.pageSize, total: 0, items: [] }; }
      if (res.ok) writeSearchCache(url, data);
    }
    if (!res && !data) {
      res = await window.ApiClient.raw(url);
      try { data = await res.json(); } catch { data = { page: state.page, page_size: state.pageSize, total: 0, items: [] }; }
    }
    if (requestGeneration !== galleryRequestGeneration || requestedGallery !== currentGalleryId()) return;
    if (data && data.error === 'search_failed') {
      const msg = CURRENT_LANG === 'zh'
        ? (data.message_zh || data.message || t('err_search_failed'))
        : (data.message_en || data.message || t('err_search_failed'));
      state.items = [];
      state.total = 0;
      try { state.workPages.clear(); } catch { }
      lastPageCount = 0;
      renderGallery();
      if (paginationEl) paginationEl.innerHTML = '';
      if (loadMoreBtn) loadMoreBtn.classList.add('hidden');
      try { if (noResultEl) noResultEl.classList.remove('visible'); } catch { }
      try {
        if (searchStatusEl) {
          const textEl = searchStatusEl.querySelector('span');
          if (textEl) textEl.textContent = msg;
          searchStatusEl.classList.add('visible', 'notice');
          keepSearchNotice = true;
        }
      } catch { }
      return;
    }
    if (res && !res.ok && data && data.error === 'rank_processing') {
      const msg = CURRENT_LANG === 'zh'
        ? (data.message_zh || t('rank_processing'))
        : (data.message_en || t('rank_processing'));
	      state.items = [];
	      state.total = 0;
      try { state.workPages.clear(); } catch { }
	      lastPageCount = 0;
      renderGallery();
      if (paginationEl) paginationEl.innerHTML = '';
      if (loadMoreBtn) loadMoreBtn.classList.add('hidden');
      try { if (noResultEl) noResultEl.classList.remove('visible'); } catch { }
      try {
        if (searchStatusEl) {
          const textEl = searchStatusEl.querySelector('span');
          if (textEl) textEl.textContent = msg;
          searchStatusEl.classList.add('visible', 'notice');
          keepSearchNotice = true;
        }
      } catch { }
      return;
	    }
    // 其它 HTTP 失败（500/超时等）：明确提示加载失败，而不是伪装成「无结果」
    if (res && !res.ok) {
      const detail = data && (data.detail || data.message) ? String(data.detail || data.message) : `HTTP ${res.status}`;
      const msg = CURRENT_LANG === 'zh' ? `加载失败：${detail}` : `Failed to load: ${detail}`;
      state.items = [];
      state.total = 0;
      try { state.workPages.clear(); } catch { }
      lastPageCount = 0;
      renderGallery();
      if (paginationEl) paginationEl.innerHTML = '';
      if (loadMoreBtn) loadMoreBtn.classList.add('hidden');
      try { setNoResultMessage(msg); } catch { }
      try { if (noResultEl) noResultEl.classList.add('visible'); } catch { }
      try {
        if (searchStatusEl) {
          const textEl = searchStatusEl.querySelector('span');
          if (textEl) textEl.textContent = msg;
          searchStatusEl.classList.add('visible', 'notice');
          keepSearchNotice = true;
        }
      } catch { }
      return;
    }
	    // 保留接口原始结果，具体隐藏规则统一在前端渲染时应用，方便开关即时恢复。
	    let incoming = Array.isArray(data.items) ? data.items : [];
            if (onlineGallery) incoming = incoming.map(adaptAitagWork);
		    if (!onlineGallery && !state.favoritesMode && !state.queueMode && !isRank) {
		      incoming = sortWorkItems(incoming, mode);
		    }
		    lastPageCount = incoming.length;
    if (state.favoritesMode && incoming.length) {
      incoming.forEach((w) => {
        const id = normalizeWorkId(w && w.id);
        if (id) state.favoriteIds.add(id);
      });
      try { sessionStorage.setItem(`${FAVORITES_CACHE_KEY}:${currentGalleryId()}`, JSON.stringify([...state.favoriteIds])); } catch { }
    }
    if (state.queueMode && incoming.length) {
      incoming.forEach((w) => {
        const id = normalizeWorkId(w && w.id);
        if (id) state.queueIds.add(id);
      });
    }
    rememberWorkListPages(incoming, state.page, { reset: !(state.listMode === 'infinite' && state.page > 1) });
	    if (state.listMode === 'infinite' && state.page > 1) {
      const prev = state.items || [];
      const seen = new Set();
      const merged = [];
      for (const w of [...prev, ...incoming]) {
        const id = normalizeWorkId(w && w.id);
        if (!id || seen.has(id)) continue;
        seen.add(id);
        merged.push(w);
      }
	      state.items = (!onlineGallery && !state.favoritesMode && !state.queueMode && !isRank) ? sortWorkItems(merged, mode) : merged;
	    } else {
	      state.items = incoming;
	    }
	    if (typeof data.total === 'number' && data.total >= 0) {
	      state.total = data.total;
	    }
	    try {
	      if (searchStatusEl) {
	        const textEl = searchStatusEl.querySelector('span');
	        if (textEl) {
	          if (isRank && state.page === 1 && !state.q && !state.prompt) {
	            textEl.textContent = t('rank_snapshot_hint');
	            searchStatusEl.classList.add('visible', 'notice');
	            keepSearchNotice = true;
	          } else if (onlineGallery || state.q || state.prompt) {
	            if (state.total > 0) {
	              textEl.textContent = CURRENT_LANG === 'zh'
	                ? `共 ${state.total.toLocaleString('zh-CN')} 条 · 第 ${state.page} 页`
	                : `${state.total.toLocaleString()} results · page ${state.page}`;
	            } else {
	              const shown = (state.items || []).length;
	              textEl.textContent = CURRENT_LANG === 'zh'
	                ? `已显示 ${shown.toLocaleString('zh-CN')} 条 · 第 ${state.page} 页`
	                : `${shown.toLocaleString()} shown · page ${state.page}`;
	            }
	            searchStatusEl.classList.add('visible');
	          } else if (!isRank) {
	            searchStatusEl.classList.remove('notice');
	          }
	        }
	      }
	    } catch { }
	    renderGallery();
	    updateNoResultVisibility();
	    if (state.listMode === 'pagination') {
      renderPagination();
    }
	    if (state.listMode === 'infinite') {
	      setupInfiniteScrollIfVisible();
      // 根据是否还有下一页，切换“加载更多”按钮显示
      const totalPages = Math.max(1, Math.ceil((state.total || 0) / (state.pageSize || 1)));
      const unknownTotal = (state.total <= 0);
      endReached = unknownTotal ? (lastPageCount < state.pageSize) : (state.page >= totalPages);
      if (loadMoreBtn) {
        loadMoreBtn.classList.toggle('hidden', endReached);
      }
      if (!endReached && state.listMode === 'infinite') {
        const nextUrl = buildWorksListUrl(state.page + 1);
        if (!readSearchCache(nextUrl)) {
          window.ApiClient.raw(nextUrl).then((r) => r.ok ? r.json() : null).then((payload) => {
            if (payload) writeSearchCache(nextUrl, payload);
          }).catch(() => {});
        }
      }
    }
  } catch (e) {
    if (requestGeneration !== galleryRequestGeneration || requestedGallery !== currentGalleryId()) return;
    loadingEl.textContent = t('loading_failed');
    try { setNoResultMessage(t('loading_failed')); } catch { }
    try { if (noResultEl) noResultEl.classList.add('visible'); } catch { }
  } finally {
    const isCurrentRequest = requestGeneration === galleryRequestGeneration && requestedGallery === currentGalleryId();
    if (isCurrentRequest) {
      loadingEl.style.display = 'none';
      loadingPage = false;
    }
    try {
      if (isCurrentRequest && searchStatusEl && !keepSearchNotice) {
        searchStatusEl.classList.remove('visible', 'notice');
      }
    } catch { }
  }
}

function renderGallery(opts = {}) {
  const shouldClear = !!opts.forceClear || !(state.listMode === 'infinite' && state.page > 1);
  if (shouldClear) {
    galleryEl.innerHTML = '';
  }
  // 更新右下角页码显示
  if (fcNum) {
    fcNum.textContent = String(state.page);
  }
  const existingIds = new Set(Array.from(galleryEl.querySelectorAll('.card img')).map((img) => normalizeWorkId(img.dataset.workId)));
  const baseItems = shouldClear ? state.items : state.items.filter((w) => !existingIds.has(normalizeWorkId(w.id)));
  const renderItems = visibleWorks(baseItems);
  const adAfterVisibleCount = Math.max(1, getGalleryColumnCount() * 3);
  const visibleCountByPage = new Map();
  const fragment = document.createDocumentFragment();
  renderItems.forEach((w, index) => {
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.workId = String(w.id);
    const img = document.createElement('img');
    img.loading = state.favoritesMode ? 'lazy' : (index < 8 ? 'eager' : 'lazy');
    img.decoding = 'async';
    if (index < 8) img.fetchPriority = state.favoritesMode ? 'low' : 'high';
    img.alt = t('thumb_alt');
    img.draggable = false;
    img.dataset.workId = w.id;
    const thumbUrl = buildThumbUrlFromWork(w);
    const eagerThumb = !state.favoritesMode && index < 8;
    if (thumbUrl && eagerThumb) img.src = thumbUrl;
    card.appendChild(img);
    try {
      if (window.GalleryVirtual && typeof window.GalleryVirtual.observeCard === 'function') {
        window.GalleryVirtual.observeCard(card, thumbUrl || '', eagerThumb);
      } else if (thumbUrl && !img.src) {
        img.src = thumbUrl;
      }
    } catch {
      if (thumbUrl && !img.src) img.src = thumbUrl;
    }

    const cardLink = document.createElement('a');
    cardLink.className = 'card-link';
    cardLink.href = withGalleryContext(withLangParam(`/i/${encodeURIComponent(String(w.id))}`));
    cardLink.target = '_blank';
    cardLink.rel = 'noopener';
    cardLink.setAttribute('aria-label', (w.title && String(w.title).trim()) ? String(w.title).trim() : t('work_fallback', { id: w.id }));
    card.dataset.workId = String(w.id);
    cardLink.addEventListener('click', (ev) => handleGalleryCardActivate(w, ev));
    card.addEventListener('dblclick', (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const id = w.id;
      if (state.openWorkInNewWindow) {
        window.open(withGalleryContext(withLangParam(`/i/${encodeURIComponent(String(id))}`)), '_blank', 'noopener');
        return;
      }
      state.directDetail = false;
      openDetail(id);
    });
    card.appendChild(cardLink);

    const topRight = document.createElement('div');
    topRight.className = 'card-top-right';
    const imageCount = resolveWorkImageCount(w);
    const pageBadge = document.createElement('span');
    pageBadge.className = 'card-page-badge';
    pageBadge.textContent = CURRENT_LANG === 'zh'
      ? `${imageCount || 0}张`
      : `${imageCount || 0}P`;
    pageBadge.setAttribute('aria-label', CURRENT_LANG === 'zh'
      ? `共 ${imageCount || 0} 张图`
      : `${imageCount || 0} image(s)`);
    topRight.appendChild(pageBadge);
    const favBtn = createFavoriteButton(w.id);
    favBtn.classList.add('fav-btn-card');
    topRight.appendChild(favBtn);
    card.appendChild(topRight);

    try {
      const mode = (sortModeSel && sortModeSel.value) || (sortModeSel2 && sortModeSel2.value) || 'new';
      if (mode === 'monthly') {
        const mets = document.createElement('div');
        mets.className = 'card-metrics';
        const v = document.createElement('span');
        v.className = 'cm-view';
        v.textContent = `${formatMetric(Number(w.total_view || 0))}V`;
        const b = document.createElement('span');
        b.className = 'cm-bookmark';
        b.textContent = `${formatMetric(Number(w.total_bookmarks || 0))}B`;
        mets.appendChild(v);
        mets.appendChild(b);
        card.appendChild(mets);
      }
    } catch { }

    // 左上角类型徽章（不同颜色）
    const typeBadge = document.createElement('div');
    typeBadge.className = 'type-pill ' + typeClass(w.AI_type || '');
    typeBadge.textContent = String(w.AI_type || '').toUpperCase();
    typeBadge.title = t('type_search_tip');
    typeBadge.addEventListener('click', (e) => {
      e.stopPropagation();
      const url = `/?q=${encodeURIComponent(String(w.AI_type || ''))}`;
      window.open(withLangParam(url), '_blank', 'noopener');
    });
    card.appendChild(typeBadge);

    const meta = document.createElement('div');
    meta.className = 'meta';
    const workHref = withGalleryContext(withLangParam(`/i/${encodeURIComponent(String(w.id))}`));
    const titleText = (w.title && String(w.title).trim()) ? String(w.title).trim() : '';
    const titlePart = titleText ? `<div class="meta-title"><a class="meta-link" href="${escapeHtml(workHref)}" target="_blank" rel="noopener">${escapeHtml(titleText)}</a></div>` : '';
    // 移动端简介仅显示 10 个字符；PC 端保持较长（70）；移动端判定扩展为 ≤800px
    const isMobile = window.innerWidth <= 800;
    const capPart = w.caption ? `<div class="meta-caption">${escapeHtml(snippet(w.caption, isMobile ? 10 : 70))}</div>` : '';
    const dateStr = w.create_date ? formatDate(w.create_date) : '';
    const datePart = dateStr ? `<div class="meta-date"><a class="meta-link" href="${escapeHtml(workHref)}" target="_blank" rel="noopener">${escapeHtml(dateStr)}</a></div>` : '';
    meta.innerHTML = `${titlePart}${capPart}${datePart}`;
    try {
      const links = meta.querySelectorAll('.meta-link');
      links.forEach((a) => {
        a.addEventListener('click', (ev) => {
          ev.stopPropagation();
        });
      });
    } catch { }
    card.appendChild(meta);

    if (!isAitagGallery() && shouldEnableHoverPreview()) {
      card.addEventListener('mouseenter', () => scheduleHoverPreview(w.id, card));
      card.addEventListener('mouseleave', () => cancelHoverPreview());
    }
    card.addEventListener('click', (ev) => handleGalleryCardActivate(w, ev));

    try {
      if (!isAitagGallery() && window.CharSwapPlugin && typeof window.CharSwapPlugin.decorateGalleryCard === 'function') {
        window.CharSwapPlugin.decorateGalleryCard(card, w);
      }
    } catch { }

    fragment.appendChild(card);
    const listPage = getWorkListPage(w);
    const nextCount = (visibleCountByPage.get(listPage) || 0) + 1;
    visibleCountByPage.set(listPage, nextCount);
    if (nextCount === adAfterVisibleCount) {
      appendGalleryAd(`page-${listPage}-after-3-rows`);
    }
  });

  galleryEl.appendChild(fragment);

  // 保证哨兵始终位于末尾
  const sentinel = document.getElementById('infiniteSentinel');
  if (sentinel && state.listMode === 'infinite') {
    galleryEl.appendChild(sentinel);
  }

  try {
    if (!isAitagGallery() && window.CharSwapPlugin && typeof window.CharSwapPlugin.onGalleryUpdated === 'function') {
      window.CharSwapPlugin.onGalleryUpdated();
    }
  } catch { }

}

let infiniteObserver = null;
function setupInfiniteScroll() {
  let sentinel = document.getElementById('infiniteSentinel');
  if (!sentinel) {
    sentinel = document.createElement('div');
    sentinel.id = 'infiniteSentinel';
    sentinel.style.height = '1px';
    sentinel.style.margin = '0';
    sentinel.style.visibility = 'hidden';
  }
  // 始终把哨兵置于末尾
  galleryEl.appendChild(sentinel);
  // 每次调用都重新注册观察器，避免旧观察器状态导致只触发一次
  if (infiniteObserver) {
    try { infiniteObserver.disconnect(); } catch { }
    infiniteObserver = null;
  }
  infiniteObserver = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (entry.isIntersecting) {
        const totalPages = Math.max(1, Math.ceil((state.total || 0) / (state.pageSize || 1)));
        const unknownTotal = (state.total <= 0);
        const hasNext = unknownTotal ? (lastPageCount === state.pageSize) : (state.page < totalPages);
        if (hasNext) {
          if (!loadingPage) {
            state.page += 1;
            fetchWorks();
          }
        } else {
          // 无更多数据，注销观察器
          if (infiniteObserver) {
            infiniteObserver.disconnect();
            infiniteObserver = null;
          }
          endReached = true;
          if (loadMoreBtn) loadMoreBtn.classList.add('hidden');
        }
      }
    }
  }, { rootMargin: '400px' });
  infiniteObserver.observe(sentinel);
}


function triggerSearch() {
  // 重置列表与滚动状态
  try { setNoResultMessage(t('no_results')); } catch { }
  state.q = qInput.value.trim();
  state.prompt = promptInput.value.trim();
  state.page = 1;
  state.items = [];
  state.total = 0;
  clearSearchCache();
  try { state.workPages.clear(); } catch { }
  loadingPage = false;
  endReached = false;
  lastPageCount = 0;
  if (infiniteObserver) { infiniteObserver.disconnect(); infiniteObserver = null; }
  const oldSentinel = document.getElementById('infiniteSentinel');
  if (oldSentinel) oldSentinel.remove();
  const url = new URL(window.location.href);
  if (state.q) url.searchParams.set('q', state.q); else url.searchParams.delete('q');
  if (state.prompt) url.searchParams.set('prompt', state.prompt); else url.searchParams.delete('prompt');
  // 新搜索总是回到第 1 页：清掉 URL 里的旧 page，避免刷新/前进后退跳错页
  url.searchParams.delete('page');
  try {
    const mode = (sortModeSel && sortModeSel.value) || (sortModeSel2 && sortModeSel2.value) || 'new';
    const tr = (timeRangeSel && timeRangeSel.value) || (timeRangeSel2 && timeRangeSel2.value) || (mode === 'monthly' ? 'current' : 'all');
    url.searchParams.set('sort', mode);
    url.searchParams.set('time_range', tr);
    const onlineFilters = onlineAdvancedFilters();
    const queryFilters = {
      creator: onlineFilters.creator,
      tags: onlineFilters.tags,
      model: onlineFilters.model,
      min_images: onlineFilters.minImages || '',
      max_images: onlineFilters.maxImages || '',
    };
    Object.entries(queryFilters).forEach(([key, value]) => {
      if (isAitagGallery() && value !== '') url.searchParams.set(key, String(value));
      else url.searchParams.delete(key);
    });
  } catch { }
  history.pushState({ view: 'list' }, '', `${url.pathname}?${url.searchParams.toString()}`);
  try { applyHomeSeo(); } catch { }
  // PC端体验：搜索后强制滚动到顶部，便于查看新结果
  try {
    window.scrollTo({ top: 0, behavior: 'instant' });
    // 某些浏览器不支持 'instant'，兜底：
    setTimeout(() => { window.scrollTo(0, 0); }, 0);
  } catch { window.scrollTo(0, 0); }
  try { if (searchStatusEl) searchStatusEl.classList.add('visible'); } catch { }
  updateAdvancedFilterSummary();
  fetchWorks();
}
searchBtn.addEventListener('click', triggerSearch);
const shuffleBtn = document.getElementById('shuffleBtn');
if (shuffleBtn) {
  shuffleBtn.addEventListener('click', () => {
    shuffleSeed = newShuffleSeed();
    triggerSearch();
  });
}
qInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') triggerSearch(); });
promptInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') triggerSearch(); });
[aitagCreatorInput, aitagTagsInput, aitagMinImagesInput, aitagMaxImagesInput].filter(Boolean).forEach((input) => {
  input.addEventListener('keydown', (event) => { if (event.key === 'Enter') triggerSearch(); });
});
aitagModelSelect?.addEventListener('change', updateAdvancedFilterSummary);
saveBlacklistBtn.addEventListener('click', () => { saveBlacklist(); triggerSearch(); });
const clearFiltersPanelBtn = document.getElementById('clearFiltersPanelBtn');
if (clearFiltersBtn) {
  clearFiltersBtn.addEventListener('click', () => {
    qInput.value = '';
    promptInput.value = '';
    const resetSort = isAitagGallery() ? 'popular' : 'new';
    if (sortModeSel) sortModeSel.value = resetSort;
    if (sortModeSel2) sortModeSel2.value = resetSort;
    if (timeRangeSel) timeRangeSel.value = 'all';
    if (timeRangeSel2) timeRangeSel2.value = 'all';
    if (galleryGroupSel) galleryGroupSel.value = '';
    resetOnlineAdvancedFilters();
    updateAdvancedFilterSummary();
    try { updateGalleryLocation(); } catch { }
    triggerSearch();
    qInput.focus();
  });
}
if (clearFiltersPanelBtn) {
  clearFiltersPanelBtn.addEventListener('click', () => {
    qInput.value = '';
    promptInput.value = '';
    const resetSort = isAitagGallery() ? 'popular' : 'new';
    if (sortModeSel) sortModeSel.value = resetSort;
    if (sortModeSel2) sortModeSel2.value = resetSort;
    if (timeRangeSel) timeRangeSel.value = 'all';
    if (timeRangeSel2) timeRangeSel2.value = 'all';
    if (galleryGroupSel) galleryGroupSel.value = '';
    resetOnlineAdvancedFilters();
    updateAdvancedFilterSummary();
    try { updateGalleryLocation(); } catch { }
    triggerSearch();
    qInput.focus();
  });
}

window.addEventListener('popstate', (e) => {
  const path = window.location.pathname || '/';
  if (path.startsWith('/i/')) {
    const idStr = path.slice(3);
    const id = normalizeWorkId(decodeURIComponent(idStr));
    if (id) {
      // Browser restored a detail URL — do not pushState again.
      state.directDetail = !(e && e.state && e.state.view === 'detail');
      openDetail(id, { skipHistory: true });
      return;
    }
  }
  // Restored a list URL (including after backBtn -> history.back()).
  detailLoadGen += 1;
  saveCurrentDetailScroll();
  state.detailScroll.currentWorkId = null;
  clearDetailScrollRestoreTimers();
  state.directDetail = false;
  if (detailView) {
    detailView.classList.add('hidden');
    detailView.classList.remove('is-open', 'blocked-detail');
  }
  try {
    window.__AITAG_CURRENT_DETAIL__ = null;
    if (window.CharSwapPlugin && typeof window.CharSwapPlugin.unmount === 'function') {
      window.CharSwapPlugin.unmount();
    }
  } catch { }
  try { closePreview(); } catch { }
  if (backBtn) backBtn.style.display = 'none';
  try { applyHomeSeo(); } catch { }
  // Refresh list filters from URL. 必须无条件 initFromQuery：快速后退/前进
  // 穿过多个搜索状态时，URL 已变但内存列表仍是旧查询的结果，只同步输入框
  // 不重取会造成「URL/输入框是新查询、列表是旧结果」的错配。
  try {
    state.favoritesMode = path === '/favorites' || path === '/favorites/';
    state.queueMode = path === '/queue' || path === '/queue/';
    if (state.favoritesMode) applyFavoritesModeUi();
    else if (state.queueMode) applyQueueModeUi();
    initFromQuery();
  } catch {
    try { initFromQuery(); } catch { }
  }
});

function scheduleIdleTask(fn, timeoutMs) {
  try {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(fn, { timeout: timeoutMs || 4000 });
      return;
    }
  } catch { }
  setTimeout(fn, Math.min(timeoutMs || 4000, 2500));
}

async function loadConfig() {
  try {
    let data = {};
    if (window.GalleryBootstrap && typeof window.GalleryBootstrap.loadConfig === 'function') {
      data = await window.GalleryBootstrap.loadConfig(API_BASE);
    } else {
      const res = await window.ApiClient.raw(`${API_BASE}/api/config?v=${CONFIG_REQUEST_VERSION}`);
      if (!res.ok) {
        galleryLoadError('图库配置加载失败');
        return;
      }
      try { data = await res.json(); } catch { data = {}; }
    }
	      CONFIG = { ...CONFIG, ...data };
	      applyGalleryAssetBase();
	      applyUserPrefs(data.user_prefs || CONFIG.user_prefs);
	      state.pageSize = CONFIG.page_size || state.pageSize;
	      state.listMode = normalizeListMode(CONFIG.list_mode || 'infinite');
	      scheduleSearchAdPreload();
	      const years = Array.isArray(data.available_years) ? data.available_years : [];
      const months = Array.isArray(data.available_months) ? data.available_months : [];
      if (sortModeSel && sortModeSel.value === 'monthly') {
        rebuildMonthlyOptions(months);
      } else {
        rebuildTimeOptions();
      }
      if (timeRangeSel2 && timeRangeSel) timeRangeSel2.innerHTML = timeRangeSel.innerHTML;
      if (sortModeSel && timeRangeSel && !sortModeSel.dataset.boundSort) {
        sortModeSel.dataset.boundSort = '1';
        sortModeSel.addEventListener('change', () => {
          const mode = sortModeSel.value || 'new';
          if (mode === 'monthly') {
            rebuildMonthlyOptions(months);
            timeRangeSel.value = 'current';
            if (sortModeSel2) sortModeSel2.value = mode;
            if (timeRangeSel2) timeRangeSel2.value = timeRangeSel.value;
          } else {
            rebuildTimeOptions();
            timeRangeSel.value = 'all';
            if (sortModeSel2) sortModeSel2.value = mode;
            if (timeRangeSel2) timeRangeSel2.value = timeRangeSel.value;
          }
          triggerSearch();
        });
      }
      if (sortModeSel2 && timeRangeSel2 && !sortModeSel2.dataset.boundSort) {
        sortModeSel2.dataset.boundSort = '1';
        sortModeSel2.addEventListener('change', () => {
          const mode = sortModeSel2.value || 'new';
          if (sortModeSel) sortModeSel.value = mode;
          if (mode === 'monthly') {
            rebuildMonthlyOptions(months);
            timeRangeSel2.value = 'current';
            if (timeRangeSel) timeRangeSel.value = timeRangeSel2.value;
          } else {
            rebuildTimeOptions();
            timeRangeSel2.value = 'all';
            if (timeRangeSel) timeRangeSel.value = timeRangeSel2.value;
          }
          triggerSearch();
        });
      }
      if (timeRangeSel && !timeRangeSel.dataset.boundTime) {
        timeRangeSel.dataset.boundTime = '1';
        timeRangeSel.addEventListener('change', () => {
          if (timeRangeSel2) timeRangeSel2.value = timeRangeSel.value;
          triggerSearch();
        });
      }
      if (timeRangeSel2 && !timeRangeSel2.dataset.boundTime) {
        timeRangeSel2.dataset.boundTime = '1';
        timeRangeSel2.addEventListener('change', () => {
          if (timeRangeSel) timeRangeSel.value = timeRangeSel2.value;
          triggerSearch();
        });
      }
      // Populate homepage announcement
      try {
        const annZh = String(data.homepage_announcement_zh || '').trim();
        const annEn = String(data.homepage_announcement_en || '').trim();
        const annEl = document.getElementById('heroAnnouncement');
        const annZhEl = document.getElementById('heroAnnouncementZh');
        const annEnEl = document.getElementById('heroAnnouncementEn');
        if (annEl && (annZh || annEn)) {
          if (annZhEl) annZhEl.textContent = annZh;
          if (annEnEl) annEnEl.textContent = annEn;
          annEl.classList.remove('hidden');
        }
      } catch { }
      renderStoragePathFooter(data.storage_paths || CONFIG.storage_paths);
  } catch {
    galleryLoadError('图库配置加载失败');
  }
}

function applyListMode() {
  if (!paginationEl) return;
  if (state.listMode === 'infinite') {
    paginationEl.style.display = 'none';
    // 切换到无限模式时，清理旧观察器
    if (infiniteObserver) { infiniteObserver.disconnect(); infiniteObserver = null; }
    const oldSentinel = document.getElementById('infiniteSentinel');
    if (oldSentinel) oldSentinel.remove();
    if (loadMoreBtn) {
      loadMoreBtn.classList.remove('hidden');
    }
  } else {
    paginationEl.style.display = 'flex';
    if (infiniteObserver) { infiniteObserver.disconnect(); infiniteObserver = null; }
    const oldSentinel = document.getElementById('infiniteSentinel');
    if (oldSentinel) oldSentinel.remove();
    if (loadMoreBtn) {
      loadMoreBtn.classList.add('hidden');
    }
  }
}

function initFromQuery() {
  const url = new URL(window.location.href);
  const q = url.searchParams.get('q') ?? '';
  const prompt = url.searchParams.get('prompt') || '';
  const pageStr = url.searchParams.get('page');
  const sortModeQ = url.searchParams.get('sort') || (isAitagGallery() ? 'popular' : 'new');
  const timeRangeQ = url.searchParams.get('time_range') || (sortModeQ === 'monthly' ? 'current' : 'all');
  if (aitagCreatorInput) aitagCreatorInput.value = url.searchParams.get('creator') || '';
  if (aitagTagsInput) aitagTagsInput.value = url.searchParams.get('tags') || '';
  if (aitagModelSelect) aitagModelSelect.value = url.searchParams.get('model') || '';
  if (aitagMinImagesInput) aitagMinImagesInput.value = url.searchParams.get('min_images') || '';
  if (aitagMaxImagesInput) aitagMaxImagesInput.value = url.searchParams.get('max_images') || '';
  // 假值也要写回：后退到无 q/page 的 URL 时，旧搜索词与页码必须清掉
  state.q = q;
  state.prompt = prompt;
  state.page = 1;
  if (pageStr) {
    const p = parseInt(pageStr, 10);
    if (!Number.isNaN(p) && p >= 1) state.page = p;
  }
  if (sortModeSel) sortModeSel.value = sortModeQ;
  if (sortModeSel2) sortModeSel2.value = sortModeQ;
  if (sortModeSel && sortModeQ === 'monthly') rebuildMonthlyOptions(CONFIG.available_months || []); else rebuildTimeOptions();
  if (timeRangeSel) timeRangeSel.value = timeRangeQ;
  if (timeRangeSel2) timeRangeSel2.value = timeRangeQ;
  qInput.value = state.q;
  promptInput.value = state.prompt;
  if (fcInput) fcInput.value = String(state.page);
  if (fcNum) fcNum.textContent = String(state.page);
  fetchWorks();
}

// initial load
async function initRouter() {
  const path = window.location.pathname || '/';
  state.favoritesMode = path === '/favorites' || path === '/favorites/';
  state.queueMode = path === '/queue' || path === '/queue/';
  initInspirationSidebar();
  try {
    if (window.GalleryVirtual && typeof window.GalleryVirtual.init === 'function') {
      window.GalleryVirtual.init(galleryEl);
    }
  } catch { }
  loadBlacklist();
		  loadOpenWorkInNewWindow();
		  loadInvalidTagFilterSettings();
		  loadCachedFavorites();
		  if (!state.favoritesMode) loadFavorites().catch(() => {});
		  loadQueue().catch(() => {});
		  loadGalleryHierarchy().catch(() => renderGalleryGroups([]));
  const configPromise = loadConfig().catch(() => {});
  applyLocalGalleryUi();
  updateGallerySourceUi();
  if (state.favoritesMode) applyFavoritesModeUi();
  if (state.queueMode) applyQueueModeUi();
  if (CONFIG.tag_translate_enabled !== false && CURRENT_LANG === 'zh') {
    scheduleIdleTask(() => {
      const run = () => {
        if (typeof TagI18n === 'undefined') return;
        TagI18n.load().then(() => {
          try { if (TagI18n.ready) refreshCurrentGallery({ preserveScroll: true }); } catch { }
        }).catch(() => {});
      };
      if (window.DeferredScripts && typeof window.DeferredScripts.load === 'function') {
        window.DeferredScripts.load('/assets/tag_i18n.js?v=cadf4820cd').then(run).catch(() => {});
      } else {
        run();
      }
    }, 5000);
  }
  scheduleIdleTask(() => {
    if (!isAitagGallery() && window.GalleryBootstrap && typeof window.GalleryBootstrap.refreshSetupBanner === 'function') {
      window.GalleryBootstrap.refreshSetupBanner(API_BASE)
        .catch(() => {})
        .finally(() => {
          if (isAitagGallery()) document.getElementById('setupBanner')?.classList.add('hidden');
        });
    }
  }, 6000);
  if (oldBlacklistMigrationEnabled()) {
    const importedFromWindow = importBlacklistFromWindowNameIfNeeded();
    const importedFromHash = importBlacklistFromHashIfNeeded();
    if (importedFromWindow || importedFromHash) {
      try { loadBlacklist(); } catch { }
    }
  }
  migrateBlacklistFromOldDomainInBackground();
  try { applyStaticI18n(); } catch { }
  updateAdvancedFilterSummary();
  try { applyHomeSeo(); } catch { }
  if (path.startsWith('/i/')) {
    const idStr = path.slice(3);
    const id = normalizeWorkId(decodeURIComponent(idStr));
    if (id) {
      state.directDetail = true;
      openDetail(id);
      return;
    }
  }
  state.directDetail = false;
  applyListMode();
  initFromQuery();
  configPromise.then(() => {
    try { applyLocalGalleryUi(); } catch { }
    try { if (state.favoritesMode) applyFavoritesModeUi(); } catch { }
    try { if (state.queueMode) applyQueueModeUi(); } catch { }
    try { applyStaticI18n(); } catch { }
    updateGallerySourceUi();
    updateAdvancedFilterSummary();
    try { applyHomeSeo(); } catch { }
  }).catch(() => {});
}

initRouter();
	if (openWorkNewWindowToggle) {
	  openWorkNewWindowToggle.addEventListener('change', () => {
	    setOpenWorkInNewWindow(!!openWorkNewWindowToggle.checked);
	  });
	}
	if (showSuspectInvalidTagToggle) {
	  showSuspectInvalidTagToggle.addEventListener('change', () => {
	    setShowSuspectInvalidTags(!!showSuspectInvalidTagToggle.checked);
	  });
	}
	if (showNaixInvalidTagToggle) {
	  showNaixInvalidTagToggle.addEventListener('change', () => {
	    setShowNaixInvalidTags(!!showNaixInvalidTagToggle.checked);
	  });
	}

// 右下角控件逻辑
function toggleHeaderVisibility(show) {
  // 按用户要求：不再隐藏顶部搜索栏，无论何时都保持显示。
  const header = document.querySelector('.site-header');
  if (!header) return;
  const searchRow = header.querySelector('.search-row');
  const blockRow = header.querySelector('.blocklist-row');
  const setRow = (row) => {
    if (!row) return;
    try {
      row.classList.remove('hidden');
      row.style.display = 'flex';
    } catch { }
  };
  setRow(searchRow);
  setRow(blockRow);
}

function applyJumpPage(p) {
  if (Number.isNaN(p) || p < 1) return;
  // 重置瀑布流状态，并从指定页加载
  state.page = p;
  state.items = [];
  endReached = false;
  lastPageCount = 0;
  loadingPage = false;
  // 清空现有内容并重新加载
  galleryEl.innerHTML = '';
  // 清理旧观察器与哨兵
  if (infiniteObserver) { try { infiniteObserver.disconnect(); } catch { } infiniteObserver = null; }
  const oldSentinel = document.getElementById('infiniteSentinel');
  if (oldSentinel) oldSentinel.remove();
  // 更新URL中的page参数，保留现有查询参数
  const url = new URL(window.location.href);
  url.searchParams.set('page', String(p));
  const newUrl = `${url.pathname}${url.search}${url.hash}`;
  history.pushState({ view: 'list' }, '', newUrl);
  // 同步控件显示
  if (fcNum) fcNum.textContent = String(p);
  if (fcInput) fcInput.value = String(p);
  fetchWorks();
}

if (fcChip) {
  // Esc 关闭页码面板（与快捷面板行为一致）
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && fcPanel && !fcPanel.classList.contains('hidden')) {
      fcPanel.classList.add('hidden');
    }
  });
  fcChip.addEventListener('click', () => {
    const panelVisible = !fcPanel.classList.contains('hidden');
    if (panelVisible) {
      fcPanel.classList.add('hidden');
    } else {
      openFcPanel();
    }
    if (!panelVisible && fcInput) fcInput.focus();

    // 始终保持顶部搜索栏显示（不再隐藏）
    toggleHeaderVisibility(true);

    try {
      if (!panelVisible) {
        const fcQ = document.getElementById('fcQ');
        const fcPrompt = document.getElementById('fcPrompt');
        const fcSearchBtn = document.getElementById('fcSearchBtn');
        const fcBlacklist = document.getElementById('fcBlacklist');
        const fcSaveBlacklistBtn = document.getElementById('fcSaveBlacklistBtn');

        if (fcQ && qInput) fcQ.value = qInput.value || '';
        if (fcPrompt && promptInput) fcPrompt.value = promptInput.value || '';
        if (fcBlacklist && blacklistInput) fcBlacklist.value = blacklistInput.value || '';

        if (fcPanel && !fcPanel.dataset.wired) {
          fcPanel.dataset.wired = '1';
          try {
            if (fcQ && qInput) {
              fcQ.addEventListener('input', () => { try { qInput.value = fcQ.value || ''; } catch { } });
              qInput.addEventListener('input', () => { try { fcQ.value = qInput.value || ''; } catch { } });
            }
          } catch { }
          try {
            if (fcPrompt && promptInput) {
              fcPrompt.addEventListener('input', () => { try { promptInput.value = fcPrompt.value || ''; } catch { } });
              promptInput.addEventListener('input', () => { try { fcPrompt.value = promptInput.value || ''; } catch { } });
            }
          } catch { }
          try {
            if (fcBlacklist && blacklistInput) {
              fcBlacklist.addEventListener('input', () => { try { blacklistInput.value = fcBlacklist.value || ''; } catch { } });
              blacklistInput.addEventListener('input', () => { try { fcBlacklist.value = blacklistInput.value || ''; } catch { } });
            }
          } catch { }
        }

        if (fcSearchBtn) fcSearchBtn.onclick = () => {
          try {
            if (fcQ && qInput) qInput.value = fcQ.value || '';
            if (fcPrompt && promptInput) promptInput.value = fcPrompt.value || '';
          } catch { }
          triggerSearch();
        };
		        if (fcSaveBlacklistBtn) fcSaveBlacklistBtn.onclick = () => {
		          try { if (fcBlacklist && blacklistInput) blacklistInput.value = fcBlacklist.value || ''; } catch { }
		          saveBlacklist();
		          refreshCurrentGallery({ preserveScroll: true });
		        };
      }
    } catch { }
  });
}

if (fcGo && fcInput) {
  fcGo.addEventListener('click', () => {
    const p = parseInt(fcInput.value || '1', 10);
    applyJumpPage(p);
  });
  fcInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const p = parseInt(fcInput.value || '1', 10);
      applyJumpPage(p);
    }
  });
}

function renderPagination() {
  if (!paginationEl) return;
  const knownTotal = (state.total > 0);
  const totalPages = knownTotal
    ? Math.max(1, Math.ceil(state.total / (state.pageSize || 1)))
    : Math.max(state.page + (lastPageCount >= state.pageSize ? 1 : 0), 1);
  const groupStart = Math.floor((state.page - 1) / 10) * 10 + 1;
  const groupEnd = Math.min(groupStart + 9, totalPages);

  paginationEl.innerHTML = '';
  paginationEl.style.display = 'flex';

  const makeBtn = (label, page, opts = {}) => {
    const btn = document.createElement('button');
    btn.className = 'page-btn' + (opts.active ? ' active' : '') + (opts.disabled ? ' disabled' : '');
    btn.textContent = label;
    if (!opts.disabled) {
      btn.addEventListener('click', () => {
        if (opts.active) return;
        state.page = page;
        closePreview();
        fetchWorks();
        window.scrollTo({ top: 0, behavior: 'smooth' });
      });
    }
    paginationEl.appendChild(btn);
  };

  if (state.page > 1) {
    makeBtn(CURRENT_LANG === 'zh' ? '上一页' : 'Prev', state.page - 1);
  }

  if (groupStart > 1) {
    makeBtn(t('prev_group'), groupStart - 10);
  }

  for (let p = groupStart; p <= groupEnd; p++) {
    makeBtn(String(p), p, { active: p === state.page });
  }

  const canNext = knownTotal
    ? state.page < totalPages
    : (lastPageCount >= state.pageSize);
  if (groupEnd < totalPages) {
    makeBtn(t('next_group'), groupEnd + 1);
  } else if (canNext && state.page >= groupEnd) {
    makeBtn(CURRENT_LANG === 'zh' ? '下一页' : 'Next', state.page + 1);
  }

  if (knownTotal) {
    const info = document.createElement('span');
    info.className = 'page-info';
    info.textContent = CURRENT_LANG === 'zh'
      ? `共 ${state.total.toLocaleString('zh-CN')} 条`
      : `${state.total.toLocaleString()} results`;
    paginationEl.appendChild(info);
  }
}

// “加载更多”按钮：在无限模式下作为兜底加载下一页
if (loadMoreBtn) {
  loadMoreBtn.addEventListener('click', () => {
    if (state.listMode !== 'infinite') return;
    const unknownTotal = (state.total <= 0);
    const totalPages = Math.max(1, Math.ceil((state.total || 0) / (state.pageSize || 1)));
    const endReached = unknownTotal
      ? (lastPageCount < state.pageSize)
      : (state.page >= totalPages);
    if (endReached) {
      loadMoreBtn.classList.add('hidden');
      return;
    }
    if (loadingPage) return;
    state.page += 1;
    fetchWorks();
  });
}

const galleryListRuntime = window.GalleryListRuntime.create({
  state,
  apiBase: API_BASE,
  applyGalleryParams,
  isAitagGallery,
  adaptAitagWork,
  getSortMode: () => (sortModeSel && sortModeSel.value) || (sortModeSel2 && sortModeSel2.value) || 'new',
  getTimeRange: () => (timeRangeSel && timeRangeSel.value) || (timeRangeSel2 && timeRangeSel2.value) || 'all',
  translate: t,
  currentLanguage: () => CURRENT_LANG,
  visibleWorks,
  getWorkListPage,
  isDetailView: () => !!(detailView && !detailView.classList.contains('hidden')),
});

function buildWorksListUrl(page = state.page) {
  return galleryListRuntime.buildWorksListUrl(page);
}

async function fetchWorksListPage(page = state.page) {
  return galleryListRuntime.fetchWorksListPage(page);
}

galleryListRuntime.mount();

window.currentGalleryId = currentGalleryId;
window.loadGalleryHierarchy = loadGalleryHierarchy;
window.triggerSearch = triggerSearch;
window.fetchWorks = fetchWorks;

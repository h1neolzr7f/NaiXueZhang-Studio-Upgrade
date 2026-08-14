const API_BASE = window.location.origin; // assume same host

const inspirationState = { workId: null, work: null, promptReq: 0 };
let userPrefs = {
  nai_only_gallery: true,
  quick_send_studio: false,
  default_optimize_mode: 'smart',
  show_other_ai_types: false,
};

function initInspirationSidebar() {
  const sidebar = document.getElementById('inspirationSidebar');
  const toggle = document.getElementById('inspirationToggle');
  const toStudio = document.getElementById('inspirationToStudio');
  const toRemix = document.getElementById('inspirationToRemix');
  const toQueue = document.getElementById('inspirationToQueue');
  const openDetailBtn = document.getElementById('inspirationOpenDetail');
  if (!sidebar) return;
  try {
    const saved = localStorage.getItem('aitag.inspirationSidebarOpen');
    sidebar.classList.toggle('open', saved === '1');
  } catch { }
  toggle?.addEventListener('click', () => {
    sidebar.classList.toggle('open');
    try {
      localStorage.setItem('aitag.inspirationSidebarOpen', sidebar.classList.contains('open') ? '1' : '0');
    } catch { }
  });
  toStudio?.addEventListener('click', () => {
    if (!inspirationState.workId || !window.WorkBridge) return;
    if (typeof isAitagGallery === 'function' && isAitagGallery()) {
      if (typeof openOnlineRemixPanel === 'function') {
        Promise.resolve(openOnlineRemixPanel(inspirationState.workId, 'draft'))
          .catch((err) => reportAsyncError('打开换角面板失败', err));
      }
      return;
    }
    const gid = typeof currentGalleryId === "function" ? currentGalleryId() : "site";
    window.WorkBridge.go('/studio', inspirationState.workId, 0, gid);
  });
  toRemix?.addEventListener('click', () => {
    if (!inspirationState.workId || !window.WorkBridge) return;
    if (typeof isAitagGallery === 'function' && isAitagGallery()) {
      if (typeof openOnlineRemixPanel === 'function') {
        Promise.resolve(openOnlineRemixPanel(inspirationState.workId, 'remix'))
          .catch((err) => reportAsyncError('打开换角面板失败', err));
      }
      return;
    }
    const gid = typeof currentGalleryId === "function" ? currentGalleryId() : "site";
    window.WorkBridge.go('/remix', inspirationState.workId, 0, gid);
  });
  openDetailBtn?.addEventListener('click', () => {
    if (!inspirationState.workId) return;
    openDetail(inspirationState.workId);
  });
  toQueue?.addEventListener('click', async () => {
    if (!inspirationState.workId) return;
    if (typeof isAitagGallery === 'function' && isAitagGallery()) return;
    const on = await toggleQueue(inspirationState.workId);
    toQueue.textContent = on ? '已入队 ✓' : '加入待生成';
    toQueue.classList.toggle('primary', on);
  });
}

async function loadInspirationPrompt(workId) {
  const el = document.getElementById('inspirationPrompt');
  if (!el || !workId) return;
  if (typeof isAitagGallery === 'function' && isAitagGallery()) {
    el.textContent = CURRENT_LANG === 'zh'
      ? '在线资产：打开详情查看 Prompt，建立草稿后再进入 Studio。'
      : 'Online asset: open details, then prepare a Studio draft.';
    el.classList.remove('is-loading');
    return;
  }
  if (userPrefs.quick_send_studio) {
    el.textContent = CURRENT_LANG === 'zh' ? '已开启快捷进工作台，咒语在工作室查看' : 'Quick studio on — open Studio for prompt';
    return;
  }
  const reqId = ++inspirationState.promptReq;
  el.textContent = CURRENT_LANG === 'zh' ? '加载咒语摘要…' : 'Loading prompt…';
  el.classList.add('is-loading');
  try {
    const preview = window.PromptPreview;
    const snippet = preview && typeof preview.fetchSnippet === 'function'
      ? await preview.fetchSnippet(workId, 0, API_BASE)
      : '';
    if (reqId !== inspirationState.promptReq) return;
    el.textContent = snippet || (CURRENT_LANG === 'zh' ? '（无咒语元数据）' : '(no prompt metadata)');
  } catch {
    if (reqId !== inspirationState.promptReq) return;
    el.textContent = CURRENT_LANG === 'zh' ? '咒语加载失败' : 'Failed to load prompt';
  } finally {
    if (reqId === inspirationState.promptReq) el.classList.remove('is-loading');
  }
}

function applyUserPrefs(prefs) {
  if (!prefs || typeof prefs !== 'object') return;
  userPrefs = {
    ...userPrefs,
    nai_only_gallery: !!prefs.nai_only_gallery,
    quick_send_studio: !!prefs.quick_send_studio,
    default_optimize_mode: String(prefs.default_optimize_mode || 'smart'),
    show_other_ai_types: !!prefs.show_other_ai_types,
  };
  const empty = document.getElementById('inspirationEmpty');
  if (empty) {
    empty.textContent = userPrefs.quick_send_studio
      ? (CURRENT_LANG === 'zh'
        ? '高级快捷模式：单击会进入生图工作台；关闭后单击查看详情与全部图片'
        : 'Advanced quick mode: single-click opens Studio; turn it off to view all images')
      : (CURRENT_LANG === 'zh'
        ? '单击查看详情与全部图片；侧边栏可预览咒语并送去生成或洗稿'
        : 'Single-click opens details and all images; use sidebar for Studio or Remix');
  }
}

function handleGalleryCardActivate(work, ev) {
  if (ev) {
    if (ev.target.closest('.meta-link, .type-pill, .fav-btn-card, .card-metrics, .card-page-badge')) return;
    ev.preventDefault();
    ev.stopPropagation();
  }
  if (!work || !work.id) return;
  selectInspirationWork(work);
  const id = work.id;
  if (typeof isAitagGallery === 'function' && isAitagGallery() && userPrefs.quick_send_studio) {
    if (typeof openOnlineRemixPanel === 'function') {
      Promise.resolve(openOnlineRemixPanel(id, 'remix'))
        .catch((err) => reportAsyncError('打开换角面板失败', err));
    }
    return;
  }
  if (userPrefs.quick_send_studio && window.WorkBridge) {
    window.WorkBridge.go('/studio', id, 0);
    return;
  }
  if (typeof state !== 'undefined' && state.openWorkInNewWindow) {
    window.open(withGalleryContext(withLangParam(`/i/${encodeURIComponent(String(id))}`)), '_blank', 'noopener');
    return;
  }
  if (typeof state !== 'undefined') state.directDetail = false;
  openDetail(id);
}

function selectInspirationWork(work) {
  if (!work || !work.id) return;
  inspirationState.workId = normalizeWorkId(work.id);
  inspirationState.work = work;
  document.querySelectorAll('.card.inspiration-selected').forEach((el) => el.classList.remove('inspiration-selected'));
  const card = document.querySelector(`.card[data-work-id="${work.id}"]`);
  if (card) card.classList.add('inspiration-selected');
  const empty = document.getElementById('inspirationEmpty');
  const body = document.getElementById('inspirationBody');
  const thumb = document.getElementById('inspirationThumb');
  const title = document.getElementById('inspirationTitle');
  const meta = document.getElementById('inspirationMeta');
  if (empty) empty.classList.add('hidden');
  if (body) body.classList.remove('hidden');
  const cover = work.cover_url || work.thumb || work.preview_url || '';
  if (thumb) {
    thumb.src = cover.startsWith('http') ? cover : (API_BASE + (cover.startsWith('/') ? cover : `/${cover}`));
    thumb.alt = work.title || `work ${work.id}`;
  }
  if (title) title.textContent = (work.title && String(work.title).trim()) ? work.title : t('work_fallback', { id: work.id });
  const wtype = String(work.AI_type || work.ai_type || '').toUpperCase();
  if (meta) meta.textContent = `#${work.id} · ${wtype || 'NAI'}`;
  loadInspirationPrompt(work.id);
  const sidebar = document.getElementById('inspirationSidebar');
  if (sidebar && !sidebar.classList.contains('open')) sidebar.classList.add('open');
}

function normalizeListMode(mode) {
  const m = String(mode || 'infinite').trim().toLowerCase();
  if (m === 'paged' || m === 'page' || m === 'pagination') return 'pagination';
  return 'infinite';
}
let CONFIG = {
  asset_base_url: '',
  page_size: 60,
  redis_enabled: false,
  list_mode: 'infinite',
  announce_enabled: false,
  ads_enabled: false,
  ads: [],
  old_blacklist_migrate_enabled: false,
};

const SITE_TITLE_ZH = 'Pixiv NAI 本地图库';
const SITE_TITLE_EN = 'Pixiv NAI Gallery';
const HOME_DESC_ZH = '从 Pixiv 发现候选作品，经本地 NovelAI 元数据严格验证后入库。';
const HOME_DESC_EN = 'Candidates are discovered on Pixiv and admitted only after strict local NovelAI metadata verification.';

function renderStoragePathFooter(paths) {
  const el = document.getElementById('storagePathFooter');
  if (!el || !paths || !paths.images_dir) return;
  const images = String(paths.images_dir || '');
  const generated = String(paths.generated_dir || '');
  const isZh = CURRENT_LANG === 'zh';
  el.replaceChildren();
  el.append(isZh ? '本地图片目录：' : 'Images: ');
  const imgCode = document.createElement('code');
  imgCode.title = images;
  imgCode.textContent = images;
  el.appendChild(imgCode);
  const imgBtn = document.createElement('button');
  imgBtn.type = 'button';
  imgBtn.className = 'js-open-storage';
  imgBtn.dataset.target = 'images';
  imgBtn.textContent = isZh ? '打开' : 'Open';
  el.appendChild(imgBtn);
  el.append(isZh ? ' · 生成图：' : ' · Generated: ');
  const genCode = document.createElement('code');
  genCode.title = generated;
  genCode.textContent = generated;
  el.appendChild(genCode);
  const genBtn = document.createElement('button');
  genBtn.type = 'button';
  genBtn.className = 'js-open-storage';
  genBtn.dataset.target = 'generated';
  genBtn.textContent = isZh ? '打开' : 'Open';
  el.appendChild(genBtn);
  el.append(' · ');
  const allLink = document.createElement('a');
  allLink.href = '/progress';
  allLink.textContent = isZh ? '查看全部路径' : 'All paths';
  el.appendChild(allLink);
  el.querySelectorAll('.js-open-storage').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        const res = await window.ApiClient.raw(`${API_BASE}/api/storage/open?target=${encodeURIComponent(btn.dataset.target || 'images')}`, {
          method: 'POST',
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
      } catch (err) {
        alert(String(err && err.message ? err.message : err));
      }
    });
  });
}

function getLangParamRaw() {
  try {
    const url = new URL(window.location.href);
    return String(url.searchParams.get('lang') || '').trim().toLowerCase();
  } catch {
    return '';
  }
}
function normalizeLangFromParam(raw) {
  const v = String(raw || '').trim().toLowerCase();
  if (v === 'us') return 'en';
  if (v === 'cn' || v === 'zh') return 'zh';
  return '';
}
const LANG_PARAM_RAW = getLangParamRaw();
const CURRENT_LANG = normalizeLangFromParam(LANG_PARAM_RAW) || 'zh';
try { window.GALLERY_LANG = CURRENT_LANG; } catch { }

const I18N = {
  zh: {
    search_placeholder_q: '在本地已入库库内搜索：角色 / 标签 / ID / 作者 / 咒语',
    search_placeholder_prompt: '搜索:NAI和SD AI元数据Prompt(不含负面词和ComfyUI)',
    sort_label: '排序',
    sort_new: '新作品排序',
    sort_count: '按图片数量',
    sort_monthly: '每月排行榜',
    time_range_label: '时间范围',
    time_all: '全部时间',
    time_full_year: ({ year }) => `${year}全年`,
    time_quarter: ({ year, quarter }) => `${year}第${quarter}季度`,
    time_older: '更老(2023年9月之前)',
    time_current_month: '当前月份',
    btn_search: '搜索',
    blacklist_placeholder: '黑名单屏蔽关键词(逗号/空格分隔,不屏蔽AI元数据)',
    btn_save_blacklist: '保存黑名单',
    status_searching: '搜索中…',
    no_results: '无搜索结果',
    loading: '载入中…',
    loading_failed: '载入失败',
    rank_processing: '排行榜正在处理中，请等待2小时后查看',
    rank_snapshot_hint: '月榜来自本地数据库快照；Pixiv 采集更新后排行才会变化。',
    load_more: '加载更多',
    jump_label: '跳至第',
	    jump_placeholder: '页码',
	    btn_go: '跳转',
	    open_work_new_window: '新窗口打开作品',
	    show_suspect_invalid_tags: '显示疑似无效TAG作品',
	    show_naix_invalid_tags: '显示NAI_X无效TAG作品',
	    fc_chip_label: '设置与页码',
    fc_q_placeholder: '搜索：id/作者id/简介/tags/日期/类型/模型',
    fc_prompt_placeholder: '搜索：NAI/SD元数据Prompt',
    fc_blacklist_placeholder: '黑名单屏蔽关键词(逗号/空格分隔)',
    preview_alt: '预览',
    back_btn: '← 返回列表',
    back_to_gallery: '← 返回图库',
    detail_header: '作品详情',
    home_alt: 'Pixiv NAI 本地图库',
    home_title: '返回首页',
    thumb_alt: '缩略图',
    type_search_tip: '点击按类型搜索',
    naix_suspect: '疑无效TAG',
    naix_suspect_bracket: '[疑无效TAG]',
    naix_suspect_paren: '（疑无效TAG）',
    non_standard_format: '非标准格式',
    non_standard_format_bracket: '[非标准格式]',
    non_standard_format_paren: '（非标准格式）',
    non_standard_format_tip: '这是来自 tensor.art 网址在线生成流，并非正确的 ComfyUI 工作流',
    work_fallback: ({ id }) => `作品 ${id}`,
    images_count: ({ n }) => `${n} 张`,
    err_network: '网络错误',
    err_work_not_found: '本地库中未找到该作品（可能尚未爬取详情）',
    err_search_failed: '搜索失败，请稍后重试',
    show_full_meta: '显示完整 AI 元数据',
    dm_pixiv_id: 'Pixiv ID',
    dm_author: '作者',
    dm_type: '类型',
    dm_tags: '标签（中文优先，悬停看原文）',
    tag_original_title: '原文',
    dm_caption: '作品简介',
    dm_posted_at: '投稿时间',
    dm_unknown: '未知',
    dm_none: '无',
    dm_views: '浏览',
    dm_bookmarks: '收藏',
    caption_show_all: '显示全部简介',
    caption_collapse: '折叠简介',
    ai_meta_mode: 'AI元数据模式',
    copy_json: '复制 JSON',
    copy_instruction: '复制指令',
    copied: '已复制',
    copy_failed: '复制失败',
    copy_failed_manual: '复制失败，请手动复制:\n\n',
    show_all: '显示全部',
    collapse: '折叠',
    copy_all_image_links: '复制全部图片链接',
    no_links_to_copy: '无可复制链接',
    copied_n_links: ({ n }) => `已复制 ${n} 条链接`,
    copy_failed_popup: '复制失败，已弹出文本',
    prev_group: '上一组',
    next_group: '下一组',
    seo_tags_prefix: '标签',
    seo_ai_meta_prefix: 'AI元数据',
    lang_btn_zh: '中文',
    lang_btn_en: 'EN',
    btn_import_blacklist: '导入旧域名黑名单',
    import_blacklist_popup_blocked: '弹窗被浏览器拦截，请允许本站弹窗后再点一次',
    import_blacklist_starting: '正在从旧域名导入…',
    import_blacklist_done: '已导入旧域名黑名单',
    import_blacklist_failed: '导入失败（可能旧域名禁止被 iframe 嵌入或无旧数据）',
  },
  en: {
    search_placeholder_q: 'Search: work id / author id / caption / tags / date / AI type / model (supports -exclude, OR, and quoted exact match)',
    search_placeholder_prompt: 'Search: NAI & SD AI metadata prompt (no negative / no ComfyUI)',
    sort_label: 'Sort',
    sort_new: 'Newest',
    sort_count: 'By image count',
    sort_monthly: 'Monthly ranking',
    time_range_label: 'Time range',
    time_all: 'All time',
    time_full_year: ({ year }) => `${year} (full year)`,
    time_quarter: ({ year, quarter }) => `${year} Q${quarter}`,
    time_older: 'Older (before 2023-09)',
    time_current_month: 'Current month',
    btn_search: 'Search',
    blacklist_placeholder: 'Block keywords (comma/space separated; does not block AI metadata)',
    btn_save_blacklist: 'Save blocklist',
    status_searching: 'Searching…',
    no_results: 'No results',
    loading: 'Loading…',
    loading_failed: 'Load failed',
    rank_processing: 'The ranking is being processed. Please check again after 2 hours.',
    rank_snapshot_hint: 'Monthly rank is a local database snapshot; run Pixiv intake to refresh it.',
    load_more: 'Load more',
    jump_label: 'Go to',
	    jump_placeholder: 'Page',
	    btn_go: 'Go',
	    open_work_new_window: 'Open works in a new window',
	    show_suspect_invalid_tags: 'Show suspect invalid-tag works',
	    show_naix_invalid_tags: 'Show NAI_X invalid-tag works',
	    fc_chip_label: 'Settings & page',
    fc_q_placeholder: 'Search: id / author / caption / tags / date / type / model',
    fc_prompt_placeholder: 'Search: NAI/SD metadata prompt',
    fc_blacklist_placeholder: 'Block keywords (comma/space separated)',
    preview_alt: 'Preview',
    back_btn: '← Back to list',
    back_to_gallery: '← Back to gallery',
    detail_header: 'Work details',
    home_alt: 'Pixiv NAI Gallery',
    home_title: 'Back to home',
    thumb_alt: 'Thumbnail',
    type_search_tip: 'Search by type',
    naix_suspect: 'Suspect invalid tags',
    naix_suspect_bracket: '[Suspect invalid tags]',
    naix_suspect_paren: '(Suspect invalid tags)',
    non_standard_format: 'Non-standard format',
    non_standard_format_bracket: '[Non-standard format]',
    non_standard_format_paren: '(Non-standard format)',
    non_standard_format_tip: 'Generated from tensor.art online workflow; not a proper ComfyUI workflow.',
    work_fallback: ({ id }) => `Work ${id}`,
    images_count: ({ n }) => `${n} images`,
    err_network: 'Network error',
    err_work_not_found: 'Work not found in local library (details may not be crawled yet)',
    err_search_failed: 'Search failed, please try again later',
    dm_pixiv_id: 'Pixiv ID',
    dm_author: 'Author',
    dm_type: 'Type',
    dm_tags: 'Tags',
    dm_caption: 'Caption',
    dm_posted_at: 'Posted at',
    dm_unknown: 'Unknown',
    dm_none: 'None',
    dm_views: 'Views',
    dm_bookmarks: 'Bookmarks',
    caption_show_all: 'Show full caption',
    caption_collapse: 'Collapse caption',
    ai_meta_mode: 'AI metadata mode',
    copy_json: 'Copy JSON',
    copy_instruction: 'Copy instruction',
    copied: 'Copied',
    copy_failed: 'Copy failed',
    copy_failed_manual: 'Copy failed. Please copy manually:\n\n',
    show_all: 'Show all',
    collapse: 'Collapse',
    copy_all_image_links: 'Copy all image links',
    no_links_to_copy: 'No links to copy',
    copied_n_links: ({ n }) => `Copied ${n} links`,
    copy_failed_popup: 'Copy failed; opened as text',
    prev_group: 'Prev',
    next_group: 'Next',
    seo_tags_prefix: 'Tags',
    seo_ai_meta_prefix: 'AI metadata',
    lang_btn_zh: 'ZH',
    lang_btn_en: 'EN',
    btn_import_blacklist: 'Import old blocklist',
    import_blacklist_popup_blocked: 'Popup was blocked. Please allow popups and retry.',
    import_blacklist_starting: 'Importing from old domain…',
    import_blacklist_done: 'Imported old blocklist',
    import_blacklist_failed: 'Import failed (old domain may block iframe or no data)',
  },
};
function t(key, vars = {}) {
  const dict = I18N[CURRENT_LANG] || I18N.zh;
  const val = dict[key];
  if (typeof val === 'function') return String(val(vars));
  if (val == null) return String(key);
  return String(val);
}
function withLangParam(urlOrPath) {
  if (!LANG_PARAM_RAW) return String(urlOrPath || '');
  const raw = String(urlOrPath || '');
  try {
    const u = new URL(raw, window.location.origin);
    if (u.origin === window.location.origin) {
      u.searchParams.set('lang', LANG_PARAM_RAW);
      return u.pathname + u.search + u.hash;
    }
    return raw;
  } catch {
    return raw;
  }
}

function applyStaticI18n() {
  try {
    document.documentElement.lang = (CURRENT_LANG === 'zh') ? 'zh-CN' : 'en';
  } catch { }
  try {
    const homeLink = document.getElementById('homeLink');
    const homeImg = homeLink ? homeLink.querySelector('img') : null;
    if (homeLink) homeLink.href = withLangParam('/');
    if (homeLink) homeLink.title = t('home_title');
    if (homeImg) homeImg.alt = t('home_alt');
  } catch { }
  try { if (qInput) qInput.placeholder = t('search_placeholder_q'); } catch { }
  try { if (promptInput) promptInput.placeholder = t('search_placeholder_prompt'); } catch { }
  try { if (blacklistInput) blacklistInput.placeholder = t('blacklist_placeholder'); } catch { }
  try { if (searchBtn) searchBtn.textContent = t('btn_search'); } catch { }
  try { if (saveBlacklistBtn) saveBlacklistBtn.textContent = t('btn_save_blacklist'); } catch { }
  try { if (importOldBlacklistBtn) importOldBlacklistBtn.textContent = t('btn_import_blacklist'); } catch { }
  try {
    document.querySelectorAll('#searchStatus span').forEach((n) => { n.textContent = t('status_searching'); });
  } catch { }
  try { setNoResultMessage(t('no_results')); } catch { }
  try { if (loadMoreBtn) loadMoreBtn.textContent = t('load_more'); } catch { }
  try { if (sortModeSel) sortModeSel.setAttribute('aria-label', t('sort_label')); } catch { }
  try { if (timeRangeSel) timeRangeSel.setAttribute('aria-label', t('time_range_label')); } catch { }
  try { if (sortModeSel2) sortModeSel2.setAttribute('aria-label', t('sort_label')); } catch { }
  try { if (timeRangeSel2) timeRangeSel2.setAttribute('aria-label', t('time_range_label')); } catch { }
  try { if (fcChip) fcChip.setAttribute('aria-label', t('fc_chip_label')); } catch { }
  try {
    [sortModeSel, sortModeSel2].filter(Boolean).forEach((sel) => {
      Array.from(sel.options || []).forEach((opt) => {
        const v = String(opt.value || '');
        if (v === 'new') opt.textContent = t('sort_new');
        if (v === 'count') opt.textContent = t('sort_count');
        if (v === 'monthly') opt.textContent = t('sort_monthly');
      });
    });
  } catch { }
  try {
    const fcLabel = document.querySelector('#fcPanel .fc-label');
    if (fcLabel) fcLabel.textContent = t('jump_label');
  } catch { }
  try { if (fcInput) fcInput.placeholder = t('jump_placeholder'); } catch { }
  try { if (fcGo) fcGo.textContent = t('btn_go'); } catch { }
	  try {
	    const fcSwitchText = document.querySelector('#fcPanel label[for="openWorkNewWindowToggle"] .fc-switch-text');
	    if (fcSwitchText) fcSwitchText.textContent = t('open_work_new_window');
	  } catch { }
	  try {
	    const el = document.querySelector('#fcPanel label[for="showSuspectInvalidTagToggle"] .fc-switch-text');
	    if (el) el.textContent = t('show_suspect_invalid_tags');
	  } catch { }
	  try {
	    const el = document.querySelector('#fcPanel label[for="showNaixInvalidTagToggle"] .fc-switch-text');
	    if (el) el.textContent = t('show_naix_invalid_tags');
	  } catch { }
  try { const fcQ = document.getElementById('fcQ'); if (fcQ) fcQ.placeholder = t('fc_q_placeholder'); } catch { }
  try { const fcPrompt = document.getElementById('fcPrompt'); if (fcPrompt) fcPrompt.placeholder = t('fc_prompt_placeholder'); } catch { }
  try { const fcBlacklist = document.getElementById('fcBlacklist'); if (fcBlacklist) fcBlacklist.placeholder = t('fc_blacklist_placeholder'); } catch { }
  try { const fcSearchBtn = document.getElementById('fcSearchBtn'); if (fcSearchBtn) fcSearchBtn.textContent = t('btn_search'); } catch { }
  try { const fcSaveBlacklistBtn = document.getElementById('fcSaveBlacklistBtn'); if (fcSaveBlacklistBtn) fcSaveBlacklistBtn.textContent = t('btn_save_blacklist'); } catch { }
  try { if (hpImg) hpImg.alt = t('preview_alt'); } catch { }
  try { if (backBtn) backBtn.textContent = t('back_btn'); } catch { }
  try { if (detailTitle) detailTitle.textContent = t('detail_header'); } catch { }
}

function setOrCreateMetaByName(name, content) {
  if (!name) return;
  const head = document.head || document.getElementsByTagName('head')[0];
  if (!head) return;
  let el = head.querySelector(`meta[name="${name}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('name', name);
    head.appendChild(el);
  }
  el.setAttribute('content', String(content ?? ''));
}

function setOrCreateMetaByProperty(property, content) {
  if (!property) return;
  const head = document.head || document.getElementsByTagName('head')[0];
  if (!head) return;
  let el = head.querySelector(`meta[property="${property}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute('property', property);
    head.appendChild(el);
  }
  el.setAttribute('content', String(content ?? ''));
}

function setOrCreateLinkRel(rel, href) {
  if (!rel) return;
  const head = document.head || document.getElementsByTagName('head')[0];
  if (!head) return;
  let el = head.querySelector(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    head.appendChild(el);
  }
  el.setAttribute('href', String(href ?? ''));
}

function clearDynamicOgImages() {
  try {
    document.querySelectorAll('meta[property="og:image"][data-dynamic="1"]').forEach((n) => n.remove());
  } catch { }
  try {
    const tw = document.querySelector('meta[name="twitter:image"][data-dynamic="1"]');
    if (tw) tw.remove();
  } catch { }
}

function setDynamicOgImages(urls) {
  const head = document.head || document.getElementsByTagName('head')[0];
  if (!head) return;
  clearDynamicOgImages();
  const list = Array.isArray(urls) ? urls.filter(Boolean).slice(0, 8) : [];
  list.forEach((u) => {
    const m = document.createElement('meta');
    m.setAttribute('property', 'og:image');
    m.setAttribute('content', String(u));
    m.dataset.dynamic = '1';
    head.appendChild(m);
  });
  if (list.length) {
    const tw = document.createElement('meta');
    tw.setAttribute('name', 'twitter:image');
    tw.setAttribute('content', String(list[0]));
    tw.dataset.dynamic = '1';
    head.appendChild(tw);
  }
}

function compactOneLine(s) {
  return String(s ?? '').replace(/\s+/g, ' ').trim();
}

function applyHomeSeo() {
  const online = typeof isAitagGallery === 'function' && isAitagGallery();
  const siteTitle = online
    ? (CURRENT_LANG === 'zh' ? 'AITag 在线图库 · Nai学长工作室' : 'AITag Online Gallery · Nai Studio')
    : CURRENT_LANG === 'zh'
    ? (CONFIG.gallery_title_zh || SITE_TITLE_ZH)
    : (CONFIG.gallery_title_en || SITE_TITLE_EN);
  const description = online
    ? (CURRENT_LANG === 'zh'
      ? '在线搜索和浏览 AITag 的 NovelAI 作品，查看多图与角色候选，并建立零生成 Studio 草稿。'
      : 'Search and browse NovelAI works from AITag, inspect every image and character slot, and create a zero-generation Studio draft.')
    : (CURRENT_LANG === 'zh' ? HOME_DESC_ZH : HOME_DESC_EN);
  document.title = siteTitle;
  setOrCreateMetaByName('description', description);
  setOrCreateMetaByName('robots', 'index,follow,max-image-preview:large');
  setOrCreateMetaByProperty('og:title', siteTitle);
  setOrCreateMetaByProperty('og:description', description);
  setOrCreateMetaByProperty('og:type', 'website');
  setOrCreateMetaByProperty('og:site_name', siteTitle);
  setOrCreateMetaByProperty('og:locale', CURRENT_LANG === 'zh' ? 'zh_CN' : 'en_US');
  setOrCreateMetaByName('twitter:card', 'summary_large_image');
  setOrCreateMetaByName('twitter:title', siteTitle);
  setOrCreateMetaByName('twitter:description', description);
  const href = String(window.location.origin || '') + '/';
  setOrCreateMetaByProperty('og:url', href);
  setOrCreateLinkRel('canonical', href);
  clearDynamicOgImages();
}

function applyWorkSeo(workId, work = {}, images = []) {
  let typeRaw = String(work.AI_type || work.ai_type || '').trim();
  if (!typeRaw) {
    try {
      const first = Array.isArray(images) ? images[0] : null;
      if (first && first.image_type) typeRaw = String(first.image_type).trim();
    } catch { }
  }
  const typeLabel = typeRaw ? typeRaw.toUpperCase() : 'AI';
  const titleRaw = (work.title && String(work.title).trim()) ? String(work.title).trim() : '';
  const online = typeof isAitagGallery === 'function' && isAitagGallery();
  const siteTitle = online
    ? (CURRENT_LANG === 'zh' ? 'AITag 在线图库 · Nai学长工作室' : 'AITag Online Gallery · Nai Studio')
    : (CURRENT_LANG === 'zh' ? SITE_TITLE_ZH : SITE_TITLE_EN);
  const workTitle = `[${typeLabel}] ${titleRaw || t('work_fallback', { id: workId })} - ${siteTitle}`;

  const tags = normalizeTags(work.tags);
  let aiJson = '';
  try {
    const first = Array.isArray(images) ? images[0] : null;
    if (first && first.ai_json != null) {
      if (typeof first.ai_json === 'string') {
        aiJson = first.ai_json;
      } else {
        aiJson = JSON.stringify(first.ai_json);
      }
    }
  } catch { }
  let desc = '';
  if (tags.length) desc += `${t('seo_tags_prefix')}: ${tags.slice(0, 80).join(', ')} `;
  if (aiJson) desc += `${t('seo_ai_meta_prefix')}: ${aiJson}`;
  desc = compactOneLine(desc).slice(0, 1200);

  document.title = workTitle;
  setOrCreateMetaByName('description', desc || (CURRENT_LANG === 'zh' ? HOME_DESC_ZH : HOME_DESC_EN));
  setOrCreateMetaByName('robots', 'index,follow,max-image-preview:large');
  setOrCreateMetaByProperty('og:title', workTitle);
  setOrCreateMetaByProperty('og:description', desc || (CURRENT_LANG === 'zh' ? HOME_DESC_ZH : HOME_DESC_EN));
  setOrCreateMetaByProperty('og:type', 'article');
  setOrCreateMetaByProperty('og:site_name', siteTitle);
  setOrCreateMetaByProperty('og:locale', CURRENT_LANG === 'zh' ? 'zh_CN' : 'en_US');
  setOrCreateMetaByName('twitter:card', 'summary_large_image');
  setOrCreateMetaByName('twitter:title', workTitle);
  setOrCreateMetaByName('twitter:description', desc || (CURRENT_LANG === 'zh' ? HOME_DESC_ZH : HOME_DESC_EN));
  const href = `${window.location.origin}/i/${workId}${online ? '?gallery=aitag-online' : ''}`;
  setOrCreateMetaByProperty('og:url', href);
  setOrCreateLinkRel('canonical', href);
  try {
    const urls = (Array.isArray(images) ? images : []).map((img) => buildImageUrl(img)).filter(Boolean);
    setDynamicOgImages(urls);
  } catch {
    clearDynamicOgImages();
  }
}

const state = {
  page: 1,
  pageSize: 60,
  q: '',
  prompt: '',
  blacklist: [],
  items: [],
  total: 0,
  preview: { index: 0, images: [], title: '', active: false, side: 'right', top: 16, anchorEl: null, hoverTimer: 0 },
  cache: { works: new Map(), searches: new Map(), workMeta: new Map() },
  favoritesMode: false,
  queueMode: false,
  favoriteIds: new Set(),
  queueIds: new Set(),
  directDetail: false,
	  listMode: 'infinite',
	  openWorkInNewWindow: false,
	  showSuspectInvalidTags: false,
	  showNaixInvalidTags: false,
	  lang: CURRENT_LANG,
		  ads: { lastKey: '', preloaded: new Set(), preloadTimer: 0 },
		  workFlags: new Map(),
		  workPages: new Map(),
		  detailScroll: { currentWorkId: null, byWork: new Map(), restoreTimers: [], isRestoring: false },
		};
// 统一移动端断点与设备特性检测（移动端不启用悬浮预览）
const MOBILE_MAX_WIDTH = 800;
function supportsHover() {
  try { return window.matchMedia('(hover: hover) and (pointer: fine)').matches; } catch { return false; }
}
function shouldEnableHoverPreview() {
  return supportsHover() && window.innerWidth > MOBILE_MAX_WIDTH;
}

const galleryEl = document.getElementById('gallery');
const loadingEl = document.getElementById('loading');
const paginationEl = document.getElementById('pagination');
const loadMoreBtn = document.getElementById('loadMoreBtn');
const qInput = document.getElementById('q');
const promptInput = document.getElementById('prompt');
const aitagCreatorInput = document.getElementById('aitagCreator');
const aitagTagsInput = document.getElementById('aitagTags');
const aitagModelSelect = document.getElementById('aitagModel');
const aitagMinImagesInput = document.getElementById('aitagMinImages');
const aitagMaxImagesInput = document.getElementById('aitagMaxImages');
const searchBtn = document.getElementById('searchBtn');
const searchStatusEl = document.getElementById('searchStatus');
const noResultEl = document.getElementById('noResult');
const noResultTextEl = document.getElementById('noResultText');
const sortModeSel = document.getElementById('sortMode');
const timeRangeSel = document.getElementById('timeRange');
const sortModeSel2 = document.getElementById('sortMode2');
const timeRangeSel2 = document.getElementById('timeRange2');
const blacklistInput = document.getElementById('blacklist');
const saveBlacklistBtn = document.getElementById('saveBlacklistBtn');
let importOldBlacklistBtn = null;
// 右下角浮动控件元素（设置形状芯片）
const fcChip = document.getElementById('fcChip');
const fcNum = document.getElementById('fcNum');
const fcPanel = document.getElementById('fcPanel');
	const fcInput = document.getElementById('fcInput');
	const fcGo = document.getElementById('fcGo');
	const openWorkNewWindowToggle = document.getElementById('openWorkNewWindowToggle');
	const showSuspectInvalidTagToggle = document.getElementById('showSuspectInvalidTagToggle');
	const showNaixInvalidTagToggle = document.getElementById('showNaixInvalidTagToggle');

// 悬浮预览元素
const hoverPreview = document.getElementById('hoverPreview');
const hpImg = document.getElementById('hpImage');
const hpTitle = document.getElementById('hpTitle');
const hpCount = document.getElementById('hpCount');

const detailView = document.getElementById('detailView');
let detailLoadGen = 0;
const backBtn = document.getElementById('backBtn');
const detailMeta = document.getElementById('detailMeta');
const detailImages = document.getElementById('detailImages');
const detailTitle = document.getElementById('detailTitle');

// 工具函数
// escapeHtml 由 shared/escape.js 提供（先于此脚本加载）
// 异步入口统一错误出口：有 toast 用 toast，否则至少落 console，避免静默 unhandled rejection
function reportAsyncError(prefix, err) {
  const msg = `${prefix}：${(err && err.message) || err || '未知错误'}`;
  try {
    if (window.UiToast && typeof window.UiToast.err === 'function') window.UiToast.err(msg);
    else console.error(msg, err);
  } catch { console.error(msg, err); }
}
// 以对象字段拼接图片完整链接：asset_base_url + image_type/author_id/file_name
// Trust DB/local extensions. Mixed PNG/WebP storage is normal until migration.
function buildImageUrl(imgOrPath = '') {
  // The config endpoint describes the site gallery.  A direct Codex/QQ
  // detail load can render before the async config/bootstrap work settles, so
  // derive isolated-gallery assets from the URL context at render time.
  let contextGallery = '';
  try {
    contextGallery = new URL(window.location.href).searchParams.get('gallery') || '';
  } catch { }
  const contextBase = {
    codex: '/data/gallery/codex/',
    qqgroup: '/data/gallery/qqgroup/',
  }[contextGallery];
  const baseRaw = String(contextBase || CONFIG.asset_base_url || '').trim();
  const base = baseRaw.endsWith('/') ? baseRaw : (baseRaw + '/');
  // lite payload 只携带 local_path；完整详情仍兼容结构化字段。
  if (imgOrPath && typeof imgOrPath === 'object') {
    const remoteUrl = String(
      imgOrPath.thumbnail_url || imgOrPath.thumb_url || imgOrPath.url || imgOrPath.image_url || ''
    ).trim();
    if (/^https:\/\//i.test(remoteUrl) || remoteUrl.startsWith('/api/nai/aitag/')) return remoteUrl;
    const localPath = String(imgOrPath.local_path || '').trim();
    if (localPath) return buildImageUrl(localPath);
    const t = String(imgOrPath.image_type || '').trim();
    const a = String(imgOrPath.author_id ?? '').trim();
    const f = String(imgOrPath.file_name || '').trim();
    if (t && a && f) {
      // 保留显式扩展名；无扩展名时原样请求，由后端按已知图片扩展逐个探测，
      // 前端不再捏造 .webp。
      return `${base}${t}/${a}/${f}`;
    }
    return '';
  }
  // 兼容旧字符串 image_path 的回退：去掉 images/ 前缀，保留真实扩展名
  let p = String(imgOrPath || '');
  p = p.replace(/\\/g, '/');
  p = p.replace(/^\/?(?:data\/)?images\//, '');
  p = p.replace(/^\/?www\/pixiv_ai_tag\//, '');
  p = p.replace(/^\/?pixiv_ai_tag\//, '');
  p = p.replace(/^\/+/, '');
  return base ? (base + p) : p;
}

function buildThumbUrlFromWork(work = {}) {
  if (!work || typeof work !== 'object') return '';
  const remoteUrl = String(work.thumbnail_url || work.thumb_url || work.cover_url || '').trim();
  if (/^https:\/\//i.test(remoteUrl) || remoteUrl.startsWith('/api/nai/aitag/')) return remoteUrl;
  if (work.thumb_path) return buildImageUrl(work.thumb_path);
  const t = String(work.AI_type || '').trim();
  const a = String(work.userId ?? '').trim();
  const id = work.id;
  if (t && a && id) {
    return buildImageUrl({ image_type: t, author_id: a, file_name: `${id}_p0` });
  }
  return '';
}

function formatMetric(value) {
  const v = Number(value) || 0;
  if (v >= 1000000) return `${(v / 1000000).toFixed(1).replace(/\.0$/, '')}m`;
  if (v >= 10000) return `${(v / 10000).toFixed(1).replace(/\.0$/, '')}w`;
  if (v >= 1000) return `${(v / 1000).toFixed(1).replace(/\.0$/, '')}k`;
  return String(v);
}

function adsEnabled() {
  return !!(CONFIG.ads_enabled && Array.isArray(CONFIG.ads) && CONFIG.ads.length);
}

// 广告栈按需加载：默认 ads_enabled=false 时入口全部空转，实现见 app-ads.js
const ADS_SCRIPT_URL = '/assets/app-ads.js?v=dcc29b34a0';
let adsImplPromise = null;
function ensureAdsImpl() {
  if (!adsEnabled()) return Promise.resolve(null);
  if (window.GalleryAds) return Promise.resolve(window.GalleryAds);
  if (!adsImplPromise) {
    adsImplPromise = new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = ADS_SCRIPT_URL;
      s.onload = () => resolve(window.GalleryAds || null);
      s.onerror = () => { adsImplPromise = null; resolve(null); };
      document.head.appendChild(s);
    });
  }
  return adsImplPromise;
}

function scheduleSearchAdPreload() {
  if (!adsEnabled()) return;
  const impl = window.GalleryAds;
  if (impl) return impl.scheduleSearchAdPreload();
  ensureAdsImpl().then((loaded) => { if (loaded) loaded.scheduleSearchAdPreload(); });
}

function createAdElement(placement = 'list') {
  if (!adsEnabled()) return null;
  const impl = window.GalleryAds;
  if (impl) return impl.createAdElement(placement);
  ensureAdsImpl();
  return null;
}

function getGalleryColumnCount() {
  try {
    const cols = getComputedStyle(galleryEl).gridTemplateColumns;
    const count = String(cols || '').split(' ').filter(Boolean).length;
    if (count > 0) return count;
  } catch { }
  return window.innerWidth <= MOBILE_MAX_WIDTH ? 2 : 6;
}

function appendGalleryAd(slotKey) {
  if (!adsEnabled() || !galleryEl || !slotKey) return;
  const impl = window.GalleryAds;
  if (impl) return impl.appendGalleryAd(slotKey);
  ensureAdsImpl().then((loaded) => { if (loaded) loaded.appendGalleryAd(slotKey); });
}

function getWorkListPage(w = {}) {
  try {
    const key = normalizeWorkId(w.id);
    const page = Number(state.workPages.get(key) || 0);
    if (Number.isFinite(page) && page >= 1) return page;
  } catch { }
  const fallback = Number(state.page || 1);
  return Number.isFinite(fallback) && fallback >= 1 ? fallback : 1;
}

function rememberWorkListPages(items = [], page = 1, opts = {}) {
  try {
    if (opts.reset) state.workPages.clear();
    const p = Math.max(1, Number(page) || 1);
    (Array.isArray(items) ? items : []).forEach((w) => {
      if (!w || w.id == null) return;
      const key = normalizeWorkId(w.id);
      if (!state.workPages.has(key)) state.workPages.set(key, p);
    });
  } catch { }
}

function resolveWorkImageCount(w = {}) {
  let count = Math.max(0, Number(w.image_count) || 0);
  if (!count && w.original_urls) {
    try {
      const urls = typeof w.original_urls === 'string' ? JSON.parse(w.original_urls) : w.original_urls;
      if (Array.isArray(urls)) count = urls.length;
    } catch { }
  }
  return count;
}

function currentSortMode() {
  return (sortModeSel && sortModeSel.value) || (sortModeSel2 && sortModeSel2.value) || 'new';
}

function sortWorkItems(items, mode = currentSortMode()) {
  if (!Array.isArray(items) || items.length <= 1) return items;
  const out = items.slice();
  if (mode === 'count') {
    out.sort((a, b) => {
      const diff = resolveWorkImageCount(b) - resolveWorkImageCount(a);
      if (diff) return diff;
      const dateDiff = String(b.create_date || '').localeCompare(String(a.create_date || ''));
      if (dateDiff) return dateDiff;
      return compareWorkIdsDesc(a.id, b.id);
    });
  } else if (mode === 'monthly') {
    out.sort((a, b) => {
      const diff = Number(b.total_bookmarks || 0) - Number(a.total_bookmarks || 0);
      if (diff) return diff;
      const dateDiff = String(b.create_date || '').localeCompare(String(a.create_date || ''));
      if (dateDiff) return dateDiff;
      return compareWorkIdsDesc(a.id, b.id);
    });
  }
  return out;
}

function clearSearchCache() {
  try { state.cache.searches.clear(); } catch { }
}

// 提取文件中的页码（_pN），用于排序
function getPageIndex(obj) {
  const s = String((obj && (obj.file_name || obj.image_path)) || '');
  const m = s.match(/_p(\d+)/);
  return m ? parseInt(m[1], 10) : 0;
}
const snippet = (s = '', n = 80) => {
  const t = String(s)
    .replace(/<br\s*\/?>/gi, ' · ')
    .replace(/<[^>]+>/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim();
  return t.length > n ? t.slice(0, n) + '…' : t;
};
const typeClass = (t = '') => {
  const k = String(t).toLowerCase();
  if (k === 'sd') return 'sd';
  if (k === 'nai') return 'nai';
  if (k === 'nai_x' || k === 'naix' || k === 'nai x') return 'nai-x';
  if (k === 'comfyui') return 'comfyui';
  return '';
};
function normalizeWorkId(id) {
  if (window.WorkBridge && typeof window.WorkBridge.normalizeWorkId === 'function') {
    return window.WorkBridge.normalizeWorkId(id);
  }
  const value = String(id == null ? '' : id).trim();
  return /^\d+$/.test(value) && value !== '0' ? value : '';
}
function compareWorkIdsDesc(leftId, rightId) {
  const left = normalizeWorkId(leftId).replace(/^0+(?=\d)/, '');
  const right = normalizeWorkId(rightId).replace(/^0+(?=\d)/, '');
  if (left.length !== right.length) return right.length - left.length;
  return right.localeCompare(left);
}
function withGalleryContext(urlOrPath) {
  if (window.WorkBridge && typeof window.WorkBridge.withGalleryContext === 'function') {
    return window.WorkBridge.withGalleryContext(urlOrPath);
  }
  return String(urlOrPath || '');
}
function isNaixWork(w = {}) {
  const raw = String((w && (w.AI_type || w.ai_type || w.image_type)) || '').trim().toLowerCase();
  return raw === 'nai_x' || raw === 'naix' || raw === 'nai x';
}
function getWorkFlags(id) {
  return state.workFlags.get(normalizeWorkId(id)) || {};
}
function setWorkFlags(id, patch = {}) {
  const key = normalizeWorkId(id);
  const prev = state.workFlags.get(key) || {};
  const next = { ...prev, ...patch };
  state.workFlags.set(key, next);
  return next;
}
function isSuspectInvalidTagWorkData(workData) {
  try {
    const wtype = String((workData && (workData.work || {}).AI_type) || '').toLowerCase();
    if (wtype !== 'nai' && wtype !== 'nai_x') return false;
    return !!(window.NAIX && typeof window.NAIX.suspectWork === 'function' && window.NAIX.suspectWork(workData));
  } catch {
    return false;
  }
}
function rememberWorkFlagsFromDetail(workData) {
  const work = workData && workData.work ? workData.work : null;
  if (!work || work.id == null) return false;
  const key = normalizeWorkId(work.id);
  const prev = getWorkFlags(key);
  const nextSuspect = isSuspectInvalidTagWorkData(workData);
  const nextNaix = isNaixWork(work);
  if (prev.suspectInvalidTags === nextSuspect && prev.naixType === nextNaix) return false;
  setWorkFlags(key, { suspectInvalidTags: nextSuspect, naixType: nextNaix });
  return true;
}
function isFrontendHiddenWork(w = {}) {
  if (isBlockedWork(w)) return true;
  const flags = getWorkFlags(w.id);
  const isNaix = isNaixWork(w) || flags.naixType;
  const isSuspect = !!flags.suspectInvalidTags;
  if (isNaix || isSuspect) {
    const allowedByNaix = isNaix && state.showNaixInvalidTags;
    const allowedBySuspect = isSuspect && state.showSuspectInvalidTags;
    return !(allowedByNaix || allowedBySuspect);
  }
  return false;
}
function visibleWorks(items = state.items) {
  return (Array.isArray(items) ? items : []).filter((w) => !isFrontendHiddenWork(w));
}
function setNoResultMessage(message) {
  if (noResultTextEl) {
    noResultTextEl.textContent = String(message || '');
  }
}
function updateNoResultVisibility() {
  try {
    if (!noResultEl) return;
    const visible = visibleWorks().length;
    noResultEl.classList.toggle('visible', visible === 0);
    // 有数据但全被前端规则（黑名单 / NAI_X / 疑似无效 TAG）挡住时，说明原因而非谎称「无结果」
    if (visible === 0 && (state.items || []).length > 0) {
      setNoResultMessage('本页作品均被当前屏蔽/隐藏规则过滤。可在设置中调整黑名单，或打开「显示 NAI_X / 疑似无效 TAG」。');
    } else if (visible === 0 && state.favoritesMode) {
      setNoResultMessage('暂无收藏作品');
    } else if (visible === 0 && state.queueMode) {
      setNoResultMessage('待生成队列为空');
    } else if (visible === 0 && window.GalleryDropFolders && window.GalleryDropFolders.isDropGallery()) {
      const grouped = typeof currentGalleryGroup === "function" && currentGalleryGroup();
      const hasQuery = !!(state.q || state.prompt || grouped);
      setNoResultMessage(hasQuery
        ? "无搜索结果。可清空条件，或把图片拖进上方区域新建文件夹。"
        : "还没有作品。把带 NovelAI 元数据的图片拖进这块区域，会收成一个文件夹。");
    } else if (visible === 0) {
      setNoResultMessage(t('no_results'));
    }
  } catch { }
}
function removeInfiniteSentinel() {
  if (infiniteObserver) {
    try { infiniteObserver.disconnect(); } catch { }
    infiniteObserver = null;
  }
  try {
    const sentinel = document.getElementById('infiniteSentinel');
    if (sentinel) sentinel.remove();
  } catch { }
}
function setupInfiniteScrollIfVisible() {
  if (visibleWorks().length > 0) {
    setupInfiniteScroll();
  } else {
    removeInfiniteSentinel();
  }
}
function preserveWindowScrollAfterRender(fn) {
  const y = window.scrollY || window.pageYOffset || 0;
  try {
    fn();
  } finally {
    const restore = () => {
      try {
        window.scrollTo({ top: y, behavior: 'auto' });
      } catch {
        try { window.scrollTo(0, y); } catch { }
      }
    };
    restore();
    try { requestAnimationFrame(restore); } catch { }
    setTimeout(restore, 80);
  }
}

function hasEchoCheckpointLoaderSimple(obj) {
  const target = 'ECHOCheckpointLoaderSimple';
  try {
    const stack = [obj];
    const seen = new WeakSet();
    let steps = 0;
    while (stack.length && steps < 8000) {
      const cur = stack.pop();
      steps += 1;
      if (cur == null) continue;
      const t = typeof cur;
      if (t === 'string') {
        if (cur.includes(target)) return true;
        continue;
      }
      if (t !== 'object') continue;
      if (seen.has(cur)) continue;
      seen.add(cur);
      if (cur.class_type === target || cur.class === target || cur.type === target) return true;
      if (Array.isArray(cur)) {
        for (const v of cur) stack.push(v);
      } else {
        for (const v of Object.values(cur)) stack.push(v);
      }
    }
  } catch { }
  return false;
}

function isNonStandardComfyuiWork(workData) {
  try {
    const wtype = String((workData && (workData.work || {}).AI_type) || '').toLowerCase();
    if (wtype !== 'comfyui') return false;
    for (const img of (workData.images || [])) {
      const raw = img ? img.ai_json : null;
      if (!raw) continue;
      if (typeof raw === 'string') {
        if (raw.includes('ECHOCheckpointLoaderSimple')) return true;
        try {
          const obj = JSON.parse(raw);
          if (hasEchoCheckpointLoaderSimple(obj)) return true;
        } catch { }
      } else {
        if (hasEchoCheckpointLoaderSimple(raw)) return true;
      }
    }
  } catch { }
  return false;
}
// 将 ISO8601 字符串格式化为 "YYYY-MM-DD HH:MM:SS"（保留源字符串的日期与时分秒）
function formatDateTime(isoStr = '') {
  const s = String(isoStr || '').trim();
  const m = s.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})/);
  if (m) return `${m[1]} ${m[2]}`;
  // 兜底：若不符合预期，尝试 Date 解析后再拼接本地时间
  const d = new Date(s);
  if (!Number.isNaN(d.getTime())) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }
  return s.replace('T', ' ').replace(/([+-]?\d{2}:?\d{2}|Z)$/, '');
}
// 仅格式化为日期（YYYY-MM-DD），用于首页卡片的投稿时间
function formatDate(isoStr = '') {
  const s = String(isoStr || '').trim();
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
  if (m) return m[1];
  const d = new Date(s);
  if (!Number.isNaN(d.getTime())) {
    const pad = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  }
  // 最后兜底：截取前 10 位（若是标准 ISO 字符串）
  return s.slice(0, 10);
}
// 渲染作品简介：保留安全的 <a> 与 <br>，其余标签去除并转义；兼容纯文本换行
function renderCaption(raw = '') {
  const s = String(raw || '');
  // DOMParser 生成惰性文档：不加载资源、不触发 onerror/onload，
  // 避免 innerHTML 解析不可信 HTML 时的解析期副作用。
  const container = new DOMParser().parseFromString(s, 'text/html').body;
  const allowedSchemes = ['http:', 'https:'];
  function walk(node) {
    const ELEMENT_NODE = 1;
    const TEXT_NODE = 3;
    if (!node) return '';
    if (node.nodeType === TEXT_NODE) {
      const t = node.textContent || '';
      return escapeHtml(t).replace(/\r\n|\r|\n/g, '<br>');
    }
    if (node.nodeType !== ELEMENT_NODE) return '';
    const tag = String(node.tagName || '').toLowerCase();
    if (tag === 'br') return '<br>';
    if (tag === 'a') {
      let href = node.getAttribute('href') || '';
      try {
        const u = new URL(href, window.location.origin);
        if (allowedSchemes.includes(u.protocol)) href = u.href; else href = '';
      } catch { href = ''; }
      const inner = Array.from(node.childNodes).map(walk).join('');
      if (!href) return inner;
      return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${inner || escapeHtml(href)}</a>`;
    }
    if (tag === 'p' || tag === 'div') {
      const inner = Array.from(node.childNodes).map(walk).join('');
      return /<br>\s*$/.test(inner) ? inner : inner + '<br>';
    }
    return Array.from(node.childNodes).map(walk).join('');
  }
  return Array.from(container.childNodes).map(walk).join('');
}
function normalizeTags(raw) {
  if (!raw) return [];
  try {
    const j = JSON.parse(raw);
    if (Array.isArray(j)) return j.map((x) => String(x)).filter(Boolean);
    if (typeof j === 'object' && j) return Object.values(j).map((x) => String(x)).filter(Boolean);
  } catch { }
  let buf = String(raw);
  for (const sep of ['\n', ',', '|', ';', ' ', '、', '，', '。', '\t']) buf = buf.split(sep).join(',');
  return buf.split(',').map((x) => x.trim()).filter(Boolean);
}

function tagTranslateEnabled() {
  return CONFIG.tag_translate_enabled !== false && CURRENT_LANG === 'zh';
}

const FAVORITES_CACHE_KEY = 'aitag_favorites_v2';
const SEARCH_CACHE_TTL_MS = 120000;
const SEARCH_CACHE_MAX = 64;
const WORK_CACHE_TTL_MS = 8 * 60 * 1000;
const WORK_CACHE_MAX = 48;

function searchCacheKey(url) {
  try { return String(url); } catch { return ''; }
}

function readSearchCache(url) {
  const key = searchCacheKey(url);
  const hit = state.cache.searches.get(key);
  if (!hit) return null;
  if (Date.now() - hit.at > SEARCH_CACHE_TTL_MS) {
    state.cache.searches.delete(key);
    return null;
  }
  return hit.data;
}

function writeSearchCache(url, data) {
  const key = searchCacheKey(url);
  if (!key) return;
  if (state.cache.searches.size >= SEARCH_CACHE_MAX) {
    const oldest = state.cache.searches.keys().next().value;
    if (oldest) state.cache.searches.delete(oldest);
  }
  state.cache.searches.set(key, { at: Date.now(), data });
}

function setFavoriteIds(ids) {
  const clean = (Array.isArray(ids) ? ids : []).map(normalizeWorkId).filter(Boolean);
  state.favoriteIds = new Set(clean);
  try { sessionStorage.setItem(`${FAVORITES_CACHE_KEY}:${currentGalleryId()}`, JSON.stringify(clean)); } catch { }
}

function loadCachedFavorites() {
  try {
    const raw = sessionStorage.getItem(`${FAVORITES_CACHE_KEY}:${currentGalleryId()}`);
    if (!raw) return false;
    const ids = JSON.parse(raw);
    if (!Array.isArray(ids)) return false;
    setFavoriteIds(ids);
    return true;
  } catch {
    return false;
  }
}

function refreshFavoriteButtons() {
  try {
    document.querySelectorAll('.fav-btn[data-work-id]').forEach((btn) => {
      const on = isFavorited(btn.dataset.workId);
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.title = on ? '取消收藏' : '收藏';
      btn.textContent = on ? '★' : '☆';
    });
  } catch { }
}

function galleryLoadError(message) {
  try {
    if (window.UiToast && typeof window.UiToast.err === 'function') {
      window.UiToast.err(message);
      return;
    }
  } catch { /* ignore */ }
  try { console.warn(message); } catch { /* ignore */ }
}

async function loadFavorites() {
  try {
    const endpoint = typeof isAitagGallery === 'function' && isAitagGallery()
      ? '/api/nai/aitag/favorites'
      : '/api/favorites';
    const res = await window.ApiClient.raw(`${API_BASE}${endpoint}`);
    if (!res.ok) {
      galleryLoadError('收藏列表加载失败');
      loadCachedFavorites();
      return;
    }
    const data = await res.json();
    setFavoriteIds(Array.isArray(data.ids) ? data.ids : []);
    refreshFavoriteButtons();
  } catch {
    loadCachedFavorites();
    galleryLoadError('收藏列表加载失败');
  }
}

function isFavorited(workId) {
  return state.favoriteIds.has(normalizeWorkId(workId));
}

async function toggleFavorite(workId) {
  const wid = normalizeWorkId(workId);
  if (!wid) return false;
  try {
    const online = typeof isAitagGallery === 'function' && isAitagGallery();
    const endpoint = online
      ? `/api/nai/aitag/favorites/${encodeURIComponent(wid)}/toggle`
      : `/api/favorites/${encodeURIComponent(wid)}/toggle`;
    const work = (state.items || []).find((item) => normalizeWorkId(item?.id) === wid) || {};
    const body = online ? {
      title: String(work.title || ''),
      creator: String(work.creator || ''),
      cover_url: String(work.cover_url || work.thumbnail_url || ''),
      ai_type: String(work.AI_type || work.ai_type || 'NAI'),
      create_date: String(work.create_date || ''),
      image_count: Number(work.image_count || 0),
      tags: normalizeTags(work.tags).slice(0, 100),
    } : undefined;
    const res = await window.ApiClient.raw(`${API_BASE}${endpoint}`, {
      method: 'POST',
      ...(body ? { body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } } : {}),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || '收藏操作失败，请稍后重试');
    if (data.favorited) state.favoriteIds.add(wid);
    else state.favoriteIds.delete(wid);
    try { sessionStorage.setItem(`${FAVORITES_CACHE_KEY}:${currentGalleryId()}`, JSON.stringify([...state.favoriteIds])); } catch { }
    document.querySelectorAll(`.fav-btn[data-work-id="${wid}"]`).forEach((btn) => {
      btn.classList.toggle('is-on', !!data.favorited);
      btn.setAttribute('aria-pressed', data.favorited ? 'true' : 'false');
      btn.title = data.favorited ? '取消收藏' : '收藏';
      btn.textContent = data.favorited ? '★' : '☆';
    });
    if (state.favoritesMode && !data.favorited) {
      const card = galleryEl.querySelector(`.card[data-work-id="${wid}"]`);
      if (card) card.remove();
      state.items = state.items.filter((w) => normalizeWorkId(w.id) !== wid);
      if (!state.items.length) {
        setNoResultMessage('暂无收藏作品');
        noResultEl.classList.add('visible');
      }
    }
    return !!data.favorited;
  } catch (e) {
    alert(e.message || '收藏操作失败');
    return isFavorited(wid);
  }
}

function createFavoriteButton(workId) {
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'fav-btn' + (isFavorited(workId) ? ' is-on' : '');
  btn.dataset.workId = String(workId);
  btn.setAttribute('aria-pressed', isFavorited(workId) ? 'true' : 'false');
  btn.title = isFavorited(workId) ? '取消收藏' : '收藏';
  btn.textContent = isFavorited(workId) ? '★' : '☆';
  btn.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();
    // 连点防重入：在途请求未返回前忽略后续点击，避免竞态导致星标与真实状态相反
    if (btn.dataset.pending === '1') return;
    btn.dataset.pending = '1';
    try {
      await toggleFavorite(workId);
    } finally {
      delete btn.dataset.pending;
    }
  });
  return btn;
}

function applyListShelfModeUi({ modeClass, title, description, emptyText }) {
  document.body.classList.add(modeClass);
  document.body.classList.remove(modeClass === 'mode-favorites' ? 'mode-queue' : 'mode-favorites');
  document.title = title;
  const hero = document.getElementById('hero-intro');
  if (hero) hero.classList.add('list-shelf-hero');
  const heroTitleZh = document.querySelector('#hero-intro .hero-title .lang-zh');
  const heroTitleEn = document.querySelector('#hero-intro .hero-title .lang-en');
  const heroDescZh = document.querySelector('#hero-intro .hero-desc .lang-zh');
  const heroDescEn = document.querySelector('#hero-intro .hero-desc .lang-en');
  const accent = document.getElementById('galleryHeroAccent');
  const lead = document.getElementById('galleryHeroLead');
  const signals = document.getElementById('galleryHeroSignals');
  const aside = document.querySelector('#hero-intro .atlas-hero-note, #hero-intro aside');
  if (heroTitleZh) heroTitleZh.textContent = title.replace(/\s*\|.*$/, '');
  if (heroTitleEn) heroTitleEn.textContent = '';
  if (heroDescZh) heroDescZh.textContent = description;
  if (heroDescEn) heroDescEn.textContent = description;
  if (lead) lead.textContent = description;
  if (accent) accent.textContent = '';
  if (signals) signals.classList.add('hidden');
  if (aside) aside.classList.add('hidden');
  ['localBanner', 'setupBanner', 'advancedFilters'].forEach((id) => {
    document.getElementById(id)?.classList.add('hidden');
  });
  document.querySelector('.atlas-search-deck')?.classList.add('hidden');
  document.querySelector('.gallery-source-bar')?.classList.add('hidden');
  const empty = document.getElementById('inspirationEmpty');
  if (empty && emptyText) empty.textContent = emptyText;
  try { window.GalleryDropFolders && window.GalleryDropFolders.sync(); } catch { }
}

function applyFavoritesModeUi() {
  if (!state.favoritesMode) return;
  applyListShelfModeUi({
    modeClass: 'mode-favorites',
    title: '我的收藏 | Nai学长工作室',
    description: '本地收藏的作品保存在 data/favorites.json，可随时回来查看。',
    emptyText: '收藏为空时，从图库详情点星标加入。',
  });
}

function isQueued(workId) {
  return state.queueIds.has(normalizeWorkId(workId));
}

async function loadQueue() {
  try {
    const res = await window.ApiClient.raw(`${API_BASE}/api/queue`);
    if (!res.ok) {
      galleryLoadError('待生成队列加载失败');
      return;
    }
    const data = await res.json();
    state.queueIds = new Set((Array.isArray(data.ids) ? data.ids : []).map(normalizeWorkId).filter(Boolean));
    refreshQueueButtons();
  } catch {
    galleryLoadError('待生成队列加载失败');
  }
}

function refreshQueueButtons() {
  try {
    document.querySelectorAll('.queue-btn[data-work-id]').forEach((btn) => {
      const on = isQueued(btn.dataset.workId);
      btn.classList.toggle('is-on', on);
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.title = on ? '移出待生成' : '加入待生成';
      btn.textContent = on ? '已入队' : '待生成';
    });
  } catch { /* ignore */ }
}

async function toggleQueue(workId) {
  const wid = normalizeWorkId(workId);
  if (!wid) return false;
  try {
    const res = await window.ApiClient.raw(`${API_BASE}/api/queue/${encodeURIComponent(wid)}/toggle`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || '待生成队列操作失败，请稍后重试');
    if (data.queued) state.queueIds.add(wid);
    else state.queueIds.delete(wid);
    refreshQueueButtons();
    if (state.queueMode && !data.queued) {
      const card = galleryEl && galleryEl.querySelector(`.card[data-work-id="${wid}"]`);
      if (card) card.remove();
      state.items = state.items.filter((w) => normalizeWorkId(w.id) !== wid);
      if (!state.items.length && noResultEl) {
        setNoResultMessage('待生成队列为空');
        noResultEl.classList.add('visible');
      }
    }
    return !!data.queued;
  } catch (e) {
    alert(e.message || '待生成队列操作失败');
    return isQueued(wid);
  }
}

function applyQueueModeUi() {
  if (!state.queueMode) return;
  applyListShelfModeUi({
    modeClass: 'mode-queue',
    title: '待生成队列 | Nai学长redu',
    description: '从图库详情加入待生成，再批量送入工作台 / 换角。数据保存在 data/production_queue.json。',
    emptyText: '队列中的作品单击可看详情；侧边栏可送去生图或换角。',
  });
}

function renderTagChip(tag) {
  const q = `"${String(tag)}"`;
  const url = withLangParam(`/?q=${encodeURIComponent(q)}`);
  const info = (typeof TagI18n !== 'undefined' && TagI18n.ready)
    ? TagI18n.translate(tag)
    : { original: String(tag), zh: String(tag), translated: false };
  const showTranslated = tagTranslateEnabled() && info.translated;
  const label = tagTranslateEnabled() ? info.zh : info.original;
  const title = showTranslated ? `${t('tag_original_title')}: ${info.original}` : '';
  const jpLine = showTranslated
    ? `<span class="tag-jp">${escapeHtml(info.original)}</span>`
    : '';
  const danbooruCls = (info.source === 'danbooru' || info.danbooru) ? ' tag-danbooru' : '';
  return `<a class="chip tag-chip${showTranslated ? ' tag-translated' : ''}${danbooruCls}" href="${escapeHtml(url)}" target="_blank" rel="noopener" title="${escapeHtml(title)}"><span class="tag-zh">${escapeHtml(label)}</span>${jpLine}</a>`;
}

function applyLocalGalleryUi() {
  if (!CONFIG.local_mirror) return;
  try {
    const hero = document.getElementById('hero-intro');
    if (hero) hero.classList.add('local-hero');
    const titleZh = document.querySelector('#hero-intro .hero-title .lang-zh');
    const titleEn = document.querySelector('#hero-intro .hero-title .lang-en');
    const descZh = document.querySelector('#hero-intro .hero-desc .lang-zh');
    const descEn = document.querySelector('#hero-intro .hero-desc .lang-en');
    if (titleZh && CONFIG.gallery_title_zh) titleZh.textContent = CONFIG.gallery_title_zh;
    if (titleEn && CONFIG.gallery_title_en) titleEn.textContent = CONFIG.gallery_title_en;
    if (descZh && CONFIG.gallery_desc_zh) descZh.textContent = CONFIG.gallery_desc_zh;
    if (descEn && CONFIG.gallery_desc_en) descEn.textContent = CONFIG.gallery_desc_en;
    const heroAnn = document.getElementById('heroAnnouncement');
    if (heroAnn) heroAnn.classList.add('hidden');
  } catch { }
}

// 黑名单工具
function parseWords(s = '') {
  let buf = String(s);
  for (const sep of ['\n', ',', '|', ';', ' ', '、', '，', '。', '\t']) buf = buf.split(sep).join(',');
  return buf.split(',').map((x) => x.trim()).filter(Boolean);
}
function loadBlacklist() {
  try {
    const raw = localStorage.getItem('gallery_blacklist') || '';
    state.blacklist = parseWords(raw).map((x) => x.toLowerCase());
    blacklistInput.value = raw;
  } catch { }
}
function saveBlacklist() {
  const raw = blacklistInput.value || '';
  localStorage.setItem('gallery_blacklist', raw);
  state.blacklist = parseWords(raw).map((x) => x.toLowerCase());
}

const BLACKLIST_MIGRATE_DONE_PREFIX = 'gallery_blacklist_migrate_done_v2:';
function importBlacklistFromWindowNameIfNeeded() {
  try {
    const marker = 'gallery_migrate_bl_v1:';
    const name = String(window.name || '');
    if (!name.startsWith(marker)) return false;

    let encoded = name.slice(marker.length);
    let decoded = '';
    try { decoded = decodeURIComponent(encoded); } catch { decoded = ''; }
    try { window.name = ''; } catch { }

    if (!decoded.trim()) return false;
    let currentRaw = '';
    try { currentRaw = String(localStorage.getItem('gallery_blacklist') || ''); } catch { currentRaw = ''; }
    if (currentRaw.trim()) return false;

    try { localStorage.setItem('gallery_blacklist', decoded); } catch { }
    try { blacklistInput.value = decoded; } catch { }
    try { state.blacklist = parseWords(decoded).map((x) => x.toLowerCase()); } catch { }
    return true;
  } catch {
    try { window.name = ''; } catch { }
    return false;
  }
}
function importBlacklistFromHashIfNeeded() {
  try {
    let h = String(window.location.hash || '');
    if (!h) return false;
    if (!h.startsWith('#')) return false;
    const rawPart = h.slice(1);
    const parts = rawPart.split('&').filter(Boolean);
    if (!parts.length) return false;
    const kv = {};
    for (const p of parts) {
      const idx = p.indexOf('=');
      if (idx === -1) continue;
      const k = p.slice(0, idx);
      const v = p.slice(idx + 1);
      if (k) kv[k] = v;
    }
    if (!kv.migrate_bl) return false;

    let currentRaw = '';
    try { currentRaw = String(localStorage.getItem('gallery_blacklist') || ''); } catch { currentRaw = ''; }
    if (currentRaw.trim()) {
      const nextParts = parts.filter((p) => !p.startsWith('migrate_bl='));
      const nextHash = nextParts.length ? `#${nextParts.join('&')}` : '';
      history.replaceState(history.state || {}, '', window.location.pathname + window.location.search + nextHash);
      return false;
    }

    let decoded = '';
    try { decoded = decodeURIComponent(String(kv.migrate_bl || '')); } catch { decoded = ''; }
    if (!decoded.trim()) return false;
    try { localStorage.setItem('gallery_blacklist', decoded); } catch { }
    try { blacklistInput.value = decoded; } catch { }
    try { state.blacklist = parseWords(decoded).map((x) => x.toLowerCase()); } catch { }

    const nextParts = parts.filter((p) => !p.startsWith('migrate_bl='));
    const nextHash = nextParts.length ? `#${nextParts.join('&')}` : '';
    history.replaceState(history.state || {}, '', window.location.pathname + window.location.search + nextHash);
    return true;
  } catch {
    return false;
  }
}
function oldBlacklistMigrationEnabled() {
  // 旧域名黑名单迁移功能保留，但默认由后端配置关闭。
  return !!CONFIG.old_blacklist_migrate_enabled;
}

// 旧域名黑名单迁移默认关闭（CONFIG.old_blacklist_migrate_enabled）；
// 开启时才按需注入 app-blacklist-migrate.js，不为过期功能支付常驻体积。
const BLACKLIST_MIGRATE_SCRIPT_URL = '/assets/app-blacklist-migrate.js?v=ef8a2a8c99';
let blacklistMigratePromise = null;
function ensureBlacklistMigrateImpl() {
  if (!oldBlacklistMigrationEnabled()) return Promise.resolve(false);
  if (window.BlacklistMigrate) return Promise.resolve(true);
  if (!blacklistMigratePromise) {
    blacklistMigratePromise = new Promise((resolve) => {
      const s = document.createElement('script');
      s.src = BLACKLIST_MIGRATE_SCRIPT_URL;
      s.onload = () => resolve(!!window.BlacklistMigrate);
      s.onerror = () => { blacklistMigratePromise = null; resolve(false); };
      document.head.appendChild(s);
    });
  }
  return blacklistMigratePromise;
}

function migrateBlacklistFromOldDomainInBackground() {
  if (!oldBlacklistMigrationEnabled()) return;
  ensureBlacklistMigrateImpl().then((ok) => {
    if (!ok || !window.BlacklistMigrate) return;
    window.BlacklistMigrate.runInBackground();
  });
}

		const OPEN_WORK_NEW_WINDOW_KEY = 'open_work_new_window_v1';
	const SHOW_SUSPECT_INVALID_TAGS_KEY = 'gallery_show_suspect_invalid_tags_v1';
	const SHOW_NAIX_INVALID_TAGS_KEY = 'gallery_show_naix_invalid_tags_v1';
		const CONFIG_REQUEST_VERSION = '260528a';
	const CONFIG_CACHE_JSON_KEY = 'gallery_config_json_v6';
	const CONFIG_CACHE_TS_KEY = 'gallery_config_ts_v6';
function loadOpenWorkInNewWindow() {
  let v = false;
  try { v = localStorage.getItem(OPEN_WORK_NEW_WINDOW_KEY) === '1'; } catch { }
  state.openWorkInNewWindow = v;
  try { if (openWorkNewWindowToggle) openWorkNewWindowToggle.checked = v; } catch { }
}
	function setOpenWorkInNewWindow(v) {
	  state.openWorkInNewWindow = !!v;
	  try { localStorage.setItem(OPEN_WORK_NEW_WINDOW_KEY, state.openWorkInNewWindow ? '1' : '0'); } catch { }
	  try { if (openWorkNewWindowToggle) openWorkNewWindowToggle.checked = state.openWorkInNewWindow; } catch { }
	}
	function syncInvalidTagToggles() {
	  try { if (showSuspectInvalidTagToggle) showSuspectInvalidTagToggle.checked = !!state.showSuspectInvalidTags; } catch { }
	  try { if (showNaixInvalidTagToggle) showNaixInvalidTagToggle.checked = !!state.showNaixInvalidTags; } catch { }
	}
	function loadInvalidTagFilterSettings() {
	  let showSuspect = false;
	  let showNaix = false;
	  try { showSuspect = localStorage.getItem(SHOW_SUSPECT_INVALID_TAGS_KEY) === '1'; } catch { }
	  try { showNaix = localStorage.getItem(SHOW_NAIX_INVALID_TAGS_KEY) === '1'; } catch { }
	  state.showSuspectInvalidTags = showSuspect;
	  state.showNaixInvalidTags = showNaix;
	  syncInvalidTagToggles();
	}
function refreshCurrentGallery(opts = {}) {
  const work = () => {
    try { closePreview(); } catch { }
    renderGallery({ forceClear: true });
    updateNoResultVisibility();
    if (state.listMode === 'pagination') {
      try { renderPagination(); } catch { }
    } else {
      try { setupInfiniteScrollIfVisible(); } catch { }
    }
  };
  if (opts.preserveScroll) {
    preserveWindowScrollAfterRender(work);
  } else {
    work();
  }
}
	let frontendFilterRefreshTimer = null;
	function scheduleFrontendFilterRefresh() {
	  if (frontendFilterRefreshTimer) return;
		  frontendFilterRefreshTimer = setTimeout(() => {
		    frontendFilterRefreshTimer = null;
		    refreshCurrentGallery({ preserveScroll: true });
		  }, 0);
		}
	function setShowSuspectInvalidTags(v) {
		  state.showSuspectInvalidTags = !!v;
		  try { localStorage.setItem(SHOW_SUSPECT_INVALID_TAGS_KEY, state.showSuspectInvalidTags ? '1' : '0'); } catch { }
		  syncInvalidTagToggles();
		  refreshCurrentGallery({ preserveScroll: true });
		}
	function setShowNaixInvalidTags(v) {
		  state.showNaixInvalidTags = !!v;
		  try { localStorage.setItem(SHOW_NAIX_INVALID_TAGS_KEY, state.showNaixInvalidTags ? '1' : '0'); } catch { }
		  syncInvalidTagToggles();
		  refreshCurrentGallery({ preserveScroll: true });
		}

async function getConfig() {
  try {
    const now = Date.now();
    const TTL_MS = 60 * 1000;
    const cachedStr = localStorage.getItem(CONFIG_CACHE_JSON_KEY) || '';
    const cachedTs = parseInt(localStorage.getItem(CONFIG_CACHE_TS_KEY) || '0', 10);
    if (cachedStr && cachedTs && (now - cachedTs) < TTL_MS) {
      try {
        const cached = JSON.parse(cachedStr);
        CONFIG = Object.assign(CONFIG, cached);
        // 从缓存配置填充首页公告。
        try {
          const annZh = String(cached.homepage_announcement_zh || '').trim();
          const annEn = String(cached.homepage_announcement_en || '').trim();
          const annEl = document.getElementById('heroAnnouncement');
          const annZhEl = document.getElementById('heroAnnouncementZh');
          const annEnEl = document.getElementById('heroAnnouncementEn');
          if (annEl && (annZh || annEn)) {
            if (annZhEl) annZhEl.textContent = annZh;
            if (annEnEl) annEnEl.textContent = annEn;
            annEl.classList.remove('hidden');
          }
        } catch { }
        return CONFIG;
      } catch { }
    }
    const res = await window.ApiClient.raw(`${API_BASE}/api/config?v=${CONFIG_REQUEST_VERSION}`);
    const cfg = res.ok ? await res.json() : {};
    CONFIG = Object.assign(CONFIG, cfg);
    // 广告开启时提前加载实现模块，避免首次渲染错过插入时机
    try { if (adsEnabled()) ensureAdsImpl(); } catch { }
    try {
      const years = Array.isArray(cfg.available_years) ? cfg.available_years : [];
      const months = Array.isArray(cfg.available_months) ? cfg.available_months : [];
      const tr = timeRangeSel;
      const tr2 = timeRangeSel2;
      if (tr) {
        // 清空并重建选项
        tr.innerHTML = '';
        const optAll = document.createElement('option'); optAll.value = 'all'; optAll.textContent = t('time_all'); tr.appendChild(optAll);
        // 年份（按年）；2023年不再细分季度，9月之前归入“更老”
        const yrs = years.length ? years : [2026, 2025, 2024, 2023];
        yrs.sort((a, b) => b - a);
        for (const y of yrs) {
          const optY = document.createElement('option'); optY.value = `y${y}`; optY.textContent = t('time_full_year', { year: y }); tr.appendChild(optY);
          if (y !== 2023) {
            for (let q = 1; q <= 4; q++) {
              const optQ = document.createElement('option'); optQ.value = `q${y}Q${q}`; optQ.textContent = t('time_quarter', { year: y, quarter: q }); tr.appendChild(optQ);
            }
          }
        }
        const optOlder = document.createElement('option'); optOlder.value = 'older'; optOlder.textContent = t('time_older'); tr.appendChild(optOlder);
      }
      if (tr && tr2) { tr2.innerHTML = tr.innerHTML; }
      const sm = sortModeSel;
      const sm2 = sortModeSel2;
      if (sm && tr) {
        if (!sm.dataset.boundSort) {
          sm.dataset.boundSort = '1';
          sm.addEventListener('change', () => {
          const mode = sm.value || 'new';
          // 当切换到“每月排行榜”时，默认时间范围为“当前月份”；列表为“全部时间”
          if (mode === 'monthly') {
            rebuildMonthlyOptions(months);
            tr.value = 'current';
            if (tr2) tr2.value = tr.value;
            if (sm2) sm2.value = mode;
          } else {
            rebuildTimeOptions();
            tr.value = 'all';
            if (tr2) tr2.value = tr.value;
            if (sm2) sm2.value = mode;
          }
          triggerSearch();
        });
        }
      }
      if (sm2 && tr2) {
        if (!sm2.dataset.boundSort) {
          sm2.dataset.boundSort = '1';
          sm2.addEventListener('change', () => {
          const mode = sm2.value || 'new';
          if (sortModeSel) sortModeSel.value = mode;
          if (mode === 'monthly') {
            rebuildMonthlyOptions(months);
            tr2.value = 'current';
            if (timeRangeSel) timeRangeSel.value = tr2.value;
          } else {
            rebuildTimeOptions();
            tr2.value = 'all';
            if (timeRangeSel) timeRangeSel.value = tr2.value;
          }
          triggerSearch();
        });
        }
      }
      if (tr && !tr.dataset.boundTime) {
        tr.dataset.boundTime = '1';
        tr.addEventListener('change', () => {
          triggerSearch();
        });
      }
      if (tr2 && !tr2.dataset.boundTime) {
        tr2.dataset.boundTime = '1';
        tr2.addEventListener('change', () => {
          if (timeRangeSel) timeRangeSel.value = tr2.value;
          triggerSearch();
        });
      }
    } catch { }
    // 从后端配置填充首页公告。
    try {
      const annZh = String(cfg.homepage_announcement_zh || '').trim();
      const annEn = String(cfg.homepage_announcement_en || '').trim();
      const annEl = document.getElementById('heroAnnouncement');
      const annZhEl = document.getElementById('heroAnnouncementZh');
      const annEnEl = document.getElementById('heroAnnouncementEn');
      if (annEl && (annZh || annEn)) {
        if (annZhEl) annZhEl.textContent = annZh;
        if (annEnEl) annEnEl.textContent = annEn;
        annEl.classList.remove('hidden');
      }
    } catch { }
    try {
      localStorage.setItem(CONFIG_CACHE_JSON_KEY, JSON.stringify(cfg));
      localStorage.setItem(CONFIG_CACHE_TS_KEY, String(now));
    } catch { }
    return CONFIG;
  } catch {
    return CONFIG;
  }
}

function rebuildTimeOptions() {
  const tr = timeRangeSel; if (!tr) return;
  const yrs = Array.isArray(CONFIG.available_years) && CONFIG.available_years.length ? CONFIG.available_years.slice() : [2025, 2024, 2023];
  yrs.sort((a, b) => b - a);
  tr.innerHTML = '';
  for (const y of yrs) {
    const optY = document.createElement('option'); optY.value = `y${y}`; optY.textContent = t('time_full_year', { year: y }); tr.appendChild(optY);
    if (y > 2023) {
      for (let q = 1; q <= 4; q++) { const optQ = document.createElement('option'); optQ.value = `q${y}Q${q}`; optQ.textContent = t('time_quarter', { year: y, quarter: q }); tr.appendChild(optQ); }
    } else if (y === 2023) {
      const optQ4 = document.createElement('option'); optQ4.value = 'q2023Q4'; optQ4.textContent = t('time_quarter', { year: 2023, quarter: 4 }); tr.appendChild(optQ4);
    }
  }
  const optOlder = document.createElement('option'); optOlder.value = 'older'; optOlder.textContent = t('time_older'); tr.appendChild(optOlder);
  if (timeRangeSel2) timeRangeSel2.innerHTML = tr.innerHTML;
}

function rebuildMonthlyOptions(months) {
  const tr = timeRangeSel; if (!tr) return;
  tr.innerHTML = '';
  const optCur = document.createElement('option'); optCur.value = 'current'; optCur.textContent = t('time_current_month'); tr.appendChild(optCur);
  const yrs = Array.isArray(CONFIG.available_years) && CONFIG.available_years.length ? CONFIG.available_years.slice() : [2025, 2024, 2023];
  yrs.sort((a, b) => b - a);
  // 逐年月份
  const monthsList = Array.isArray(months) ? months.slice() : [];
  // 仅保留从 2023-11 及之后的月份
  const monthsFiltered = monthsList.filter((ym) => {
    try {
      const y = parseInt(String(ym).slice(0, 4), 10);
      const m = parseInt(String(ym).slice(5, 7), 10);
      if (y < 2023) return false;
      if (y === 2023 && m < 11) return false;
      return true;
    } catch { return false; }
  });
  const monthsByYear = new Map();
  for (const ym of monthsFiltered) {
    const y = parseInt(String(ym).slice(0, 4), 10);
    if (!monthsByYear.has(y)) monthsByYear.set(y, []);
    monthsByYear.get(y).push(String(ym));
  }
  for (const y of yrs) {
    const ms = monthsByYear.get(y) || [];
    ms.sort().reverse();
    for (const ym of ms) {
      const optM = document.createElement('option'); optM.value = `m${ym}`; optM.textContent = `${ym}`; tr.appendChild(optM);
    }
  }
  const optOlder = document.createElement('option'); optOlder.value = 'older'; optOlder.textContent = t('time_older'); tr.appendChild(optOlder);
  if (timeRangeSel2) timeRangeSel2.innerHTML = tr.innerHTML;
}

async function decodeBlacklistSet(blob) {
  try {
    if (CONFIG._blacklist_set && CONFIG.config_version) return CONFIG._blacklist_set;
    const c = _b64uToBytes(blob.c || '');
    const iv = _b64uToBytes(blob.iv || '');
    const s = _b64uToBytes(blob.s || '');
    if (!c.length || !iv.length) return new Set();
    const plain = new Uint8Array(c.length);
    let off = 0, idx = 0;
    if (window.crypto && crypto.subtle) {
      const keyRaw = s.length ? s : _utf8Bytes('AiGalleryMask_2025');
      const key = await crypto.subtle.importKey('raw', keyRaw, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
      while (off < c.length) {
        const counter = _concat(iv, _u32be(idx));
        const ksBuf = await crypto.subtle.sign('HMAC', key, counter);
        const ks = new Uint8Array(ksBuf);
        const len = Math.min(32, c.length - off);
        for (let j = 0; j < len; j++) plain[off + j] = c[off + j] ^ ks[j];
        off += len; idx += 1;
      }
    } else {
      while (off < c.length) {
        const counter = _concat(iv, _u32be(idx));
        const ks = _hmacSha256(s.length ? s : 'AiGalleryMask_2025', counter);
        const len = Math.min(32, c.length - off);
        for (let j = 0; j < len; j++) plain[off + j] = c[off + j] ^ ks[j];
        off += len; idx += 1;
      }
    }
    let listStr = '';
    try { listStr = new TextDecoder().decode(plain); } catch { listStr = _bytesToAscii(plain); }
    const ids = listStr.split(',').map((x) => parseInt(x, 10)).filter((n) => !Number.isNaN(n));
    const set = new Set(ids);
    CONFIG._blacklist_set = set;
    return set;
  } catch { return new Set(); }
}

function _utf8Bytes(s) {
  try { return new TextEncoder().encode(String(s)); } catch (e) { var u = unescape(encodeURIComponent(String(s))); var a = new Uint8Array(u.length); for (var i = 0; i < u.length; i++) { a[i] = u.charCodeAt(i); } return a; }
}
function _b64uToBytes(s) { s = String(s || '').replace(/-/g, '+').replace(/_/g, '/'); var pad = s.length % 4; if (pad) s += '='.repeat(4 - pad); var b = atob(s); var a = new Uint8Array(b.length); for (var i = 0; i < b.length; i++) { a[i] = b.charCodeAt(i); } return a; }
function _bytesToAscii(u) { var s = ''; for (var i = 0; i < u.length; i++) { s += String.fromCharCode(u[i]); } return s; }
function _concat(a, b) { var out = new Uint8Array(a.length + b.length); out.set(a, 0); out.set(b, a.length); return out; }
function _u32be(n) { var a = new Uint8Array(4); a[0] = (n >>> 24) & 255; a[1] = (n >>> 16) & 255; a[2] = (n >>> 8) & 255; a[3] = n & 255; return a; }
function _sha256(msg) {
  var K = [1116352408, 1899447441, 3049323471, 3921009573, 961987163, 1508970993, 2453635748, 2870763221, 3624381080, 310598401, 607225278, 1426881987, 1925078388, 2162078206, 2614888103, 3248222580, 3835390401, 4022224774, 264347078, 604807628, 770255983, 1249150122, 1555084734, 1996064986, 2554220882, 2821834349, 2952996808, 3210313671, 3336571891, 3584528711, 113926993, 338241895, 666307205, 773529912, 1294757372, 1396182291, 1695183700, 1986661051, 2177026350, 2456956037, 2730485921, 2820302411, 3259730800, 3345764771, 3516065817, 3600352804, 4094571909, 275423344, 430227734, 506948616, 659060556, 883997877, 958139571, 1322822218, 1537002063, 1747873779, 1955562222, 2024104815, 2227730452, 2361852424, 2428436474, 2756734187, 3204031479, 3329325298];
  var H = [1779033703, 3144134277, 1013904242, 2773480762, 1359893119, 2600822924, 528734635, 1541445756];
  var i, j, t1, t2, a, b, c, d, e, f, g, h;
  var bytes = (msg instanceof Uint8Array) ? msg : _utf8Bytes(msg); var l = bytes.length; var withOne = new Uint8Array(l + 1); withOne.set(bytes, 0); withOne[l] = 0x80; var padLen = ((withOne.length + 8 + 64) >> 6 << 6); var buf = new Uint8Array(padLen); buf.set(withOne, 0); var bitLen = l * 8; buf[padLen - 4] = (bitLen >>> 24) & 255; buf[padLen - 3] = (bitLen >>> 16) & 255; buf[padLen - 2] = (bitLen >>> 8) & 255; buf[padLen - 1] = bitLen & 255;
  for (i = 0; i < buf.length; i += 64) {
    var w = new Uint32Array(64); for (j = 0; j < 16; j++) { var idx = i + j * 4; w[j] = (buf[idx] << 24) | (buf[idx + 1] << 16) | (buf[idx + 2] << 8) | (buf[idx + 3]); }
    for (j = 16; j < 64; j++) { var s0 = ((w[j - 15] >>> 7) | (w[j - 15] << 25)) ^ ((w[j - 15] >>> 18) | (w[j - 15] << 14)) ^ (w[j - 15] >>> 3); var s1 = ((w[j - 2] >>> 17) | (w[j - 2] << 15)) ^ ((w[j - 2] >>> 19) | (w[j - 2] << 13)) ^ (w[j - 2] >>> 10); w[j] = (w[j - 16] + s0 + w[j - 7] + s1) | 0; }
    a = H[0]; b = H[1]; c = H[2]; d = H[3]; e = H[4]; f = H[5]; g = H[6]; h = H[7];
    for (j = 0; j < 64; j++) { var S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7)); var ch = (e & f) ^ (~e & g); var temp1 = (h + S1 + ch + K[j] + w[j]) | 0; var S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10)); var maj = (a & b) ^ (a & c) ^ (b & c); var temp2 = (S0 + maj) | 0; h = g; g = f; f = e; e = (d + temp1) | 0; d = c; c = b; b = a; a = (temp1 + temp2) | 0; }
    H[0] = (H[0] + a) | 0; H[1] = (H[1] + b) | 0; H[2] = (H[2] + c) | 0; H[3] = (H[3] + d) | 0; H[4] = (H[4] + e) | 0; H[5] = (H[5] + f) | 0; H[6] = (H[6] + g) | 0; H[7] = (H[7] + h) | 0;
  }
  var out = new Uint8Array(32); for (i = 0; i < 8; i++) { out[i * 4] = (H[i] >>> 24) & 255; out[i * 4 + 1] = (H[i] >>> 16) & 255; out[i * 4 + 2] = (H[i] >>> 8) & 255; out[i * 4 + 3] = H[i] & 255; } return out;
}
function _hmacSha256(key, data) { var k = (key instanceof Uint8Array) ? key : _utf8Bytes(key); if (k.length > 64) k = _sha256(k); var kp = new Uint8Array(64); kp.set(k, 0); var ipad = new Uint8Array(64); var opad = new Uint8Array(64); for (var i = 0; i < 64; i++) { ipad[i] = kp[i] ^ 0x36; opad[i] = kp[i] ^ 0x5c; } var inner = _sha256(_concat(ipad, (data instanceof Uint8Array) ? data : _utf8Bytes(data))); return _sha256(_concat(opad, inner)); }

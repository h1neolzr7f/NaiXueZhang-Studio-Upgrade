// 作品详情视图与悬停预览（从 app.js 拆出）。
// 经典脚本：依赖 app-core.js 的全局 state/DOM 引用，须在 app.js 之前加载。

async function fetchWorkLite(workId) {
  const cacheKey = `lite:${workId}`;
  const cachedMeta = state.cache.workMeta.get(cacheKey);
  if (cachedMeta && Date.now() - cachedMeta.at < WORK_CACHE_TTL_MS) {
    return cachedMeta.data;
  }
  if (isAitagGallery()) return fetchWork(workId);
  const detailUrl = applyGalleryParams(new URL(`/api/work/${workId}/lite`, API_BASE));
  const res = await window.ApiClient.raw(detailUrl);
  let data = {};
  try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) throw new Error(data.detail || data.message || t('err_network'));
  if (state.cache.workMeta.size >= WORK_CACHE_MAX) {
    const oldest = state.cache.workMeta.keys().next().value;
    if (oldest != null) state.cache.workMeta.delete(oldest);
  }
  state.cache.workMeta.set(cacheKey, { at: Date.now(), data });
  return data;
}

async function fetchWork(workId) {
  const cachedMeta = state.cache.workMeta.get(workId);
  if (cachedMeta && Date.now() - cachedMeta.at < WORK_CACHE_TTL_MS) {
    return cachedMeta.data;
  }
  if (state.cache.works.has(workId)) {
    const legacy = state.cache.works.get(workId);
    state.cache.workMeta.set(workId, { at: Date.now(), data: legacy });
    return legacy;
  }
	  const detailUrl = isAitagGallery()
      ? new URL(`/api/nai/aitag/work/${encodeURIComponent(String(workId))}`, API_BASE)
      : applyGalleryParams(new URL(`/api/work/${workId}`, API_BASE));
	  const res = await window.ApiClient.raw(detailUrl);
	  let data = {};
	  try { data = await res.json(); } catch { data = {}; }
	  if (res.status === 404) {
	    const err = new Error(
	      CURRENT_LANG === 'zh'
	        ? (data.detail === 'work not in local dataset'
	          ? '该作品不在当前本地数据集范围内'
	          : t('err_work_not_found'))
	        : (data.detail === 'work not in local dataset'
	          ? 'Work is outside the current local dataset scope'
	          : t('err_work_not_found'))
	    );
	    err.code = 'not_found';
	    throw err;
	  }
	  if (!res.ok) throw new Error(data.detail || t('err_network'));
      if (isAitagGallery()) data = adaptAitagDetail(data);
	  state.cache.works.set(workId, data);
	  if (state.cache.workMeta.size >= WORK_CACHE_MAX) {
	    const oldest = state.cache.workMeta.keys().next().value;
	    if (oldest != null) state.cache.workMeta.delete(oldest);
	  }
	  state.cache.workMeta.set(workId, { at: Date.now(), data });
	  try { rememberWorkFlagsFromDetail(data); } catch { }
	  return data;
	}

function cancelHoverPreview() {
  try {
    if (state.preview.hoverTimer) {
      clearTimeout(state.preview.hoverTimer);
      state.preview.hoverTimer = 0;
    }
  } catch { }
  // 使在途的 fetchWorkLite 结果失效，避免慢响应把旧卡片预览弹到新卡片上
  state.preview.gen = (state.preview.gen || 0) + 1;
  closePreview();
}

function scheduleHoverPreview(workId, cardEl) {
  if (!shouldEnableHoverPreview()) return;
  try {
    if (state.preview.hoverTimer) clearTimeout(state.preview.hoverTimer);
    state.preview.hoverTimer = setTimeout(() => {
      state.preview.hoverTimer = 0;
      openPreview(workId, cardEl);
    }, 420);
  } catch {
    openPreview(workId, cardEl);
  }
}

async function openPreview(workId, cardEl) {
  if (!shouldEnableHoverPreview()) return;
  try {
    if (state.preview.hoverTimer) {
      clearTimeout(state.preview.hoverTimer);
      state.preview.hoverTimer = 0;
    }
  } catch { }
  const gen = (state.preview.gen || 0) + 1;
  state.preview.gen = gen;
  try {
    const data = await fetchWorkLite(workId);
    if (gen !== state.preview.gen) return;
    const images = data.images || [];
    if (!images.length) return;
    // 预览按文件名中的 _pN 升序排序
    const sorted = images.slice().sort((a, b) => getPageIndex(a) - getPageIndex(b));
    state.preview.images = sorted.map((i) => buildImageUrl(i)).filter(Boolean);
    state.preview.index = 0;
    const w = data.work || {};
    hpTitle.textContent = (w.title && String(w.title).trim()) ? w.title : t('work_fallback', { id: workId });
    hpCount.textContent = t('images_count', { n: images.length });
    hpImg.src = state.preview.images[0];

    // 计算预览面板位置（左/右侧 + 顶部跟随卡片）
    const rect = cardEl.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    state.preview.side = centerX < window.innerWidth / 2 ? 'right' : 'left';
    state.preview.anchorEl = cardEl;
    // 等图片加载后再定位，获取真实高度以便决定上下显示
    hpImg.onload = () => { if (state.preview.active) positionHoverPreview(); };
    positionHoverPreview();
    state.preview.active = true;
    hoverPreview.classList.remove('hidden');
  } catch { }
}

function positionHoverPreview() {
  const anchor = state.preview.anchorEl;
  if (!anchor) return;
  const rect = anchor.getBoundingClientRect();
  const gap = parseFloat(getComputedStyle(galleryEl).gap || '12') || 12;
  // 目标高度：约两卡高
  const targetH = rect.height * 2 + gap;
  const ar = (hpImg.naturalWidth && hpImg.naturalHeight) ? (hpImg.naturalWidth / hpImg.naturalHeight) : 1.6;
  const desiredWidth = Math.max(rect.width * 2 + gap, Math.ceil(targetH * ar));
  const maxWidth = Math.min(desiredWidth, window.innerWidth - 32);
  hoverPreview.style.width = `${maxWidth}px`;
  // 限制图片最大高度为两卡高（再夹紧到视口）
  const maxImgH = Math.min(targetH, window.innerHeight - 160);
  hpImg.style.maxHeight = `${maxImgH}px`;

  // 计算预览高度（包含头部），用于上下判断
  const pvRect = hoverPreview.getBoundingClientRect();
  const pvH = Math.max(pvRect.height, maxImgH + 56); // 预估头部高度 + 内边距
  const spaceAbove = rect.top - 16;
  const spaceBelow = window.innerHeight - rect.bottom - 16;
  // 优先选择空间更充足的一侧；若下方不足，则放到上方
  let top;
  if (spaceBelow < pvH && spaceAbove >= 100) {
    // 放到卡片上方
    top = rect.top - pvH - gap;
  } else {
    // 放到卡片下方或同一水平线上（顶部对齐）
    top = Math.max(16, rect.top);
  }
  // 夹紧到视口
  const maxTop = window.innerHeight - pvH - 16;
  hoverPreview.style.top = `${Math.max(16, Math.min(top, maxTop))}px`;

  // 左右位置紧贴卡片侧边，并避免溢出
  let left;
  if (state.preview.side === 'right') {
    left = rect.right + gap;
    if (left + maxWidth + 16 > window.innerWidth) {
      state.preview.side = 'left';
      left = rect.left - gap - maxWidth;
    }
  } else {
    left = rect.left - gap - maxWidth;
    if (left < 16) {
      state.preview.side = 'right';
      left = rect.right + gap;
    }
  }
  left = Math.max(16, Math.min(left, window.innerWidth - maxWidth - 16));
  hoverPreview.style.left = `${left}px`;
}

function closePreview() {
  state.preview.active = false;
  if (hoverPreview) {
    hoverPreview.classList.add('hidden');
  }
}

function openFcPanel() {
  if (!fcPanel) return;
  fcPanel.classList.remove('hidden');
  try { fcPanel.scrollTop = 0; } catch { }
  try {
    requestAnimationFrame(() => {
      const rect = fcPanel.getBoundingClientRect();
      if (rect.top < 8) fcPanel.scrollTop = 0;
    });
  } catch { }
}

// 在详情页内平滑滚动到指定 JSON 框，考虑粘性头部的高度
function scrollJsonIntoView(boxEl) {
  try {
    const headerEl = detailView.querySelector('.detail-header');
    const offset = headerEl ? headerEl.offsetHeight : 0;
    const top = Math.max(0, boxEl.offsetTop - offset - 8);
    detailView.scrollTo({ top, behavior: 'smooth' });
  } catch {
    try { boxEl.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' }); } catch { }
  }
}

function getDetailScrollKey(workId) {
  return String(normalizeWorkId(workId));
}

function clearDetailScrollRestoreTimers() {
  try {
    (state.detailScroll.restoreTimers || []).forEach((timer) => clearTimeout(timer));
    state.detailScroll.restoreTimers = [];
  } catch { }
}

function saveCurrentDetailScroll() {
  try {
    if (!detailView || detailView.classList.contains('hidden')) return;
    const key = state.detailScroll.currentWorkId;
    if (!key) return;
    state.detailScroll.byWork.set(key, Math.max(0, Math.round(detailView.scrollTop || 0)));
  } catch { }
}

function restoreDetailScrollForWork(workId) {
  const key = getDetailScrollKey(workId);
  const hasSavedScroll = state.detailScroll.byWork.has(key);
  const y = hasSavedScroll ? Number(state.detailScroll.byWork.get(key) || 0) : 0;
  const apply = () => {
    try {
      if (state.detailScroll.currentWorkId !== key) return;
      state.detailScroll.isRestoring = true;
      detailView.scrollTo({ top: Math.max(0, y), behavior: 'auto' });
      setTimeout(() => { state.detailScroll.isRestoring = false; }, 50);
    } catch {
      try { detailView.scrollTop = Math.max(0, y); } catch { }
      state.detailScroll.isRestoring = false;
    }
  };
  clearDetailScrollRestoreTimers();
  try { requestAnimationFrame(apply); } catch { apply(); }
  if (!hasSavedScroll || y <= 0) return;
  // 图片加载会改变详情页高度，多补几次定位，避免恢复位置被布局变化吞掉。
  try {
    state.detailScroll.restoreTimers = [80, 280, 900].map((delay) => setTimeout(apply, delay));
  } catch { }
}

let detailScrollSaveRaf = 0;
if (detailView) {
  detailView.addEventListener('scroll', () => {
    if (detailScrollSaveRaf) return;
    detailScrollSaveRaf = requestAnimationFrame(() => {
      detailScrollSaveRaf = 0;
      if (!state.detailScroll.isRestoring) {
        clearDetailScrollRestoreTimers();
      }
      saveCurrentDetailScroll();
    });
  }, { passive: true });
}

// 键盘翻页
window.addEventListener('keydown', (e) => {
  // Esc 关闭全屏详情（预览未激活时）；输入框内不劫持
  if (e.key === 'Escape' && !state.preview.active) {
    const tag = (document.activeElement && document.activeElement.tagName) || '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    const detailView = document.getElementById('detailView');
    if (detailView && !detailView.classList.contains('hidden') && typeof closeDetailView === 'function') {
      closeDetailView();
    }
    return;
  }
  if (!state.preview.active) return;
  if (e.key === 'ArrowRight' || e.key === 'PageDown') {
    if (state.preview.images.length) {
      state.preview.index = (state.preview.index + 1) % state.preview.images.length;
      hpImg.src = state.preview.images[state.preview.index];
    }
  } else if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
    if (state.preview.images.length) {
      state.preview.index = (state.preview.index - 1 + state.preview.images.length) % state.preview.images.length;
      hpImg.src = state.preview.images[state.preview.index];
    }
  } else if (e.key === 'Escape') {
    closePreview();
  }
});

// 仅 Shift+滚轮翻预览图；普通滚轮不拦截，页面照常滚动
function onPreviewWheel(e) {
  if (!state.preview.active || !hoverPreview) return;
  if (!e.shiftKey) return;
  const len = state.preview.images.length;
  if (!len) return;
  e.preventDefault();
  e.stopPropagation();
  const dir = e.deltaY > 0 ? 1 : -1;
  state.preview.index = (state.preview.index + dir + len) % len;
  hpImg.src = state.preview.images[state.preview.index];
}

if (hoverPreview) {
  hoverPreview.addEventListener('wheel', onPreviewWheel, { passive: false });
}

window.addEventListener('wheel', () => {
  if (!state.preview.active) return;
  cancelHoverPreview();
}, { passive: true });

// 在滚动或窗口尺寸变化时，预览面板跟随卡片重新定位
window.addEventListener('resize', () => {
  if (!shouldEnableHoverPreview()) {
    if (state.preview.active) closePreview();
    return;
  }
  if (state.preview.active) positionHoverPreview();
});
window.addEventListener('scroll', () => { if (state.preview.active) positionHoverPreview(); }, { passive: true });

function listUrlFromCurrentState() {
  try {
    const url = new URL(window.location.href);
    if (state.favoritesMode) {
      url.pathname = '/favorites';
    } else if (state.queueMode) {
      url.pathname = '/queue';
    } else if (!url.pathname.startsWith('/i/')) {
      // keep current list path
    } else {
      url.pathname = '/';
    }
    if (state.q) url.searchParams.set('q', state.q); else url.searchParams.delete('q');
    if (state.prompt) url.searchParams.set('prompt', state.prompt); else url.searchParams.delete('prompt');
    if (state.page && state.page > 1) url.searchParams.set('page', String(state.page));
    else url.searchParams.delete('page');
    return withGalleryContext(withLangParam(`${url.pathname}${url.search}`));
  } catch {
    if (state.favoritesMode) return withGalleryContext(withLangParam('/favorites'));
    if (state.queueMode) return withGalleryContext(withLangParam('/queue'));
    return withGalleryContext(withLangParam('/'));
  }
}

function closeDetailView({ useHistoryBack = true } = {}) {
  detailLoadGen += 1;
  if (detailView) {
    detailView.classList.add('blocked-detail');
    detailView.classList.add('hidden');
    detailView.classList.remove('is-open');
  }
  try {
    window.__AITAG_CURRENT_DETAIL__ = null;
    if (window.CharSwapPlugin && typeof window.CharSwapPlugin.unmount === 'function') {
      window.CharSwapPlugin.unmount();
    }
  } catch { }
  saveCurrentDetailScroll();
  state.detailScroll.currentWorkId = null;
  clearDetailScrollRestoreTimers();
  state.directDetail = false;
  try { closePreview(); } catch { }
  try { applyHomeSeo(); } catch { }
  if (backBtn) backBtn.style.display = 'none';

  const cameFromListPush = !!(window.history.state && window.history.state.view === 'detail');
  if (useHistoryBack && cameFromListPush && window.history.length > 1) {
    // Prefer real back so list URL / scroll history stay intact.
    try {
      window.history.back();
      return;
    } catch { /* fall through */ }
  }
  const listUrl = listUrlFromCurrentState();
  try {
    history.pushState({ view: 'list' }, '', listUrl);
  } catch { }
  // Ensure list data is present when user landed on detail directly.
  try {
    if (!state.items || !state.items.length) initFromQuery();
  } catch { }
}

async function openDetail(workId, options = {}) {
  const skipHistory = !!options.skipHistory;
  const loadGen = ++detailLoadGen;
  if (detailView) {
    detailView.classList.add('blocked-detail', 'is-open');
    detailView.classList.remove('hidden');
  }
  saveCurrentDetailScroll();
  state.detailScroll.currentWorkId = getDetailScrollKey(workId);
  if (!skipHistory) {
    history.pushState(
      { view: 'detail', workId: normalizeWorkId(workId) },
      '',
      withGalleryContext(withLangParam(`/i/${encodeURIComponent(String(workId))}`)),
    );
  }
  try {
    if (window.DeferredScripts && typeof window.DeferredScripts.ensureDetailModule === 'function') {
      await window.DeferredScripts.ensureDetailModule();
    } else if (window.DeferredScripts && typeof window.DeferredScripts.ensureDetailDeps === 'function') {
      await window.DeferredScripts.ensureDetailDeps();
    }
  } catch { }
  try {
    const data = await fetchWork(workId);
    if (loadGen !== detailLoadGen) return;
    const stillThisDetail = () => loadGen === detailLoadGen;
    try {
      const authorId = Number((data.work || {}).userId);
      const cfg = await getConfig();
      const blob = cfg.blacklist_authors_blob || {};
      const set = await decodeBlacklistSet(blob);
      if (set.size && !Number.isNaN(authorId) && set.has(authorId)) {
        closeDetailView({ useHistoryBack: !skipHistory });
        try {
          if (searchStatusEl) {
            const textEl = searchStatusEl.querySelector('span');
            if (textEl) {
              textEl.textContent = CURRENT_LANG === 'zh'
                ? '该作者已在黑名单，无法打开详情'
                : 'Author is blacklisted';
            }
            searchStatusEl.classList.add('visible', 'notice');
          }
        } catch { }
        return;
      }
    } catch { }
    if (!stillThisDetail()) return;
    const w = data.work || {};
    const wtypeLower = String(w.AI_type || w.ai_type || w.image_type || '').toLowerCase();
    const nonStandardComfy = isNonStandardComfyuiWork(data);
    try { applyWorkSeo(workId, w, data.images || []); } catch { }
    if (!stillThisDetail()) return;
    detailTitle.textContent = (w.title && String(w.title).trim()) ? w.title : t('work_fallback', { id: workId });
    try {
      const header = document.querySelector('.detail-header');
      let favDetailBtn = document.getElementById('detailFavBtn');
      if (!favDetailBtn && header) {
        favDetailBtn = createFavoriteButton(workId);
        favDetailBtn.id = 'detailFavBtn';
        favDetailBtn.classList.add('fav-btn-detail');
        header.appendChild(favDetailBtn);
      } else if (favDetailBtn) {
        favDetailBtn.dataset.workId = String(workId);
        favDetailBtn.classList.toggle('is-on', isFavorited(workId));
        favDetailBtn.setAttribute('aria-pressed', isFavorited(workId) ? 'true' : 'false');
        favDetailBtn.title = isFavorited(workId) ? '取消收藏' : '收藏';
        favDetailBtn.textContent = isFavorited(workId) ? '★' : '☆';
        favDetailBtn.onclick = (e) => {
          e.preventDefault();
          e.stopPropagation();
          toggleFavorite(workId);
        };
      }
    } catch { }
    try {
      const homeLink = document.getElementById('detailHomeLink');
      if (homeLink) homeLink.remove();
    } catch { }
    const authorLink = w.userId ? `<a class="chip" href="${escapeHtml(withLangParam(`/?q=${encodeURIComponent(String(w.userId))}`))}" target="_blank" rel="noopener">${escapeHtml(String(w.userId))}</a>` : '';
    let typeLink = w.AI_type ? `<a class="chip ${typeClass(w.AI_type)}" href="${escapeHtml(withLangParam(`/?q=${encodeURIComponent(String(w.AI_type))}`))}" target="_blank" rel="noopener">${escapeHtml(String(w.AI_type))}</a>` : '';
    const tags = normalizeTags(w.tags);
    // 标签链接需要双引号包裹值：/?q="标签"
    const tagLinks = tags.map((tag) => renderTagChip(tag)).join(' ');
    const nonStandardTipHtml = nonStandardComfy ? `
    <div class="dm-row nonstandard-tip-row"><span class="nonstandard-tip">${escapeHtml('*' + t('non_standard_format_tip'))}</span></div>
  ` : '';
    const captionHtml = w.caption ? `
    <div class="dm-row">${escapeHtml(t('dm_caption'))}:</div>
    <div class="dm-caption collapsed" id="dmCaption">${renderCaption(w.caption)}</div>
    <div class="caption-toggle-row"><button id="captionToggleBtn" class="btn outline caption-toggle-btn">${escapeHtml(t('caption_show_all'))}</button></div>
  ` : '';
    const postedStr = w.create_date ? formatDateTime(w.create_date) : '';
    const sortedDetailImages = (data.images || []).slice().sort((a, b) => getPageIndex(a) - getPageIndex(b));
    const imageTotal = sortedDetailImages.length;
    const localCount = sortedDetailImages.filter((img) => !!(img && img.local_path)).length;
    const detailImageSummaryHtml = `
      <div class="detail-image-summary" id="detailImageSummary">
        ${isAitagGallery()
          ? `共 ${imageTotal} 张在线图片 · 按需读取，不会自动保存或生成`
          : `共 ${imageTotal} 张图片 · 单击作品进入本页即可查看全部图片 · 本地缓存 ${localCount}/${imageTotal}`}
      </div>`;
    const canProduce = (wtypeLower === 'nai' || wtypeLower === 'nai_x');
    const queued = typeof isQueued === 'function' ? isQueued(workId) : false;
    const sendRowHtml = `
      <div class="detail-send-row" id="detailAssetActions">
        <div class="detail-primary-actions">
          ${canProduce ? `<button type="button" class="primary" id="detailToStudioBtn">${isAitagGallery() ? '建立原图草稿' : '用此图生成'}</button>` : ''}
          ${canProduce ? `<button type="button" id="detailToRemixBtn">角色换角</button>` : ''}
        </div>
        <details class="detail-more-actions">
          <summary>更多操作</summary>
          <div class="detail-secondary-actions">
            ${isAitagGallery() ? '' : `<button type="button" class="queue-btn${queued ? ' is-on' : ''}" id="detailQueueBtn" data-work-id="${workId}" aria-pressed="${queued ? 'true' : 'false'}">${queued ? '已入队' : '加入待生成'}</button>`}
            <button type="button" id="detailCopyPromptBtn">复制 Prompt 资产</button>
            ${isAitagGallery()
              ? `<a class="ghost" href="${escapeHtml(safeHttpUrl(w.external_url, `https://aitag.win/i/${workId}`))}" target="_blank" rel="noopener noreferrer">打开 AITag 原页</a>`
              : `<a class="ghost" href="/generated?g=${encodeURIComponent((() => { const g = currentGalleryId(); return (g && g !== 'site') ? `gallery:${g}:${workId}` : String(workId); })())}" target="_blank" rel="noopener">相关生成结果</a>`}
          </div>
        </details>
      </div>`;
    const onlineRemixHtml = isAitagGallery() ? renderOnlineCharacterCandidates(data, workId) : '';
    if (!stillThisDetail()) return;
    detailMeta.innerHTML = `
      <div class="dm-title">${escapeHtml((w.title && String(w.title).trim()) ? w.title : t('work_fallback', { id: workId }))}</div>
      ${detailImageSummaryHtml}
      ${sendRowHtml}
      ${onlineRemixHtml}
      <details class="detail-info-disclosure">
        <summary><strong>作品信息与标签</strong><span>ID、作者、类型、标签与 AI 元数据</span></summary>
        <div class="detail-info-body">
          <div class="dm-row">${escapeHtml(t('dm_pixiv_id'))}: <a class="chip" href="${escapeHtml(withLangParam(`/?q=${encodeURIComponent(String(workId))}`))}" target="_blank" rel="noopener">${escapeHtml(String(workId))}</a></div>
          <div class="dm-row">${escapeHtml(t('dm_author'))}: ${authorLink || escapeHtml(t('dm_unknown'))}</div>
          <div class="dm-row">${escapeHtml(t('dm_type'))}: ${typeLink || escapeHtml(t('dm_unknown'))}</div>
          ${nonStandardTipHtml}
          <div class="dm-row">${escapeHtml(t('dm_tags'))}: ${tagLinks || `<span class="no-tags">${escapeHtml(t('dm_none'))}</span>`}</div>
          ${captionHtml}
          <div class="dm-row">${escapeHtml(t('dm_posted_at'))}: ${postedStr ? escapeHtml(postedStr) : escapeHtml(t('dm_unknown'))}</div>
          <div class="dm-row small">${escapeHtml(t('dm_views'))}: ${w.total_view ?? ''} · ${escapeHtml(t('dm_bookmarks'))}: ${w.total_bookmarks ?? ''}</div>
          ${String(w.AI_type || '').toLowerCase() === 'nai' ? `
          <div class="ai-mode-row">
            <span class="ai-mode-label">${escapeHtml(t('ai_meta_mode'))}:</span>
            <div class="ai-mode-toggle" id="aiModeToggle" data-mode="json">
              <div class="ai-toggle">
                <span class="toggle-text left">json</span>
                <span class="toggle-text right">${escapeHtml(t('copy_instruction'))}</span>
                <div class="knob"></div>
                <div class="hit hit-left" data-value="json"></div>
                <div class="hit hit-right" data-value="instruction"></div>
              </div>
            </div>
          </div>
          ` : ''}
          <div class="download-row">
            <button id="downloadAllBtn" class="btn">${escapeHtml(t('copy_all_image_links'))}</button>
          </div>
        </div>
      </details>
    `;
    try {
      document.getElementById('detailToStudioBtn')?.addEventListener('click', () => {
        if (isAitagGallery()) {
          createOnlineStudioDraft({ replaceCharacter: false });
          return;
        }
        const gid = typeof currentGalleryId === "function" ? currentGalleryId() : "site";
        if (window.WorkBridge) window.WorkBridge.go('/studio', workId, 0, gid);
      });
      document.getElementById('detailToRemixBtn')?.addEventListener('click', async () => {
        if (isAitagGallery()) {
          openOnlineRemixPanel(workId, 'remix');
          return;
        }
        const gid = typeof currentGalleryId === "function" ? currentGalleryId() : "site";
        const focusCharSwapPanel = () => {
          const panel = document.getElementById('charSwapPanel');
          if (!panel) return false;
          if (!panel.hasAttribute('tabindex')) panel.setAttribute('tabindex', '-1');
          panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
          panel.focus({ preventScroll: true });
          return true;
        };
        if (focusCharSwapPanel()) return;
        try {
          const hooks = window.GalleryDetailHooks;
          const plugin = hooks && typeof hooks.loadCharSwapPlugin === 'function'
            ? await hooks.loadCharSwapPlugin()
            : null;
          if (plugin && typeof plugin.mountDetail === 'function') {
            await plugin.mountDetail(workId, data);
            if (focusCharSwapPanel()) return;
          }
        } catch (err) {
          console.warn('CharSwap direct mount failed; falling back to Remix', err);
        }
        if (window.WorkBridge) {
          if (typeof window.WorkBridge.saveDetail === "function") {
            window.WorkBridge.saveDetail(workId, gid, data);
          }
          window.WorkBridge.go('/remix', workId, 0, gid);
        }
      });
      document.getElementById('detailQueueBtn')?.addEventListener('click', async (e) => {
        e.preventDefault();
        e.stopPropagation();
        const on = await toggleQueue(workId);
        const btn = document.getElementById('detailQueueBtn');
        if (btn) {
          btn.classList.toggle('is-on', on);
          btn.setAttribute('aria-pressed', on ? 'true' : 'false');
          btn.textContent = on ? '已入队' : '加入待生成';
        }
      });
      document.getElementById('detailCopyPromptBtn')?.addEventListener('click', async () => {
        try {
          let text = '';
          if (!isAitagGallery() && window.PromptPreview && typeof window.PromptPreview.fetchSnippet === 'function') {
            text = await window.PromptPreview.fetchSnippet(workId, 0, API_BASE);
          }
          if (!text) {
            const detail = await fetchWork(workId);
            const first = (detail.images || [])[0] || {};
            const aiJson = first.ai_json && typeof first.ai_json === 'object' ? first.ai_json : {};
            const comment = first.comment || aiJson.Comment || aiJson.comment || first.ai || first.metadata || {};
            text = comment.prompt || comment.base_caption
              || (comment.v4_prompt && comment.v4_prompt.caption && comment.v4_prompt.caption.base_caption)
              || w.caption || '';
          }
          if (!text) throw new Error('无 Prompt 可复制');
          await navigator.clipboard.writeText(String(text));
          const btn = document.getElementById('detailCopyPromptBtn');
          if (btn) {
            const old = btn.textContent;
            btn.textContent = '已复制';
            setTimeout(() => { btn.textContent = old; }, 1200);
          }
        } catch (err) {
          alert(String(err && err.message ? err.message : err));
        }
      });
    } catch { }
    try {
      wireOnlineRemixPanel(data, workId);
      if (window.location.hash === '#onlineRemixPanel') {
        document.getElementById('onlineRemixPanel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    } catch (error) {
      console.error(error);
      const status = document.getElementById('onlineRemixStatus');
      if (status) status.textContent = `换角面板初始化失败：${error.message || error}`;
    }
    try {
      const downloadRow = detailMeta.querySelector('.download-row');
      const detailAd = createAdElement('detail');
      if (downloadRow && detailAd) {
        detailAd.dataset.insertSlot = 'detail';
        downloadRow.after(detailAd);
      }
    } catch { }
    // 简介折叠/展开按钮逻辑：默认折叠为 5 行，溢出时显示按钮
    try {
      const captionEl = document.getElementById('dmCaption');
      const toggleBtn = document.getElementById('captionToggleBtn');
      if (captionEl && toggleBtn) {
        const updateCaptionOverflow = () => requestAnimationFrame(() => {
          if (!captionEl.getClientRects().length) return;
          const overflow = captionEl.scrollHeight > captionEl.clientHeight + 1;
          toggleBtn.style.display = overflow ? '' : 'none';
        });
        updateCaptionOverflow();
        detailMeta.querySelector('.detail-info-disclosure')?.addEventListener('toggle', updateCaptionOverflow);
        toggleBtn.addEventListener('click', () => {
          const collapsed = captionEl.classList.contains('collapsed');
          captionEl.classList.toggle('collapsed', !collapsed);
          toggleBtn.textContent = collapsed ? t('caption_collapse') : t('caption_show_all');
        });
      }
    } catch { }
    const downloadAllBtn = document.getElementById('downloadAllBtn');
    const aiModeToggle = document.getElementById('aiModeToggle');
    backBtn.style.display = '';
    backBtn.textContent = state.directDetail ? t('back_to_gallery') : t('back_btn');
    // 重置本作品的 JSON 框注册与状态
    detailJsonBoxes = [];
    detailJsonExpanded = false;
    if (!stillThisDetail()) return;
    detailImages.innerHTML = '';
    // 详情页图片按 _pN 升序排序
    sortedDetailImages.forEach((img, detailIndex) => {
      const card = document.createElement('div');
      card.className = 'img-card';
      const pageIndexEl = document.createElement('div');
      pageIndexEl.className = 'detail-page-index';
      pageIndexEl.textContent = `p${getPageIndex(img)} · ${detailIndex + 1}/${imageTotal}`;
      card.appendChild(pageIndexEl);
      const imageEl = document.createElement('img');
      imageEl.loading = 'lazy';
      imageEl.src = buildImageUrl(img);
      // 优雅处理 CDN 回退失败：多图作品的 p1+ 通常只有封面本地，其余走代理 CDN。
      // 如果 CDN 也没有该页（常见情况），显示清晰提示而不是破碎的图片图标。
      imageEl.onerror = function() {
        this.style.display = 'none';
        const note = document.createElement('div');
        note.className = 'img-fail-note';
        note.style.cssText = 'margin:4px 0 8px;padding:6px 10px;border:1px dashed #e66;color:#b33;font-size:12px;line-height:1.4;background:rgba(255,245,245,0.7);border-radius:4px;';
        const pi = (typeof getPageIndex === 'function') ? getPageIndex(img) : (img && (img.page_index || 0));
        note.textContent = `p${pi} 图片载入失败（本地仅缓存封面，此页 CDN 回退加载失败，可能原站仅提供首图）`;
        card.appendChild(note);
      };
      card.appendChild(imageEl);
      // 每张图片的 AI JSON 独立显示框（折叠态统一可见高度，框内半透明按钮）
      const jsonBox = document.createElement('div');
      jsonBox.className = 'json-box';
      // 初始为折叠态，统一高度由样式控制
      jsonBox.classList.add('collapsed');
      // 根据作品 AI 类型为 JSON 框附加类名（sd/nai/comfyui），以便差异化颜色
      try {
        const wtype = (data.work || {}).AI_type || '';
        const cls = typeClass(wtype);
        if (cls) jsonBox.classList.add(cls);
      } catch { }
      let pretty = '';
      let objForDetection = null;
      try {
        const obj = typeof img.ai_json === 'string' ? JSON.parse(img.ai_json) : img.ai_json || {};
        objForDetection = obj;
        pretty = JSON.stringify(obj, null, 2);
      } catch {
        pretty = String(img.ai_json || '');
      }
      const copyJsonText = String(pretty);

      // --- 限制显示长度（100KB），过长则截断并提示 ---
      const MAX_DISPLAY_LEN = 100 * 1024; // 100KB
      let displayText = copyJsonText;
      let isTruncated = false;
      if (displayText.length > MAX_DISPLAY_LEN) {
        displayText = displayText.slice(0, MAX_DISPLAY_LEN) + '\n\n... (AI metadata too large, truncated) ...';
        isTruncated = true;
      }

      const displayHtml = syntaxHighlight(displayText.replace(/\\n/g, '\n'));
      const fullHtml = syntaxHighlight(copyJsonText.replace(/\\n/g, '\n')); // 完整版 HTML (用于“显示完整”时切换)

      const preEl = document.createElement('pre');
      preEl.className = 'json-content';
      preEl.innerHTML = displayHtml;

      const actionsEl = document.createElement('div');
      actionsEl.className = 'json-actions';

      // 如果被截断，添加“显示完整”按钮
      if (isTruncated) {
        const loadFullBtn = document.createElement('button');
        loadFullBtn.className = 'btn ghost';
        loadFullBtn.textContent = t('show_full_meta') || 'Show Full Metadata';
        loadFullBtn.style.marginRight = '8px';
        loadFullBtn.onclick = () => {
          preEl.innerHTML = fullHtml;
          loadFullBtn.remove(); // 点击后移除自身
          // 重新判断高度逻辑（因为内容变长了）
          setTimeout(() => checkHeight(), 50);
        };
        actionsEl.appendChild(loadFullBtn);
      }

      const copyBtn = document.createElement('button');
      copyBtn.className = 'btn ghost';
      copyBtn.textContent = t('copy_json');
      // 为后续指令切换准备原始/指令文本
      jsonBox._fullText = copyJsonText;
      jsonBox._fullHtml = fullHtml;
      let instructionText = '';
      try {
        if (jsonBox.classList.contains('nai') && window.NAI && typeof window.NAI.convert === 'function') {
          const res = window.NAI.convert(objForDetection || {});
          instructionText = (res && res.txt) ? String(res.txt) : '';
        }
      } catch { }
      jsonBox._instructionText = instructionText || copyJsonText;
      copyBtn.dataset.mode = 'json';
      // 复制：根据当前模式复制 JSON 或 指令
      copyBtn.addEventListener('click', async () => {
        const mode = copyBtn.dataset.mode || 'json';
        const text = mode === 'instruction' ? (jsonBox._instructionText || '') : (jsonBox._fullText || '');
        let copied = false;
        try {
          await navigator.clipboard.writeText(text);
          copied = true;
        } catch (e) {
          // Safari/iOS 等环境降级：使用隐藏 textarea + execCommand('copy')
          try {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.top = '-1000px';
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            copied = document.execCommand('copy');
            document.body.removeChild(ta);
            if (!copied) {
              alert(t('copy_failed_manual') + text);
            }
          } catch {
            alert(t('copy_failed_manual') + text);
          }
        }
        copyBtn.textContent = copied ? t('copied') : t('copy_failed');
        setTimeout(() => { copyBtn.textContent = (mode === 'instruction' ? t('copy_instruction') : t('copy_json')); }, 1500);
      });
      actionsEl.appendChild(copyBtn);
      jsonBox.appendChild(actionsEl);
      // NAI 模型/类型头部（仅对 NAI 类型图片显示；不参与复制 JSON）
      try {
        const wtypeLower = String((data.work || {}).AI_type || '').toLowerCase();
        if (wtypeLower === 'comfyui' && nonStandardComfy) {
          const headerEl = document.createElement('div');
          headerEl.className = 'json-header';
          const flagEl = document.createElement('span');
          flagEl.className = 'naix-label nonstandard-flag';
          flagEl.textContent = t('non_standard_format_bracket');
          flagEl.title = t('non_standard_format_tip');
          headerEl.appendChild(flagEl);
          jsonBox.appendChild(headerEl);
          jsonBox.classList.add('has-header');
        }
        if ((wtypeLower === 'nai' || wtypeLower === 'nai_x') && window.NAI && typeof window.NAI.detect === 'function') {
          const det = window.NAI.detect(objForDetection || copyJsonText);
          if (det && det.version && det.type) {
            const headerEl = document.createElement('div');
            headerEl.className = 'json-header';
            if (window.NAIX && typeof window.NAIX.suspect === 'function') {
              try {
                const suspect = !!window.NAIX.suspect(objForDetection || copyJsonText);
                if (suspect) {
                  const suspectEl = document.createElement('span');
                  suspectEl.className = 'naix-label';
                  suspectEl.textContent = t('naix_suspect_bracket');
                  headerEl.appendChild(suspectEl);
                }
              } catch { }
            }
            const modelEl = document.createElement('span');
            modelEl.className = 'json-header-line model';
            modelEl.textContent = `Model:${det.version}`;
            const typeEl = document.createElement('span');
            typeEl.className = 'json-header-line type';
            typeEl.textContent = `Type:${det.type}`;
            headerEl.appendChild(modelEl);
            headerEl.appendChild(typeEl);
            jsonBox.appendChild(headerEl);
            // 标记有头部，以便样式为内容增加顶部空白（避免遮挡）
            jsonBox.classList.add('has-header');
          }
        }
      } catch { }
      // 底部居中“显示全部/折叠”按钮
      const bottomEl = document.createElement('div');
      bottomEl.className = 'json-bottom';
      const showAllBtn = document.createElement('button');
      showAllBtn.className = 'btn ghost';
      showAllBtn.textContent = t('show_all');
      showAllBtn.addEventListener('click', () => {
        // 切换全局展开/折叠状态，并同步所有 JSON 框样式与按钮文案
        detailJsonExpanded = !detailJsonExpanded;
        detailJsonBoxes.forEach((box) => {
          // 短内容没有按钮，跳过折叠/展开切换
          if (box.btn && box.btn.style.display === 'none') return;
          if (detailJsonExpanded) {
            box.boxEl.classList.remove('collapsed');
            box.btn.textContent = t('collapse');
          } else {
            box.boxEl.classList.add('collapsed');
            box.btn.textContent = t('show_all');
          }
        });
        // 等待布局完成后，将视图定位到触发按钮所在的 JSON 框
        setTimeout(() => scrollJsonIntoView(jsonBox), 0);
      });
      bottomEl.appendChild(showAllBtn);
      jsonBox.appendChild(preEl);
      jsonBox.appendChild(bottomEl);
      card.appendChild(jsonBox);
      // 注册到全局列表，便于统一切换
      detailJsonBoxes.push({ boxEl: jsonBox, preEl, btn: showAllBtn, copyBtn });
      // 根据内容高度决定显示逻辑：短内容收回底部留白并隐藏按钮；长内容保持折叠固定高度
      function checkHeight() {
        try {
          const maxH = 320;
          const h = preEl.scrollHeight; // 实际内容高度
          const isShort = h <= maxH;
          if (isShort) {
            // 短内容：不需要“显示全部”，收回底部留白
            showAllBtn.style.display = 'none';
            bottomEl.style.display = 'none';
            jsonBox.classList.remove('collapsed');
            jsonBox.classList.add('short');
          } else {
            // 长内容：保留固定高度与按钮
            showAllBtn.style.display = '';
            bottomEl.style.display = '';
            jsonBox.classList.remove('short');
            jsonBox.classList.add('collapsed');
          }
        } catch { }
      }
      setTimeout(checkHeight, 0);
      detailImages.appendChild(card);
    });
    try {
      const wtype = String((data.work || {}).AI_type || '').toLowerCase();
      if ((wtype === 'nai' || wtype === 'nai_x') && window.NAIX && typeof window.NAIX.suspectWork === 'function') {
        const isSuspect = !!window.NAIX.suspectWork(data);
        const meta = document.getElementById('detailMeta');
        if (meta) {
          const oldFlag = meta.querySelector('.chip.naix-flag');
          if (oldFlag) oldFlag.remove();
        }
        if (isSuspect && meta) {
          const typeChip = meta.querySelector('.chip.nai');
          if (typeChip) {
            const flag = document.createElement('span');
            flag.className = 'chip naix-flag';
            flag.textContent = t('naix_suspect_paren');
            typeChip.after(flag);
          }
        }
      }
    } catch { }
    try {
      const wtype = String((data.work || {}).AI_type || '').toLowerCase();
      const meta = document.getElementById('detailMeta');
      if (meta) {
        const oldFlag = meta.querySelector('.chip.nonstandard-flag');
        if (oldFlag) oldFlag.remove();
      }
      if (wtype === 'comfyui' && meta && isNonStandardComfyuiWork(data)) {
        const typeChip = meta.querySelector('.chip.comfyui');
        if (typeChip) {
          const flag = document.createElement('span');
          flag.className = 'chip naix-flag nonstandard-flag';
          flag.textContent = t('non_standard_format_paren');
          flag.title = t('non_standard_format_tip');
          typeChip.after(flag);
        }
      }
    } catch { }
    // AI元数据模式：json / 指令，全局持久化（ON/OFF样式开关）
    if (aiModeToggle) {
      const getStoredMode = () => {
        const v = localStorage.getItem('aiMode') || 'json';
        return (v === 'instruction') ? 'instruction' : 'json';
      };
      const setStoredMode = (m) => { try { localStorage.setItem('aiMode', m); } catch { } };
      const applyModeToBoxes = (mode) => {
        detailJsonBoxes.forEach((box) => {
          try {
            if (!box || !box.boxEl || !box.preEl) return;
            if (!box.boxEl.classList.contains('nai')) return; // 仅 NAI 切换
            if (mode === 'instruction') {
              box.preEl.textContent = box.boxEl._instructionText || '';
              if (box.copyBtn) { box.copyBtn.textContent = t('copy_instruction'); box.copyBtn.dataset.mode = 'instruction'; }
            } else {
              box.preEl.innerHTML = box.boxEl._fullHtml || '';
              if (box.copyBtn) { box.copyBtn.textContent = t('copy_json'); box.copyBtn.dataset.mode = 'json'; }
            }
          } catch { }
        });
      };
      // 初始化：根据 localStorage 设置开关与内容
      let currentMode = getStoredMode();
      const toggleEl = aiModeToggle.querySelector('.ai-toggle');
      const setUi = (m) => { aiModeToggle.setAttribute('data-mode', m); };
      setUi(currentMode);
      applyModeToBoxes(currentMode);
      const onSelect = (m) => {
        if (m === currentMode) return;
        currentMode = m;
        setUi(currentMode);
        setStoredMode(currentMode);
        applyModeToBoxes(currentMode);
      };
      if (toggleEl) {
        const leftHit = aiModeToggle.querySelector('.hit-left');
        const rightHit = aiModeToggle.querySelector('.hit-right');
        const handleByPosition = (e) => {
          try {
            const rect = toggleEl.getBoundingClientRect();
            const x = (e.clientX ?? 0) - rect.left;
            const targetMode = x < rect.width / 2 ? 'json' : 'instruction';
            onSelect(targetMode);
          } catch {
            onSelect(currentMode === 'json' ? 'instruction' : 'json');
          }
        };
        // 点击整体，根据左右半区决定模式
        toggleEl.addEventListener('click', (e) => { handleByPosition(e); });
        // 显式左右命中区，避免圆点或文字影响点击
        if (leftHit) leftHit.addEventListener('click', (e) => { e.stopPropagation(); onSelect('json'); });
        if (rightHit) rightHit.addEventListener('click', (e) => { e.stopPropagation(); onSelect('instruction'); });
      }
    }
    // 将当前作品全部图片链接复制到剪贴板（适配 Chrome/Firefox/Safari，含移动端降级方案）
    downloadAllBtn.addEventListener('click', async () => {
      const urls = sortedDetailImages.map((img) => buildImageUrl(img)).filter(Boolean);
      if (!urls.length) {
        downloadAllBtn.textContent = t('no_links_to_copy');
        setTimeout(() => { downloadAllBtn.textContent = t('copy_all_image_links'); }, 1500);
        return;
      }
      const text = urls.join('\n');
      let copied = false;
      try {
        await navigator.clipboard.writeText(text);
        copied = true;
      } catch (e) {
        // Safari/iOS 等环境的降级复制方案
        try {
          const ta = document.createElement('textarea');
          ta.value = text;
          ta.style.position = 'fixed';
          ta.style.top = '-1000px';
          document.body.appendChild(ta);
          ta.focus();
          ta.select();
          copied = document.execCommand('copy');
          document.body.removeChild(ta);
          if (!copied) {
            alert(t('copy_failed_manual') + text);
          }
        } catch {
          alert(t('copy_failed_manual') + text);
        }
      }
      downloadAllBtn.textContent = copied ? t('copied_n_links', { n: urls.length }) : t('copy_failed_popup');
      setTimeout(() => { downloadAllBtn.textContent = t('copy_all_image_links'); }, 2000);
    });
    if (!stillThisDetail()) return;
    try {
      window.__AITAG_CURRENT_DETAIL__ = { workId, data };
      if (window.WorkBridge && typeof window.WorkBridge.save === 'function') {
        window.WorkBridge.save({
          workId,
          pageIndex: 0,
          galleryId: isAitagGallery() ? 'aitag-online' : currentGalleryId(),
          from: 'detail',
        });
      }
      window.dispatchEvent(new CustomEvent('aitag:detail-ready', {
        detail: {
          workId,
          data,
          source: isAitagGallery() ? AITAG_GALLERY_ID : currentGalleryId(),
        },
      }));
    } catch { }
    if (!stillThisDetail()) return;
    if (detailView) detailView.classList.remove('blocked-detail');
    detailView.classList.remove('hidden');
    restoreDetailScrollForWork(workId);
    closePreview();
  } catch (e) {
    if (loadGen !== detailLoadGen) return;
    if (detailView) detailView.classList.remove('blocked-detail');
    detailView.classList.remove('hidden');
	    detailTitle.textContent = e && e.code === 'not_found'
	      ? (CURRENT_LANG === 'zh' ? '作品未找到' : 'Work not found')
	      : t('loading_failed');
	    detailMeta.innerHTML = `<div class="dm-row">${escapeHtml((e && e.message) || t('err_network'))}</div>`;
	    if (detailImages) detailImages.innerHTML = '';
	    closePreview();
	  }
}

backBtn.addEventListener('click', (event) => {
  event.preventDefault();
  // Direct deep-link (/i/id) has no list entry under it — rebuild list URL.
  if (state.directDetail) {
    closeDetailView({ useHistoryBack: false });
    return;
  }
  closeDetailView({ useHistoryBack: true });
});

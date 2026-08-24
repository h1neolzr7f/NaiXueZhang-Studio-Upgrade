(function () {
  "use strict";

  function create(options) {
    const state = options.state;

    function buildWorksListUrl(page = state.page) {
      if (state.queueMode) {
        const url = new URL('/api/queue/works', options.apiBase);
        options.applyGalleryParams(url);
        url.searchParams.set('page', Math.max(1, Number(page) || 1));
        url.searchParams.set('page_size', state.pageSize);
        if (state.q) url.searchParams.set('q', state.q);
        return url;
      }
      if (state.favoritesMode) {
        const url = new URL('/api/favorites/works', options.apiBase);
        options.applyGalleryParams(url);
        url.searchParams.set('page', Math.max(1, Number(page) || 1));
        url.searchParams.set('page_size', state.pageSize);
        if (state.q) url.searchParams.set('q', state.q);
        return url;
      }
      if (options.isAitagGallery()) {
        const url = new URL('/api/nai/aitag/search', options.apiBase);
        const mode = options.getSortMode() || 'popular';
        url.searchParams.set('page', Math.max(1, Number(page) || 1));
        url.searchParams.set('page_size', state.pageSize);
        url.searchParams.set('sort', ['popular', 'recent', 'relevance'].includes(mode) ? mode : 'popular');
        url.searchParams.set('time_range', options.getTimeRange() || 'all');
        const filters = typeof options.getOnlineFilters === 'function' ? options.getOnlineFilters() : {};
        url.searchParams.set('nai_only', filters.naiOnly === false ? 'false' : 'true');
        url.searchParams.set('safe_only', filters.safeOnly ? 'true' : 'false');
        if (filters.creator) url.searchParams.set('creator', filters.creator);
        if (filters.tags) url.searchParams.set('tags', filters.tags);
        if (filters.model) url.searchParams.set('model', filters.model);
        if (filters.minImages) url.searchParams.set('min_images', String(filters.minImages));
        if (filters.maxImages) url.searchParams.set('max_images', String(filters.maxImages));
        if (state.q) url.searchParams.set('q', state.q);
        if (state.prompt) url.searchParams.set('prompt', state.prompt);
        return url;
      }
      const mode = options.getSortMode() || 'new';
      const isRank = mode === 'monthly';
      let url;
      if (isRank) {
        const trVal = options.getTimeRange() || 'current';
        if (trVal === 'current') url = new URL('/api/rank/monthly/real', options.apiBase);
        else if (trVal === 'older' || trVal.startsWith('m')) url = new URL('/api/rank/monthly/fixed', options.apiBase);
        else url = new URL('/api/rank/monthly', options.apiBase);
      } else {
        url = new URL('/api/ai_works_search', options.apiBase);
      }
      url.searchParams.set('page', Math.max(1, Number(page) || 1));
      url.searchParams.set('page_size', state.pageSize);
      options.applyGalleryParams(url);
      if (Number(page) > 1 || state.q || state.prompt || state.listMode === 'infinite') {
        url.searchParams.set('skip_total', '1');
      }
      if (state.q) url.searchParams.set('q', state.q);
      if (state.prompt) url.searchParams.set('prompt', state.prompt);
      const tr = options.getTimeRange() || (isRank ? 'current' : 'all');
      if (isRank) {
        const path = url.pathname || '';
        if (!path.includes('/real')) {
          if (path.includes('/fixed')) {
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
        }
      } else {
        url.searchParams.set('sort', mode || 'new');
        url.searchParams.set('time_range', tr || 'all');
      }
      return url;
    }

    async function fetchWorksListPage(page = state.page) {
      const url = buildWorksListUrl(page);
      const res = await window.ApiClient.raw(url);
      let data = {};
      try {
        data = await res.json();
      } catch {
        data = { page, page_size: state.pageSize, total: 0, items: [] };
      }
      if (data && data.error === 'search_failed') {
        const err = new Error(options.currentLanguage() === 'zh'
          ? (data.message_zh || data.message || options.translate('err_search_failed'))
          : (data.message_en || data.message || options.translate('err_search_failed')));
        err.code = 'search_failed';
        throw err;
      }
      if (!res.ok) {
        const err = new Error((data && (data.message_zh || data.message_en || data.error)) || `HTTP ${res.status}`);
        err.code = data && data.error;
        throw err;
      }
      return {
        items: (Array.isArray(data.items) ? data.items : []).map((item) => options.isAitagGallery() ? options.adaptAitagWork(item) : item),
        total: typeof data.total === 'number' ? data.total : 0,
        page: Number(data.page) || Number(page) || 1,
        page_size: Number(data.page_size) || state.pageSize,
      };
    }

    function mountPublicApi() {
      window.AitagGallery = {
        getListContext() {
          const loaded = options.visibleWorks(state.items);
          const currentPage = Math.max(1, Number(state.page) || 1);
          return {
            q: state.q || '', prompt: state.prompt || '', page: currentPage,
            total: Number(state.total) || 0, listMode: state.listMode || 'infinite',
            pageSize: state.pageSize || 0, sort: options.getSortMode() || 'new',
            timeRange: options.getTimeRange() || 'all', loadedCount: loaded.length,
            currentPageCount: loaded.filter((w) => options.getWorkListPage(w) === currentPage).length,
            isListView: !options.isDetailView(), isDetailView: options.isDetailView(),
          };
        },
        getLoadedWorks: () => options.visibleWorks(state.items),
        getCurrentPageWorks() {
          const currentPage = Math.max(1, Number(state.page) || 1);
          const items = options.visibleWorks(state.items);
          return state.listMode === 'pagination' ? items : items.filter((w) => options.getWorkListPage(w) === currentPage);
        },
        isDetailView: options.isDetailView,
        isListView: () => !options.isDetailView(),
        buildWorksListUrl,
        fetchWorksListPage,
      };
    }

    async function checkOnboarding() {
      const banner = document.getElementById('setupBanner');
      const text = document.getElementById('setupBannerText');
      const dismiss = document.getElementById('setupBannerDismiss');
      if (!banner || !text || !window.ApiClient || options.isAitagGallery()) return;
      if (dismiss) dismiss.addEventListener('click', () => banner.classList.add('hidden'));
      try {
        const report = await window.ApiClient.request('/api/crawler/pixiv/report');
        const rep = report.report || {};
        if (rep.status && rep.status !== 'never_run' && Number(rep.works_accepted || 0) > 0) return;
        let total = 0;
        for (const gid of ['site', 'codex', 'qqgroup']) {
          const response = await window.ApiClient.request(`/api/ai_works_search?gallery_id=${gid}&page_size=1`);
          total += Number(response.total || 0);
        }
        if (total > 0) return;
        text.textContent = '欢迎使用 Nai学长工作室：先建初始图库——去「采集页」无账号开爬，或把本地图拖进「自选库」。只有通过 NovelAI 元数据验证的图片才会入库；图库有数据后，Studio 再创作、换角与 Pixiv 发布即可使用。';
        if (!options.isAitagGallery()) banner.classList.remove('hidden');
      } catch (_error) { /* banner stays hidden */ }
    }

    return {
      buildWorksListUrl,
      fetchWorksListPage,
      mount() {
        mountPublicApi();
        checkOnboarding();
      },
    };
  }

  window.GalleryListRuntime = { create };
})();

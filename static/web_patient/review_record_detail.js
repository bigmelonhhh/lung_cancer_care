(() => {
  const LOAD_MORE_THRESHOLD = 600;

  const state = {
    categoryCode: '',
    title: '',
    patientId: '',
    reportMonth: '',
    hasMore: false,
    cursorMonth: '',
    cursorOffset: 0,
    batchSize: 6,
    groups: [],
    heights: [],
    offsets: [],
    totalHeight: 0,
    isLoading: false,
    abortController: null,
    firstRenderReported: false,
    startedAt: 0,
    performanceObserver: null,
    viewer: {
      isOpen: false,
      images: [],
      index: 0,
      touchStartX: 0,
      touchStartY: 0,
    },
  };

  const els = {};

  function $(id) {
    return document.getElementById(id);
  }

  function parseJsonScript(id) {
    const node = $(id);
    if (!node) return [];
    try {
      const parsed = JSON.parse(node.textContent || '[]');
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      console.error('review_record_detail parse initial groups failed:', error);
      return [];
    }
  }

  function initDom() {
    els.scroll = $('rrd-scroll');
    els.monthPicker = $('rrd-month-picker');
    els.monthDisplay = $('rrd-month-display');
    els.virtualContainer = $('rrd-virtual-container');
    els.virtualInner = $('rrd-virtual-inner');
    els.empty = $('rrd-empty');
    els.spinner = $('loading-spinner');
    els.noMore = $('no-more-data');
    els.toast = $('rrd-toast');
    els.viewer = $('rrd-viewer');
    els.viewerImage = $('rrd-viewer-image');
    els.viewerLoading = $('rrd-viewer-loading');
    els.viewerClose = $('rrd-viewer-close');
    els.viewerPrev = $('rrd-viewer-prev');
    els.viewerNext = $('rrd-viewer-next');
    els.viewerIndex = $('rrd-viewer-index');

    if (!els.scroll) return;

    state.patientId = els.scroll.getAttribute('data-patient-id') || '';
    state.categoryCode = els.scroll.getAttribute('data-category-code') || '';
    state.title = els.scroll.getAttribute('data-title') || '';
    state.reportMonth = els.monthPicker ? els.monthPicker.value : '';
    state.hasMore = (els.scroll.getAttribute('data-has-more') || '') === 'true';
    state.cursorMonth = els.scroll.getAttribute('data-next-cursor-month') || '';
    state.cursorOffset = parseInt(els.scroll.getAttribute('data-next-cursor-offset') || '0', 10) || 0;
    state.batchSize = parseInt(els.scroll.getAttribute('data-batch-size') || '6', 10) || 6;
    state.groups = parseJsonScript('rrd-initial-groups');
  }

  function showToast(message, type = 'info') {
    if (!els.toast) return;
    const colors = {
      info: 'bg-slate-900 text-white',
      success: 'bg-emerald-600 text-white',
      error: 'bg-rose-600 text-white',
    };
    const div = document.createElement('div');
    div.className = `${colors[type] || colors.info} rounded-2xl px-4 py-3 shadow-lg text-base text-center pointer-events-auto`;
    div.textContent = message;
    els.toast.appendChild(div);
    setTimeout(() => {
      div.classList.add('opacity-0', '-translate-y-2', 'transition');
      div.addEventListener('transitionend', () => div.remove());
    }, 2200);
  }

  function thumbUrl(url) {
    const raw = (url || '').trim();
    if (!raw) return '';
    const sep = raw.includes('?') ? '&' : '?';
    return `${raw}${sep}x-oss-process=image/resize,m_fill,w_200,h_200`;
  }

  function placeholderDataUrl() {
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(
      '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200"><rect width="100%" height="100%" fill="#f1f5f9"/><path d="M70 120l25-30 25 30H70zm60-10l20 25H50l30-40 20 25 10-10z" fill="#cbd5e1"/><circle cx="80" cy="75" r="10" fill="#cbd5e1"/></svg>'
    );
  }

  function setLoading(loading) {
    state.isLoading = loading;
    if (els.spinner) els.spinner.classList.toggle('hidden', !loading);
  }

  function setEmptyVisible(visible) {
    if (!els.empty) return;
    els.empty.classList.toggle('hidden', !visible);
  }

  function setNoMoreVisible(visible) {
    if (!els.noMore) return;
    els.noMore.classList.toggle('hidden', !visible);
  }

  function syncListStates() {
    const hasGroups = state.groups.length > 0;
    setEmptyVisible(!hasGroups && !state.isLoading);
    setNoMoreVisible(hasGroups && !state.hasMore && !state.isLoading);
  }

  function isNearBottom(threshold = LOAD_MORE_THRESHOLD) {
    if (!els.scroll) return false;
    return els.scroll.scrollHeight - els.scroll.scrollTop - els.scroll.clientHeight < threshold;
  }

  function scrollToFooter() {
    if (!els.scroll) return;
    els.scroll.scrollTop = els.scroll.scrollHeight;
  }

  function computeItemHeight(group) {
    const images = Array.isArray(group.image_urls) ? group.image_urls : [];
    const rows = Math.max(1, Math.ceil(images.length / 3));
    const gap = 8;
    const containerWidth = els.scroll ? els.scroll.clientWidth : 375;
    const gridWidth = Math.max(0, containerWidth - 32);
    const thumb = Math.max(56, Math.floor((gridWidth - gap * 2) / 3));
    const gridHeight = rows * thumb + (rows - 1) * gap;
    return 16 + 24 + 12 + gridHeight + 16;
  }

  function recomputeLayout(fromIndex = 0) {
    const start = Math.max(0, fromIndex);
    for (let i = start; i < state.groups.length; i += 1) {
      state.heights[i] = computeItemHeight(state.groups[i]);
      state.offsets[i] = i === 0 ? 0 : state.offsets[i - 1] + state.heights[i - 1];
    }
    const lastIndex = state.groups.length - 1;
    state.totalHeight = lastIndex >= 0 ? state.offsets[lastIndex] + state.heights[lastIndex] : 0;
    if (els.virtualContainer) {
      els.virtualContainer.style.height = `${state.totalHeight}px`;
    }
  }

  function findIndexByScrollTop(scrollTop) {
    let low = 0;
    let high = state.groups.length - 1;
    let ans = 0;
    while (low <= high) {
      const mid = (low + high) >> 1;
      const start = state.offsets[mid] || 0;
      const end = start + (state.heights[mid] || 0);
      if (scrollTop >= end) {
        low = mid + 1;
      } else if (scrollTop < start) {
        high = mid - 1;
      } else {
        ans = mid;
        break;
      }
    }
    if (low > high) ans = Math.max(0, Math.min(low, state.groups.length - 1));
    return ans;
  }

  function buildCardHtml(group) {
    const urls = Array.isArray(group.image_urls) ? group.image_urls : [];
    const date = group.report_date || '';
    const thumbs = urls.map((url, idx) => {
      const t = thumbUrl(url);
      const safeFull = (url || '').replace(/'/g, '&#39;');
      const safeThumb = (t || '').replace(/'/g, '&#39;');
      return `
        <button type="button" class="rrd-thumb rrd-square bg-slate-100 rounded-lg overflow-hidden border border-slate-200" data-full-url="${safeFull}" data-idx="${idx}">
          <img loading="lazy" src="${safeThumb}" data-fallback-src="${safeFull}" class="object-cover" alt="缩略图">
        </button>
      `;
    }).join('');

    return `
      <div class="bg-white rounded-xl shadow-sm p-4 mt-3 ml-3 mr-3">
        <div class="flex items-center gap-3 text-sm mb-3">
          <span class="font-bold text-slate-800 text-base">${date}</span>
        </div>
        <div class="grid grid-cols-3 gap-2">
          ${thumbs}
        </div>
      </div>
    `;
  }

  function renderVirtual() {
    if (!els.scroll || !els.virtualInner) return;
    const n = state.groups.length;
    if (n === 0) {
      els.virtualInner.innerHTML = '';
      return;
    }

    const scrollTop = els.scroll.scrollTop;
    const viewHeight = els.scroll.clientHeight;
    const overscan = 6;
    const startIndex = findIndexByScrollTop(Math.max(0, scrollTop - 200));
    const endIndex = findIndexByScrollTop(scrollTop + viewHeight + 400);
    const from = Math.max(0, startIndex - overscan);
    const to = Math.min(n - 1, endIndex + overscan);
    const offsetY = state.offsets[from] || 0;

    const parts = [];
    for (let i = from; i <= to; i += 1) {
      parts.push(`<div data-group-index="${i}">${buildCardHtml(state.groups[i])}</div>`);
    }
    els.virtualInner.style.transform = `translateY(${offsetY}px)`;
    els.virtualInner.innerHTML = parts.join('');

    els.virtualInner.querySelectorAll('img').forEach(img => {
      img.addEventListener('error', () => {
        const fallbackSrc = img.getAttribute('data-fallback-src') || '';
        if (img.src && img.src.startsWith('data:image')) return;
        if (fallbackSrc && img.src !== fallbackSrc) {
          img.src = fallbackSrc;
          return;
        }
        console.error('review_record_detail thumbnail failed:', fallbackSrc || img.src);
        img.src = placeholderDataUrl();
      }, { once: true });
    });

    els.virtualInner.querySelectorAll('.rrd-thumb').forEach(btn => {
      btn.addEventListener('click', () => {
        const wrapper = btn.closest('[data-group-index]');
        const groupIndex = parseInt((wrapper && wrapper.getAttribute('data-group-index')) || '0', 10);
        const imgIndex = parseInt(btn.getAttribute('data-idx') || '0', 10);
        const group = state.groups[groupIndex];
        const urls = group && Array.isArray(group.image_urls) ? group.image_urls : [];
        openViewer(urls, imgIndex);
      });
    });
  }

  function openViewer(urls, startIndex = 0) {
    if (!els.viewer) return;
    state.viewer.images = Array.isArray(urls) ? urls.slice() : [];
    state.viewer.index = Math.max(0, Math.min(startIndex, state.viewer.images.length - 1));
    state.viewer.isOpen = true;
    els.viewer.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    renderViewerImage();
  }

  function closeViewer() {
    if (!els.viewer) return;
    state.viewer.isOpen = false;
    els.viewer.classList.add('hidden');
    document.body.style.overflow = '';
    if (els.viewerImage) els.viewerImage.src = '';
  }

  function renderViewerImage() {
    const urls = state.viewer.images;
    const idx = state.viewer.index;
    if (!els.viewerLoading || !els.viewerImage || !els.viewerIndex) return;

    if (!urls.length) {
      els.viewerLoading.textContent = '暂无图片';
      els.viewerLoading.classList.remove('hidden');
      els.viewerImage.classList.add('hidden');
      els.viewerIndex.textContent = '';
      return;
    }

    els.viewerIndex.textContent = `${idx + 1} / ${urls.length}`;
    els.viewerLoading.textContent = '加载中...';
    els.viewerLoading.classList.remove('hidden');
    els.viewerImage.classList.add('hidden');

    const url = urls[idx];
    const img = new Image();
    img.onload = () => {
      if (!state.viewer.isOpen) return;
      els.viewerImage.src = url;
      els.viewerImage.classList.remove('hidden');
      els.viewerLoading.classList.add('hidden');
    };
    img.onerror = () => {
      if (!state.viewer.isOpen) return;
      console.error('review_record_detail original image failed:', url);
      els.viewerLoading.textContent = '图片加载失败，点击重试';
    };
    img.src = url;
  }

  function prevImage() {
    if (!state.viewer.images.length) return;
    state.viewer.index = (state.viewer.index - 1 + state.viewer.images.length) % state.viewer.images.length;
    renderViewerImage();
  }

  function nextImage() {
    if (!state.viewer.images.length) return;
    state.viewer.index = (state.viewer.index + 1) % state.viewer.images.length;
    renderViewerImage();
  }

  function bindViewerEvents() {
    if (!els.viewer) return;
    if (els.viewerClose) els.viewerClose.addEventListener('click', closeViewer);
    if (els.viewerPrev) els.viewerPrev.addEventListener('click', prevImage);
    if (els.viewerNext) els.viewerNext.addEventListener('click', nextImage);

    els.viewer.addEventListener('click', e => {
      const target = e.target;
      if (target === els.viewer) closeViewer();
      if (target && target.classList && target.classList.contains('bg-black/90')) closeViewer();
    });

    if (els.viewerLoading) {
      els.viewerLoading.addEventListener('click', () => {
        renderViewerImage();
      });
    }

    els.viewer.addEventListener('touchstart', e => {
      if (!e.touches || e.touches.length !== 1) return;
      state.viewer.touchStartX = e.touches[0].clientX;
      state.viewer.touchStartY = e.touches[0].clientY;
    }, { passive: true });

    els.viewer.addEventListener('touchend', e => {
      if (!e.changedTouches || e.changedTouches.length !== 1) return;
      const dx = e.changedTouches[0].clientX - state.viewer.touchStartX;
      const dy = e.changedTouches[0].clientY - state.viewer.touchStartY;
      if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy)) return;
      if (dx > 0) prevImage();
      else nextImage();
    }, { passive: true });
  }

  function buildApiUrl() {
    const apiUrl = els.scroll ? (els.scroll.getAttribute('data-api-url') || '') : '';
    const url = new URL(apiUrl || window.location.pathname, window.location.origin);
    if (state.patientId) url.searchParams.set('patient_id', state.patientId);
    url.searchParams.set('category_code', state.categoryCode);
    url.searchParams.set('month', state.reportMonth);
    url.searchParams.set('cursor_month', state.cursorMonth || state.reportMonth);
    url.searchParams.set('cursor_offset', String(state.cursorOffset));
    url.searchParams.set('limit', String(state.batchSize));
    return url.toString();
  }

  function cancelInFlight() {
    if (state.abortController) {
      state.abortController.abort();
      state.abortController = null;
    }
  }

  function initPerformanceObserver() {
    state.startedAt = typeof performance !== 'undefined' && performance.now ? performance.now() : 0;
    if (!window.PerformanceObserver || !PerformanceObserver.supportedEntryTypes) return;
    if (!PerformanceObserver.supportedEntryTypes.includes('largest-contentful-paint')) return;
    try {
      state.performanceObserver = new PerformanceObserver(() => {});
      state.performanceObserver.observe({ type: 'largest-contentful-paint', buffered: true });
    } catch (error) {}
  }

  function reportFirstRender() {
    if (state.firstRenderReported) return;
    state.firstRenderReported = true;
    const elapsed = typeof performance !== 'undefined' && performance.now ? Math.round(performance.now() - state.startedAt) : -1;

    let lcp = null;
    if (state.performanceObserver) {
      try {
        const entries = state.performanceObserver.takeRecords();
        const last = entries && entries.length ? entries[entries.length - 1] : null;
        if (last && typeof last.startTime === 'number') lcp = Math.round(last.startTime);
      } catch (error) {}
      try {
        state.performanceObserver.disconnect();
      } catch (error) {}
      state.performanceObserver = null;
    }

    if (lcp !== null) {
      console.log('review_record_detail first_render_ms', elapsed, 'lcp_ms', lcp);
      return;
    }
    console.log('review_record_detail first_render_ms', elapsed);
  }

  function loadMore() {
    if (state.isLoading || !state.hasMore) return;
    if (!state.categoryCode) {
      showToast('缺少复查分类参数', 'error');
      return;
    }

    const prevHasMore = state.hasMore;
    const shouldStickFooter = isNearBottom();
    cancelInFlight();
    state.abortController = new AbortController();
    state.isLoading = true;
    setLoading(true);
    setNoMoreVisible(false);
    setEmptyVisible(false);
    if (shouldStickFooter) {
      window.requestAnimationFrame(scrollToFooter);
    }

    const preserveCursorMonth = state.cursorMonth;
    const preserveCursorOffset = state.cursorOffset;
    const url = buildApiUrl();

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      signal: state.abortController.signal,
    })
      .then(res => res.json().then(data => ({ ok: res.ok, data })))
      .then(({ ok, data }) => {
        if (!ok || !data || data.success === false) {
          throw new Error((data && data.message) || '数据加载失败，请重试');
        }

        const list = Array.isArray(data.list) ? data.list : [];
        const startIndex = state.groups.length;
        state.groups = state.groups.concat(list);
        state.hasMore = Boolean(data.has_more);
        state.cursorMonth = data.next_cursor_month || '';
        state.cursorOffset = parseInt(data.next_cursor_offset ?? 0, 10) || 0;
        if (typeof data.batch_size !== 'undefined') {
          state.batchSize = parseInt(data.batch_size, 10) || state.batchSize;
        }

        recomputeLayout(startIndex);
        renderVirtual();
        syncListStates();
        if (prevHasMore && !state.hasMore) {
          window.requestAnimationFrame(scrollToFooter);
        }
      })
      .catch(err => {
        if (err && err.name === 'AbortError') return;
        state.cursorMonth = preserveCursorMonth;
        state.cursorOffset = preserveCursorOffset;
        showToast(err && err.message ? err.message : '数据加载失败，请重试', 'error');
      })
      .finally(() => {
        setLoading(false);
        state.isLoading = false;
        state.abortController = null;
        syncListStates();
        if (shouldStickFooter && state.hasMore) {
          window.requestAnimationFrame(scrollToFooter);
        }
        window.requestAnimationFrame(ensureScrollableContent);
      });
  }

  function handleScroll() {
    renderVirtual();
    if (state.isLoading || !state.hasMore) return;
    const bottom = els.scroll.scrollTop + els.scroll.clientHeight;
    if (state.totalHeight - bottom < LOAD_MORE_THRESHOLD) {
      loadMore();
    }
  }

  function ensureScrollableContent() {
    if (!els.scroll || state.isLoading || !state.hasMore) return;
    if (state.totalHeight <= els.scroll.clientHeight + 20) {
      loadMore();
    }
  }

  function handleMonthChange(value) {
    if (!value) return;
    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set('month', value);
    window.location.replace(nextUrl.toString());
  }

  function bindEvents() {
    if (els.scroll) {
      els.scroll.addEventListener('scroll', () => {
        window.requestAnimationFrame(handleScroll);
      }, { passive: true });
    }

    if (els.monthPicker) {
      els.monthPicker.addEventListener('change', e => {
        const value = e.target.value;
        if (els.monthDisplay && value) {
          els.monthDisplay.textContent = value;
        }
        handleMonthChange(value);
      });
    }

    window.addEventListener('resize', () => {
      window.requestAnimationFrame(() => {
        recomputeLayout(0);
        renderVirtual();
        ensureScrollableContent();
      });
    });
  }

  function init() {
    initDom();
    if (!els.scroll) return;
    bindEvents();
    bindViewerEvents();
    initPerformanceObserver();
    recomputeLayout(0);
    renderVirtual();
    syncListStates();
    window.requestAnimationFrame(() => {
      reportFirstRender();
      ensureScrollableContent();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

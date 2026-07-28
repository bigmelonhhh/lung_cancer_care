(function () {
  'use strict';

  if (window.__PATIENT_HOME_BOOTED__) {
    return;
  }
  window.__PATIENT_HOME_BOOTED__ = true;

  function readPatientHomeConfig() {
    const configElement = document.getElementById('patient-home-config');
    if (!configElement) {
      return {};
    }
    try {
      return JSON.parse(configElement.textContent || '{}');
    } catch (error) {
      console.error('Invalid patient home config:', error);
      return {};
    }
  }

  const config = readPatientHomeConfig();
  const IS_MEMBER = Boolean(config.isMember);
  const BUY_URL = config.buyUrl || '';
  const PATIENT_ID = config.patientId || '';
  const MENU_URLS = config.menuUrl || {};
  const URLS = config.urls || {};
  const CSRF_TOKEN = config.csrfToken || '';
  const UNREAD_REFRESH_INTERVAL_MS = Number(config.unreadRefreshIntervalMs || 15000);
  const HOME_SUCCESS_PARAMS = [
    'temperature',
    'bp_hr',
    'spo2',
    'weight',
    'breath_val',
    'sputum_val',
    'pain_val',
    'step',
    'medication_taken',
    'checkup_completed',
    'followup'
  ];
  const HOME_PLAN_REFRESH_MARKER_KEY = 'home_plan_refresh_marker';
  const HOME_PLAN_REFRESH_MARKER_TTL_MS = 10 * 60 * 1000;
  const HOME_PLAN_REFRESH_THROTTLE_MS = 1200;
  const HOME_COMPLETED_FALLBACK_SUBTITLES = {
    temperature: '今日已记录',
    bp_hr: '今日已记录',
    spo2: '今日已记录',
    weight: '今日已记录',
    medication: '今日已服药',
    checkup: '已完成复查任务',
    followup: '已完成随访任务'
  };

  let UNREAD_CHAT_COUNT = parseInt(config.unreadChatCount, 10) || 0;
  let MEMBER_ONLY_REDIRECT_URL = BUY_URL;
  let LAST_UNREAD_FETCH_AT = Date.now();
  let LAST_PLAN_REFRESH_AT = 0;
  let PLAN_REFRESH_IN_FLIGHT = null;
  let HOME_PAGE_WAS_HIDDEN = false;
  let HOME_PERF_REPORTED = false;

  function getHomePlanMarkerDateKey() {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');
    return year + '-' + month + '-' + day;
  }

  function readHomePlanRefreshMarker() {
    try {
      const raw = localStorage.getItem(HOME_PLAN_REFRESH_MARKER_KEY);
      if (!raw) {
        return null;
      }

      const marker = JSON.parse(raw);
      if (!marker || marker.date !== getHomePlanMarkerDateKey() || Number(marker.expiresAt || 0) <= Date.now()) {
        localStorage.removeItem(HOME_PLAN_REFRESH_MARKER_KEY);
        return null;
      }

      const completedTypes = Array.isArray(marker.completedTypes)
        ? marker.completedTypes.filter(function (type) {
          return typeof type === 'string' && type.length > 0;
        })
        : [];

      if (completedTypes.length === 0) {
        localStorage.removeItem(HOME_PLAN_REFRESH_MARKER_KEY);
        return null;
      }

      return {
        completedTypes: completedTypes,
        date: marker.date,
        expiresAt: marker.expiresAt
      };
    } catch (error) {
      localStorage.removeItem(HOME_PLAN_REFRESH_MARKER_KEY);
      return null;
    }
  }

  function writeHomePlanRefreshMarker(type) {
    if (!type) {
      return;
    }

    try {
      const marker = readHomePlanRefreshMarker() || {};
      const completedTypes = Array.isArray(marker.completedTypes) ? marker.completedTypes.slice() : [];
      if (!completedTypes.includes(type)) {
        completedTypes.push(type);
      }
      localStorage.setItem(HOME_PLAN_REFRESH_MARKER_KEY, JSON.stringify({
        completedTypes: completedTypes,
        date: getHomePlanMarkerDateKey(),
        expiresAt: Date.now() + HOME_PLAN_REFRESH_MARKER_TTL_MS
      }));
    } catch (error) {}
  }

  function showMemberOnlyModal(message, redirectUrl) {
    const modal = document.getElementById('member-only-modal');
    const messageEl = document.getElementById('member-only-message');
    if (!modal || !messageEl) {
      alert(message || '该功能为会员专属，请先开通会员');
      if (redirectUrl) {
        window.location.href = redirectUrl;
      }
      return;
    }
    MEMBER_ONLY_REDIRECT_URL = redirectUrl || BUY_URL;
    messageEl.textContent = message || '该功能为会员专属，请先开通会员';
    modal.classList.remove('hidden');
    modal.style.display = 'block';
    modal.setAttribute('aria-hidden', 'false');
  }

  function closeMemberOnlyModal() {
    const modal = document.getElementById('member-only-modal');
    if (!modal) {
      return;
    }
    modal.classList.add('hidden');
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden', 'true');
  }

  function confirmMemberOnlyModal() {
    const targetUrl = MEMBER_ONLY_REDIRECT_URL || BUY_URL;
    closeMemberOnlyModal();
    if (targetUrl) {
      window.location.href = targetUrl;
    }
  }

  function handleMemberOnlyNavigation(event) {
    if (IS_MEMBER) {
      return true;
    }
    if (event) {
      event.preventDefault();
    }
    showMemberOnlyModal('该功能为会员专属，请先开通会员', BUY_URL);
    return false;
  }

  function openMedicationModal() {
    const modal = document.getElementById('medication-modal');
    if (!modal) {
      return;
    }
    modal.classList.remove('hidden');
    modal.style.display = 'block';
  }

  function closeMedicationModal() {
    const modal = document.getElementById('medication-modal');
    if (!modal) {
      return;
    }
    modal.classList.add('hidden');
    modal.style.display = 'none';
  }

  function submitMedication() {
    if (!PATIENT_ID) {
      alert('未找到患者信息');
      return;
    }
    if (!URLS.submitMedication) {
      alert('提交地址未配置');
      return;
    }

    fetch(URLS.submitMedication, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'X-CSRFToken': CSRF_TOKEN
      },
      body: new URLSearchParams({
        patient_id: PATIENT_ID
      })
    })
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (data.success) {
          if (URLS.patientHome) {
            writeHomePlanRefreshMarker('medication');
            window.location.replace(URLS.patientHome + '?medication_taken=true');
            return;
          }
          window.location.reload();
          return;
        }
        alert(data.message || '提交失败');
      })
      .catch(function (error) {
        console.error('Error:', error);
        alert('提交出错，请稍后重试');
      });
  }

  function buildTaskActionUrl(type, specificUrl) {
    const fallbackUrl = MENU_URLS[type];
    const urlBase = specificUrl || fallbackUrl;
    if (!urlBase) {
      console.error('未找到对应类型的跳转链接:', type);
      return '';
    }

    const taskUrl = new URL(urlBase, window.location.href);
    taskUrl.searchParams.set('source', 'home');
    taskUrl.searchParams.set('patient_id', PATIENT_ID);
    if (taskUrl.origin === window.location.origin) {
      return taskUrl.pathname + taskUrl.search + taskUrl.hash;
    }
    return taskUrl.toString();
  }

  function handleHomeTaskAction(event) {
    const action = event.target.closest('[data-home-task-action]');
    if (!action || action.dataset.homeTaskAction !== 'medication') {
      return;
    }
    event.preventDefault();
    if (!IS_MEMBER) {
      showMemberOnlyModal('该功能为会员专属，请先开通会员', BUY_URL);
      return;
    }
    openMedicationModal();
  }

  const PLAN_ACTION_CONTROL_CLASS = 'bg-white border border-slate-200 text-slate-600 text-sm font-bold px-3 py-1.5 rounded-full shadow-sm hover:border-blue-400 hover:text-blue-600 active:bg-blue-50 transition whitespace-nowrap';

  function setPlanActionState(type, status, plan) {
    const actionEl = document.getElementById('plan-action-' + type);
    if (!actionEl) {
      return;
    }

    const planData = plan || {};
    if (typeof planData.action_text === 'string' && planData.action_text.length > 0) {
      actionEl.dataset.actionText = planData.action_text;
    }
    if (typeof planData.url === 'string') {
      actionEl.dataset.planUrl = planData.url;
    }

    if (status === 'completed') {
      actionEl.innerHTML = '';
      return;
    }

    const actionText = actionEl.dataset.actionText || '去完成';
    const specificUrl = actionEl.dataset.planUrl || '';

    actionEl.innerHTML = '';
    if (type === 'medication') {
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.homeTaskAction = 'medication';
      button.className = PLAN_ACTION_CONTROL_CLASS;
      button.textContent = actionText;
      actionEl.appendChild(button);
      return;
    }

    const actionUrl = buildTaskActionUrl(type, specificUrl);
    if (!actionUrl) {
      return;
    }
    const link = document.createElement('a');
    link.href = actionUrl;
    link.className = PLAN_ACTION_CONTROL_CLASS;
    link.textContent = actionText;
    actionEl.appendChild(link);
  }

  function setPlanCardState(type, status, subtitle, plan) {
    const subtitleEl = document.getElementById('plan-subtitle-' + type);
    if (subtitleEl && typeof subtitle === 'string' && subtitle.length > 0) {
      subtitleEl.textContent = subtitle;
    }
    setPlanActionState(type, status, plan || {});
  }

  function markFollowupCompletedFallback() {
    setPlanCardState('followup', 'completed', '已完成随访任务');
  }

  function applyRecentCompletedFallbacks(plans) {
    const marker = readHomePlanRefreshMarker();
    if (!marker) {
      return;
    }

    const planMap = plans || {};
    marker.completedTypes.forEach(function (type) {
      const plan = planMap[type];
      if (plan) {
        return;
      }

      const subtitle = HOME_COMPLETED_FALLBACK_SUBTITLES[type];
      if (subtitle) {
        setPlanCardState(type, 'completed', subtitle);
      }
    });
  }

  function refreshMetricData(options) {
    if (!IS_MEMBER || !URLS.queryLastMetric) {
      return Promise.resolve(null);
    }

    const refreshUrl = new URL(URLS.queryLastMetric, window.location.origin);
    refreshUrl.searchParams.set('_ts', String(Date.now()));

    return fetch(refreshUrl.toString(), { cache: 'no-store' })
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (data.success) {
          updateMetricDisplay(data.plans || {}, options || {});
        }
        return data;
      })
      .catch(function (error) {
        console.error('Error refreshing metrics:', error);
        return null;
      });
  }

  function updateMetricDisplay(plans, options) {
    let hasFollowupPlan = false;
    Object.entries(plans || {}).forEach(function (entry) {
      const type = entry[0];
      const plan = entry[1];
      if (type === 'followup') {
        hasFollowupPlan = true;
      }
      setPlanCardState(type, plan.status, plan.subtitle, plan);
    });

    if (options && options.followupSubmitted && !hasFollowupPlan) {
      markFollowupCompletedFallback();
    }
    applyRecentCompletedFallbacks(plans);
  }

  function requestPlanRefresh(reason, options) {
    options = options || {};
    const refreshOptions = options;
    const now = Date.now();
    if (PLAN_REFRESH_IN_FLIGHT) {
      return PLAN_REFRESH_IN_FLIGHT;
    }
    if (options.force !== true && now - LAST_PLAN_REFRESH_AT < HOME_PLAN_REFRESH_THROTTLE_MS) {
      applyRecentCompletedFallbacks({});
      return Promise.resolve(null);
    }
    PLAN_REFRESH_IN_FLIGHT = refreshMetricData(refreshOptions).then(function (data) {
      LAST_PLAN_REFRESH_AT = Date.now();
      applyRecentCompletedFallbacks((data && data.plans) || {});
      return data;
    }).finally(function () {
      PLAN_REFRESH_IN_FLIGHT = null;
    });
    return PLAN_REFRESH_IN_FLIGHT;
  }

  function hasHomeSuccessParam() {
    const searchParams = new URLSearchParams(window.location.search);
    return HOME_SUCCESS_PARAMS.some(function (param) {
      return searchParams.has(param);
    });
  }

  function isHistoryRestore(event) {
    if (event && event.persisted === true) {
      return true;
    }

    if (!window.performance) {
      return false;
    }

    if (typeof window.performance.getEntriesByType === 'function') {
      const navEntry = (window.performance.getEntriesByType('navigation') || [])[0];
      if (navEntry && navEntry.type === 'back_forward') {
        return true;
      }
    }

    const nav = window.performance.navigation;
    return Boolean(nav && nav.type === 2);
  }

  async function consumeRefreshMarkersAndSync() {
    let shouldRefresh = false;
    let followupSubmitted = false;

    try {
      const refreshFlag = localStorage.getItem('refresh_flag');
      if (refreshFlag === 'true') {
        shouldRefresh = true;
      }

      const metricRaw = localStorage.getItem('metric_data');
      if (metricRaw) {
        try {
          const metric = JSON.parse(metricRaw);
          followupSubmitted = Boolean(
            metric && (
              metric.followup_completed === true ||
              metric.followup === 'completed'
            )
          );
        } catch (error) {
          followupSubmitted = false;
        }
      }

      if (followupSubmitted) {
        markFollowupCompletedFallback();
        shouldRefresh = true;
      }

      if (!shouldRefresh) {
        return { refreshed: false, followupSubmitted: followupSubmitted };
      }

      await requestPlanRefresh('legacy_marker', { followupSubmitted: followupSubmitted });
      return { refreshed: true, followupSubmitted: followupSubmitted };
    } finally {
      localStorage.removeItem('metric_data');
      localStorage.removeItem('refresh_flag');
    }
  }

  function setUnreadBadge(count) {
    UNREAD_CHAT_COUNT = count;
    const badge = document.getElementById('unread-badge');
    if (!badge) {
      return;
    }
    if (count > 0) {
      badge.style.display = 'inline-block';
      badge.textContent = count > 99 ? '99+' : String(count);
    } else {
      badge.style.display = 'none';
    }
  }

  function fetchUnreadCount() {
    if (!IS_MEMBER || !URLS.chatUnreadCount) {
      return;
    }

    LAST_UNREAD_FETCH_AT = Date.now();

    const badge = document.getElementById('unread-badge');
    if (badge) {
      badge.classList.add('animate-pulse');
    }

    fetch(URLS.chatUnreadCount)
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        if (data && data.status === 'success' && typeof data.count === 'number') {
          setUnreadBadge(data.count);
        }
      })
      .catch(function () {})
      .finally(function () {
        if (badge) {
          badge.classList.remove('animate-pulse');
        }
      });
  }

  function reportHomePerf(event) {
    if (HOME_PERF_REPORTED && !(event && event.persisted)) {
      return;
    }
    HOME_PERF_REPORTED = true;

    if (!window.performance || typeof window.performance.now !== 'function') {
      return;
    }

    const payload = {
      pageshow_ms: Math.round(window.performance.now()),
      persisted: Boolean(event && event.persisted)
    };

    const navEntry = (window.performance.getEntriesByType('navigation') || [])[0];
    if (navEntry && typeof navEntry.startTime === 'number') {
      payload.navigation_start_ms = Math.round(navEntry.startTime);
    }

    const paintEntries = window.performance.getEntriesByType('paint') || [];
    paintEntries.forEach(function (entry) {
      if (entry.name === 'first-paint') {
        payload.first_paint_ms = Math.round(entry.startTime);
      }
      if (entry.name === 'first-contentful-paint') {
        payload.first_contentful_paint_ms = Math.round(entry.startTime);
      }
    });

    if (typeof console !== 'undefined' && typeof console.info === 'function') {
      console.info('[patient_home_perf]', payload);
    }
  }

  async function handleHomePageShow(event) {
    reportHomePerf(event);
    const markerResult = await consumeRefreshMarkersAndSync();

    const historyRestored = isHistoryRestore(event);
    const shouldRefreshPlans = !markerResult.refreshed;
    const isUnreadExpired = Date.now() - LAST_UNREAD_FETCH_AT > UNREAD_REFRESH_INTERVAL_MS;
    HOME_PAGE_WAS_HIDDEN = false;

    if (shouldRefreshPlans) {
      await requestPlanRefresh('pageshow', { followupSubmitted: markerResult.followupSubmitted, force: true });
    }

    if (historyRestored || isUnreadExpired) {
      fetchUnreadCount();
    }
  }

  function handleHomePageHide() {
    HOME_PAGE_WAS_HIDDEN = true;
  }

  function handleHomeBeforeUnload() {
    HOME_PAGE_WAS_HIDDEN = true;
  }

  function handleHomeVisibilityChange() {
    if (document.visibilityState === 'hidden') {
      HOME_PAGE_WAS_HIDDEN = true;
      return;
    }

    if (document.visibilityState === 'visible') {
      requestPlanRefresh('visibilitychange', {});
    }
  }

  function handleConsultationEntry(event) {
    const href = event && event.currentTarget
      ? event.currentTarget.getAttribute('href')
      : '';

    if (!IS_MEMBER) {
      return handleMemberOnlyNavigation(event);
    }

    if (!href) {
      return false;
    }

    if (event) {
      event.preventDefault();
    }

    const hadUnread = UNREAD_CHAT_COUNT > 0;
    if (hadUnread) {
      setUnreadBadge(0);
      LAST_UNREAD_FETCH_AT = Date.now();
    }

    if (hadUnread && URLS.chatResetUnread) {
      const controller = new AbortController();
      const timeout = setTimeout(function () {
        controller.abort();
      }, 1500);

      fetch(URLS.chatResetUnread, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': CSRF_TOKEN
        },
        signal: controller.signal
      })
        .then(function () {
          setUnreadBadge(0);
          LAST_UNREAD_FETCH_AT = Date.now();
        })
        .catch(function () {})
        .finally(function () {
          clearTimeout(timeout);
          window.location.href = href;
        });
      return false;
    }

    window.location.href = href;
    return false;
  }

  window.addEventListener('pageshow', handleHomePageShow);
  window.addEventListener('pagehide', handleHomePageHide);
  window.addEventListener('beforeunload', handleHomeBeforeUnload);
  document.addEventListener('visibilitychange', handleHomeVisibilityChange);
  document.addEventListener('click', handleHomeTaskAction);

  window.showMemberOnlyModal = showMemberOnlyModal;
  window.closeMemberOnlyModal = closeMemberOnlyModal;
  window.confirmMemberOnlyModal = confirmMemberOnlyModal;
  window.handleMemberOnlyNavigation = handleMemberOnlyNavigation;
  window.openMedicationModal = openMedicationModal;
  window.closeMedicationModal = closeMedicationModal;
  window.submitMedication = submitMedication;
  window.handleConsultationEntry = handleConsultationEntry;
  window.writeHomePlanRefreshMarker = writeHomePlanRefreshMarker;
})();

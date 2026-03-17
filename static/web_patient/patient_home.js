(function () {
  'use strict';

  if (window.__PATIENT_HOME_BOOTED__) {
    return;
  }
  window.__PATIENT_HOME_BOOTED__ = true;

  const config = window.__PATIENT_HOME_CONFIG__ || {};
  const IS_MEMBER = Boolean(config.isMember);
  const BUY_URL = config.buyUrl || '';
  const PATIENT_ID = config.patientId || '';
  const MENU_URLS = config.menuUrl || {};
  const URLS = config.urls || {};
  const CSRF_TOKEN = config.csrfToken || '';
  const UNREAD_REFRESH_INTERVAL_MS = Number(config.unreadRefreshIntervalMs || 15000);

  let UNREAD_CHAT_COUNT = parseInt(config.unreadChatCount, 10) || 0;
  let MEMBER_ONLY_REDIRECT_URL = BUY_URL;
  let LAST_UNREAD_FETCH_AT = Date.now();
  let HOME_PERF_REPORTED = false;

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

  function handleTaskClick(title, type, specificUrl) {
    if (!IS_MEMBER) {
      showMemberOnlyModal('该功能为会员专属，请先开通会员', BUY_URL);
      return;
    }

    if ((title || '').includes('用药提醒')) {
      openMedicationModal();
      return;
    }

    const fallbackUrl = MENU_URLS[type];
    const urlBase = specificUrl || fallbackUrl;

    if (!urlBase) {
      console.error('未找到对应类型的跳转链接:', type);
      return;
    }

    const separator = urlBase.includes('?') ? '&' : '?';
    let finalUrl = urlBase + separator + 'patient_id=' + encodeURIComponent(PATIENT_ID);

    if (type === 'checkup') {
      const sep2 = finalUrl.includes('?') ? '&' : '?';
      finalUrl = finalUrl + sep2 + 'source=home';
    }

    window.location.href = finalUrl;
  }

  const PLAN_ACTION_BUTTON_CLASS = 'bg-white border border-slate-200 text-slate-600 text-sm font-bold px-3 py-1.5 rounded-full shadow-sm hover:border-blue-400 hover:text-blue-600 active:bg-blue-50 transition whitespace-nowrap';

  function setPlanActionState(type, status, plan) {
    const actionEl = document.getElementById('plan-action-' + type);
    if (!actionEl) {
      return;
    }

    const planData = plan || {};
    if (typeof planData.title === 'string' && planData.title.length > 0) {
      actionEl.dataset.planTitle = planData.title;
    }
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
    const planTitle = actionEl.dataset.planTitle || '';
    const specificUrl = actionEl.dataset.planUrl || '';

    actionEl.innerHTML = '';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = PLAN_ACTION_BUTTON_CLASS;
    button.textContent = actionText;
    button.addEventListener('click', function () {
      handleTaskClick(planTitle, type, specificUrl);
    });
    actionEl.appendChild(button);
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

  function refreshMetricData(options) {
    if (!IS_MEMBER || !URLS.queryLastMetric) {
      return Promise.resolve();
    }

    return fetch(URLS.queryLastMetric)
      .then(function (response) {
        return response.json();
      })
      .then(function (data) {
        if (data.success) {
          updateMetricDisplay(data.plans || {}, options || {});
        }
      })
      .catch(function (error) {
        console.error('Error refreshing metrics:', error);
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
  }

  async function consumeRefreshMarkersAndSync() {
    let shouldRefresh = false;
    let followupSubmitted = false;

    try {
      const checkupFlag = localStorage.getItem('checkup_all_completed');
      if (checkupFlag === 'true') {
        setPlanCardState('checkup', 'completed', '已完成复查任务');
        shouldRefresh = true;
      } else if (checkupFlag === 'false') {
        setPlanCardState('checkup', 'pending', '请及时完成您的复查任务');
        shouldRefresh = true;
      }

      if (checkupFlag !== null) {
        localStorage.removeItem('checkup_all_completed');
      }

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
        return;
      }

      await refreshMetricData({ followupSubmitted: followupSubmitted });
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
    await consumeRefreshMarkersAndSync();

    const isBfCacheRestore = Boolean(event && event.persisted === true);
    const isUnreadExpired = Date.now() - LAST_UNREAD_FETCH_AT > UNREAD_REFRESH_INTERVAL_MS;

    if (isBfCacheRestore || isUnreadExpired) {
      fetchUnreadCount();
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

    if (UNREAD_CHAT_COUNT > 0 && URLS.chatResetUnread) {
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

  window.addEventListener('message', function (event) {
    const data = event.data || {};
    if (data.type === 'CHECKUP_COMPLETION_UPDATED') {
      if (data.allCompleted) {
        setPlanCardState('checkup', 'completed', '已完成复查任务');
      } else {
        setPlanCardState('checkup', 'pending', '请及时完成您的复查任务');
      }
      refreshMetricData();
    }
  });

  window.showMemberOnlyModal = showMemberOnlyModal;
  window.closeMemberOnlyModal = closeMemberOnlyModal;
  window.confirmMemberOnlyModal = confirmMemberOnlyModal;
  window.handleMemberOnlyNavigation = handleMemberOnlyNavigation;
  window.openMedicationModal = openMedicationModal;
  window.closeMedicationModal = closeMedicationModal;
  window.submitMedication = submitMedication;
  window.handleTaskClick = handleTaskClick;
  window.handleConsultationEntry = handleConsultationEntry;
})();

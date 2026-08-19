(function (window, document) {
  'use strict';

  if (window.LCCSubmitGuard) {
    return;
  }

  const inFlightRequests = new Map();
  const activeStates = new Map();
  const markerPrefix = 'lcc-submit-guard:';
  const markerTtlMs = 10 * 60 * 1000;

  function SubmitError(message, kind, payload) {
    this.name = 'SubmitError';
    this.message = message || '提交失败，请稍后重试';
    this.kind = kind || 'unknown';
    this.payload = payload || null;
  }
  SubmitError.prototype = Object.create(Error.prototype);
  SubmitError.prototype.constructor = SubmitError;

  function getPayloadMessage(payload, fallback) {
    if (payload && typeof payload === 'object') {
      return payload.message || payload.msg || payload.error || fallback;
    }
    return fallback;
  }

  async function parseJsonResponse(response) {
    const responseText = await response.text();
    let payload = null;
    let parseFailed = false;
    try {
      payload = responseText ? JSON.parse(responseText) : {};
    } catch (error) {
      parseFailed = true;
    }

    if (!response.ok) {
      const rolledBack = payload && payload.error_code === 'ROLLED_BACK';
      const rejectedBeforeBusiness = response.status === 401 || response.status === 403;
      const knownFailure = rolledBack || rejectedBeforeBusiness || (
        !parseFailed && response.status >= 400 && response.status < 500
      );
      throw new SubmitError(
        getPayloadMessage(
          payload,
          rejectedBeforeBusiness
            ? '页面校验或登录状态已失效，请刷新页面后重试'
            : knownFailure
              ? '提交失败，请检查后重试'
              : '提交结果暂未确认，请点击按钮核对任务状态'
        ),
        knownFailure ? 'failed' : 'unknown',
        payload
      );
    }

    if (parseFailed) {
      throw new SubmitError('提交结果暂未确认，请点击按钮核对任务状态', 'unknown');
    }

    return { response: response, payload: payload };
  }

  function getPageIdentity() {
    return window.location.pathname + window.location.search;
  }

  function getMarkerStorageKey(guardKey) {
    return markerPrefix + encodeURIComponent(guardKey);
  }

  function removeMarker(guardKey) {
    try {
      window.sessionStorage.removeItem(getMarkerStorageKey(guardKey));
    } catch (error) {}
  }

  function readMarker(guardKey) {
    try {
      const raw = window.sessionStorage.getItem(getMarkerStorageKey(guardKey));
      if (!raw) return null;
      const marker = JSON.parse(raw);
      if (!marker || marker.guardKey !== guardKey || marker.expiresAt <= Date.now()) {
        removeMarker(guardKey);
        return null;
      }
      return marker;
    } catch (error) {
      removeMarker(guardKey);
      return null;
    }
  }

  function normalizeVerifyUrl(verifyUrl) {
    try {
      const target = new URL(verifyUrl || window.location.href, window.location.href);
      return target.origin === window.location.origin ? target.href : window.location.href;
    } catch (error) {
      return window.location.href;
    }
  }

  function writeMarker(guardKey, button, state, unknownText, verifyUrl) {
    if (!button || !button.id) return;
    try {
      window.sessionStorage.setItem(getMarkerStorageKey(guardKey), JSON.stringify({
        guardKey: guardKey,
        buttonId: button.id,
        page: getPageIdentity(),
        state: state,
        unknownText: unknownText || '核对提交结果',
        verifyUrl: normalizeVerifyUrl(verifyUrl),
        expiresAt: Date.now() + markerTtlMs
      }));
    } catch (error) {}
  }

  function emitState(guardKey, state, button) {
    try {
      const detail = { guardKey: guardKey, state: state, button: button };
      let stateEvent;
      if (typeof window.CustomEvent === 'function') {
        stateEvent = new window.CustomEvent('lcc:submit-state', { detail: detail });
      } else {
        stateEvent = document.createEvent('CustomEvent');
        stateEvent.initCustomEvent('lcc:submit-state', false, false, detail);
      }
      window.dispatchEvent(stateEvent);
    } catch (error) {}
  }

  function buildHeaders(csrfToken, extraHeaders) {
    const headers = Object.assign(
      { 'X-Requested-With': 'XMLHttpRequest' },
      extraHeaders || {}
    );
    if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken;
    }
    return headers;
  }

  function postForm(url, formData, options) {
    const requestOptions = options || {};
    return fetch(url, {
      method: 'POST',
      headers: buildHeaders(requestOptions.csrfToken),
      body: formData
    }).then(parseJsonResponse);
  }

  function postJson(url, payload, options) {
    const requestOptions = options || {};
    return fetch(url, {
      method: 'POST',
      headers: buildHeaders(requestOptions.csrfToken, {
        'Content-Type': 'application/json'
      }),
      body: JSON.stringify(payload)
    }).then(parseJsonResponse);
  }

  function toast(message, variant) {
    const containerId = 'lcc-submit-toast-container';
    let container = document.getElementById(containerId);
    if (!container) {
      container = document.createElement('div');
      container.id = containerId;
      container.className = 'fixed top-4 left-1/2 -translate-x-1/2 z-[9999] space-y-2 w-[92vw] max-w-sm';
      document.body.appendChild(container);
    }

    const toastElement = document.createElement('div');
    const messageElement = document.createElement('span');
    const closeButton = document.createElement('button');
    const tone = variant === 'error'
      ? 'bg-red-600 text-white'
      : variant === 'success'
        ? 'bg-emerald-600 text-white'
        : 'bg-slate-900 text-white';

    toastElement.className = 'px-4 py-3 rounded-lg shadow-lg text-sm font-medium flex items-center justify-between gap-3 ' + tone;
    messageElement.className = 'leading-5';
    messageElement.textContent = String(message || '');
    closeButton.type = 'button';
    closeButton.className = 'text-white/80 hover:text-white';
    closeButton.setAttribute('aria-label', '关闭提示');
    closeButton.textContent = '×';
    closeButton.addEventListener('click', function () {
      toastElement.remove();
    });

    toastElement.appendChild(messageElement);
    toastElement.appendChild(closeButton);
    container.appendChild(toastElement);
    window.setTimeout(function () {
      toastElement.classList.add('opacity-0', 'transition', 'duration-300');
      window.setTimeout(function () {
        toastElement.remove();
      }, 320);
    }, 2600);
  }

  function captureButton(button) {
    return {
      html: button.innerHTML,
      disabled: button.disabled,
      ariaBusy: button.getAttribute('aria-busy')
    };
  }

  function restoreButton(button, original) {
    button.innerHTML = original.html;
    button.disabled = original.disabled;
    button.dataset.submitState = 'idle';
    if (original.ariaBusy === null) {
      button.removeAttribute('aria-busy');
    } else {
      button.setAttribute('aria-busy', original.ariaBusy);
    }
  }

  function setButtonState(button, state, text) {
    button.dataset.submitState = state;
    button.disabled = state !== 'unknown';
    if (state === 'submitting') {
      button.setAttribute('aria-busy', 'true');
    } else {
      button.removeAttribute('aria-busy');
    }
    button.textContent = text;
  }

  function removeUnknownVerifier(entry) {
    if (!entry || !entry.unknownHandler) return;
    entry.button.removeEventListener('click', entry.unknownHandler, true);
    entry.unknownHandler = null;
  }

  function attachUnknownVerifier(guardKey, entry, unknownText, verifyUrl) {
    if (!entry || !entry.button) return;
    removeUnknownVerifier(entry);
    entry.verifyUrl = normalizeVerifyUrl(verifyUrl || entry.verifyUrl);
    entry.unknownText = unknownText || entry.unknownText || '核对提交结果';
    setButtonState(entry.button, 'unknown', entry.unknownText);
    entry.unknownHandler = function (event) {
      if (entry.button.dataset.submitState !== 'unknown') return;
      event.preventDefault();
      event.stopImmediatePropagation();
      entry.button.disabled = true;
      entry.button.textContent = '正在前往核对...';
      removeMarker(guardKey);
      inFlightRequests.delete(guardKey);
      activeStates.delete(guardKey);
      removeUnknownVerifier(entry);
      try {
        window.location.replace(entry.verifyUrl);
      } catch (error) {
        activeStates.set(guardKey, entry);
        writeMarker(guardKey, entry.button, 'unknown', entry.unknownText, entry.verifyUrl);
        attachUnknownVerifier(guardKey, entry, entry.unknownText, entry.verifyUrl);
        toast('无法打开核对页面，请稍后重试', 'error');
      }
    };
    entry.button.addEventListener('click', entry.unknownHandler, true);
  }

  function normalizeState(state) {
    if (state === 'succeeded' || state === 'failed' || state === 'pending') {
      return state;
    }
    return 'failed';
  }

  function run(options) {
    const config = options || {};
    const key = config.guardKey;
    const button = config.button;
    if (!key || !button || typeof config.request !== 'function') {
      return Promise.reject(new Error('提交守卫缺少必要配置'));
    }
    if (inFlightRequests.has(key)) {
      return inFlightRequests.get(key);
    }

    const unresolvedMarker = readMarker(key);
    if (unresolvedMarker && unresolvedMarker.page === getPageIdentity()) {
      const unresolvedOriginal = captureButton(button);
      const unresolvedEntry = {
        button: button,
        original: unresolvedOriginal,
        status: 'unknown',
        invalidated: true,
        verifyUrl: unresolvedMarker.verifyUrl,
        unknownText: unresolvedMarker.unknownText
      };
      activeStates.set(key, unresolvedEntry);
      attachUnknownVerifier(
        key,
        unresolvedEntry,
        unresolvedMarker.unknownText,
        unresolvedMarker.verifyUrl
      );
      emitState(key, 'unknown', button);
      return Promise.resolve({
        status: 'unknown',
        error: new SubmitError('已存在结果待确认的提交，请先核对任务状态', 'unknown')
      });
    }

    const original = captureButton(button);
    const entry = {
      button: button,
      original: original,
      status: 'submitting',
      invalidated: false,
      verifyUrl: normalizeVerifyUrl(config.verifyUrl),
      unknownText: config.unknownText || '核对提交结果'
    };
    activeStates.set(key, entry);
    setButtonState(button, 'submitting', config.loadingText || '提交中...');
    writeMarker(key, button, 'submitting', entry.unknownText, entry.verifyUrl);
    emitState(key, 'submitting', button);

    const promise = Promise.resolve()
      .then(config.request)
      .then(async function (result) {
        if (entry.invalidated) {
          const staleError = new SubmitError('页面已恢复，旧提交结果不再直接应用', 'stale');
          throw staleError;
        }
        const resolveState = typeof config.getSubmissionState === 'function'
          ? config.getSubmissionState
          : function () { return 'succeeded'; };
        const transportPending = result.response && result.response.status === 202;
        const payloadPending = result.payload && result.payload.status === 'pending';
        const state = transportPending || payloadPending
          ? 'pending'
          : normalizeState(resolveState(result.response, result.payload));

        if (state === 'pending') {
          throw new SubmitError('提交结果暂未确认，请点击按钮核对任务状态', 'unknown', result.payload);
        }
        if (state === 'failed') {
          const message = typeof config.getErrorMessage === 'function'
            ? config.getErrorMessage(result.payload)
            : getPayloadMessage(result.payload, '提交失败，请检查后重试');
          throw new SubmitError(message, 'failed', result.payload);
        }

        entry.status = 'succeeded';
        removeMarker(key);
        removeUnknownVerifier(entry);
        setButtonState(button, 'succeeded', config.successText || '提交成功');
        emitState(key, 'succeeded', button);
        if (typeof config.onSuccess === 'function') {
          try {
            await config.onSuccess(result.payload, result.response);
          } catch (error) {
            console.error('Post-submit UI update failed:', error);
          }
        }
        if (config.keepDisabledOnSuccess === false) {
          restoreButton(button, original);
          activeStates.delete(key);
          emitState(key, 'idle', button);
        }
        return { status: 'succeeded', payload: result.payload };
      })
      .catch(async function (error) {
        if (error && error.kind === 'stale') {
          return { status: 'unknown', error: error };
        }
        const knownFailure = error && error.kind === 'failed';
        const message = error && error.message
          ? error.message
          : knownFailure
            ? '提交失败，请检查后重试'
            : '提交结果暂未确认，请点击按钮核对任务状态';

        if (knownFailure) {
          entry.status = 'failed';
          removeMarker(key);
          removeUnknownVerifier(entry);
          restoreButton(button, original);
          activeStates.delete(key);
          emitState(key, 'idle', button);
          toast(message, 'error');
          if (typeof config.onFailure === 'function') {
            await config.onFailure(error);
          }
          return { status: 'failed', error: error };
        }

        entry.status = 'unknown';
        attachUnknownVerifier(key, entry, entry.unknownText, entry.verifyUrl);
        writeMarker(key, button, 'unknown', entry.unknownText, entry.verifyUrl);
        emitState(key, 'unknown', button);
        toast(message, 'error');
        if (typeof config.onUnknown === 'function') {
          await config.onUnknown(error);
        }
        return { status: 'unknown', error: error };
      })
      .finally(function () {
        inFlightRequests.delete(key);
      });

    inFlightRequests.set(key, promise);
    return promise;
  }

  function reset(guardKey) {
    const entry = activeStates.get(guardKey);
    if (!entry || entry.status === 'submitting') {
      return false;
    }
    restoreButton(entry.button, entry.original);
    removeUnknownVerifier(entry);
    activeStates.delete(guardKey);
    removeMarker(guardKey);
    emitState(guardKey, 'idle', entry.button);
    return true;
  }

  function restorePersistedMarkers() {
    let keys = [];
    try {
      for (let index = 0; index < window.sessionStorage.length; index += 1) {
        const key = window.sessionStorage.key(index);
        if (key) keys.push(key);
      }
    } catch (error) {
      return;
    }

    keys.filter(function (key) {
      return key.indexOf(markerPrefix) === 0;
    }).forEach(function (storageKey) {
      let marker = null;
      try {
        marker = JSON.parse(window.sessionStorage.getItem(storageKey));
      } catch (error) {}

      if (!marker || !marker.guardKey || marker.expiresAt <= Date.now()) {
        try { window.sessionStorage.removeItem(storageKey); } catch (error) {}
        return;
      }
      if (marker.page !== getPageIdentity() || activeStates.has(marker.guardKey)) {
        return;
      }

      const button = document.getElementById(marker.buttonId);
      if (!button) {
        removeMarker(marker.guardKey);
        return;
      }
      const entry = {
        button: button,
        original: captureButton(button),
        status: 'unknown',
        invalidated: true,
        verifyUrl: marker.verifyUrl,
        unknownText: marker.unknownText
      };
      activeStates.set(marker.guardKey, entry);
      attachUnknownVerifier(marker.guardKey, entry, marker.unknownText, marker.verifyUrl);
      emitState(marker.guardKey, 'unknown', button);
    });
  }

  window.addEventListener('pageshow', function (event) {
    if (!event.persisted) {
      return;
    }
    inFlightRequests.clear();
    activeStates.forEach(function (entry, guardKey) {
      if (entry.status === 'submitting') {
        entry.invalidated = true;
        entry.status = 'unknown';
        attachUnknownVerifier(guardKey, entry, entry.unknownText, entry.verifyUrl);
        writeMarker(guardKey, entry.button, 'unknown', entry.unknownText, entry.verifyUrl);
        emitState(guardKey, 'unknown', entry.button);
      } else if (entry.status === 'succeeded') {
        removeUnknownVerifier(entry);
        restoreButton(entry.button, entry.original);
        activeStates.delete(guardKey);
        removeMarker(guardKey);
        emitState(guardKey, 'idle', entry.button);
      }
    });
    restorePersistedMarkers();
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', restorePersistedMarkers, { once: true });
  } else {
    restorePersistedMarkers();
  }

  window.LCCSubmitGuard = {
    run: run,
    postForm: postForm,
    postJson: postJson,
    toast: toast,
    reset: reset
  };
})(window, document);

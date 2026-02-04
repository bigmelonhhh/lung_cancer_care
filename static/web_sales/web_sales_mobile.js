(function () {
  if (window.__webSalesMobileBound) return;
  window.__webSalesMobileBound = true;

  var root = document.documentElement;
  root.dataset.wsTouch = '1';

  var EDGE_OPEN_PX = 20;
  var TRIGGER_DX = 70;
  var TRIGGER_DY = 30;

  function isEditableTarget(target) {
    if (!target) return false;
    var tag = target.tagName;
    return (
      tag === 'INPUT' ||
      tag === 'TEXTAREA' ||
      tag === 'SELECT' ||
      target.isContentEditable
    );
  }

  function dispatch(name) {
    window.dispatchEvent(new CustomEvent(name));
  }

  function bindSwipeOpenSidebar() {
    var tracking = null;

    function onStart(ev) {
      if (ev.isPrimary === false) return;
      if (isEditableTarget(ev.target)) return;

      var point = ev.touches ? ev.touches[0] : ev;
      if (!point) return;

      if (point.clientX > EDGE_OPEN_PX) return;
      tracking = { x: point.clientX, y: point.clientY, fired: false };
    }

    function onMove(ev) {
      if (!tracking || tracking.fired) return;
      var point = ev.touches ? ev.touches[0] : ev;
      if (!point) return;

      var dx = point.clientX - tracking.x;
      var dy = point.clientY - tracking.y;
      if (Math.abs(dy) > TRIGGER_DY && Math.abs(dy) > Math.abs(dx)) return;
      if (dx < TRIGGER_DX) return;

      tracking.fired = true;
      dispatch('ws-open-sidebar');
    }

    function onEnd() {
      tracking = null;
    }

    if (window.PointerEvent) {
      document.addEventListener('pointerdown', onStart, { passive: true });
      document.addEventListener('pointermove', onMove, { passive: true });
      document.addEventListener('pointerup', onEnd, { passive: true });
      document.addEventListener('pointercancel', onEnd, { passive: true });
    } else {
      document.addEventListener('touchstart', onStart, { passive: true });
      document.addEventListener('touchmove', onMove, { passive: true });
      document.addEventListener('touchend', onEnd, { passive: true });
      document.addEventListener('touchcancel', onEnd, { passive: true });
    }
  }

  function bindSwipeCloseSidebar() {
    var tracking = null;

    function resolveSidebarEl(target) {
      if (!target) return null;
      if (target.closest) return target.closest('[data-ws-sidebar]');
      return null;
    }

    function onStart(ev) {
      if (ev.isPrimary === false) return;
      if (isEditableTarget(ev.target)) return;
      var sidebar = resolveSidebarEl(ev.target);
      if (!sidebar) return;
      var point = ev.touches ? ev.touches[0] : ev;
      if (!point) return;
      tracking = { x: point.clientX, y: point.clientY, fired: false };
    }

    function onMove(ev) {
      if (!tracking || tracking.fired) return;
      var point = ev.touches ? ev.touches[0] : ev;
      if (!point) return;
      var dx = point.clientX - tracking.x;
      var dy = point.clientY - tracking.y;
      if (Math.abs(dy) > TRIGGER_DY && Math.abs(dy) > Math.abs(dx)) return;
      if (dx > -TRIGGER_DX) return;
      tracking.fired = true;
      dispatch('ws-close-sidebar');
    }

    function onEnd() {
      tracking = null;
    }

    if (window.PointerEvent) {
      document.addEventListener('pointerdown', onStart, { passive: true });
      document.addEventListener('pointermove', onMove, { passive: true });
      document.addEventListener('pointerup', onEnd, { passive: true });
      document.addEventListener('pointercancel', onEnd, { passive: true });
    } else {
      document.addEventListener('touchstart', onStart, { passive: true });
      document.addEventListener('touchmove', onMove, { passive: true });
      document.addEventListener('touchend', onEnd, { passive: true });
      document.addEventListener('touchcancel', onEnd, { passive: true });
    }
  }

  function bindSwipeBack() {
    var main = document.getElementById('main-content-area');
    if (!main) return;

    var tracking = null;

    function onStart(ev) {
      if (ev.isPrimary === false) return;
      if (isEditableTarget(ev.target)) return;
      var point = ev.touches ? ev.touches[0] : ev;
      if (!point) return;
      if (point.clientX > EDGE_OPEN_PX) return;
      tracking = { x: point.clientX, y: point.clientY, fired: false };
    }

    function onMove(ev) {
      if (!tracking || tracking.fired) return;
      var point = ev.touches ? ev.touches[0] : ev;
      if (!point) return;
      var dx = point.clientX - tracking.x;
      var dy = point.clientY - tracking.y;
      if (Math.abs(dy) > TRIGGER_DY && Math.abs(dy) > Math.abs(dx)) return;
      if (dx < TRIGGER_DX) return;
      tracking.fired = true;
      if (typeof window.webSalesGoBackToDashboard === 'function') {
        window.webSalesGoBackToDashboard();
      }
    }

    function onEnd() {
      tracking = null;
    }

    if (window.PointerEvent) {
      main.addEventListener('pointerdown', onStart, { passive: true });
      main.addEventListener('pointermove', onMove, { passive: true });
      main.addEventListener('pointerup', onEnd, { passive: true });
      main.addEventListener('pointercancel', onEnd, { passive: true });
    } else {
      main.addEventListener('touchstart', onStart, { passive: true });
      main.addEventListener('touchmove', onMove, { passive: true });
      main.addEventListener('touchend', onEnd, { passive: true });
      main.addEventListener('touchcancel', onEnd, { passive: true });
    }
  }

  bindSwipeOpenSidebar();
  bindSwipeCloseSidebar();

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bindSwipeBack, { once: true });
  } else {
    bindSwipeBack();
  }
})();
